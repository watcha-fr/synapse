from twisted.internet import defer

from ._base import BaseHandler

import logging

logger = logging.getLogger(__name__)


class VerificationHandler(BaseHandler):
    @defer.inlineCallbacks
    def verification_history(self, n):
        if not(type(n)==str):
            n = "0"
        result = yield self.store.verification_history(n)
        defer.returnValue(result)

    @defer.inlineCallbacks
    def post_message(self, parameter_json):
        if 'message' in parameter_json and 'signature' in parameter_json:
            result = yield self.store.post_message(parameter_json["message"], parameter_json["signature"])
        else:
            result = yield False
        defer.returnValue(result)
