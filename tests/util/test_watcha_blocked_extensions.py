# watcha+
import json
import os
import tempfile

from synapse.util.watcha_blocked_extensions import (
    blocked_extension_for_upload,
    extensions_for_content,
    extensions_for_media_type,
    extensions_for_name,
    load_blocked_extensions,
    save_blocked_extensions,
)

from tests import unittest

# A minimal Windows executable header, and an ELF one.
PE_HEADER = b"MZ\x90\x00\x03\x00\x00\x00" + b"\x00" * 32
ELF_HEADER = b"\x7fELF\x02\x01\x01\x00" + b"\x00" * 32


class BlockedExtensionsFileTestCase(unittest.TestCase):
    def setUp(self) -> None:
        fd, self.path = tempfile.mkstemp(suffix=".json")
        os.close(fd)
        os.unlink(self.path)  # start with no file

    def tearDown(self) -> None:
        if os.path.exists(self.path):
            os.unlink(self.path)

    def _write(self, content: str) -> None:
        with open(self.path, "w", encoding="utf-8") as f:
            f.write(content)

    def test_empty_when_no_file(self) -> None:
        self.assertEqual(load_blocked_extensions(self.path), set())

    def test_save_then_load_roundtrip(self) -> None:
        saved = save_blocked_extensions(["EXE", ".bat", " sh "], self.path)
        self.assertEqual(saved, ["bat", "exe", "sh"])
        self.assertEqual(load_blocked_extensions(self.path), {"exe", "bat", "sh"})

    def test_normalises_hand_written_file(self) -> None:
        self._write(json.dumps([".EXE", "Bat", "", "  ", "sh"]))
        self.assertEqual(load_blocked_extensions(self.path), {"exe", "bat", "sh"})

    def test_malformed_file_is_ignored(self) -> None:
        self._write("{ not json")
        self.assertEqual(load_blocked_extensions(self.path), set())

    def test_non_list_file_is_ignored(self) -> None:
        self._write(json.dumps({"blocked_extensions": ["exe"]}))
        self.assertEqual(load_blocked_extensions(self.path), set())

    def test_non_string_entries_are_dropped(self) -> None:
        self._write(json.dumps(["exe", 42, None, "sh"]))
        self.assertEqual(load_blocked_extensions(self.path), {"exe", "sh"})

    def test_cache_is_invalidated_on_write(self) -> None:
        save_blocked_extensions(["exe"], self.path)
        self.assertEqual(load_blocked_extensions(self.path), {"exe"})

        save_blocked_extensions(["sh"], self.path)
        self.assertEqual(load_blocked_extensions(self.path), {"sh"})


class ExtensionsForNameTestCase(unittest.TestCase):
    def test_no_name(self) -> None:
        self.assertEqual(extensions_for_name(None), set())
        self.assertEqual(extensions_for_name(""), set())

    def test_no_extension(self) -> None:
        self.assertEqual(extensions_for_name("README"), set())

    def test_simple_extension(self) -> None:
        self.assertEqual(extensions_for_name("payload.EXE"), {"exe"})

    def test_compound_extension(self) -> None:
        self.assertEqual(extensions_for_name("archive.tar.gz"), {"gz", "tar.gz"})

    def test_double_extension(self) -> None:
        # The trailing extension is what an OS looks at; the hidden `.exe` is
        # caught by content sniffing instead.
        self.assertEqual(extensions_for_name("payload.exe.txt"), {"txt", "exe.txt"})

    def test_trailing_dots_and_spaces_are_stripped(self) -> None:
        self.assertEqual(extensions_for_name("payload.exe. "), {"exe"})

    def test_path_is_reduced_to_basename(self) -> None:
        self.assertEqual(extensions_for_name("C:\\dir.exe\\notes.txt"), {"txt"})
        self.assertEqual(extensions_for_name("/tmp/dir.exe/notes.txt"), {"txt"})


class ExtensionsForMediaTypeTestCase(unittest.TestCase):
    def test_generic_types_say_nothing(self) -> None:
        for media_type in ("application/octet-stream", "", None, "*/*"):
            self.assertEqual(extensions_for_media_type(media_type), set())

    def test_text_plain_is_not_mapped_to_bat(self) -> None:
        # The system mime database maps text/plain to .bat on some platforms;
        # we must not, or every text upload would be rejected.
        self.assertEqual(extensions_for_media_type("text/plain"), set())

    def test_executable_type(self) -> None:
        self.assertEqual(
            extensions_for_media_type("application/x-msdownload"), {"exe", "dll"}
        )

    def test_parameters_are_ignored(self) -> None:
        self.assertEqual(
            extensions_for_media_type("application/x-sh; charset=utf-8"), {"sh"}
        )


