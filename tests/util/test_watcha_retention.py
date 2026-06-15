# watcha+
import json
import os
import tempfile

from synapse.util.watcha_retention import (
    DEFAULT_ALLOW_ROOM_OVERRIDE,
    load_retention_config,
    save_retention_config,
)

from tests import unittest


class WatchaRetentionConfigTestCase(unittest.TestCase):
    def setUp(self) -> None:
        fd, self.path = tempfile.mkstemp(suffix=".json")
        os.close(fd)
        os.unlink(self.path)  # start with no file

    def tearDown(self) -> None:
        if os.path.exists(self.path):
            os.unlink(self.path)

    def test_defaults_when_no_file(self) -> None:
        config = load_retention_config(self.path)
        self.assertIsNone(config["default_max_lifetime"])
        self.assertEqual(config["allow_room_override"], DEFAULT_ALLOW_ROOM_OVERRIDE)

    def test_defaults_when_path_is_none(self) -> None:
        config = load_retention_config(None)
        self.assertIsNone(config["default_max_lifetime"])
        self.assertTrue(config["allow_room_override"])

    def test_save_then_load_roundtrip(self) -> None:
        save_retention_config(self.path, 86400000, False)
        config = load_retention_config(self.path)
        self.assertEqual(config["default_max_lifetime"], 86400000)
        self.assertFalse(config["allow_room_override"])

    def test_save_null_default(self) -> None:
        save_retention_config(self.path, None, True)
        config = load_retention_config(self.path)
        self.assertIsNone(config["default_max_lifetime"])
        self.assertTrue(config["allow_room_override"])

    def test_malformed_file_yields_defaults(self) -> None:
        with open(self.path, "w", encoding="utf-8") as f:
            f.write("{not valid json")
        config = load_retention_config(self.path)
        self.assertIsNone(config["default_max_lifetime"])
        self.assertTrue(config["allow_room_override"])

    def test_invalid_values_ignored(self) -> None:
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(
                {"default_max_lifetime": -5, "allow_room_override": "yes"}, f
            )
        config = load_retention_config(self.path)
        # negative duration and non-bool flag fall back to defaults
        self.assertIsNone(config["default_max_lifetime"])
        self.assertTrue(config["allow_room_override"])

    def test_bool_is_not_accepted_as_duration(self) -> None:
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump({"default_max_lifetime": True}, f)
        config = load_retention_config(self.path)
        self.assertIsNone(config["default_max_lifetime"])

    def test_cache_invalidated_on_rewrite(self) -> None:
        save_retention_config(self.path, 1000, True)
        self.assertEqual(load_retention_config(self.path)["default_max_lifetime"], 1000)
        save_retention_config(self.path, 2000, False)
        config = load_retention_config(self.path)
        self.assertEqual(config["default_max_lifetime"], 2000)
        self.assertFalse(config["allow_room_override"])
# +watcha
