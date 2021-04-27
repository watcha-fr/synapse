from tests import unittest


class NextcloudStorageTestCase(unittest.HomeserverTestCase):
    def prepare(self, reactor, clock, hs):
        self.store = hs.get_datastore()
        self.room_id = "room1"
        self.share_id = 1

        self.get_success(self.store.register_share(self.room_id, self.share_id))

    def test_get_share_id(self):
        share_id = self.get_success(self.store.get_share_id(self.room_id))
        self.assertEquals(share_id, self.share_id)

    def test_delete_share(self):
        self.get_success(self.store.delete_share(self.room_id))
        share_id = self.get_success(self.store.get_share_id(self.room_id))

        self.assertIsNone(share_id)

    def test_update_group(self):
        new_share_id = 2

        self.get_success(self.store.register_share(self.room_id, new_share_id))
        share_id = self.get_success(self.store.get_share_id(self.room_id))

        self.assertEquals(share_id, new_share_id)
