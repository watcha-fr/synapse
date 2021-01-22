import logging

from synapse.api.errors import SynapseError

from ._base import BaseHandler

logger = logging.getLogger(__name__)


class AdministrationHandler(BaseHandler):
    def __init__(self, hs: "HomeServer"):
        super().__init__(hs)
        self.auth_handler = hs.get_auth_handler()

    async def watcha_user_list(self):
        users = await self.store.watcha_user_list()

        result = []
        for user in users:
            role = await self.get_user_role(user["user_id"])

            result.append(
                {
                    "user_id": user["user_id"],
                    "email_address": user["email_address"],
                    "display_name": user["display_name"],
                    "role": role,
                    "last_seen": user["last_seen"],
                    "creation_ts": user["creation_ts"],
                }
            )

        return result

    async def watcha_room_membership(self):
        result = await self.store.watcha_room_membership()
        return result

    async def watcha_room_list(self):
        result = await self.store.watcha_room_list()
        return result

    async def watcha_update_mail(self, user_id, email):
        result = await self.store.watcha_update_mail(user_id, email)
        return result

    async def watcha_update_user_role(self, user_id, role):
        user_role = await self.get_user_role(user_id)

        if user_role == role:
            raise SynapseError(400, "This user has already the %s role" % role)

        await self.store.watcha_update_user_role(user_id, role)

        return role

    async def get_user_role(self, user_id):
        """Retrieves user role. It can be 'administrator', 'collaborator' or 'partner'

        Returns:
            The user role.
        """
        is_partner = await self.auth_handler.is_partner(user_id)
        is_admin = await self.auth_handler.is_admin(user_id)

        if is_partner and is_admin:
            raise SynapseError(400, "A user can't be admin and partner too.")
        elif is_partner:
            role = "partner"
        elif is_admin:
            role = "administrator"
        else:
            role = "collaborator"

        return role

    async def watcha_admin_stat(self):
        result = await self.store.watcha_admin_stats()
        return result

    async def watcha_user_ip(self, user_id):
        result = await self.store.watcha_user_ip(user_id)
        return result
