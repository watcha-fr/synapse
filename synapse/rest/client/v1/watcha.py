# -*- coding: utf-8 -*-

import sys

import base64
import hmac
from hashlib import sha1

import logging


# requires python 2.7.7 or later
from hmac import compare_digest

from twisted.internet import defer

from synapse.api.errors import AuthError, SynapseError
from synapse.http.servlet import RestServlet, parse_json_object_from_request
from synapse.rest.client.v2_alpha._base import client_patterns
from synapse.util.watcha import generate_password, send_mail
from synapse.types import UserID, create_requester
from synapse.api.constants import Membership

logger = logging.getLogger(__name__)

def _decode_share_secret_parameters(config, parameter_names, parameter_json):
    for parameter_name in parameter_names:
        if parameter_name not in parameter_json:
            raise SynapseError(400, "Expected %s." % parameter_name)

    if not config.registration_shared_secret:
        raise SynapseError(400, "Shared secret registration is not enabled")

    parameters = { parameter_name: parameter_json[parameter_name]
                   for parameter_name in parameter_names }

    # Its important to check as we use null bytes as HMAC field separators
    if any("\x00" in parameters[parameter_name] for parameter_name in parameter_names):
        raise SynapseError(400, "Invalid message")

    # FIXME: hack for create_user: parse_json will not return unicode if it's only ascii... making hmac fail.
    # So force it to be unicode.
    if 'full_name' in parameters:
        parameters['full_name'] = unicode(parameters['full_name'])

    got_mac = str(parameter_json["mac"])

    want_mac = hmac.new(
        key=config.registration_shared_secret,
        digestmod=sha1,
    )
    for parameter_name in parameter_names:
        want_mac.update(repr(parameters[parameter_name]))
        want_mac.update("\x00")
    if not compare_digest(want_mac.hexdigest(), got_mac):
        logger.error("Failed to decode HMAC for parameters names: " +
                     repr(parameter_names) +
                     ' and values: ' +
                     repr(parameter_json))

        raise SynapseError(
            403, "HMAC incorrect",
        )
    return parameters

@defer.inlineCallbacks
def _check_admin(auth, request):
    requester = yield auth.get_user_by_req(request)
    is_admin = yield auth.is_server_admin(requester.user)
    if not is_admin:
        raise AuthError(403, "You are not a server admin")

@defer.inlineCallbacks
def _check_admin_or_secret(config, auth, request, parameter_names):
    auth_headers = request.requestHeaders.getRawHeaders("Authorization")
    parameter_json = parse_json_object_from_request(request)

    if auth_headers:
        yield _check_admin(auth, request)
        ret = parameter_json
    else:
        # auth by checking that the HMAC is valid. this raises an error otherwise.
        ret = _decode_share_secret_parameters(config, parameter_names, parameter_json)

    defer.returnValue(ret)

class WatchaUserlistRestServlet(RestServlet):

    PATTERNS = client_patterns("/watcha_user_list", v1=True)
    def __init__(self, hs):
        super(WatchaUserlistRestServlet, self).__init__()
        self.auth = hs.get_auth()
        self.handlers = hs.get_handlers()

    @defer.inlineCallbacks
    def on_GET(self, request):
        yield _check_admin(self.auth, request)
        ret = yield self.handlers.watcha_admin_handler.watcha_user_list()
        defer.returnValue((200, ret))

class WatchaRoomlistRestServlet(RestServlet):

    PATTERNS = client_patterns("/watcha_room_list", v1=True)
    def __init__(self, hs):
        super(WatchaRoomlistRestServlet, self).__init__()
        self.auth = hs.get_auth()
        self.handlers = hs.get_handlers()

    @defer.inlineCallbacks
    def on_GET(self, request):
        yield _check_admin(self.auth, request)
        ret = yield self.handlers.watcha_admin_handler.watcha_room_list()
        defer.returnValue((200, ret))

class WatchaRoomMembershipRestServlet(RestServlet):

    PATTERNS = client_patterns("/watcha_room_membership", v1=True)
    def __init__(self, hs):
        super(WatchaRoomMembershipRestServlet, self).__init__()
        self.auth = hs.get_auth()
        self.handlers = hs.get_handlers()

    @defer.inlineCallbacks
    def on_GET(self, request):
        yield _check_admin(self.auth, request)
        ret = yield self.handlers.watcha_admin_handler.watcha_room_membership()
        defer.returnValue((200, ret))

