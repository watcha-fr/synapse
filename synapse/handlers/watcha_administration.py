import logging
from typing import Dict

from synapse.api.constants import EventTypes, Membership
from synapse.api.errors import SynapseError
from synapse.push.presentable_names import descriptor_from_member_events
from synapse.types import StateMap, UserID

from ._base import BaseHandler

logger = logging.getLogger(__name__)


class AdministrationHandler(BaseHandler):
    def __init__(self, hs: "HomeServer"):
        super().__init__(hs)
        self.store = hs.get_datastore()
        self.auth = hs.get_auth()
        self.auth_handler = hs.get_auth_handler()

    async def get_room_name(self, room_id: str):
        """Get the name of a room
        Inspired by Matrix calculate_room_name function

        Args:
            room_id: the id of the room
        """

        def _state_as_two_level_dict(state: StateMap[str]) -> Dict[str, Dict[str, str]]:
            ret = {}  # type: Dict[str, Dict[str, str]]
            for k, v in state.items():
                ret.setdefault(k[0], {})[k[1]] = v
            return ret

        room_state_ids = await self.state_handler.get_current_state_ids(room_id)
        if (EventTypes.Name, "") in room_state_ids:
            name_event = await self.store.get_event(
                room_state_ids[(EventTypes.Name, "")]
            )
            return name_event.content["name"]

        all_members = []
        room_state_bytype_ids = _state_as_two_level_dict(room_state_ids)
        if EventTypes.Member in room_state_bytype_ids:
            member_events = await self.store.get_events(
                room_state_bytype_ids[EventTypes.Member].values()
            )
            all_members = [
                event
                for event in member_events.values()
                if event.content.get("membership") == Membership.JOIN
                or event.content.get("membership") == Membership.INVITE
            ]
            # Sort the member events oldest-first so the we name people in the
            # order the joined (it should at least be deterministic rather than
            # dictionary iteration order)
            all_members.sort(key=lambda e: e.origin_server_ts)

        return descriptor_from_member_events(all_members)

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
