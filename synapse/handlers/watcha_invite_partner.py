import logging

from ._base import BaseHandler
from secrets import token_hex
from synapse.config.emailconfig import ThreepidBehaviour
from synapse.push.mailer import Mailer
from synapse.types import map_username_to_mxid_localpart

logger = logging.getLogger(__name__)


class InvitePartnerHandler(BaseHandler):
    def __init__(self, hs):
        super().__init__(hs)
        self.config = hs.config
        self.auth_handler = self.hs.get_auth_handler()
        self.nextcloud_handler = self.hs.get_nextcloud_handler()
        self.registration_handler = self.hs.get_registration_handler()
        self.room_handler = self.hs.get_room_member_handler()

        if self.config.threepid_behaviour_email == ThreepidBehaviour.LOCAL:
            self.mailer = Mailer(
                hs=self.hs,
                app_name=self.config.email_app_name,
                template_html=self.config.watcha_registration_template_html,
                template_text=self.config.watcha_registration_template_text,
            )

    async def invite(self, room_id, host_id, host_device_id, invitee_email):

        user_id = await self.auth_handler.find_user_id_by_email(invitee_email)
        email_sent = False

        if user_id:
            logger.info(
                "Invitee with email {email} already exists (id is {user_id}), inviting her to room {room_id}".format(
                    email=invitee_email,
                    user_id=user_id,
                    room_id=room_id,
                )
            )
        else:
            localpart = map_username_to_mxid_localpart(invitee_email)
            logger.info(
                "invited user {} is not in the DB. Creating user (id is {}), inviting to room and sending invitation email.".format(
                    invitee_email,
                    localpart,
                )
            )

            password = token_hex(6)
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
                host_id=host_id,
                password=password,
            )

            email_sent = True
        
        await self.store.insert_partner_invitation(
            partner_user_id=user_id,
            inviter_user_id=host_id,
            inviter_device_id=host_device_id,
            email_sent=email_sent,
        )

        return user_id
