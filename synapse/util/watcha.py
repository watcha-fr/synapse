# -*- coding: utf-8 -*-


import random
import logging
import jinja2
import os
from os.path import join, dirname, realpath

from smtplib import SMTP
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.header import Header

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


def send_mail(config, recipient, subject, template_name, fields):

    msg = MIMEMultipart('alternative')
    msg['From'] = config.email_notif_from
    msg['To'] = recipient

    # Set the parameter maxlinelen https://docs.python.org/2.7/library/email.header.html
    # setting a high-enough value helps avoid glitches in the subject line (space added every 40-50 characters),
    # when executed with Python 2.7.
    #
    # Semi-relevant online discussions:
    # https://stackoverflow.com/questions/25671608/python-mail-puts-unaccounted-space-in-outlook-subject-line
    # https://bugs.python.org/issue1974
    msg['Subject'] = Header(subject, 'utf-8', 200)

    # HACK: to avoid issues with setuptools/distutil,
    # (not easy to get the 'res/templates' folder to be included in the whl file...)
    # we ship the templates as .py files, and put them in the code tree itself.
    template_dir = join(dirname(realpath(__file__)), 'watcha_templates')
    jinjaenv = jinja2.Environment(loader=jinja2.FileSystemLoader(template_dir))

    for mimetype, extension in {'plain': 'txt',
                                'html': 'html'}.items():
        body = jinjaenv.get_template(template_name + '.' + extension + '.py').render(fields)
        msg.attach(MIMEText(body, mimetype, 'utf-8'))

    # if needed to customize the reply-to field
    # msg['Reply-To'] = ...
    #logger.info(msg.as_string())

    logger.info("Sending email through host %s...", config.email_smtp_host)
    error = None
    try:
        conn = SMTP(config.email_smtp_host, port=config.email_smtp_port)
        conn.ehlo()
        conn.starttls()  # enable TLS
        conn.ehlo()
        conn.set_debuglevel(False)
        conn.login(config.email_smtp_user, config.email_smtp_pass)
        conn.sendmail(config.email_notif_from, [recipient], msg.as_string())
        logger.info("...Mail sent to %s (Subject was: %s)", recipient, subject)
    except Exception, exc:
        logger.exception("...Failed to send mail")
        error = str(exc)
    finally:
        conn.quit()

    return error
