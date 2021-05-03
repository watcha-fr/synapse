import synapse.rest.admin
from synapse.rest.client.v1 import login, room
from tests import unittest


class AdministrationTestCase(unittest.HomeserverTestCase):

    servlets = [
        synapse.rest.admin.register_servlets,
        login.register_servlets,
        room.register_servlets,
    ]

    def prepare(self, reactor, clock, hs):
        self.administration_handler = hs.get_administration_handler()

        creator = self.register_user("creator", "pass")
        self.creator_tok = self.login("creator", "pass")
        self.room_id = self.helper.create_room_as(tok=self.creator_tok)

    def test_get_room_name(self):
        expected_room_name = "default room"
        self.helper.send_state(
            self.room_id,
            "m.room.name",
            {"name": expected_room_name},
            tok=self.creator_tok,
        )

        room_name = self.get_success(
            self.administration_handler.get_room_name(self.room_id)
        )

        self.assertEquals(room_name, expected_room_name)

    def test_get_empty_room_name(self):
        room_name = self.get_success(
            self.administration_handler.get_room_name(self.room_id)
        )

        self.assertIsNone(room_name)
