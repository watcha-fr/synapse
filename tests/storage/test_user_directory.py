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
    test_search_user_dir.skip = (
        "Disabled for watcha because of user directory modification for partners"
    )
    test_search_user_dir_all_users.skip = (
        "Disabled for watcha because of user directory modification for partners"
    )
    test_search_user_dir_stop_words.skip = (
        "Disabled for watcha because of user directory modification for partners"
    )

    def test_search_user_dir_for_watcha(self):
        # This only tests that it's not crashing :) after our motifs.
        # There should be more tests !
        r = self.get_success(self.store.search_user_dir(ALICE, "bob", 10))
        self.assertFalse(r["limited"])
        self.assertEqual(0, len(r["results"]))

    # +watcha


# watcha+
class WatchaUserDirectoryStoreTestCase(HomeserverTestCase):
    def prepare(self, reactor, clock, hs):
        self.store = hs.get_datastore()
        self.user_id = "@user:test"
        self.searched_user = "@searched_user:test"
        self.partner_id = "@partner:test"
        self.time = int(hs.get_clock().time_msec())

        # Register a user who want to see other user on the user_directory :
        self.get_success(
            self.store.register_user(
                self.user_id, password_hash=None, create_profile_with_displayname=None
            )
        )

        # Register an active user who @user:test want to see :
        self.get_success(
            self.store.register_user(
                self.searched_user,
                password_hash=None,
                create_profile_with_displayname=None,
            )
        )

        # Register an active external partner :
        self.get_success(
            self.store.register_user(
                self.partner_id,
                password_hash=None,
                make_partner=True,
                create_profile_with_displayname=None,
            )
        )

    def test_search_user_dir_with_user_id(self):
        with self.assertLogs(
            "synapse.storage.databases.main.user_directory", level="INFO"
        ) as cm:
            sqlResult = self.get_success(
                self.store.search_user_dir(self.user_id, self.searched_user, 1)
            )
            self.assertIn(
                "INFO:synapse.storage.databases.main.user_directory:Searching with search term: %s"
                % repr(self.searched_user),
                "".join(cm.output),
            )

        self.assertFalse(sqlResult["limited"])
        self.assertEquals(
            sqlResult["results"],
            [],
        )

    def test_search_user_dir_with_email(self):
        self.get_success(
            self.store.user_add_threepid(
                self.searched_user, "email", "example@example.com", self.time, self.time
            )
        )
        sqlResult = self.get_success(
            self.store.search_user_dir(self.user_id, "example@example.com", 1)
        )

        self.assertEquals(
            sqlResult["results"],
            [
                {
                    "user_id": self.searched_user,
                    "deactivated": 0,
                    "is_partner": 0,
                    "display_name": None,
                    "avatar_url": None,
                    "presence": None,
                    "email": "example@example.com",
                }
            ],
        )

    def test_search_user_dir_with_displayname(self):
        self.get_success(
            self.store.update_profile_in_user_dir(self.searched_user, "user", None)
        )
        sqlResult = self.get_success(
            self.store.search_user_dir(self.user_id, "user", 1)
        )
        self.assertEquals(
            sqlResult["results"],
            [
                {
                    "user_id": self.searched_user,
                    "deactivated": 0,
                    "is_partner": 0,
                    "display_name": "user",
                    "avatar_url": None,
                    "presence": None,
                    "email": None,
                }
            ],
        )

    def test_search_user_dir_with_user_invite_partner(self):
        # User invite partner :
        self.get_success(
            self.store.add_partner_invitation(self.partner_id, self.user_id)
        )
        self.get_success(
            self.store.user_add_threepid(
                self.partner_id, "email", "partner@example.com", self.time, self.time
            )
        )

        sqlResult = self.get_success(
            self.store.search_user_dir(self.user_id, "partner@example.com", 1)
        )

        self.assertEquals(
            sqlResult["results"],
            [
                {
                    "user_id": self.partner_id,
                    "deactivated": 0,
                    "is_partner": 1,
                    "display_name": None,
                    "avatar_url": None,
                    "presence": "invited",
                    "email": "partner@example.com",
                }
            ],
        )

    def test_search_user_dir_with_user_dont_invite_partner(self):
        # User doesn't invite partner but want to see it on the user directory :

        sqlResult = self.get_success(
            self.store.search_user_dir(self.user_id, self.partner_id, 1)
        )
        self.assertEquals(sqlResult["results"], [])


# +watcha
