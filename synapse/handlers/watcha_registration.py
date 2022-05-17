import logging
import uuid
from typing import Optional

from jsonschema.exceptions import SchemaError, ValidationError

from synapse.api.errors import HttpResponseException, NextcloudError, SynapseError
from synapse.config.emailconfig import ThreepidBehaviour
from synapse.push.mailer import Mailer
from synapse.util.watcha import ActionStatus, Secrets, build_log_message

logger = logging.getLogger(__name__)


class RegistrationHandler:
    def __init__(self, hs):
        self.hs = hs
        self.config = hs.config
        self.auth_handler = hs.get_auth_handler()
        self.registration_handler = hs.get_registration_handler()
        self.user_directory_handler = hs.get_user_directory_handler()
        self.store = hs.get_datastore()
        self.keycloak_client = hs.get_keycloak_client()
        self.nextcloud_client = hs.get_nextcloud_client()
        self.secrets = Secrets()

        if hs.config.email.threepid_behaviour_email == ThreepidBehaviour.LOCAL:
            self.mailer = Mailer(
                hs=hs,
                app_name=hs.config.email.email_app_name,
                template_html=hs.config.email.watcha_registration_template_html,
                template_text=hs.config.email.watcha_registration_template_text,
            )

    async def register(
        self,
        sender_id: str,
        email_address: str,
        password: Optional[str] = None,
        is_partner: Optional[bool] = False,
        is_admin: Optional[bool] = False,
        default_display_name: Optional[str] = None,
    ):
        """Registers a new user on the server.

        Args:
            sender_id: The mxid of the user who invite.
            email_address: The invitee email address.
            password: The invitee password.
            is_partner: True if the user should be registered as a partner.
            is_admin: True if the user should be registered as a server admin.
            default_display_name: If set, the new user's displayname will be set to this. Defaults to 'email_address'.

        Returns:
            user_id: the mxid of the new user
        """
        if await self.store.get_user_id_by_threepid("email", email_address):
            raise SynapseError(
                400,
                build_log_message(
                    action="check if email is available",
                    log_vars={
                        "email_address": email_address,
                    },
                ),
            )

        password = self.secrets.gen_password()
        password_hash = await self.auth_handler.hash(password)

        if default_display_name is None:
            default_display_name = email_address

        register_kc_user = self.config.watcha.managed_idp and (
            not is_partner or self.config.watcha.external_authentication_for_partners
        )

        register_nc_user = (
            self.config.watcha.managed_idp
            and self.config.watcha.nextcloud_integration
            and (
                not is_partner
                or self.config.watcha.external_authentication_for_partners
            )
        )

        if register_kc_user:
            response = await self.keycloak_client.add_user(
                password_hash, email_address, is_admin
            )
            location = response.headers.getRawHeaders("location")[0]
            localpart = location.split("/")[-1]
            local_password_hash = None
        else:
            localpart = str(uuid.uuid4())
            local_password_hash = password_hash

        if register_nc_user:
            try:
                await self.nextcloud_client.add_user(localpart, default_display_name)
            except:
                if register_kc_user:
                    await self.keycloak_client.delete_user(localpart)
                raise

        try:
            user_id = await self.registration_handler.register_user(
                localpart=localpart,
                password_hash=local_password_hash,
                admin=is_admin,
                default_display_name=default_display_name,
                bind_emails=[email_address],
                make_partner=is_partner,
            )
        except SynapseError:
            if register_kc_user:
                await self.keycloak_client.delete_user(localpart)
            if register_nc_user:
                await self.nextcloud_client.delete_user(localpart)
            raise

        if is_partner:
            await self.store.add_partner_invitation(
                sender_id=sender_id,
                partner_id=user_id,
            )

        if self.hs.config.userdirectory.user_directory_search_all_users:
            profile = await self.store.get_profileinfo(localpart)
            await self.user_directory_handler.handle_local_profile_change(
                user_id, profile
            )

        await self.mailer.send_watcha_registration_mail(
            sender_id=sender_id,
            email_address=email_address,
            password=password,
            is_partner=is_partner,
        )

        logger.info(build_log_message(status=ActionStatus.SUCCESS))

        return user_id
