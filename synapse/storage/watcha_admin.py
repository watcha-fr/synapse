from twisted.internet import defer

from ._base import SQLBaseStore

from synapse.util.caches.descriptors import cached, cachedInlineCallbacks
from synapse.api.constants import EventTypes, JoinRules
from synapse.storage.engines import PostgresEngine, Sqlite3Engine
from synapse.types import get_domain_from_id, get_localpart_from_id
import time
import psutil
import subprocess
import os

import logging

logger = logging.getLogger(__name__)

class WatchaAdminStore(SQLBaseStore):

    @defer.inlineCallbacks
    def watcha_user_list(self):
        sql_user_list = """
            SELECT "name", "is_guest", "is_partner", "admin", "email", "creation_ts", "is_active" FROM users;
        """
        sql_user_displayname = """
            SELECT "user_id", "displayname" FROM profiles;
        """
        sql_user_ip = """
            SELECT "user_id", "ip", "last_seen" FROM user_ips ORDER BY last_seen ASC;
        """

        userList =  yield self._execute("get_watcha_user_list", None, sql_user_list)
        userNameList = yield self._execute("get_user_name", None, sql_user_displayname)
        userIpList = yield self._execute("get_user_name", None, sql_user_ip)
        userObject = {}
        userListTupple = []
        for user in userList:
            userObject = {}
            userObject['name'] = user[0]
            userObject['is_guest'] = user[1]
            userObject['is_partner'] = user[2]
            userObject['admin'] = user[3]
            userObject['email'] = user[4]
            userObject['creation_ts'] = user[5]
            userObject['is_active'] = user[6]
            userObject['displayname'] = ''
            userObject['last_seen'] = ''
            userObject['ip'] = set()
            for name in userNameList:
                if userObject['name'].replace('@','').split(':')[0] == name[0]:
                    userObject['displayname'] = name[1]
            userListTupple.append(userObject)

            for user in userIpList:
                if userObject['name'] == user[0]:
                    userObject['ip'].add(user[1])
                    userObject['last_seen'] = user[2]


        defer.returnValue(userListTupple)

    @defer.inlineCallbacks
    def watcha_extend_room_list(self):
        """ List the rooms their state and their users """
        sql_rooms = """ SELECT room_id, creator FROM rooms """
        sql_members = """
            SELECT user_id, membership FROM room_memberships WHERE room_id = "{room_id}" ORDER BY event_id ASC;
        """
        sql_last_message = """
            SELECT received_ts FROM events WHERE type = "m.room.message" AND room_id = "{room_id}" ORDER BY received_ts DESC LIMIT 1;
        """
        sql_room_name = """
            SELECT room_id, name FROM room_names;
        """
        now = int(round(time.time() * 1000))
        ACTIVE_THRESHOLD = 1000 * 3600 * 24 * 7
        result = { "now": now, "active_threshold": ACTIVE_THRESHOLD }
        rooms = yield self._execute("get_room_count_per_type", None, sql_rooms)
        room_name = yield self._execute("get_room_name", None, sql_room_name)
        roomArray = []
        for room in rooms:
            roomObject = {}
            roomObject['room_id'] = room[0]
            roomObject['creator'] = room[1]
            roomObject['members'] = set()
            membership_events = yield self._execute("get_room_count_per_type", None, sql_members.format(**{ "room_id": room[0] }))
            for step in membership_events:
                user_id = step[0]
                membership = step[1]
                if membership == "join" or membership == "invite":
                    roomObject['members'].add(user_id)
                elif membership == "leave":
                    roomObject['members'].discard(user_id)
                if len(roomObject['members']) >= 3:
                    roomObject['type'] = "Room"
                else:
                    roomObject['type'] = "One to one"

            for name in room_name:
                if name[0] == room[0]:
                    roomObject['name'] = name[1]

            last_message_ts = yield self._execute("get_room_count_per_type", None, sql_last_message.format(**{ "room_id": room[0] }))
            roomObject['active'] = 0
            if last_message_ts is not None and len(last_message_ts) > 0:
                last_message_ts = last_message_ts[0][0]
                if now - last_message_ts < ACTIVE_THRESHOLD: # one week
                    roomObject['active'] = 1
            roomArray.append(roomObject)

        defer.returnValue(roomArray);




    def watcha_room_membership(self):
        return self._simple_select_list(
            table = "room_memberships",
            keyvalues = {},
            retcols = [
                "room_id",
                "user_id",
                "membership"
            ],
            desc = "get_rooms",
        )

    def watcha_server_state(self):
        serverState = {}
        cpu = {}
        memory = {}
        cpuUtilization = psutil.cpu_percent(interval=1)
        cpuUtilizationPerCpu = psutil.cpu_percent(interval=1, percpu=True)
        mem = psutil.virtual_memory()
        swap = psutil.swap_memory()
        diskUsage = psutil.disk_usage('/')
        cpu['average'] = cpuUtilization
        cpu['detailed'] = cpuUtilizationPerCpu
        memory['memory'] = mem._asdict()
        memory['swap'] = swap._asdict()
        serverState['cpu'] = cpu
        serverState['memory'] = memory
        serverState ['disk'] = diskUsage._asdict()
        return serverState


    def watcharoom_name(self):
        return self._simple_select_list(
            table = "room_names",
            keyvalues = {},
            retcols = [
                "name",
                "room_id",
            ],
            desc = "get_rooms",
        )

    def watcha_update_mail(self, userId, email):
        return self._simple_update(
            table = "users",
            keyvalues = {'name':userId},
            updatevalues = {'email':email},
            desc = 'updateMail',
        )

    def watcha_update_to_member(self, userId):
        return self._simple_update(
            table = "users",
            keyvalues = {'name':userId},
            updatevalues = {'is_partner':0},
            desc = 'WatchaUpdateToMember',
        )

    def watcha_deactivate_account(self, userId):
        return self._simple_update(
            table = "users",
            keyvalues = {'name':userId},
            updatevalues = {'is_active':0},
            desc = 'watchaDeactivateAccount',
    )

    def watcha_log(self):
        f=open("/home/morisse/Work/synapse-admin/synapse/homeserver.log", "r")
        if f.mode == 'r':
            contents =f.read()
        return contents
