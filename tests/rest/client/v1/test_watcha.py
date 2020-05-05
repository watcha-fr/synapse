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

class WatchaUpdateUserRoleResterServletTestCase(BaseHomeserverWithEmailTestCase):

    def prepare(self, reactor, clock, hs):
        #Register admin user :
        self.admin_id = self.register_user("admin_user", "pass", True)
        self.admin_access_token = self.login("admin_user", "pass")

        #Register no admin user
        self.non_admin_id = self.register_user("no_admin_user", "pass", False)
        self.non_admin_user_token = self.login("no_admin_user", "pass")

    def _do_update_user_role(self, target_user_id, access_token, role):
        request, channel = self.make_request(
            "PUT",
            "/_matrix/client/r0/watcha_update_user_role/%s" % target_user_id,
            content=json.dumps({"role": role}),
            access_token=access_token,
        )
        self.render(request)
        return channel

    def test_do_all_update_user_role(self):
        roles = ["partner", "member", "admin"]

        for role in roles:
            channel = self._do_update_user_role(self.non_admin_id, self.admin_access_token, role)

            self.assertEqual(channel.code, 200)
            self.assertEqual(json.loads(channel.result["body"]), {"new_role": role})

    def test_do_update_user_role_on_ourself(self):
        role = "member"
        channel = self._do_update_user_role(self.admin_id, self.admin_access_token, role)

        self.assertEqual(channel.code, 200)
        self.assertEqual(json.loads(channel.result["body"]), {"new_role": role})

    def test_do_update_user_role_with_same_role(self):
        role = "member"
        channel = self._do_update_user_role(self.non_admin_id, self.admin_access_token, role)

        self.assertRaises(SyntaxError)
        self.assertEqual(channel.code, 400)
        self.assertEqual(
            json.loads(channel.result["body"])["error"], "This user has already the %s status" % role
        )

    def test_do_update_user_role_without_admin_right(self):
        channel = self._do_update_user_role(self.admin_id, self.non_admin_user_token, "admin")

        self.assertRaises(SyntaxError)
        self.assertEqual(channel.code, 403)
        self.assertEqual(
            json.loads(channel.result["body"])["error"], "You are not a server admin"
        )

    def test_do_update_user_role_with_wrong_user_id(self):
        channel = self._do_update_user_role("@user_test:test", self.admin_access_token, "admin")

        self.assertRaises(SyntaxError)
        self.assertEqual(channel.code, 400)
        self.assertEqual(
            json.loads(channel.result["body"])["error"], "The target user is not register in this homeserver."
        )

    def test_do_update_user_role_with_wrong_role(self):
        role = "master"
        channel = self._do_update_user_role(self.non_admin_id, self.admin_access_token, role)

        self.assertRaises(SyntaxError)
        self.assertEqual(channel.code, 400)
        self.assertEqual(
            json.loads(channel.result["body"])["error"], "%s is not a defined role." % role
        )
