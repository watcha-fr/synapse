import logging
from pathlib import Path

from ._base import BaseHandler
from synapse.api.constants import EventTypes
from synapse.api.errors import  SynapseError
from synapse.http.watcha_keycloak_api import WatchaKeycloakClient
from synapse.http.watcha_nextcloud_api import WatchaNextcloudClient
from synapse.types import create_requester,
from synapse.types import get_localpart_from_id

logger = logging.getLogger(__name__)

# echo -n watcha | md5sum
NEXTCLOUD_GROUP_NAME_PREFIX = "c4d96a06b758a7ed12f897690828e414_"


class NextcloudHandler(BaseHandler):
    def __init__(self, hs):
        self.store = hs.get_datastore()
        self.event_creation_handler = hs.get_event_creation_handler()
        self.keycloak_client = WatchaKeycloakClient(hs)
        self.nextcloud_client = WatchaNextcloudClient(hs)

    async def unbind(self, room_id):
        """ Delete a mapping between a room and an Nextcloud folder.

        Args :
            room_id: the id of the room.
        """

        await self.nextcloud_client.delete_group(room_id)

        await self.store.deleted_room_mapping_with_nextcloud_directory(room_id)

    async def bind(
        self, room_id, requester_id, nextcloud_directory_path
    ):
        """ Update the mapping between a room and a Nextcloud folder.

        Args :
            room_id: the id of the room which must be linked with the Nextcloud folder.
            requester_id: the user_id of the requester.
            nextcloud_directory_path: the directory path of the Nextcloud folder to link with the room.
        """

        keycloak_user_representation = await self.keycloak_client.get_keycloak_user(
            get_localpart_from_id(requester_id)
        )
        nextcloud_requester = keycloak_user_representation["id"]

        await self.nextcloud_client.add_group(NEXTCLOUD_GROUP_NAME_PREFIX + room_id)

        await self.add_room_users_to_nextcloud_group(room_id)

        old_share_id = await self.store.get_nextcloud_share_id_from_roomID(room_id)

        if old_share_id:
            await self.nextcloud_client.unshare(nextcloud_requester, old_share_id)

        new_share_id = await self.nextcloud_client.share(
            nextcloud_requester, nextcloud_directory_path, room_id
        )

        await self.store.map_room_with_nextcloud_directory(
            room_id, nextcloud_directory_path, new_share_id
        )

    async def add_room_users_to_nextcloud_group(self, room_id):
        """ Add all users of a room to a Nextcloud group which name like the room_id.

        Args:
            room_id: the id of the room which is the name of the Nextcloud group.
        """

        users_id = await self.store.get_users_in_room(room_id)
        localparts = [get_localpart_from_id(user_id) for user_id in users_id]

        for user in await self.keycloak_client.get_all_keycloak_users():
            localpart = user["username"]
            nextcloud_username = user["id"]

            if localpart in localparts:
                try:
                    await self.nextcloud_client.get_user(nextcloud_username)
                except Exception:
                    logger.warn(
                        "The user {} does not have a Nextcloud account.".format(
                            localpart
                        )
                    )
                    continue

                try:
                    await self.nextcloud_client.add_user_to_group(
                        nextcloud_username, room_id
                    )
                except SynapseError:
                    logger.warn(
                        "Unable to add the user {} to the Nextcloud group {}.".format(
                            localpart, room_id
                        )
                    )
                continue

    async def update_share(
        self, user_id, group_name, membership
    ):
        keycloak_user_representation = await self.keycloak_client.get_keycloak_user(
            get_localpart_from_id(user_id)
        )
        nextcloud_username = keycloak_user_representation["id"]

        if membership in ("invite", "join"):
            try:
                await self.nextcloud_client.add_user_to_group(
                    nextcloud_username, group_name
                )
            except SynapseError:
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
            except SynapseError:
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
            room = await self.store.get_roomID_from_nextcloud_directory_path(directory)

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
                {"room_id": room, "sender": sender,}
            )

        notification_sent["notified_rooms"] = notified_rooms
        return notification_sent
