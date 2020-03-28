from tests import unittest
from tests.utils import setup_test_homeserver
from synapse.rest.client.v1 import watcha, login, room
from synapse.rest import admin
from synapse.api.errors import SynapseError
import json
import logging

logger = logging.getLogger(__name__)

class BaseHomeserverWithEmailTestCase(unittest.HomeserverTestCase):

    servlets = [
        admin.register_servlets_for_client_rest_resource,
        login.register_servlets,
        watcha.register_servlets,
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

        return self.hs

    def prepare(self, reactor, clock, hs):
        # Admin_user register.
        self.user_id = self.register_user("admin", "pass", True)
        self.user_access_token = self.login("admin", "pass")

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


class WatchaRegisterThreePidServletTestCase(unittest.HomeserverTestCase):

    servlets = [
        admin.register_servlets_for_client_rest_resource,
        login.register_servlets,
        watcha.register_servlets,
        room.register_servlets
    ]

    def prepare(self, reactor, clock, hs):
        self.auth = hs.get_auth_handler()

        # Admin register.
        self.admin_id = self.register_user("user_test", "pass", True)
        self.admin_access_token = self.login("user_test", "pass")

        #User without threepids register :
        self.user_id = self.register_user("admin_test", "pass", False)
        self.auth.set_email(self.user_id, "test@test.com")

    def _do_register_threepids(self):
        request, channel = self.make_request(
            "POST",
            "/_matrix/client/r0/watcha_threepids",
        )
        self.render(request)
        return channel

    def test_register_threepids(self):
        channel = self._do_register_threepids()
        self.assertEqual(channel.code, 200)
        self.assertEqual(channel.result['body'], b'1')

    def test_register_threepids_with_user(self):
        room_id = self.helper.create_room_as(self.admin_id, tok=self.admin_access_token)
        request, channel = self.make_request(
            "POST",
            "/rooms/%s/invite" % (room_id, ),
            content=json.dumps({"id_server":"localhost",
                                  "medium":"email",
                                  "address":"asfsadf@qwf.com"}),
            access_token=self.admin_access_token,
        )
        self.render(request)
        self.assertEqual(channel.code, 200)
        self.assertEqual(channel.result['body'], b'{}')

        channel = self._do_register_threepids()
        self.assertEqual(channel.code, 200)
        self.assertEqual(channel.result['body'], b'1')
        