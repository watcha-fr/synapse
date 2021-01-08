import os
import pkg_resources
from mock import Mock

from synapse.rest import admin
from synapse.rest.client.v1 import watcha, login, room
from tests import unittest
from tests.utils import setup_test_homeserver


def simple_async_mock(return_value=None, raises=None):
    # AsyncMock is not available in python3.5, this mimics part of its behaviour
    async def cb(*args, **kwargs):
        if raises:
            raise raises
        return return_value

    return Mock(side_effect=cb)


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
        self.email_attempts = []

        async def sendmail(smtphost, from_addr, to_addrs, msg, **kwargs):
            self.email_attempts.append(msg)
            return

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

        hs = self.setup_test_homeserver(config=config, sendmail=sendmail)
        return hs

    def prepare(self, reactor, clock, hs):
        self.time = self.hs.get_clock().time_msec()

        self.auth = hs.get_auth_handler()

        self.owner = self.register_user("owner", "pass", admin=True)
        self.owner_tok = self.login("owner", "pass")
        self.get_success(
            self.auth.add_threepid(self.owner, "email", "owner@example.com", self.time)
        )
        self.room_id = self.helper.create_room_as(self.owner, tok=self.owner_tok)

        self.keycloak_client = hs.get_keycloak_client()
        self.nextcloud_client = hs.get_nextcloud_client()
        self.keycloak_client.add_user = simple_async_mock()
        self.keycloak_client.update_user = simple_async_mock()
        self.keycloak_client.get_user = simple_async_mock(return_value={"id": "user1"})
        self.nextcloud_client.add_user = simple_async_mock()

    def test_register_user(self):
        request, channel = self.make_request(
            "POST",
            self.url,
            {
                "email": "user1@example.com",
                "admin": False,
                "password": "",
            },
            self.owner_tok,
        )
        self.render(request)

        self.assertTrue(self.keycloak_client.add_user.called)
        self.assertTrue(self.keycloak_client.update_user.called)
        self.assertTrue(self.keycloak_client.get_user.called)
        self.assertTrue(self.nextcloud_client.add_user.called)
        self.assertEqual(channel.code, 200)

    def test_register_user_with_password(self):
        request, channel = self.make_request(
            "POST",
            self.url,
            {
                "email": "user1@example.com",
                "admin": False,
                "password": "pass",
            },
            self.owner_tok,
        )
        self.render(request)

        self.assertTrue(self.keycloak_client.add_user.called)
        self.assertTrue(self.keycloak_client.update_user.called)
        self.assertTrue(self.keycloak_client.get_user.called)
        self.assertTrue(self.nextcloud_client.add_user.called)
        self.assertEqual(channel.code, 200)

    def test_register_user_with_empty_email(self):
        request, channel = self.make_request(
            "POST",
            self.url,
            {
                "email": "",
                "admin": False,
                "password": "",
            },
            self.owner_tok,
        )
        self.render(request)

        self.keycloak_client.add_user.not_called()
        self.keycloak_client.update_user.not_called()
        self.keycloak_client.get_user.not_called()
        self.nextcloud_client.add_user.not_called()

        self.assertEqual(channel.code, 400)
        self.assertEqual(
            channel.result["body"],
            b'{"errcode":"M_UNKNOWN","error":"Email address cannot be empty"}',
        )

    def test_register_user_with_same_email_adress(self):
        request, channel = self.make_request(
            "POST",
            self.url,
            {
                "email": "owner@example.com",
                "admin": False,
                "password": "",
            },
            self.owner_tok,
        )
        self.render(request)

        self.keycloak_client.add_user.not_called()
        self.keycloak_client.update_user.not_called()
        self.keycloak_client.get_user.not_called()
        self.nextcloud_client.add_user.not_called()

        self.assertEqual(channel.code, 400)
        self.assertEqual(
            channel.result["body"],
            b'{"errcode":"M_UNKNOWN","error":"A user with this email address already exists. Cannot create a new one."}',
        )
