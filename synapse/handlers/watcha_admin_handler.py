from twisted.internet import defer

from ._base import BaseHandler

import logging

logger = logging.getLogger(__name__)

class WatchaAdminHandler(BaseHandler):
    def __init__(self, hs):
        super(WatchaAdminHandler, self).__init__(hs)

    @defer.inlineCallbacks
    def getUserList(self):
        ret = yield self.store.get_watchauser_list()
        defer.returnValue(ret)

    @defer.inlineCallbacks
    def getRoomList(self):
        ret = yield self.store.get_watcharoom_list()
        defer.returnValue(ret)

    @defer.inlineCallbacks
    def getRoomMembership(self):
        ret = yield self.store.get_watcharoom_membership()
        defer.returnValue(ret)

    @defer.inlineCallbacks
    def getRoomName(self):
        ret = yield self.store.get_watcharoom_name()
        defer.returnValue(ret)

    @defer.inlineCallbacks
    def getDisplayName(self):
        ret = yield self.store.get_watchauser_display_name()
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
    def watchaUpdateToMember(self, userId, email):
        ret = yield self.store.watcha_update_to_member(userId)
        defer.returnValue(ret)
