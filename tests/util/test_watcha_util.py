from tests import unittest
from synapse.util.watcha import compute_registration_token
from synapse.rest import admin
from synapse.rest.client.v1 import watcha, login
import json, base64, ast

class WatchaUtilTestCase(unittest.HomeserverTestCase):
    
    servlets = [
        admin.register_servlets_for_client_rest_resource,
        login.register_servlets,
        watcha.register_servlets,
    ]

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

    def test_register_and_send_token(self):
        request_content = {"user":"user_test", "full_name":"test", "email":"test@test.com", "admin":False}
        channel = self._do_register_user(request_content)
        token = ast.literal_eval(channel.result['body'].decode('utf-8'))['token']
        password = ast.literal_eval(channel.result['body'].decode('utf-8'))['password']
        self.assertEquals(base64.b64decode(token).decode('ascii'),'{"user":"@user_test:test", "email":"test@test.com", "pw":"' + password + '"}')

    def test_compute_registration_token(self):
        user = "user_test"
        password = "password"
        email = "test@email.com"

        token = compute_registration_token(user, email, password)
        self.assertEquals(base64.b64decode(token).decode('ascii'),'{"user":"user_test", "email":"test@email.com", "pw":"password"}')