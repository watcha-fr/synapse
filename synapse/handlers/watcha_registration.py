import logging
import uuid
from typing import Optional, TYPE_CHECKING

from synapse.api.errors import HttpResponseException
from synapse.config.emailconfig import ThreepidBehaviour
from synapse.push.mailer import Mailer
from synapse.util.watcha import ActionStatus, Secrets, build_log_message

if TYPE_CHECKING:
    from synapse.server import HomeServer

logger = logging.getLogger(__name__)


class RegistrationHandler:
    def __init__(self, hs: "HomeServer"):
        self.hs = hs
        self.config = hs.config
        self.auth_handler = hs.get_auth_handler()
        self.registration_handler = hs.get_registration_handler()
        self.user_directory_handler = hs.get_user_directory_handler()
        self.store = hs.get_datastores().main
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
        is_partner: Optional[bool] = False,
        is_admin: Optional[bool] = False,
        default_display_name: Optional[str] = None,
        keycloak_username: Optional[str] = None,
        keycloak_as_broker: Optional[bool] = False,
    ):
        """Registers a new user on the server.

        Args:
            sender_id: The mxid of the user who invite.
            email_address: The invitee email address.
            is_partner: True if the user should be registered as a partner.
            is_admin: True if the user should be registered as a server admin.
            default_display_name: If set, the new user's displayname will be set to this. Defaults to 'email_address'.

        Returns:
            user_id: the mxid of the new user
        """

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

        send_registration_mail = is_partner or register_kc_user and not keycloak_as_broker

        if register_kc_user:
            try:
                response = await self.keycloak_client.add_user(
                    password_hash,
                    email_address,
                    is_admin,
                    keycloak_username,
                    keycloak_as_broker,
                )
                location = response.headers.getRawHeaders("location")[0]
                localpart = location.split("/")[-1]
            except HttpResponseException as error:
                if error.code == 409: # user already exists
                    send_registration_mail = False
                    kc_user = await self.keycloak_client.get_user_by_email(
                        email_address
                    )
                    localpart = kc_user["id"]
                else:
                    raise
            local_password_hash = None
        else:
            localpart = str(uuid.uuid4())
            local_password_hash = password_hash

        if register_nc_user:
            await self.nextcloud_client.add_user(
                localpart, default_display_name, email_address, is_admin
            )

        user_id = await self.registration_handler.register_user(
            localpart=localpart,
            password_hash=local_password_hash,
            admin=is_admin,
            default_display_name=default_display_name,
            bind_emails=[email_address],
            make_partner=is_partner,
        )

        if register_kc_user:
            idp_ids = list(self.hs.get_oidc_handler()._providers)
            idp_id = idp_ids[0] if len(idp_ids) == 1 else "nextcloud"
            await self.store.record_user_external_id(
                idp_id,
                localpart,
                user_id,
                localpart,
            )

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

        if send_registration_mail:
            await self.mailer.send_watcha_registration_mail(
                sender_id=sender_id,
                email_address=email_address,
                password=password,
                is_partner=is_partner,
            )

        logger.info(build_log_message(status=ActionStatus.SUCCESS))

        return user_id
