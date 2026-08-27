# watcha+
import os
import tempfile

from twisted.test.proto_helpers import MemoryReactor

import synapse.rest.admin
from synapse.rest.client import login
from synapse.server import HomeServer
from synapse.util.clock import Clock

from tests import unittest


class WatchaRetentionConfigTestCase(unittest.HomeserverTestCase):
    servlets = [
        synapse.rest.admin.register_servlets,
        login.register_servlets,
    ]
    url = "/_synapse/admin/v1/watcha_retention_config"

    def prepare(self, reactor: MemoryReactor, clock: Clock, hs: HomeServer) -> None:
        fd, self.config_path = tempfile.mkstemp(suffix=".json")
        os.close(fd)
        os.unlink(self.config_path)
        hs.config.watcha.retention_config_path = self.config_path

        self.admin_user = self.register_user("admin", "pass", admin=True)
        self.admin_user_tok = self.login("admin", "pass")

        self.other_user = self.register_user("user", "pass")
        self.other_user_tok = self.login("user", "pass")

    def tearDown(self) -> None:
        if os.path.exists(self.config_path):
            os.unlink(self.config_path)
        super().tearDown()

    def test_get_returns_defaults_when_unset(self) -> None:
        channel = self.make_request("GET", self.url, access_token=self.admin_user_tok)
        self.assertEqual(200, channel.code, msg=channel.json_body)
        self.assertIsNone(channel.json_body["default_max_lifetime"])
        self.assertTrue(channel.json_body["allow_room_override"])

    def test_requires_admin(self) -> None:
        channel = self.make_request(
            "GET", self.url, access_token=self.other_user_tok
        )
        self.assertEqual(403, channel.code, msg=channel.json_body)

    def test_post_then_get_roundtrip(self) -> None:
        channel = self.make_request(
            "POST",
            self.url,
            {"default_max_lifetime": 86400000, "allow_room_override": False},
            access_token=self.admin_user_tok,
        )
        self.assertEqual(200, channel.code, msg=channel.json_body)
        self.assertEqual(86400000, channel.json_body["default_max_lifetime"])
        self.assertFalse(channel.json_body["allow_room_override"])

        channel = self.make_request("GET", self.url, access_token=self.admin_user_tok)
        self.assertEqual(200, channel.code, msg=channel.json_body)
        self.assertEqual(86400000, channel.json_body["default_max_lifetime"])
        self.assertFalse(channel.json_body["allow_room_override"])

    def test_post_null_default(self) -> None:
        channel = self.make_request(
            "POST",
            self.url,
            {"default_max_lifetime": None, "allow_room_override": True},
            access_token=self.admin_user_tok,
        )
        self.assertEqual(200, channel.code, msg=channel.json_body)
        self.assertIsNone(channel.json_body["default_max_lifetime"])

    def test_post_rejects_invalid_duration(self) -> None:
        channel = self.make_request(
            "POST",
            self.url,
            {"default_max_lifetime": -1},
            access_token=self.admin_user_tok,
        )
        self.assertEqual(400, channel.code, msg=channel.json_body)

    def test_post_rejects_non_bool_override(self) -> None:
        channel = self.make_request(
            "POST",
            self.url,
            {"allow_room_override": "yes"},
            access_token=self.admin_user_tok,
        )
        self.assertEqual(400, channel.code, msg=channel.json_body)
# +watcha
