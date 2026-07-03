# watcha+
"""Helpers to read and write the server-wide "message depth" (retention)
configuration set from the admin console.

The configuration is persisted as a small JSON file (path configured via
``watcha.retention_config_path``) so it can be changed at runtime without a
server restart, mirroring the pattern used by ``watcha_file_type_filter`` and
``watcha_user_audit_log``. It holds two values:

  - ``default_max_lifetime``: the server-wide default retention duration, in
    milliseconds (``None`` means "no default", i.e. fall back to homeserver.yaml).
  - ``allow_room_override``: whether room admins are allowed to set a per-room
    retention duration from the room settings (defaults to ``True``).
"""

import json
import logging
import os
from typing import Optional, Tuple, TypedDict

logger = logging.getLogger(__name__)

# When no configuration file exists yet, room admins are allowed to manage the
# per-room retention by default (the admin can disable it from the console).
DEFAULT_ALLOW_ROOM_OVERRIDE = True


class WatchaRetentionConfig(TypedDict):
    default_max_lifetime: Optional[int]
    allow_room_override: bool


def _defaults() -> WatchaRetentionConfig:
    return {
        "default_max_lifetime": None,
        "allow_room_override": DEFAULT_ALLOW_ROOM_OVERRIDE,
    }


# Tiny mtime-based cache so that ``get_retention_policy_for_room`` (a hot path
# hit on /sync, /messages and purge) does not read the file on every call.
# Keyed by path; value is (mtime, parsed_config).
_cache: dict = {}


def _parse(content: str) -> WatchaRetentionConfig:
    config = _defaults()

    try:
        data = json.loads(content)
    except Exception as e:
        logger.error("[watcha] failed to parse retention config: %s", e)
        return config

    if not isinstance(data, dict):
        return config

    default_max_lifetime = data.get("default_max_lifetime")
    if (
        isinstance(default_max_lifetime, int)
        and not isinstance(default_max_lifetime, bool)
        and default_max_lifetime > 0
    ):
        config["default_max_lifetime"] = default_max_lifetime

    allow_room_override = data.get("allow_room_override")
    if isinstance(allow_room_override, bool):
        config["allow_room_override"] = allow_room_override

    return config


def load_retention_config(path: Optional[str]) -> WatchaRetentionConfig:
    """Read the retention configuration file, returning safe defaults.

    Never raises: a missing or malformed file yields the defaults so the server
    keeps working even if the file has not been created yet. Results are cached
    and invalidated when the file's modification time changes.
    """
    if not path or not os.path.exists(path):
        return _defaults()

    try:
        mtime = os.path.getmtime(path)
    except OSError:
        mtime = None

    cached: Optional[Tuple[float, WatchaRetentionConfig]] = _cache.get(path)
    if cached is not None and mtime is not None and cached[0] == mtime:
        return dict(cached[1])  # type: ignore[return-value]

    try:
        with open(path, "r", encoding="utf-8") as f:
            content = f.read().strip()
    except Exception as e:
        logger.error("[watcha] failed to read retention config %s: %s", path, e)
        return _defaults()

    config = _parse(content) if content else _defaults()

    if mtime is not None:
        _cache[path] = (mtime, dict(config))  # type: ignore[assignment]

    return config


def save_retention_config(
    path: str,
    default_max_lifetime: Optional[int],
    allow_room_override: bool,
) -> WatchaRetentionConfig:
    """Persist the retention configuration to ``path`` and return what was written."""
    config: WatchaRetentionConfig = {
        "default_max_lifetime": default_max_lifetime,
        "allow_room_override": allow_room_override,
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2)
    # Refresh the cache so subsequent reads see the new value immediately.
    try:
        _cache[path] = (os.path.getmtime(path), dict(config))  # type: ignore[assignment]
    except OSError:
        _cache.pop(path, None)
    return config
# +watcha
