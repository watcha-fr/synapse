import logging
from jsonschema.exceptions import ValidationError, SchemaError
from pathlib import Path

from ._base import BaseHandler
from synapse.api.constants import EventTypes
from synapse.api.errors import Codes, SynapseError

logger = logging.getLogger(__name__)

# echo -n watcha | md5sum  | head -c 10
NEXTCLOUD_GROUP_NAME_PREFIX = "c4d96a06b7_"


class NextcloudHandler(BaseHandler):
    def __init__(self, hs):
        self.store = hs.get_datastore()
        self.event_creation_handler = hs.get_event_creation_handler()
        self.keycloak_client = hs.get_keycloak_client()
        self.nextcloud_client = hs.get_nextcloud_client()

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
        nextcloud_username = await self.store.get_nextcloud_username(user_id)

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

        for user_id in user_ids:
            nextcloud_username = await self.store.get_nextcloud_username(user_id)
            try:
                await self.nextcloud_client.add_user_to_group(
                    nextcloud_username, group_name
                )
            except (SynapseError, ValidationError, SchemaError) as error:
                logger.warn(
                    "Unable to add the user {} to the Nextcloud group {}.".format(
                        user_id, group_name
                    )
                )

    async def update_share(self, user_id, room_id, membership):

        group_name = NEXTCLOUD_GROUP_NAME_PREFIX + room_id
        nextcloud_username = await self.store.get_nextcloud_username(user_id)

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
