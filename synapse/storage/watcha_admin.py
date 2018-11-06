# -*- coding: utf-8 -*-

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
        fields = ["name", "is_guest", "is_partner", "admin", "email", "creation_ts", "is_active" ,"displayname", "MAX(last_seen)"]
        sql_user_list = 'SELECT ' + ', '.join(fields) + ' FROM users LEFT JOIN user_ips ON users.name = user_ips.user_id LEFT JOIN profiles ON users.name LIKE "@"||profiles.user_id||":%"GROUP BY users.name ;'
        userList =  yield self._execute("get_watcha_user_list", None, sql_user_list)
        userObject = {}
        userListTuple = []
        for user in userList:
            userObject = {}
            for i in range(0, len(fields)):
                userObject[fields[i]] = user[i]
            userListTuple.append(userObject)
        defer.returnValue(userListTuple)

    @defer.inlineCallbacks
    def watcha_user_ip(self, userId):
        sql_user_ip="SELECT ip, user_agent, last_seen FROM user_ips where user_id="+"'"+userId+"'"+"ORDER BY last_seen DESC"
        user_ip = yield self._execute("watcha_user_ip",None, sql_user_ip)
        defer.returnValue(user_ip)


    @defer.inlineCallbacks
    def watcha_extend_room_list(self):
        """ List the rooms their state and their users """
        sql_rooms = """
            SELECT rooms.room_id, creator, name FROM rooms JOIN room_names on rooms.room_id = room_names.room_id
        """
        sql_members = """
            SELECT user_id, membership FROM room_memberships WHERE room_id = "{room_id}" ORDER BY event_id ASC;
        """
        sql_last_message = """
            SELECT received_ts FROM events WHERE type = "m.room.message" AND room_id = "{room_id}" ORDER BY received_ts DESC LIMIT 1;
        """

        now = int(round(time.time() * 1000))
        ACTIVE_THRESHOLD = 1000 * 3600 * 24 * 7 # one week
        rooms = yield self._execute("get_room_count_per_type", None, sql_rooms)
        roomArray = []
        for room in rooms:
            roomObject = {}
            roomObject['room_id'] = room[0]
            roomObject['creator'] = room[1]
            roomObject['name'] = room[2]
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
            last_message_ts = yield self._execute("get_room_count_per_type", None, sql_last_message.format(**{ "room_id": room[0] }))
            roomObject['active'] = 0
            if last_message_ts is not None and len(last_message_ts) > 0:
                last_message_ts = last_message_ts[0][0]
                #room_result["last_ts"] = last_message_ts
                if now - last_message_ts < ACTIVE_THRESHOLD:
                    roomObject['active'] = 1
            roomArray.append(roomObject)

        defer.returnValue(roomArray)


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
    
    def watcha_reactivate_account(self, userId):
        return self._simple_update(
            table = "users",
            keyvalues = {'name':userId},
            updatevalues = {'is_active':1},
            desc = 'watchaReactivateAccount',
    )

    def watcha_log(self):
        f=open("/home/morisse/Work/synapse-admin/synapse/homeserver.log", "r")
        if f.mode == 'r':
            contents =f.read()
        return contents

    @defer.inlineCallbacks
    def get_user_admin(self):
        sql_user_admin = """ SELECT name FROM users WHERE admin=1"""
        admins=yield self._execute("get_user_admin", None, sql_user_admin)
        defer.returnValue(admins)

    @defer.inlineCallbacks
    def watcha_admin_stats(self):
        user_stats = yield self.get_count_users_partners()
        room_stats = yield self.get_room_count_per_type()
        user_admin = yield self.get_user_admin()
        try:
            proc = subprocess.Popen(['pip', 'freeze'], stdout=subprocess.PIPE)
            output = subprocess.check_output(('grep', 'matrix-synapse==='), stdin=proc.stdout)
            proc.wait()
            if type(output) is str:
                synapse_version = output
            else:
                (synapse_version, err) = output.communicate()
        except subprocess.CalledProcessError as e:
            synapse_version = "unavailable"

        ret={'users':user_stats,'rooms':room_stats,'admins':user_admin,'version':synapse_version}

        defer.returnValue(ret)
