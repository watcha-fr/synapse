import logging
import secrets
from base64 import b64encode
from typing import List, Optional, TYPE_CHECKING

from jsonschema import validate

from synapse.api.errors import NextcloudError
from synapse.http.client import SimpleHttpClient
from synapse.util.watcha import ActionStatus, build_log_message

if TYPE_CHECKING:
    from synapse.server import HomeServer

logger = logging.getLogger(__name__)

META_SCHEMA = {
    "type": "object",
    "properties": {
        "statuscode": {"type": "number"},
        "status": {"type": "string"},
    },
    "required": ["statuscode", "status"],
}

WITHOUT_DATA_SCHEMA = {
    "$schema": "http://json-schema.org/draft-04/schema#",
    "description": "Nextcloud API schema which data is not expected",
    "definitions": {"meta": META_SCHEMA},
    "type": "object",
    "properties": {
        "ocs": {
            "type": "object",
            "properties": {
                "meta": {"$ref": "#/definitions/meta"},
            },
            "required": ["meta"],
        },
    },
    "required": ["ocs"],
}

WITH_DATA_SCHEMA = {
    "$schema": "http://json-schema.org/draft-04/schema#",
    "description": "Nextcloud API schema which data is expected",
    "definitions": {"meta": META_SCHEMA},
    "type": "object",
    "properties": {
        "ocs": {
            "type": "object",
            "properties": {
                "meta": {"$ref": "#/definitions/meta"},
                "data": {
                    "type": "object",
                    "properties": {"id": {"type": "string"}},
                    "required": ["id"],
                },
            },
            "required": ["meta", "data"],
        },
    },
    "required": ["ocs"],
}


