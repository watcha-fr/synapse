# Copyright 2014-2016 OpenMarket Ltd
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

"""Tests REST events for /profile paths."""
from typing import Any, Dict

from synapse.api.errors import Codes
from synapse.rest import admin
from synapse.rest.client import login, profile, room
from synapse.types import UserID

from tests import unittest


from urllib.parse import quote  # watcha+
from synapse.api.errors import SynapseError  # watcha+


class ProfileTestCase(unittest.HomeserverTestCase):

    servlets = [
        admin.register_servlets_for_client_rest_resource,
        login.register_servlets,
        profile.register_servlets,
        room.register_servlets,
    ]

    def make_homeserver(self, reactor, clock):
        self.hs = self.setup_test_homeserver()
        self.auth = self.hs.get_auth_handler()  # watcha+
        return self.hs

    def prepare(self, reactor, clock, hs):
        self.owner = self.register_user("owner", "pass")
        self.owner_tok = self.login("owner", "pass")
        self.other = self.register_user("other", "pass", displayname="Bob")
        self.time = self.hs.get_clock().time_msec()  # watcha+

    def test_get_displayname(self):
        res = self._get_displayname()
        self.assertEqual(res, "owner")

    def test_set_displayname(self):
        channel = self.make_request(
            "PUT",
            "/profile/%s/displayname" % (self.owner,),
            content={"displayname": "test"},
            access_token=self.owner_tok,
        )
        self.assertEqual(channel.code, 200, channel.result)

        res = self._get_displayname()
        self.assertEqual(res, "test")

    def test_set_displayname_noauth(self):
        channel = self.make_request(
            "PUT",
            "/profile/%s/displayname" % (self.owner,),
            content={"displayname": "test"},
        )
        self.assertEqual(channel.code, 401, channel.result)

    def test_set_displayname_too_long(self):
        """Attempts to set a stupid displayname should get a 400"""
        channel = self.make_request(
            "PUT",
            "/profile/%s/displayname" % (self.owner,),
            content={"displayname": "test" * 100},
            access_token=self.owner_tok,
        )
        self.assertEqual(channel.code, 400, channel.result)

        res = self._get_displayname()
        self.assertEqual(res, "owner")

    def test_get_displayname_other(self):
        res = self._get_displayname(self.other)
        self.assertEquals(res, "Bob")

    def test_set_displayname_other(self):
        channel = self.make_request(
            "PUT",
            "/profile/%s/displayname" % (self.other,),
            content={"displayname": "test"},
            access_token=self.owner_tok,
        )
        self.assertEqual(channel.code, 400, channel.result)

    def test_get_avatar_url(self):
        res = self._get_avatar_url()
        self.assertIsNone(res)

    def test_set_avatar_url(self):
        channel = self.make_request(
            "PUT",
            "/profile/%s/avatar_url" % (self.owner,),
            content={"avatar_url": "http://my.server/pic.gif"},
            access_token=self.owner_tok,
        )
        self.assertEqual(channel.code, 200, channel.result)

        res = self._get_avatar_url()
        self.assertEqual(res, "http://my.server/pic.gif")

    def test_set_avatar_url_noauth(self):
        channel = self.make_request(
            "PUT",
            "/profile/%s/avatar_url" % (self.owner,),
            content={"avatar_url": "http://my.server/pic.gif"},
        )
        self.assertEqual(channel.code, 401, channel.result)

    def test_set_avatar_url_too_long(self):
        """Attempts to set a stupid avatar_url should get a 400"""
        channel = self.make_request(
            "PUT",
            "/profile/%s/avatar_url" % (self.owner,),
            content={"avatar_url": "http://my.server/pic.gif" * 100},
            access_token=self.owner_tok,
        )
        self.assertEqual(channel.code, 400, channel.result)

        res = self._get_avatar_url()
        self.assertIsNone(res)

    def test_get_avatar_url_other(self):
        res = self._get_avatar_url(self.other)
        self.assertIsNone(res)

    def test_set_avatar_url_other(self):
        channel = self.make_request(
            "PUT",
            "/profile/%s/avatar_url" % (self.other,),
            content={"avatar_url": "http://my.server/pic.gif"},
            access_token=self.owner_tok,
        )
        self.assertEqual(channel.code, 400, channel.result)

    def _get_displayname(self, name=None):
        channel = self.make_request(
            "GET", "/profile/%s/displayname" % (name or self.owner,)
        )
        self.assertEqual(channel.code, 200, channel.result)
        return channel.json_body["displayname"]

    def _get_avatar_url(self, name=None):
        channel = self.make_request(
            "GET", "/profile/%s/avatar_url" % (name or self.owner,)
        )
        self.assertEqual(channel.code, 200, channel.result)
        return channel.json_body.get("avatar_url")

    @unittest.override_config({"max_avatar_size": 50})
    def test_avatar_size_limit_global(self):
        """Tests that the maximum size limit for avatars is enforced when updating a
        global profile.
        """
        self._setup_local_files(
            {
                "small": {"size": 40},
                "big": {"size": 60},
            }
        )

        channel = self.make_request(
            "PUT",
            f"/profile/{self.owner}/avatar_url",
            content={"avatar_url": "mxc://test/big"},
            access_token=self.owner_tok,
        )
        self.assertEqual(channel.code, 403, channel.result)
        self.assertEqual(
            channel.json_body["errcode"], Codes.FORBIDDEN, channel.json_body
        )

        channel = self.make_request(
            "PUT",
            f"/profile/{self.owner}/avatar_url",
            content={"avatar_url": "mxc://test/small"},
            access_token=self.owner_tok,
        )
        self.assertEqual(channel.code, 200, channel.result)

    @unittest.override_config({"max_avatar_size": 50})
    def test_avatar_size_limit_per_room(self):
        """Tests that the maximum size limit for avatars is enforced when updating a
        per-room profile.
        """
        self._setup_local_files(
            {
                "small": {"size": 40},
                "big": {"size": 60},
            }
        )

        room_id = self.helper.create_room_as(tok=self.owner_tok)

        channel = self.make_request(
            "PUT",
            f"/rooms/{room_id}/state/m.room.member/{self.owner}",
            content={"membership": "join", "avatar_url": "mxc://test/big"},
            access_token=self.owner_tok,
        )
        self.assertEqual(channel.code, 403, channel.result)
        self.assertEqual(
            channel.json_body["errcode"], Codes.FORBIDDEN, channel.json_body
        )

        channel = self.make_request(
            "PUT",
            f"/rooms/{room_id}/state/m.room.member/{self.owner}",
            content={"membership": "join", "avatar_url": "mxc://test/small"},
            access_token=self.owner_tok,
        )
        self.assertEqual(channel.code, 200, channel.result)

    @unittest.override_config({"allowed_avatar_mimetypes": ["image/png"]})
    def test_avatar_allowed_mime_type_global(self):
        """Tests that the MIME type whitelist for avatars is enforced when updating a
        global profile.
        """
        self._setup_local_files(
            {
                "good": {"mimetype": "image/png"},
                "bad": {"mimetype": "application/octet-stream"},
            }
        )

        channel = self.make_request(
            "PUT",
            f"/profile/{self.owner}/avatar_url",
            content={"avatar_url": "mxc://test/bad"},
            access_token=self.owner_tok,
        )
        self.assertEqual(channel.code, 403, channel.result)
        self.assertEqual(
            channel.json_body["errcode"], Codes.FORBIDDEN, channel.json_body
        )

        channel = self.make_request(
            "PUT",
            f"/profile/{self.owner}/avatar_url",
            content={"avatar_url": "mxc://test/good"},
            access_token=self.owner_tok,
        )
        self.assertEqual(channel.code, 200, channel.result)

    @unittest.override_config({"allowed_avatar_mimetypes": ["image/png"]})
    def test_avatar_allowed_mime_type_per_room(self):
        """Tests that the MIME type whitelist for avatars is enforced when updating a
        per-room profile.
        """
        self._setup_local_files(
            {
                "good": {"mimetype": "image/png"},
                "bad": {"mimetype": "application/octet-stream"},
            }
        )

        room_id = self.helper.create_room_as(tok=self.owner_tok)

        channel = self.make_request(
            "PUT",
            f"/rooms/{room_id}/state/m.room.member/{self.owner}",
            content={"membership": "join", "avatar_url": "mxc://test/bad"},
            access_token=self.owner_tok,
        )
        self.assertEqual(channel.code, 403, channel.result)
        self.assertEqual(
            channel.json_body["errcode"], Codes.FORBIDDEN, channel.json_body
        )

        channel = self.make_request(
            "PUT",
            f"/rooms/{room_id}/state/m.room.member/{self.owner}",
            content={"membership": "join", "avatar_url": "mxc://test/good"},
            access_token=self.owner_tok,
        )
        self.assertEqual(channel.code, 200, channel.result)

    def _setup_local_files(self, names_and_props: Dict[str, Dict[str, Any]]):
        """Stores metadata about files in the database.

        Args:
            names_and_props: A dictionary with one entry per file, with the key being the
                file's name, and the value being a dictionary of properties. Supported
                properties are "mimetype" (for the file's type) and "size" (for the
                file's size).
        """
        store = self.hs.get_datastore()

        for name, props in names_and_props.items():
            self.get_success(
                store.store_local_media(
                    media_id=name,
                    media_type=props.get("mimetype", "image/png"),
                    time_now_ms=self.clock.time_msec(),
                    upload_name=None,
                    media_length=props.get("size", 50),
                    user_id=UserID.from_string("@rin:test"),
                )
            )

    # watcha+
    def test_get_email_threepids(self):

        # Addition of email as a threepids :
        self.get_success(
            self.auth.add_threepid(self.owner, "email", "example@email.com", self.time)
        )

        channel = self.make_request("GET", "/profile/%s" % (quote(self.owner, safe="")))

        self.assertEqual(channel.code, 200)
        self.assertEqual(channel.json_body["email"], "example@email.com")

    def test_do_not_get_phone_threepids(self):

        # Addition of phone number as a threepids :
        self.get_success(
            self.auth.add_threepid(self.owner, "msisdn", "0612345678", self.time)
        )

        channel = self.make_request("GET", "/profile/%s" % (quote(self.owner, safe="")))

        self.assertEqual(channel.code, 200)
        self.assertRaises(SynapseError)

    def test_get_only_one_email_threepids(self):

        # Addition of two emails as a threepids :
        self.get_success(
            self.auth.add_threepid(self.owner, "email", "example@email.com", self.time)
        )
        self.get_success(
            self.auth.add_threepid(
                self.owner, "email", "second_example@email.com", self.time
            )
        )

        channel = self.make_request("GET", "/profile/%s" % (quote(self.owner, safe="")))

        self.assertEqual(channel.code, 200)
        self.assertRaises(SynapseError)

    # +watcha


