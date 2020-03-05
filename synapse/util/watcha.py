# -*- coding: utf-8 -*-


import random
import logging
import os
import base64
from os.path import join, dirname, abspath

from jinja2 import Environment, FileSystemLoader
from smtplib import SMTP
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.header import Header

from synapse.api.errors import SynapseError

logger = logging.getLogger(__name__)

# must be defined at package loading time,
# because synctl start's demonizer is changing the abspath...
TEMPLATE_DIR = join(dirname(abspath(__file__)), 'watcha_templates')

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


def compute_registration_token(user, password=None):
    '''Returns a (weakly encrypted) token that can be passed in a URL or in a JSON for temporaly login
    This cannot be strongly encrypted, because it will be decoded in Riot (in javascript).
    '''
    if password is None:
        json = '{{"user":"{user}"}}'.format(user=user)
    else:
        json = '{{"user":"{user}","pw":"{password}"}}'.format(user=user,
                                                              password=password)
    return base64.b64encode(json.encode("utf-8")).decode("ascii")


def send_registration_email(config, recipient, template_name, token,
                            user_login, **additional_fields):
    '''
    Sends email related to user registration (invitation, reset password...)

    Beside the "additional_fields", the 'user_login', 'server', 'title', 'login_url',
    and 'setup_account_url' variables  also used in the template.
    The 'title' will be created from the subject.

    This method should only be used in a Matrix APIs,
    i.e. called in the code of an HTTP end point, as it raises a SynapseError on error,
    and such errors are only handled correctly in endpoints (ie. passed back as 403 error)'''

    fields = dict(additional_fields)
    fields['user_login'] = user_login
    fields['server'] = config.server_name
    if 'polypus-core.watcha.fr' in config.server_name:
        # legacy... polypus was installed with an incorrect server name, and it can't be changed after install,
        # so correcting it here... (see also devops.git/prod/install.sh)
        fields['server'] = 'polypus.watcha.fr'

    fields['login_url'] = "%s/#/login/t=%s" % (config.email_riot_base_url, token)
    fields['setup_account_url'] = "%s/setup-account.html?t=%s" % (config.email_riot_base_url, token)

    # To avoid issues with setuptools/distutil,
    # (not easy to get the 'res/templates' folder to be included in the whl file...)
    # we ship the templates as .py files, and put them in the code tree itself.
    jinjaenv = Environment(loader=FileSystemLoader(TEMPLATE_DIR))
    subject = jinjaenv.get_template(template_name + '.subject.py').render(fields)
    fields['title'] = subject

    message = MIMEMultipart('alternative')
    message['From'] = config.email_notif_from
    message['To'] = recipient

    # Set the parameter maxlinelen https://docs.python.org/2.7/library/email.header.html
    # setting a high-enough value helps avoid glitches in the subject line (space added every 40-50 characters),
    # when executed with Python 2.7. Semi-relevant online discussions:
    # https://stackoverflow.com/questions/25671608/python-mail-puts-unaccounted-space-in-outlook-subject-line
    # https://bugs.python.org/issue1974
    message['Subject'] = Header(subject, 'utf-8', 200)

    for mimetype, extension in {'plain': 'txt',
                                'html': 'html'}.items():
        template_file_name = template_name + '.' + extension + '.py'
        body = jinjaenv.get_template(template_file_name).render(fields)
        message.attach(MIMEText(body, mimetype, 'utf-8'))

    # if needed to customize the reply-to field
    # message['Reply-To'] = ...

    if config.email_smtp_host == 'TEST':
        # For running on a local machine. Requires multiple configs in homeserver.yaml:
        #email:
        #   riot_base_url: "http://localhost:8080"
        #   smtp_host: "TEST"
        #   smtp_port: "0"
        #   notif_from: "TEST"
        #public_baseurl: "TEST"

        logger.info("NOT Sending registration email to '%s', we are in test mode", recipient)
        logger.info("Email subject is: " + subject)
        logger.info("Email text content follows:")
        logger.info(str(base64.b64decode(message.get_payload()[0].get_payload())))
        return

    if not config.email_smtp_host:
        # (used in tests.rest.client.test_identity.IdentityTestCase.test_3pid_lookup_disabled: just skip it)
        logger.error("Cannot send email, SMTP host not defined in config")
        return

    if not config.email_riot_base_url:
        logger.error("Cannot send email, riot_base_url not defined in config")
        return

    logger.info("Sending email to '%s' through host %s...", recipient, config.email_smtp_host)
    connection = None
    try:
        connection = SMTP(config.email_smtp_host,
                          port=config.email_smtp_port,
                          timeout=10) # putting a short timeout to avoid client erroring before server
        connection.ehlo()
        connection.starttls()  # enable TLS
        connection.ehlo()
        connection.set_debuglevel(False)
        connection.login(config.email_smtp_user, config.email_smtp_pass)
        connection.sendmail(config.email_notif_from, [recipient], message.as_string())
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
