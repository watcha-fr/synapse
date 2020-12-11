import json, logging
from mock import Mock

from synapse.rest import admin
from synapse.rest.client.v1 import watcha, login, room
from synapse.types import UserID, create_requester
from tests import unittest
from tests.test_utils import get_awaitable_result
from tests.utils import setup_test_homeserver

logger = logging.getLogger(__name__)


def simple_async_mock(return_value=None, raises=None):
    # AsyncMock is not available in python3.5, this mimics part of its behaviour
    async def cb(*args, **kwargs):
        if raises:
            raise raises
        return return_value

    return Mock(side_effect=cb)


class BaseHomeserverWithEmailTestCase(unittest.HomeserverTestCase):

    servlets = [
        admin.register_servlets_for_client_rest_resource,
        login.register_servlets,
        watcha.register_servlets,
        room.register_servlets,
    ]

    def make_homeserver(self, reactor, clock):
        self.hs = self.setup_test_homeserver(
            config={
                **self.default_config(),
                "require_auth_for_profile_requests": True,
                "email": {
                    "riot_base_url": "http://localhost:8080",
                    "smtp_host": "TEST",
                    "smtp_port": 10,
                    "notif_from": "TEST",
                },
                "public_baseurl": "TEST",
            }
        )
        self.auth = self.hs.get_auth_handler()

        return self.hs

    def prepare(self, reactor, clock, hs):
        # Admin_user register.
        self.time = self.hs.get_clock().time_msec()
        self.user_id = self.register_user("admin", "pass", True)
        self.user_access_token = self.login("admin", "pass")
        self.get_success(
            self.auth.add_threepid(
                self.user_id, "email", "example@email.com", self.time
            )
        )

        self.room_id = self._create_room()

        self.nextcloud_handler = hs.get_nextcloud_handler()
        self.keycloak_client = self.nextcloud_handler.keycloak_client
        self.nextcloud_client = self.nextcloud_handler.nextcloud_client

        self.keycloak_client.add_user = simple_async_mock()
        self.keycloak_client.get_user = simple_async_mock(return_value={"id": "1234"})
        self.nextcloud_client.add_user = simple_async_mock()

    def _do_register_user(self, request_content):
        # Admin send the request with access_token :
        request, channel = self.make_request(
            "POST",
            "/_matrix/client/r0/watcha_register",
            content=json.dumps(request_content),
            access_token=self.user_access_token,
        )
        self.render(request)
        return channel

    def _create_room(self):
        request, channel = self.make_request(
            "POST",
            "/createRoom",
            content=json.dumps({}),
            access_token=self.user_access_token,
        )

        self.render(request)
        return json.loads(channel.result["body"])["room_id"]

    def _invite_member_in_room(self, room_id, user_id):
        request, _ = self.make_request(
            "POST",
            "/rooms/%s/invite" % room_id,
            content=json.dumps({"user_id": user_id}),
            access_token=self.user_access_token,
        )

        self.render(request)


class WatchaRegisterRestServletTestCase(BaseHomeserverWithEmailTestCase):
    def test_register_user(self):
        with self.assertLogs("synapse.util.watcha", level="INFO") as cm:
            request_content = {
                "user": "user_test",
                "full_name": "test",
                "email": "test@test.com",
                "admin": False,
                "password": "",
            }

            channel = self._do_register_user(request_content)
            self.assertIn(
                "INFO:synapse.util.watcha:NOT Sending registration email to 'test@test.com', we are in test mode",
                "".join(cm.output),
            )
            self.assertIn(" http://localhost:8080/#/login/t=", "".join(cm.output))
            self.assertEqual(
                channel.result["body"],
                b'{"display_name":"test","user_id":"@user_test:test"}',
            )
            self.assertEqual(channel.code, 200)

    def test_register_user_with_password(self):
        request_content = {
            "user": "user_test",
            "full_name": "test",
            "email": "test@test.com",
            "admin": False,
            "password": "password",
        }
        channel = self._do_register_user(request_content)
        self.assertEqual(
            channel.result["body"],
            b'{"display_name":"test","user_id":"@user_test:test"}',
        )

        self.assertTrue(self.keycloak_client.add_user.called)
        self.assertTrue(self.keycloak_client.get_user.called)
        self.assertTrue(self.nextcloud_client.add_user.called)
        self.assertEqual(channel.code, 200)

    def test_register_user_with_upper_user_id(self):
        request_content = {
            "user": "USER_TEST",
            "full_name": "test",
            "email": "test@test.com",
            "admin": False,
            "password": "",
        }
        channel = self._do_register_user(request_content)

        self.assertFalse(self.keycloak_client.add_user.called)
        self.assertFalse(self.keycloak_client.get_user.called)
        self.assertFalse(self.nextcloud_client.add_user.called)
        self.assertEqual(channel.code, 500)

    def test_register_user_with_empty_email(self):
        request_content = {
            "user": "user_test",
            "full_name": "test",
            "email": "",
            "admin": False,
            "password": "",
        }
        channel = self._do_register_user(request_content)

        self.assertFalse(self.keycloak_client.add_user.called)
        self.assertFalse(self.keycloak_client.get_user.called)
        self.assertFalse(self.nextcloud_client.add_user.called)
        self.assertEqual(channel.code, 500)

    def test_register_user_with_same_email_adress(self):
        request_content = {
            "user": "user_test",
            "full_name": "test",
            "email": "test@test.com",
            "admin": False,
            "password": "",
        }
        self._do_register_user(request_content)
        request_content = {
            "user": "other_user",
            "full_name": "other",
            "email": "test@test.com",
            "admin": False,
            "password": "",
        }
        channel = self._do_register_user(request_content)

        self.keycloak_client.add_user.assert_called_once()
        self.keycloak_client.get_user.assert_called_once()
        self.nextcloud_client.add_user.assert_called_once()
        self.assertEqual(channel.code, 500)

    def test_register_user_with_plus_in_email(self):
        with self.assertLogs("synapse.util.watcha", level="INFO") as cm:
            request_content = {
                "user": "user_test",
                "full_name": "test",
                "email": "test+test@test.com",
                "admin": False,
                "password": "",
            }

            channel = self._do_register_user(request_content)
            self.assertIn(
                "INFO:synapse.util.watcha:NOT Sending registration email to 'test+test@test.com', we are in test mode",
                "".join(cm.output),
            )
            self.assertIn(" http://localhost:8080/#/login/t=", "".join(cm.output))
            self.assertEqual(
                channel.result["body"],
                b'{"display_name":"test","user_id":"@user_test:test"}',
            )
            self.assertTrue(self.keycloak_client.add_user.called)
            self.assertTrue(self.keycloak_client.get_user.called)
            self.assertTrue(self.nextcloud_client.add_user.called)
            self.assertEqual(channel.code, 200)


