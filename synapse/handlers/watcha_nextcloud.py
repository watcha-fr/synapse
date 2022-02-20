import logging

from jsonschema.exceptions import SchemaError, ValidationError

from synapse.api.errors import (
    Codes,
    HttpResponseException,
    NextcloudError,
    SynapseError,
)

from ._base import BaseHandler

logger = logging.getLogger(__name__)

# echo -n watcha | md5sum  | head -c 10
NEXTCLOUD_GROUP_ID_PREFIX = "c4d96a06b7_"
# Nextcloud does not allow group id longer than 64 characters
NEXTCLOUD_GROUP_ID_LENGHT_LIMIT = 64 
NEXTCLOUD_CLIENT_ERRORS = (
    NextcloudError,
    SchemaError,
    ValidationError,
    HttpResponseException,
)


class NextcloudHandler(BaseHandler):
    def __init__(self, hs: "Homeserver"):
        self.store = hs.get_datastore()
        self.administration_handler = hs.get_administration_handler()
        self.event_creation_handler = hs.get_event_creation_handler()
        self.group_displayname_prefix = hs.config.nextcloud_group_displayname_prefix
        self.keycloak_client = hs.get_keycloak_client()
        self.nextcloud_client = hs.get_nextcloud_client()

    async def bind(self, requester_id: str, room_id: str, path: str):
        """Bind a Nextcloud folder with a room in three steps :
            1 - create a new Nextcloud group
            2 - add all room members in the new group
            3 - create a share on folder for the new group

        Args :
           requester_id: the mxid of the requester.
           room_id: the id of the room to bind.
           path: the path of the Nextcloud folder to bind.
        """
        await self.create_group(room_id)
        await self.add_room_members_to_group(room_id)
        await self.create_share(requester_id, room_id, path)

    async def create_group(self, room_id: str):
        """Create a Nextcloud group with specific id and displayname.

        Args:
            room_id: the id of the room
        """
        group_id = await self.build_group_id(room_id)
        group_displayname = await self.build_group_displayname(room_id)

        try:
            await self.nextcloud_client.add_group(group_id)
        except NEXTCLOUD_CLIENT_ERRORS as error:
            # Do not raise error if Nextcloud group already exist
            if isinstance(error, NextcloudError) and error.code == 102:
                logger.warn(
                    f"[watcha] add nextcloud group {group_id} - failed: the group already exists"
                )
            else:
                raise SynapseError(
                    500,
                    f"[watcha] add nextcloud group {group_id} - failed: {error}",
                    Codes.NEXTCLOUD_CAN_NOT_CREATE_GROUP,
                )

        await self.set_group_displayname(group_id, group_displayname)

    async def build_group_id(self, room_id: str):
        """Build the Nextcloud group id corresponding to an association of a pattern and room id

        Args:
            room_id: the id of the room
        """
        group_id = NEXTCLOUD_GROUP_ID_PREFIX + room_id
        return group_id[:NEXTCLOUD_GROUP_ID_LENGHT_LIMIT]

    async def build_group_displayname(self, room_id):
        """Build the Nextcloud group name corresponding to an association of a pattern and room name

        Args:
            room_id: the id of the room
        """
        room_name = await self.administration_handler.calculate_room_name(room_id)
        group_displayname = self.group_displayname_prefix + room_name
        return group_displayname

    async def set_group_displayname(self, group_id: str, group_displayname: str):
        """Set the displayname of a Nextcloud group

        Args:
            group_id: the id of group
            group_displayname: the displayname of the group
        """
        try:
            await self.nextcloud_client.set_group_displayname(
                group_id, group_displayname
            )
        except NEXTCLOUD_CLIENT_ERRORS as error:
            logger.warn(
                f"[watcha] set displayname for group {group_id} - failed: {error}"
            )

    async def add_room_members_to_group(self, room_id: str):
        """Add all members of a room to a Nextcloud group.

        Args:
            room_id: the id of the room which the Nextcloud group name is infered from.
        """
        group_id = await self.build_group_id(room_id)
        user_ids = await self.store.get_users_in_room(room_id)

        for user_id in user_ids:
            nextcloud_username = await self.store.get_username(user_id)
            try:
                await self.nextcloud_client.add_user_to_group(
                    nextcloud_username, group_id
                )
            except NEXTCLOUD_CLIENT_ERRORS as error:
                # Do not raise error if some users can not be added to group
                if isinstance(error, NextcloudError) and (error.code in (103, 105)):
                    logger.error(
                        f"[watcha] add user {user_id} to group {group_id} - failed: {error}"
                    )
                else:
                    raise SynapseError(
                        500,
                        f"[watcha] add members of room {room_id} to group {group_id} - failed: {error}",
                        Codes.NEXTCLOUD_CAN_NOT_ADD_MEMBERS_TO_GROUP,
                    )

    async def create_share(self, requester_id: str, room_id: str, path: str):
        """Create a new share on folder for a specific Nextcloud group.
        Before that, delete old existing share for this group if it exist.

        Args:
            requester_id: the mxid of the requester.
            room_id: the id of the room to bind.
            path: the path of the Nextcloud folder to bind.
        """
        group_id = await self.build_group_id(room_id)
        nextcloud_username = await self.store.get_username(requester_id)

        old_share_id = await self.store.get_share_id(room_id)
        if old_share_id:
            try:
                await self.nextcloud_client.unshare(nextcloud_username, old_share_id)
            except NEXTCLOUD_CLIENT_ERRORS as error:
                logger.error(f"[watcha] unshare {old_share_id} - failed: {error}")

        try:
            new_share_id = await self.nextcloud_client.share(
                nextcloud_username, path, group_id
            )
        except NEXTCLOUD_CLIENT_ERRORS as error:
            await self.unbind(room_id)
            # raise 404 error if folder to share do not exist
            http_code = (
                error.code
                if isinstance(error, NextcloudError) and error.code == 404
                else 500
            )
            raise SynapseError(
                http_code,
                f"[watcha] share folder {path} with group {group_id} - failed: {error}",
                Codes.NEXTCLOUD_CAN_NOT_SHARE,
            )

        await self.store.register_share(room_id, new_share_id)

    async def unbind(self, room_id: str):
        """Unbind a Nextcloud folder from a room.

        Args :
            room_id: the id of the room to bind
        """
        group_id = await self.build_group_id(room_id)
        try:
            await self.nextcloud_client.delete_group(group_id)
        except NEXTCLOUD_CLIENT_ERRORS as error:
            logger.error(
                f"[watcha] delete nextcloud group {group_id} - failed: {error}"
            )

        await self.store.delete_share(room_id)

    async def update_group(self, user_id: str, room_id: str, membership: str):
        """Update a Nextcloud group by adding or removing users.
        If membership is 'join' or 'invite', the user is add to the Nextcloud group infered from the room.
        Else, the users is removed from the group.

        Args:
            user_id: mxid of the user concerned by the membership event
            room_id: the id of the room where the membership event was sent
            membership: membership event. Can be 'invite', 'join', 'kick' or 'leave'
        """
        group_id = await self.build_group_id(room_id)
        nextcloud_username = await self.store.get_username(user_id)

        if membership in ("invite", "join"):
            try:
                await self.nextcloud_client.add_user_to_group(
                    nextcloud_username, group_id
                )
            except NEXTCLOUD_CLIENT_ERRORS as error:
                logger.warn(
                    f"[watcha] add user {user_id} to group {group_id} - failed: {error}"
                )
        else:
            try:
                await self.nextcloud_client.remove_user_from_group(
                    nextcloud_username, group_id
                )
            except NEXTCLOUD_CLIENT_ERRORS as error:
                logger.warn(
                    f"[watcha] remove user {user_id} from group {group_id} - failed: {error}"
                )
