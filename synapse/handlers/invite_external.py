# -*- coding: utf-8 -*-

import logging
import random
import os

from smtplib import SMTP
from email.mime.text import MIMEText
from email.header import Header
from twisted.internet import defer

import synapse.types
from synapse.api.constants import (
    EventTypes, Membership,
)
from synapse.api.errors import AuthError, SynapseError, Codes
from synapse.types import UserID, RoomID
from synapse.util.async import Linearizer
from synapse.util.distributor import user_left_room, user_joined_room
from ._base import BaseHandler
# To enable diceware, add to REQUIREMENTS in python_dependencies.py:
#     "diceware>=0.9.3": ["diceware"],
#import diceware # only needed if diceware password generation is enabled

#
# TODO: merge with code in scripts/register_watcha_users !
#


logger = logging.getLogger(__name__)

def generate_password():
    '''Generate 'good enough' password

    password strength target: 1000 years of computation with 8 GTX 1080 cards.
    hash algorithm is bcrypt, so hash speed is 105khash/s
        (according to https://gist.github.com/epixoip/a83d38f412b4737e99bbef804a270c40)
        log(1000 years * 105 khash/s) / log(2) = 51.6 bits of entropy.

        first method: diceware password generation. you need to enable the diceware dependency.
        the file 'wordlist_fr_5d.txt' is needed in ~/.synapse/lib/python2.7/site-packages/diceware/wordlists
        the wordlist_fr_5d provides ~12.9bits of entropy per word
        cf https://github.com/mbelivo/diceware-wordlists-fr
        four words of 12.9 bits of entropy gives a password of 51.6 bits.
        password = diceware.get_passphrase(diceware.handle_options(["-w", "fr_5d", "-n", "4", "-d", " ", "--no-caps"]))

        alternate method: generate groups of random characters:
        * lowercase alphanumeric characters
          log(36)/log(2) = 5.17 bits / character. therefore, we need at least 10 characters.
          dictionary = "abcdefghijklmnopqrstuvwxyz0123456789"
        * lowercase and uppercase alphanumeric characters: log(62)/log(2) = 5.95 bits / character
        * lowercase characters:
          log(26)/log(2) = 4.7 bits / character. therefore, we need at least 11 characters.

        here we use 12 random lowercase characters, in 3 groups of 4 characters.
    '''
    dictionary = "abcdefghijklmnopqrstuvwxyz"
    grouplen = 4
    password = "".join(random.sample(dictionary, grouplen) + ["-"] + random.sample(dictionary, grouplen) + ["-"] + random.sample(dictionary, grouplen))

    return password


# TODO use a templating engine
EMAIL_SUBJECT_FR = u'''Accès à l'espace de travail sécurisé {server}'''
NEW_USER_EMAIL_MESSAGE_FR = u'''Bonjour,

{inviter_name} vous a invité à participer à un espace de travail sécurisé Watcha.

Votre nom d’utilisateur est :

    {user_id}

et votre mot de passe :

    {user_password}

Vous pouvez accéder à l’espace de travail à partir d’un navigateur sur :

    https://{server}

Vous pouvez aussi installer l'application mobile Android :

    https://play.google.com/store/apps/details?id=im.watcha

N’hésitez pas à répondre à cet email si vous avez des difficultés à utiliser Watcha,


L'équipe Watcha.
'''

EXISTING_USER_EMAIL_MESSAGE_FR = u'''Bonjour,

{inviter_name} vous a invité à participer à un espace de travail sécurisé Watcha.

Votre nom d’utilisateur est :

    {user_id}

et votre mot de passe est celui qui vous avait été adressé à votre première invitation sur cet espace de travail.

Vous pouvez accéder à l’espace de travail à partir d’un navigateur sur :

    https://{server}

Vous pouvez aussi installer l'application mobile Android :

    https://play.google.com/store/apps/details?id=im.watcha

N’hésitez pas à répondre à cet email si vous avez des difficultés à utiliser Watcha,


L'équipe Watcha.
'''


