import logging

from jsonschema.exceptions import SchemaError, ValidationError
from typing import List, TYPE_CHECKING

from synapse.api.constants import Membership
from synapse.api.errors import (
    Codes,
    HttpResponseException,
    NextcloudError,
    SynapseError,
)
from synapse.logging.utils import build_log_message
from synapse.types import Requester
from synapse.util.watcha import calculate_room_name

if TYPE_CHECKING:
    from synapse.server import HomeServer

logger = logging.getLogger(__name__)

# echo -n watcha | md5sum  | head -c 10
NEXTCLOUD_GROUP_ID_PREFIX = "c4d96a06b7_"
# Nextcloud does not allow group id longer than 64 characters
NEXTCLOUD_GROUP_ID_LENGHT_LIMIT: int = 64
NEXTCLOUD_CLIENT_ERRORS = (
    NextcloudError,
    SchemaError,
    ValidationError,
    HttpResponseException,
)


class NextcloudBindHandler:
    def __init__(self, hs: "HomeServer"):
        self.auth_handler = hs.get_auth_handler()
        self.event_creation_handler = hs.get_event_creation_handler()
        self.nextcloud_client = hs.get_nextcloud_client()
        self.nextcloud_group_handler = hs.get_nextcloud_group_handler()
        self.nextcloud_share_handler = hs.get_nextcloud_share_handler()
        self.store = hs.get_datastore()

    async def bind(self, requester: Requester, room_id: str, path: str):
        """Bind a Nextcloud folder with a room in four steps :
            1 - create a new Nextcloud group
            2 - add internal room members in the new group
            3 - create a internal share on folder for the new group
            4 - create a public link share for partners in the room

        Args :
           requester: user requesting the bind.
           room_id: the id of the room to bind.
           path: the path of the Nextcloud folder to bind.

        Returns:
            url of the public link share
        """
        requester_id = requester.user.to_string()
        members = await self.store.get_users_in_room(room_id)
        partner_members = await self.store.get_partners_in_room(room_id)
        internal_members = [
            member for member in members if member not in partner_members
        ]

        await self.nextcloud_group_handler.create_group(room_id)
        await self.nextcloud_group_handler.add_internal_members_to_group(
            room_id, internal_members
        )

        await self.nextcloud_share_handler.delete_internal_share(requester_id, room_id)
        await self.nextcloud_share_handler.create_internal_share(
            requester_id, room_id, path
        )

        public_link_url = ""
        if partner_members:
            await self.nextcloud_share_handler.delete_public_link_share(
                requester_id, room_id
            )
            public_link_url = (
                await self.nextcloud_share_handler.create_public_link_share(
                    requester_id, room_id, path
                )
            )

        return public_link_url

    async def unbind(self, requester_id: str, room_id: str):
        """Unbind a Nextcloud folder from a room.

        Args :
            requester_id: the mxid of the requester.
            room_id: the id of the room to bind
        """
        group_id = await self.nextcloud_group_handler.build_group_id(room_id)
        try:
            await self.nextcloud_client.delete_group(group_id)
        except NEXTCLOUD_CLIENT_ERRORS as error:
            logger.error(
                build_log_message(log_vars={"group_id": group_id, "error": error})
            )

        await self.nextcloud_share_handler.delete_internal_share(requester_id, room_id)
        await self.nextcloud_share_handler.delete_public_link_share(
            requester_id, room_id
        )

    async def update_bind(self, user_id: str, room_id: str, membership: str):
        """Update a Nextcloud bind.
        Create or delete public share link in case of the user is a partner, else update the Nextcloud group associated to the room.

        Args:
            user_id: mxid of the user concerned by the membership event
            room_id: the id of the room where the membership event was sent
            membership: membership event. Can be 'invite', 'join', 'kick' or 'leave'
        """
        if await self.auth_handler.is_partner(user_id):
            await self.nextcloud_share_handler.handle_public_link_share_on_membership(
                room_id, membership
            )
        else:
            await self.nextcloud_group_handler.update_group(
                user_id, room_id, membership
            )


