# -*- coding: utf-8 -*-

import sys

import hmac
from hashlib import sha1

import logging

# requires python 2.7.7 or later
from hmac import compare_digest

from twisted.internet import defer

from synapse.api.errors import AuthError, SynapseError
from synapse.http.servlet import RestServlet, parse_json_object_from_request
from synapse.rest.client.v2_alpha._base import client_patterns
from synapse.util.watcha import generate_password, send_registration_email, compute_registration_token
from synapse.types import UserID, create_requester
from synapse.api.constants import Membership

logger = logging.getLogger(__name__)


@defer.inlineCallbacks
def _check_admin(auth, request):
    requester = yield auth.get_user_by_req(request)
    is_admin = yield auth.is_server_admin(requester.user)
    if not is_admin:
        raise AuthError(403, "You are not a server admin")


class Verification(RestServlet):
    '''API for the verification
    '''
    PATTERNS = client_patterns("/verification", v1=True)

    def __init__(self, hs):
        super(Verification, self).__init__()
        self.hs = hs
        self.store = hs.get_datastore()
        self.auth = hs.get_auth()
        self.handlers = hs.get_handlers()

    @defer.inlineCallbacks
    def on_GET(self, request):
        # yield _check_admin(self.auth, request)
        ret = yield self.handlers.verification_handler.verification_history()
        defer.returnValue((200, ret))

    @defer.inlineCallbacks
    def on_POST(self, request):
        parameter_json = parse_json_object_from_request(request)

        ret = yield self.handlers.verification_handler.post_message(parameter_json)
        defer.returnValue((200, ret))


def register_servlets(hs, http_server):
    Verification(hs).register(http_server)
