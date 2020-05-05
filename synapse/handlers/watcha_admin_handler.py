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
        # TODO remove this - there is no 'watcha_room_list' in the store
        result = yield self.store.watcha_room_list()
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
        # TODO: rename to watcha_extended_room_list -- or better, to watcha_room_list since that one is not working
        result = yield self.store.watcha_extend_room_list()
        defer.returnValue(result)

    @defer.inlineCallbacks
    def watcha_update_mail(self, user_id, email):
        result = yield self.store.watcha_update_mail(user_id, email)
        defer.returnValue(result)

    @defer.inlineCallbacks
    def watcha_update_user_statut(self, user_id, statut_action, final_statut):
        user_statut = yield self.watcha_get_user_statut(user_id)

        if user_statut == final_statut:
            raise SynapseError(400, "This user has already %s status" % final_statut)
        if statut_action == "promote" and (user_statut == "admin" or final_statut == "partner"):
            raise SynapseError(400, "The promotion is not possible with this couple of user status (%s) and desired statut (%s)." % (user_statut, final_statut))
        elif (statut_action == "demote" and (user_statut == "partner" or final_statut == "admin")):
            raise SynapseError(400, "The demotion is not possible with this couple of user status (%s) and desired statut (%s)." % (user_statut, final_statut))

        yield self.store.watcha_update_user_statut(user_id, user_statut, final_statut)
        defer.returnValue(result)

    @defer.inlineCallbacks
    def watcha_get_user_statut(self, user_id):
        is_partner = yield self.hs.get_auth_handler().is_partner(user_id)
        is_admin = yield self.auth.is_server_admin(user_id)

        status = "member"

        if is_partner and is_admin:
            raise SynapseError(400, "A user can't be admin and partner too.")
        elif is_partner:
            status = "partner"
        elif is_admin:
            status = "admin"

        defer.returnValue(status)

    @defer.inlineCallbacks
    def watchaDeactivateAccount(self, user_id):
        result = yield self.store.watcha_deactivate_account(user_id)
        defer.returnValue(result)

    @defer.inlineCallbacks
    def watcha_server_state(self):
        result = yield self.store.watcha_server_state()
        defer.returnValue(result)

    @defer.inlineCallbacks
    def watcha_admin_stat(self, ranges=None):
        result = yield self.store.watcha_admin_stats(ranges)
        defer.returnValue(result)

    @defer.inlineCallbacks
    def watcha_user_ip(self, user_id):
        result = yield self.store.watcha_user_ip(user_id)
        defer.returnValue(result)

    @defer.inlineCallbacks
    def watcha_reactivate_account(self, user_id):
        result = yield self.store.watcha_reactivate_account(user_id)
        defer.returnValue(result)