class WatchaRoomNameRestServlet(RestServlet):

    PATTERNS = client_patterns("/watcha_room_name", v1=True)
    def __init__(self, hs):
        super(WatchaRoomNameRestServlet, self).__init__()
        self.auth = hs.get_auth()
        self.handlers = hs.get_handlers()

    @defer.inlineCallbacks
    def on_GET(self, request):
        yield _check_admin(self.auth, request)
        ret = yield self.handlers.watcha_admin_handler.watcha_room_name()
        defer.returnValue((200, ret))

class WatchaDisplayNameRestServlet(RestServlet):

    PATTERNS = client_patterns("/watcha_display_name", v1=True)
    def __init__(self, hs):
        super(WatchaDisplayNameRestServlet, self).__init__()
        self.auth = hs.get_auth()
        self.handlers = hs.get_handlers()

    @defer.inlineCallbacks
    def on_GET(self, request):
        yield _check_admin(self.auth, request)
        ret = yield self.handlers.watcha_admin_handler.watcha_display_name()
        defer.returnValue((200, ret))

class WatchaExtendRoomlistRestServlet(RestServlet):
    PATTERNS = client_patterns("/watcha_extend_room_list", v1=True)
    def __init__(self, hs):
        super(WatchaExtendRoomlistRestServlet, self).__init__()
        self.auth = hs.get_auth()
        self.handlers = hs.get_handlers()

    @defer.inlineCallbacks
    def on_GET(self, request):
        yield _check_admin(self.auth, request)
        ret = yield self.handlers.watcha_admin_handler.watcha_extend_room_list()
        defer.returnValue((200, ret))

class WatchaUpdateMailRestServlet(RestServlet):
    PATTERNS = client_patterns("/watcha_update_email/(?P<target_user_id>[^/]*)", v1=True)
    def __init__(self, hs):
        super(WatchaUpdateMailRestServlet, self).__init__()
        self.auth = hs.get_auth()
        self.handlers = hs.get_handlers()

    @defer.inlineCallbacks
    def on_PUT(self, request, target_user_id):
        yield _check_admin(self.auth, request)
        params = parse_json_object_from_request(request)
        new_email = params['new_email']
        if not new_email:
            raise SynapseError(400, "Missing 'new_email' arg")
        yield self.handlers.watcha_admin_handler.watcha_update_mail(target_user_id, new_email)
        defer.returnValue((200, {}))

class WatchaUpdateToMember(RestServlet):
    PATTERNS = client_patterns("/watcha_update_partner_to_member/(?P<target_user_id>[^/]*)", v1=True)
    def __init__(self, hs):
        super(WatchaUpdateToMember, self).__init__()
        self.auth = hs.get_auth()
        self.handlers = hs.get_handlers()

    @defer.inlineCallbacks
    def on_PUT(self, request, target_user_id):
        yield _check_admin(self.auth, request)
        yield self.handlers.watcha_admin_handler.watcha_update_to_member(target_user_id)
        defer.returnValue((200, {}))

class WatchaServerState(RestServlet):

    PATTERNS = client_patterns("/watcha_server_state", v1=True)
    def __init__(self, hs):
        super(WatchaServerState, self).__init__()
        self.auth = hs.get_auth()
        self.handlers = hs.get_handlers()

    @defer.inlineCallbacks
    def on_GET(self, request):
        yield _check_admin(self.auth, request)
        ret = yield self.handlers.watcha_admin_handler.watcha_server_state()
        defer.returnValue((200, ret))

class WatchaAdminStats(RestServlet):
    '''Get stats on the server.

    For POST, a optional 'ranges' parameters in JSON input made of a list of time ranges,
    will return stats for these ranges.

    The ranges must be arrays with three elements:
    label, start seconds since epoch, end seconds since epoch.
    '''

    PATTERNS = client_patterns("/watcha_admin_stats", v1=True)
    def __init__(self, hs):
        super(WatchaAdminStats, self).__init__()
        self.hs = hs
        self.store = hs.get_datastore()
        self.auth = hs.get_auth()
        self.handlers = hs.get_handlers()

    @defer.inlineCallbacks
    def on_GET(self, request):
        yield _check_admin(self.auth, request)
        ret = yield self.handlers.watcha_admin_handler.watcha_admin_stat()
        defer.returnValue((200, ret))

    @defer.inlineCallbacks
    def on_POST(self, request):
        params = yield _check_admin_or_secret(self.hs.config, self.auth, request, ['ranges'])

        ret = yield self.handlers.watcha_admin_handler.watcha_admin_stat(params['ranges'] or None)
        defer.returnValue((200, ret))


