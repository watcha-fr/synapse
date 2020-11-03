from binascii import b2a_hex
import logging
import re

from twisted.internet import defer

from synapse.api.constants import Membership
from synapse.api.errors import SynapseError
from synapse.types import UserID, create_requester
from synapse.util.watcha import (
    compute_registration_token,
    create_display_inviter_name,
    generate_password,
    send_registration_email,
)

from ._base import BaseHandler

logger = logging.getLogger(__name__)


class InvitePartnerHandler(BaseHandler):
    async def invite(self, room_id, inviter, inviter_device_id, invitee):

        user_id = await self.hs.get_auth_handler().find_user_id_by_email(invitee)

        # the user already exists. it is an internal user or an external user.
        if user_id:
            logger.info(
                "Invitee with email %s already exists (id is %s), inviting her to room %s",
                invitee,
                user_id,
                room_id,
            )

            user = UserID.from_string(user_id)
            await self.hs.get_room_member_handler().update_membership(
                requester=create_requester(inviter.to_string()),
                target=user,
                room_id=room_id,
                action=Membership.INVITE,
                txn_id=None,
                third_party_signed=None,
                content=None,
            )

            localpart = user.localpart
            new_user = False

            # TODO: This is probably very wrong !
            # there is no reason to have a different behaviour for partner ??

            # only send email if that user is external.
            # this restriction can be removed once internal users will also receive notifications from invitations by user ID.
            is_partner = await self.hs.get_auth_handler().is_partner(user_id)
            if not is_partner:
                logger.info(
                    "Invitee is an internal user. Do not send a notification email."
                )
                defer.returnValue(user_id)

        # the user does not exist. we create an account
        else:
            localpart = self._gen_localpart_from_email(invitee)
            logger.info(
                "invited user %s is not in the DB. Creating user (id is %s), inviting to room and sending invitation email.",
                invitee,
                localpart,
            )

            user_id = UserID(localpart, self.hs.hostname).to_string()
            password = generate_password()
            password_hash = await self.hs.get_auth_handler().hash(password)

            try:
                await self.hs.get_registration_handler().register_user(
                    localpart=localpart,
                    password_hash=password_hash,
                    guest_access_token=None,
                    make_guest=False,
                    admin=False,
                    make_partner=True,
                    bind_emails=[invitee],
                )
                new_user = True
            except SynapseError as detail:
                # user already exists as external user
                # (maybe this code is useless since adding a check for email; but leaving it for now)
                if str(detail) == "400: User ID already taken.":
                    logger.info(
                        "invited user is already in the DB. Not modified. Will send a notification by email."
                    )
                    new_user = False
                else:
                    logger.info("registration error=%s", detail)
                    raise SynapseError(400, "Registration error: {0}".format(detail))

        # log invitation in DB
        await self.store.insert_partner_invitation(
            partner_user_id=user_id,
            inviter_user_id=inviter,
            inviter_device_id=inviter_device_id,
            email_sent=True,
        )

        inviter_name = await create_display_inviter_name(self.hs, inviter)

        logger.info(
            "Generating message: invitation_name=%s invitee=%s localpart=%s new_user=%s",
            inviter_name,
            invitee,
            localpart,
            new_user,
        )

        if new_user:
            token = compute_registration_token(localpart, invitee, password)
            template_name = "invite_new_account"
        else:
            token = compute_registration_token(localpart, invitee)
            template_name = "invite_existing_account"

        await send_registration_email(
            self.hs.config,
            invitee,
            template_name=template_name,
            token=token,
            inviter_name=inviter_name,
            full_name=None,
        )

        return user_id

    def _gen_localpart_from_email(self, email):
        # https://matrix.org/docs/spec/appendices#id14
        lowered = email.lower()
        escaped = lowered.replace("=", "==")
        return re.sub(
            r"[^\w.=/-]", self._encode_forbidden_char, escaped, flags=re.ASCII
        )

    def _encode_forbidden_char(self, match):
        bin_char = match.group(0).encode()
        hex_char = b2a_hex(bin_char).decode()
        return re.sub(r"(..)", r"=\1", hex_char)
