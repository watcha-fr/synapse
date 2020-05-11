# -*- coding: utf-8 -*-

import time
import psutil
from collections import defaultdict
import inspect

from twisted.internet import defer

from ._base import SQLBaseStore

from synapse.util.caches.descriptors import cached, cachedInlineCallbacks
from synapse.api.constants import EventTypes, JoinRules
from synapse.storage.engines import PostgresEngine, Sqlite3Engine
from synapse.types import get_domain_from_id, get_localpart_from_id

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
    def _get_room_count_per_type(self):
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
        SQL_USER_LIST = '''
            SELECT 
                users.name
                , users.is_guest
                , users.is_partner
                , users.admin
                , user_email.address
                , users.creation_ts
                , users.is_active
                , profiles.displayname
                , user_ips.last_seen
            FROM users
                LEFT JOIN
                    (SELECT
                        t.user_id
                        , t.address
                    FROM user_threepids AS t
                    WHERE t.medium = 'email') AS user_email
                    ON users.name = user_email.user_id
                LEFT JOIN user_ips ON users.name = user_ips.user_id
                LEFT JOIN profiles ON users.name LIKE "@"||profiles.user_id||":%"
            GROUP BY users.name
            '''

        users = yield self._execute_sql(SQL_USER_LIST)

        defer.returnValue([dict(zip(FIELDS, user)) for user in users])

    @defer.inlineCallbacks
    def watcha_email_list(self):

        SQL_EMAIL_LIST = """
            SELECT
                user_threepids.user_id
                , user_threepids.address
            FROM user_threepids
            WHERE medium = "email"
            """

        emails = yield self._execute_sql(SQL_EMAIL_LIST)

        defer.returnValue(emails)

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
    def _get_user_admin(self):
        admins = yield self._execute_sql(
            """
            SELECT
                users.name
                , user_emails.address
                , user_directory.display_name
            FROM users
                INNER JOIN (
                    SELECT
                        user_threepids.user_id
                        , user_threepids.address
                    FROM user_threepids
                    WHERE user_threepids.medium = "email") AS user_emails
                    ON user_emails.user_id = users.name
            LEFT JOIN user_directory ON users.name = user_directory.user_id
            WHERE users.admin = 1;
        """
        )

        admins = [
            {"user_id": element[0], "email": element[1], "displayname": element[2]}
            for element in admins
        ]

        defer.returnValue(admins)

    @defer.inlineCallbacks
    def _get_range_count(self, where_clause, time_range):
        value = yield self._execute_sql('SELECT count(*) FROM events WHERE ' +
                                        where_clause +
                                        ' AND received_ts BETWEEN %d AND %d' %
                                        (int(time_range[1])*1000, int(time_range[2])*1000))
        defer.returnValue(value[0][0])

    @defer.inlineCallbacks
    def watcha_admin_stats(self, ranges=None):
        # ranges must be a list of arrays with three elements: label, start seconds since epoch, end seconds since epoch
        user_stats = yield self.get_count_users_partners()
        room_stats = yield self._get_room_count_per_type()
        user_admin = yield self._get_user_admin()

        result = { 'users': user_stats,
                   'rooms': room_stats,
                   'admins': user_admin,
        }

        if ranges:
            result['stats'] = []
            for index, time_range in enumerate(ranges):
                message_count = yield self._get_range_count("type = 'm.room.message'", time_range)
                file_count = yield self._get_range_count("type='m.room.message' AND content NOT LIKE '%m.text%'", time_range)
                create_room_count = yield self._get_range_count("type = 'm.room.create'", time_range)
                result['stats'].append({
                    'label': time_range[0],
                    'message_count': message_count,
                    'file_count': file_count,
                    'create_room_count': create_room_count,
                })

        defer.returnValue(result)
