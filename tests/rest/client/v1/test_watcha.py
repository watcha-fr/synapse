import json, logging, hmac, hashlib

from tests import unittest
from tests.utils import setup_test_homeserver
from synapse.rest.client.v1 import watcha, login, room
from synapse.rest import admin
from synapse.api.errors import SynapseError

logger = logging.getLogger(__name__)

class BaseHomeserverWithEmailTestCase(unittest.HomeserverTestCase):

    servlets = [
        admin.register_servlets_for_client_rest_resource,
        login.register_servlets,
        watcha.register_servlets,
        room.register_servlets,
    ]

    def make_homeserver(self, reactor, clock):
        self.hs = self.setup_test_homeserver(config={
            **self.default_config(),
            "require_auth_for_profile_requests": True,
            "email": {
                "riot_base_url": "http://localhost:8080",
                "smtp_host": "TEST",
                "smtp_port": 10,
                "notif_from": "TEST"
            },
            "public_baseurl": "TEST"
        })
        self.auth = self.hs.get_auth_handler()

        return self.hs

    def prepare(self, reactor, clock, hs):
        # Admin_user register.
        self.time = self.hs.get_clock().time_msec()
        self.user_id = self.register_user("admin", "pass", True)
        self.user_access_token = self.login("admin", "pass")
        self.auth.add_threepid(self.user_id, "email", "example@email.com", self.time)
        self.nextcloud_folder_url = "https://test/nextcloud/apps/files/?dir=/parent_directory/Test_NC"

        self.room_id = self._create_room()
        self._do_room_mapping_with_nextcloud_folder(self.nextcloud_folder_url, self.room_id)

    def _do_register_user(self, request_content):
        #Admin send the request with access_token :
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

    def _do_room_mapping_with_nextcloud_folder(self, nextcloud_url, room_id):
        request, _ = self.make_request(
            "PUT",
            "/rooms/{}/state/im.vector.web.settings".format(room_id),
            content=json.dumps({"nextcloud": nextcloud_url}),
            access_token=self.user_access_token,
        )
        self.render(request)

class WatchaRegisterRestServletTestCase(BaseHomeserverWithEmailTestCase):

    def test_register_user(self):
        with self.assertLogs('synapse.util.watcha', level='INFO') as cm:
            request_content = {"user":"user_test", "full_name":"test", "email":"test@test.com", "admin":False}
            channel = self._do_register_user(request_content)
            self.assertIn("INFO:synapse.util.watcha:NOT Sending registration email to \'test@test.com\', we are in test mode",
                            ''.join(cm.output))
            self.assertIn(" http://localhost:8080/#/login/t=",
                            ''.join(cm.output))
            self.assertEqual(channel.result['body'], b'{"display_name":"test","user_id":"@user_test:test"}')
            self.assertEqual(channel.code,200)

    def test_register_user_with_upper_user_id(self):
        request_content = {"user":"USER_TEST", "full_name":"test", "email":"test@test.com", "admin":False}
        channel = self._do_register_user(request_content)
        self.assertEqual(channel.code,500)

    def test_register_user_with_empty_email(self):
        request_content = {"user":"user_test", "full_name":"test", "email":"", "admin":False}
        channel = self._do_register_user(request_content)
        self.assertEqual(channel.code,500)

    def test_register_user_with_same_email_adress(self):
        request_content = {"user":"user_test", "full_name":"test", "email":"test@test.com", "admin":False}
        self._do_register_user(request_content)
        request_content = {"user":"other_user", "full_name":"other", "email":"test@test.com", "admin":False}
        channel = self._do_register_user(request_content)
        self.assertEqual(channel.code,500)

    def test_register_user_with_plus_in_email(self):
        with self.assertLogs('synapse.util.watcha', level='INFO') as cm:
            request_content = {"user":"user_test", "full_name":"test", "email":"test+test@test.com", "admin":False}
            channel = self._do_register_user(request_content)
            self.assertIn("INFO:synapse.util.watcha:NOT Sending registration email to \'test+test@test.com\', we are in test mode",
                            ''.join(cm.output))
            self.assertIn(" http://localhost:8080/#/login/t=",
                            ''.join(cm.output))
            self.assertEqual(channel.result['body'], b'{"display_name":"test","user_id":"@user_test:test"}')
            self.assertEqual(channel.code,200)


