# Copyright 2018-2021 The Matrix.org Foundation C.I.C.
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

from tests.unittest import HomeserverTestCase, override_config

ALICE = "@alice:a"
BOB = "@bob:b"
BOBBY = "@bobby:a"
# The localpart isn't 'Bela' on purpose so we can test looking up display names.
BELA = "@somenickname:a"


class UserDirectoryStoreTestCase(HomeserverTestCase):
    def prepare(self, reactor, clock, hs):
        self.store = hs.get_datastore()

        # alice and bob are both in !room_id. bobby is not but shares
        # a homeserver with alice.
        self.get_success(self.store.update_profile_in_user_dir(ALICE, "alice", None))
        self.get_success(self.store.update_profile_in_user_dir(BOB, "bob", None))
        self.get_success(self.store.update_profile_in_user_dir(BOBBY, "bobby", None))
        self.get_success(self.store.update_profile_in_user_dir(BELA, "Bela", None))
        self.get_success(self.store.add_users_in_public_rooms("!room:id", (ALICE, BOB)))

    def test_search_user_dir(self):
        # normally when alice searches the directory she should just find
        # bob because bobby doesn't share a room with her.
        r = self.get_success(self.store.search_user_dir(ALICE, "bob", 10))
        self.assertFalse(r["limited"])
        self.assertEqual(1, len(r["results"]))
        self.assertDictEqual(
            r["results"][0], {"user_id": BOB, "display_name": "bob", "avatar_url": None}
        )

    @override_config({"user_directory": {"search_all_users": True}})
    def test_search_user_dir_all_users(self):
        r = self.get_success(self.store.search_user_dir(ALICE, "bob", 10))
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

    @override_config({"user_directory": {"search_all_users": True}})
    def test_search_user_dir_stop_words(self):
        """Tests that a user can look up another user by searching for the start if its
        display name even if that name happens to be a common English word that would
        usually be ignored in full text searches.
        """
        r = self.get_success(self.store.search_user_dir(ALICE, "be", 10))
        self.assertFalse(r["limited"])
        self.assertEqual(1, len(r["results"]))
        self.assertDictEqual(
            r["results"][0],
            {"user_id": BELA, "display_name": "Bela", "avatar_url": None},
        )

    # watcha+
    skip_reason = "[watcha] reason: user directory modifications for partners & 3pids"
    test_search_user_dir.skip = skip_reason
    test_search_user_dir_all_users.skip = skip_reason
    test_search_user_dir_stop_words.skip = skip_reason
    # +watcha


# watcha+
USER = "@user:test"
USER_X = "@user_x:test"
USER_Y = "@user_y:test"
PARTNER = "@partner:test"


class WatchaUserDirectoryStoreTestCase(HomeserverTestCase):
    def prepare(self, reactor, clock, hs):
        self.registration_handler = self.hs.get_registration_handler()
        self.store = hs.get_datastore()
        self.time = int(hs.get_clock().time_msec())

        self.get_success(
            self.registration_handler.register_user(
                localpart="user_x",
                default_display_name="user_x",
                bind_emails=["user_x@example.com"],
            )
        )

        self.get_success(
            self.registration_handler.register_user(
                localpart="user_y",
                default_display_name="user_y",
                bind_emails=["user_y@example.com"],
            )
        )

        self.get_success(
            self.registration_handler.register_user(
                localpart="partner",
                default_display_name="partner",
                bind_emails=["partner@external.com"],
                make_partner=True,
            )
        )

        self.get_success(self.store.add_partner_invitation(PARTNER, USER))

        self.get_success(self.store.update_profile_in_user_dir(USER_X, "user_x", None))
        self.get_success(self.store.update_profile_in_user_dir(USER_Y, "user_y", None))
        self.get_success(
            self.store.update_profile_in_user_dir(PARTNER, "partner", None)
        )

    @override_config({"user_directory": {"search_all_users": True}})
    def test_search_user_dir_by_user_id(self):
        r = self.get_success(self.store.search_user_dir(USER, USER_X, 10))
        self.assertFalse(r["limited"])
        self.assertEqual(0, len(r["results"]))

    @override_config({"user_directory": {"search_all_users": True}})
    def test_search_user_dir_by_displayname(self):
        r = self.get_success(self.store.search_user_dir(USER, "user", 10))
        self.assertFalse(r["limited"])
        self.assertEqual(2, len(r["results"]))
        self.assertEquals(
            r["results"][0],
            {
                "user_id": USER_X,
                "display_name": "user_x",
                "avatar_url": None,
                "email": "user_x@example.com",
            },
        )
        self.assertEquals(
            r["results"][1],
            {
                "user_id": USER_Y,
                "display_name": "user_y",
                "avatar_url": None,
                "email": "user_y@example.com",
            },
        )

    @override_config({"user_directory": {"search_all_users": True}})
    def test_search_user_dir_by_email(self):
        r = self.get_success(self.store.search_user_dir(USER, "@example.com", 10))
        self.assertFalse(r["limited"])
        self.assertEqual(2, len(r["results"]))
        self.assertEquals(
            r["results"][0],
            {
                "user_id": USER_X,
                "display_name": "user_x",
                "avatar_url": None,
                "email": "user_x@example.com",
            },
        )
        self.assertEquals(
            r["results"][1],
            {
                "user_id": USER_Y,
                "display_name": "user_y",
                "avatar_url": None,
                "email": "user_y@example.com",
            },
        )

    @override_config({"user_directory": {"search_all_users": True}})
    def test_search_user_dir_with_user_invite_partner(self):
        r = self.get_success(self.store.search_user_dir(USER, "partner", 10))
        self.assertFalse(r["limited"])
        self.assertEqual(1, len(r["results"]))
        self.assertEquals(
            r["results"][0],
            {
                "user_id": PARTNER,
                "display_name": "partner",
                "avatar_url": None,
                "email": "partner@external.com",
            },
        )

    @override_config({"user_directory": {"search_all_users": True}})
    def test_search_user_dir_with_user_dont_invite_partner(self):
        r = self.get_success(self.store.search_user_dir(USER_X, "partner", 10))
        self.assertFalse(r["limited"])
        self.assertEqual(0, len(r["results"]))


# +watcha
