# watcha+
"""Helpers to decide whether an uploaded file must be rejected.

The list of blocked extensions is managed from the admin console and persisted
as a small JSON file (``blocked_extensions.json``) so it can be changed at
runtime without restarting the server, mirroring the pattern used by
``watcha_retention``.

The decision itself (``blocked_extension_for_upload``) never relies on the
client-provided filename alone: the declared content type and the first bytes
of the stored file are inspected too, so that renaming ``payload.exe`` into
``notes.txt`` -- or uploading it with no filename at all -- does not bypass the
filter.
"""

import json
import logging
import os
from typing import Iterable, Optional

logger = logging.getLogger(__name__)

# Default location of the list, shared by the admin servlet and the spam
# checker module.
BLOCKED_EXT_FILE = "/etc/opt/matrix-synapse/blocked_extensions.json"

# Number of bytes we need from the beginning of a file to recognise the
# signatures below.
SNIFF_HEADER_SIZE = 512

# Media types that carry no information about the actual content: clients send
# them for any binary payload, so they must never be mapped to an extension.
_GENERIC_MEDIA_TYPES = frozenset(
    {
        "",
        "application/octet-stream",
        "binary/octet-stream",
        "application/x-binary",
        "application/unknown",
        "*/*",
    }
)

# Deliberately hand-written instead of using ``mimetypes.guess_all_extensions``:
# the system mime database maps ``text/plain`` to ``.bat`` and
# ``application/octet-stream`` to ``.exe`` on some platforms, which would reject
# every plain text or binary upload.
_MEDIA_TYPE_EXTENSIONS = {
    "application/x-msdownload": {"exe", "dll"},
    "application/x-msdos-program": {"exe", "com", "bat"},
    "application/x-dosexec": {"exe", "com"},
    "application/vnd.microsoft.portable-executable": {"exe"},
    "application/x-ms-installer": {"msi"},
    "application/x-msi": {"msi"},
    "application/x-ms-shortcut": {"lnk"},
    "application/x-executable": {"elf", "bin"},
    "application/x-sharedlib": {"so"},
    "application/x-mach-binary": {"bin", "dylib"},
    "application/x-sh": {"sh"},
    "application/x-shellscript": {"sh", "bash"},
    "text/x-shellscript": {"sh", "bash"},
    "application/x-csh": {"csh"},
    "application/x-powershell": {"ps1"},
    "application/x-bat": {"bat"},
    "application/bat": {"bat"},
    "application/x-msbatch": {"bat", "cmd"},
    "text/x-python": {"py"},
    "application/x-python-code": {"py", "pyc"},
    "text/x-perl": {"pl"},
    "application/x-perl": {"pl"},
    "text/x-php": {"php"},
    "application/x-php": {"php"},
    "application/x-httpd-php": {"php"},
    "application/java-archive": {"jar"},
    "application/x-java-archive": {"jar"},
    "application/java-vm": {"class"},
    "application/vnd.android.package-archive": {"apk"},
    "application/x-apple-diskimage": {"dmg"},
    "application/vnd.microsoft.help": {"chm"},
    "application/hta": {"hta"},
    "application/x-vbs": {"vbs"},
    "text/vbscript": {"vbs"},
    "application/x-shockwave-flash": {"swf"},
}

# Byte signatures of executable content. Only unambiguous ones are listed:
# formats shared by harmless documents (OLE compound files used by both ``.msi``
# and ``.doc``, ZIP containers used by both ``.jar`` and ``.docx``) are left out
# so a legitimate document is never rejected because of its container.
_MAGIC_EXTENSIONS: tuple[tuple[bytes, set[str]], ...] = (
    # Windows/DOS executables (PE, and the legacy MZ stub they all start with).
    (b"MZ", {"exe", "dll", "com", "scr", "sys", "cpl", "ocx"}),
    # Linux/BSD ELF binaries and shared objects.
    (b"\x7fELF", {"elf", "bin", "so", "o", "out"}),
    # Compiled Java class files.
    (b"\xca\xfe\xba\xbe", {"class", "jar"}),
    # Mach-O binaries (32/64 bits, both endiannesses).
    (b"\xfe\xed\xfa\xce", {"bin", "dylib", "o"}),
    (b"\xfe\xed\xfa\xcf", {"bin", "dylib", "o"}),
    (b"\xce\xfa\xed\xfe", {"bin", "dylib", "o"}),
    (b"\xcf\xfa\xed\xfe", {"bin", "dylib", "o"}),
    # Windows shortcut (.lnk), a classic malware delivery vehicle.
    (b"\x4c\x00\x00\x00\x01\x14\x02\x00", {"lnk"}),
)

