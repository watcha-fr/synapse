from twisted.internet import defer
import re

from ._base import BaseHandler

from synapse.types import UserID, create_requester

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
    def post_message(self, parameter_json, hs, requester):
        if 'message' in parameter_json and 'signature' in parameter_json:
            regex = re.search("^@[a-z0-9=_\-./]+:[a-zA-Z0-9./_\-]+ \/ [A-Z]+ : (entering)|(verifying) [A-Z]?$", parameter_json["message"])

            if (not(regex)):
                result = False
            else:
                result = yield self.store.post_message(parameter_json["message"], parameter_json["signature"])
                
                # sounds good, doesn’t work
                # we need a real room to do that (mostly because we need to know whom to notify)
                #event_dict = {"type": "m.verification","room_id": "0","sender": requester.user.to_string(),"content": {"test":"test"}}
                #hs.get_event_creation_handler().create_and_send_nonmember_event(requester,event_dict)
                
                # TODO : send notify other connected users that a new line has been added
        else:
            result = False
        defer.returnValue(result)
