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
import base64
from synapse.types import create_requester


logger = logging.getLogger(__name__)

def _decode_share_secret_parameters(hs, parameter_names, parameter_json):
    for parameter_name in parameter_names:
        if not isinstance(parameter_json.get(parameter_name, None), basestring):
            raise SynapseError(400, "Expected %s." % parameter_name)

    if not hs.config.registration_shared_secret:
        raise SynapseError(400, "Shared secret registration is not enabled")

    parameters = { parameter_name: parameter_json[parameter_name]
                   for parameter_name in parameter_names }

    # Its important to check as we use null bytes as HMAC field separators
    if any("\x00" in parameters[parameter_name] for parameter_name in parameter_names):
        raise SynapseError(400, "Invalid message")

    got_mac = str(parameter_json["mac"])

    want_mac = hmac.new(
        key=hs.config.registration_shared_secret,
        digestmod=sha1,
    )
    for parameter_name in parameter_names:
        want_mac.update(repr(parameters[parameter_name]))
        want_mac.update("\x00")
    if not compare_digest(want_mac.hexdigest(), got_mac):
            raise SynapseError(
                403, "HMAC incorrect",
            )
    return parameters


class WatchaRegisterRestServlet(ClientV1RestServlet):
    """
    Registration of users.
    Requester must either be logged in as an admin, or supply a valid HMAC (generated from the registration_shared_secret)
    """
    PATTERNS = client_path_patterns("/watcha_register")

    def __init__(self, hs):
        ClientV1RestServlet.__init__(self, hs)


    @defer.inlineCallbacks
    def on_POST(self, request):
        yield run_on_reactor() # not sure what it is :)
        auth_headers = request.requestHeaders.getRawHeaders("Authorization")
        is_admin = False

        if auth_headers:
            requester = yield self.auth.get_user_by_req(request)
            is_admin = yield self.auth.is_server_admin(requester.user)
        logger.info("Adding Watcha user...")

        parameter_json = parse_json_object_from_request(request)
        # parse_json will not return unicode if it's only ascii... making hmac fail. Force it to be unicode.
        parameter_json['full_name'] = unicode(parameter_json['full_name'])
        if not is_admin:
            # auth by checking that the HMAC is valid. this raises an error otherwise.
            params = _decode_share_secret_parameters(self.hs, ['user', 'full_name', 'email', 'admin'], parameter_json)
        else:
            params = parameter_json

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
        requester = create_requester(user_id)
        self.hs.profile_handler.set_displayname(user, requester, params['full_name'], by_admin=True)

        yield self.hs.auth_handler.set_email(user_id, params['email'])

        display_name = yield self.hs.profile_handler.get_displayname(user)

        setupToken = base64.b64encode('{"user":"' + user_id + '","pw":"' + password + '"}')

        server = self.hs.config.public_baseurl.rstrip('/')
        subject = u'''Accès à l'espace de travail sécurisé Watcha {server}'''.format(server=server)

        fields = {
                'title': subject,
                'full_name': display_name,
                'user_login': params['user'],
                'setupToken': setupToken,
                'server': server,
        }

        send_email_error = send_mail(
            self.hs.config,
            params['email'],
            subject=subject,
            template_name='new_account',
            fields=fields,
        )

        if send_email_error is None:
            defer.returnValue((200, { "user_id": user_id }))
        else:
            raise SynapseError(403,
                               "Failed to sent email: " + repr(send_email_error))


class WatchaResetPasswordRestServlet(ClientV1RestServlet):
    PATTERNS = client_path_patterns("/watcha_reset_password")

    def __init__(self, hs):
        ClientV1RestServlet.__init__(self, hs)
        self.handlers =hs.get_handlers()


    @defer.inlineCallbacks
    def on_POST(self, request):
        yield run_on_reactor() # not sure what it is :)
        auth_headers = request.requestHeaders.getRawHeaders("Authorization")
        is_admin = False
        if auth_headers:
            requester = yield self.auth.get_user_by_req(request)
            is_admin = yield self.auth.is_server_admin(requester.user)

        parameter_json = parse_json_object_from_request(request)
        if not is_admin:
            params = _decode_share_secret_parameters(self.hs, ['user'], parameter_json)
            user_id = '@' + params['user'] + ':' + self.hs.get_config().server_name
        else:
            params = parameter_json
            user_id = params['user']
        password = generate_password()
        logger.info("Setting password for user %s", user_id)
        user = UserID.from_string(user_id)

        user_info = yield self.hs.get_datastore().get_user_by_id(user_id)
        # do not update password if email is not set
        if not user_info['email']:
            raise SynapseError(403,
                               "email not defined for this user")

        requester = create_requester(user_id)
        yield self.hs.get_set_password_handler().set_password(
            user_id, password, requester
        )
        yield self.handlers.watcha_admin_handler.watcha_reactivate_account(user_id)
        
        try:
            display_name = yield self.hs.profile_handler.get_displayname(user)
        except:
            display_name = params['user']

        setupToken = base64.b64encode('{"user":"' + user_id + '","pw":"' + password + '"}')

        server = self.hs.config.public_baseurl.rstrip('/')
        subject = u'''Nouveau mot de passe pour l'espace de travail sécurisé Watcha {server}'''.format(server=server)

        fields = {
                'title': subject,
                'full_name': display_name,
                'user_login': params['user'],
                'setupToken': setupToken,
                'server': server,
        }

        send_email_error = send_mail(
            self.hs.config,
            user_info['email'],
            subject=subject,
            template_name='reset_password',
            fields=fields,
        )

        if send_email_error is None:
            defer.returnValue((200, {}))
        else:
            raise SynapseError(403,
                               "Failed to sent email: " + repr(send_email_error))


class WatchaStats(ClientV1RestServlet):
    PATTERNS = client_path_patterns("/stats")

    def __init__(self, hs):
        super(WatchaStats, self).__init__(hs)
        self.store = hs.get_datastore()

    @defer.inlineCallbacks
    def on_GET(self, request):
        ### fetch the number of local and external users.
        user_stats = yield self.store.get_count_users_partners()

        ### fetch the list of rooms, the amount of users and their activity status
        room_stats = yield self.store.get_room_count_per_type()

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

        defer.returnValue((200, { "users": user_stats, "rooms": room_stats, "synapse_version": synapse_version }))


def register_servlets(hs, http_server):
    WatchaStats(hs).register(http_server)
    WatchaResetPasswordRestServlet(hs).register(http_server)
    WatchaRegisterRestServlet(hs).register(http_server)
