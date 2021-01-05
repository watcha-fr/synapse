import logging
from base64 import b64encode
from jsonschema import validate

from secrets import token_hex
from synapse.api.errors import Codes, SynapseError
from synapse.http.client import SimpleHttpClient

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
    "definitions": {
        "meta": META_SCHEMA,
    },
    "type": "object",
    "properties": {
        "ocs": {
            "type": "object",
            "properties": {
                "meta": {"$ref": "#/definitions/meta"},
                "data": {
                    "type": "array",
                },
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

    def __init__(self, hs):
        super().__init__(hs)

        self.nextcloud_url = hs.config.nextcloud_url
        self.service_account_name = hs.config.service_account_name
        self.service_account_password = hs.config.nextcloud_service_account_password
        self._headers = self._get_headers()

    def _get_headers(self):
        return {
            "OCS-APIRequest": ["true"],
            "Authorization": [
                "Basic "
                + b64encode(
                    "{}:{}".format(
                        self.service_account_name, self.service_account_password
                    ).encode()
                ).decode()
            ],
        }

    def _raise_for_status(self, meta, errcode):
        if meta["status"] == "failure":
            raise SynapseError(
                400,
                "OCS error : status code {status_code} - message {msg}".format(
                    status_code=meta["statuscode"], msg=meta["message"]
                ),
                errcode,
            )

    async def add_user(self, keycloak_user_id):
        """Create a new user on the Nextcloud server.

        Args:
            user_id: the required username for the new user.

        Status codes:
            100 - successful
            101 - invalid input data
            102 - username already exists
            103 - unknown error occurred whilst adding the user
        """
        # A password is needed to create NC user, but it will not be used by KC login process. 
        password = token_hex()

        response = await self.post_json_get_json(
            uri="{}/ocs/v1.php/cloud/users".format(self.nextcloud_url),
            post_json={"userid": keycloak_user_id, "password": password},
            headers=self._headers,
        )

        meta = response["ocs"]["meta"]

        if meta["statuscode"] == 102:
            logger.info(
                "User {} already exists on Nextcloud server.".format(keycloak_user_id)
            )
        else:
            self._raise_for_status(meta, Codes.NEXTCLOUD_CAN_NOT_CREATE_GROUP)

    async def add_group(self, group_name):
        """Adds a new Nextcloud group.

        Args:
            group_name: the name of the Nextcloud group

        Status codes:
            100: successful
            101: invalid input data
            102: group already exists
            103: failed to add the group
        """

        response = await self.post_json_get_json(
            uri="{}/ocs/v1.php/cloud/groups".format(self.nextcloud_url),
            post_json={"groupid": group_name},
            headers=self._headers,
        )

        validate(response, WITHOUT_DATA_SCHEMA)
        meta = response["ocs"]["meta"]

        if meta["statuscode"] == 102:
            logger.info("Nextcloud group {} already exists.".format(group_name))
        else:
            self._raise_for_status(meta, Codes.NEXTCLOUD_CAN_NOT_CREATE_GROUP)

    async def delete_group(self, group_name):
        """Removes a existing Nextcloud group.

        Args:
            group_name: the name of the Nextcloud group

        Status codes:
            100: successful
            101: group does not exist
            102: failed to delete group
        """

        response = await self.delete_get_json(
            uri="{}/ocs/v1.php/cloud/groups/{}".format(self.nextcloud_url, group_name),
            headers=self._headers,
        )

        validate(response, WITHOUT_DATA_SCHEMA)

        self._raise_for_status(
            response["ocs"]["meta"], Codes.NEXTCLOUD_CAN_NOT_DELETE_GROUP
        )

    async def add_user_to_group(self, username, group_name):
        """Add user to the Nextcloud group.

        Args:
            username: the username of the user to add to the group.
            group_name: the group name.

        Status codes:
            100: successful
            101: no group specified
            102: group does not exist
            103: user does not exist
            104: insufficient privileges
            105: failed to add user to group
        """

        response = await self.post_json_get_json(
            uri="{}/ocs/v1.php/cloud/users/{}/groups".format(
                self.nextcloud_url, username
            ),
            post_json={"groupid": group_name},
            headers=self._headers,
        )

        validate(response, WITHOUT_DATA_SCHEMA)

        self._raise_for_status(
            response["ocs"]["meta"], Codes.NEXTCLOUD_CAN_NOT_ADD_USER_TO_GROUP
        )

    async def remove_user_from_group(self, username, group_name):
        """Removes the specified user from the specified group.

        Args:
            username: the username of the user to remove from the group.
            group_name: the group name.

        Status codes:
            100: successful
            101: no group specified
            102: group does not exist
            103: user does not exist
            104: insufficient privileges
            105: failed to remove user from group
        """

        response = await self.delete_get_json(
            uri="{}/ocs/v1.php/cloud/users/{}/groups".format(
                self.nextcloud_url, username
            ),
            headers=self._headers,
            json_body={"groupid": group_name},
        )

        validate(response, WITHOUT_DATA_SCHEMA)

        self._raise_for_status(
            response["ocs"]["meta"], Codes.NEXTCLOUD_CAN_NOT_REMOVE_USER_FROM_GROUP
        )

    async def get_user(self, username):
        """Get informations of user with username given on parameter

        Args:
            username: the username of the user to add to the group.

        Status codes:
            100: successful
            404: user does not exist

        Returns:
            informations on the user
        """

        response = await self.get_json(
            uri="{}/ocs/v1.php/cloud/users/{}".format(self.nextcloud_url, username),
            headers=self._headers,
        )

        validate(response, WITH_DATA_SCHEMA)

        self._raise_for_status(
            response["ocs"]["meta"], Codes.NEXTCLOUD_CAN_NOT_GET_USER
        )

        return response["ocs"]["data"]

    async def share(self, requester, path, group_name):
        """Share an existing file or folder with all permissions for a group.

        Args:
            requester: the user who want to create the share
            path: the path of folder to share
            group_name: the name of group which will share the folder

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
            uri="{}/ocs/v2.php/apps/watcha_integrator/api/v1/shares".format(
                self.nextcloud_url
            ),
            headers=self._headers,
            post_json={
                "path": path,
                "shareType": 1,
                "shareWith": group_name,
                "permissions": 31,
                "requester": requester,
            },
        )

        validate(response, WITH_DATA_SCHEMA)

        self._raise_for_status(response["ocs"]["meta"], Codes.NEXTCLOUD_CAN_NOT_SHARE)

        return response["ocs"]["data"]["id"]

    async def unshare(self, requester, share_id):
        """Remove a given Nextcloud share

        Args:
            requester: the user who want to remove the share
            share_id: the share's unique id.

        Status codes:
            100: successful
            404: Share couldn’t be deleted.
        """

        response = await self.delete_get_json(
            uri="{}/ocs/v2.php/apps/watcha_integrator/api/v1/shares/{}".format(
                self.nextcloud_url, share_id
            ),
            headers=self._headers,
            json_body={"requester": requester},
        )

        validate(response, WITHOUT_DATA_SCHEMA)

        self._raise_for_status(response["ocs"]["meta"], Codes.NEXTCLOUD_CAN_NOT_UNSHARE)
