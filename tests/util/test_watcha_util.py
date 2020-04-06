from tests import unittest
from synapse.util.watcha import compute_registration_token, create_display_inviter_name
from synapse.rest import admin
from synapse.rest.client.v1 import login
from synapse.types import create_requester
import base64

class WatchaUtilTestCase(unittest.HomeserverTestCase):
    
    servlets = [
        admin.register_servlets_for_client_rest_resource,
        login.register_servlets,
    ]

    def make_homeserver(self, reactor, clock):
        self.hs = self.setup_test_homeserver()
        self.auth_handler = self.hs.get_auth_handler()
        self.profile_handler = self.hs.get_profile_handler()
        self.time = self.hs.get_clock().time_msec() 
        return self.hs

    def prepare(self, reactor, clock, hs):
        self.owner = self.register_user("owner", "pass", True)
        self.owner_access_token = self.login("owner", "pass")
        self.requester = create_requester(self.owner)
        self.inviter_display_name = self.get_success(self.profile_handler.get_displayname(self.requester.user))

    def test_compute_registration_token_without_email_and_password(self):
        token = compute_registration_token("user_test")
        self.assertEquals(base64.b64decode(token).decode(),'{"user":"user_test"}')

    def test_compute_registration_token_without_password(self):
        token = compute_registration_token("user_test", "test@email.com")
        self.assertEquals(base64.b64decode(token).decode(),'{"user":"user_test", "email":"test@email.com"}')

    def test_compute_registration_token(self):
        token = compute_registration_token("user_test", "test@email.com", "password")
        self.assertEquals(base64.b64decode(token).decode(),'{"user":"user_test", "email":"test@email.com", "pw":"password"}')

    def test_create_display_inviter_name_with_email(self):
        self.auth_handler.add_threepid(self.owner, "email", "example@email.com", self.time)
        inviter_name = self.get_success(create_display_inviter_name(self.hs, self.requester.user))
        self.assertEquals(inviter_name, self.inviter_display_name + " (example@email.com)")

    def test_create_display_inviter_name_without_email(self):
        inviter_name = self.get_success(create_display_inviter_name(self.hs, self.requester.user))
        self.assertEquals(inviter_name, self.inviter_display_name)
