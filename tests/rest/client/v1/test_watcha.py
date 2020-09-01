import json, logging, hmac, hashlib

from tests import unittest
from tests.utils import setup_test_homeserver
from synapse.rest.client.v1 import watcha, login, room
from synapse.rest import admin
from synapse.api.errors import SynapseError
from twisted.internet import defer

logger = logging.getLogger(__name__)


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
        self._auth_handler = hs.get_auth_handler()
        self.get_success(
            self._auth_handler.add_threepid(
                self.user_id, "email", "example@email.com", self.time
            )
        )
        self.nextcloud_folder_url = "https://test/nextcloud/apps/files/?dir=/Partage"

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
        request, channel = self.make_request(
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
            "GET", "watcha_user_list", access_token=self.user_access_token,
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
            "GET", "/watcha_admin_stats", access_token=self.user_access_token,
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
                "other_statistics": {"number_of_users_with_pending_invitation": 2,},
            },
        )

    def test_get_watcha_admin_stats_room_type(self):
        room_id = self._create_room()
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
        rooms_id = []
        for _ in range(3):
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

class WatchaSendNextcloudActivityToWatchaRoomServletTestCase(BaseHomeserverWithEmailTestCase):

    def _send_POST_nextcloud_notification_request(self, request_content):
        request, channel = self.make_request(
            "POST",
            "/watcha_room_nextcloud_activity",
            content=json.dumps(request_content),
            access_token=self.user_access_token,
        )
        self.render(request)

        return channel

    def _do_room_mapping_with_nextcloud_folder(self):
        room_id = self._create_room()
        request, channel = self.make_request(
            "PUT",
            "/rooms/{}/state/im.vector.web.settings".format(room_id),
            content=json.dumps({"nextcloud": self.nextcloud_folder_url}),
            access_token=self.user_access_token,
        )
        self.render(request)

        return channel

    def test_do_room_mapping_with_same_nextcloud_folder(self):
        self._do_room_mapping_with_nextcloud_folder()
        channel = self._do_room_mapping_with_nextcloud_folder()

        self.assertEquals(500, channel.code)
        self.assertEquals(
            json.loads(channel.result["body"])["error"],
            "This Nextcloud folder is already linked with another room.",
        )

    def test_send_nextcloud_notification_in_unlinked_room(self):
        request_content = {
            "file_name": "WATCHA-Brochure A4.pdf",
            "directory": self.nextcloud_folder_url,
            "link": "https://test/nextcloud/f/307",
            "activity_type": "file_created",
        }

        channel = self._send_POST_nextcloud_notification_request(request_content)

        self.assertEquals(400, channel.code)
        self.assertEquals(
            json.loads(channel.result["body"])["error"],
            "No room has been linked with this Nextcloud folder url.",
        )

    def test_send_nextcloud_file_notification_in_linked_room(self):
        self._do_room_mapping_with_nextcloud_folder()
        request_content = {
            "file_name": "WATCHA-Brochure A4.pdf",
            "directory": self.nextcloud_folder_url,
            "link": "https://test/nextcloud/f/307",
            "activity_type": "file_created",
        }

        channel = self._send_POST_nextcloud_notification_request(request_content)
        self.assertEquals(200, channel.code)

        request_content["activity_type"] = "file_deleted"
        channel = self._send_POST_nextcloud_notification_request(request_content)
        self.assertEquals(200, channel.code)

        request_content["activity_type"] = "file_restored"
        channel = self._send_POST_nextcloud_notification_request(request_content)
        self.assertEquals(200, channel.code)

        request_content["activity_type"] = "file_changed"
        channel = self._send_POST_nextcloud_notification_request(request_content)
        self.assertEquals(400, channel.code)
        self.assertEquals(
            json.loads(channel.result["body"])["error"],
            "'file_changed' Nextcloud activity is not managed.",
        )

        request_content["activity_type"] = "wrong type"
        channel = self._send_POST_nextcloud_notification_request(request_content)
        self.assertEquals(400, channel.code)
        self.assertEquals(
            json.loads(channel.result["body"])["error"],
            "Wrong value for nextcloud activity_type.",
        )

    def test_send_nextcloud_notification_in_linked_room_with_empty_values(self):
        self._do_room_mapping_with_nextcloud_folder()
        request_content = {
            "file_name": "",
            "directory": "",
            "link": "",
            "activity_type": "",
        }

        channel = self._send_POST_nextcloud_notification_request(request_content)
        self.assertEquals(400, channel.code)
        self.assertEquals(
            json.loads(channel.result["body"])["error"],
            "'file_name', 'link', 'directory args and 'activity_type' cannot be empty.",
        )

    def test_send_nextcloud_notification_in_linked_room_with_wrong_url_scheme(self):
        self._do_room_mapping_with_nextcloud_folder()
        request_content = {
            "file_name": "WATCHA-Brochure A4.pdf",
            "directory": "scheme://test/nextcloud/apps/files/?dir=/Partage",
            "link": "scheme://test/nextcloud/f/307",
            "activity_type": "file_created",
        }

        channel = self._send_POST_nextcloud_notification_request(request_content)
        self.assertEquals(400, channel.code)
        self.assertEquals(
            json.loads(channel.result["body"])["error"], "Wrong Nextcloud URL scheme.",
        )

    def test_send_nextcloud_notification_in_linked_room_with_wrong_url_netloc(self):
        self._do_room_mapping_with_nextcloud_folder()
        request_content = {
            "file_name": "WATCHA-Brochure A4.pdf",
            "directory": "https://localhost/nextcloud/apps/files/?dir=/Partage",
            "link": "https://localhost/nextcloud/f/307",
            "activity_type": "file_created",
        }

        channel = self._send_POST_nextcloud_notification_request(request_content)
        self.assertEquals(400, channel.code)
        self.assertEquals(
            json.loads(channel.result["body"])["error"], "Wrong Nextcloud URL netloc.",
        )
