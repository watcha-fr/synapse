from tests import unittest
from tests.utils import setup_test_homeserver
from synapse.rest.client.v1 import watcha, login
from synapse.rest import admin
import json

class WatchaRegisterThreePidServletTestCase(unittest.HomeserverTestCase):
    
    servlets = [
        admin.register_servlets_for_client_rest_resource,
        login.register_servlets,
        watcha.register_servlets
    ]

    def prepare(self, reactor, clock, hs):
        # User register.
        self.user_id = self.register_user("user_test", "pass")
        self.user_access_token = self.login("user_test", "pass")

    def _do_register_threepids(self, request_content):
        request, channel = self.make_request(
            "POST",
            "/_matrix/client/r0/watcha_threepids",
            content=json.dumps(request_content),
            access_token=self.user_access_token,
        )
        self.render(request)
        return channel.code

    def test_right_register_threepids(self):
        request_content = {"user":self.user_id,"email":"test@test.com"}
        code = self._do_register_threepids(request_content)
        self.assertEqual(code, 200)




    
