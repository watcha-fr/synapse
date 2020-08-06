from twisted.internet import defer
from synapse.api.errors import SynapseError
from ._base import BaseHandler

import logging

logger = logging.getLogger(__name__)

class WatchaAdminHandler(BaseHandler):
    def __init__(self, hs):
        super(WatchaAdminHandler, self).__init__(hs)

    async def watcha_user_list(self):
        users = await self.store.watcha_user_list()

        result = []
        for user in users:
            role = await self.watcha_get_user_role(user["user_id"])

            result.append({
                "user_id": user["user_id"],
                "email_address": user["email_address"],
                "display_name": user["display_name"],
                "role": role,
                "status": user["status"],
                "last_seen": user["last_seen"],
                "creation_ts": user["creation_ts"],
            })

        return 'result'

    async def watcha_room_membership(self):
        result = await self.store.watcha_room_membership()
        return result

    async def watcha_room_name(self):
        result = await self.store.watcha_room_name()
        return result

    async def watcha_display_name(self):
        # TODO this cannot work - there is no store.watchauser_display_name method
        # Fortunately it doesn't seem to be called :)
        result = await self.store.watchauser_display_name()
        return result

    async def watcha_room_list(self):
        result = await self.store.watcha_room_list()
        return result

    async def watcha_update_mail(self, user_id, email):
        result = await self.store.watcha_update_mail(user_id, email)
        return result

    async def watcha_update_user_role(self, user_id, role):
        user_role =  await self.watcha_get_user_role(user_id)

        if user_role == role:
            raise SynapseError(400, "This user has already the %s role" % role)

        await self.store.watcha_update_user_role(user_id, role)

        return role

    async def watcha_get_user_role(self, user_id):
        is_partner =  await self.hs.get_auth_handler().is_partner(user_id)
        is_admin =  await self.hs.get_auth_handler().is_admin(user_id)

        role = "collaborator"

        if is_partner and is_admin:
            raise SynapseError(400, "A user can't be admin and partner too.")
        elif is_partner:
            role = "partner"
        elif is_admin:
            role = "administrator"

        return role

    async def watchaDeactivateAccount(self, user_id):
        result =  await self.store.watcha_deactivate_account(user_id)
        return result

    async def watcha_admin_stat(self):
        result =  await self.store.watcha_admin_stats()
        return result

    async def watcha_user_ip(self, user_id):
        result =  await self.store.watcha_user_ip(user_id)
        return result

    async def watcha_reactivate_account(self, user_id):
        result =  await self.store.watcha_reactivate_account(user_id)
        return result
