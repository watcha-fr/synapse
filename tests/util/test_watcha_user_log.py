import json
import os
import tempfile

from synapse.util.watcha_user_log import UserAuditAction, append_user_audit_log

from tests import unittest


class WatchaUserLogTestCase(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.path = os.path.join(self.dir, "watcha_user_audit_log.json")

    def _read(self):
        with open(self.path, "r", encoding="utf-8") as f:
            return json.load(f)

    def test_creates_file_and_entry(self):
        append_user_audit_log(
            self.path,
            user_id="@alice:test",
            display_name="alice@test.com",
            action=UserAuditAction.CREATE,
        )

        entries = self._read()
        self.assertEqual(len(entries), 1)
        entry = entries[0]
        self.assertEqual(entry["id"], "log-1")
        self.assertEqual(entry["user_id"], "@alice:test")
        self.assertEqual(entry["display_name"], "alice@test.com")
        self.assertEqual(entry["action"], "CREATE")
        self.assertIsNone(entry["avatar_src"])
        self.assertIn("timestamp", entry)

    def test_appends_with_incrementing_ids(self):
        append_user_audit_log(
            self.path, "@alice:test", "alice", UserAuditAction.CREATE
        )
        append_user_audit_log(
            self.path, "@alice:test", "alice", UserAuditAction.DEACTIVATE
        )
        append_user_audit_log(
            self.path, "@alice:test", "alice", UserAuditAction.REACTIVATE
        )
        append_user_audit_log(
            self.path, "@alice:test", "alice", UserAuditAction.DELETE
        )

        entries = self._read()
        self.assertEqual([e["id"] for e in entries], ["log-1", "log-2", "log-3", "log-4"])
        self.assertEqual(
            [e["action"] for e in entries],
            ["CREATE", "DEACTIVATE", "REACTIVATE", "DELETE"],
        )

    def test_none_path_is_noop(self):
        # Should not raise.
        append_user_audit_log(None, "@alice:test", "alice", UserAuditAction.CREATE)

    def test_corrupted_file_is_recovered(self):
        with open(self.path, "w", encoding="utf-8") as f:
            f.write("not valid json {")

        append_user_audit_log(
            self.path, "@alice:test", "alice", UserAuditAction.CREATE
        )

        entries = self._read()
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["id"], "log-1")
