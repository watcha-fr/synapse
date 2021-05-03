import logging

from synapse.api.constants import EventTypes
from synapse.api.errors import SynapseError
from synapse.types import UserID

from ._base import BaseHandler

logger = logging.getLogger(__name__)


class AdministrationHandler(BaseHandler):
    def __init__(self, hs: "HomeServer"):
        super().__init__(hs)
        self.auth = hs.get_auth()
        self.auth_handler = hs.get_auth_handler()

    async def get_room_name(self, room_id: str):
        """Get the name of a room

        Args:
            room_id: the id of the room
        """
        room_state = await self.state_handler.get_current_state(room_id)
        room_name_event = room_state.get((EventTypes.Name, ""))
        if not room_name_event:
            return

        return room_name_event.content.get("name", "")

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

    async def watcha_update_user_role(self, user_id, role):
        user_role = await self.get_user_role(user_id)

        if user_role == role:
            raise SynapseError(400, "This user has already the %s role" % role)

        await self.store.watcha_update_user_role(user_id, role)

        return role

    async def get_user_role(self, user_id):
        """Retrieve user role [administrator|collaborator|partner]

        Returns:
            The user role.
        """
        is_partner = await self.auth_handler.is_partner(user_id)
        is_admin = await self.auth.is_server_admin(UserID.from_string(user_id))

        if is_partner and is_admin:
            raise SynapseError(400, "A user can't be admin and partner too.")
        elif is_partner:
            role = "partner"
        elif is_admin:
            role = "administrator"
        else:
            role = "collaborator"

        return role
