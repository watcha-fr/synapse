import logging
import re  # watcha+
import uuid
from typing import Optional, TYPE_CHECKING

from synapse.api.errors import HttpResponseException, SynapseError  # watcha+
""" watcha!
from synapse.config.emailconfig import ThreepidBehaviour
!watcha"""
from synapse.push.mailer import Mailer
from synapse.util.watcha import (
    ActionStatus,
    Secrets,
    build_log_message,
    email_domain_matches,  # watcha+
)
from synapse.util.watcha_user_log import UserAuditAction, append_user_audit_log # watcha+
from synapse.types import UserID # watcha+

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
        self.pusher_pool = hs.get_pusherpool() # watcha+
        self.secrets = Secrets()

        """ watcha!
        if hs.config.email.threepid_behaviour_email == ThreepidBehaviour.LOCAL:
        !watcha"""
        self.mailer = None # watcha+ : évite un AttributeError si l'email n'est pas configuré
        if hs.config.email.can_verify_email: # watcha+
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
        localpart_id: Optional[str] = None,
        # watcha+ `register_kc_user` used to be a parameter here, but it was
        # unconditionally reassigned from the configuration a few lines below
        # before ever being read: dead code, removed. No caller passed it.
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

        # watcha+
        # Un invité marqué partenaire mais dont l'adresse relève d'un domaine de
        # l'organisation est enregistré comme membre de plein droit. Piloté par
        # `watcha.partner_email_whitelist`, vide par défaut.
        if is_partner and email_domain_matches(
            email_address, self.config.watcha.partner_email_whitelist
        ):
            is_partner = False
        # +watcha

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

        # watcha+
        # Nom lisible du compte Nextcloud. L'UUID reste le pivot d'identité ;
        # ce nom vient à côté, pour que l'espace documentaire soit exploitable.
        nextcloud_username = await self._derive_nextcloud_username(email_address)
        # +watcha

        if register_kc_user:
            try:
                response = await self.keycloak_client.add_user(
                    password_hash,
                    email_address,
                    is_partner,  # watcha+
                    is_admin,
                    keycloak_username,
                    keycloak_as_broker,
                    nextcloud_username,  # watcha+
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
        elif localpart_id:
            localpart=localpart_id
            local_password_hash = None
        else:
            localpart = str(uuid.uuid4())
            local_password_hash = password_hash

        # watcha+
        # A deactivated account keeps its localpart forever, so registering it
        # again fails with "User ID already taken" and the whole invitation
        # errors out. Bring the existing account back instead: this is what
        # keeps an address that once had an account invitable.
        user_id = UserID(localpart, self.hs.hostname).to_string()
        existing_user = await self.store.get_user_by_id(user_id)

        # Un compte déjà connu garde le nom Nextcloud enregistré : en dériver un
        # nouveau lui fabriquerait un second compte à côté du sien.
        if existing_user is not None:
            nextcloud_username = (
                await self.store.get_username(user_id) or nextcloud_username
            )
        # +watcha

        # watcha+
        # Same single implementation as the SSO path. The name provisioned here
        # is the one recorded in the mapping below, so the two agree by
        # construction — unlike the SSO path, where they were rendered from two
        # independent templates and could diverge.
        if register_nc_user:
            await self.hs.get_nextcloud_handler().provision_account(
                nextcloud_username=nextcloud_username,
                displayname=default_display_name,
                email=email_address,
                is_admin=bool(is_admin),
                is_partner=bool(is_partner),
            )
        # +watcha

        """ watcha!
        user_id = await self.registration_handler.register_user(
            localpart=localpart,
            password_hash=local_password_hash,
            admin=is_admin,
            default_display_name=default_display_name,
            bind_emails=[email_address],
            make_partner=is_partner,
        )
        !watcha """
        # watcha+
        if existing_user is not None:
            await self._reactivate_account(
                user_id,
                existing_user,
                email_address,
                default_display_name,
                is_partner,
                is_admin,
            )
            send_registration_mail = False
        else:
            user_id = await self.registration_handler.register_user(
                localpart=localpart,
                password_hash=local_password_hash,
                admin=is_admin,
                default_display_name=default_display_name,
                bind_emails=[email_address],
                make_partner=is_partner,
            )
        # +watcha

        """ watcha!
        if register_kc_user:
        !watcha """
        # The mapping already exists on a reactivated account, and recording it
        # twice raises ExternalIDReuseException.
        if register_kc_user and existing_user is None:  # watcha+
            idp_ids = list(self.hs.get_oidc_handler()._providers)
            idp_id = idp_ids[0] if len(idp_ids) == 1 else "nextcloud"
            await self.store.record_user_external_id(
                idp_id,
                localpart,
                user_id,
                nextcloud_username,  # watcha+ : le nom lisible, plus l'UUID
            )

        if is_partner:
            await self.store.add_partner_invitation(
                sender_id=sender_id,
                partner_id=user_id,
            )

        if self.hs.config.userdirectory.user_directory_search_all_users:
            """watcha!
            profile = await self.store.get_profileinfo(localpart)
            !watcha"""
            profile = await self.store.get_profileinfo(UserID.from_string(user_id)) # watcha+
            await self.user_directory_handler.handle_local_profile_change(
                user_id, profile
            )

        if send_registration_mail and self.mailer is not None: # watcha+ : mailer None si email non configuré
            await self.mailer.send_watcha_registration_mail(
                sender_id=sender_id,
                email_address=email_address,
                password=password,
                is_partner=is_partner,
            )

        logger.info(build_log_message(status=ActionStatus.SUCCESS))

        append_user_audit_log(
            self.config.watcha.user_audit_log_path,
            user_id=user_id,
            display_name=default_display_name,
            action=(
                UserAuditAction.REACTIVATE  # watcha+
                if existing_user is not None  # watcha+
                else UserAuditAction.CREATE
            ),
        )

        return user_id

    # watcha+
    async def _derive_nextcloud_username(self, email_address: str) -> str:
        """A readable Nextcloud name derived from the address, deduplicated.

        `jean.dupont@example.com` gives `jean.dupont`, then `jean.dupont2` if
        that one is already mapped to someone.
        """

        base = re.sub(
            r"[^a-z0-9._-]", "", email_address.split("@")[0].lower()
        ) or "user"

        candidate = base
        suffix = 1
        while await self.store.is_nextcloud_username_taken(candidate):
            suffix += 1
            candidate = f"{base}{suffix}"

        return candidate

    async def provision_external_accounts(
        self,
        user_id: str,
        localpart: str,
        email_address: Optional[str],
        password_hash: Optional[str],
        displayname: Optional[str],
        is_admin: bool = False,
    ) -> None:
        """Give an already registered Synapse account its Keycloak and Nextcloud
        counterparts.

        Used by the admin API, whose accounts were until now created in Synapse
        only. Unlike `register()`, the Synapse account already exists and keeps
        the localpart the administrator chose: the Keycloak UUID is recorded as
        the external id, which the login path resolves on its own, so the two
        need not be equal.

        Does nothing on an instance without a managed identity provider.
        """

        if not self.config.watcha.managed_idp:
            return

        if not email_address:
            raise SynapseError(
                400,
                build_log_message(
                    action="check that an email address is set",
                    log_vars={"user_id": user_id},
                ),
            )

        try:
            response = await self.keycloak_client.add_user(
                password_hash,
                email_address,
                False,
                is_admin,
                localpart,
                # Sans mot de passe, ne pas poser de bloc d'identifiants :
                # `add_user` y écrirait la chaîne « None » comme secret.
                keycloak_as_broker=password_hash is None,
                # Le localpart choisi par l'administrateur est déjà lisible :
                # c'est lui que porte le compte Nextcloud.
                nextcloud_username=localpart,
            )
            keycloak_id = response.headers.getRawHeaders("location")[0].split("/")[-1]
        except HttpResponseException as error:
            if error.code != 409:
                raise
            keycloak_user = await self.keycloak_client.get_user_by_email(email_address)
            keycloak_id = keycloak_user["id"]

        if (
            self.config.watcha.nextcloud_integration
            and self.config.watcha.managed_idp
        ):
            await self.hs.get_nextcloud_handler().provision_account(
                nextcloud_username=localpart,
                displayname=displayname or localpart,
                email=email_address,
                is_admin=is_admin,
                is_partner=False,
            )

        idp_ids = list(self.hs.get_oidc_handler()._providers)
        idp_id = idp_ids[0] if len(idp_ids) == 1 else "nextcloud"
        await self.store.record_user_external_id(
            idp_id,
            keycloak_id,
            user_id,
            localpart,
        )

        logger.info(
            build_log_message(
                status=ActionStatus.SUCCESS,
                log_vars={"user_id": user_id, "keycloak_id": keycloak_id},
            )
        )

    async def _reactivate_account(
        self,
        user_id: str,
        existing_user,
        email_address: str,
        default_display_name: str,
        is_partner: bool,
        is_admin: bool,
    ):
        """Bring back an account that already holds this localpart.

        Reactivating also unlocks the Keycloak and Nextcloud accounts, so the
        person comes back under the identity they already had.
        """

        if existing_user.is_deactivated:
            await self.hs.get_deactivate_account_handler().activate_account(user_id)

        # The role carried by this invitation wins over the one the account had
        # before it was deactivated.
        if is_admin:
            role = "administrator"
        elif is_partner:
            role = "partner"
        else:
            role = "collaborator"
        await self.store.update_user_role(user_id, role)

        threepids = await self.store.user_get_threepids(user_id)
        if not any(
            threepid.medium == "email" and threepid.address == email_address
            for threepid in threepids
        ):
            now = self.hs.get_clock().time_msec()
            await self.store.user_add_threepid(
                user_id, "email", email_address, now, now
            )

        # Erasing the account cleared the profile.
        await self.store.set_profile_displayname(
            UserID.from_string(user_id), default_display_name
        )

        logger.info(
            build_log_message(
                status=ActionStatus.SUCCESS,
                log_vars={"user_id": user_id, "email_address": email_address},
            )
        )
    # +watcha
