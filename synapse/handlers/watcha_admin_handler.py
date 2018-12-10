from twisted.internet import defer

from ._base import BaseHandler

import logging

logger = logging.getLogger(__name__)

class WatchaAdminHandler(BaseHandler):
    def __init__(self, hs):
        super(WatchaAdminHandler, self).__init__(hs)

    @defer.inlineCallbacks
    def watcha_user_list(self):
        result = yield self.store.watcha_user_list()
        defer.returnValue(result)

    @defer.inlineCallbacks
    def watcha_room_list(self):
        result = yield self.store.watcharoom_list()
        defer.returnValue(result)

    @defer.inlineCallbacks
    def watcha_room_membership(self):
        result = yield self.store.watcha_room_membership()
        defer.returnValue(result)

    @defer.inlineCallbacks
    def watcha_room_name(self):
        result = yield self.store.watcha_room_name()
        defer.returnValue(result)

    @defer.inlineCallbacks
    def watcha_display_name(self):
        # TODO this cannot work - there is no store.watchauser_display_name method
        # Fortunately it doesn't seem to be called :)
        result = yield self.store.watchauser_display_name()
        defer.returnValue(result)

    @defer.inlineCallbacks
    def watcha_extend_room_list(self):
        result = yield self.store.watcha_extend_room_list()
        defer.returnValue(result)

    @defer.inlineCallbacks
    def watcha_update_mail(self, user_id, email):
        result = yield self.store.watcha_update_mail(user_id, email)
        defer.returnValue(result)

    @defer.inlineCallbacks
    def watcha_update_to_member(self, user_id):
        result = yield self.store.watcha_update_to_member(user_id)
        defer.returnValue(result)

    @defer.inlineCallbacks
    def watchaDeactivateAccount(self, user_id):
        result = yield self.store.watcha_deactivate_account(user_id)
        defer.returnValue(result)

    @defer.inlineCallbacks
    def watcha_server_state(self):
        result = yield self.store.watcha_server_state()
        defer.returnValue(result)

    @defer.inlineCallbacks
    def watcha_log(self):
        result = yield self.store.watcha_log()
        defer.returnValue(result)

    @defer.inlineCallbacks
    def watcha_admin_stat(self):
        result = yield self.store.watcha_admin_stats()
        defer.returnValue(result)

    @defer.inlineCallbacks
    def watcha_user_ip(self, user_id):
        result = yield self.store.watcha_user_ip(user_id)
        defer.returnValue(result)

    @defer.inlineCallbacks
    def watcha_reactivate_account(self, user_id):
        result = yield self.store.watcha_reactivate_account(user_id)
        defer.returnValue(result)
