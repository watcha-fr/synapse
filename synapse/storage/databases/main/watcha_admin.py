# -*- coding: utf-8 -*-

import time, json, calendar, logging
from datetime import datetime
import psutil
from collections import defaultdict
import inspect

from synapse.storage._base import SQLBaseStore
from synapse.storage.database import DatabasePool

logger = logging.getLogger(__name__)

WATCHA_CONF_FILE_PATH = "/etc/watcha.conf"


def _caller_name():
    """returns the name of the function calling the one calling this one"""
    try:
        return inspect.stack()[2][3]
    except IndexError:
        # seems to happen (related to iPython install ?)
        return "<unknown function>"


class AdministrationStore(SQLBaseStore):
    def __init__(self, database: DatabasePool, db_conn, hs):
        super().__init__(database, db_conn, hs)

        self.clock = hs.get_clock()

    async def _get_new_rooms(self):
        """Retrieve a list of rooms that have recevied m.room.create event during the last week
        
        Returns:
            A list of room_id
        """

        def _get_new_rooms_txn(txn):
            txn.execute(
                """
                SELECT DISTINCT room_id
                FROM events
                WHERE type = "m.room.create"
                    AND received_ts >= (SELECT (strftime('%s','now') || substr(strftime('%f', 'now'),4)) - (3600 * 24 * 7 * 1000));
            """
            )

            return [rooms[0] for rooms in txn.fetchall()]

        return await self.db_pool.runInteraction("_get_new_rooms", _get_new_rooms_txn)

    async def _get_active_rooms(self):
        """Retrieve a list of rooms that have recevied some message during the last week
        
        Returns:
            A list of room_id
        """

        def _get_active_rooms_txn(txn):
            txn.execute(
                """
                SELECT DISTINCT room_id
                FROM events
                WHERE type = "m.room.message"
                    AND received_ts >= (
                        SELECT (strftime('%s','now') || substr(strftime('%f', 'now'),4)) - (3600 * 24 * 7 * 1000));
            """
            )

            return [rooms[0] for rooms in txn.fetchall()]

        return await self.db_pool.runInteraction("_get_active_rooms", _get_active_rooms_txn)

    async def _get_dm_rooms(self):
        """Retrieve a list of rooms that have m.direct flag on account_data and with exactly two joinned or invited members

        Returns:
            A list of room_id
        """
        members_by_room = await self.members_by_room()

        dm_rooms_by_member = await self.db_pool.simple_select_onecol(
            table="account_data",
            keyvalues={"account_data_type": "m.direct"},
            retcol="content",
        )

        dm_rooms = list(
            set(
                [
                    room
                    for row in dm_rooms_by_member
                    for member_rooms in json.loads(row).values()
                    for room in member_rooms
                    if room in members_by_room and len(members_by_room[room]) == 2
                ]
            )
        )

        return dm_rooms

    async def _get_room_count_per_type(self):
        """Retrieve a dict of number of active and non active rooms per type (direct message room, regular room).

        Returns:
            A dict of integers
        """
        members_by_room = await self.members_by_room()
        dm_rooms = await self._get_dm_rooms()
        new_rooms = await self._get_new_rooms()
        active_rooms = await self._get_active_rooms()

        active_rooms = set(active_rooms).union(new_rooms)

        all_rooms = await self.db_pool.simple_select_onecol(
            table="rooms", keyvalues=None, retcol="room_id",
        )

        regular_rooms = set(all_rooms) & set(members_by_room.keys()) - set(dm_rooms)

        result = {
            "dm_room_count": len(dm_rooms),
            "active_dm_room_count": len(set(dm_rooms).intersection(active_rooms)),
            "regular_room_count": len(regular_rooms),
            "active_regular_room_count": len(regular_rooms.intersection(active_rooms)),
        }

        return result

    async def _get_users_stats(self):
        """Retrieve the count of users per role (administrators, members and partners) and some stats about activity of users and pending invitations
        
        Used for Watcha admin console.
        
        Returns:
            A dict of integers
        """

        administrators_users = await self._get_user_admin()
        number_of_administrators = len(administrators_users)

        now = int(self.clock.time())
        now_datetime = datetime.fromtimestamp(now)

        MS_PER_DAY = 24 * 3600
        WEEK_TRESHOLD = (now - 7 * MS_PER_DAY) * 1000
        MONTH_TRESHOLD = (
            now
            - calendar.monthrange(now_datetime.year, now_datetime.month)[1] * MS_PER_DAY
        ) * 1000

        def _get_users_stats_txn(txn):
            txn.execute(
                """
                SELECT COUNT(*) as count
                FROM users
                WHERE is_partner = 0
                    AND admin = 0
                    AND deactivated = 0
            """
            )
            collaborators_users = txn.fetchone()

            txn.execute(
                """
                SELECT COUNT(*) as count
                FROM users
                WHERE is_partner = 1
                    AND admin = 0
                    AND deactivated = 0
            """
            )
            partner_users = txn.fetchone()

            txn.execute(
                """
                SELECT
                    user_id
                    , max(last_seen)
                FROM user_ips
                GROUP BY user_id;
            """
            )
            last_seen_ts_per_users = txn.fetchall()

            return collaborators_users, partner_users, last_seen_ts_per_users

        users = await self.db_pool.runInteraction("_get_users_stats", _get_users_stats_txn)

        number_of_collaborators = users[0][0]
        number_of_partners = users[1][0]
        last_seen_ts_per_users = users[2]

        last_month_logged_users = [
            user_ts[0]
            for user_ts in last_seen_ts_per_users
            if user_ts[1] > MONTH_TRESHOLD
        ]

        last_week_logged_users = [
            user_ts[0]
            for user_ts in last_seen_ts_per_users
            if user_ts[1] > WEEK_TRESHOLD
        ]

        users_with_pending_invitation = await self._get_users_with_pending_invitation()

        return {
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
            "other_statistics": {
                "number_of_users_with_pending_invitation": len(
                    users_with_pending_invitation
                ),
            },
        }

    async def _get_server_state(self):
        """Retrieve informations about server (disk usage, install and upgrade date, version)
        
        Used for Watcha admin console.
        
        Returns:
            A dict of strings
        """

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
                return (
                    datetime.strptime(value, "%Y-%m-%dT%H:%M:%S").strftime("%d/%m/%Y")
                    if ((label == "UPGRADE_DATE" or label == "INSTALL_DATE") and value)
                    else value
                )

            for value in ["WATCHA_RELEASE", "UPGRADE_DATE", "INSTALL_DATE"]:
                result[value.lower()] = [
                    _parse_date(line.split("=")[0], line.split("=")[1])
                    for line in watcha_conf_content
                    if value in line
                ][0]

        return result

    async def watcha_user_list(self):
        """Retrieve a list of all users with some informations.

        Used for Watcha admin console.

        Returns:
            A list of tuples which contains users informations
        """

        users_with_pending_invitation = await self._get_users_with_pending_invitation()

        def watcha_user_list_txn(txn):
            FIELDS = [
                "user_id",
                "email_address",
                "display_name",
                "is_partner",
                "is_admin",
                "status",
                "last_seen",
                "creation_ts",
            ]

            SQL_USER_LIST = """
                SELECT
                    users.name
                    , user_email.address
                    , profiles.displayname
                    , users.is_partner
                    , users.admin
                    , users.deactivated
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
                    WHERE users.deactivated = 0
                GROUP BY users.name
            """

            txn.execute(SQL_USER_LIST)
            result = txn.fetchall()

            return [dict(zip(FIELDS, user)) for user in result]

        users = await self.db_pool.runInteraction("watcha_user_list", watcha_user_list_txn)

        for user in users:
            user["status"] = (
                "inactive"
                if user["status"] == 0
                else "invited"
                if user["user_id"] in users_with_pending_invitation
                else "active"
            )
        return users

    async def watcha_email_list(self):
        """Retrieve a list of couple user_id/email of al users.

        Used for Watcha admin console.

        Returns:
            A list of tuples which contains user_id and email values for each users.
        """

        def watcha_email_list_txn(txn):
            SQL_EMAIL_LIST = """
                SELECT
                    user_threepids.user_id
                    , user_threepids.address
                FROM user_threepids
                WHERE medium = "email"
                """

            txn.execute(SQL_EMAIL_LIST)

            return txn.fetchall()

        return await self.db_pool.runInteraction("watcha_email_list", watcha_email_list_txn)

    async def watcha_user_ip(self, user_id):
        def watcha_user_ip_txn(txn):
            txn.execute(
                """
                SELECT ip
                    , user_agent
                    , last_seen 
                FROM user_ips
                WHERE user_id = ?
                ORDER BY last_seen DESC
                """,
                (user_id,),
            )

            return txn.fetchall()

        return await self.db_pool.runInteraction("watcha_user_ip", watcha_user_ip_txn)

    async def members_by_room(self):
        """Retrieve a list of all users with membership 'join' or 'invite' for each rooms.

        Does not concerned empty rooms.

        Returns:
            A dict with room_id as key and list of user_id as value.
        """

        def members_by_room_txn(txn):
            txn.execute(
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

            return txn.fetchall()

        room_memberships = await self.db_pool.runInteraction(
            "members_by_room", members_by_room_txn
        )
        membership_by_room = defaultdict(list)
        for room_id, user_id, membership in room_memberships:
            membership_by_room[room_id].append((user_id, membership))

        return {
            room_id: list(
                set(
                    user_id
                    for user_id, membership in members
                    if membership in ["join", "invite"]
                )
                - set(
                    user_id for user_id, membership in members if membership == "leave"
                )
            )
            for room_id, members in membership_by_room.items()
        }

    async def watcha_room_list(self):
        """Retrieve a list of rooms with some informations for each one (room_id, creator, name, members, type and status).

        Used for Watcha admin console. 

        Returns:
            A list of dict for each rooms.
        """

        def watcha_room_list_txn(txn):
            txn.execute(
                """
                SELECT
                    rooms.room_id
                    , rooms.creator
                    , room_stats_state.name
                FROM rooms
                    LEFT JOIN room_stats_state
                        ON room_stats_state.room_id = rooms.room_id
                ORDER BY rooms.room_id ASC;
            """
            )

            return txn.fetchall()

        rooms = await self.db_pool.runInteraction("watcha_room_list", watcha_room_list_txn)
        members_by_room = await self.members_by_room()
        new_rooms = await self._get_new_rooms()
        active_rooms = await self._get_active_rooms()
        dm_rooms = await self._get_dm_rooms()

        return [
            {
                "room_id": room_id,
                "creator": creator,
                "name": name,
                "members": members_by_room[room_id],
                "type": "dm_room" if room_id in dm_rooms else "regular_room",
                "status": "new"
                if room_id in new_rooms
                else "active"
                if room_id in active_rooms
                else "inactive",
            }
            for room_id, creator, name in rooms
            if room_id
            in members_by_room  # don't show empty room (and avoid a possible exception)
        ]

    async def watcha_room_membership(self):
        return await self.db_pool.simple_select_list(
            table="room_memberships",
            keyvalues={},
            retcols=["room_id", "user_id", "membership"],
            desc="get_rooms",
        )

    async def _update_user(self, user_id, **updatevalues):
        return await self.db_pool.simple_update(
            table="users",
            keyvalues={"name": user_id},
            updatevalues=updatevalues,
            desc=_caller_name(),
        )

    async def watcha_update_mail(self, user_id, email):
        return await self._update_user(user_id, email=email)

    async def watcha_update_user_role(self, user_id, role):
        if role == "collaborator":
            return await self._update_user(user_id, admin=0, is_partner=0)
        elif role == "administrator":
            return await self._update_user(user_id, admin=1, is_partner=0)
        elif role == "partner":
            return await self._update_user(user_id, admin=0, is_partner=1)

    async def watcha_deactivate_account(self, user_id):
        return await self._update_user(user_id, is_active=0)

    async def watcha_reactivate_account(self, user_id):
        return await self._update_user(user_id, is_active=1)

    async def _get_users_with_pending_invitation(self):
        """Retrieve a list of users who have a pending invitation.

        Used for Watcha admin console.

        Returns:
            A set of user_id.
        """

        def _get_users_with_pending_invitation_txn(txn):
            txn.execute(
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
            never_logged_users = [user[0] for user in txn.fetchall()]

            txn.execute(
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
            never_logged_users_with_defined_password = [
                user[0] for user in txn.fetchall()
            ]

            return set(never_logged_users) | set(
                never_logged_users_with_defined_password
            )

        return await self.db_pool.runInteraction(
            "_get_users_with_pending_invitation",
            _get_users_with_pending_invitation_txn,
        )

    async def _get_user_admin(self):
        def _get_user_admin_txn(txn):
            txn.execute(
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
                WHERE users.admin = 1 
                    AND users.deactivated = 0;
            """
            )

            return txn.fetchall()

        admins = await self.db_pool.runInteraction("_get_user_admin", _get_user_admin_txn)
        admins = [
            {"user_id": element[0], "email": element[1], "displayname": element[2]}
            for element in admins
        ]

        return admins

    async def watcha_admin_stats(self):
        user_stats = await self._get_users_stats()
        room_stats = await self._get_room_count_per_type()
        server_stats = await self._get_server_state()

        return {
            "users": user_stats,
            "rooms": room_stats,
            "server": server_stats,
        }
