import json
import logging
import os

from synapse.http.servlet import RestServlet
from synapse.rest.admin._base import admin_patterns, assert_requester_is_admin

logger = logging.getLogger(__name__)


class WatchaUserAuditLogAdminServlet(RestServlet):
    """
    Endpoint admin:
      - GET /_synapse/admin/v1/watcha_user_audit_log
        -> renvoie le journal d'audit des utilisateurs (CREATE, DELETE,
           DEACTIVATE, REACTIVATE) sous forme de tableau JSON.

    Le chemin du fichier est celui configuré via `watcha.user_audit_log_path`.
    """

    PATTERNS = admin_patterns("/watcha_user_audit_log")

    def __init__(self, hs):
        super().__init__()
        self.auth = hs.get_auth()
        self._user_audit_log_path = hs.config.watcha.user_audit_log_path

    async def on_GET(self, request):
        await assert_requester_is_admin(self.auth, request)

        entries = []
        path = self._user_audit_log_path
        if path and os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    content = f.read().strip()
                if content:
                    entries = json.loads(content)
            except Exception as e:
                logger.error("[watcha] failed to read user audit log %s: %s", path, e)
                entries = []

        return 200, entries
