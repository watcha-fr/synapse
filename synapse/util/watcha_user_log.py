import json
import logging
import os
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

logger = logging.getLogger(__name__)


class UserAuditAction(str, Enum):
    """Actions tracked in the Watcha user audit log."""

    CREATE = "CREATE"
    DELETE = "DELETE"
    DEACTIVATE = "DEACTIVATE"
    REACTIVATE = "REACTIVATE"


def append_user_audit_log(
    path: Optional[str],
    user_id: str,
    display_name: Optional[str],
    action: UserAuditAction,
    avatar_src: Optional[str] = None,
) -> None:
    """Append an entry to the Watcha user audit log JSON file.

    The file holds a JSON array of entries with the following shape::

        {
            "id": "log-1",
            "timestamp": "2026-05-02T08:14:22.341210+00:00",
            "user_id": "@...:server",
            "display_name": "...",
            "avatar_src": null,
            "action": "CREATE"
        }

    This is best-effort: any failure is logged and swallowed so it never breaks
    the admin request that triggered it. It is meant to be called from the
    Synapse reactor thread; since the reactor is single-threaded the
    read-modify-write cycle below cannot interleave with another call.

    Args:
        path: Path of the JSON file. If ``None`` the call is a no-op (feature
            disabled).
        user_id: The full Matrix ID of the user the action targets.
        display_name: The user's display name at the time of the action.
        action: The action performed.
        avatar_src: The user's avatar URL, if any.
    """
    if not path:
        return

    try:
        entries = []
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    content = f.read().strip()
                if content:
                    entries = json.loads(content)
                    if not isinstance(entries, list):
                        logger.warning(
                            "[watcha] user audit log %s is not a JSON array, "
                            "starting fresh",
                            path,
                        )
                        entries = []
            except (json.JSONDecodeError, OSError):
                logger.exception(
                    "[watcha] failed to read user audit log %s, starting fresh", path
                )
                entries = []

        entries.append(
            {
                "id": f"log-{len(entries) + 1}",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "user_id": user_id,
                "display_name": display_name,
                "avatar_src": avatar_src,
                "action": action.value,
            }
        )

        # Write to a temporary file then atomically replace, so a crash mid-write
        # can never corrupt the existing log.
        tmp_path = f"{path}.tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(entries, f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, path)
    except Exception:
        logger.exception("[watcha] failed to append user audit log entry")
