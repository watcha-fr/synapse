# -*- coding: utf-8 -*-

import logging

from twisted.internet import defer

from synapse.api.constants import EventTypes
from synapse.api.errors import SynapseError
from ._base import BaseHandler
from synapse.util.watcha import generate_password, send_mail

import base64

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
    def gen_user_id_from_email(
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

        full_user_id = yield self.hs.auth_handler.find_user_id_by_email(invitee)

        if full_user_id:
            logger.info("Invitee with email %s already exists (id is %s), inviting her to room %s",
                        invitee, full_user_id, room_id)

            user = UserID.from_string(full_user_id)
            yield self.hs.get_handlers().room_member_handler.update_membership(
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
        else:
            user_id = self.gen_user_id_from_email(invitee)
            logger.info("invited user %s is not in the DB. Creating user (id is %s), inviting to room and sending invitation email.",
                        invitee, user_id)

            # note about server names:
            # self.hs.hostname is self.hs.get_config().server_name - the core's server
            # self.hs.get_config().public_baseurl.rstrip('/') is the public URL - riot's

            full_user_id = UserID(user_id, self.hs.hostname).to_string()
            user_password = generate_password()

            try:
                new_user_id, token = yield self.hs.get_handlers().registration_handler.register(
                    localpart=user_id,
                    password=user_password,
                    generate_token=True,
                    guest_access_token=None,
                    make_guest=False,
                    admin=False,
                    make_partner=True,
                )

                yield self.hs.auth_handler.set_email(full_user_id, invitee)

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
                    logger.info("registration error={0}", detail)
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
        
        logger.info("Generating message: invitation_name=%s invitee=%s user_id=%s user_pw=<REDACTED> new_user=%s server=%s",
                    invitation_name, invitee, user_id, new_user, self.hs.get_config().server_name);

        server = self.hs.config.public_baseurl.rstrip('/')
        setupToken = base64.b64encode('{{"user":"{user_id}","pw":"{user_password}"}}'.format(user_id=user_id, user_password=user_password))
        outToken = base64.b64encode('{{"user":"{user_id}"}}'.format(user_id=user_id))
        subject = u'''Accès à l'espace de travail sécurisé {server}'''.format(server=server)

        fields = {
                'title': subject,
                'inviter_name': invitation_name,
                'user_login': user_id,
                'setupToken': setupToken, # only used if new_user, in fact
                'outToken': outToken, # only used if existing user, in fact
                'server': server,
        }

        send_mail(
            self.hs.config,
            invitee,
            subject=subject,
            template_name='invite_new_account' if new_user else 'invite_existing_account',
            fields=fields,
        )

        defer.returnValue(full_user_id)
