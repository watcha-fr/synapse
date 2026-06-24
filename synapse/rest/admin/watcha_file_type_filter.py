import logging
from synapse.http.servlet import RestServlet, parse_json_object_from_request
from synapse.rest.admin._base import assert_requester_is_admin, admin_patterns
import json
import os

logger = logging.getLogger(__name__)

BLOCKED_EXT_FILE = "/etc/opt/matrix-synapse/blocked_extensions.json"


def load_blocked_extensions():
    if os.path.exists(BLOCKED_EXT_FILE):
        with open(BLOCKED_EXT_FILE, "r") as f:
            try:
                return json.load(f)
            except Exception as e:
                logger.error(f"Erreur lecture {BLOCKED_EXT_FILE}: {e}")
                return []
    return []


def save_blocked_extensions(exts):
    with open(BLOCKED_EXT_FILE, "w") as f:
        json.dump(exts, f, indent=2)


class WatchaFileTypeFilterAdminServlet(RestServlet):
    """
    Endpoint admin:
      - GET  /_synapse/admin/v1/watcha_file_type_filter  -> liste des extensions bloquées
      - POST /_synapse/admin/v1/watcha_file_type_filter  -> maj de la liste
    """

    PATTERNS = admin_patterns("/watcha_file_type_filter")

    def __init__(self, hs):
        super().__init__()
        self.auth = hs.get_auth()

    async def on_GET(self, request):
        """Récupère la liste des extensions bloquées"""
        await assert_requester_is_admin(self.auth, request)
        blocked = load_blocked_extensions()
        return 200, {"blocked_extensions": blocked}

    async def on_POST(self, request):
        """Met à jour la liste des extensions bloquées"""
        await assert_requester_is_admin(self.auth, request)
        params = parse_json_object_from_request(request)
        new_list = params.get("blocked_extensions")

        if not isinstance(new_list, list) or not all(isinstance(x, str) for x in new_list):
            return 400, {"error": "Invalid blocked_extensions format, must be a list of strings"}

        save_blocked_extensions(new_list)
        return 200, {"blocked_extensions": new_list}
