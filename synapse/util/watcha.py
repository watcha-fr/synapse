# -*- coding: utf-8 -*-


import random
import logging
import os
import re
import base64
from os.path import join, dirname, abspath
from pathlib import Path

from jinja2 import Environment, FileSystemLoader
from smtplib import SMTP
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.header import Header

from twisted.internet import defer

from synapse.api.errors import SynapseError

logger = logging.getLogger(__name__)

# must be defined at package loading time,
# because synctl start's demonizer is changing the abspath...
TEMPLATE_DIR = join(dirname(abspath(__file__)), "watcha_templates")


def generate_password():
    """Generate 'good enough' password

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
    """
    dictionary = "abcdefghijklmnopqrstuvwxyz"
    grouplen = 4
    password = "".join(
        random.sample(dictionary, grouplen)
        + ["-"]
        + random.sample(dictionary, grouplen)
        + ["-"]
        + random.sample(dictionary, grouplen)
    )

    return password


def compute_registration_token(user, email=None, password=None):
    """Returns a (weakly encrypted) token that can be passed in a URL or in a JSON for temporaly login
    This cannot be strongly encrypted, because it will be decoded in Riot (in javascript).
    """
    if password is None and email is None:
        json = '{{"user":"{user}"}}'.format(user=user)
    elif password is None:
        json = '{{"user":"{user}", "email":"{email}"}}'.format(
            user=user, email=email
        )
    else:
        json = '{{"user":"{user}", "email":"{email}", "pw":"{password}"}}'.format(
            user=user, email=email, password=password
        )
    return base64.b64encode(json.encode("utf-8")).decode("ascii")

# additional email we send to, when not sending to a mail gun
# (to keep a copy of the received emails)
BCC_TO='registration+sent@watcha.fr'

@defer.inlineCallbacks
def create_display_inviter_name(hs, inviter):

    # TODO: Test why was:
    # inviter_room_state = yield hs.get_state_handler().get_current_state(room_id)
    # inviter_member_event = inviter_room_state.get((EventTypes.Member, inviter.to_string()))
    # inviter_display_name = inviter_member_event.content.get("displayname", "") if inviter_member_event else ""
    # instead of:
    # inviter_display_name = yield hs.get_profile_handler().get_displayname(inviter)
    # which seems to work too..
    inviter_display_name = yield hs.get_profile_handler().get_displayname(inviter)
    inviter_threepids = yield hs.get_datastore().user_get_threepids(inviter.to_string())
    inviter_emails = [ threepid["address"] for threepid in inviter_threepids if threepid["medium"] == "email"]
    inviter_email = inviter_emails[0] if inviter_emails else ""
    inviter_name = (
        (
            inviter_display_name
            + (
                (" (" + inviter_email + ")")
                if inviter_email
                else ""
            )
        )
        if inviter_display_name
        else inviter_email
    )
    defer.returnValue(inviter_name)


def send_registration_email(
    config, recipient, template_name, token, inviter_name, full_name
):
    """
    Sends email related to user registration (invitation, reset password...)

    The templates can use the 'inviter_name', 'full_name', 'email', 'server', 'title',
    'login_url', and 'setup_account_url' variables.
    The 'title' will be created from the subject.

    This method should only be used in a Matrix APIs,
    i.e. called in the code of an HTTP end point, as it raises a SynapseError on error,
    and such errors are only handled correctly in endpoints (ie. passed back as 403 error)"""

    fields = {
        "inviter_name": inviter_name,
        "full_name": full_name,
        "email": recipient,
        # legacy for polypus... was installed with an incorrect server name, and it can't be changed after install,
        # so correcting it here... (see also devops.git/prod/install.sh)
        "server": "polypus.watcha.fr" if "polypus-core.watcha.fr" in config.server_name else config.server_name,
        "login_url": "%s/#/login/t=%s" % (config.email_riot_base_url, token),
        "setup_account_url": "%s/setup-account.html?t=%s" % (
            config.email_riot_base_url,
            token,
        ),
    }

    jinjaenv = Environment(loader=FileSystemLoader(TEMPLATE_DIR))

    jinjaenv.filters.update({
        # Overwrite existing 'striptags' filter, to make it keep EOLs:
        # EOLs are significant in our templates for text emails,
        # they define the presentation and should be changed with care !
        'striptags': lambda text: re.sub('<.*?>', '', text).replace('&nbsp;', ' '),
        # prevent "xxx.com"-like strings to become links in HTML mail clients
        'preventlinks': lambda text: text.replace(
            ".", "<a class=\"prevent-link\" href=\"#\">.</a>"
        ),
        'spacebefore': lambda text: (" " + text) if text else "",        
        'b64content': lambda file_name: base64.b64encode(
            Path(TEMPLATE_DIR, file_name).read_bytes()
        ).decode()
    })
    
    subject = jinjaenv.get_template(template_name + "_subject.j2").render(fields)
    fields["title"] = subject

    message = MIMEMultipart("alternative")
    message["From"] = config.email_notif_from
    message["To"] = recipient
    # maxlinelen to workaround https://bugs.python.org/issue1974, maybe not needed anymore
    message["Subject"] = Header(subject, "utf-8", 200)

    for mimetype in [ "plain", "html" ]:
        fields["mimetype"] = mimetype
        body = jinjaenv.get_template(template_name + ".j2").render(fields)
        # suggested by https://www.htmlemailcheck.com/check/
        # (as well as ".ExternalClass" in the CSS)
        body = body.replace('<div>', '<div style="mso-line-height-rule:exactly;">') 
       
        message.attach(MIMEText(body, mimetype, "utf-8"))
        # useful for debugging...
        #Path("/tmp", f"{template_name}.{mimetype}").write_text(body)

    # if needed to customize the reply-to field
    # message['Reply-To'] = ...

    if not config.email_smtp_host:
        # (used in multipe tests, including tests.rest.client.test_identity.IdentityTestCase.test_3pid_lookup_disabled: just skip it)
        logger.error("Cannot send email, SMTP host not defined in config")
        return

    recipients = [ recipient ]
    if not any(domain in config.email_smtp_host for domain in ['mailgun.org', 'sendinblue.com']):
        recipients += BCC_TO

    if config.email_smtp_host == "TEST":
        # Used in tests only
        logger.info(
            "NOT Sending registration email to '%s', we are in test mode", recipient
        )
        logger.info("Email subject is: " + subject)
        logger.info("Email text content follows:")
        logger.info(str(base64.b64decode(message.get_payload()[0].get_payload())))
        return

    if not config.email_riot_base_url:
        logger.error("Cannot send email, riot_base_url not defined in config")
        return

    logger.info(
        "Sending email to '%s' through host %s...", recipient, config.email_smtp_host
    )
    connection = None
    try:
        connection = SMTP(
            config.email_smtp_host, port=config.email_smtp_port, timeout=10
        )  # putting a short timeout to avoid client erroring before server
        connection.ehlo()
        connection.starttls()  # enable TLS
        connection.ehlo()
        connection.set_debuglevel(False)
        connection.login(config.email_smtp_user, config.email_smtp_pass)
        connection.sendmail(
            config.email_notif_from, recipients, message.as_string()
        )
        logger.info("...email sent to %s (subject was: %s)", recipient, subject)
    except Exception as exc:
        message = "failed to send email: " + str(exc)
        logger.exception("..." + message)
        raise SynapseError(
            403, message,
        )
    finally:
        if connection:
            connection.quit()
