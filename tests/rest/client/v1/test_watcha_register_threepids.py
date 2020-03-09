from tests import unittest
from tests.utils import setup_test_homeserver
from synapse.rest.client.v1 import watcha, login, room
from synapse.rest import admin
import json

class WatchaRegisterThreePidServletTestCase(unittest.HomeserverTestCase):
    
    servlets = [
        admin.register_servlets_for_client_rest_resource,
        login.register_servlets,
        watcha.register_servlets,
        room.register_servlets
    ]

    def prepare(self, reactor, clock, hs):
        # User register.
        self.user_id = self.register_user("user_test", "pass", True)
        self.user_access_token = self.login("user_test", "pass")

    def _do_register_threepids(self):
        request, channel = self.make_request(
            "POST",
            "/_matrix/client/r0/watcha_threepids",
            access_token=self.user_access_token,
        )
        self.render(request)
        return channel

    def test_register_threepids(self):
        channel = self._do_register_threepids()
        self.assertEqual(channel.code, 200)
        self.assertEqual(channel.result['body'], b'{}')
        
    def test_register_threepids_with_user(self):
        room_id = self.helper.create_room_as(self.user_id, tok=self.user_access_token)
        request, channel = self.make_request(
            "POST",
            "/rooms/%s/invite" % (room_id, ),
            content=json.dumps({"id_server":"localhost",
                                  "medium":"email",
                                  "address":"asfsadf@qwf.com"}),
            access_token=self.user_access_token,
        )
        self.render(request)
        self.assertEqual(channel.code, 200)
        self.assertEqual(channel.result['body'], b'{}')
        
        channel = self._do_register_threepids()
        self.assertEqual(channel.code, 200)
        self.assertEqual(channel.result['body'],
                         b'{"@asfsadf/qwf.com:test":"asfsadf@qwf.com"}')

    def test_register_threepids_without_auth(self):
        self.user_access_token = None
        channel = self._do_register_threepids()
        self.assertEqual(channel.code, 401)