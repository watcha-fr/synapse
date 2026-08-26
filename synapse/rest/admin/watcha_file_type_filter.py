import logging
from typing import TYPE_CHECKING

from synapse.http.servlet import RestServlet, parse_json_object_from_request
from synapse.http.site import SynapseRequest
from synapse.types import JsonDict
from synapse.rest.admin._base import admin_patterns, assert_requester_is_admin
from synapse.util.watcha_blocked_extensions import (
    load_blocked_extensions,
    save_blocked_extensions,
)

if TYPE_CHECKING:
    from synapse.server import HomeServer

logger = logging.getLogger(__name__)


class WatchaFileTypeFilterAdminServlet(RestServlet):
    """
    Endpoint admin:
      - GET  /_synapse/admin/v1/watcha_file_type_filter  -> liste des extensions bloquées
      - POST /_synapse/admin/v1/watcha_file_type_filter  -> maj de la liste

    La liste est lue et écrite via ``synapse.util.watcha_blocked_extensions``,
    partagé avec le module ``FileTypeFilter`` : les extensions sont normalisées
    (sans point, en minuscules) et le cache du filtre est rafraîchi dès
    l'écriture.
    """

    PATTERNS = admin_patterns("/watcha_file_type_filter")

    def __init__(self, hs: "HomeServer"):
        super().__init__()
        self.auth = hs.get_auth()
        self.blocked_ext_file = hs.config.watcha.blocked_extensions_path

    async def on_GET(self, request: SynapseRequest) -> tuple[int, JsonDict]:
        """Récupère la liste des extensions bloquées"""
        await assert_requester_is_admin(self.auth, request)
        blocked = sorted(load_blocked_extensions(self.blocked_ext_file))
        return 200, {"blocked_extensions": blocked}

    async def on_POST(self, request: SynapseRequest) -> tuple[int, JsonDict]:
        """Met à jour la liste des extensions bloquées"""
        await assert_requester_is_admin(self.auth, request)
        params = parse_json_object_from_request(request)
        new_list = params.get("blocked_extensions")

        if not isinstance(new_list, list) or not all(
            isinstance(x, str) for x in new_list
        ):
            return 400, {
                "error": "Invalid blocked_extensions format, must be a list of strings"
            }

        saved = save_blocked_extensions(new_list, self.blocked_ext_file)
        return 200, {"blocked_extensions": saved}
