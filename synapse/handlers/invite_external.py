# -*- coding: utf-8 -*-

import logging

from twisted.internet import defer

from synapse.api.constants import EventTypes
from synapse.api.errors import SynapseError
from ._base import BaseHandler
from synapse.util.watcha import generate_password, send_mail
import base64

#
# TODO: merge this code with synapse/rest/client/v1/watcha.py
#
# In the meantime, changing the URLs to the mobile apps must be done in BOTH places
#
logger = logging.getLogger(__name__)

EMAIL_SUBJECT_FR = u'''Accès à l'espace de travail sécurisé {server}'''
NEW_USER_EMAIL_MESSAGE_FR = u'''Bonjour,

{inviter_name} vous a invité à participer à l'espace de travail sécurisé Watcha {server}.

Votre nom d’utilisateur est :

    {user_id}

Cliquez sur ce lien pour activer votre compte :

    https://{server}/setup-account.html?t={setupToken}

Nous pouvons vous aider à utiliser Watcha. Si vous rencontrez des difficultés, n'hésitez pas à répondre à cet email !

L'équipe Watcha.
'''

# those links will be put in the setup-account.html page, alongside the deep link.
'''
Vous pouvez accéder à l’espace de travail à partir d’un navigateur sur :

    https://{server}

Vous pouvez aussi installer l'application mobile :

    - iOS : https://itunes.apple.com/us/app/watcha/id1383732254
    - Android : https://play.google.com/store/apps/details?id=im.watcha.app
'''


# TODO: put deep link here
EXISTING_USER_EMAIL_MESSAGE_FR = u'''Bonjour,

{inviter_name} vous a invité à participer à un espace de travail sécurisé Watcha.

Votre nom d’utilisateur est :

    {user_id}

et votre mot de passe est celui que vous avez défini lors de l'activation de votre compte sur cet espace de travail.

Vous pouvez accéder à l’espace de travail à partir d’un navigateur sur :

    https://{server}

Vous pouvez aussi installer l'application mobile :

    - iOS : https://itunes.apple.com/us/app/watcha/id1383732254
    - Android : https://play.google.com/store/apps/details?id=im.watcha.app

Nous pouvons vous aider à utiliser Watcha. Si vous rencontrez des difficultés ou si vous avez perdu votre mot de passe, n'hésitez pas à répondre à cet email !

L'équipe Watcha.
'''


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
            logger.debug("inviter: display_name={0} avatar_url={1}", inviter_display_name, inviter_avatar_url)

        room_canonical_alias = ""
        canonical_alias_event = room_state.get((EventTypes.CanonicalAlias, ""))
        if canonical_alias_event:
            room_canonical_alias = canonical_alias_event.content.get("alias", "")
            logger.debug("room: canonical_alias={0}", room_canonical_alias)

        room_name = ""
        room_name_event = room_state.get((EventTypes.Name, ""))
        if room_name_event:
            room_name = room_name_event.content.get("name", "")
            logger.debug("room: name={0}", room_name)

        room_join_rules = ""
        join_rules_event = room_state.get((EventTypes.JoinRules, ""))
        if join_rules_event:
            room_join_rules = join_rules_event.content.get("join_rule", "")
            logger.debug("room: join_rules={0}", room_join_rules)

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
        email_split = email.split("@")
        local_part = email_split[0]
        domain = email_split[1]
        user_id = local_part + "/" + domain
        logger.debug("gen_user_id_from_email: email={0} leads to user_id={1}", email, user_id)
        return local_part + "/" + domain

    @defer.inlineCallbacks
    def invite(
        self,
        room_id,
        inviter,
        inviter_device_id,
        invitee
    ):

        user_id = self.gen_user_id_from_email(invitee)

        # note about server names:
        # self.hs.get_config().server_name is of the format SERVER-core.watcha.fr
        # self.hs.get_config().public_baseurl.rstrip('/') is of the format SERVER.watcha.fr

        full_user_id = "@" + user_id + ":" + self.hs.get_config().server_name
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
            logger.info("invited user is not in the DB. Will send an invitation email.")

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
        result = yield self.store.insert_partner_invitation(
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

        logger.info("will generate message: invitation_name=%s invitee=%s user_id=%s user_pw=<REDACTED> new_user=%s server=%s",
                    invitation_name, invitee, user_id, new_user, self.hs.get_config().server_name);

        setupToken = base64.b64encode('{"user":"' + user_id + '","pw":"' + user_password + '"}')

        send_mail(self.hs.config, invitee,
                  EMAIL_SUBJECT_FR,
                  (NEW_USER_EMAIL_MESSAGE_FR if new_user else EXISTING_USER_EMAIL_MESSAGE_FR),
                  inviter_name=invitation_name,
                  user_id=user_id,
                  setupToken=setupToken, # only used if new_user, in fact
                  server=self.hs.get_config().server_name)

        defer.returnValue(full_user_id)
