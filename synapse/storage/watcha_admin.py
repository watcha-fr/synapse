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
import inspect

import logging

logger = logging.getLogger(__name__)

def _caller_name():
    '''returns the name of the function calling the one calling this one'''
    try:
        return inspect.stack()[2][3]
    except IndexError:
        # seems to happen (related to iPython install ?)
        return "<unknown function>"

class WatchaAdminStore(SQLBaseStore):

    def _execute_sql(self, sql, *args):
        return self._execute(
            _caller_name(),
            None, sql, *args)

    @defer.inlineCallbacks
    def get_room_count_per_type(self):
        """List the rooms, with two or less members, and with three or more members.
        """

        now = int(round(time.time() * 1000))
        ACTIVE_THRESHOLD = 1000 * 3600 * 24 * 7

        rooms = yield self._execute_sql("""
        SELECT rooms.room_id, last_events.last_received_ts FROM rooms
        LEFT JOIN (SELECT max(received_ts) last_received_ts, room_id FROM events
                   GROUP BY room_id HAVING type = "m.room.message") last_events
              ON last_events.room_id = rooms.room_id
        ORDER BY rooms.room_id ASC;
        """)

        members_by_room = yield self.members_by_room()

        room_details = {
            room_id: { 'three_or_more': 1 if len(members_by_room[room_id]) > 3 else 0,
                       'active': 1 if last_message_ts and (now - last_message_ts < ACTIVE_THRESHOLD) else 0
            }
            for room_id, last_message_ts in rooms
            if room_id in members_by_room # don't show empty room (and avoid a possible exception)
        }

        result = (
            {'now': now,
             'active_threshold': ACTIVE_THRESHOLD,
             "one_one_rooms_count": len([_ for _, counts in room_details.items() if counts['three_or_more']]),
             "big_rooms_count": len([_ for _, counts in room_details.items() if not counts['three_or_more']]),
             "big_rooms_count_active": len([_ for _, counts in room_details.items() if counts['active']]),
             "room_details": room_details
            })

        defer.returnValue(result)

    @defer.inlineCallbacks
    def watcha_user_list(self):
        FIELDS = ["name", "is_guest", "is_partner", "admin", "email",
                  "creation_ts", "is_active" , "displayname", "last_seen"]
        COLUMNS = FIELDS[:-1] + ["MAX(last_seen)"]
        SQL_USER_LIST = 'SELECT ' + ', '.join(COLUMNS) + ''' FROM users
        LEFT JOIN user_ips ON users.name = user_ips.user_id
        LEFT JOIN profiles ON users.name LIKE "@"||profiles.user_id||":%"
        GROUP BY users.name'''

        users = yield self._execute_sql(SQL_USER_LIST)

        defer.returnValue([dict(zip(FIELDS, user)) for user in users])

    @defer.inlineCallbacks
    def watcha_user_ip(self, user_id):

        user_ip = yield self._execute_sql("""
        SELECT ip, user_agent, last_seen FROM user_ips
        WHERE user_id = ?
        ORDER BY last_seen DESC
        """, user_id)

        defer.returnValue(user_ip)

    @defer.inlineCallbacks
    def members_by_room(self):
        # (Does not return empty rooms)
        room_memberships = yield self._execute_sql("""
        SELECT room_id, user_id, membership FROM room_memberships ORDER BY room_id, event_id ASC
        """)

        membership_by_room = defaultdict(list)
        for room_id, user_id, membership in room_memberships:
            membership_by_room[room_id].append((user_id, membership))

        defer.returnValue({
            room_id: list(set(user_id for user_id, membership in members if membership in ["join", "invite"])
                          -
                          set(user_id for user_id, membership in members if membership == "leave"))
            for room_id, members in membership_by_room.items()
        })


    @defer.inlineCallbacks
    def watcha_extend_room_list(self):
        """ List the rooms their state and their users """


        rooms = yield self._execute_sql("""
        SELECT rooms.room_id, rooms.creator, room_names.name, last_events.last_received_ts FROM rooms
        LEFT JOIN (SELECT max(event_id) event_id, room_id from room_names group by room_id) last_room_names
              ON rooms.room_id = last_room_names.room_id
        LEFT JOIN room_names on room_names.event_id = last_room_names.event_id
        LEFT JOIN (SELECT max(received_ts) last_received_ts, room_id FROM events
                   GROUP BY room_id HAVING type = "m.room.message") last_events
              ON last_events.room_id = rooms.room_id
        ORDER BY rooms.room_id ASC;
        """)

        members_by_room = yield self.members_by_room()

        now = int(round(time.time() * 1000))
        ACTIVE_THRESHOLD = 1000 * 3600 * 24 * 7 # one week

        defer.returnValue([
            {
                'room_id': room_id,
                'creator': creator,
                'name': name,
                'members': members_by_room[room_id],
                'type': "Room" if (len(members_by_room[room_id]) >= 3) else "One to one",
                'active': 1 if last_received_ts and (now - last_received_ts < ACTIVE_THRESHOLD) else 0
            }
            for room_id, creator, name, last_received_ts in rooms
            if room_id in members_by_room # don't show empty room (and avoid a possible exception)
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
        return {
            'disk': psutil.disk_usage('/')._asdict(),
            'memory': {
                'memory': psutil.virtual_memory()._asdict(),
                'swap': psutil.swap_memory()._asdict()
            },
            'cpu': {
                'average': psutil.cpu_percent(interval=1),
                'detailed': psutil.cpu_percent(interval=1, percpu=True),
            }
        }

    def watcha_room_name(self):
        return self._simple_select_list(
            table="room_names",
            keyvalues={},
            retcols=[
                "name",
                "room_id",
            ],
            desc="get_rooms",
        )

    def _update_user(self, user_id, **updatevalues):
        return self._simple_update(
            table="users",
            keyvalues={ 'name': user_id },
            updatevalues=updatevalues,
            desc=_caller_name(),
        )

    def watcha_update_mail(self, user_id, email):
        return self._update_user(user_id, email=email)

    def watcha_update_to_member(self, user_id):
        return self._update_user(user_id, is_partner=0)

    def watcha_deactivate_account(self, user_id):
        return self._update_user(user_id, is_active=0)


    def watcha_reactivate_account(self, user_id):
        return self._update_user(user_id, is_active=1)

    @defer.inlineCallbacks
    def get_user_admin(self):
        admins = yield self._execute_sql("SELECT name FROM users WHERE admin = 1")
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

        result = { 'users': user_stats,
                   'rooms': room_stats,
                   'admins': user_admin,
                   'version':synapse_version
        }

        defer.returnValue(result)
