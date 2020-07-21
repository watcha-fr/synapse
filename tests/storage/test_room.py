# -*- coding: utf-8 -*-
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


from twisted.internet import defer

from synapse.api.constants import EventTypes
from synapse.api.errors import StoreError, SynapseError  # insertion for Watcha OP491
from synapse.api.room_versions import RoomVersions
from synapse.types import RoomAlias, RoomID, UserID

from tests import unittest
from tests.utils import create_room, setup_test_homeserver


class RoomStoreTestCase(unittest.TestCase):
    @defer.inlineCallbacks
    def setUp(self):
        hs = yield setup_test_homeserver(self.addCleanup)

        # We can't test RoomStore on its own without the DirectoryStore, for
        # management of the 'room_aliases' table
        self.store = hs.get_datastore()

        self.room = RoomID.from_string("!abcde:test")
        self.alias = RoomAlias.from_string("#a-room-name:test")
        self.u_creator = UserID.from_string("@creator:test")

        yield self.store.store_room(
            self.room.to_string(),
            room_creator_user_id=self.u_creator.to_string(),
            is_public=True,
        )

    @defer.inlineCallbacks
    def test_get_room(self):
        self.assertDictContainsSubset(
            {
                "room_id": self.room.to_string(),
                "creator": self.u_creator.to_string(),
                "is_public": True,
            },
            (yield self.store.get_room(self.room.to_string())),
        )


class RoomEventsStoreTestCase(unittest.TestCase):
    @defer.inlineCallbacks
    def setUp(self):
        hs = setup_test_homeserver(self.addCleanup)

        # Room events need the full datastore, for persist_event() and
        # get_room_state()
        self.store = hs.get_datastore()
        self.event_factory = hs.get_event_factory()

        self.room = RoomID.from_string("!abcde:test")

        yield self.store.store_room(
            self.room.to_string(), room_creator_user_id="@creator:text", is_public=True
        )

    @defer.inlineCallbacks
    def inject_room_event(self, **kwargs):
        yield self.store.persist_event(
            self.event_factory.create_event(room_id=self.room.to_string(), **kwargs)
        )

    @defer.inlineCallbacks
    def STALE_test_room_name(self):
        name = "A-Room-Name"

        yield self.inject_room_event(
            etype=EventTypes.Name, name=name, content={"name": name}, depth=1
        )

        state = yield self.store.get_current_state(room_id=self.room.to_string())

        self.assertEquals(1, len(state))
        self.assertObjectHasAttributes(
            {"type": "m.room.name", "room_id": self.room.to_string(), "name": name},
            state[0],
        )

    @defer.inlineCallbacks
    def STALE_test_room_topic(self):
        topic = "A place for things"

        yield self.inject_room_event(
            etype=EventTypes.Topic, topic=topic, content={"topic": topic}, depth=1
        )

        state = yield self.store.get_current_state(room_id=self.room.to_string())

        self.assertEquals(1, len(state))
        self.assertObjectHasAttributes(
            {"type": "m.room.topic", "room_id": self.room.to_string(), "topic": topic},
            state[0],
        )

    # Not testing the various 'level' methods for now because there's lots
    # of them and need coalescing; see JIRA SPEC-11


# insertion for watcha - OP433
class WatchaRoomEventsStoreTestCase(unittest.TestCase):
    @defer.inlineCallbacks
    def setUp(self):
        hs = yield setup_test_homeserver(self.addCleanup)

        self.store = hs.get_datastore()
        self.event_builder_factory = hs.get_event_builder_factory()
        self.event_creation_handler = hs.get_event_creation_handler()

        self.user = UserID.from_string("@user:test")
        self.room = RoomID.from_string("!abc123:test")
        self.second_room = RoomID.from_string("!abc456:test")
        self.nextcloud_folder_url = (
            "http://test.watcha.fr/nextcloud/apps/files/?dir=/Watcha-rooms/Test_NC"
        )

        yield create_room(hs, self.room.to_string(), self.user.to_string())
        yield create_room(hs, self.second_room.to_string(), self.user.to_string())
        yield self._send_room_mapping_event(
            self.room.to_string(), self.nextcloud_folder_url
        )

    @defer.inlineCallbacks
    def _send_room_mapping_event(self, room_id, nextcloud_folder_url):
        builder = self.event_builder_factory.for_room_version(
            RoomVersions.V1,
            {
                "type": EventTypes.VectorSetting,
                "sender": self.user.to_string(),
                "room_id": room_id,
                "content": {"nextcloud": nextcloud_folder_url},
            },
        )

        event, context = yield self.event_creation_handler.create_new_client_event(
            builder
        )

        yield self.store.persist_event(event, context)

    @defer.inlineCallbacks
    def test_get_room_link_with_NC(self):

        result = yield self.store._simple_select_onecol(
            table="room_mapping_with_NC",
            keyvalues={"room_id": self.room.to_string()},
            retcol="link_url",
        )

        self.assertEquals(result[0], self.nextcloud_folder_url)

    @defer.inlineCallbacks
    def test_update_room_link_with_NC(self):
        new_nextcloud_folder_url = (
            "http://test.watcha.fr/nextcloud/apps/files/?dir=/Watcha-rooms/Test_NC2"
        )
        yield self._send_room_mapping_event(
            self.room.to_string(), new_nextcloud_folder_url
        )

        result = yield self.store._simple_select_onecol(
            table="room_mapping_with_NC",
            keyvalues={"room_id": self.room.to_string()},
            retcol="link_url",
        )

        self.assertEquals(result[0], new_nextcloud_folder_url)

    @defer.inlineCallbacks
    def test_delete_room_link_with_NC(self):
        yield self._send_room_mapping_event(self.room.to_string(), "")

        result = yield self.store._simple_select_onecol(
            table="room_mapping_with_NC",
            keyvalues={"room_id": self.room.to_string()},
            retcol="link_url",
        )

        self.assertFalse(result)

    @defer.inlineCallbacks
    def test_set_same_link_in_another_room(self):
        with self.assertRaises(StoreError) as e:
            yield self._send_room_mapping_event(
                self.second_room.to_string(), self.nextcloud_folder_url
            )

        self.assertEquals(e.exception.code, 500)
        self.assertEquals(e.exception.msg, "This Nextcloud folder is already linked.")

    @defer.inlineCallbacks
    def test_set_link_with_wrong_url_query(self):
        with self.assertRaises(SynapseError) as e:
            yield self._send_room_mapping_event(
                self.second_room.to_string(),
                "http://test.watcha.fr/nextcloud/apps/files/?param",
            )

        self.assertEquals(e.exception.code, 400)
        self.assertEquals(
            e.exception.msg, "The url doesn't point to a valid directory path."
        )

    @defer.inlineCallbacks
    def test_set_link_with_directory_out_of_right_parent_directory(self):
        with self.assertRaises(SynapseError) as e:
            yield self._send_room_mapping_event(
                self.second_room.to_string(),
                "http://test.watcha.fr/nextcloud/apps/files/?dir=/Test_NC2",
            )

        self.assertEquals(e.exception.code, 400)
        self.assertEquals(
            e.exception.msg, "The url doesn't point to the right Watcha rooms parent directory."
        )

    @defer.inlineCallbacks
    def test_set_link_with_parent_directory(self):
        with self.assertRaises(SynapseError) as e:
            yield self._send_room_mapping_event(
                self.second_room.to_string(),
                "http://test.watcha.fr/nextcloud/apps/files/?dir=/Watcha-rooms",
            )

        self.assertEquals(e.exception.code, 400)
        self.assertEquals(
            e.exception.msg, "The url doesn't point to a room directory."
        )
# end of insertion