class WatchaResetPasswordRestServletTestCase(BaseHomeserverWithEmailTestCase):
    def test_reset_password(self):
        self._do_register_user(
            {
                "user": "user_test",
                "full_name": "test",
                "email": "test@test.com",
                "admin": False,
                "password": "password",
            }
        )
        with self.assertLogs("synapse.util.watcha", level="INFO") as cm:
            request, channel = self.make_request(
                "POST",
                "/_matrix/client/r0/watcha_reset_password",
                content=json.dumps({"user": "user_test"}),
                access_token=self.user_access_token,
            )
            self.render(request)

            self.assertIn(
                "INFO:synapse.util.watcha:NOT Sending registration email to 'test@test.com', we are in test mode",
                "".join(cm.output),
            )
            self.assertIn(
                "http://localhost:8080/setup-account.html?t=", "".join(cm.output)
            )
            self.assertEqual(channel.code, 200)


class WatchaAdminStatsTestCase(BaseHomeserverWithEmailTestCase):
    def test_watcha_user_list(self):
        self._do_register_user(
            {
                "user": "user_test",
                "full_name": "test",
                "email": "test@test.com",
                "admin": False,
                "password": "",
            }
        )

        request, channel = self.make_request(
            "POST",
            "admin/deactivate/@user_test:test",
            access_token=self.user_access_token,
        )
        self.render(request)

        request, channel = self.make_request(
            "GET",
            "watcha_user_list",
            access_token=self.user_access_token,
        )
        self.render(request)

        self.assertEqual(
            json.loads(channel.result["body"]),
            [
                {
                    "creation_ts": 0,
                    "display_name": "admin",
                    "email_address": "example@email.com",
                    "last_seen": None,
                    "role": "administrator",
                    "status": "invited",
                    "user_id": "@admin:test",
                },
                {
                    "creation_ts": 0,
                    "display_name": "test",
                    "email_address": None,
                    "last_seen": None,
                    "role": "collaborator",
                    "status": "inactive",
                    "user_id": "@user_test:test",
                },
            ],
        )

    def test_get_watcha_admin_user_stats(self):
        self._do_register_user(
            {
                "user": "user_test",
                "full_name": "test",
                "email": "test@test.com",
                "admin": False,
                "password": "",
            }
        )

        request, channel = self.make_request(
            "GET",
            "/watcha_admin_stats",
            access_token=self.user_access_token,
        )
        self.render(request)
        self.assertEquals(
            json.loads(channel.result["body"])["users"],
            {
                "administrators_users": [
                    {
                        "displayname": None,
                        "email": "example@email.com",
                        "user_id": "@admin:test",
                    }
                ],
                "users_per_role": {
                    "administrators": 1,
                    "collaborators": 1,
                    "partners": 0,
                },
                "connected_users": {
                    "number_of_users_logged_at_least_once": 0,
                    "number_of_last_month_logged_users": 0,
                    "number_of_last_week_logged_users": 0,
                },
                "other_statistics": {
                    "number_of_users_with_pending_invitation": 2,
                },
            },
        )

    def test_get_watcha_admin_stats_room_type(self):
        room_id = self.room_id
        self._invite_member_in_room(room_id, self.user_id)

        request, channel = self.make_request(
            "GET", "watcha_admin_stats", access_token=self.user_access_token
        )
        self.render(request)

        self.assertEquals(
            json.loads(channel.result["body"])["rooms"],
            {
                "active_dm_room_count": 0,
                "dm_room_count": 0,
                "active_regular_room_count": 0,
                "regular_room_count": 1,
            },
        )
        self.assertEquals(200, channel.code)

    def test_get_watcha_admin_stats_room_list(self):
        rooms_id = [self.room_id]
        for _ in range(2):
            room_id = self._create_room()
            rooms_id.append(room_id)
            self._invite_member_in_room(room_id, self.user_id)

        rooms_id = sorted(rooms_id)

        request, channel = self.make_request(
            "GET", "watcha_room_list", access_token=self.user_access_token
        )
        self.render(request)

        for room_id in rooms_id:
            self.assertEquals(
                json.loads(channel.result["body"])[rooms_id.index(room_id)],
                {
                    "creator": "@admin:test",
                    "members": ["@admin:test"],
                    "name": None,
                    "room_id": room_id,
                    "status": "inactive",
                    "type": "regular_room",
                },
            )
        self.assertEquals(200, channel.code)


class WatchaSendNextcloudActivityToWatchaRoomServletTestCase(
    unittest.HomeserverTestCase
):

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
