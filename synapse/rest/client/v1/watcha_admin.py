# -*- coding: utf-8 -*-
# Copyright 2014-2016 OpenMarket Ltd
# Copyright 2018 New Vector Ltd
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from twisted.internet import defer

from synapse.api.constants import Membership
from synapse.api.errors import AuthError, SynapseError
from synapse.types import UserID, create_requester
from synapse.http.servlet import parse_json_object_from_request

from .base import ClientV1RestServlet, client_path_patterns

import logging

logger = logging.getLogger(__name__)

class WatchaUserlistRestServlet(ClientV1RestServlet):

    PATTERNS = client_path_patterns("/watchauserlist")
    def __init__(self, hs):
        super(WatchaUserlistRestServlet, self).__init__(hs)
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

        ret = yield self.handlers.watcha_admin_handler.getUserList()
        defer.returnValue((200, ret))

class WatchaRoomlistRestServlet(ClientV1RestServlet):

    PATTERNS = client_path_patterns("/watcharoomlist")
    def __init__(self, hs):
        super(WatchaRoomlistRestServlet, self).__init__(hs)
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
        ret = yield self.handlers.watcha_admin_handler.getRoomList()
        defer.returnValue((200, ret))

class WatchaRoomMembershipRestServlet(ClientV1RestServlet):

    PATTERNS = client_path_patterns("/watcharoommembershib")
    def __init__(self, hs):
        super(WatchaRoomMembershipRestServlet, self).__init__(hs)
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
        ret = yield self.handlers.watcha_admin_handler.getRoomMembership()
        defer.returnValue((200, ret))

class WatchaRoomNameRestServlet(ClientV1RestServlet):

    PATTERNS = client_path_patterns("/watcharoomname")
    def __init__(self, hs):
        self.hs = hs
        self.store = hs.get_datastore()
        super(WatchaRoomNameRestServlet, self).__init__(hs)
        self.auth = hs.get_auth()
        self.handlers = hs.get_handlers()

    @defer.inlineCallbacks
    def on_GET(self, request):
        requester = yield self.auth.get_user_by_req(request)
        is_admin = yield self.auth.is_server_admin(requester.user)
        if not is_admin:
            raise AuthError(403, "You are not a server admin")
        ret = yield self.handlers.watcha_admin_handler.getRoomName()
        defer.returnValue((200, ret))

class WatchaDisplayNameRestServlet(ClientV1RestServlet):

    PATTERNS = client_path_patterns("/watchadisplayname")
    def __init__(self, hs):
        super(WatchaDisplayNameRestServlet, self).__init__(hs)
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
        ret = yield self.handlers.watcha_admin_handler.getDisplayName()
        defer.returnValue((200, ret))

class WatchaExtendRoomlistRestServlet(ClientV1RestServlet):
    PATTERNS = client_path_patterns("/watchaextendroomlist")
    def __init__(self, hs):
        super(WatchaExtendRoomlistRestServlet, self).__init__(hs)
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
        ret = yield self.handlers.watcha_admin_handler.extendRoomlist()
        defer.returnValue((200, ret))

class WatchaUpdateMailRestServlet(ClientV1RestServlet):
    PATTERNS = client_path_patterns("/watchaupdatemail/(?P<target_user_id>[^/]*)")
    def __init__(self, hs):
        super(WatchaUpdateMailRestServlet, self).__init__(hs)
        self.hs = hs
        self.store = hs.get_datastore()
        self.auth = hs.get_auth()
        self.handlers = hs.get_handlers()

    @defer.inlineCallbacks
    def on_POST(self, request, target_user_id):
        UserID.from_string(target_user_id)
        requester = yield self.auth.get_user_by_req(request)
        is_admin = yield self.auth.is_server_admin(requester.user)
        if not is_admin:
            raise AuthError(403, "You are not a server admin")
        params = parse_json_object_from_request(request)
        new_email = params['new_email']
        if not new_email:
            raise SynapseError(400, "Missing 'new_email' arg")
        ret = yield self.handlers.watcha_admin_handler.watchaUpdateMail(target_user_id, new_email)
        defer.returnValue((200, {}))

class WatchaUpdateToMember(ClientV1RestServlet):
    PATTERNS = client_path_patterns("/watchaupdatepartnertomember/(?P<target_user_id>[^/]*)")
    def __init__(self, hs):
        super(WatchaUpdateToMember, self).__init__(hs)
        self.hs = hs
        self.store = hs.get_datastore()
        self.auth = hs.get_auth()
        self.handlers = hs.get_handlers()

    @defer.inlineCallbacks
    def on_PUT(self, request, target_user_id):
        UserID.from_string(target_user_id)
        requester = yield self.auth.get_user_by_req(request)
        is_admin = yield self.auth.is_server_admin(requester.user)
        if not is_admin:
            raise AuthError(403, "You are not a server admin")
        ret = yield self.handlers.watcha_admin_handler.watchaUpdateToMember(target_user_id)
        defer.returnValue((200, {}))

def register_servlets(hs, http_server):
    WatchaUpdateToMember(hs).register(http_server)
    WatchaUpdateMailRestServlet(hs).register(http_server)
    WatchaUserlistRestServlet(hs).register(http_server)
    WatchaRoomlistRestServlet(hs).register(http_server)
    WatchaExtendRoomlistRestServlet(hs).register(http_server)
    WatchaRoomMembershipRestServlet(hs).register(http_server)
    WatchaRoomNameRestServlet(hs).register(http_server)
    WatchaDisplayNameRestServlet(hs).register(http_server)
