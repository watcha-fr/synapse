from tests import unittest
from synapse.util.watcha import compute_registration_token
import base64

class WatchaUtilTestCase(unittest.HomeserverTestCase):
    
    def test_compute_registration_token_without_email_and_password(self):
        user = "user_test"

        token = compute_registration_token(user)
        self.assertEquals(base64.b64decode(token).decode('ascii'),'{"user":"user_test"}')

    def test_compute_registration_token_without_password(self):
        user = "user_test"
        email = "test@email.com"

        token = compute_registration_token(user, email)
        self.assertEquals(base64.b64decode(token).decode('ascii'),'{"user":"user_test", "email":"test@email.com"}')

    def test_compute_registration_token(self):
        user = "user_test"
        password = "password"
        email = "test@email.com"

        token = compute_registration_token(user, email, password)
        self.assertEquals(base64.b64decode(token).decode('ascii'),'{"user":"user_test", "email":"test@email.com", "pw":"password"}')