# -*- coding: utf-8 -*-

import sys

import hmac
from hashlib import sha1

import subprocess
import logging
# requires python 2.7.7 or later
from hmac import compare_digest

from twisted.internet import defer

from synapse.util.async import run_on_reactor
from synapse.api.errors import SynapseError
from .base import ClientV1RestServlet, client_path_patterns
from synapse.http.servlet import parse_json_object_from_request
from synapse.util.watcha import generate_password, send_mail
from synapse.types import UserID


logger = logging.getLogger(__name__)

HELP = u'''


Vous pouvez accéder à l’espace de travail à partir d’un navigateur sur {server}.
Vous pouvez installer aussi un client mobile :

pour Android: https://play.google.com/store/apps/details?id=im.watcha
Pour iOS: https://itunes.apple.com/us/app/riot-im/id1083446067

Sur l'application mobile, choisissez "Utiliser un serveur personnalisé" et entrez les valeurs:

Serveur d'accueil : {server}
Serveur d'identité : {server}

Si vous avez des difficultés à utiliser Watcha, répondez à cet email et nous vous aiderons

Cordialement,

L'équipe Watcha.
'''

CONFIRMATION_EMAIL_SUBJECT_FR = u'''Accès à l'espace de travail sécurisé Watcha {server}'''
CONFIRMATION_EMAIL_MESSAGE_FR = u'''Bonjour {full_name},



Vous avez été invité à participer à l’espace de travail sécurisé Watcha {server} 
Pour y accéder, votre nom d’utilisateur est :

{user_login}

et votre mot de passe est :

{user_password}


''' + HELP

PASSWORD_EMAIL_SUBJECT_FR = u'''Nouveau mot de passe pour l'espace de travail sécurisé Watcha {server}'''
PASSWORD_EMAIL_MESSAGE_FR = u'''Bonjour {full_name},

Votre mot de passe pour accéder à l’espace de travail sécurisé {server} a été changé.

Votre nom d’utilisateur est toujours :

{user_login}

et votre mot de passe est maintenant :

{user_password}

''' + HELP


def _decode_share_secret_parameters(hs, parameter_names, parameter_json):
    for parameter_name in parameter_names:
        if not isinstance(parameter_json.get(parameter_name, None), basestring):
            raise SynapseError(400, "Expected %s." % parameter_name)

    if not hs.config.registration_shared_secret:
        raise SynapseError(400, "Shared secret registration is not enabled")

    parameters = { parameter_name: parameter_json[parameter_name].encode("utf-8")
                   for parameter_name in parameter_names }

    # Its important to check as we use null bytes as HMAC field separators
    if any("\x00" in parameters[parameter_name] for parameter_name in parameter_names):
        raise SynapseError(400, "Invalid message")

    # str() because otherwise hmac complains that 'unicode' does not
    # have the buffer interface
    got_mac = str(parameter_json["mac"])

    want_mac = hmac.new(
        key=hs.config.registration_shared_secret,
        digestmod=sha1,
    )
    for parameter_name in parameter_names:
        want_mac.update(parameters[parameter_name])
        want_mac.update("\x00")        
    if not compare_digest(want_mac.hexdigest(), got_mac):
            raise SynapseError(
                403, "HMAC incorrect",
            )
    return parameters

class WatchaRegisterRestServlet(ClientV1RestServlet):
    PATTERNS = client_path_patterns("/watcha_register")

    @defer.inlineCallbacks
    def on_POST(self, request):
        yield run_on_reactor() # not sure what it is :)
        logger.info("Adding Watcha user...")
        
        parameter_json = parse_json_object_from_request(request)
        params = _decode_share_secret_parameters(self.hs, ['user', 'full_name', 'email', 'admin'], parameter_json)
        if params['user'].lower() != params['user']:
            raise SynapseError(
                403, "user name must be lowercase",
            )
            
        password = generate_password()
        handler = self.hs.get_handlers().registration_handler
        admin = (params['admin'] == 'admin')
        user_id, token = yield handler.register(
            localpart=params['user'],
            password=password,
            admin=admin,
        )
        
        user = UserID.from_string(user_id)
        self.hs.profile_handler.set_displayname(user, None, params['full_name'], by_admin=True)
        
        yield self.hs.auth_handler.set_email(user_id, params['email'])

        display_name = yield self.hs.profile_handler.get_displayname(user)
        
        send_mail(self.hs.config, params['email'], 
                  CONFIRMATION_EMAIL_SUBJECT_FR.format(server=self.hs.config.public_baseurl),
                  CONFIRMATION_EMAIL_MESSAGE_FR.format(
                      full_name=display_name,
                      server=self.hs.config.public_baseurl,
                      user_login=params['user'],
                      user_password=password
                  ))
        defer.returnValue((200, { "user_id": user_id, }))
            
    
class WatchaResetPasswordRestServlet(ClientV1RestServlet):
    PATTERNS = client_path_patterns("/watcha_reset_password")

    @defer.inlineCallbacks
    def on_POST(self, request):
        yield run_on_reactor() # not sure what it is :)
        
        parameter_json = parse_json_object_from_request(request)
        params = _decode_share_secret_parameters(self.hs, ['user'], parameter_json)
        password = generate_password()

        logger.info("Setting password for user %s", param['user'])
        self.hs.get_set_password_handler().set_password(
            params['user'], password, None # no requester
        )
        user = UserID.from_string('@' + params['user'] + ':' + self.hs.get_config().server_name)
        display_name = yield  self.hs.profile_handler.get_displayname(user)
        send_mail(self.hs.config, params['email'], 
                  PASSWORD_EMAIL_SUBJECT_FR.format(server=self.hs.config.public_baseurl),
                  PASSWORD_EMAIL_MESSAGE_FR.format(
                      full_name=display_name,
                      server=self.hs.config.public_baseurl,
                      user_login=params['user'],
                      user_password=password
                  ))

        defer.returnValue((200, response))


class WatchaStats(ClientV1RestServlet):
    PATTERNS = client_path_patterns("/stats")

    def __init__(self, hs):
        super(WatchaStats, self).__init__(hs)
        self.store = hs.get_datastore()

    @defer.inlineCallbacks
    def on_GET(self, request):
        ### fetch the number of local and external users.
        user_stats = yield self.store.get_count_users_partners()

        ### get the version of the synapse server, if installed with pip.

 # this method may block the synapse process for a while, as pip does not immediately return.
        #synapse_version = system('pip freeze | grep "matrix-synapse==="')

        try:
            proc = subprocess.Popen(['pip', 'freeze'], stdout=subprocess.PIPE)
            output = subprocess.check_output(('grep', 'matrix-synapse==='), stdin=proc.stdout)
            proc.wait()
            # output seems not always to be of the same type. str or object.
            #(synapse_version, err) = output.communicate()
            if type(output) is str:
                synapse_version = output
            else:
                (synapse_version, err) = output.communicate()

        except subprocess.CalledProcessError as e:
            # when grep does not find any line, this error is thrown. it is normal behaviour during development.
            synapse_version = "unavailable"

        defer.returnValue((200, { "users": user_stats, "synapse_version": synapse_version }))


def register_servlets(hs, http_server):
    WatchaStats(hs).register(http_server)
    WatchaResetPasswordRestServlet(hs).register(http_server)
    WatchaRegisterRestServlet(hs).register(http_server)
