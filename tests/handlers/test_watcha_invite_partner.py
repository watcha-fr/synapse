import os
import pkg_resources
from mock import Mock

from synapse.rest import admin
from synapse.rest.client.v1 import login, room

from tests import unittest


def simple_async_mock(return_value=None, raises=None):
    # AsyncMock is not available in python3.5, this mimics part of its behaviour
    async def cb(*args, **kwargs):
        if raises:
            raise raises
        return return_value

    return Mock(side_effect=cb)


class InvitePartnerHandlerTestCase(unittest.HomeserverTestCase):

    servlets = [
        admin.register_servlets_for_client_rest_resource,
        login.register_servlets,
        room.register_servlets,
    ]

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
        self.nextcloud_handler = hs.get_nextcloud_handler()

        self.owner = self.register_user("owner", "pass")
        self.owner_tok = self.login("owner", "pass")
        self.get_success(
            self.auth.add_threepid(
                self.owner, "email", "owner@example.com", self.time
            )
        )
        self.other_user = self.register_user("otheruser", "pass")
        self.other_user_access_token = self.login("otheruser", "pass")
        self.get_success(
            self.auth.add_threepid(
                self.other_user, "email", "otheruser@example.com", self.time
            )
        )
        self.room_id = self.helper.create_room_as(self.owner, tok=self.owner_tok)

        self.keycloak_client = self.nextcloud_handler.keycloak_client
        self.nextcloud_client = self.nextcloud_handler.nextcloud_client
        self.keycloak_client.add_user = simple_async_mock()
        self.nextcloud_client.add_user = simple_async_mock()

        self.url = "/rooms/{}/invite".format(self.room_id)

    def test_invite_new_partner(self):
        request, channel = self.make_request(
            "POST",
            self.url,
            {"id_server": "test", "medium": "email", "address": "partner@example.com"},
            self.owner_tok,
        )
        self.render(request)

        self.assertTrue(self.keycloak_client.add_user.called)
        self.assertTrue(self.nextcloud_client.add_user.called)

        self.assertEqual(len(self.email_attempts), 1)

        self.assertEqual(channel.code, 200)
        self.assertEqual(channel.result["body"], b"{}")

    def test_invite_existing_partner(self):
        request, channel = self.make_request(
            "POST",
            self.url,
            {"id_server": "test", "medium": "email", "address": "otheruser@example.com"},
            self.owner_tok,
        )
        self.render(request)

        self.keycloak_client.add_user.not_called()
        self.nextcloud_client.add_user.not_called()

        self.assertEqual(len(self.email_attempts), 0)

        self.assertEqual(channel.code, 200)
        self.assertEqual(channel.result["body"], b"{}")
