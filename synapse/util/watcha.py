# -*- coding: utf-8 -*-


import random
import logging
import os
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


def send_mail(config, recipient, subject, template_name, fields):
    '''This method should only be used in a Matrix APIs,
    i.e. called in the code of an HTTP end point, as it raises a SynapseError on error,
    and such errors are only handled correctly in endpoints (ie. passed back as 403 error)'''

    if not config.email_smtp_host:
        # (used in tests)
        logger.error("Cannot send email, SMTP host not defined in config")
        return

    message = MIMEMultipart('alternative')
    message['From'] = config.email_notif_from
    message['To'] = recipient

    # Set the parameter maxlinelen https://docs.python.org/2.7/library/email.header.html
    # setting a high-enough value helps avoid glitches in the subject line (space added every 40-50 characters),
    # when executed with Python 2.7.
    #
    # Semi-relevant online discussions:
    # https://stackoverflow.com/questions/25671608/python-mail-puts-unaccounted-space-in-outlook-subject-line
    # https://bugs.python.org/issue1974
    message['Subject'] = Header(subject, 'utf-8', 200)

    # HACK: to avoid issues with setuptools/distutil,
    # (not easy to get the 'res/templates' folder to be included in the whl file...)
    # we ship the templates as .py files, and put them in the code tree itself.
    jinjaenv = Environment(loader=FileSystemLoader(TEMPLATE_DIR))

    for mimetype, extension in {'plain': 'txt',
                                'html': 'html'}.items():
        template_file_name = template_name + '.' + extension + '.py'
        body = jinjaenv.get_template(template_file_name).render(fields)
        message.attach(MIMEText(body, mimetype, 'utf-8'))

    # if needed to customize the reply-to field
    # message['Reply-To'] = ...
    #logger.info(message.as_string())

    logger.info("Sending email to %s through host %s...", recipient, config.email_smtp_host)
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
        error = str(exc)
        logger.error("...failed to send email: %s", error )
        raise SynapseError(
            403, "Failed to send email: " + repr(error),
        )
    finally:
        if connection:
            connection.quit()