# Interpreters recognised in a shebang line, mapped to the extensions usually
# used for such scripts. Longest names first so ``powershell`` is not matched
# as ``sh``.
_SHEBANG_INTERPRETERS: tuple[tuple[str, set[str]], ...] = (
    ("python", {"py"}),
    ("perl", {"pl"}),
    ("ruby", {"rb"}),
    ("php", {"php"}),
    ("node", {"js"}),
    ("powershell", {"ps1"}),
    ("pwsh", {"ps1"}),
    ("bash", {"sh", "bash"}),
    ("zsh", {"sh", "zsh"}),
    ("ksh", {"sh", "ksh"}),
    ("csh", {"csh"}),
    ("sh", {"sh"}),
)

# Byte order marks that a Windows editor may write before the shebang. They are
# skipped before looking at text signatures, so `notepad`-saved scripts are not
# a free pass.
_BOMS: tuple[bytes, ...] = (
    b"\xef\xbb\xbf",  # UTF-8
    b"\xff\xfe",  # UTF-16 LE
    b"\xfe\xff",  # UTF-16 BE
)

# Text signatures that only a script starts with. Matched at the very beginning
# of the file (BOM aside): a document merely *quoting* PHP or batch code does
# not start with it, so this stays free of false positives.
_TEXT_SIGNATURES: tuple[tuple[bytes, set[str]], ...] = (
    (b"<?php", {"php"}),
    (b"@echo off", {"bat", "cmd"}),
)

# Cache of the parsed list, keyed by path; value is (mtime, extensions).
_cache: dict = {}


def normalize_extension(ext: str) -> str:
    """Normalise a single extension: no leading dot, lowercase, no spaces."""
    return ext.strip().lstrip(".").strip().lower()


def normalize_extensions(exts: Iterable[str]) -> set[str]:
    """Normalise a list of extensions, dropping empty entries."""
    return {normalize_extension(e) for e in exts if normalize_extension(e)}


def load_blocked_extensions(path: Optional[str] = None) -> set[str]:
    """Read the blocked extension list, returning a normalised set.

    Never raises: a missing or malformed file yields an empty set so uploads
    keep working. Results are cached and invalidated when the file's
    modification time changes, since this runs on every upload.
    """
    path = path or BLOCKED_EXT_FILE

    if not os.path.exists(path):
        return set()

    try:
        mtime = os.path.getmtime(path)
    except OSError:
        mtime = None

    cached = _cache.get(path)
    if cached is not None and mtime is not None and cached[0] == mtime:
        return set(cached[1])

    try:
        with open(path, "r", encoding="utf-8") as f:
            content = f.read().strip()
    except Exception as e:
        logger.error("[watcha] failed to read %s: %s", path, e)
        return set()

    extensions: set[str] = set()
    if content:
        try:
            data = json.loads(content)
        except Exception as e:
            logger.error("[watcha] failed to parse %s: %s", path, e)
            return set()

        if not isinstance(data, list):
            logger.error("[watcha] %s does not contain a list, ignoring it", path)
            return set()

        extensions = normalize_extensions(x for x in data if isinstance(x, str))

    if mtime is not None:
        _cache[path] = (mtime, set(extensions))

    return extensions


