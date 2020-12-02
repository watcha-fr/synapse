import logging
from base64 import b64encode

from synapse.api.errors import Codes, SynapseError
from synapse.http.client import SimpleHttpClient
from synapse.util.watcha import generate_password

logger = logging.getLogger(__name__)


class WatchaNextcloudClient(SimpleHttpClient):
    """Interface for talking with Nextcloud APIs
    https://doc.owncloud.com/server/admin_manual/configuration/user/user_provisioning_api.html
    """

    def __init__(self, hs):
        super().__init__(hs)

        self.nextcloud_url = hs.config.nextcloud_url
        self.service_account_name = hs.config.service_account_name
        self.service_account_password = hs.config.nextcloud_service_account_password
        # temporary attribute
        self.nextcloud_shared_secret = self.service_account_password

    def _set_headers(self, username, password):
        return {
            "OCS-APIRequest": ["true"],
            "Authorization": [
                "Basic "
                + b64encode("{}:{}".format(username, password).encode()).decode()
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
        password = generate_password()

        headers = self._set_headers(
            self.service_account_name, self.service_account_password
        )
        response = await self.post_json_get_json(
            uri="{}/ocs/v1.php/cloud/users".format(self.nextcloud_url),
            post_json={"userid": keycloak_user_id, "password": password},
            headers=headers,
        )

        meta = response["ocs"]["meta"]

        if meta["statuscode"] == 102:
            logger.info("User {} already exists on Nextcloud server.".format(keycloak_user_id))
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

        headers = self._set_headers(
            self.service_account_name, self.service_account_password
        )
        response = await self.post_json_get_json(
            uri="{}/ocs/v1.php/cloud/groups".format(self.nextcloud_url),
            post_json={"groupid": group_name},
            headers=headers,
        )

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

        headers = self._set_headers(
            self.service_account_name, self.service_account_password
        )
        response = await self.delete_get_json(
            uri="{nextcloud_url}/ocs/v1.php/cloud/groups/{group_name}".format(
                nextcloud_url=self.nextcloud_url, group_name=group_name
            ),
            headers=headers,
        )

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

        headers = self._set_headers(
            self.service_account_name, self.service_account_password
        )
        response = await self.post_json_get_json(
            uri="{nextcloud_url}/ocs/v1.php/cloud/users/{user_id}/groups".format(
                nextcloud_url=self.nextcloud_url, user_id=username
            ),
            post_json={"groupid": group_name},
            headers=headers,
        )

        self._raise_for_status(
            response["ocs"]["meta"], Codes.NEXTCLOUD_CAN_NOT_ADD_USER_TO_GROUP
        )

    async def remove_from_group(self, username, group_name):
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

        headers = self._set_headers(
            self.service_account_name, self.service_account_password
        )
        response = await self.delete_get_json(
            uri="{nextcloud_url}/ocs/v1.php/cloud/users/{user_id}/groups".format(
                nextcloud_url=self.nextcloud_url, user_id=username
            ),
            headers=headers,
            json_body={"groupid": group_name},
        )

        self._raise_for_status(
            response["ocs"]["meta"], Codes.NEXTCLOUD_CAN_NOT_REMOVE_USER_TO_GROUP
        )

    async def get_user(self, username):
        """Add user to the Nextcloud group.

        Args:
            username: the username of the user to add to the group.
            group_name: the group name.

        Status codes:
            100: successful
            404: user does not exist
        """

        headers = self._set_headers(
            self.service_account_name, self.service_account_password
        )
        response = await self.get_json(
            uri="{nextcloud_url}/ocs/v1.php/cloud/users/{user_id}".format(
                nextcloud_url=self.nextcloud_url, user_id=username
            ),
            headers=headers,
        )

        self._raise_for_status(
            response["ocs"]["meta"], Codes.NEXTCLOUD_CAN_NOT_GET_USER
        )

        return response["ocs"]["data"]

    async def get_all_shares(self, requester, args={}):
        """Get informations about a known share

        Args:
            requester: the user who want to remove the share
            args: request attributes to filter the search.

        Status codes:
            100: successful
            400: Not a directory
            404: Couldn’t fetch shares or file doesn’t exist
            997: Unauthorised
        """

        headers = self._set_headers(requester, self.nextcloud_shared_secret)
        response = await self.get_json(
            uri="{nextcloud_url}/ocs/v2.php/apps/files_sharing/api/v1/shares/".format(
                nextcloud_url=self.nextcloud_url
            ),
            headers=headers,
        )

        self._raise_for_status(
            response["ocs"]["meta"], Codes.NEXTCLOUD_CAN_NOT_GET_SHARES
        )

        return response["ocs"]["data"]

    async def create_all_permission_share_with_group(self, requester, path, group_name):
        """Share an existing file or folder with all permissions for a group.

        Args:
            requester: the user who want to remove the share
            args: request attributes to filter the search.

        Status codes:
            100: successful
            400: Unknown share type
            403: Public upload was disabled by the admin
            404: File or folder couldn’t be shared
        """

        headers = self._set_headers(requester, self.nextcloud_shared_secret)
        response = await self.post_json_get_json(
            uri="{}/ocs/v2.php/apps/files_sharing/api/v1/shares".format(
                self.nextcloud_url
            ),
            headers=headers,
            post_json={
                "path": path,
                "shareType": 1,
                "shareWith": group_name,
                "permissions": 31,
            },
        )

        self._raise_for_status(
            response["ocs"]["meta"], Codes.NEXTCLOUD_CAN_NOT_CREATE_NEW_SHARE
        )

    async def delete_share(self, requester, share_id):
        """Remove a given Nextcloud share

        Args:
            requester: the user who want to remove the share
            share_id: the share's unique id.

        Status codes:
            100: successful
            404: Share couldn’t be deleted.
        """

        headers = self._set_headers(requester, self.nextcloud_shared_secret)
        response = await self.delete_get_json(
            uri="{nextcloud_url}/ocs/v2.php/apps/files_sharing/api/v1/shares/{share_id}".format(
                nextcloud_url=self.nextcloud_url, share_id=share_id
            ),
            headers=headers,
        )

        self._raise_for_status(
            response["ocs"]["meta"], Codes.NEXTCLOUD_CAN_NOT_DELETE_SHARE
        )
