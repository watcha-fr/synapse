# -*- coding: utf-8 -*-

import time, json
import psutil
from collections import defaultdict
import inspect

from twisted.internet import defer

from ._base import SQLBaseStore

from synapse.util.caches.descriptors import cached, cachedInlineCallbacks
from synapse.api.constants import EventTypes, JoinRules
from synapse.storage.engines import PostgresEngine, Sqlite3Engine
from synapse.types import get_domain_from_id, get_localpart_from_id
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
    def _get_room_count_per_type(self):
        """List the rooms, with two or less members, and with three or more members.
        """

        members_by_room = yield self.members_by_room()

        # Get active rooms (message send last week in room):
        active_rooms = yield self._execute_sql(
            """
            SELECT DISTINCT room_id 
            FROM events
            WHERE type = "m.room.message"
                AND received_ts >= (
                    SELECT (strftime('%%s','now') || substr(strftime('%%f', 'now'),4)) - (3600 * 24 * 7 * 1000));
        """
        )
        active_rooms = [element[0] for element in active_rooms]

        # Get direct rooms (m.direct flag on account_data and with exactly two joinned or invited members):
        direct_rooms_by_member = yield self._simple_select_onecol(
            table="account_data",
            keyvalues={"account_data_type": "m.direct"},
            retcol="content",
        )

        direct_rooms = list(
            set(
                [
                    room
                    for row in direct_rooms_by_member
                    for member_rooms in json.loads(row).values()
                    for room in member_rooms
                    if room in members_by_room and len(members_by_room[room]) == 2
                ]
            )
        )

        # Get rooms (all rooms less personnal conversation):
        all_rooms = yield self._simple_select_onecol(
            table="rooms", keyvalues=None, retcol="room_id",
        )

        non_direct_rooms = [room for room in all_rooms if room not in direct_rooms]

        result = {
            "direct_rooms_count": len(direct_rooms),
            "direct_active_rooms_count": len(
                set(direct_rooms).intersection(active_rooms)
            ),
            "non_direct_rooms_count": len(non_direct_rooms),
            "non_direct_active_rooms_count": len(
                set(non_direct_rooms).intersection(active_rooms)
            ),
        }

        defer.returnValue(result)

    @defer.inlineCallbacks
    def watcha_user_list(self):

        FIELDS = ["user_id", "email_address", "display_name", "is_partner", "is_admin", "is_active"
                  "last_seen", "creation_ts"]

        SQL_USER_LIST = """
            SELECT 
                users.name
                , user_email.address
                , profiles.displayname
                , users.is_partner
                , users.admin
                , users.is_active
                , users_last_seen.last_seen
                , users.creation_ts
            FROM users
                LEFT JOIN
                    (SELECT
                        t.user_id
                        , t.address
                    FROM user_threepids AS t
                    WHERE t.medium = 'email') AS user_email
                    ON users.name = user_email.user_id
                LEFT JOIN
                    (SELECT
                        user_ips.user_id
                        , max(user_ips.last_seen) as last_seen
                    FROM user_ips
                    GROUP BY user_ips.user_id) as users_last_seen ON users_last_seen.user_id = users.name
                LEFT JOIN profiles ON users.name LIKE "@"||profiles.user_id||":%"
            GROUP BY users.name
        """

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
        room_memberships = yield self._execute_sql(
            """
            SELECT
                room_id
                , state_key
                , membership
            FROM current_state_events
            WHERE type = "m.room.member"
                AND (membership = "join" OR membership = "invite");
        """
        )

        membership_by_room = defaultdict(list)
        for room_id, user_id, membership in room_memberships:
            membership_by_room[room_id].append((user_id, membership))

        defer.returnValue(
            {
                room_id: list(
                    set(
                        user_id
                        for user_id, membership in members
                        if membership in ["join", "invite"]
                    )
                    - set(
                        user_id
                        for user_id, membership in members
                        if membership == "leave"
                    )
                )
                for room_id, members in membership_by_room.items()
            }
        )


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

    def watcha_update_user_role(self, user_id, role):
        if role == "member":
            return self._update_user(user_id, admin=0, is_partner=0)
        elif role == "admin":
            return self._update_user(user_id, admin=1, is_partner=0)
        elif role == "partner":
            return self._update_user(user_id, admin=0, is_partner=1)

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