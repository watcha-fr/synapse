from twisted.internet import defer

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
    def post_message(self, parameter_json, hs):
        if 'message' in parameter_json and 'signature' in parameter_json:
            result = yield self.store.post_message(parameter_json["message"], parameter_json["signature"])

            user_id = parameter_json['user']
            if not user_id.startswith('@'):
                user_id = '@' + parameter_json['user'] + ':' + hs.get_config().server_name

            user = UserID.from_string(user_id)

            requester = create_requester(user_id)

            event_dict = {"type": "m.verification", "room_id": "0", "sender": user_id, "content": {"test":"blablabla"}}

            hs.get_event_creation_handler().create_and_send_nonmember_event(requester, event_dict)
        else:
            result = yield False
        defer.returnValue(result)
