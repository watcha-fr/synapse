from twisted.internet import defer
from synapse.api.errors import SynapseError
from ._base import BaseHandler

import logging

logger = logging.getLogger(__name__)

class WatchaAdminHandler(BaseHandler):
    def __init__(self, hs):
        super(WatchaAdminHandler, self).__init__(hs)

    @defer.inlineCallbacks
    def watcha_user_list(self):
        users = yield self.store.watcha_user_list()

        result = []
        for user in users:
            role = yield self.watcha_get_user_role(user["user_id"])
            status = yield self.watcha_get_user_status(user["user_id"])
            result.append({
                "user_id": user["user_id"],
                "email_address": user["email_address"],
                "display_name": user["display_name"],
                "role": role,
                "status": status,
                "last_seen": user["last_seen"],
                "creation_ts": user["creation_ts"],
            })

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
    def watcha_room_list(self):
        result = yield self.store.watcha_room_list()
        defer.returnValue(result)

    @defer.inlineCallbacks
    def watcha_update_mail(self, user_id, email):
        result = yield self.store.watcha_update_mail(user_id, email)
        defer.returnValue(result)

    @defer.inlineCallbacks
    def watcha_update_user_role(self, user_id, role):
        user_role = yield self.watcha_get_user_role(user_id)

        if user_role == role:
            raise SynapseError(400, "This user has already the %s role" % role)

        yield self.store.watcha_update_user_role(user_id, role)

        defer.returnValue(role)

    @defer.inlineCallbacks
    def watcha_get_user_role(self, user_id):
        is_partner = yield self.hs.get_auth_handler().is_partner(user_id)
        is_admin = yield self.hs.get_auth_handler().is_admin(user_id)

        role = "collaborator"

        if is_partner and is_admin:
            raise SynapseError(400, "A user can't be admin and partner too.")
        elif is_partner:
            role = "partner"
        elif is_admin:
            role = "administrator"

        defer.returnValue(role)

    @defer.inlineCallbacks
    def watcha_get_user_status(self, user_id):
        result = yield self.store.watcha_get_user_status(user_id)
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
