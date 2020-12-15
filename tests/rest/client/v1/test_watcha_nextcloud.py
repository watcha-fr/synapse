import json
from mock import Mock

from synapse.api.errors import SynapseError
from synapse.rest import admin
from synapse.rest.client.v1 import login, room, watcha
from synapse.types import UserID, create_requester

from tests import unittest


def simple_async_mock(return_value=None, raises=None):
    # AsyncMock is not available in python3.5, this mimics part of its behaviour
    async def cb(*args, **kwargs):
        if raises:
            raise raises
        return return_value

    return Mock(side_effect=cb)


class NextcloudShareTestCase(unittest.HomeserverTestCase):
    """Tests that Nextcloud sharing is updated with membership event when the room is mapped with a Nextcloud directory"""

    servlets = [
        admin.register_servlets_for_client_rest_resource,
        room.register_servlets,
        login.register_servlets,
    ]

    def prepare(self, reactor, clock, hs):
        self.store = hs.get_datastore()
        self.creator = self.register_user("creator", "pass")
        self.creator_tok = self.login("creator", "pass")

        self.inviter = self.register_user("inviter", "pass")
        self.inviter_tok = self.login("inviter", "pass")

        self.room_id = self.helper.create_room_as(self.creator, tok=self.creator_tok)

        # map a room with a Nextcloud directory :
        self.get_success(self.store.bind(self.room_id, "/directory", 1))

        # mock some functions of WatchaRoomNextcloudMappingHandler
        self.nextcloud_handler = hs.get_nextcloud_handler()

        self.keycloak_client = self.nextcloud_handler.keycloak_client
        self.nextcloud_client = self.nextcloud_handler.nextcloud_client
        self.nextcloud_handler.bind = simple_async_mock()
        self.nextcloud_handler.unbind = simple_async_mock()
        self.nextcloud_directory_url = (
            "https://test/nextcloud/apps/files/?dir=/directory"
        )

        self.keycloak_client.get_user = simple_async_mock(
            return_value={"id": "1234", "username": "creator"},
        )
        self.nextcloud_client.add_user_to_group = simple_async_mock()
        self.nextcloud_client.remove_user_from_group = simple_async_mock()

    def send_room_nextcloud_mapping_event(self, request_content):
        request, channel = self.make_request(
            "PUT",
            "/rooms/{}/state/im.vector.web.settings".format(self.room_id),
            content=json.dumps(request_content),
            access_token=self.creator_tok,
        )
        self.render(request)

        return channel

    def test_create_new_room_nextcloud_mapping(self):
        channel = self.send_room_nextcloud_mapping_event(
            {"nextcloudShare": self.nextcloud_directory_url}
        )

        self.assertTrue(self.nextcloud_handler.bind.called)
        self.assertEquals(200, channel.code)

    def test_delete_existing_room_nextcloud_mapping(self):
        self.send_room_nextcloud_mapping_event(
            {"nextcloudShare": self.nextcloud_directory_url}
        )
        self.assertTrue(self.nextcloud_handler.bind.called)

        channel = self.send_room_nextcloud_mapping_event({"nextcloudShare": ""})
        self.assertTrue(self.nextcloud_handler.unbind.called)

        self.assertEquals(200, channel.code)

    def test_update_existing_room_nextcloud_mapping(self):
        self.send_room_nextcloud_mapping_event(
            {"nextcloudShare": self.nextcloud_directory_url}
        )
        channel = self.send_room_nextcloud_mapping_event(
            {"nextcloudShare": "https://test/nextcloud/apps/files/?dir=/directory2"}
        )

        self.assertTrue(self.nextcloud_handler.bind.called)
        self.assertEquals(200, channel.code)

    def test_create_new_room_nextcloud_mapping_without_nextcloudShare_attribute(self):
        channel = self.send_room_nextcloud_mapping_event(
            {"nextcloud": self.nextcloud_directory_url}
        )

        self.assertFalse(self.nextcloud_handler.bind.called)
        self.assertRaises(SynapseError)
        self.assertEquals(400, channel.code)
        self.assertEquals(
            "VectorSetting is only used for Nextcloud integration.",
            json.loads(channel.result["body"])["error"],
        )

    def test_create_new_room_nextcloud_mapping_with_wrong_url(self):
        channel = self.send_room_nextcloud_mapping_event(
            {"nextcloudShare": "https://test/nextcloud/apps/files/?file=brandbook.pdf"}
        )

        self.assertFalse(self.nextcloud_handler.bind.called)
        self.assertRaises(SynapseError)
        self.assertEquals(400, channel.code)
        self.assertEquals(
            "The url doesn't point to a valid nextcloud directory path.",
            json.loads(channel.result["body"])["error"],
        )

    def test_update_nextcloud_share_on_invite_and_join_event(self):
        self.helper.invite(
            self.room_id, self.creator, self.inviter, tok=self.creator_tok
        )

        request, channel = self.make_request(
            "POST",
            "/_matrix/client/r0/rooms/{}/join".format(self.room_id),
            access_token=self.inviter_tok,
        )
        self.render(request)

        self.assertEquals(self.nextcloud_client.add_user_to_group.call_count, 2)
        self.assertEqual(200, channel.code)

    def test_update_nextcloud_share_on_leave_event(self):
        self.helper.invite(
            self.room_id, self.creator, self.inviter, tok=self.creator_tok
        )

        request, channel = self.make_request(
            "POST",
            "/_matrix/client/r0/rooms/{}/leave".format(self.room_id),
            access_token=self.inviter_tok,
        )
        self.render(request)

        self.nextcloud_client.add_user_to_group.assert_called_once()
        self.nextcloud_client.remove_user_from_group.assert_called_once()
        self.assertEqual(200, channel.code)

    def test_update_nextcloud_share_on_kick_event(self):
        self.helper.invite(
            self.room_id, self.creator, self.inviter, tok=self.creator_tok
        )
        self.helper.join(self.room_id, user=self.inviter, tok=self.inviter_tok)

        request, channel = self.make_request(
            "POST",
            "/_matrix/client/r0/rooms/{}/kick".format(self.room_id),
            content={"user_id": self.inviter},
            access_token=self.inviter_tok,
        )
        self.render(request)

        self.assertEquals(self.nextcloud_client.add_user_to_group.call_count, 2)
        self.nextcloud_client.remove_user_from_group.assert_called_once()
        self.assertEqual(200, channel.code)

    def test_update_nextcloud_share_with_an_unmapped_room(self):
        self.nextcloud_handler.update_existing_nextcloud_share_for_user = (
            simple_async_mock()
        )

        room_id = self.helper.create_room_as(self.creator, tok=self.creator_tok)

        self.helper.invite(room_id, self.creator, self.inviter, tok=self.creator_tok)

        self.nextcloud_handler.update_existing_nextcloud_share_for_user.assert_not_called()