class WatchaResetPasswordRestServletTestCase(BaseHomeserverWithEmailTestCase):

    def test_reset_password(self):
        self._do_register_user({"user":"user_test",
                                "full_name":"test",
                                "email":"test@test.com",
                                "admin": False })
        with self.assertLogs('synapse.util.watcha', level='INFO') as cm:
            request, channel = self.make_request(
                "POST",
                "/_matrix/client/r0/watcha_reset_password",
                content=json.dumps({ "user": "user_test" }),
                access_token=self.user_access_token,
            )
            self.render(request)

            self.assertIn("INFO:synapse.util.watcha:NOT Sending registration email to \'test@test.com\', we are in test mode",
                            ''.join(cm.output))
            self.assertIn("http://localhost:8080/setup-account.html?t=",
                            ''.join(cm.output))
            self.assertEqual(channel.code,200)


class WatchaAdminStatsTestCase(BaseHomeserverWithEmailTestCase):

    def test_watcha_user_list(self):
        self._do_register_user(
            {
                "user": "user_test",
                "full_name": "test",
                "email": "test@test.com",
                "admin": False,
            }
        )

        request, channel = self.make_request(
            "POST", "admin/deactivate/@user_test:test", access_token=self.user_access_token,
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
                    "email_address": "test@test.com",
                    "last_seen": None,
                    "role": "collaborator",
                    "status": "inactive",
                    "user_id": "@user_test:test",
                },
            ],
        )
    
    def test_get_watcha_admin_user_stats(self):
        self._do_register_user({"user":"user_test",
                                "full_name":"test",
                                "email":"test@test.com",
                                "admin": False })

        request, channel = self.make_request(
                "GET",
                "/watcha_admin_stats",
                access_token=self.user_access_token,
        )
        self.render(request)

        self.assertEquals(
            json.loads(channel.result["body"])["users"],
            {
                "administrators_users": [{"displayname": None,
                    "email": "example@email.com",
                    "user_id": "@admin:test"}],
                "users_per_role": {
                    "administrators": 1,
                    "collaborators": 1,
                    "partners": 0,
                },
                "connected_users": {
                    "number_of_users_logged_at_least_once":0,
                    "number_of_last_month_logged_users":0,
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

class WatchaSendNextcloudActivityToWatchaRoomServlet(BaseHomeserverWithEmailTestCase):
    def _do_hmac_with_shared_secret(self, parameters):
        mac = hmac.new(
            key=self.hs.get_config().registration_shared_secret.encode(),
            digestmod=hashlib.sha1,
        )

        for parameter_value in parameters:
            mac.update(parameter_value.encode())
            mac.update(b"\x00")

        return mac.hexdigest()

    def _send_POST_nextcloud_notification_request(self, request_content):
        mac = self._do_hmac_with_shared_secret(request_content)
        request_content["mac"] = mac

        request, channel = self.make_request(
            "POST",
            "/watcha_room_nextcloud_activity",
            content=json.dumps(request_content),
            access_token=self.user_access_token,
        )
        self.render(request)

        return channel

    def test_send_nextcloud_notification_in_unlinked_nextcloud_directory(self):
        request_content = {
            "file_name": "WATCHA-Brochure A4.pdf",
            "directory": "https://test/nextcloud/apps/files/?dir=/unlinked_directory",
            "link": "https://test/nextcloud/f/307",
            "activity_type": "file_created",
        }

        channel = self._send_POST_nextcloud_notification_request(request_content)

        self.assertEquals(400, channel.code)
        self.assertEquals(
            json.loads(channel.result["body"])["error"],
            "No rooms has been linked with this Nextcloud directory.",
        )

    def test_send_nextcloud_file_notification_in_linked_room(self):
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
            "Some data in payload have empty value.",
        )

    def test_send_nextcloud_notification_in_linked_room_with_unrecognized_url(self):
        urls = [
            {
                "directory": "scheme://test/nextcloud/apps/files/?dir=/Partage",
                "link": "scheme://test/nextcloud/f/307",
            },
            {
                "directory": "https://localhost/nextcloud/apps/files/?dir=/Partage",
                "link": "https://localhost/nextcloud/f/307",
            },
        ]

        for url in urls:
            request_content = {
                "file_name": "WATCHA-Brochure A4.pdf",
                "directory": url["directory"],
                "link": url["link"],
                "activity_type": "file_created",
            }

            channel = self._send_POST_nextcloud_notification_request(request_content)
            self.assertEquals(400, channel.code)
            self.assertEquals(
                json.loads(channel.result["body"])["error"],
                "The Nextcloud url is not recognized.",
            )

    def test_send_nextcloud_notification_in_linked_room_with_wrong_url_query(self):
        request_content = {
            "file_name": "WATCHA-Brochure A4.pdf",
            "directory": "https://test/nextcloud/apps/files/?file=/Partage",
            "link": "https://test/nextcloud/f/307",
            "activity_type": "file_created",
        }

        channel = self._send_POST_nextcloud_notification_request(request_content)
        self.assertEquals(400, channel.code)
        self.assertEquals(
            json.loads(channel.result["body"])["error"],
            "The url doesn't point to a valid directory path.",
        )

    def test_send_nextcloud_notification_in_rooms_linked_with_other_directories(self):
        nextcloud_urls_by_case = {
            "subdirectory_case": "https://test/nextcloud/apps/files/?dir=/parent_directory/Test_NC/sub_directory",
            "sub_subdirectory_case": "https://test/nextcloud/apps/files/?dir=/parent_directory/Test_NC/sub_directory/sub_directory",
            "parent_directory_case": "https://test/nextcloud/apps/files/?dir=/parent_directory",
            "cross_directory_case": "https://test/nextcloud/apps/files/?dir=/parent_directory/cross_directory",
        }
        room_id_by_case = {}
        for url in nextcloud_urls_by_case:
            room_id = self._create_room()
            room_id_by_case[url] = room_id

            self._do_room_mapping_with_nextcloud_folder(
                nextcloud_urls_by_case[url], room_id
            )

        request_content = {
            "file_name": "WATCHA-Brochure A4.pdf",
            "link": "https://test/nextcloud/f/307",
            "activity_type": "file_created",
        }

        # in subdirectory case :
        request_content["directory"] = nextcloud_urls_by_case["subdirectory_case"]
        channel = self._send_POST_nextcloud_notification_request(request_content)
        self.assertEquals(200, channel.code)
        self.assertListEqual(
            json.loads(channel.result["body"])["rooms_id"],
            [
                self.room_id,
                room_id_by_case["parent_directory_case"],
                room_id_by_case["subdirectory_case"],
            ],
        )

        # in sub subdirectory case :
        request_content["directory"] = nextcloud_urls_by_case["sub_subdirectory_case"]
        channel = self._send_POST_nextcloud_notification_request(request_content)
        self.assertEquals(200, channel.code)
        self.assertEquals(
            json.loads(channel.result["body"])["rooms_id"],
            [
                room_id_by_case["subdirectory_case"],
                self.room_id,
                room_id_by_case["parent_directory_case"],
                room_id_by_case["sub_subdirectory_case"],
            ],
        )

        # in parent directory case :
        request_content["directory"] = nextcloud_urls_by_case["parent_directory_case"]
        channel = self._send_POST_nextcloud_notification_request(request_content)
        self.assertEquals(200, channel.code)
        self.assertEquals(
            json.loads(channel.result["body"])["rooms_id"],
            [room_id_by_case["parent_directory_case"]],
        )

        # cross directory case :
        request_content["directory"] = nextcloud_urls_by_case["cross_directory_case"]
        channel = self._send_POST_nextcloud_notification_request(request_content)
        self.assertEquals(200, channel.code)
        self.assertEquals(
            json.loads(channel.result["body"])["rooms_id"],
            [
                room_id_by_case["parent_directory_case"],
                room_id_by_case["cross_directory_case"],
            ],
        )