class NextcloudGroupHandler:
    def __init__(self, hs: "HomeServer"):
        self.hs = hs
        self.administration_handler = hs.get_administration_handler()
        self.group_display_name_prefix = hs.config.nextcloud_group_display_name_prefix
        self.nextcloud_client = hs.get_nextcloud_client()
        self.store = hs.get_datastore()

    async def create_group(self, room_id: str):
        """Create a Nextcloud group with specific id and display name.

        Args:
            room_id: the id of the room
        """
        group_id = await self.build_group_id(room_id)
        group_display_name = await self.build_group_display_name(room_id)

        try:
            await self.nextcloud_client.add_group(group_id)
        except NEXTCLOUD_CLIENT_ERRORS as error:
            # Do not raise error if Nextcloud group already exist
            log_message = build_log_message(
                log_vars={"group_id": group_id, "error": error}
            )
            if isinstance(error, NextcloudError) and error.code == 102:
                logger.warning(log_message)
            else:
                raise SynapseError(
                    500,
                    log_message,
                    Codes.NEXTCLOUD_CAN_NOT_CREATE_GROUP,
                )

        await self.set_group_display_name(group_id, group_display_name)

    @staticmethod
    async def build_group_id(room_id: str):
        """Build the Nextcloud group id corresponding to an association of a pattern and room id

        Args:
            room_id: the id of the room
        """
        group_id = NEXTCLOUD_GROUP_ID_PREFIX + room_id
        return group_id[:NEXTCLOUD_GROUP_ID_LENGHT_LIMIT]

    async def build_group_display_name(self, room_id):
        """Build the Nextcloud group name corresponding to an association of a pattern and room name

        Args:
            room_id: the id of the room
        """
        room_name = await calculate_room_name(self.hs, room_id)
        return f"{self.group_display_name_prefix} {room_name}"

    async def set_group_display_name(self, group_id: str, group_display_name: str):
        """Set the display name of a Nextcloud group

        Args:
            group_id: the id of group
            group_display_name: the display name of the group
        """
        try:
            await self.nextcloud_client.set_group_display_name(
                group_id, group_display_name
            )
        except NEXTCLOUD_CLIENT_ERRORS as error:
            logger.warning(
                build_log_message(
                    log_vars={
                        "group_id": group_id,
                        "group_display_name": group_display_name,
                        "error": error,
                    }
                )
            )

    async def add_internal_members_to_group(
        self, room_id: str, internal_members: List[str]
    ):
        """Add internal room members to a Nextcloud group.

        Args:
            room_id: the id of the room which the Nextcloud group name is infered from
            internal_members: a list of all non partner members in the room
        """
        group_id = await self.build_group_id(room_id)

        for member in internal_members:
            nextcloud_username = await self.store.get_username(member)
            try:
                await self.nextcloud_client.add_user_to_group(
                    nextcloud_username, group_id
                )
            except NEXTCLOUD_CLIENT_ERRORS as error:
                log_message = build_log_message(
                    log_vars={
                        "user_id": member,
                        "nextcloud_username": nextcloud_username,
                        "group_id": group_id,
                        "room_id": room_id,
                        "error": error,
                    }
                )
                # Do not raise error if some users can not be added to group
                if isinstance(error, NextcloudError) and (error.code in (103, 105)):
                    logger.error(log_message)
                else:
                    raise SynapseError(
                        500,
                        log_message,
                        Codes.NEXTCLOUD_CAN_NOT_ADD_MEMBERS_TO_GROUP,
                    )

    async def update_group(self, user_id: str, room_id: str, membership: str):
        """Update a Nextcloud group by adding or removing users.
        If membership is 'join' or 'invite', the user is add to the Nextcloud group inferred from the room.
        Else, the users is removed from the group.

        Args:
            user_id: mxid of the user concerned by the membership event
            room_id: the id of the room where the membership event was sent
            membership: membership event. Can be 'invite', 'join', 'ban' or 'leave'
        """
        group_id = await self.build_group_id(room_id)
        nextcloud_username = await self.store.get_username(user_id)

        log_vars = {
            "user_id": user_id,
            "room_id": room_id,
            "membership": membership,
            "nextcloud_username": nextcloud_username,
            "group_id": group_id,
        }
        if membership in (Membership.INVITE, Membership.JOIN):
            try:
                await self.nextcloud_client.add_user_to_group(
                    nextcloud_username, group_id
                )
            except NEXTCLOUD_CLIENT_ERRORS as error:
                log_vars["error"] = error
                logger.warning(build_log_message(log_vars=log_vars))
        else:
            try:
                await self.nextcloud_client.remove_user_from_group(
                    nextcloud_username, group_id
                )
            except NEXTCLOUD_CLIENT_ERRORS as error:
                log_vars["error"] = error
                logger.warning(build_log_message(log_vars=log_vars))


