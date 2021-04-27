from twisted.internet import defer

from tests import unittest
from tests.utils import setup_test_homeserver


class NextcloudStorageTestCase(unittest.HomeserverTestCase):
    @defer.inlineCallbacks
    def setUp(self):
        hs = setup_test_homeserver(self.addCleanup)
        self.store = hs.get_datastore()
        self.room_id = "room1"
        self.share_id = 1

        # Set mapping between a room and a nextcloud directory :
        yield defer.ensureDeferred(
            self.store.register_share(
                self.room_id, self.share_id
            )
        )

    @defer.inlineCallbacks
    def test_get_share_id(self):
        share_id = yield defer.ensureDeferred(
            self.store.get_share_id(self.room_id)
        )
        self.assertEquals(share_id, self.share_id)

    @defer.inlineCallbacks
    def test_delete_share(self):
        yield defer.ensureDeferred(
            self.store.delete_share(self.room_id)
        )
        share_id = yield defer.ensureDeferred(
            self.store.get_share_id(self.room_id)
        )

        self.assertIsNone(share_id)

    @defer.inlineCallbacks
    def test_update_group(self):
        new_share_id = 2

        yield defer.ensureDeferred(
            self.store.register_share(
                self.room_id, new_share_id
            )
        )
        share_id = yield defer.ensureDeferred(
            self.store.get_share_id(self.room_id)
        )

        self.assertEquals(share_id, new_share_id)