class ProfilesRestrictedTestCase(unittest.HomeserverTestCase):

    servlets = [
        admin.register_servlets_for_client_rest_resource,
        login.register_servlets,
        profile.register_servlets,
        room.register_servlets,
    ]

    def make_homeserver(self, reactor, clock):

        config = self.default_config()
        config["require_auth_for_profile_requests"] = True
        config["limit_profile_requests_to_users_who_share_rooms"] = True
        self.hs = self.setup_test_homeserver(config=config)

        return self.hs

    def prepare(self, reactor, clock, hs):
        # User owning the requested profile.
        self.owner = self.register_user("owner", "pass")
        self.owner_tok = self.login("owner", "pass")
        self.profile_url = "/profile/%s" % (self.owner)

        # User requesting the profile.
        self.requester = self.register_user("requester", "pass")
        self.requester_tok = self.login("requester", "pass")

        self.room_id = self.helper.create_room_as(self.owner, tok=self.owner_tok)

    def test_no_auth(self):
        self.try_fetch_profile(401)

    def test_not_in_shared_room(self):
        self.ensure_requester_left_room()

        self.try_fetch_profile(403, access_token=self.requester_tok)

    def test_in_shared_room(self):
        self.ensure_requester_left_room()

        self.helper.join(room=self.room_id, user=self.requester, tok=self.requester_tok)

        self.try_fetch_profile(200, self.requester_tok)

    def try_fetch_profile(self, expected_code, access_token=None):
        self.request_profile(expected_code, access_token=access_token)

        self.request_profile(
            expected_code, url_suffix="/displayname", access_token=access_token
        )

        self.request_profile(
            expected_code, url_suffix="/avatar_url", access_token=access_token
        )

    def request_profile(self, expected_code, url_suffix="", access_token=None):
        channel = self.make_request(
            "GET", self.profile_url + url_suffix, access_token=access_token
        )
        self.assertEqual(channel.code, expected_code, channel.result)

    def ensure_requester_left_room(self):
        try:
            self.helper.leave(
                room=self.room_id, user=self.requester, tok=self.requester_tok
            )
        except AssertionError:
            # We don't care whether the leave request didn't return a 200 (e.g.
            # if the user isn't already in the room), because we only want to
            # make sure the user isn't in the room.
            pass


