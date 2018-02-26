# -*- coding: utf-8 -*-
#
# Specific Watcha register service:
# * Create new unprivileged user with random userid (ou hmac ?)
# * Sets  displayname for the newly created user
# * Create default room for this user (add also pattern so that the room is monitored by Watcha AS)
# * Automate internal user (who invokes the register) joining the created room
# * Send email with link the riot WEB client et userid
# * Send SMS with the password

from twisted.internet import defer
from email.mime.text import MIMEText
import bcrypt
import plivo

from matrix_client.client import MatrixClient

from .base import ClientV1RestServlet, client_path_patterns
from synapse.api.errors import AuthError, SynapseError
from synapse.util import stringutils
from synapse.http.servlet import parse_json_object_from_request
from synapse.types import UserID

# TODO: send password via SMS ("Votre mot de passe vous a été envoyé par SMS au numéro: ")

CONFIRMATION_EMAIL_SUBJECT_FR = u'''Accès à l'espace de travail sécurisé {instance} Watcha'''
CONFIRMATION_EMAIL_MESSAGE_FR = u'''Bonjour {full_name},



{requester_name} vous a invité à participer à l’espace de travail sécurisé {instance} Watcha.
Pour y accéder, votre nom d’utilisateur est :

{user_login}

et votre mot de passe est:

{user_password}




Vous pouvez accéder à l’espace de travail à partir d’un navigateur sur {server}.
Vous pouvez installer aussi un client mobile:

pour Android: https://play.google.com/store/apps/details?id=im.vector.alpha
Pour iOS: https://itunes.apple.com/us/app/riot-im/id1083446067

Sur l'application mobile, choisissez "Utiliser un serveur personnalisé" et entrez les valeurs:

Serveur d'accueil : {server}
Serveur d'identité : {server}

N’hésitez pas à répondre à cet email si vous avez des difficultés à utiliser Watcha,


L'équipe Watcha.
'''


EMAIL_SETTINGS = {
    'smtphost': 'mail.infomaniak.com',
    'from_addr': 'Watcha registration <registration@watcha.fr>',
    'port': 587,
    'username': "registration@watcha.fr",
    'password': u"Fyr-Www-9t9-V8M",
    'requireAuthentication': True,
    'requireTransportSecurity': True,
}

def _send_registration_email(requester_name, full_name, user_email, user_login, user_password, instance, server):
    message = CONFIRMATION_EMAIL_MESSAGE_FR.format(**{
        'full_name': full_name,
        'instance': instance,
        'server': server,
        'user_login': user_login,
        'user_password': user_password,
        'requester_name': requester_name,
        })
    subject = CONFIRMATION_EMAIL_SUBJECT_FR.format(**{
        'instance': instance
    })

    msg = MIMEText(message, "plain", "utf8")
    msg['Subject'] = subject
    msg['From'] = EMAIL_SETTINGS['from_addr']
    msg['To'] = user_email

    if False: # not EMAIL_SETTINGS['requireTransportSecurity']: # TODO: not working ?
        from smtplib import SMTP_SSL as SMTP       # this invokes the secure SMTP protocol (port 465, uses SSL)
    else:
        from smtplib import SMTP                  # use this for standard SMTP protocol   (port 25, no encryption)


    conn = SMTP(EMAIL_SETTINGS['smtphost'], port=EMAIL_SETTINGS['port'])
    # TODO 'port': 587,
    conn.set_debuglevel(False)
    conn.login(EMAIL_SETTINGS['username'], EMAIL_SETTINGS['password'])
    try:
        conn.sendmail(EMAIL_SETTINGS['from_addr'], [user_email], msg.as_string())
        print("Registration mail sent to %s" % user_email )
    except Exception, exc:
        print("Registration mail failed: %s" % str(exc) )
    finally:
        conn.quit()

def later():
    params = {
        'src' : '1111111111', # Sender's phone number with country code
        'dst' : user_phone, # Receiver's phone Number with country code
        'text' : u"Le mdp watcha est: " + new_pass, # Your SMS Text Message - French
        #    'url' : "http://example.com/report/", # The URL to which with the status of the message is sent
        'method' : 'POST' # The method used to call the url
    }

    # FIXME comment for now to avoid to waste SMS fees
    response = self.sms.send_message(params)
    # FIXME handle error:
    #if response[0] != 202:

    # FIXME allow to send again mail/SMS...
    # Success


