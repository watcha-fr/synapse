from twisted.internet import defer

from ._base import BaseHandler

import logging

logger = logging.getLogger(__name__)

class WatchaAdminHandler(BaseHandler):
    def __init__(self, hs):
        super(WatchaAdminHandler, self).__init__(hs)

    @defer.inlineCallbacks
    def watcha_user_list(self):
        ret = yield self.store.watcha_user_list()
        defer.returnValue(ret)

    @defer.inlineCallbacks
    def watcha_room_list(self):
        ret = yield self.store.watcharoom_list()
        defer.returnValue(ret)

    @defer.inlineCallbacks
    def watcha_room_membership(self):
        ret = yield self.store.watcha_room_membership()
        defer.returnValue(ret)

    @defer.inlineCallbacks
    def watcha_room_name(self):
        ret = yield self.store.watcharoom_name()
        defer.returnValue(ret)

    @defer.inlineCallbacks
    def watcha_display_name(self):
        ret = yield self.store.watchauser_display_name()
        defer.returnValue(ret)

    @defer.inlineCallbacks
    def watcha_extend_room_list(self):
        ret = yield self.store.watcha_extend_room_list()
        defer.returnValue(ret)

    @defer.inlineCallbacks
    def watcha_update_mail(self, userId, email):
        ret = yield self.store.watcha_update_mail(userId, email)
        defer.returnValue(ret)

    @defer.inlineCallbacks
    def watcha_update_to_member(self, userId):
        ret = yield self.store.watcha_update_to_member(userId)
        defer.returnValue(ret)

    @defer.inlineCallbacks
    def watchaDeactivateAccount(self, userId):
        ret = yield self.store.watcha_deactivate_account(userId)
        defer.returnValue(ret)

    @defer.inlineCallbacks
    def watcha_server_state(self):
        ret = yield self.store.watcha_server_state()
        defer.returnValue(ret)

    @defer.inlineCallbacks
    def watcha_log(self):
        ret = yield self.store.watcha_log()
        defer.returnValue(ret)

    @defer.inlineCallbacks
    def watcha_admin_stat(self):
        ret = yield self.store.watcha_admin_stats()
        defer.returnValue(ret)

    @defer.inlineCallbacks
    def watcha_user_ip(self, userId):
        ret = yield self.store.watcha_user_ip(userId)
        defer.returnValue(ret)

    @defer.inlineCallbacks
    def watcha_reactivate_account(self, userId):
        ret = yield self.store.watcha_reactivate_account(userId)
        defer.returnValue(ret)
