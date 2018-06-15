#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
# User creation code
# See also synapse/rest/client/v1/watcha.py
#
# script to create new accounts on a watcha instance
# can also reset password for accounts
#
# usage: this script is to be used in a two-step process.
# first, generate a data template by running
# $ python watcha_users.py /tmp/watcha_users_conf.py
# where /tmp/watcha_users_conf.py does not exist in the first place.
# then, edit it with your favorite editor.
# once you are ready, re-run the above command
# $ python watcha_users.py /tmp/watcha_users_conf.py

import sys

from os.path import basename, exists, splitext, abspath, dirname, join
import hashlib
import hmac
import json
import sys
import urllib2

# Inspired by `request_registration` in file `scripts/register_new_matrix_user`
def _call_with_shared_secret(endpoint, parameters, server_location, shared_secret):
    '''Order of parameters matters, so must be list of pairs'''
    mac = hmac.new(
        key=shared_secret,
        digestmod=hashlib.sha1,
    )

    for _, parameter_value in parameters:
        mac.update(repr(parameter_value))
        mac.update("\x00")

    mac = mac.hexdigest()

    data = dict(parameters)
    data["mac"] = mac

    server_location = server_location.rstrip("/")

    print "Sending %s request..." % endpoint

    req = urllib2.Request(
        "%s/_matrix/client/api/v1/%s" % (server_location, endpoint),
        data=json.dumps(data),
        headers={'Content-Type': 'application/json'}
    )

    try:
        if sys.version_info[:3] >= (2, 7, 9):
            # As of version 2.7.9, urllib2 now checks SSL certs
            import ssl
            f = urllib2.urlopen(req, context=ssl.SSLContext(ssl.PROTOCOL_SSLv23))
        else:
            f = urllib2.urlopen(req)
        f.read()
        f.close()
        print "Success."
    except urllib2.HTTPError as e:
        print "ERROR! Received %d %s" % (e.code, e.reason,)
        if 400 <= e.code < 500:
            if e.info().type == "application/json":
                resp = json.load(e)
                if "error" in resp:
                    print resp["error"]
        sys.exit(1)

VERSION = "0.7"
CONFIG_TEMPLATE=u'''# -*- coding: utf-8 -*-

# Version of this file, do not modify
VERSION = "{version}"

# Url to the core server, with https:// at the beginning.
CORE = ""

# new users to create
NEW_USERS = [
    # [u'full name', 'email@adress', 'username', True if 'admin' else False ]
]

# users to send a new password to. put usernames without leading "@" and without suffix.
RESET_PASSWORD_FOR_USERS = [
  # 'username'
]

# Registration shared secret from homeserver.yaml
REGISTRATION_SHARED_SECRET = ""
'''.format(version=VERSION)

def main():
    if len(sys.argv) < 2:
        print 'Usage: watcha_users <user file>.py'
        return
    user_file = abspath(sys.argv.pop())
    if not user_file.endswith('.py'):
        print "Config file name must finish with .py"
        return

    if not exists(user_file):
        with open(user_file, 'w') as f:
            f.write(CONFIG_TEMPLATE)
        print "Template user configuration file created at %s. Please fill it now and re-run" % user_file
        return

    # the loading of the user file, is **ugly**... but I don't find easier ways...
    mylocals = {}
    execfile(join(dirname(__file__), 'register_new_matrix_user'), {'__name__': None}, mylocals)
    mylocals['__name__'] = None
    execfile(join(dirname(__file__), 'register_new_matrix_user'), mylocals, mylocals)

    sys.path.append(dirname(user_file))
    try:
        config = __import__(splitext(basename(user_file))[0], ['VERSION', 'CORE', 'NEW_USERS',
                                                               'RESET_PASSWORD_FOR_USERS',
                                                               'REGISTRATION_SHARED_SECRET'])
    except ImportError, e:
        print "Could not import users from file %s. Is it a valid file ?" % user_file
        return

    if not hasattr(config, 'VERSION') or config.VERSION != VERSION:
        print "Config file version ({config_version}) incompatible with this version ({script_version}) of the script. Maybe pull an older version of the script ?".format(config_version=(config.VERSION if hasattr(config, 'VERSION') else 'none found'), script_version=VERSION)
        return

    if not getattr(config, 'NEW_USERS', None) and not getattr(config, 'RESET_PASSWORD_FOR_USERS', None):
        print "No user found in %s, please edit file and add users" % user_file
        return

    if not getattr(config, 'REGISTRATION_SHARED_SECRET', None):
        print "No shared secret in %s, please edit file and add users" % user_file
        return
    
    for user in config.NEW_USERS:
        full_name, email, user_name, admin = user

        _call_with_shared_secret('watcha_register',
                                 [('user', user_name),
                                  # force it to be unicode in all case, to ensure hmac consistency
                                  ('full_name', unicode(full_name)),
                                  ('email', email),
                                  ('admin', 'admin' if admin else 'notadmin')],
                                 config.CORE, config.REGISTRATION_SHARED_SECRET)

    for user_name in config.RESET_PASSWORD_FOR_USERS:
        _call_with_shared_secret('watcha_reset_password', [('user', user_name)],
                                 config.CORE, config.REGISTRATION_SHARED_SECRET)
if __name__ == "__main__":
    main()
