# -*- coding: utf-8 -*-

import time, json, calendar, logging
from datetime import datetime
import psutil
from collections import defaultdict
import inspect

from twisted.internet import defer

from ._base import SQLBaseStore

from synapse.util.caches.descriptors import cached, cachedInlineCallbacks
from synapse.api.constants import EventTypes, JoinRules
from synapse.storage.engines import PostgresEngine, Sqlite3Engine
from synapse.types import get_domain_from_id, get_localpart_from_id

logger = logging.getLogger(__name__)

WATCHA_CONF_FILE_PATH = "/etc/watcha.conf"

def _caller_name():
    '''returns the name of the function calling the one calling this one'''
    try:
        return inspect.stack()[2][3]
    except IndexError:
        # seems to happen (related to iPython install ?)
        return "<unknown function>"

class WatchaAdminStore(SQLBaseStore):
    def __init__(self, db_conn, hs):
        super(WatchaAdminStore, self).__init__(db_conn, hs)

        self.clock = hs.get_clock()

    def _execute_sql(self, sql, *args):
        return self._execute(
            _caller_name(),
            None, sql, *args)

    @defer.inlineCallbacks
    def _get_active_rooms(self):
        """List rooms where the last message was sent than less a week ago"""

        active_rooms = yield self._execute_sql(
            """
            SELECT DISTINCT room_id 
            FROM events
            WHERE type = "m.room.message"
                AND received_ts >= (
                    SELECT (strftime('%s','now') || substr(strftime('%f', 'now'),4)) - (3600 * 24 * 7 * 1000));
        """
        )
        active_rooms = [rooms[0] for rooms in active_rooms]

        defer.returnValue(active_rooms)

    @defer.inlineCallbacks
    def _get_direct_rooms(self):
        """List rooms with m.direct flag on account_data and with exactly two joinned or invited members"""

        members_by_room = yield self.members_by_room()

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

        defer.returnValue(direct_rooms)

    @defer.inlineCallbacks
    def _get_room_count_per_type(self):
        """List the rooms, with two or less members, and with three or more members.
        """
        members_by_room = yield self.members_by_room()
        active_rooms = yield self._get_active_rooms()
        direct_rooms = yield self._get_direct_rooms()

        all_rooms = yield self._simple_select_onecol(
            table="rooms", keyvalues=None, retcol="room_id",
        )
        
        non_direct_rooms = set(all_rooms) & set(
            members_by_room.keys()
        ) - set(direct_rooms)

        result = {
            "direct_rooms_count": len(direct_rooms),
            "direct_active_rooms_count": len(
                set(direct_rooms).intersection(active_rooms)
            ),
            "non_direct_rooms_count": len(non_direct_rooms),
            "non_direct_active_rooms_count": len(
                non_direct_rooms.intersection(active_rooms)
            ),
        }

        defer.returnValue(result)

    @defer.inlineCallbacks
    def _get_users_stats(self):
        """Retrieve the count of users per role (members and partners) and some stats of connected users"""

        administrators_users = yield self._get_user_admin()

        collaborators_users = yield self._execute_sql(
        """
            SELECT COUNT(*) as count
            FROM users
            WHERE is_partner = 0
                AND admin = 0
        """
        )

        partner_users = yield self._execute_sql(
        """
            SELECT COUNT(*) as count
            FROM users
            WHERE is_partner = 1
                AND admin = 0
        """
        )

        last_seen_ts_per_users = yield self._execute_sql(
        """
            SELECT
                user_id
                , max(last_seen)
            FROM user_ips
            GROUP BY user_id;
        """
        )

        now = int(self.clock.time())
        now_datetime = datetime.fromtimestamp(now)

        MS_PER_DAY = 24 * 3600
        WEEK_TRESHOLD = (now - 7 * MS_PER_DAY)*1000
        MONTH_TRESHOLD = (now -
            calendar.monthrange(now_datetime.year, now_datetime.month)[1] * MS_PER_DAY
        )*1000

        number_of_collaborators = collaborators_users[0][0]
        number_of_partners = partner_users[0][0]
        number_of_administrators = len(administrators_users)

        last_month_logged_users = [
            user_ts[0] for user_ts in last_seen_ts_per_users if user_ts[1] > MONTH_TRESHOLD
        ]

        last_week_logged_users = [
            user_ts[0] for user_ts in last_seen_ts_per_users if user_ts[1] > WEEK_TRESHOLD
        ]

        users_with_pending_invitation = yield self._get_users_with_pending_invitation()

        defer.returnValue(
            {
                "administrators_users": administrators_users,
                "users_per_role": {
                    "administrators": number_of_administrators,
                    "collaborators": number_of_collaborators,
                    "partners": number_of_partners,
                },
                "connected_users": {
                    "number_of_users_logged_at_least_once": number_of_collaborators
                    + number_of_partners 
                    + number_of_administrators
                    - len(users_with_pending_invitation),
                    "number_of_last_month_logged_users": len(last_month_logged_users),
                    "number_of_last_week_logged_users": len(last_week_logged_users),
                },
                "other_statistics":{
                    "number_of_users_with_pending_invitation": len(users_with_pending_invitation),
                },
            }
        )

    def _get_server_state(self):
        result = {
            "disk": psutil.disk_usage("/")._asdict(),
            "watcha_release": "",
            "upgrade_date": "",
            "install_date": "",
        }

        try:
            with open(WATCHA_CONF_FILE_PATH, "r") as f:
                watcha_conf_content = f.read().splitlines()

        except FileNotFoundError:
            logger.info("No such file : %s" % WATCHA_CONF_FILE_PATH)
        else:
            def _parse_date(label, value):
                return datetime.strptime(value, "%Y-%m-%dT%H:%M:%S").strftime(
                        "%d/%m/%Y"
                    ) if ((label == "UPGRADE_DATE" or label == "INSTALL_DATE") and value) else value

            for value in ["WATCHA_RELEASE", "UPGRADE_DATE", "INSTALL_DATE"]:
                result[value.lower()] = [
                    _parse_date(line.split("=")[0], line.split("=")[1])
                    for line in watcha_conf_content
                    if value in line
                ][0]

        return result

    @defer.inlineCallbacks
    def watcha_user_list(self):

        FIELDS = ["user_id", "email_address", "display_name", "is_partner", "is_admin", "is_active",
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
                , users.creation_ts * 1000
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
    def watcha_room_list(self):
        """ List the rooms their state and their users """

        rooms = yield self._execute_sql(
            """
            SELECT
                rooms.room_id
                , rooms.creator
                , room_names.name
            FROM rooms
                LEFT JOIN (
                    SELECT
                        room_id
                        , event_id
                    FROM current_state_events
                    WHERE type = "m.room.name") as last_room_names
                    ON last_room_names.room_id = rooms.room_id
                LEFT JOIN room_names
                    ON room_names.event_id = last_room_names.event_id
            ORDER BY rooms.room_id ASC;
        """
        )

        members_by_room = yield self.members_by_room()
        active_rooms = yield self._get_active_rooms()
        direct_rooms = yield self._get_direct_rooms()

        defer.returnValue(
            [
                {
                    "room_id": room_id,
                    "creator": creator,
                    "name": name,
                    "members": members_by_room[room_id],
                    "type": "Personnal conversation" if room_id in direct_rooms else "Room",
                    "active": 1 if room_id in active_rooms else 0,
                }
                for room_id, creator, name in rooms
                if room_id
                in members_by_room  # don't show empty room (and avoid a possible exception)
            ]
        )


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
        if role == "collaborator":
            return self._update_user(user_id, admin=0, is_partner=0)
        elif role == "administrator":
            return self._update_user(user_id, admin=1, is_partner=0)
        elif role == "partner":
            return self._update_user(user_id, admin=0, is_partner=1)

    def watcha_deactivate_account(self, user_id):
        return self._update_user(user_id, is_active=0)

    def watcha_reactivate_account(self, user_id):
        return self._update_user(user_id, is_active=1)

    @defer.inlineCallbacks
    def watcha_get_user_status(self, user_id):
        users_with_pending_invitation = yield self._get_users_with_pending_invitation()

        if user_id in users_with_pending_invitation:
            result = "invited"
        else:
            is_active = yield self._simple_select_onecol(
                table="users", keyvalues={"name": user_id}, retcol="is_active",
            )

            result = "inactive" if is_active == 0 else "active"

        defer.returnValue(result)


    @defer.inlineCallbacks
    def _get_users_with_pending_invitation(self):
        never_logged_users = yield self._execute_sql(
        """
            SELECT
                users.name
            FROM users
            LEFT JOIN(
                    SELECT
                        user_ips.user_id
                        , max(user_ips.last_seen) as last_seen
                    FROM user_ips
                    GROUP BY user_ips.user_id) as logged_users
                ON logged_users.user_id = users.name
            WHERE logged_users.user_id is null
            ORDER BY users.name ASC;
        """
        )
        never_logged_users = [user[0] for user in never_logged_users]

        never_logged_users_with_defined_password = yield self._execute_sql(
        """
            SELECT distinct
                devices.user_id
            FROM devices
            LEFT JOIN (
                    SELECT DISTINCT
                        devices.user_id
                    FROM devices
                    WHERE devices.display_name != "Web setup account") as users_logged_with_password_defined
                ON users_logged_with_password_defined.user_id = devices.user_id
            WHERE users_logged_with_password_defined.user_id is null
                AND devices.display_name = "Web setup account"
            ORDER BY devices.user_id ASC;
        """
        )
        never_logged_users_with_defined_password = [user[0] for user in never_logged_users_with_defined_password]

        defer.returnValue(set(never_logged_users) | set(never_logged_users_with_defined_password))

    @defer.inlineCallbacks
    def _get_user_admin(self):
        admins = yield self._execute_sql(
            """
            SELECT
                users.name
                , user_emails.address
                , user_directory.display_name
            FROM users
                LEFT JOIN (
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
    def watcha_admin_stats(self):
        # ranges must be a list of arrays with three elements: label, start seconds since epoch, end seconds since epoch
        user_stats = yield self._get_users_stats()
        room_stats = yield self._get_room_count_per_type()
        server_stats = yield self._get_server_state()

        result = { 'users': user_stats,
                   'rooms': room_stats,
                   "server": server_stats,
        }

        defer.returnValue(result)
