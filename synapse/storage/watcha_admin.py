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
from collections import defaultdict

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
        SQL_USER_IP = "SELECT ip, user_agent, last_seen FROM user_ips where user_id="+"'"+userId+"'"+"ORDER BY last_seen DESC"
        user_ip = yield self._execute("watcha_user_ip",None, SQL_USER_IP)
        defer.returnValue(user_ip)

    @defer.inlineCallbacks
    def watcha_extend_room_list(self):
        """ List the rooms their state and their users """

        ROOMS_SQL = """
        SELECT rooms.room_id, rooms.creator, room_names.name, last_events.last_received_ts FROM rooms 
        LEFT JOIN (SELECT max(event_id) event_id, room_id from room_names group by room_id) last_room_names 
              ON rooms.room_id = last_room_names.room_id 
        LEFT JOIN room_names on room_names.event_id = last_room_names.event_id 
        LEFT JOIN (SELECT max(received_ts) last_received_ts, room_id FROM events 
                   GROUP BY room_id HAVING type = "m.room.message") last_events 
              ON last_events.room_id = rooms.room_id
        ORDER BY rooms.room_id ASC;
        """

        MEMBERS_SQL = """
        SELECT room_id, user_id, membership FROM room_memberships ORDER BY room_id, event_id ASC
        """

        rooms = yield self._execute("get_room_count_per_type", None, ROOMS_SQL)        
        room_memberships = yield self._execute("get_room_count_per_type", None, MEMBERS_SQL)
        
        membership_by_room = defaultdict(list)
        for room_id, user_id, membership in room_memberships:
            membership_by_room[room_id].append((user_id, membership))

        members_by_room = {
            room_id: list(set(user_id for user_id, membership in members if membership in ["join", "invite"])
                          -
                          set(user_id for user_id, membership in members if membership == "leave"))
            for room_id, members in membership_by_room.items()
        }
        
        now = int(round(time.time() * 1000))
        ACTIVE_THRESHOLD = 1000 * 3600 * 24 * 7 # one week

        defer.returnValue(
            [ {
                'room_id': room_id,
                'creator': creator,
                'name': name,
                'members': members_by_room[room_id],
                'type': "Room" if (len(members_by_room[room_id]) >= 3) else "One to one",
                'active': 1 if last_received_ts and (now - last_received_ts < ACTIVE_THRESHOLD) else 0
            }
              for room_id, creator, name, last_received_ts in rooms
            ])


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
