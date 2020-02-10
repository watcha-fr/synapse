# -*- coding: utf-8 -*-

import logging

from twisted.internet import defer

from synapse.api.constants import EventTypes
from synapse.api.errors import SynapseError
from ._base import BaseHandler
from synapse.util.watcha import generate_password, send_registration_email, compute_registration_token
from synapse.types import UserID, create_requester
from synapse.api.constants import Membership

logger = logging.getLogger(__name__)

class InviteExternalHandler(BaseHandler):

    # from room_id and user ID, get details about who invites and where.
    # adapted from synapse/handlers/room_member.py
    @defer.inlineCallbacks
    def _get_invitation_info(
        self,
        room_id,
        inviter,
    ):
        room_state = yield self.hs.get_state_handler().get_current_state(room_id)

        inviter_display_name = ""
        inviter_avatar_url = ""
        member_event = room_state.get((EventTypes.Member, inviter.to_string()))
        if member_event:
            inviter_display_name = member_event.content.get("displayname", "")
            inviter_avatar_url = member_event.content.get("avatar_url", "")
            logger.debug(u"inviter: display_name=%s avatar_url=%s", inviter_display_name, inviter_avatar_url)

        room_canonical_alias = ""
        canonical_alias_event = room_state.get((EventTypes.CanonicalAlias, ""))
        if canonical_alias_event:
            room_canonical_alias = canonical_alias_event.content.get("alias", "")
            logger.debug(u"room: canonical_alias=%s", room_canonical_alias)

        room_name = ""
        room_name_event = room_state.get((EventTypes.Name, ""))
        if room_name_event:
            room_name = room_name_event.content.get("name", "")
            logger.debug(u"room: name=%s", room_name)

        room_join_rules = ""
        join_rules_event = room_state.get((EventTypes.JoinRules, ""))
        if join_rules_event:
            room_join_rules = join_rules_event.content.get("join_rule", "")
            logger.debug(u"room: join_rules=%s", room_join_rules)

        room_avatar_url = ""
        room_avatar_event = room_state.get((EventTypes.RoomAvatar, ""))
        if room_avatar_event:
            room_avatar_url = room_avatar_event.content.get("url", "")

        result = {
            "inviter_id": inviter.to_string(),
            "inviter_display_name":inviter_display_name,
            "inviter_avatar_url":inviter_avatar_url,
            "room_canonical_alias":room_canonical_alias,
            "room_name":room_name,
            "room_join_rules":room_join_rules,
            "room_avatar_url":room_avatar_url
        }

        defer.returnValue(result)

    # convert an email address into a user_id in a deterministic way
    def _gen_user_id_from_email(
        self,
        email
    ):
        # user_id must be lowercase (and it's OK to consider email as case-insensitive)
        local_part, domain = email.lower().split("@")
        user_id = local_part + "/" + domain
        logger.debug("gen_user_id_from_email: email=%s leads to user_id=%s", email, user_id)
        return user_id

    @defer.inlineCallbacks
    def invite(
        self,
        room_id,
        inviter,
        inviter_device_id,
        invitee
    ):

        full_user_id = yield self.hs.get_auth_handler().find_user_id_by_email(invitee)

        # the user already exists. it is an internal user or an external user.
        if full_user_id:
            logger.info("Invitee with email %s already exists (id is %s), inviting her to room %s",
                        invitee, full_user_id, room_id)

            user = UserID.from_string(full_user_id)
            yield self.hs.get_room_member_handler().update_membership(
                requester=create_requester(inviter.to_string()),
                target=user,
                room_id=room_id,
                action=Membership.INVITE,
                txn_id=None,
                third_party_signed=None,
                content=None,
            )

            user_id = user.localpart
            new_user = False

            # TODO: This is probably very wrong !
            # there is no reason to have a different behaviour for partner ??
            
            # only send email if that user is external.
            # this restriction can be removed once internal users will also receive notifications from invitations by user ID.
            is_partner = yield self.hs.get_auth_handler().is_partner(full_user_id)
            if not is_partner:
                logger.info("Invitee is an internal user. Do not send a notification email.")
                defer.returnValue(full_user_id)

        # the user does not exist. we create an account
        else:
            user_id = self._gen_user_id_from_email(invitee)
            logger.info("invited user %s is not in the DB. Creating user (id is %s), inviting to room and sending invitation email.",
                        invitee, user_id)

            full_user_id = UserID(user_id, self.hs.hostname).to_string()
            user_password = generate_password()

            try:
                yield self.hs.get_registration_handler().register(
                    localpart=user_id,
                    password=user_password,
                    generate_token=True,
                    guest_access_token=None,
                    make_guest=False,
                    admin=False,
                    make_partner=True,
                )

                yield self.hs.get_auth_handler().set_email(full_user_id, invitee)

                """
                # we save the account type
                result = yield self.store.set_partner(
                user_id,
                self.store.EXTERNAL_RESTRICTED_USER
                )
                logger.info("set partner account result=" + str(result))
                """
                new_user = True
            except SynapseError as detail:
                # user already exists as external user
                # (maybe this code is useless since adding a check for email; but leaving it for now)
                if str(detail) == "400: User ID already taken.":
                    logger.info("invited user is already in the DB. Not modified. Will send a notification by email.")
                    new_user = False
                else:
                    logger.info("registration error=%s", detail)
                    raise SynapseError(
                        400,
                        "Registration error: {0}".format(detail)
                    )


        # log invitation in DB
        yield self.store.insert_partner_invitation(
            partner_user_id=full_user_id,
            inviter_user_id=inviter,
            inviter_device_id=inviter_device_id,
            email_sent=True
        )

        invitation_info = yield self._get_invitation_info(
            room_id,
            inviter
        )

        if (invitation_info["inviter_display_name"] is not None):
            invitation_name = u''.join((invitation_info["inviter_display_name"], ' (', invitation_info["inviter_id"], ')'))
        else:
            invitation_name = invitation_info["inviter_id"]

        logger.info("Generating message: invitation_name=%s invitee=%s user_id=%s user_pw=<REDACTED> new_user=%s",
                    invitation_name, invitee, user_id, new_user);

        if new_user:
            token = compute_registration_token(user_id, user_password)
            template_name = 'invite_new_account'
        else:
            token = compute_registration_token(user_id)
            template_name = 'invite_existing_account'
            
        send_registration_email(
            self.hs.config,
            invitee,
            template_name=template_name,
            token=token,
            user_login=user_id,
            inviter_name=invitation_name
        )

        defer.returnValue(full_user_id)