class NextcloudClient(SimpleHttpClient):
    """Interface for talking with Nextcloud APIs
    https://docs.nextcloud.com/server/latest/developer_manual/client_apis/index.html
    """

    NEXTCLOUD_APP_NAME = "watcha"

    def __init__(self, hs: "HomeServer"):
        super().__init__(hs)

        self.nextcloud_url = hs.config.watcha.nextcloud_url
        self.service_account_name = hs.config.watcha.nextcloud_service_account_name
        self.service_account_password = (
            hs.config.watcha.nextcloud_service_account_password
        )
        self._headers = self._get_headers()
        self._headers_for_ocs_api = self._get_headers_for_ocs_api()

    @property
    def base_url(self):
        return f"{self.nextcloud_url}/apps/{self.NEXTCLOUD_APP_NAME}"

    def _get_headers(self):
        return {
            "Authorization": [
                "Basic "
                + b64encode(
                    f"{self.service_account_name}:{self.service_account_password}".encode()
                ).decode()
            ],
        }

    def _get_headers_for_ocs_api(self):
        return {"OCS-APIRequest": ["true"], **self._get_headers()}

    def _raise_for_status(self, meta):
        if meta["status"] == "failure":
            raise NextcloudError(
                meta["statuscode"],
                meta["message"],
            )

    async def add_user(
        self,
        username: str,
        displayname: Optional[str] = None,
        email: Optional[str] = None,
        is_admin: Optional[bool] = False,
        groups: Optional[List] = None
    ):
        """Create a new user.

        Args:
            username: the username of the user to create.
            displayname: displayname of the user. Defaults to user keycloak id.

        Status codes:
            100 - successful
            101 - invalid input data
            102 - username already exists
            103 - unknown error occurred whilst adding the user
        """
        # A password is needed to create NC user, but it will not be used by KC login process.
        password = secrets.token_hex()
        payload = {
            "userid": username,
            "password": password,
            "groups": groups or []
        }

        if displayname:
            payload["displayName"] = displayname

        if email:
            payload["email"] = email

        if is_admin:
            payload["groups"].append("admin")

        response = await self.post_json_get_json(
            uri=f"{self.nextcloud_url}/ocs/v1.php/cloud/users",
            post_json=payload,
            headers=self._headers_for_ocs_api,
        )

        meta = response["ocs"]["meta"]
        if meta["statuscode"] == 102:
            logger.warn(build_log_message(log_vars={"meta": meta, "payload": payload}))
        else:
            self._raise_for_status(meta)
            logger.info(build_log_message(status=ActionStatus.SUCCESS))

    async def delete_user(self, username: str):
        """Delete an existing user.

        Args:
            username: The username of the user to delete.

        Status codes:
            100 - successful
            101 - failure
        """
        response = await self.delete_get_json(
            uri=f"{self.nextcloud_url}/ocs/v1.php/cloud/users/{username}",
            headers=self._headers_for_ocs_api,
        )

        validate(response, WITHOUT_DATA_SCHEMA)
        self._raise_for_status(response["ocs"]["meta"])

    async def add_group(self, group_id: str):
        """Adds a new Nextcloud group.

        Args:
            group_id: id of the Nextcloud group

        Status codes:
            100: successful
            101: invalid input data
            102: group already exists
            103: failed to add the group
        """
        response = await self.post_json_get_json(
            uri=f"{self.nextcloud_url}/ocs/v1.php/cloud/groups",
            post_json={"groupid": group_id},
            headers=self._headers_for_ocs_api,
        )

        validate(response, WITHOUT_DATA_SCHEMA)
        self._raise_for_status(response["ocs"]["meta"])

    async def set_group_displayname(self, group_id: str, displayname: str):
        """Set the displayname of a Nextcloud group

        Args:
            group_id: id of the Nextcloud group
            displayname: value of the displayname to set

        Status codes:
            100: successful
            101: not supported by backend
            997: unauthorised
        """
        response = await self.put_json(
            uri=f"{self.nextcloud_url}/ocs/v1.php/cloud/groups/{group_id}",
            json_body={"key": "displayname", "value": displayname},
            headers=self._headers_for_ocs_api,
        )

        validate(response, WITHOUT_DATA_SCHEMA)
        self._raise_for_status(response["ocs"]["meta"])

    async def delete_group(self, group_id: str):
        """Removes a existing Nextcloud group.

        Args:
            group_id: id of the Nextcloud group

        Status codes:
            100: successful
            101: group does not exist
            102: failed to delete group
        """
        response = await self.delete_get_json(
            uri=f"{self.nextcloud_url}/ocs/v1.php/cloud/groups/{group_id}",
            headers=self._headers_for_ocs_api,
        )

        validate(response, WITHOUT_DATA_SCHEMA)
        self._raise_for_status(response["ocs"]["meta"])

    async def add_user_to_group(self, username: str, group_id: str):
        """Add user to the Nextcloud group.

        Args:
            username: the username of the user to add to the group
            group_id: id of the Nextcloud group

        Status codes:
            100: successful
            101: no group specified
            102: group does not exist
            103: user does not exist
            104: insufficient privileges
            105: failed to add user to group
        """
        response = await self.post_json_get_json(
            uri=f"{self.nextcloud_url}/ocs/v1.php/cloud/users/{username}/groups",
            post_json={"groupid": group_id},
            headers=self._headers_for_ocs_api,
        )

        validate(response, WITHOUT_DATA_SCHEMA)
        self._raise_for_status(response["ocs"]["meta"])

    async def remove_user_from_group(self, username: str, group_id: str) -> None:
        """Removes the specified user from the specified group.

        Args:
            username: the username of the user to remove from the group
            group_id: id of the Nextcloud group

        Status codes:
            100: successful
            101: no group specified
            102: group does not exist
            103: user does not exist
            104: insufficient privileges
            105: failed to remove user from group
        """
        response = await self.delete_get_json(
            uri=f"{self.nextcloud_url}/ocs/v1.php/cloud/users/{username}/groups",
            headers=self._headers_for_ocs_api,
            json_body={"groupid": group_id},
        )

        validate(response, WITHOUT_DATA_SCHEMA)
        self._raise_for_status(response["ocs"]["meta"])

    async def share(self, requester: str, path: str, group_id: str):
        """Share an existing file or folder with all permissions for a group.

        Args:
            requester: the user who want to create the share
            path: the path of the folder to share
            group_id: id of the Nextcloud group which will share the folder

        Payload:
            shareType: the type of the share. This can be one of:
                0 = user
                1 = group
                3 = public link
                6 = federated cloud share

            permissions: the permissions to set on the share.
                1 = read (default for public link shares);
                2 = update;
                4 = create;
                8 = delete;
                15 = read/write;
                16 = share;
                31 = All permissions.

        Status codes:
            100: successful
            400: Unknown share type
            403: Public upload was disabled by the admin
            404: File or folder couldn’t be shared

        Returns:
            the id of Nextcloud share
        """
        response = await self.post_json_get_json(
            uri=f"{self.base_url}/documents",
            headers=self._headers_for_ocs_api,
            post_json={
                "path": path,
                "shareType": 1,
                "shareWith": group_id,
                "permissions": 31,
                "requester": requester,
            },
        )

        validate(response, WITH_DATA_SCHEMA)
        self._raise_for_status(response["ocs"]["meta"])

        return response["ocs"]["data"]["id"]

    async def unshare(self, requester: str, share_id: str):
        """Remove a given Nextcloud share

        Args:
            requester: the user who want to remove the share
            share_id: the share's unique id.

        Status codes:
            100: successful
            404: Share couldn’t be deleted.
        """
        response = await self.delete_get_json(
            uri=f"{self.base_url}/documents/{share_id}",
            headers=self._headers_for_ocs_api,
            json_body={"requester": requester},
        )

        validate(response, WITHOUT_DATA_SCHEMA)
        self._raise_for_status(response["ocs"]["meta"])

    # calendar operations
    # ===================

    async def get_users_own_calendars(self, user_id: str):
        """List all calendars owned by a specific user.

        Args:
            user_id: the ID of the concerned Nextcloud user
        """

        return await self.get_json(
            uri=f"{self.base_url}/users/{user_id}/calendars",
            headers=self._headers,
        )

    async def get_calendar(self, user_id: str, calendar_id: int):
        """Get properties for a specific calendar from the perspective of a specific user.

        Args:
            user_id: the ID of the concerned Nextcloud user
            calendar_id: the ID of the concerned calendar
        """

        return await self.get_json(
            uri=f"{self.base_url}/users/{user_id}/calendars/{calendar_id}",
            headers=self._headers,
        )

    async def reorder_calendars(self, user_id: str, calendar_id: int):
        """Move up a calendar at the top of the list for a specific user.

        Args:
            user_id: the ID of the Nextcloud user for whom to reorder calendars
            calendar_id: the ID of the calendar to put at the top of the list
        """

        return await self.put_json(
            uri=f"{self.base_url}/users/{user_id}/calendars/{calendar_id}/top",
            headers=self._headers,
            json_body={},
        )

    async def create_and_share_calendar(
        self, room_id: str, displayname: str, user_ids: List[str]
    ):
        """Create and share a calendar with members of a specific room.

        Args:
            room_id: the ID of the concerned room
            displayname: the displayname to use for the group and the calendar
            user_ids: the IDs of Nextcloud users to share with
        """

        return await self.post_json_get_json(
            uri=f"{self.base_url}/calendars",
            headers=self._headers,
            post_json={
                "mxRoomId": room_id,
                "displayName": displayname,
                "userIds": user_ids,
            },
        )

    async def share_calendar(
        self,
        user_id: str,
        calendar_id: int,
        room_id: str,
        displayname: str,
        user_ids: List[str],
    ):
        """Share a personal user calendar with members of a specific room.

        Args:
            user_id: the ID of the Nextcloud calendar owner
            calendar_id: the ID of the calendar to share
            room_id: the ID of the concerned room
            displayname: the displayname to use for the group and the calendar
            user_ids: the IDs of Nextcloud users to share with
        """

        return await self.put_json(
            uri=f"{self.base_url}/users/{user_id}/calendars/{calendar_id}",
            headers=self._headers,
            json_body={
                "mxRoomId": room_id,
                "displayName": displayname,
                "userIds": user_ids,
            },
        )

    async def unshare_calendar(
        self, calendar_ids: List[int], room_id: str, delete_group: bool
    ):
        """Cancel sharing a calendar with a specific room.

        Args:
            calendar_id: the ID of the calendar not to be shared anymore
            room_id: the ID of the concerned room
        """

        return await self.delete_get_json(
            uri=f"{self.base_url}/calendars",
            headers=self._headers,
            json_body={
                "calendarIds": calendar_ids,
                "mxRoomId": room_id,
                "deleteGroup": delete_group,
            },
        )

    async def add_user_access_to_calendars(
        self, user_id: str, room_id: str, calendar_ids: List[int], displayname: str
    ):
        """Allow one user to access specific calendars in the context of a room.

        Args:
            user_id: the ID of the concerned Nextcloud user
            room_id: the ID of the concerned room
            calendar_ids: the calendar IDs to be accessible to
            displayname: the displayname to use for the calendar
        """

        return await self.post_json_get_json(
            uri=f"{self.base_url}/users",
            headers=self._headers,
            post_json={
                "userId": user_id,
                "mxRoomId": room_id,
                "calendarIds": calendar_ids,
                "displayName": displayname,
            },
        )

    async def remove_user_access_to_calendars(self, user_id: str, room_id: str):
        """Revoke a user's access to a calendar in the context of a room.

        Args:
            user_id: the ID of the concerned Nextcloud user
            room_id: the ID of the concerned room
        """

        return await self.delete_get_json(
            uri=f"{self.base_url}/users/{user_id}",
            headers=self._headers,
            json_body={
                "mxRoomId": room_id,
            },
        )

    async def rename_calendars(
        self, calendar_ids: List[int], room_id: str, displayname: str
    ):
        """Rename calendars for each members of a specific room.

        Args:
            calendar_ids: the calendar IDs to rename
            room_id: the ID of the concerned room
            displayname: the displayname to use for the group and the calendar
        """

        return await self.put_json(
            uri=f"{self.base_url}/calendars/displayname",
            headers=self._headers,
            json_body={
                "calendarIds": calendar_ids,
                "mxRoomId": room_id,
                "displayName": displayname,
            },
        )
