import json

from synapse.rest import admin
from synapse.rest.client.v1 import watcha, login, room
from tests import unittest


class AdministrationTestCase(unittest.HomeserverTestCase):

    servlets = [
        admin.register_servlets_for_client_rest_resource,
        login.register_servlets,
        watcha.register_servlets,
        room.register_servlets,
    ]

    url = "/_matrix/client/r0/"

    def prepare(self, reactor, clock, hs):
        self.time = self.hs.get_clock().time_msec()
        self.auth = hs.get_auth_handler()

        self.admin = self.register_user("admin", "pass", admin=True)
        self.admin_tok = self.login("admin", "pass")
        self.get_success(
            self.auth.add_threepid(self.admin, "email", "admin@example.com", self.time)
        )
        self.collaborator = self.register_user("collaborator", "pass")
        self.collaborator_tok = self.login("collaborator", "pass")
        self.get_success(
            self.auth.add_threepid(
                self.collaborator, "email", "collaborator@example.com", self.time
            )
        )
        self.partner = self.register_user("partner", "pass", is_partner=True)
        self.partner_tok = self.login("partner", "pass")
        self.get_success(
            self.auth.add_threepid(
                self.partner, "email", "partner@example.com", self.time
            )
        )
        self.room1_id = self.helper.create_room_as(self.admin, tok=self.admin_tok)
        self.room2_id = self.helper.create_room_as(self.admin, tok=self.admin_tok)

    def test_watcha_user_list(self):
        channel = self.make_request(
            "GET",
            self.url + "watcha_user_list",
            access_token=self.admin_tok,
        )

        self.assertEqual(
            json.loads(channel.result["body"]),
            [
                {
                    "creation_ts": 0,
                    "display_name": "admin",
                    "email_address": "admin@example.com",
                    "last_seen": None,
                    "role": "administrator",
                    "user_id": "@admin:test",
                },
                {
                    "creation_ts": 0,
                    "display_name": "collaborator",
                    "email_address": "collaborator@example.com",
                    "last_seen": None,
                    "role": "collaborator",
                    "user_id": "@collaborator:test",
                },
                {
                    "creation_ts": 0,
                    "display_name": "partner",
                    "email_address": "partner@example.com",
                    "last_seen": None,
                    "role": "partner",
                    "user_id": "@partner:test",
                },
            ],
        )
        self.assertEqual(channel.code, 200)

    def test_get_watcha_admin_user_stats(self):
        channel = self.make_request(
            "GET", self.url + "watcha_admin_stats", access_token=self.admin_tok
        )

        self.assertEquals(
            json.loads(channel.result["body"])["users"],
            {
                "administrators_users": [
                    {
                        "displayname": None,
                        "email": "admin@example.com",
                        "user_id": "@admin:test",
                    }
                ],
                "connected_users": {
                    "number_of_last_month_logged_users": 0,
                    "number_of_last_week_logged_users": 0,
                    "number_of_users_logged_at_least_once": 3,
                },
                "users_per_role": {
                    "administrators": 1,
                    "collaborators": 1,
                    "partners": 1,
                },
            },
        )
        self.assertEqual(channel.code, 200)

    def test_get_watcha_admin_stats_room_type(self):
        channel = self.make_request(
            "GET", self.url + "watcha_admin_stats", access_token=self.admin_tok
        )

        self.assertEquals(
            json.loads(channel.result["body"])["rooms"],
            {
                "active_dm_room_count": 0,
                "dm_room_count": 0,
                "active_regular_room_count": 0,
                "regular_room_count": 2,
            },
        )
        self.assertEquals(200, channel.code)

    def test_get_watcha_admin_stats_room_list(self):
        room_ids = sorted([self.room1_id, self.room2_id])

        channel = self.make_request(
            "GET", self.url + "watcha_room_list", access_token=self.admin_tok
        )

        for room_id in room_ids:
            self.assertIn(
                json.loads(channel.result["body"])[room_ids.index(room_id)],
                [
                    {
                        "creator": "@admin:test",
                        "members": ["@admin:test"],
                        "name": None,
                        "room_id": self.room1_id,
                        "status": "inactive",
                        "type": "regular_room",
                    },
                    {
                        "creator": "@admin:test",
                        "members": ["@admin:test"],
                        "name": None,
                        "room_id": self.room2_id,
                        "status": "inactive",
                        "type": "regular_room",
                    },
                ],
            )
        self.assertEquals(200, channel.code)