class WatchaRegister(ClientV1RestServlet):
    PATTERNS = client_path_patterns("/watcha/register$")

    def __init__(self, hs):
        super(WatchaRegister, self).__init__(hs)
        self.handlers = hs.get_handlers()
        #self.config = hs.get_config()
        #self.store = hs.get_datastore()

        # FIXME extraire de conf
        auth_id = "MANGRMOGU5YWE1ZWQ4MT"
        auth_token = "MWNlZTJlM2IzZTgzZWU4MzI4ZWUyYTliODYxNWJk"
        self.sms = plivo.RestAPI(auth_id, auth_token)

    @defer.inlineCallbacks
    def on_POST(self, request):
        requester = yield self.auth.get_user_by_req(request, allow_guest=False)
        is_admin = yield self.auth.is_server_admin(requester.user)
        if not is_admin:
            raise AuthError(403, "You are not a server admin")

        params = parse_json_object_from_request(request)
        try:
            user_name = params["username"]
            user_mail = params["email"]
            user_phone = params["phone"]
        except:
            defer.returnValue((400, "Unable to find required params: username, email and phone"))

        # Generate Random userID
        new_userid = stringutils.random_string(10)
        # Generate random Password
        new_pass = stringutils.random_string(8)
        # Create User
        # passwd = bcrypt.hashpw(new_pass + self.config.password_pepper,
        #                        bcrypt.gensalt(self.config.bcrypt_rounds))

        handler = self.handlers.registration_handler
        user_id, token = yield handler.register(
            localpart=new_userid,
            password=new_pass,
            admin=False,
        )

        # Set displayname for newly created user
        yield self.handlers.profile_handler.set_displayname(
            UserID.from_string(user_id),
            requester, user_name, by_admin=True)
        # Create Room
        # Set alias for new room
        # New user autojoin the room
        handler = self.handlers.room_creation_handler
        info = yield handler.create_room(
            requester, {
                "preset": "private_chat",
                "visibility": "private",
                "invite": [user_id],
                "name": "salon " + user_name,
                "room_alias_name": "fs_" + user_name,
                "creation_content": {
                    "m.federate": False
                }
            }
        )
        room_id = info["room_id"]

        # TODO: send email and/or SMS
        defer.returnValue((200, {}))

    def on_OPTIONS(self, request):
        return (200, {})

class WatchaPhone(ClientV1RestServlet):
    PATTERNS = client_path_patterns("/watcha/phone2user/(?P<number>[^/]*)$")

    def __init__(self, hs):
        super(WatchaPhone, self).__init__(hs)
        self.reg = hs.get_handlers().registration_handler

    @defer.inlineCallbacks
    def on_GET(self, request, number):
        requester = yield self.auth.get_user_by_req(request)
        userid = reg.get_user_by_phone(number)

        ret = {}
        if userid is not None:
            ret["user_id"] = userid
            defer.returnValue((200, ret))

def register_servlets(hs, http_server):
    WatchaRegister(hs).register(http_server)
    WatchaPhone(hs).register(http_server)

CONFIG_TEMPLATE=u'''# -*- coding: utf-8 -*-

SERVER = "https://url.to.the.server"

# Name of the person or institution who sends the email
ADMIN=""

# The name of the Watcha instance. Usually the customer's name (e.g.
INSTANCE=""

USERS = [
    # ['Last name', 'first name', 'email adress', 'user_name_to_create', 'password_to_create', True if 'admin' else False]
]
'''

def main():
    from os.path import basename, dirname, exists, splitext, abspath
    import sys

    if len(sys.argv) < 2:
        print 'Usage: python -m synapse.rest.client.v1.watcha <user configuration file>'
        return
    config_file = abspath(sys.argv[1])
    if not exists(config_file):
        with open(config_file, 'w') as f:
            f.write(CONFIG_TEMPLATE)
            print "Template user configuration file created at %s. Please fill it now and re-run" % config_file
            return

    sys.path.append(dirname(config_file))
    try:
        config = __import__(splitext(basename(config_file))[0], ['USERS', 'SERVER', 'ADMIN', 'INSTANCE'])
    except ImportError:
        print "Could not import users from file %s. Is it a valid file ?" % config_file
        return

    if not config.USERS:
        print "No user found in %s, please edit file and add users" % config_file

    print "User creation commands to run on the server:"
    print
    for user in config.USERS:
        last_name, first_name, email, user_name, password, admin = user
        full_name = first_name + ' ' + last_name
        print "register_new_matrix_user -u '%s' -p '%s' %s-c /etc/matrix-synapse/homeserver.yaml http://localhost:8008" % (user_name, password, '-a ' if admin else '')
    print
    raw_input("press enter once you have created the users: ")
    print
    for user in config.USERS:
        last_name, first_name, email, user_name, password, admin = user
        full_name = first_name + ' ' + last_name
        client = MatrixClient(config.SERVER)
        token = client.login_with_password(username=user_name, password=password)
        user = client.get_user(client.user_id)
        user.set_display_name(full_name)
        print 'Display name:', user.get_display_name()
        _send_registration_email(config.ADMIN, full_name, email, user_name, password, config.INSTANCE, config.SERVER)

if __name__ == "__main__":
    main()
