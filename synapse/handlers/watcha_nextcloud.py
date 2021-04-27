import logging

from jsonschema.exceptions import SchemaError, ValidationError

from synapse.api.errors import SynapseError

from ._base import BaseHandler

logger = logging.getLogger(__name__)

# echo -n watcha | md5sum  | head -c 10
NEXTCLOUD_GROUP_NAME_PREFIX = "c4d96a06b7_"


class NextcloudHandler(BaseHandler):
    def __init__(self, hs: "Homeserver"):
        self.store = hs.get_datastore()
        self.event_creation_handler = hs.get_event_creation_handler()
        self.keycloak_client = hs.get_keycloak_client()
        self.nextcloud_client = hs.get_nextcloud_client()

    async def unbind(self, room_id: str):
        """Unbind a Nextcloud folder from a room.

        Args :
            room_id: the id of the room to bind.
        """
        await self.nextcloud_client.delete_group(NEXTCLOUD_GROUP_NAME_PREFIX + room_id)
        await self.store.delete_share(room_id)

    async def bind(self, requester_id: str, room_id: str, path: str):
        """Bind a Nextcloud folder with a room.

        Args :
           requester_id: the mxid of the requester.
           room_id: the id of the room to bind.
           path: the path of the Nextcloud folder to bind.
        """
        group_name = NEXTCLOUD_GROUP_NAME_PREFIX + room_id
        await self.nextcloud_client.add_group(group_name)
        await self.add_room_users_to_nextcloud_group(room_id)

        nextcloud_username = await self.store.get_username(requester_id)

        old_share_id = await self.store.get_share_id(room_id)
        if old_share_id:
            await self.nextcloud_client.unshare(nextcloud_username, old_share_id)

        new_share_id = await self.nextcloud_client.share(
            nextcloud_username, path, group_name
        )
        await self.store.register_share(room_id, new_share_id)

    async def add_room_users_to_nextcloud_group(self, room_id: str):
        """Add all users of a room to a Nextcloud group.

        Args:
            room_id: the id of the room which the Nextcloud group name is infered from.
        """
        group_name = NEXTCLOUD_GROUP_NAME_PREFIX + room_id
        user_ids = await self.store.get_users_in_room(room_id)

        for user_id in user_ids:
            nextcloud_username = await self.store.get_username(user_id)
            try:
                await self.nextcloud_client.add_user_to_group(
                    nextcloud_username, group_name
                )
            except (SynapseError, ValidationError, SchemaError) as error:
                logger.warn(
                    f"[watcha] add user {user_id} to group {group_name} - failed"
                )

    async def update_group(self, user_id: str, room_id: str, membership: str):
        """Update a Nextcloud group by adding or removing users.
        If membership is 'join' or 'invite', the user is add to the Nextcloud group infered from the room.
        Else, the users is removed from the group.

        Args:
            user_id: mxid of the user concerned by the membership event
            room_id: the id of the room where the membership event was sent
            membership: membership event. Can be 'invite', 'join', 'kick' or 'leave'
        """
        group_name = NEXTCLOUD_GROUP_NAME_PREFIX + room_id
        nextcloud_username = await self.store.get_username(user_id)

        if membership in ("invite", "join"):
            try:
                await self.nextcloud_client.add_user_to_group(
                    nextcloud_username, group_name
                )
            except (SynapseError, ValidationError, SchemaError):
                logger.warn(
                    f"[watcha] add user {user_id} to group {group_name} - failed"
                )
        else:
            try:
                await self.nextcloud_client.remove_user_from_group(
                    nextcloud_username, group_name
                )
            except (SynapseError, ValidationError, SchemaError):
                logger.warn(
                    f"[watcha] remove user {user_id} from group {group_name} - failed"
                )