class OwnProfileUnrestrictedTestCase(unittest.HomeserverTestCase):

    servlets = [
        admin.register_servlets_for_client_rest_resource,
        login.register_servlets,
        profile.register_servlets,
    ]

    def make_homeserver(self, reactor, clock):
        config = self.default_config()
        config["require_auth_for_profile_requests"] = True
        config["limit_profile_requests_to_users_who_share_rooms"] = True
        self.hs = self.setup_test_homeserver(config=config)

        return self.hs

    def prepare(self, reactor, clock, hs):
        # User requesting the profile.
        self.requester = self.register_user("requester", "pass")
        self.requester_tok = self.login("requester", "pass")

    def test_can_lookup_own_profile(self):
        """Tests that a user can lookup their own profile without having to be in a room
        if 'require_auth_for_profile_requests' is set to true in the server's config.
        """
        channel = self.make_request(
            "GET", "/profile/" + self.requester, access_token=self.requester_tok
        )
        self.assertEqual(channel.code, 200, channel.result)

        channel = self.make_request(
            "GET",
            "/profile/" + self.requester + "/displayname",
            access_token=self.requester_tok,
        )
        self.assertEqual(channel.code, 200, channel.result)

        channel = self.make_request(
            "GET",
            "/profile/" + self.requester + "/avatar_url",
            access_token=self.requester_tok,
        )
        self.assertEqual(channel.code, 200, channel.result)
