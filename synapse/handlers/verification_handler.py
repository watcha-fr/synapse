from twisted.internet import defer

from ._base import BaseHandler

import logging

logger = logging.getLogger(__name__)


class VerificationHandler(BaseHandler):
    def __init__(self, hs):
        super(VerificationHandler, self).__init__(hs)

    @defer.inlineCallbacks
    def verification_history(self):
        result = yield self.store.verification_history()
        defer.returnValue(result)

    @defer.inlineCallbacks
    def post_message(self, parameter_json):
        if 'message' in parameter_json and 'signature' in parameter_json:
            result = yield self.store.post_message(parameter_json["message"], parameter_json["signature"])
            defer.returnValue(result)
        else:
            result = yield False
            defer.returnValue(result)
