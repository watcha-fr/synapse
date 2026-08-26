import logging
from typing import TYPE_CHECKING, Literal, Optional

from synapse.api.errors import Codes, SynapseError
from synapse.module_api import NOT_SPAM, ModuleApi
from synapse.util.watcha_blocked_extensions import (
    BLOCKED_EXT_FILE,
    SNIFF_HEADER_SIZE,
    blocked_extension_for_upload,
    load_blocked_extensions,
)

if TYPE_CHECKING:
    from synapse.media._base import FileInfo
    from synapse.media.media_storage import ReadableFileWrapper

logger = logging.getLogger(__name__)


class FileTypeFilter:
    """Rejects uploads whose type is on the blocked extension list.

    The list is managed from the admin console (see
    ``synapse/rest/admin/watcha_file_type_filter.py``) and read from disk on
    each upload, through an mtime-based cache so a change is picked up without
    restarting the server.

    A file is rejected when *any* of the following names a blocked extension:
    the filename declared by the client, the content type declared by the
    client, or the actual first bytes of the stored file. The last one is what
    makes the filter meaningful: renaming ``payload.exe`` into ``notes.txt``,
    or uploading it with no filename at all, no longer gets through.

    Known and accepted limit
    ------------------------
    Content detection only recognises signatures that a legitimate document
    never starts with: executables (PE, ELF, Mach-O, ``.class``, ``.lnk``), a
    shebang line, ``<?php`` and ``@echo off``. A shell or python script saved
    *without* a shebang carries no such signature -- it is a text file, and
    nothing tells it apart from a genuine ``.txt``. Renaming such a script to
    ``notes.txt`` therefore still gets through.

    This is deliberate: the alternatives are to guess from keywords (which
    rejects real documents quoting code, and is trivially defeated by
    rewriting the script) or to move to a whitelist of recognised types (which
    rejects every unlisted business format). Note that a renamed script is not
    executable as-is either: the recipient has to save it *and* rename it back.
    For these files the extension filter is a hygiene measure, not a barrier;
    blocking malicious content itself is the job of an antivirus, not of this
    module.
    """

    def __init__(self, config: dict, api: ModuleApi):
        self.api = api
        # The path may be set in the module config (mostly for tests); otherwise
        # it comes from `watcha.blocked_extensions_path`, shared with the admin
        # endpoint that writes the list.
        self.blocked_ext_file = (config or {}).get("blocked_ext_file")
        if not self.blocked_ext_file:
            hs = getattr(api, "_hs", None)
            self.blocked_ext_file = (
                getattr(hs.config.watcha, "blocked_extensions_path", None)
                if hs is not None
                else None
            ) or BLOCKED_EXT_FILE

        api.register_spam_checker_callbacks(
            check_media_file_for_spam=self.check_media_file_for_spam,
        )

    async def _read_header(
        self, file_wrapper: "ReadableFileWrapper"
    ) -> Optional[bytes]:
        """Read the first bytes of the stored file, without blocking the reactor."""
        path = getattr(file_wrapper, "path", None)
        if path:

            def read_header() -> bytes:
                with open(path, "rb") as f:
                    return f.read(SNIFF_HEADER_SIZE)

            try:
                return await self.api.defer_to_thread(read_header)
            except Exception as e:
                logger.warning("[FileTypeFilter] could not read %s: %s", path, e)
                return None

        # No path available (should not happen with the bundled media storage):
        # fall back to the documented API, keeping only the leading bytes.
        chunks: list = []
        size = 0

        def collect(chunk: bytes) -> None:
            nonlocal size
            if size < SNIFF_HEADER_SIZE:
                chunks.append(chunk[: SNIFF_HEADER_SIZE - size])
                size += len(chunks[-1])

        try:
            await file_wrapper.write_chunks_to(collect)
        except Exception as e:
            logger.warning("[FileTypeFilter] could not read the uploaded file: %s", e)
            return None

        return b"".join(chunks)

    async def check_media_file_for_spam(
        self, file_wrapper: "ReadableFileWrapper", file_info: "FileInfo"
    ) -> Literal["NOT_SPAM"]:
        blocked_exts = await self.api.defer_to_thread(
            load_blocked_extensions, self.blocked_ext_file
        )
        if not blocked_exts:
            return NOT_SPAM

        # `upload_name` and `media_type` are set by the media repository for
        # local uploads; they are `None` for remote media and thumbnails, where
        # only the content signature applies.
        upload_name = getattr(file_info, "upload_name", None)
        media_type = getattr(file_info, "media_type", None)

        header = await self._read_header(file_wrapper)

        blocked_ext = blocked_extension_for_upload(
            blocked_exts,
            upload_name=upload_name,
            media_type=media_type,
            header=header,
        )

        if blocked_ext is None:
            return NOT_SPAM

        logger.warning(
            "[FileTypeFilter] blocked upload %s (media_id=%s, declared type=%s): "
            "matches blocked extension .%s",
            upload_name or "<no name>",
            file_info.file_id,
            media_type or "<none>",
            blocked_ext,
        )
        raise SynapseError(
            403,
            f"L'upload du fichier avec extension .{blocked_ext} est interdit",
            Codes.FORBIDDEN,
        )
