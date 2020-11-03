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
from synapse.api.room_versions import RoomVersions
from synapse.types import RoomAlias, RoomID, UserID

from tests import unittest
from tests.utils import setup_test_homeserver

# watcha+
from synapse.api.errors import StoreError, SynapseError
from tests.utils import create_room

# +watcha


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

        yield defer.ensureDeferred(
            self.store.store_room(
                self.room.to_string(),
                room_creator_user_id=self.u_creator.to_string(),
                is_public=True,
                room_version=RoomVersions.V1,
            )
        )

    @defer.inlineCallbacks
    def test_get_room(self):
        self.assertDictContainsSubset(
            {
                "room_id": self.room.to_string(),
                "creator": self.u_creator.to_string(),
                "is_public": True,
            },
            (yield defer.ensureDeferred(self.store.get_room(self.room.to_string()))),
        )

    @defer.inlineCallbacks
    def test_get_room_unknown_room(self):
        self.assertIsNone(
            (yield defer.ensureDeferred(self.store.get_room("!uknown:test")))
        )

    @defer.inlineCallbacks
    def test_get_room_with_stats(self):
        self.assertDictContainsSubset(
            {
                "room_id": self.room.to_string(),
                "creator": self.u_creator.to_string(),
                "public": True,
            },
            (
                yield defer.ensureDeferred(
                    self.store.get_room_with_stats(self.room.to_string())
                )
            ),
        )

    @defer.inlineCallbacks
    def test_get_room_with_stats_unknown_room(self):
        self.assertIsNone(
            (
                yield defer.ensureDeferred(
                    self.store.get_room_with_stats("!uknown:test")
                )
            ),
        )


class RoomEventsStoreTestCase(unittest.TestCase):
    @defer.inlineCallbacks
    def setUp(self):
        hs = setup_test_homeserver(self.addCleanup)

        # Room events need the full datastore, for persist_event() and
        # get_room_state()
        self.store = hs.get_datastore()
        self.storage = hs.get_storage()
        self.event_factory = hs.get_event_factory()

        self.room = RoomID.from_string("!abcde:test")

        yield defer.ensureDeferred(
            self.store.store_room(
                self.room.to_string(),
                room_creator_user_id="@creator:text",
                is_public=True,
                room_version=RoomVersions.V1,
            )
        )

    @defer.inlineCallbacks
    def inject_room_event(self, **kwargs):
        yield defer.ensureDeferred(
            self.storage.persistence.persist_event(
                self.event_factory.create_event(room_id=self.room.to_string(), **kwargs)
            )
        )

    @defer.inlineCallbacks
    def STALE_test_room_name(self):
        name = "A-Room-Name"

        yield self.inject_room_event(
            etype=EventTypes.Name, name=name, content={"name": name}, depth=1
        )

        state = yield defer.ensureDeferred(
            self.store.get_current_state(room_id=self.room.to_string())
        )

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

        state = yield defer.ensureDeferred(
            self.store.get_current_state(room_id=self.room.to_string())
        )

        self.assertEquals(1, len(state))
        self.assertObjectHasAttributes(
            {"type": "m.room.topic", "room_id": self.room.to_string(), "topic": topic},
            state[0],
        )

    # Not testing the various 'level' methods for now because there's lots
    # of them and need coalescing; see JIRA SPEC-11


# watcha+
class WatchaRoomEventsStoreTestCase(unittest.HomeserverTestCase):
    @defer.inlineCallbacks
    def setUp(self):
        hs = setup_test_homeserver(self.addCleanup)
        self.store = hs.get_datastore()
        self.room_id = "room1"
        self.directory_path = "/directory"
        self.share_id = 1

        # Set mapping between a room and a nextcloud directory :
        yield defer.ensureDeferred(
            self.store.set_room_mapping_with_nextcloud_directory(
                self.room_id, self.directory_path, self.share_id
            )
        )

    @defer.inlineCallbacks
    def test_get_room_mapping_with_nextcloud_directory(self):
        mapped_directory = yield defer.ensureDeferred(
            self.store.get_nextcloud_directory_path_from_roomID(self.room_id)
        )
        mapped_room = yield defer.ensureDeferred(
            self.store.get_roomID_from_nextcloud_directory_path(self.directory_path)
        )
        share_id = yield defer.ensureDeferred(
            self.store.get_nextcloud_share_id_from_roomID(self.room_id)
        )

        self.assertEquals(mapped_directory, self.directory_path)
        self.assertEquals(mapped_room, self.room_id)
        self.assertEquals(share_id, self.share_id)

    @defer.inlineCallbacks
    def test_delete_room_nextcloud_mapping(self):
        yield defer.ensureDeferred(
            self.store.deleted_room_mapping_with_nextcloud_directory(self.room_id)
        )
        mapped_directory = yield defer.ensureDeferred(
            self.store.get_nextcloud_directory_path_from_roomID(self.room_id)
        )

        self.assertIsNone(mapped_directory)

        share_id = yield defer.ensureDeferred(
            self.store.get_nextcloud_share_id_from_roomID(self.room_id)
        )

        self.assertIsNone(share_id)

    @defer.inlineCallbacks
    def test_update_room_mapping_with_nextcloud_directory(self):
        new_directory_path = "/directory2"
        new_share_id = 2

        yield defer.ensureDeferred(
            self.store.set_room_mapping_with_nextcloud_directory(
                self.room_id, new_directory_path, new_share_id
            )
        )
        mapped_directory = yield defer.ensureDeferred(
            self.store.get_nextcloud_directory_path_from_roomID(self.room_id)
        )

        self.assertEquals(mapped_directory, new_directory_path)

        share_id = yield defer.ensureDeferred(
            self.store.get_nextcloud_share_id_from_roomID(self.room_id)
        )

        self.assertEquals(share_id, new_share_id)


# +watcha
