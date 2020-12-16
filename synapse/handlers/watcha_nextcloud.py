import logging
from jsonschema.exceptions import ValidationError, SchemaError
from pathlib import Path

from ._base import BaseHandler
from synapse.api.constants import EventTypes
from synapse.api.errors import SynapseError
from synapse.http.watcha_keycloak_client import KeycloakClient
from synapse.http.watcha_nextcloud_client import NextcloudClient
from synapse.types import (
    create_requester,
    get_localpart_from_id,
    map_username_to_mxid_localpart,
    decode_localpart,
)

logger = logging.getLogger(__name__)

# echo -n watcha | md5sum  | head -c 10
NEXTCLOUD_GROUP_NAME_PREFIX = "c4d96a06b7_"


class NextcloudHandler(BaseHandler):
    def __init__(self, hs):
        self.store = hs.get_datastore()
        self.event_creation_handler = hs.get_event_creation_handler()
        self.keycloak_client = KeycloakClient(hs)
        self.nextcloud_client = NextcloudClient(hs)

    async def unbind(self, room_id):
        """Unbind a Nextcloud folder from a room.

        Args :
            room_id: the id of the room to bind.
        """

        await self.nextcloud_client.delete_group(NEXTCLOUD_GROUP_NAME_PREFIX + room_id)

        await self.store.unbind(room_id)

    async def bind(self, user_id, room_id, path):
        """Bind a Nextcloud folder with a room.

        Args :
           user_id: the matrix user id of the requester.
           room_id: the id of the room to bind.
           path: the path of the Nextcloud folder to bind.
        """
        group_name = NEXTCLOUD_GROUP_NAME_PREFIX + room_id
        user = await self.keycloak_client.get_user(decode_localpart(user_id))
        nextcloud_username = user["id"]

        await self.nextcloud_client.add_group(group_name)

        await self.add_room_users_to_nextcloud_group(room_id)

        old_share_id = await self.store.get_nextcloud_share_id_from_room_id(room_id)

        if old_share_id:
            await self.nextcloud_client.unshare(nextcloud_username, old_share_id)

        new_share_id = await self.nextcloud_client.share(
            nextcloud_username, path, group_name
        )

        await self.store.bind(room_id, path, new_share_id)

    async def add_room_users_to_nextcloud_group(self, room_id):
        """Add all users of a room to a Nextcloud.

        Args:
            room_id: the id of the room which the Nextcloud group name is infered from.
        """
        group_name = NEXTCLOUD_GROUP_NAME_PREFIX + room_id
        user_ids = await self.store.get_users_in_room(room_id)
        localparts = [get_localpart_from_id(user_id) for user_id in user_ids]
        users = await self.keycloak_client.get_users()

        for user in users:
            localpart = map_username_to_mxid_localpart(user["username"])
            nextcloud_username = user["id"]

            if localpart in localparts:
                try:
                    await self.nextcloud_client.get_user(nextcloud_username)
                except (SynapseError, ValidationError, SchemaError):
                    logger.warn(
                        "The user {} does not have a Nextcloud account.".format(
                            localpart
                        )
                    )
                    continue

                try:
                    await self.nextcloud_client.add_user_to_group(
                        nextcloud_username, group_name
                    )
                except (SynapseError, ValidationError, SchemaError):
                    logger.warn(
                        "Unable to add the user {} to the Nextcloud group {}.".format(
                            localpart, group_name
                        )
                    )

    async def update_share(self, user_id, room_id, membership):

        group_name = NEXTCLOUD_GROUP_NAME_PREFIX + room_id
        user = await self.keycloak_client.get_user(decode_localpart(user_id))
        nextcloud_username = user["id"]

        if membership in ("invite", "join"):
            try:
                await self.nextcloud_client.add_user_to_group(
                    nextcloud_username, group_name
                )
            except (SynapseError, ValidationError, SchemaError):
                logger.warn(
                    "Unable to add the user {} to the Nextcloud group {}.".format(
                        user_id, group_name
                    ),
                )
        else:
            try:
                await self.nextcloud_client.remove_user_from_group(
                    nextcloud_username, group_name
                )
            except (SynapseError, ValidationError, SchemaError):
                logger.warn(
                    "Unable to remove the user {} from the Nextcloud group {}.".format(
                        user_id, group_name
                    ),
                )

    async def get_rooms_to_send_notification(
        self, directory, limit_of_notification_propagation
    ):
        rooms = []

        if not directory:
            raise SynapseError(400, "The directory path is empty")

        directories = [
            str(directory)
            for directory in Path(directory).parents
            if limit_of_notification_propagation in str(directory)
            and str(directory) != limit_of_notification_propagation
        ]
        directories.append(directory)

        for directory in directories:
            room = await self.store.get_room_id_from_path(directory)

            if room:
                rooms.append(room)

        if not rooms:
            raise SynapseError(
                400, "No rooms are linked with this Nextcloud directory."
            )

        return rooms

    async def send_nextcloud_notification_to_rooms(
        self, rooms, file_name, file_url, file_operation
    ):
        notification_sent = {
            "file_name": file_name,
            "file_operation": file_operation,
        }

        content = {
            "body": file_operation,
            "filename": file_name,
            "msgtype": "m.file",
            "url": "",
        }

        if file_operation in ("file_created", "file_restored", "file_moved"):
            content["url"] = file_url

        notified_rooms = []
        for room in rooms:
            users = await self.store.get_users_in_room(room)

            if not users:
                logger.warn(
                    "This room has no users. The Nextcloud notification cannot be posted.",
                )
                continue

            requester = create_requester(users[0])
            sender = requester.user.to_string()

            event_dict = {
                "type": EventTypes.Message,
                "content": content,
                "room_id": room,
                "sender": sender,
            }

            await self.event_creation_handler.create_and_send_nonmember_event(
                requester, event_dict
            )

            notified_rooms.append(
                {
                    "room_id": room,
                    "sender": sender,
                }
            )

        notification_sent["notified_rooms"] = notified_rooms

        return notification_sent