class ExtensionsForContentTestCase(unittest.TestCase):
    def test_no_header(self) -> None:
        self.assertEqual(extensions_for_content(None), set())
        self.assertEqual(extensions_for_content(b""), set())

    def test_windows_executable(self) -> None:
        self.assertIn("exe", extensions_for_content(PE_HEADER))

    def test_elf_binary(self) -> None:
        self.assertIn("elf", extensions_for_content(ELF_HEADER))

    def test_shebang_shell(self) -> None:
        self.assertIn("sh", extensions_for_content(b"#!/bin/bash\necho hello\n"))

    def test_shebang_python(self) -> None:
        self.assertEqual(
            extensions_for_content(b"#!/usr/bin/env python3\nprint(1)\n"), {"py"}
        )

    def test_shebang_unknown_interpreter(self) -> None:
        self.assertEqual(extensions_for_content(b"#!/opt/weird\n"), {"sh"})

    def test_shebang_behind_utf8_bom(self) -> None:
        # A script saved by a Windows editor starts with a BOM.
        self.assertEqual(
            extensions_for_content(b"\xef\xbb\xbf#!/bin/bash\necho x\n"),
            {"sh", "bash"},
        )
        self.assertEqual(
            extensions_for_content(b"\xef\xbb\xbf#!/usr/bin/env python3\n"), {"py"}
        )

    def test_php_opening_tag(self) -> None:
        self.assertEqual(extensions_for_content(b"<?php\necho 1;\n"), {"php"})
        self.assertEqual(extensions_for_content(b"\xef\xbb\xbf<?PHP\n"), {"php"})

    def test_batch_file(self) -> None:
        self.assertEqual(
            extensions_for_content(b"@echo off\r\ndel target\r\n"), {"bat", "cmd"}
        )

    def test_document_quoting_php_is_not_matched(self) -> None:
        # The signature is only looked for at the very beginning: a text file
        # showing PHP code further down stays acceptable.
        self.assertEqual(
            extensions_for_content(b"Exemple de code :\n<?php echo 1; ?>\n"), set()
        )

    def test_xml_is_not_php(self) -> None:
        self.assertEqual(extensions_for_content(b'<?xml version="1.0"?>\n'), set())

    def test_script_without_shebang_is_not_detectable(self) -> None:
        # Known limit: a shell or python script carrying no shebang is a plain
        # text file, and nothing in its content gives it away.
        self.assertEqual(extensions_for_content(b"echo coucou\n"), set())
        self.assertEqual(extensions_for_content(b"import os\nprint(1)\n"), set())

    def test_plain_text_is_not_executable(self) -> None:
        self.assertEqual(
            extensions_for_content(b"Bonjour, ceci est un texte.\n"), set()
        )

    def test_zip_container_is_not_guessed(self) -> None:
        # A .docx is a ZIP too: guessing "jar"/"apk" here would reject
        # legitimate documents.
        self.assertEqual(extensions_for_content(b"PK\x03\x04rest of a docx"), set())


class BlockedExtensionForUploadTestCase(unittest.TestCase):
    BLOCKED = {"exe", "bat", "sh", "jar"}

    def test_empty_list_never_blocks(self) -> None:
        self.assertIsNone(
            blocked_extension_for_upload(set(), "payload.exe", None, PE_HEADER)
        )

    def test_blocked_by_name(self) -> None:
        self.assertEqual(
            blocked_extension_for_upload(self.BLOCKED, "payload.exe", "text/plain"),
            "exe",
        )

    def test_blocked_by_declared_media_type(self) -> None:
        self.assertEqual(
            blocked_extension_for_upload(
                self.BLOCKED, "notes.txt", "application/x-msdownload"
            ),
            "exe",
        )

    def test_blocked_by_content_when_renamed(self) -> None:
        # The regression this fix is about: .exe renamed to .txt.
        self.assertEqual(
            blocked_extension_for_upload(
                self.BLOCKED, "notes.txt", "text/plain", PE_HEADER
            ),
            "exe",
        )

    def test_blocked_by_content_when_no_name(self) -> None:
        self.assertEqual(
            blocked_extension_for_upload(
                self.BLOCKED, None, "application/octet-stream", PE_HEADER
            ),
            "exe",
        )

    def test_shell_script_without_extension(self) -> None:
        self.assertEqual(
            blocked_extension_for_upload(
                self.BLOCKED, "runme", "text/plain", b"#!/bin/sh\nrm -rf /\n"
            ),
            "sh",
        )

    def test_legitimate_document_passes(self) -> None:
        self.assertIsNone(
            blocked_extension_for_upload(
                self.BLOCKED,
                "rapport.pdf",
                "application/pdf",
                b"%PDF-1.7\n%%EOF\n",
            )
        )

    def test_legitimate_text_passes(self) -> None:
        self.assertIsNone(
            blocked_extension_for_upload(
                self.BLOCKED, "notes.txt", "text/plain", b"Bonjour\n"
            )
        )

    def test_docx_passes(self) -> None:
        self.assertIsNone(
            blocked_extension_for_upload(
                self.BLOCKED,
                "rapport.docx",
                "application/vnd.openxmlformats-officedocument"
                ".wordprocessingml.document",
                b"PK\x03\x04rest of a docx",
            )
        )


# +watcha
