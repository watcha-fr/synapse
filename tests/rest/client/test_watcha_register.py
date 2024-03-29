import os
from unittest.mock import AsyncMock

import pkg_resources

from synapse.rest import admin
from synapse.rest.client import login, room, watcha
from synapse.types import UserID

from tests import unittest
from tests.utils import mock_getRawHeaders


class RegisterTestCase(unittest.HomeserverTestCase):
    servlets = [
        admin.register_servlets_for_client_rest_resource,
        login.register_servlets,
        watcha.register_servlets,
        room.register_servlets,
    ]

    url = "/_matrix/client/r0/watcha_register"

    def make_homeserver(self, reactor, clock):
        config = self.default_config()

        # Email config.
        config["email"] = {
            "enable_notifs": False,
            "template_dir": os.path.abspath(
                pkg_resources.resource_filename("synapse", "res/templates")
            ),
            "smtp_host": "127.0.0.1",
            "smtp_port": 20,
            "require_transport_security": False,
            "smtp_user": None,
            "smtp_pass": None,
            "notif_from": "test@example.com",
        }
        config["public_baseurl"] = "https://example.com"

        hs = self.setup_test_homeserver(config=config)

        async def sendmail(
            reactor, smtphost, smtpport, from_addr, to_addrs, msg, **kwargs
        ):
            self.email_attempts.append(msg)

        self.email_attempts = []
        hs.get_send_email_handler()._sendmail = sendmail

        return hs

    def prepare(self, reactor, clock, hs):
        self.time = self.hs.get_clock().time_msec()

        self.auth = hs.get_auth_handler()
        self.profile = hs.get_profile_handler()

        self.owner = self.register_user("owner", "pass", admin=True)
        self.owner_tok = self.login("owner", "pass")
        self.get_success(
            self.auth.add_threepid(self.owner, "email", "owner@example.com", self.time)
        )

        self.room_id = self.helper.create_room_as(self.owner, tok=self.owner_tok)

        self.keycloak_client = hs.get_keycloak_client()
        self.nextcloud_client = hs.get_nextcloud_client()

        response = AsyncMock()
        response.headers.getRawHeaders = mock_getRawHeaders(
            {
                "location": [
                    "https://keycloak_url/auth/admin/realms/realm_name/users/c76bff5e-dd38-4100-bad2-ed2aa4dc9c6f"
                ]
            }
        )
        self.keycloak_client.add_user = AsyncMock(return_value=response)
        self.nextcloud_client.add_user = AsyncMock()

    def test_register_user(self):
        channel = self.make_request(
            "POST",
            self.url,
            {"email": "user1@example.com", "admin": False, "password": ""},
            self.owner_tok,
        )
        user_id = UserID.from_string(channel.json_body["user_id"])
        nextcloud_username = user_id.localpart
        displayname = self.get_success(self.profile.get_displayname(user_id))

        self.assertEqual(displayname, "user1@example.com")
        self.assertTrue(self.keycloak_client.add_user.called)
        self.nextcloud_client.add_user.assert_called_with(nextcloud_username, "")
        self.assertEqual(channel.code, 200)

    def test_register_user_with_password(self):
        channel = self.make_request(
            "POST",
            self.url,
            {"email": "user1@example.com", "admin": False, "password": "pass"},
            self.owner_tok,
        )

        self.assertTrue(self.keycloak_client.add_user.called)
        self.assertTrue(self.nextcloud_client.add_user.called)
        self.assertEqual(channel.code, 200)

    def test_register_user_with_empty_email(self):
        channel = self.make_request(
            "POST",
            self.url,
            {"email": "", "admin": False, "password": ""},
            self.owner_tok,
        )

        self.keycloak_client.add_user.assert_not_called()
        self.nextcloud_client.add_user.assert_not_called()

        self.assertEqual(channel.code, 400)

    def test_register_user_with_displayname(self):
        channel = self.make_request(
            "POST",
            self.url,
            {
                "email": "user1@example.com",
                "admin": False,
                "password": "",
                "displayname": "user1",
            },
            self.owner_tok,
        )
        user_id = UserID.from_string(channel.json_body["user_id"])
        nextcloud_username = user_id.localpart
        displayname = self.get_success(self.profile.get_displayname(user_id))

        self.assertEqual(displayname, "user1")
        self.assertTrue(self.keycloak_client.add_user.called)
        self.nextcloud_client.add_user.assert_called_with(
            nextcloud_username, displayname
        )
        self.assertEqual(channel.code, 200)

    # watcha+
    skip_reason = (
        "[watcha] to be adapted to conditional functionalities "
        "(managed_idp, nextcloud_integration)"
    )
    test_register_user.skip = skip_reason
    test_register_user_with_displayname.skip = skip_reason
    test_register_user_with_password.skip = skip_reason
    # +watcha
