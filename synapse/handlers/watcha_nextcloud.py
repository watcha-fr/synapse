import logging
from typing import Iterable, List, Optional, Set
from urllib import parse as urlparse

from jsonschema.exceptions import SchemaError, ValidationError

from synapse.api.constants import EventTypes, Membership
from synapse.api.errors import (
    Codes,
    HttpResponseException,
    NextcloudError,
    SynapseError,
)
from synapse.events import EventBase
from synapse.push.presentable_names import calculate_room_name
from synapse.types import Requester
from synapse.util.watcha import build_log_message

logger = logging.getLogger(__name__)

# echo -n watcha | md5sum | head -c 10
NEXTCLOUD_GROUP_ID_PREFIX = "c4d96a06b7_"
# Nextcloud does not allow group id longer than 64 characters
NEXTCLOUD_GROUP_ID_LENGHT_LIMIT = 64
NEXTCLOUD_CLIENT_ERRORS = (
    NextcloudError,
    SchemaError,
    ValidationError,
    HttpResponseException,
)


class NextcloudHandler:
    def __init__(self, hs: "Homeserver"):
        self.config = hs.config
        self.auth = hs.get_auth()
        self.store = hs.get_datastores().main
        self.administration_handler = hs.get_watcha_administration_handler()
        self.event_creation_handler = hs.get_event_creation_handler()
        self._storage_controllers = hs.get_storage_controllers()
        self.keycloak_client = hs.get_keycloak_client()
        self.nextcloud_client = hs.get_nextcloud_client()

    async def handle_room_member_event(
        self, requester: Requester, room_id: str, user_id: str, membership: str
    ):
        if (
            await self.administration_handler.get_user_role(user_id) == "partner"
            and not self.config.watcha.external_authentication_for_partners
        ):
            return

        if await self.store.get_share_id(room_id):
            await self.update_group(user_id, room_id, membership)

        events = await self._get_calendar_events(room_id)
        if events:
            await self.update_calendar_access(
                requester, room_id, user_id, membership, events
            )

    async def handle_room_name_event(
        self, requester: Requester, event_dict: dict, txn_id: Optional[str] = None
    ):
        event, _ = await self.event_creation_handler.create_and_send_nonmember_event(
            requester, event_dict, txn_id=txn_id
        )

        room_id = event_dict["room_id"]
        displayname = await self.build_group_displayname(room_id)

        if await self.store.get_share_id(room_id):
            group_id = await self.build_group_id(room_id)
            await self.set_group_displayname(group_id, displayname)

        calendar_ids = await self._get_calendar_ids(room_id)
        if calendar_ids:
            await self.nextcloud_client.rename_calendars(
                calendar_ids, room_id, displayname
            )

        return event.event_id

    # file sharing
    # ============

    async def update_share(self, room_id: str, user_id: str, event_content: dict):
        await self.auth.check_user_in_room(room_id, user_id)

        nextcloud_url = event_content["nextcloudShare"]

        if nextcloud_url:
            url_query = urlparse.parse_qs(urlparse.urlparse(nextcloud_url).query)
            if "dir" not in url_query:
                raise SynapseError(
                    400,
                    build_log_message(
                        action="get `nextcloud_folder_path` from `im.vector.web.settings` event",
                        log_vars={"nextcloud_url": nextcloud_url},
                    ),
                )
            nextcloud_folder_path = url_query["dir"][0]
            await self.bind(user_id, room_id, nextcloud_folder_path)

        else:
            await self.unbind(user_id, room_id)

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
            log_message = build_log_message(
                log_vars={"group_id": group_id, "error": error}
            )
            if isinstance(error, NextcloudError) and error.code == 102:
                logger.warn(log_message)
            else:
                raise SynapseError(
                    500,
                    log_message,
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
        room_state_ids = await self._storage_controllers.state.get_current_state_ids(room_id)
        room_name = await calculate_room_name(self.store, room_state_ids, None)
        return f"[Watcha] {room_name}"

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
                build_log_message(
                    log_vars={
                        "group_id": group_id,
                        "group_displayname": group_displayname,
                        "error": error,
                    }
                )
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
                log_message = build_log_message(
                    log_vars={
                        "user_id": user_id,
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
                logger.error(
                    build_log_message(
                        log_vars={
                            "nextcloud_username": nextcloud_username,
                            "old_share_id": old_share_id,
                            "error": error,
                        }
                    )
                )

        try:
            new_share_id = await self.nextcloud_client.share(
                nextcloud_username, path, group_id
            )
        except NEXTCLOUD_CLIENT_ERRORS as error:
            await self.unbind(requester_id, room_id)
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

        await self.store.register_share(room_id, new_share_id)

    async def unbind(self, requester_id: str, room_id: str):
        """Unbind a Nextcloud folder from a room.

        Args :
            requester_id: the mxid of the requester.
            room_id: the id of the room to bind
        """
        nextcloud_username = await self.store.get_username(requester_id)
        share_id = await self.store.get_share_id(room_id)
        if share_id:
            try:
                await self.nextcloud_client.unshare(nextcloud_username, share_id)
            except NEXTCLOUD_CLIENT_ERRORS as error:
                logger.error(
                    build_log_message(
                        log_vars={
                            "nextcloud_username": nextcloud_username,
                            "share_id": share_id,
                            "error": error,
                        }
                    )
                )

        group_id = await self.build_group_id(room_id)
        try:
            await self.nextcloud_client.delete_group(group_id)
        except NEXTCLOUD_CLIENT_ERRORS as error:
            logger.error(
                build_log_message(log_vars={"group_id": group_id, "error": error})
            )

        await self.store.delete_share(room_id)

    async def update_group(self, user_id: str, room_id: str, membership: str):
        """Update a Nextcloud group by adding or removing users.

        Args:
            user_id: The mxid whose membership has been updated
            room_id: The id of the room where the membership event was sent
            membership: The type of membership event
        """
        nextcloud_username = await self.store.get_username(user_id)
        group_id = await self.build_group_id(room_id)

        try:
            if membership == Membership.JOIN:
                await self.nextcloud_client.add_user_to_group(
                    nextcloud_username, group_id
                )
            else:
                await self.nextcloud_client.remove_user_from_group(
                    nextcloud_username, group_id
                )
        except NEXTCLOUD_CLIENT_ERRORS as error:
            log_vars = {
                "user_id": user_id,
                "room_id": room_id,
                "membership": membership,
                "nextcloud_username": nextcloud_username,
                "group_id": group_id,
                "error": error,
            }
            logger.warn(build_log_message(log_vars=log_vars))

    # calendar sharing
    # ================

    async def list_users_own_calendars(self, user_id: str):
        nextcloud_username = await self.store.get_username(user_id)
        calendars = await self.nextcloud_client.get_users_own_calendars(
            nextcloud_username
        )
        aggregated_calendars = {key: list() for key in CalendarComponentTypes.ALL}
        for calendar in calendars:
            components = calendar["components"]
            key = CalendarComponentTypes.serialize(components)
            aggregated_calendars[key].append(
                {
                    "id": calendar["id"],
                    "displayname": calendar["displayname"],
                }
            )
        return aggregated_calendars

    async def get_calendar(self, user_id: str, calendar_id: str):
        nextcloud_username = await self.store.get_username(user_id)
        return await self.nextcloud_client.get_calendar(nextcloud_username, calendar_id)

    async def reorder_calendars(self, user_id: str, calendar_id: str):
        nextcloud_username = await self.store.get_username(user_id)
        return await self.nextcloud_client.reorder_calendars(
            nextcloud_username, calendar_id
        )

    async def update_calendar_share(
        self, requester: Requester, event_dict: dict, txn_id: Optional[str] = None
    ):
        user_id = event_dict["sender"]
        room_id = event_dict["room_id"]
        content = event_dict["content"]

        await self.auth.check_user_in_room(room_id, user_id)

        if not content:
            state_key = event_dict["state_key"]
            calendar_event = await self._storage_controllers.state.get_current_state_event(
                room_id, EventTypes.NextcloudCalendar, state_key
            )
            if calendar_event is None or not calendar_event["content"]:
                raise SynapseError(
                    400,
                    f"[Watcha] No such iCalendar component shared with this room",
                    Codes.BAD_STATE,
                )
            calendar_ids = [calendar_event.content["id"]]
            # FIXME: infer delete_group also from share_state
            delete_group = len(await self._get_calendar_events(room_id)) == 1
            await self.nextcloud_client.unshare_calendar(
                calendar_ids, room_id, delete_group
            )
            event_dict["content"] = {}

        elif content.get("id") is None:
            fake_calendar = {
                "components": [
                    CalendarComponentTypes.VEVENT,
                    CalendarComponentTypes.VTODO,
                ]
            }
            await self._validate_calendar(room_id, fake_calendar)
            displayname = await self.build_group_displayname(room_id)
            user_ids = await self.store.get_users_in_room(room_id)
            nextcloud_usernames = [
                await self.store.get_username(user_id) for user_id in user_ids
            ]
            calendar = await self.nextcloud_client.create_and_share_calendar(
                room_id, displayname, nextcloud_usernames
            )
            event_dict["content"] = self._make_calendar_event_content(calendar)
            event_dict["state_key"] = CalendarComponentTypes.VEVENT_VTODO

        else:
            nextcloud_username = await self.store.get_username(user_id)
            calendar_id = content["id"]
            calendar = await self.nextcloud_client.get_calendar(
                nextcloud_username, calendar_id
            )
            await self._validate_calendar(room_id, calendar)
            components = calendar["components"]
            event_dict["state_key"] = CalendarComponentTypes.serialize(components)
            displayname = await self.build_group_displayname(room_id)
            user_ids = await self.store.get_users_in_room(room_id)
            nextcloud_usernames = [
                await self.store.get_username(user_id) for user_id in user_ids
            ]
            calendar = await self.nextcloud_client.share_calendar(
                nextcloud_username,
                calendar_id,
                room_id,
                displayname,
                nextcloud_usernames,
            )
            event_dict["content"] = self._make_calendar_event_content(calendar)

        event, _ = await self.event_creation_handler.create_and_send_nonmember_event(
            requester, event_dict, txn_id=txn_id
        )
        return event.event_id

    async def update_calendar_access(
        self,
        requester: Requester,
        room_id: str,
        user_id: str,
        membership: str,
        calendar_events: List[EventBase],
    ):
        if membership == Membership.JOIN:
            nextcloud_username = await self.store.get_username(user_id)
            calendar_ids = [event["content"]["id"] for event in calendar_events]
            displayname = await self.build_group_displayname(room_id)
            await self.nextcloud_client.add_user_access_to_calendars(
                nextcloud_username, room_id, calendar_ids, displayname
            )
            return

        own_calendar_ids = []

        for event in calendar_events:
            if self._is_own_calendar(user_id, event):
                own_calendar_ids.append(event["content"]["id"])
                event_dict = {
                    "type": EventTypes.NextcloudCalendar,
                    "content": {},
                    "room_id": room_id,
                    "sender": user_id,
                    "state_key": event["state_key"],
                }
                await self.event_creation_handler.create_and_send_nonmember_event(
                    requester, event_dict
                )

        # FIXME: infer delete_group also from share_state
        delete_group = all(
            self._is_own_calendar(user_id, event) for event in calendar_events
        )

        if own_calendar_ids:
            await self.nextcloud_client.unshare_calendar(
                own_calendar_ids, room_id, delete_group
            )

        if not delete_group:
            nextcloud_username = await self.store.get_username(user_id)
            await self.nextcloud_client.remove_user_access_to_calendars(
                nextcloud_username, room_id
            )

    def _is_own_calendar(self, user_id: str, calendar_event: EventBase):
        return (
            calendar_event["sender"] == user_id
            and calendar_event["content"]["is_personal"] == True
        )

    async def _validate_calendar(self, room_id: str, calendar: dict):
        components = CalendarComponentTypes.from_calendar(calendar)
        state_keys = [
            event["state_key"] for event in await self._get_calendar_events(room_id)
        ]
        current_components = CalendarComponentTypes.deserialize_from_state_keys(
            state_keys
        )
        if not components.isdisjoint(current_components):
            raise SynapseError(
                400,
                f"[Watcha] Some of the iCalendar components are already shared with this room",
                Codes.BAD_STATE,
            )

    async def _get_calendar_events(self, room_id: str) -> List[EventBase]:
        calendar_events = []
        room_state = await self._storage_controllers.state.get_current_state(room_id)
        for state_key in CalendarComponentTypes.ALL:
            event = room_state.get((EventTypes.NextcloudCalendar, state_key))
            if event is not None and event["content"]:
                calendar_events.append(event)
        return calendar_events

    async def _get_calendar_ids(self, room_id: str) -> List[int]:
        calendar_ids = []
        for event in await self._get_calendar_events(room_id):
            calendar_ids.append(event["content"]["id"])
        return calendar_ids

    def _make_calendar_event_content(self, calendar: dict) -> dict:
        return {
            "id": calendar["id"],
            "is_personal": calendar["is_personal"],
        }


class CalendarComponentTypes:
    VEVENT_VTODO = "VEVENT_VTODO"
    VEVENT = "VEVENT"
    VTODO = "VTODO"
    ALL = (VEVENT_VTODO, VEVENT, VTODO)

    @classmethod
    def serialize(cls, components: List[str]) -> str:
        key = set(components)
        if key == {cls.VEVENT, cls.VTODO}:
            return cls.VEVENT_VTODO
        if key == {cls.VEVENT}:
            return cls.VEVENT
        if key == {cls.VTODO}:
            return cls.VTODO

    @classmethod
    def deserialize(cls, components: str) -> Set[str]:
        types = {
            cls.VEVENT_VTODO: {cls.VEVENT, cls.VTODO},
            cls.VEVENT: {cls.VEVENT},
            cls.VTODO: {cls.VTODO},
        }
        return types.get(components)

    @classmethod
    def deserialize_from_state_keys(cls, state_keys: List[str]) -> Set[str]:
        component_set = set()
        for key in state_keys:
            component_set.update(cls.deserialize(key))
        return component_set

    @classmethod
    def from_calendar(cls, calendar: dict) -> Set[str]:
        return set(calendar["components"])
