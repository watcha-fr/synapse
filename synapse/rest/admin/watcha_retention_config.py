# watcha+
import logging
from http import HTTPStatus
from typing import TYPE_CHECKING, Tuple

from synapse.http.servlet import RestServlet, parse_json_object_from_request
from synapse.http.site import SynapseRequest
from synapse.rest.admin._base import admin_patterns, assert_requester_is_admin
from synapse.types import JsonDict
from synapse.util.watcha_retention import load_retention_config, save_retention_config

if TYPE_CHECKING:
    from synapse.server import HomeServer

logger = logging.getLogger(__name__)


class WatchaRetentionConfigAdminServlet(RestServlet):
    """Server-wide "message depth" (retention) settings, editable from the
    admin console.

    Endpoints:
      - GET  /_synapse/admin/v1/watcha_retention_config
            -> {"default_max_lifetime": <int ms|null>, "allow_room_override": <bool>}
      - POST /_synapse/admin/v1/watcha_retention_config
            body: {"default_max_lifetime": <int ms|null>, "allow_room_override": <bool>}
            -> the persisted configuration
    """

    PATTERNS = admin_patterns("/watcha_retention_config$")

    def __init__(self, hs: "HomeServer"):
        super().__init__()
        self.auth = hs.get_auth()
        self._retention_config_path = hs.config.watcha.retention_config_path

    async def on_GET(self, request: SynapseRequest) -> Tuple[int, JsonDict]:
        await assert_requester_is_admin(self.auth, request)
        config = load_retention_config(self._retention_config_path)
        return HTTPStatus.OK, dict(config)

    async def on_POST(self, request: SynapseRequest) -> Tuple[int, JsonDict]:
        await assert_requester_is_admin(self.auth, request)
        body = parse_json_object_from_request(request)

        default_max_lifetime = body.get("default_max_lifetime")
        if default_max_lifetime is not None and not (
            isinstance(default_max_lifetime, int)
            and not isinstance(default_max_lifetime, bool)
            and default_max_lifetime > 0
        ):
            return (
                HTTPStatus.BAD_REQUEST,
                {
                    "error": "default_max_lifetime must be a positive integer "
                    "(milliseconds) or null"
                },
            )

        allow_room_override = body.get("allow_room_override", True)
        if not isinstance(allow_room_override, bool):
            return (
                HTTPStatus.BAD_REQUEST,
                {"error": "allow_room_override must be a boolean"},
            )

        config = save_retention_config(
            self._retention_config_path,
            default_max_lifetime,
            allow_room_override,
        )
        logger.info(
            "[watcha] retention config updated: default_max_lifetime=%s "
            "allow_room_override=%s",
            config["default_max_lifetime"],
            config["allow_room_override"],
        )
        return HTTPStatus.OK, dict(config)
# +watcha