def save_blocked_extensions(
    extensions: Iterable[str], path: Optional[str] = None
) -> list:
    """Persist the blocked extension list and return what was written."""
    path = path or BLOCKED_EXT_FILE
    normalized = sorted(normalize_extensions(extensions))

    with open(path, "w", encoding="utf-8") as f:
        json.dump(normalized, f, indent=2)

    # Refresh the cache so the filter picks up the new list immediately.
    try:
        _cache[path] = (os.path.getmtime(path), set(normalized))
    except OSError:
        _cache.pop(path, None)

    return normalized


def extensions_for_name(upload_name: Optional[str]) -> set[str]:
    """Every extension a filename claims, including compound ones.

    ``archive.tar.gz`` yields ``{"gz", "tar.gz"}`` so a list blocking either
    form matches. ``payload.exe.txt`` yields ``{"txt", "exe.txt"}``: the hidden
    ``.exe`` is caught by content sniffing, not by the name.
    """
    if not upload_name:
        return set()

    # Keep the basename only: clients may send a path, and a directory name
    # must not drive the decision.
    name = upload_name.replace("\\", "/").rsplit("/", 1)[-1].strip()
    # Windows ignores trailing dots and spaces when opening a file, so
    # ``payload.exe.`` really is ``payload.exe``.
    name = name.rstrip(". ")

    parts = [p for p in name.lower().split(".") if p]
    if len(parts) < 2:
        return set()

    suffixes = parts[1:]
    return {".".join(suffixes[i:]) for i in range(len(suffixes))}


def extensions_for_media_type(media_type: Optional[str]) -> set[str]:
    """Extensions implied by the declared content type, if it is specific."""
    if not media_type:
        return set()

    # Drop any parameter (``text/plain; charset=utf-8``).
    main_type = media_type.split(";", 1)[0].strip().lower()
    if main_type in _GENERIC_MEDIA_TYPES:
        return set()

    return set(_MEDIA_TYPE_EXTENSIONS.get(main_type, set()))


def extensions_for_content(header: Optional[bytes]) -> set[str]:
    """Extensions implied by the first bytes of the file itself.

    Only signatures that a legitimate document never starts with are used. A
    script carrying no signature at all -- a ``.sh`` or ``.py`` with no shebang
    -- is indistinguishable from a text file and cannot be recognised here.
    """
    if not header:
        return set()

    extensions: set[str] = set()

    for magic, exts in _MAGIC_EXTENSIONS:
        if header.startswith(magic):
            extensions |= exts

    # Text signatures are looked up past any byte order mark, so a script saved
    # by a Windows editor is not treated as a plain document.
    text = header
    for bom in _BOMS:
        if text.startswith(bom):
            text = text[len(bom) :]
            break

    for signature, exts in _TEXT_SIGNATURES:
        if text[: len(signature)].lower() == signature:
            extensions |= exts

    if text.startswith(b"#!"):
        # A shebang means the file is meant to be run by an interpreter.
        first_line = text.split(b"\n", 1)[0][:256].decode("ascii", "replace").lower()
        matched = False
        for interpreter, exts in _SHEBANG_INTERPRETERS:
            if interpreter in first_line:
                extensions |= exts
                matched = True
                break
        if not matched:
            extensions |= {"sh"}

    return extensions


def blocked_extension_for_upload(
    blocked_extensions: set[str],
    upload_name: Optional[str] = None,
    media_type: Optional[str] = None,
    header: Optional[bytes] = None,
) -> Optional[str]:
    """Return the blocked extension matching this upload, or ``None``.

    The three sources are combined: the declared filename, the declared content
    type and the actual leading bytes of the file.
    """
    if not blocked_extensions:
        return None

    candidates = (
        extensions_for_name(upload_name)
        | extensions_for_media_type(media_type)
        | extensions_for_content(header)
    )

    matches = candidates & blocked_extensions
    if not matches:
        return None

    # Deterministic answer, so the message shown to the user does not depend on
    # set ordering.
    return sorted(matches)[0]


# +watcha
