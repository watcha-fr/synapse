import logging

from jsonschema.exceptions import SchemaError, ValidationError

from synapse.api.errors import HttpResponseException, SynapseError
from synapse.config.emailconfig import ThreepidBehaviour
from synapse.push.mailer import Mailer
from synapse.util.watcha import Secrets

from ._base import BaseHandler

logger = logging.getLogger(__name__)


class PartnerHandler(BaseHandler):
    def __init__(self, hs):
        super().__init__(hs)
        self.auth_handler = hs.get_auth_handler()
        self.registration_handler = hs.get_registration_handler()
        self.keycloak_client = hs.get_keycloak_client()
        self.nextcloud_client = hs.get_nextcloud_client()
        self.secrets = Secrets(hs.config.word_list_path)

        if hs.config.threepid_behaviour_email == ThreepidBehaviour.LOCAL:
            self.mailer = Mailer(
                hs=hs,
                app_name=hs.config.email_app_name,
                template_html=hs.config.watcha_registration_template_html,
                template_text=hs.config.watcha_registration_template_text,
            )

    async def register_partner(self, sender_id, invitee_email):
        """Register a new partner on the Keycloak, Nextcloud and Synapse server

        Args:
            sender_id: the user mxid of sender
            invitee_email: the invitee email

        Returns:
            invitee_id: the mxid of the new partner
        """
        password = self.secrets.passphrase()
        password_hash = await self.auth_handler.hash(password)
        response = await self.keycloak_client.add_user(password_hash, invitee_email)

        location = response.headers.getRawHeaders("location")[0]
        keycloak_user_id = location.split("/")[-1]

        try:
            await self.nextcloud_client.add_user(keycloak_user_id)
        except (SynapseError, HttpResponseException, ValidationError, SchemaError):
            await self.keycloak_client.delete_user(keycloak_user_id)
            raise

        invitee_id = await self.registration_handler.register_user(
            localpart=keycloak_user_id,
            default_display_name=invitee_email,
            bind_emails=[invitee_email],
            make_partner=True,
        )

        logger.info("[watcha] create new partner - success")

        await self.mailer.send_watcha_registration_email(
            email_address=invitee_email,
            sender_id=sender_id,
            password=password,
        )

        return invitee_id
