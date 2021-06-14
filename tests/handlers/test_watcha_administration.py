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

        self.creator = self.register_user("creator", "pass")
        self.second_user = self.register_user("second_user", "pass")
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
            self.administration_handler.calculate_room_name(self.room_id)
        )

        self.assertEquals(room_name, expected_room_name)

    def test_get_empty_room_name(self):
        self.helper.send_state(
            self.room_id,
            "m.room.name",
            {"name": ""},
            tok=self.creator_tok,
        )

        room_name = self.get_success(
            self.administration_handler.calculate_room_name(self.room_id)
        )

        self.assertEquals(room_name, "creator")

    def test_get_unspecified_room_name_with_one_member(self):
        room_name = self.get_success(
            self.administration_handler.calculate_room_name(self.room_id)
        )

        self.assertEquals(room_name, "creator")

    def test_get_unspecified_room_name_with_two_members(self):
        self.helper.invite(
            self.room_id, self.creator, self.second_user, tok=self.creator_tok
        )
        room_name = self.get_success(
            self.administration_handler.calculate_room_name(self.room_id)
        )

        self.assertEquals(room_name, "creator and second_user")

    def test_get_unspecified_room_name_with_many_members(self):
        third_user = self.register_user("third_user", "pass")
        self.helper.invite(
            self.room_id, self.creator, self.second_user, tok=self.creator_tok
        )
        self.helper.invite(self.room_id, self.creator, third_user, tok=self.creator_tok)
        room_name = self.get_success(
            self.administration_handler.calculate_room_name(self.room_id)
        )

        self.assertEquals(room_name, "creator and 2 others")

    def test_get_unspecified_room_name_with_empty_room(self):
        self.helper.leave(self.room_id, self.creator, tok=self.creator_tok)
        room_name = self.get_success(
            self.administration_handler.calculate_room_name(self.room_id)
        )

        self.assertEquals(room_name, "nobody")
