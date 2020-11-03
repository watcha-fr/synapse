import logging
from base64 import b64encode

from synapse.http.client import SimpleHttpClient
from synapse.api.errors import Codes, SynapseError

logger = logging.getLogger(__name__)


class WatchaNextcloudClient(SimpleHttpClient):
    """ Interface for talking with Nextcloud APIs : https://doc.owncloud.com/server/admin_manual/configuration/user/user_provisioning_api.html
    """

    def __init__(self, hs):
        super(WatchaNextcloudClient, self).__init__(hs)

        self.nextcloud_shared_secret = hs.config.nextcloud_shared_secret
        self.nextcloud_server = hs.config.nextcloud_server
        self.service_account_name = hs.config.service_account_name
        self.service_account_password = hs.config.service_account_password

    @property
    def _headers(self):
        return {
            "OCS-APIRequest": ["true"],
            "Authorization": [
                "Basic "
                + b64encode(
                    bytes(
                        "{}:{}".format(
                            self.service_account_name, self.service_account_password,
                        ),
                        "utf-8",
                    )
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

    async def add_group(self, group_name):
        """ Adds a new Nextcloud group.

        Args:
            group_name: the name of the Nextcloud group

        Status codes:
            100: successful
            101: invalid input data
            102: group already exists
            103: failed to add the group
        """

        response = await self.post_json_get_json(
            uri="{}/ocs/v1.php/cloud/groups".format(self.nextcloud_server),
            post_json={"groupid": group_name},
            headers=self._headers,
        )

        meta = response["ocs"]["meta"]

        if meta["statuscode"] == 102:
            logger.info("Nextcloud group {} already exists.".format(group_name))
        else:
            self._raise_for_status(meta, Codes.NEXTCLOUD_CAN_NOT_CREATE_GROUP)

    async def delete_group(self, group_name):
        """ Removes a existing Nextcloud group.

        Args:
            group_name: the name of the Nextcloud group

        Status codes:
            100: successful
            101: group does not exist
            102: failed to delete group
        """

        response = await self.delete_get_json(
            uri="{nextcloud_server}/ocs/v1.php/cloud/groups/{group_name}".format(
                nextcloud_server=self.nextcloud_server, group_name=group_name
            ),
            headers=self._headers,
        )

        self._raise_for_status(
            response["ocs"]["meta"], Codes.NEXTCLOUD_CAN_NOT_DELETE_GROUP
        )

    async def add_user_to_group(self, username, group_name):
        """ Add user to the Nextcloud group.

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
            uri="{nextcloud_server}/ocs/v1.php/cloud/users/{user_id}/groups".format(
                nextcloud_server=self.nextcloud_server, user_id=username
            ),
            post_json={"groupid": group_name},
            headers=self._headers,
        )

        self._raise_for_status(
            response["ocs"]["meta"], Codes.NEXTCLOUD_CAN_NOT_ADD_USER_TO_GROUP
        )

    async def remove_from_group(self, username, group_name):
        """ Removes the specified user from the specified group.

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
            uri="{nextcloud_server}/ocs/v1.php/cloud/users/{user_id}/groups".format(
                nextcloud_server=self.nextcloud_server, user_id=username
            ),
            headers=self._headers,
            json_body={"groupid": group_name},
        )

        self._raise_for_status(
            response["ocs"]["meta"], Codes.NEXTCLOUD_CAN_NOT_REMOVE_USER_TO_GROUP
        )

    async def get_user(self, username):
        """ Add user to the Nextcloud group.

        Args:
            username: the username of the user to add to the group.
            group_name: the group name.

        Status codes:
            100: successful
            404: user does not exist
        """

        response = await self.get_json(
            uri="{nextcloud_server}/ocs/v1.php/cloud/users/{user_id}".format(
                nextcloud_server=self.nextcloud_server, user_id=username
            ),
            headers=self._headers,
        )

        self._raise_for_status(
            response["ocs"]["meta"], Codes.NEXTCLOUD_CAN_NOT_GET_USER
        )

        return response["ocs"]["data"]

    async def create_all_permission_share_with_group(self, requester, path, group_name):
        """ Share an existing file or folder with all permissions for a group.

        Args:
            requester: the user who want to remove the share
            args: request attributes to filter the search.

        Status codes:
            100: successful
            400: Unknown share type
            403: Public upload was disabled by the admin
            404: File or folder couldn’t be shared
        """

        response = await self.post_json_get_json(
            uri="{}/ocs/v2.php/apps/watcha_integrator/api/v1/shares".format(
                self.nextcloud_server
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

        self._raise_for_status(
            response["ocs"]["meta"], Codes.NEXTCLOUD_CAN_NOT_CREATE_NEW_SHARE
        )

        return response["ocs"]["data"]["id"]

    async def delete_share(self, requester, share_id):
        """ Remove a given Nextcloud share

        Args:
            requester: the user who want to remove the share
            share_id: the share's unique id.

        Status codes:
            100: successful
            404: Share couldn’t be deleted.
        """

        response = await self.delete_get_json(
            uri="{nextcloud_server}/ocs/v2.php/apps/watcha_integrator/api/v1/shares/{share_id}".format(
                nextcloud_server=self.nextcloud_server, share_id=share_id
            ),
            headers=self._headers,
            json_body={"requester": requester},
        )

        self._raise_for_status(
            response["ocs"]["meta"], Codes.NEXTCLOUD_CAN_NOT_DELETE_SHARE
        )
