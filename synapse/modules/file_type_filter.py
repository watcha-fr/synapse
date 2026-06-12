import logging
import os
import json

from synapse.module_api import ModuleApi, NOT_SPAM
from synapse.api.errors import Codes
from synapse.api.errors import SynapseError
from synapse.util.watcha_upload_names import UPLOAD_NAMES

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

class FileTypeFilter:
    """Filtre les fichiers uploadés selon leur type MIME"""
    def __init__(self, config: dict, api: ModuleApi):
        self.api = api

        api.register_spam_checker_callbacks(
            check_media_file_for_spam=self.check_media_file_for_spam,
        )

    async def check_media_file_for_spam(self, file_wrapper, file_info):
        # Charger la liste à chaque upload (toujours à jour)
        blocked_exts = load_blocked_extensions()
        logger.info(f"[FileTypeFilter] Extensions bloquées: {blocked_exts}")

        # Récupération du filename depuis upload_names.py
        filename = UPLOAD_NAMES.get(file_info.file_id)
        if filename:
            logger.info(f"[FileTypeFilter] Filename détecté: {filename}")
            ext = filename.split(".")[-1].lower() if "." in filename else None

            if ext and ext in blocked_exts:
                error_msg = f"L’upload du fichier avec extension .{ext} est interdit"
                logger.warning(f"[FileTypeFilter] Bloqué: {filename} ({ext})")
                # Nettoyer l’état partagé
                UPLOAD_NAMES.pop(file_info.file_id, None)
                raise SynapseError(403, error_msg, Codes.FORBIDDEN)

        # Nettoyer si non bloqué aussi
        UPLOAD_NAMES.pop(file_info.file_id, None)
        return NOT_SPAM
