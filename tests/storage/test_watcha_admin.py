# -*- coding: utf-8 -*-
# Copyright 2020 Watcha SAS
#
# This code is not licensed unless agreed with Watcha SAS.
#

from twisted.internet import defer
from tests import unittest
from tests.utils import setup_test_homeserver
from datetime import datetime


class WatchaAdminTestCase(unittest.TestCase):
    @defer.inlineCallbacks
    def setUp(self):
        hs = yield setup_test_homeserver(self.addCleanup)
        self.store = hs.get_datastore()
        self.time = int(hs.get_clock().time_msec())

    @defer.inlineCallbacks
    def test_watcha_user_list(self):

        register_users_list = [
            {
                "user_id": "@admin:test",
                "make_partner": False,
                "admin": True,
                "create_profile_with_displayname": None,
                "email": None,
            },
            {
                "user_id": "@active_user:test",
                "make_partner": False,
                "admin": False,
                "create_profile_with_displayname": "active_user",
                "email": "example@example.com",
            },
            {
                "user_id": "@partner:test",
                "make_partner": True,
                "admin": False,
                "create_profile_with_displayname": None,
                "email": None,
            },
            {
                "user_id": "@non_active_user:test",
                "make_partner": False,
                "admin": False,
                "create_profile_with_displayname": None,
                "email": None,
            },
        ]

        for user in register_users_list:
            yield self.store.register_user(
                user["user_id"],
                password_hash=None,
                make_partner=user["make_partner"],
                create_profile_with_displayname=user["create_profile_with_displayname"],
                admin=user["admin"],
            )

            if user["email"]:

                # Addition of email as threepids for @active_user:test :
                yield self.store.user_add_threepid(
                    "@active_user:test",
                    "email",
                    "example@example.com",
                    self.time,
                    self.time,
                )

        users_informations = yield self.store.watcha_user_list()

        # Sorted the register_users_list like the function watcha_user_list do it :
        register_users_list_sorted = sorted(
            register_users_list, key=lambda i: i["user_id"]
        )

        for user in register_users_list_sorted:
            user_index = register_users_list_sorted.index(user)
            self.assertEquals(user["user_id"], users_informations[user_index]["user_id"])
            self.assertEquals(
                user["make_partner"], users_informations[user_index]["is_partner"]
            )
            self.assertEquals(user["admin"], users_informations[user_index]["is_admin"])
            self.assertEquals(user["email"], users_informations[user_index]["email_address"])
            self.assertEquals(
                user["create_profile_with_displayname"],
                users_informations[user_index]["display_name"],
            )
            self.assertEquals(None, users_informations[user_index]["last_seen"])
            self.assertEquals(self.time, users_informations[user_index]["creation_ts"]*1000)

    @defer.inlineCallbacks
    def test_watcha_update_user_role(self):
        user_id = "@admin:test"
        yield self.store.register_user(user_id, admin=True)

        expected_values = [
            {"role": "partner", "values": {"is_partner": 1, "is_admin": 0}},
            {"role": "collaborator", "values": {"is_partner": 0, "is_admin": 0}},
            {"role": "administrator", "values": {"is_partner": 0, "is_admin": 1}},
        ]

        for element in expected_values:
            yield self.store.watcha_update_user_role(user_id, element["role"])
            is_partner = yield self.store.is_user_partner(user_id)
            is_admin = yield self.store.is_user_admin(user_id)
            self.assertEquals(is_partner, element["values"]["is_partner"])
            self.assertEquals(is_admin, element["values"]["is_admin"])

    @defer.inlineCallbacks
    def test_get_users_with_pending_invitation(self):

        register_users_list = [
            {
                "user_id": "@user1:test",
                "logged_user": False,
                "defined_password": False,
                "logged_with_defined_password": False,
            },
            {
                "user_id": "@user2:test",
                "logged_user": True,
                "defined_password": True,
                "logged_with_defined_password": False,
            },
            {
                "user_id": "@user3:test",
                "logged_user": True,
                "defined_password": True,
                "logged_with_defined_password": True,
            },
        ]

        for user in register_users_list:
            yield self.store.register_user(user["user_id"], "pass")

            if user["logged_user"]:
                yield self.store._execute_sql(
                    """
                        INSERT INTO user_ips(
                            user_id
                            , access_token
                            , device_id
                            , ip
                            , user_agent
                            , last_seen
                        )VALUES(
                            "%s"
                            , "access_token"
                            , "device_id"
                            , "ip"
                            , "user_agent"
                            , %s
                        );
                    """
                    % (user["user_id"], self.time)
                )

            if user["defined_password"]:
                yield self.store.store_device(
                    user["user_id"], "device_id", "Web setup account"
                )

            if user["logged_with_defined_password"]:
                yield self.store.update_device(
                    user["user_id"], "device_id", new_display_name="display_name"
                )

        users_with_pending_invitation = (
            yield self.store._get_users_with_pending_invitation()
        )

        self.assertEquals(users_with_pending_invitation, {"@user1:test", "@user2:test"})

    def test_get_server_state(self):

        server_state = self.store._get_server_state()
        self.assertEquals(len(server_state), 4)
        self.assertEquals(list(server_state.keys()), ["disk", "watcha_release", "upgrade_date", "install_date"])
        self.assertEquals(list(server_state["disk"].keys()), ["total", "used", "free", "percent"])

        for date in server_state:
            if date in ["upgrade_date", "install_date"]:
                error = False
                try:
                    datetime.strptime(server_state[date], "%d/%m/%Y")
                except:
                    error = True
                self.assertFalse(error)
