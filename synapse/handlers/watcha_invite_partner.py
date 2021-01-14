import logging

from ._base import BaseHandler
from synapse.api.errors import SynapseError
from synapse.config.emailconfig import ThreepidBehaviour
from synapse.push.mailer import Mailer
from synapse.types import map_username_to_mxid_localpart
from synapse.util.threepids import canonicalise_email

logger = logging.getLogger(__name__)


class InvitePartnerHandler(BaseHandler):
    def __init__(self, hs):
        super().__init__(hs)
        self.auth_handler = hs.get_auth_handler()
        self.nextcloud_handler = hs.get_nextcloud_handler()
        self.registration_handler = hs.get_registration_handler()
        self.room_handler = hs.get_room_member_handler()
        self.secret = hs.get_secrets()

        if hs.config.threepid_behaviour_email == ThreepidBehaviour.LOCAL:
            self.mailer = Mailer(
                hs=hs,
                app_name=hs.config.email_app_name,
                template_html=hs.config.watcha_registration_template_html,
                template_text=hs.config.watcha_registration_template_text,
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
            localpart = map_username_to_mxid_localpart(invitee_email)
            password = self.secret.token_hex(6)
            password_hash = await self.auth_handler.hash(password)

            await self.nextcloud_handler.create_keycloak_and_nextcloud_user(
                invitee_email, password_hash, "partner"
            )

            user_id = await self.registration_handler.register_user(
                localpart=localpart,
                bind_emails=[invitee_email],
                make_partner=True,
            )

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
