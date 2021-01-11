import logging

from ._base import BaseHandler
from jsonschema.exceptions import ValidationError, SchemaError

from synapse.api.errors import SynapseError, HttpResponseException
from synapse.config.emailconfig import ThreepidBehaviour
from synapse.push.mailer import Mailer
from synapse.util.watcha import Secrets

logger = logging.getLogger(__name__)


class InvitePartnerHandler(BaseHandler):
    def __init__(self, hs):
        super().__init__(hs)
        self.config = hs.config
        self.auth_handler = hs.get_auth_handler()
        self.registration_handler = self.hs.get_registration_handler()
        self.store = hs.get_datastore()
        self.keycloak_client = hs.get_keycloak_client()
        self.nextcloud_client = hs.get_nextcloud_client()
        self.secrets = Secrets(hs.config.word_list_path)

        if self.config.threepid_behaviour_email == ThreepidBehaviour.LOCAL:
            self.mailer = Mailer(
                hs=hs,
                app_name=self.config.email_app_name,
                template_html=self.config.watcha_registration_template_html,
                template_text=self.config.watcha_registration_template_text,
            )

    async def invite(self, room_id, sender_id, sender_device_id, invitee_email):

        user_id = await self.auth_handler.find_user_id_by_email(invitee_email)
        invitee_email = invitee_email.strip()
        email_sent = False

        if user_id:
            logger.info(
                "Partner with email {email} already exists. His id is {user_id}. Inviting him to room {room_id}".format(
                    email=invitee_email,
                    user_id=user_id,
                    room_id=room_id,
                )
            )
        else:
            password = self.secrets.passphrase()
            password_hash = await self.auth_handler.hash(password)
            response = await self.keycloak_client.add_user(password_hash, invitee_email)

            location = response.headers.getRawHeaders('location')[0]
            keycloak_user_id = location.split("/")[-1]
            try:
                await self.nextcloud_client.add_user(keycloak_user_id)
            except (SynapseError, HttpResponseException, ValidationError, SchemaError):
                await self.keycloak_client.delete_user(keycloak_user_id)
                raise

            try:
                user_id = await self.registration_handler.register_user(
                    localpart=keycloak_user_id,
                    default_display_name="",
                    bind_emails=[invitee_email],
                    make_partner=True,
                )
            except SynapseError:
                await self.keycloak_client.delete_user(keycloak_user_id)
                await self.nextcloud_client.delete_user(keycloak_user_id)
                raise

            await self.mailer.send_watcha_registration_email(
                email_address=invitee_email,
                sender_id=sender_id,
                password=password,
            )

            email_sent = True
            logger.info(
                "New partner with id {user_id} was created and an email has been sent to {email}. Inviting him to room {room_id}.".format(
                    user_id=user_id,
                    email=invitee_email,
                    room_id=room_id,
                )
            )

        await self.store.insert_partner_invitation(
            partner_user_id=user_id,
            inviter_user_id=sender_id,
            inviter_device_id=sender_device_id,
            email_sent=email_sent,
        )

        return user_id
