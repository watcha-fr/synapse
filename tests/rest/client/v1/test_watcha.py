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
        self.account_activity_handler = self.hs.get_account_validity_handler()

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

    def _do_update_email(self, user_id, email):
        #Admin send the request with access_token :
        request, channel = self.make_request(
            "PUT",
            "/_matrix/client/r0/watcha_update_email/%s" % user_id,
            content=json.dumps({"new_email": email}),
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

class WatchaUpdateMailRestServletTestCase(BaseHomeserverWithEmailTestCase):
    def test_update_email(self):
        user_id = "@user_test:test"
        self._do_register_user(
            {
                "user": "user_test",
                "full_name": "test",
                "email": "example@example.com",
                "admin": False,
            }
        )

        self._do_update_email(user_id, "example2@example.com")
        self.assertEqual(
            self.get_success(
                self.account_activity_handler.get_email_address_for_user(user_id)
            ),
            "example2@example.com",
        )

    def test_update_email_when_a_email_is_not_defined(self):
        self.register_user("user_test", "pass")

        with self.assertLogs("synapse.rest.client.v1.watcha", level="ERROR") as cm:
            channel = self._do_update_email("@user_test:test", "example@example.com")

        self.assertEqual(channel.code, 403)
        self.assertIn(
            "ERROR:synapse.rest.client.v1.watcha:No email are defined for this user.",
            cm.output[0],
        )

    def test_update_email_with_no_new_email_parameter(self):
        channel = self._do_update_email("@user_test:test", None)
        self.assertRaises(SynapseError)
        self.assertEqual(channel.code, 400)
        self.assertEqual(
            json.loads(channel.result["body"])["error"], "Missing 'new_email' arg"
        )

    def test_update_email_with_wrong_target_user_id(self):
        channel = self._do_update_email("@user_test:test", "example@example.com")
        self.assertRaises(SynapseError)
        self.assertEqual(channel.code, 400)
        self.assertEqual(
            json.loads(channel.result["body"])["error"],
            "The target user is not register in this homeserver.",
        )
