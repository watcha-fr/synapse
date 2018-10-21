from twisted.internet import defer

from ._base import BaseHandler

import logging

logger = logging.getLogger(__name__)

class WatchaAdminHandler(BaseHandler):
    def __init__(self, hs):
        super(WatchaAdminHandler, self).__init__(hs)

    @defer.inlineCallbacks
    def getUserList(self):
        ret = yield self.store.get_watcha_user_list()
        defer.returnValue(ret)

    @defer.inlineCallbacks
    def getRoomList(self):
        ret = yield self.store.get_watcha_room_list()
        defer.returnValue(ret)

    @defer.inlineCallbacks
    def getRoomMembership(self):
        ret = yield self.store.get_watcha_room_membership()
        defer.returnValue(ret)

    @defer.inlineCallbacks
    def getRoomName(self):
        ret = yield self.store.get_watcha_room_name()
        defer.returnValue(ret)

    @defer.inlineCallbacks
    def getDisplayName(self):
        ret = yield self.store.get_watcha_user_display_name()
        defer.returnValue(ret)

    @defer.inlineCallbacks
    def extendRoomlist(self):
        ret = yield self.store.get_watcha_extend_room_list()
        defer.returnValue(ret)

    @defer.inlineCallbacks
    def watchaUpdateMail(self, userId, email):
        ret = yield self.store.watcha_update_mail(userId, email)
        defer.returnValue(ret)

    @defer.inlineCallbacks
    def watchaUpdateToMember(self, userId):
        ret = yield self.store.watcha_update_to_member(userId)
        defer.returnValue(ret)

    @defer.inlineCallbacks
    def watchaDeactivateAccount(self, userId):
        ret = yield self.store.watcha_deactivate_account(userId)
        defer.returnValue(ret)