class NextcloudShareHandler:
    def __init__(self, hs: "HomeServer"):
        self.hs = hs
        self.nextcloud_client = hs.get_nextcloud_client()
        self.nextcloud_group_handler = hs.get_nextcloud_group_handler()
        self.store = hs.get_datastore()

    async def create_internal_share(self, requester_id: str, room_id: str, path: str):
        """Create a internal share on folder for a specific Nextcloud group.
        Before that, delete old existing internal share for this group if it exist.

        Args:
            requester_id: the mxid of the requester.
            room_id: the id of the room to bind.
            path: the path of the Nextcloud folder to bind.
        """
        group_id = await self.nextcloud_group_handler.build_group_id(room_id)
        nextcloud_username = await self.store.get_username(requester_id)

        try:
            new_share_id = await self.nextcloud_client.create_internal_share(
                nextcloud_username, path, group_id
            )
        except NEXTCLOUD_CLIENT_ERRORS as error:
            await self.hs.get_nextcloud_bind_handler().unbind(requester_id, room_id)
            # raise 404 error if folder to share do not exist
            http_code = (
                error.code
                if isinstance(error, NextcloudError) and error.code == 404
                else 500
            )
            raise SynapseError(
                http_code,
                build_log_message(
                    log_vars={
                        "nextcloud_username": nextcloud_username,
                        "path": path,
                        "group_id": group_id,
                        "error": error,
                    }
                ),
                Codes.NEXTCLOUD_CAN_NOT_SHARE,
            )

        await self.store.register_internal_share(
            room_id, new_share_id, requester_id, path
        )

    async def delete_internal_share(self, requester_id: str, room_id: str):
        """Delete, if it exist, internal share of a room

        Args:
            requester_id: the mxid of the requester.
            room_id: the id of the room.
        """
        old_share_id = await self.store.get_internal_share_id(room_id)

        if old_share_id:
            nextcloud_username = await self.store.get_username(requester_id)
            try:
                await self.nextcloud_client.unshare(nextcloud_username, old_share_id)
            except NEXTCLOUD_CLIENT_ERRORS as error:
                logger.error(
                    build_log_message(
                        log_vars={
                            "nextcloud_username": nextcloud_username,
                            "old_share_id": old_share_id,
                            "error": error,
                        }
                    )
                )

            await self.store.delete_internal_share(room_id)

    async def create_public_link_share(
        self, requester_id: str, room_id: str, path: str
    ):
        """Create a public link share on folder for partners in room.
        Before that, delete old existing public link share if it exist.

        Args:
            requester_id: the mxid of the requester.
            room_id: the id of the room to bind.
            path: the path of the Nextcloud folder to bind.

        Returns:
            url of the public link share
        """
        nextcloud_username = await self.store.get_username(requester_id)

        try:
            (
                new_share_id,
                public_link_url,
            ) = await self.nextcloud_client.create_public_link_share(
                nextcloud_username,
                path,
            )
        except NEXTCLOUD_CLIENT_ERRORS as error:
            # raise 404 error if folder to share do not exist
            http_code = (
                error.code
                if isinstance(error, NextcloudError) and error.code == 404
                else 500
            )
            raise SynapseError(
                http_code,
                build_log_message(
                    log_vars={
                        "nextcloud_username": nextcloud_username,
                        "path": path,
                        "error": error,
                    }
                ),
                Codes.NEXTCLOUD_CAN_NOT_SHARE,
            )

        await self.store.register_public_link_share(room_id, new_share_id)

        return public_link_url

    async def delete_public_link_share(self, requester_id: str, room_id: str):
        """Delete, if it exist, public link share of a room

        Args:
            requester_id: the mxid of the requester.
            room_id: the id of the room.
        """
        old_share_id = await self.store.get_public_link_share_id(room_id)

        if old_share_id:
            nextcloud_username = await self.store.get_username(requester_id)
            try:
                await self.nextcloud_client.unshare(nextcloud_username, old_share_id)
            except NEXTCLOUD_CLIENT_ERRORS as error:
                logger.error(
                    build_log_message(
                        log_vars={
                            "nextcloud_username": nextcloud_username,
                            "old_share_id": old_share_id,
                            "error": error,
                        }
                    )
                )

            await self.store.delete_public_link_share(room_id)

    async def handle_public_link_share_on_membership(
        self, room_id: str, membership: str
    ):
        """Handle public link share on partner membership according to three use cases :
            if it's the first partner to join room : create a new public link share
            if it's the last partner to leave room : delete the public link share
            if it's not the last partner to leave room : delete the public link share and create a new one

        Args :
            room_id: the id of the room where the membership event was sent
            membership: membership event. Can be 'invite', 'join', 'ban' or 'leave'
        """
        partner_members = await self.store.get_partners_in_room(room_id)
        sharing_requester_id = await self.store.get_sharing_requester_id(room_id)
        path = await self.store.get_folder_path(room_id)

        if membership == Membership.JOIN and len(partner_members) == 1:
            await self.create_public_link_share(sharing_requester_id, room_id, path)

        elif membership in (Membership.LEAVE, Membership.BAN):
            await self.delete_public_link_share(sharing_requester_id, room_id)

            if len(partner_members) > 0:
                await self.create_public_link_share(sharing_requester_id, room_id, path)
