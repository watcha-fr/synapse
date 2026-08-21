# watcha+
import json
import os

from twisted.internet.testing import MemoryReactor
from twisted.web.resource import Resource

from synapse.rest import admin
from synapse.rest.client import login
from synapse.server import HomeServer
from synapse.util.clock import Clock

from tests import unittest
from tests.server import FakeChannel

# Minimal Windows executable header: what a renamed .exe starts with.
PE_CONTENT = b"MZ\x90\x00\x03\x00\x00\x00" + b"\x00" * 64


class WatchaFileTypeFilterTestCase(unittest.HomeserverTestCase):
    """End-to-end checks of the upload filter, through /_matrix/media/v3/upload."""

    servlets = [
        admin.register_servlets,
        login.register_servlets,
    ]

    def make_homeserver(self, reactor: MemoryReactor, clock: Clock) -> HomeServer:
        config = self.default_config()

        self.media_store_path = self.mktemp()
        os.mkdir(self.media_store_path)
        config["media_store_path"] = self.media_store_path

        self.blocked_ext_file = os.path.join(self.media_store_path, "blocked.json")
        self._write_blocked(["exe", "bat", "sh", "jar"])

        config["modules"] = [
            {
                "module": "synapse.modules.file_type_filter.FileTypeFilter",
                "config": {"blocked_ext_file": self.blocked_ext_file},
            }
        ]
        # Same file for the admin endpoint that writes the list.
        config["watcha"] = {"blocked_extensions_path": self.blocked_ext_file}

        return self.setup_test_homeserver(config=config)

    def prepare(self, reactor: MemoryReactor, clock: Clock, hs: HomeServer) -> None:
        self.user = self.register_user("user", "pass")
        self.tok = self.login("user", "pass")

    def create_resource_dict(self) -> dict[str, Resource]:
        resources = super().create_resource_dict()
        resources["/_matrix/media"] = self.hs.get_media_repository_resource()
        return resources

    def _write_blocked(self, extensions: list) -> None:
        with open(self.blocked_ext_file, "w", encoding="utf-8") as f:
            json.dump(extensions, f)

    def upload(
        self,
        content: bytes,
        filename: str | None = None,
        content_type: bytes = b"application/octet-stream",
    ) -> FakeChannel:
        path = "/_matrix/media/v3/upload"
        if filename is not None:
            path += f"?filename={filename}"

        return self.make_request(
            "POST",
            path,
            content=content,
            access_token=self.tok,
            shorthand=False,
            content_type=content_type,
        )

    def test_harmless_file_is_accepted(self) -> None:
        channel = self.upload(b"Bonjour", "notes.txt", b"text/plain")
        self.assertEqual(channel.code, 200, channel.json_body)

    def test_blocked_by_filename(self) -> None:
        channel = self.upload(b"whatever", "payload.exe", b"text/plain")
        self.assertEqual(channel.code, 403, channel.json_body)
        self.assertIn("exe", channel.json_body["error"])

    def test_blocked_when_renamed(self) -> None:
        """An .exe renamed to .txt no longer gets through."""
        channel = self.upload(PE_CONTENT, "notes.txt", b"text/plain")
        self.assertEqual(channel.code, 403, channel.json_body)
        self.assertIn("exe", channel.json_body["error"])

    def test_blocked_without_filename(self) -> None:
        """An executable uploaded with no filename at all no longer gets through."""
        channel = self.upload(PE_CONTENT)
        self.assertEqual(channel.code, 403, channel.json_body)

    def test_blocked_by_declared_content_type(self) -> None:
        channel = self.upload(b"whatever", "notes.txt", b"application/x-msdownload")
        self.assertEqual(channel.code, 403, channel.json_body)

    def test_blocked_shell_script_without_extension(self) -> None:
        channel = self.upload(b"#!/bin/sh\nrm -rf /\n", "runme", b"text/plain")
        self.assertEqual(channel.code, 403, channel.json_body)

    def test_document_with_zip_container_is_accepted(self) -> None:
        """A .docx is a ZIP, like a .jar: it must not be rejected for that."""
        channel = self.upload(
            b"PK\x03\x04rest of a docx",
            "rapport.docx",
            b"application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )
        self.assertEqual(channel.code, 200, channel.json_body)

    def test_empty_list_accepts_everything(self) -> None:
        self._write_blocked([])
        channel = self.upload(PE_CONTENT, "payload.exe", b"text/plain")
        self.assertEqual(channel.code, 200, channel.json_body)

    def test_list_is_reloaded_without_restart(self) -> None:
        channel = self.upload(b"Bonjour", "notes.md", b"text/plain")
        self.assertEqual(channel.code, 200, channel.json_body)

        self._write_blocked(["md"])
        channel = self.upload(b"Bonjour", "notes.md", b"text/plain")
        self.assertEqual(channel.code, 403, channel.json_body)

    def test_admin_endpoint_roundtrip(self) -> None:
        """The admin endpoint normalises what it stores and reads it back."""
        admin_user = self.register_user("admin", "pass", admin=True)
        admin_tok = self.login("admin", "pass")

        channel = self.make_request(
            "POST",
            "/_synapse/admin/v1/watcha_file_type_filter",
            {"blocked_extensions": [".EXE", "Bat", " sh "]},
            access_token=admin_tok,
        )
        self.assertEqual(channel.code, 200, channel.json_body)
        self.assertEqual(channel.json_body["blocked_extensions"], ["bat", "exe", "sh"])

        channel = self.make_request(
            "GET",
            "/_synapse/admin/v1/watcha_file_type_filter",
            access_token=admin_tok,
        )
        self.assertEqual(channel.code, 200, channel.json_body)
        self.assertEqual(channel.json_body["blocked_extensions"], ["bat", "exe", "sh"])

        self.assertIsNotNone(admin_user)

    def test_admin_endpoint_requires_admin(self) -> None:
        channel = self.make_request(
            "GET",
            "/_synapse/admin/v1/watcha_file_type_filter",
            access_token=self.tok,
        )
        self.assertEqual(channel.code, 403, channel.json_body)


# +watcha
