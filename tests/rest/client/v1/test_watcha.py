import json
import logging

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
        request, channel = self.make_request(
            "POST",
            "/rooms/%s/invite" % room_id,
            content=json.dumps({"user_id": user_id}),
            access_token=self.user_access_token,
        )

        self.render(request)


class WatchaRegisterRestServletTestCase(BaseHomeserverWithEmailTestCase):

    def test_register_user(self):
        request_content = {"user":"user_test", "full_name":"test", "email":"test@test.com", "admin":False}
        with self.assertLogs('synapse.util.watcha', level='INFO') as cm:
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
        request_content = {"user":"user_test", "full_name":"test", "email":"test+test@test.com", "admin":False}
        with self.assertLogs('synapse.util.watcha', level='INFO') as cm:
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
                    "status": "invited",
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
        room_id = self._create_room()
        self._invite_member_in_room(room_id, self.user_id)

        request, channel = self.make_request(
            "GET", "watcha_admin_stats", access_token=self.user_access_token
        )
        self.render(request)

        self.assertEquals(
            json.loads(channel.result["body"])["rooms"],
            {
                "direct_active_rooms_count": 0,
                "direct_rooms_count": 0,
                "non_direct_active_rooms_count": 0,
                "non_direct_rooms_count": 1,
            },
        )
        self.assertEquals(200, channel.code)

    def test_get_watcha_admin_stats_room_list(self):
        rooms_id = []
        for i in range(3):
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
                    "type": "Room",
                },
            )
        self.assertEquals(200, channel.code)