class NextcloudActivityTestCase(unittest.HomeserverTestCase):

    servlets = [
        login.register_servlets,
        watcha.register_servlets,
        admin.register_servlets_for_client_rest_resource,
        room.register_servlets,
    ]

    def prepare(self, reactor, clock, hs):
        self.store = hs.get_datastore()
        self.room_creator = hs.get_room_creation_handler()

        # register admin user:
        self.register_user("admin", "pass", True)
        self.user_access_token = self.login("admin", "pass")

        # user who creates rooms :
        self.user = UserID("user", "test")

        self.nextcloud_directory_url = "https://test/nextcloud/apps/files/?dir="
        self.nextcloud_root_directory = "/"
        self.nextcloud_file_name = "WATCHA-Brochure A4.pdf"
        self.nextcloud_file_url = "https://test/nextcloud/f/307"

        self.rooms_mapping = self.get_success(
            self._do_rooms_mapping_with_nextcloud_directories()
        )

    def _create_room(self):
        requester = create_requester(self.user)

        return self.get_success(self.room_creator.create_room(requester, {}))[0][
            "room_id"
        ]

    async def _do_rooms_mapping_with_nextcloud_directories(self):
        rooms_mapping = {
            "parent_directory": {"path": "/a", "share_id": 1},
            "main_directory": {"path": "/a/b", "share_id": 2},
            "sub_directory": {"path": "/a/b/c", "share_id": 3},
            "cross_directory": {"path": "/a/d", "share_id": 4},
        }

        for _, mapping_value in rooms_mapping.items():
            room_id = self._create_room()
            mapping_value["room_id"] = room_id

            await self.store.bind(
                room_id, mapping_value["path"], mapping_value["share_id"]
            )

        return rooms_mapping

    def _send_POST_nextcloud_notification_request(self, request_content):
        request, channel = self.make_request(
            "POST",
            "/watcha_room_nextcloud_activity",
            content=json.dumps(request_content),
            access_token=self.user_access_token,
        )
        self.render(request)

        return channel

    def test_send_notification_for_basic_file_operations_in_parent_directory(self):
        room_id = self.rooms_mapping["parent_directory"]["room_id"]
        request_content = {
            "file_name": self.nextcloud_file_name,
            "file_url": self.nextcloud_file_url,
            "notifications": [
                {
                    "activity_type": "file_created",
                    "directory": self.rooms_mapping["parent_directory"]["path"],
                    "limit_of_notification_propagation": self.nextcloud_root_directory,
                },
            ],
        }

        # case of file created :
        channel = self._send_POST_nextcloud_notification_request(request_content)
        self.assertEquals(200, channel.code)
        self.assertEquals(
            json.loads(channel.result["body"]),
            [
                {
                    "file_name": self.nextcloud_file_name,
                    "file_operation": "file_created",
                    "notified_rooms": [
                        {"room_id": room_id, "sender": self.user.to_string()}
                    ],
                },
            ],
        )

        # case of file deleted :
        request_content["notifications"][0]["activity_type"] = "file_deleted"
        channel = self._send_POST_nextcloud_notification_request(request_content)
        self.assertEquals(200, channel.code)
        self.assertEquals(
            json.loads(channel.result["body"]),
            [
                {
                    "file_name": self.nextcloud_file_name,
                    "file_operation": "file_deleted",
                    "notified_rooms": [
                        {"room_id": room_id, "sender": self.user.to_string()}
                    ],
                },
            ],
        )

        # case of restored :
        request_content["notifications"][0]["activity_type"] = "file_restored"
        channel = self._send_POST_nextcloud_notification_request(request_content)
        self.assertEquals(200, channel.code)
        self.assertEquals(
            json.loads(channel.result["body"]),
            [
                {
                    "file_name": self.nextcloud_file_name,
                    "file_operation": "file_restored",
                    "notified_rooms": [
                        {"room_id": room_id, "sender": self.user.to_string()}
                    ],
                },
            ],
        )

    def test_send_notification_with_unrecognized_file_operation(self):
        with self.assertLogs("synapse.rest.client.v1.watcha", level="INFO") as log:
            request_content = {
                "file_name": self.nextcloud_file_name,
                "file_url": self.nextcloud_file_url,
                "notifications": [
                    {
                        "activity_type": "unrecognized_operation",
                        "directory": self.rooms_mapping["parent_directory"]["path"],
                        "limit_of_notification_propagation": self.nextcloud_root_directory,
                    },
                ],
            }

            channel = self._send_POST_nextcloud_notification_request(request_content)
            self.assertIn(
                "WARNING:synapse.rest.client.v1.watcha:This nextcloud file operation is not handled",
                log.output[0],
            )

    def test_send_notification_with_unlinked_directory(self):
        with self.assertLogs("synapse.rest.client.v1.watcha", level="INFO") as log:
            request_content = {
                "file_name": self.nextcloud_file_name,
                "file_url": self.nextcloud_file_url,
                "notifications": [
                    {
                        "activity_type": "file_created",
                        "directory": "/unlinked/directory",
                        "limit_of_notification_propagation": self.nextcloud_root_directory,
                    },
                ],
            }

            channel = self._send_POST_nextcloud_notification_request(request_content)
            self.assertIn(
                "ERROR:synapse.rest.client.v1.watcha:Error during getting rooms to send notifications : 400: No rooms are linked with this Nextcloud directory.",
                log.output[0],
            )

    def test_send_notification_with_empty_directory_path(self):
        with self.assertLogs("synapse.rest.client.v1.watcha", level="INFO") as log:
            request_content = {
                "file_name": self.nextcloud_file_name,
                "file_url": self.nextcloud_file_url,
                "notifications": [
                    {
                        "activity_type": "file_created",
                        "directory": "",
                        "limit_of_notification_propagation": self.nextcloud_root_directory,
                    },
                ],
            }

            channel = self._send_POST_nextcloud_notification_request(request_content)
            self.assertIn(
                "ERROR:synapse.rest.client.v1.watcha:Error during getting rooms to send notifications : 400: The directory path is empty",
                log.output[0],
            )

    def test_send_notification_with_missing_notification_parameters(self):
        with self.assertLogs("synapse.rest.client.v1.watcha", level="INFO") as log:
            request_content = {
                "file_name": self.nextcloud_file_name,
                "file_url": self.nextcloud_file_url,
                "notifications": [
                    {
                        "activity_type": "file_created",
                    }
                ],
            }

            request_content["notifications"][0].pop("activity_type", None)
            channel = self._send_POST_nextcloud_notification_request(request_content)
            self.assertIn(
                "WARNING:synapse.rest.client.v1.watcha:It missing some parameters to notify file operation",
                log.output[0],
            )

    def test_send_notification_with_empty_values_in_payload(self):
        request_content = {
            "file_name": "",
            "file_url": "",
            "notifications": [],
        }

        channel = self._send_POST_nextcloud_notification_request(request_content)
        self.assertEquals(400, channel.code)
        self.assertEquals(
            json.loads(channel.result["body"])["error"],
            "Some data in payload have empty value.",
        )

    def test_send_notification_with_wrong_file_url(self):
        urls = ["scheme://test/nextcloud/f/307", "https://localhost/nextcloud/f/307"]

        for url in urls:
            request_content = {
                "file_name": self.nextcloud_file_name,
                "file_url": url,
                "notifications": [
                    {
                        "activity_type": "file_created",
                        "directory": "/parent_directory/Test_NC",
                        "limit_of_notification_propagation": "/",
                    },
                ],
            }

            channel = self._send_POST_nextcloud_notification_request(request_content)
            self.assertEquals(400, channel.code)
            self.assertEquals(
                json.loads(channel.result["body"])["error"],
                "The Nextcloud url is not recognized.",
            )

    def test_propagate_notification_in_rooms(self):
        parent_room_id = self.rooms_mapping["parent_directory"]["room_id"]
        main_room_id = self.rooms_mapping["main_directory"]["room_id"]
        sub_room_id = self.rooms_mapping["sub_directory"]["room_id"]
        cross_room_id = self.rooms_mapping["cross_directory"]["room_id"]

        request_content = {
            "file_name": self.nextcloud_file_name,
            "file_url": self.nextcloud_file_url,
            "notifications": [
                {
                    "activity_type": "file_created",
                    "directory": "",
                    "limit_of_notification_propagation": "/",
                },
            ],
        }

        # in subdirectory :
        request_content["notifications"][0]["directory"] = self.rooms_mapping[
            "sub_directory"
        ]["path"]
        channel = self._send_POST_nextcloud_notification_request(request_content)
        self.assertEquals(200, channel.code)
        self.assertEquals(
            json.loads(channel.result["body"]),
            [
                {
                    "file_name": self.nextcloud_file_name,
                    "file_operation": "file_created",
                    "notified_rooms": [
                        {"room_id": main_room_id, "sender": self.user.to_string()},
                        {"room_id": parent_room_id, "sender": self.user.to_string()},
                        {"room_id": sub_room_id, "sender": self.user.to_string()},
                    ],
                }
            ],
        )

        # in main directory :
        request_content["notifications"][0]["directory"] = self.rooms_mapping[
            "main_directory"
        ]["path"]
        channel = self._send_POST_nextcloud_notification_request(request_content)
        self.assertEquals(200, channel.code)
        self.assertEquals(
            json.loads(channel.result["body"]),
            [
                {
                    "file_name": self.nextcloud_file_name,
                    "file_operation": "file_created",
                    "notified_rooms": [
                        {"room_id": parent_room_id, "sender": self.user.to_string()},
                        {"room_id": main_room_id, "sender": self.user.to_string()},
                    ],
                }
            ],
        )

        # parent directory :
        request_content["notifications"][0]["directory"] = self.rooms_mapping[
            "parent_directory"
        ]["path"]
        channel = self._send_POST_nextcloud_notification_request(request_content)
        self.assertEquals(200, channel.code)
        self.assertEquals(
            json.loads(channel.result["body"]),
            [
                {
                    "file_name": self.nextcloud_file_name,
                    "file_operation": "file_created",
                    "notified_rooms": [
                        {"room_id": parent_room_id, "sender": self.user.to_string()},
                    ],
                }
            ],
        )

        # cross directory :
        request_content["notifications"][0]["directory"] = self.rooms_mapping[
            "cross_directory"
        ]["path"]
        channel = self._send_POST_nextcloud_notification_request(request_content)
        self.assertEquals(200, channel.code)
        self.assertEquals(
            json.loads(channel.result["body"]),
            [
                {
                    "file_name": self.nextcloud_file_name,
                    "file_operation": "file_created",
                    "notified_rooms": [
                        {"room_id": parent_room_id, "sender": self.user.to_string()},
                        {"room_id": cross_room_id, "sender": self.user.to_string()},
                    ],
                }
            ],
        )

        # case of cross moved (/a/b/c to /a/d) :
        # In Watcha rooms, it's like :
        # - Deletion notification in source directory and all parents directories between source directory and root directory (/a in our example).
        # - Creation notification in target directory and all parents directories between target directory and root directory (/a in our example).
        # - Movement notification in root directory and all parents directories of root directory (/a in our example).
        request_content["notifications"] = [
            {
                "activity_type": "file_deleted",
                "directory": self.rooms_mapping["sub_directory"]["path"],
                "limit_of_notification_propagation": self.rooms_mapping[
                    "parent_directory"
                ]["path"],
            },
            {
                "activity_type": "file_created",
                "directory": self.rooms_mapping["cross_directory"]["path"],
                "limit_of_notification_propagation": self.rooms_mapping[
                    "parent_directory"
                ]["path"],
            },
            {
                "activity_type": "file_moved",
                "directory": self.rooms_mapping["parent_directory"]["path"],
                "limit_of_notification_propagation": self.nextcloud_root_directory,
            },
        ]

        channel = self._send_POST_nextcloud_notification_request(request_content)
        self.assertEquals(200, channel.code)
        self.assertEquals(
            json.loads(channel.result["body"]),
            [
                {
                    "file_name": self.nextcloud_file_name,
                    "file_operation": "file_deleted",
                    "notified_rooms": [
                        {"room_id": main_room_id, "sender": self.user.to_string()},
                        {"room_id": sub_room_id, "sender": self.user.to_string()},
                    ],
                },
                {
                    "file_name": self.nextcloud_file_name,
                    "file_operation": "file_created",
                    "notified_rooms": [
                        {"room_id": cross_room_id, "sender": self.user.to_string()},
                    ],
                },
                {
                    "file_name": self.nextcloud_file_name,
                    "file_operation": "file_moved",
                    "notified_rooms": [
                        {"room_id": parent_room_id, "sender": self.user.to_string()},
                    ],
                },
            ],
        )


# +watcha
