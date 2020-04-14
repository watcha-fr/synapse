# -*- coding: utf-8 -*-
# Copyright 2018 New Vector Ltd
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from twisted.internet import defer

from synapse.storage import UserDirectoryStore

from tests import unittest
from tests.utils import setup_test_homeserver

ALICE = "@alice:a"
BOB = "@bob:b"
BOBBY = "@bobby:a"


class UserDirectoryStoreTestCase(unittest.TestCase):
    @defer.inlineCallbacks
    def setUp(self):
        self.hs = yield setup_test_homeserver(self.addCleanup)
        self.store = UserDirectoryStore(self.hs.get_db_conn(), self.hs)

        # alice and bob are both in !room_id. bobby is not but shares
        # a homeserver with alice.
        yield self.store.update_profile_in_user_dir(ALICE, "alice", None)
        yield self.store.update_profile_in_user_dir(BOB, "bob", None)
        yield self.store.update_profile_in_user_dir(BOBBY, "bobby", None)
        yield self.store.add_users_in_public_rooms("!room:id", (ALICE, BOB))

    @defer.inlineCallbacks
    def test_search_user_dir(self):
        # normally when alice searches the directory she should just find
        # bob because bobby doesn't share a room with her.
        r = yield self.store.search_user_dir(ALICE, "bob", 10)
        self.assertFalse(r["limited"])
        self.assertEqual(1, len(r["results"]))
        self.assertDictEqual(
            r["results"][0], {"user_id": BOB, "display_name": "bob", "avatar_url": None}
        )

    @defer.inlineCallbacks
    def test_search_user_dir_all_users(self):
        self.hs.config.user_directory_search_all_users = True
        try:
            r = yield self.store.search_user_dir(ALICE, "bob", 10)
            self.assertFalse(r["limited"])
            self.assertEqual(2, len(r["results"]))
            self.assertDictEqual(
                r["results"][0],
                {"user_id": BOB, "display_name": "bob", "avatar_url": None},
            )
            self.assertDictEqual(
                r["results"][1],
                {"user_id": BOBBY, "display_name": "bobby", "avatar_url": None},
            )
        finally:
            self.hs.config.user_directory_search_all_users = False

    test_search_user_dir.skip = "Not working because of Watcha modification"
    test_search_user_dir_all_users.skip = "Not working because of Watcha modification"

    @defer.inlineCallbacks
    def test_search_user_dir_for_watcha(self):
        # This only tests that it's not crashing :) after our motifs.
        # There should be more tests !
        r = yield self.store.search_user_dir(ALICE, "bob", 10)
        self.assertFalse(r["limited"])
        self.assertEqual(0, len(r["results"]))

# Insertion for watcha
class WatchaUserDirectoryStoreTestCase(unittest.TestCase):
    @defer.inlineCallbacks
    def setUp(self):
        hs = yield setup_test_homeserver(self.addCleanup)
        self.store = hs.get_datastore()
        self.user_id = "@user:test"
        self.searched_user = "@searched_user:test"
        self.partner_id = "@partner:test"
        self.time = int(hs.get_clock().time_msec())

        # Register a user who want to see other user on the user_directory :
        yield self.store.register_user(
            self.user_id, password_hash=None, create_profile_with_displayname=None
        )

        # Register an active user who @user:test want to see :
        yield self.store.register_user(
            self.searched_user, password_hash=None, create_profile_with_displayname=None
        )

        # Register an active external partner :
        yield self.store.register_user(
            self.partner_id,
            password_hash=None,
            make_partner=True,
            create_profile_with_displayname=None,
        )

    @defer.inlineCallbacks
    def test_search_user_dir(self):
        with self.assertLogs("synapse.storage.user_directory", level="INFO") as cm:
            sqlResult = yield self.store.search_user_dir(
                self.user_id, self.searched_user, 1
            )
            self.assertIn(
                "INFO:synapse.storage.user_directory:Searching with search term: %s"
                % repr(self.searched_user),
                "".join(cm.output),
            )

        self.assertFalse(sqlResult["limited"])
        self.assertEquals(
            sqlResult["results"],
            [
                {
                    "user_id": self.searched_user,
                    "is_active": 1,
                    "is_partner": 0,
                    "display_name": None,
                    "avatar_url": None,
                    "presence": None,
                    "email": None,
                }
            ],
        )

    @defer.inlineCallbacks
    def test_search_user_dir_with_email(self):
        yield self.store.user_add_threepid(
            self.searched_user, "email", "example@example.com", self.time, self.time
        )
        sqlResult = yield self.store.search_user_dir(
            self.user_id, self.searched_user, 1
        )
        self.assertEquals(
            sqlResult["results"],
            [
                {
                    "user_id": self.searched_user,
                    "is_active": 1,
                    "is_partner": 0,
                    "display_name": None,
                    "avatar_url": None,
                    "presence": None,
                    "email": "example@example.com",
                }
            ],
        )

    @defer.inlineCallbacks
    def test_search_user_dir_with_displayname(self):
        yield self.store.update_profile_in_user_dir(self.searched_user, "user", None)
        sqlResult = yield self.store.search_user_dir(
            self.user_id, self.searched_user, 1
        )
        self.assertEquals(
            sqlResult["results"],
            [
                {
                    "user_id": self.searched_user,
                    "is_active": 1,
                    "is_partner": 0,
                    "display_name": "user",
                    "avatar_url": None,
                    "presence": None,
                    "email": None,
                }
            ],
        )

    @defer.inlineCallbacks
    def test_search_user_dir_with_user_invite_partner(self):
        # User invite partner :
        yield self.store.insert_partner_invitation(self.partner_id, self.user_id, 0, 0)

        sqlResult = yield self.store.search_user_dir(self.user_id, self.partner_id, 1)
        self.assertEquals(
            sqlResult["results"],
            [
                {
                    "user_id": self.partner_id,
                    "is_active": 1,
                    "is_partner": 1,
                    "display_name": None,
                    "avatar_url": None,
                    "presence": "invited",
                    "email": None,
                }
            ],
        )

    @defer.inlineCallbacks
    def test_search_user_dir_with_user_dont_invite_partner(self):
        # User doesn't invite partner but want to see it on the user directory :

        sqlResult = yield self.store.search_user_dir(self.user_id, self.partner_id, 1)
        self.assertEquals(sqlResult["results"], [])
# end of insertion
