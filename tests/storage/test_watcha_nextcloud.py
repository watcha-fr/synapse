from synapse.rest import admin
from synapse.rest.client.v1 import login
from tests import unittest


class NextcloudStorageTestCase(unittest.HomeserverTestCase):
    servlets = [
        admin.register_servlets,
        login.register_servlets,
    ]

    def prepare(self, reactor, clock, hs):
        self.store = hs.get_datastore()
        self.room_id = "room1"
        self.internal_share_id = 1
        self.public_link_share_id = 2

    def test_get_internal_share_id(self):
        self.get_success(
            self.store.register_internal_share(self.room_id, self.internal_share_id)
        )

        internal_share_id = self.get_success(
            self.store.get_internal_share_id(self.room_id)
        )

        self.assertEquals(internal_share_id, self.internal_share_id)

    def test_get_empty_internal_share_id(self):
        internal_share_id = self.get_success(self.store.get_internal_share_id(self.room_id))

        self.assertIsNone(internal_share_id)

    def test_get_public_link_share_id(self):
        self.get_success(
            self.store.register_public_link_share(self.room_id, self.public_link_share_id)
        )

        public_link_share_id = self.get_success(
            self.store.get_public_link_share_id(self.room_id)
        )

        self.assertEquals(public_link_share_id, self.public_link_share_id)

    def test_get_empty_public_link_share_id(self):
        public_link_share_id = self.get_success(self.store.get_public_link_share_id(self.room_id))

        self.assertIsNone(public_link_share_id)

    def test_delete_internal_share(self):
        self.get_success(
            self.store.register_internal_share(self.room_id, self.internal_share_id)
        )
        self.get_success(self.store.delete_internal_share(self.room_id))

        internal_share_id = self.get_success(self.store.get_internal_share_id(self.room_id))

        self.assertIsNone(internal_share_id)

    def test_delete_public_link_share(self):
        self.get_success(
            self.store.register_public_link_share(self.room_id, self.public_link_share_id)
        )
        self.get_success(self.store.delete_public_link_share(self.room_id))

        public_link_share_id = self.get_success(self.store.get_public_link_share_id(self.room_id))

        self.assertIsNone(public_link_share_id)

    def test_delete_all_shares(self):
        self.get_success(
            self.store.register_internal_share(self.room_id, self.internal_share_id)
        )
        self.get_success(
            self.store.get_public_link_share_id(self.room_id)
        )

        self.get_success(self.store.delete_all_shares(self.room_id))
        internal_share_id = self.get_success(
            self.store.get_internal_share_id(self.room_id)
        )
        public_link_share_id = self.get_success(
            self.store.get_public_link_share_id(self.room_id)
        )

        self.assertIsNone(internal_share_id)
        self.assertIsNone(public_link_share_id)
