from tests import unittest
from synapse.util.watcha import compute_registration_token
import base64

class WatchaUtilTestCase(unittest.HomeserverTestCase):
    
    def test_compute_registration_token_without_email_and_password(self):
        token = compute_registration_token("user_test")
        self.assertEquals(base64.b64decode(token).decode('ascii'),'{"user":"user_test"}')

    def test_compute_registration_token_without_password(self):
        token = compute_registration_token("user_test", "test@email.com")
        self.assertEquals(base64.b64decode(token).decode('ascii'),'{"user":"user_test", "email":"test@email.com"}')

    def test_compute_registration_token(self):
        token = compute_registration_token("user_test", "test@email.com", "password")
        self.assertEquals(base64.b64decode(token).decode('ascii'),'{"user":"user_test", "email":"test@email.com", "pw":"password"}')