# -*- coding: utf-8 -*-

from twisted.internet import defer

from synapse.api.constants import Membership
from synapse.api.errors import AuthError, SynapseError
from synapse.types import UserID, create_requester
from synapse.http.servlet import parse_json_object_from_request

from .base import ClientV1RestServlet, client_path_patterns

import logging

logger = logging.getLogger(__name__)

@defer.inlineCallbacks
def check_admin(auth, request):
    requester = yield auth.get_user_by_req(request)
    is_admin = yield auth.is_server_admin(requester.user)
    if not is_admin:
        raise AuthError(403, "You are not a server admin")
    return

class WatchaUserlistRestServlet(ClientV1RestServlet):

    PATTERNS = client_path_patterns("/watcha_user_list")
    def __init__(self, hs):
        super(WatchaUserlistRestServlet, self).__init__(hs)
        self.auth = hs.get_auth()
        self.handlers = hs.get_handlers()

    @defer.inlineCallbacks
    def on_GET(self, request):
        yield check_admin(self.auth, request)
        ret = yield self.handlers.watcha_admin_handler.getUserList()
        defer.returnValue((200, ret))

class WatchaRoomlistRestServlet(ClientV1RestServlet):

    PATTERNS = client_path_patterns("/watcha_room_list")
    def __init__(self, hs):
        super(WatchaRoomlistRestServlet, self).__init__(hs)
        self.auth = hs.get_auth()
        self.handlers = hs.get_handlers()

    @defer.inlineCallbacks
    def on_GET(self, request):
        yield check_admin(self.auth, request)
        ret = yield self.handlers.watcha_admin_handler.getRoomList()
        defer.returnValue((200, ret))

class WatchaRoomMembershipRestServlet(ClientV1RestServlet):

    PATTERNS = client_path_patterns("/watcha_room_membership")
    def __init__(self, hs):
        super(WatchaRoomMembershipRestServlet, self).__init__(hs)
        self.auth = hs.get_auth()
        self.handlers = hs.get_handlers()

    @defer.inlineCallbacks
    def on_GET(self, request):
        yield check_admin(self.auth, request)
        ret = yield self.handlers.watcha_admin_handler.getRoomMembership()
        defer.returnValue((200, ret))

class WatchaRoomNameRestServlet(ClientV1RestServlet):

    PATTERNS = client_path_patterns("/watcha_room_name")
    def __init__(self, hs):
        super(WatchaRoomNameRestServlet, self).__init__(hs)
        self.auth = hs.get_auth()
        self.handlers = hs.get_handlers()

    @defer.inlineCallbacks
    def on_GET(self, request):
        yield check_admin(self.auth, request)
        ret = yield self.handlers.watcha_admin_handler.getRoomName()
        defer.returnValue((200, ret))

class WatchaDisplayNameRestServlet(ClientV1RestServlet):

    PATTERNS = client_path_patterns("/watcha_display_name")
    def __init__(self, hs):
        super(WatchaDisplayNameRestServlet, self).__init__(hs)
        self.auth = hs.get_auth()
        self.handlers = hs.get_handlers()

    @defer.inlineCallbacks
    def on_GET(self, request):
        yield check_admin(self.auth, request)
        ret = yield self.handlers.watcha_admin_handler.getDisplayName()
        defer.returnValue((200, ret))

class WatchaExtendRoomlistRestServlet(ClientV1RestServlet):
    PATTERNS = client_path_patterns("/watcha_extend_room_list")
    def __init__(self, hs):
        super(WatchaExtendRoomlistRestServlet, self).__init__(hs)
        self.auth = hs.get_auth()
        self.handlers = hs.get_handlers()

    @defer.inlineCallbacks
    def on_GET(self, request):
        yield check_admin(self.auth, request)
        ret = yield self.handlers.watcha_admin_handler.extendRoomlist()
        defer.returnValue((200, ret))

class WatchaUpdateMailRestServlet(ClientV1RestServlet):
    PATTERNS = client_path_patterns("/watcha_update_email/(?P<target_user_id>[^/]*)")
    def __init__(self, hs):
        super(WatchaUpdateMailRestServlet, self).__init__(hs)
        self.auth = hs.get_auth()
        self.handlers = hs.get_handlers()

    @defer.inlineCallbacks
    def on_PUT(self, request, target_user_id):
        yield check_admin(self.auth, request)
        params = parse_json_object_from_request(request)
        new_email = params['new_email']
        if not new_email:
            raise SynapseError(400, "Missing 'new_email' arg")
        yield self.handlers.watcha_admin_handler.watchaUpdateMail(target_user_id, new_email)
        defer.returnValue((200, {}))

class WatchaUpdateToMember(ClientV1RestServlet):
    PATTERNS = client_path_patterns("/watcha_update_partner_to_member/(?P<target_user_id>[^/]*)")
    def __init__(self, hs):
        super(WatchaUpdateToMember, self).__init__(hs)
        self.auth = hs.get_auth()
        self.handlers = hs.get_handlers()

    @defer.inlineCallbacks
    def on_PUT(self, request, target_user_id):
        yield check_admin(self.auth, request)
        yield self.handlers.watcha_admin_handler.watchaUpdateToMember(target_user_id)
        defer.returnValue((200, {}))

class WatchaServerState(ClientV1RestServlet):

    PATTERNS = client_path_patterns("/watcha_server_state")
    def __init__(self, hs):
        super(WatchaServerState, self).__init__(hs)
        self.auth = hs.get_auth()
        self.handlers = hs.get_handlers()

    @defer.inlineCallbacks
    def on_GET(self, request):
        yield check_admin(self.auth, request)
        ret = yield self.handlers.watcha_admin_handler.watchaServerState()
        defer.returnValue((200, ret))

class WatchaLog(ClientV1RestServlet):

    PATTERNS = client_path_patterns("/watcha_log")
    def __init__(self, hs):
        super(WatchaLog, self).__init__(hs)
        self.auth = hs.get_auth()
        self.handlers = hs.get_handlers()

    @defer.inlineCallbacks
    def on_GET(self, request):
        yield check_admin(self.auth, request)
        ret = yield self.handlers.watcha_admin_handler.watchaLog()
        defer.returnValue((200, ret))

class WatchaAdminStats(ClientV1RestServlet):

    PATTERNS = client_path_patterns("/watcha_admin_stats")
    def __init__(self, hs):
        super(WatchaAdminStats, self).__init__(hs)
        self.hs = hs
        self.store = hs.get_datastore()
        self.auth = hs.get_auth()
        self.handlers = hs.get_handlers()

    @defer.inlineCallbacks
    def on_GET(self, request):
        requester = yield self.auth.get_user_by_req(request)
        is_admin = yield self.auth.is_server_admin(requester.user)
        if not is_admin:
            raise AuthError(403, "You are not a server admin")
        ret = yield self.handlers.watcha_admin_handler.WatchaAdminStats()
        defer.returnValue((200, ret))

def register_servlets(hs, http_server):
    WatchaUpdateToMember(hs).register(http_server)
    WatchaAdminStats(hs).register(http_server)
    WatchaServerState(hs).register(http_server)
    WatchaUpdateMailRestServlet(hs).register(http_server)
    WatchaUserlistRestServlet(hs).register(http_server)
    WatchaRoomlistRestServlet(hs).register(http_server)
    WatchaExtendRoomlistRestServlet(hs).register(http_server)
    WatchaRoomMembershipRestServlet(hs).register(http_server)
    WatchaRoomNameRestServlet(hs).register(http_server)
    WatchaDisplayNameRestServlet(hs).register(http_server)
    WatchaLog(hs).register(http_server)