def _generate_message(
        inviter_name,
        invitee_email,
        user_id,
        user_password,
        server,
        new_user,
        email_from,
        locale="FR"
):
    subject_template = None
    message_template = None

    if new_user:
        if locale=="FR":
            subject_template = EMAIL_SUBJECT_FR
            message_template = NEW_USER_EMAIL_MESSAGE_FR
        else:
            raise SynapseError(
                400,
                "Locale not supported"
            )

        subject = subject_template.format(**{
            'server': server
        })

        message = message_template.format(**{
            'inviter_name': inviter_name,
            'invitee_email': invitee_email,
            'user_id': user_id,
            'user_password': user_password,
            'server': server,
        })

    else:
        if locale=="FR":
            subject_template = EMAIL_SUBJECT_FR
            message_template = EXISTING_USER_EMAIL_MESSAGE_FR
        else:
            raise SynapseError(
                400,
                "Locale not supported"
            )

        subject = subject_template.format(**{
            'server': server
        })

        message = message_template.format(**{
            'inviter_name': inviter_name,
            'invitee_email': invitee_email,
            'user_id': user_id,
            'server': server,
        })

    msg = MIMEText(message, "plain", "utf8")
    #msg['Subject'] = subject
    msg['Subject'] = Header(subject, 'utf-8', 200)
    # line above sets the parameter maxlinelen https://docs.python.org/2.7/library/email.header.html
    # setting a high-enough value helps avoid glitches in the subject line (space added every 40-50 characters),
    # when executed with Python 2.7.
    #
    # Semi-relevant online discussions:
    # https://stackoverflow.com/questions/25671608/python-mail-puts-unaccounted-space-in-outlook-subject-line
    # https://bugs.python.org/issue1974

    msg['From'] = email_from
    msg['To'] = invitee_email

    # if needed to customize the reply-to field
    # msg['Reply-To'] = EMAIL_SETTINGS['reply_to']
    #logger.info(msg.as_string())
    return msg

class InviteExternalHandler(BaseHandler):

    def __init__(self, hs):
        super(InviteExternalHandler, self).__init__(hs)

        # gather email settings in an object
        self.email_settings = {
            'smtphost': hs.config.email_smtp_host,
            'from_addr': hs.config.email_notif_from,
            'port': hs.config.email_smtp_port,
            'username': hs.config.email_smtp_user,
            'password': hs.config.email_smtp_pass,
            'requireAuthentication': True,
            'requireTransportSecurity': hs.config.require_transport_security
        }
        self.public_baseurl = hs.config.public_baseurl

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
            if (inviter_display_name is not None):
                logger.debug(u''.join(("inviter: display_name=", inviter_display_name)))
            if (inviter_avatar_url is not None):
                logger.debug("avatar_url=" + str(inviter_avatar_url))

        room_canonical_alias = ""
        canonical_alias_event = room_state.get((EventTypes.CanonicalAlias, ""))
        if canonical_alias_event:
            room_canonical_alias = canonical_alias_event.content.get("alias", "")
            logger.debug("room: canonical_alias=" + str(room_canonical_alias))

        room_name = ""
        room_name_event = room_state.get((EventTypes.Name, ""))
        if room_name_event:
            room_name = room_name_event.content.get("name", "")
            logger.debug("room: name=" + str(room_name))

        room_join_rules = ""
        join_rules_event = room_state.get((EventTypes.JoinRules, ""))
        if join_rules_event:
            room_join_rules = join_rules_event.content.get("join_rule", "")
            logger.debug("room: join_rules=" + str(room_join_rules))

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
        logger.debug("gen_user_id_from_email: email=" + str(email) + " leads to user_id=" + str(user_id))
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
        user_password = generate_password()
        server = self.hs.get_config().server_name

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
                # the generated password above will not be sent in the email notification.
            else:
                logger.info("registration error: " + str(detail))
                raise SynapseError(
                    400,
                    "Registration error: " + str(detail)
                )


        # log invitation in DB
        result = yield self.store.insert_partner_invitation(
            partner_user_id="@" + user_id + ":" + server,
            inviter_user_id=inviter,
            inviter_device_id=inviter_device_id,
            email_sent=True
        )

        invitation_info = yield self._get_invitation_info(
            room_id,
            inviter
        )

        # the contents of the invitation email
        if (invitation_info["inviter_display_name"] is not None):
            invitation_name = u''.join((invitation_info["inviter_display_name"], ' (', invitation_info["inviter_id"], ')'))
        else:
            invitation_name = invitation_info["inviter_id"]

        logger.info("will generate message: invitation_name=%s invitee_email=%s user_id=%s user_pw=<REDACTED> new_user=%s server=%s" % (invitation_name, invitee, user_id, new_user, server));

        msg = _generate_message(
            inviter_name=invitation_name,
            invitee_email=invitee,
            user_id=user_id,
            user_password=user_password, # in case of an existing user, the user_password is not in the template because irrelevant.
            new_user=new_user,
            server=self.public_baseurl,
            email_from=self.email_settings['from_addr'],
            locale="FR"
        )

        logger.info("send email through host " + self.email_settings['smtphost'])
        try:
            conn = SMTP(self.email_settings['smtphost'], port=self.email_settings['port'])
            conn.ehlo()
            conn.starttls()  # enable TLS
            conn.ehlo()
            conn.set_debuglevel(False)
            conn.login(self.email_settings['username'], self.email_settings['password'])
            conn.sendmail(self.email_settings['from_addr'], [invitee], msg.as_string())
            logger.info("registration mail sent to %s" % invitee )
        except Exception, exc:
            logger.warn("failed to send registration mail: %s" % str(exc) )
        finally:
            conn.quit()

        defer.returnValue("@" + user_id + ":" + server)
