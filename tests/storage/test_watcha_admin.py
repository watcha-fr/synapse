# -*- coding: utf-8 -*-
# Copyright 2020 Watcha SAS
#
# This code is not licensed unless agreed with Watcha SAS.
#

from twisted.internet import defer
from tests import unittest
from tests.utils import setup_test_homeserver


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
            self.assertEquals(user["user_id"], users_informations[user_index]["name"])
            self.assertEquals(
                user["make_partner"], users_informations[user_index]["is_partner"]
            )
            self.assertEquals(user["admin"], users_informations[user_index]["admin"])
            self.assertEquals(user["email"], users_informations[user_index]["email"])
            self.assertEquals(
                user["create_profile_with_displayname"],
                users_informations[user_index]["displayname"],
            )

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
