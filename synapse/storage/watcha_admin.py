from twisted.internet import defer

from ._base import SQLBaseStore

from synapse.util.caches.descriptors import cached, cachedInlineCallbacks
from synapse.api.constants import EventTypes, JoinRules
from synapse.storage.engines import PostgresEngine, Sqlite3Engine
from synapse.types import get_domain_from_id, get_localpart_from_id

import re
import logging

logger = logging.getLogger(__name__)

class WatchaAdminStore(SQLBaseStore):
    def get_watchauser_list(self):
        return self._simple_select_list(
            table="users",
            keyvalues={},
            retcols=[
                "name",
                "is_guest",
                "is_partner",
                "admin",
                "email",
                "creation_ts"

            ],
            desc="get_watchausers",
        )

    def get_watcharoom_list(self):
        return self._simple_select_list(
            table="rooms",
            keyvalues={},
            retcols=[
                "room_id",
                "creator",
            ],
            desc="get_rooms",
        )

    def get_watchauser_display_name(self):
        return self._simple_select_list(
            table="profiles",
            keyvalues={},
            retcols=[
                "room_id",
                "creator",
            ],
            desc="get_rooms",
        )

    def get_watcharoom_membership(self):
        return self._simple_select_list(
            table="room_memberships",
            keyvalues={},
            retcols=[
                "room_id",
                "user_id",
                "membership"
            ],
            desc="get_rooms",
        )

    def get_watcharoom_name(self):
        return self._simple_select_list(
            table="room_names",
            keyvalues={},
            retcols=[
                "name",
                "room_id",
            ],
            desc="get_rooms",
        )