class WatchaUserIp(RestServlet):

    PATTERNS = client_patterns("/watcha_user_ip/(?P<target_user_id>[^/]*)", v1=True)
    def __init__(self, hs):
        super(WatchaUserIp, self).__init__()
        self.hs = hs
        self.store = hs.get_datastore()
        self.auth = hs.get_auth()
        self.handlers = hs.get_handlers()

    @defer.inlineCallbacks
    def on_GET(self, request, target_user_id):
        yield _check_admin(self.auth, request)
        ret = yield self.handlers.watcha_admin_handler.watcha_user_ip(target_user_id)
        defer.returnValue((200, ret))

class WatchaRegisterRestServlet(RestServlet):
    """
    Registration of users.
    Requester must either be logged in as an admin, or supply a valid HMAC (generated from the registration_shared_secret)
    """
    PATTERNS = client_patterns("/watcha_register", v1=True)

    def __init__(self, hs):
        super(WatchaRegisterRestServlet, self).__init__()
        self.hs = hs
        self.auth = hs.get_auth()
        
    @defer.inlineCallbacks
    def on_POST(self, request):
        params = yield _check_admin_or_secret(self.hs.config, self.auth, request,
                                             ['user', 'full_name', 'email', 'admin'])

        logger.info("Adding Watcha user...")

        if params['user'].lower() != params['user']:
            raise SynapseError(
                500, "user name must be lowercase",
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
        subject = u'''Invitation à l'espace de travail sécurisé Watcha {server}'''.format(server=server)

        fields = {
                'title': subject,
                'full_name': display_name,
                'user_login': user.localpart,
                'setupToken': setupToken,
                'server': server,
        }

        send_mail(
            self.hs.config,
            params['email'],
            subject=subject,
            template_name='new_account',
            fields=fields,
        )

        defer.returnValue((200, { "user_id": user_id }))


class WatchaResetPasswordRestServlet(RestServlet):
    PATTERNS = client_patterns("/watcha_reset_password", v1=True)

    def __init__(self, hs):
        super(WatchaResetPasswordRestServlet, self).__init__()
        self.hs = hs
        self.handlers = hs.get_handlers()
        self.auth = hs.get_auth()

    @defer.inlineCallbacks
    def on_POST(self, request):
        params = yield _check_admin_or_secret(self.hs.config, self.auth, request, ['user'])

        user_id = params['user']
        # FIXME: when called from the 'watcha_users' script,
        # the user_id usually doesn't have the server name. add it.
        if not user_id.startswith('@'):
            user_id = '@' + params['user'] + ':' + self.hs.get_config().server_name

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
            display_name = user.localpart

        setupToken = base64.b64encode('{"user":"' + user_id + '","pw":"' + password + '"}')

        server = self.hs.config.public_baseurl.rstrip('/')
        subject = u'''Nouveau mot de passe pour l'espace de travail sécurisé Watcha {server}'''.format(server=server)

        fields = {
                'title': subject,
                'full_name': display_name,
                'user_login': user.localpart,
                'setupToken': setupToken,
                'server': server,
        }

        send_mail(
            self.hs.config,
            user_info['email'],
            subject=subject,
            template_name='reset_password',
            fields=fields,
        )

        defer.returnValue((200, {}))


def register_servlets(hs, http_server):
    WatchaResetPasswordRestServlet(hs).register(http_server)
    WatchaRegisterRestServlet(hs).register(http_server)

    WatchaUpdateToMember(hs).register(http_server)
    WatchaUserIp(hs).register(http_server)
    WatchaAdminStats(hs).register(http_server)
    WatchaServerState(hs).register(http_server)
    WatchaUpdateMailRestServlet(hs).register(http_server)
    WatchaUserlistRestServlet(hs).register(http_server)
    WatchaRoomlistRestServlet(hs).register(http_server)
    WatchaExtendRoomlistRestServlet(hs).register(http_server)
    WatchaRoomMembershipRestServlet(hs).register(http_server)
    WatchaRoomNameRestServlet(hs).register(http_server)
    WatchaDisplayNameRestServlet(hs).register(http_server)
