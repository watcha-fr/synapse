from twisted.internet import defer

from tests import unittest
from tests.utils import setup_test_homeserver


class NextcloudStorageTestCase(unittest.HomeserverTestCase):
    @defer.inlineCallbacks
    def setUp(self):
        hs = setup_test_homeserver(self.addCleanup)
        self.store = hs.get_datastore()
        self.room_id = "room1"
        self.directory_path = "/directory"
        self.share_id = 1

        # Set mapping between a room and a nextcloud directory :
        yield defer.ensureDeferred(
            self.store.bind(
                self.room_id, self.directory_path, self.share_id
            )
        )

    @defer.inlineCallbacks
    def test_get_room_mapping_with_nextcloud_directory(self):
        mapped_directory = yield defer.ensureDeferred(
            self.store.get_path_from_room_id(self.room_id)
        )
        share_id = yield defer.ensureDeferred(
            self.store.get_nextcloud_share_id_from_room_id(self.room_id)
        )

        self.assertEquals(mapped_directory, self.directory_path)
        self.assertEquals(share_id, self.share_id)

    @defer.inlineCallbacks
    def test_delete_room_nextcloud_mapping(self):
        yield defer.ensureDeferred(
            self.store.unbind(self.room_id)
        )
        mapped_directory = yield defer.ensureDeferred(
            self.store.get_path_from_room_id(self.room_id)
        )

        self.assertIsNone(mapped_directory)

        share_id = yield defer.ensureDeferred(
            self.store.get_nextcloud_share_id_from_room_id(self.room_id)
        )

        self.assertIsNone(share_id)

    @defer.inlineCallbacks
    def test_update_room_mapping_with_nextcloud_directory(self):
        new_directory_path = "/directory2"
        new_share_id = 2

        yield defer.ensureDeferred(
            self.store.bind(
                self.room_id, new_directory_path, new_share_id
            )
        )
        mapped_directory = yield defer.ensureDeferred(
            self.store.get_path_from_room_id(self.room_id)
        )

        self.assertEquals(mapped_directory, new_directory_path)

        share_id = yield defer.ensureDeferred(
            self.store.get_nextcloud_share_id_from_room_id(self.room_id)
        )

        self.assertEquals(share_id, new_share_id)
