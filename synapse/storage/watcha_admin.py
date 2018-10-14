from twisted.internet import defer

from ._base import SQLBaseStore

from synapse.util.caches.descriptors import cached, cachedInlineCallbacks
from synapse.api.constants import EventTypes, JoinRules
from synapse.storage.engines import PostgresEngine, Sqlite3Engine
from synapse.types import get_domain_from_id, get_localpart_from_id
import time

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


    def get_watchauser_display_name(self):
        return self._simple_select_list(
            table="profiles",
            keyvalues={},
            retcols=[
                "user_id",
                "displayname",
            ],
            desc="get_rooms",
        )

    @defer.inlineCallbacks
    def get_watcha_extend_room_list(self):
        """ List the rooms their state and their users """
        sql_rooms =""" SELECT room_id, creator FROM rooms """
        sql_members = """
            SELECT user_id, membership FROM room_memberships WHERE room_id = "{room_id}" ORDER BY event_id ASC;
        """
        sql_last_message = """
            SELECT received_ts FROM events WHERE type = "m.room.message" AND room_id = "{room_id}" ORDER BY received_ts DESC LIMIT 1;
        """
        now = int(round(time.time() * 1000))
        ACTIVE_THRESHOLD = 1000 * 3600 * 24 * 7
        result = { "now": now, "active_threshold": ACTIVE_THRESHOLD }
        rooms = yield self._execute("get_room_count_per_type", None, sql_rooms)
        logger.info(rooms);
        roomArray=[]
        for room in rooms:
            roomObject={}
            roomObject['room_id']=room[0]
            roomObject['creator']=room[1]
            roomObject['members']=[]
            membership_events = yield self._execute("get_room_count_per_type", None, sql_members.format(**{ "room_id": room[0] }))
            for step in membership_events:
                user_id = step[0]
                membership = step[1]
                if membership == "join" or membership == "invite":
                    roomObject['members'].append(user_id)
                elif membership == "leave":
                    roomObject['members'].remove(user_id)
                if len(roomObject['members']) >= 3:
                    roomObject['type'] = "room"
                else:
                    roomObject['type'] = "discussion"

                last_message_ts = yield self._execute("get_room_count_per_type", None, sql_last_message.format(**{ "room_id": room }))
                if last_message_ts is not None and len(last_message_ts) > 0:
                    last_message_ts = last_message_ts[0][0]
                    #room_result["last_ts"] = last_message_ts
                    if now - last_message_ts < ACTIVE_THRESHOLD: # one week
                        roomObject['state'] = 'active'
                else:
                    roomObject['state'] = 'inactive'
                roomArray.append(roomObject)

            defer.returnValue(roomArray);




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
