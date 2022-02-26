from unittest.mock import mock_open, patch

from synapse.types import UserID

from tests import unittest

SETUP_PROPERTIES = """\
WATCHA_RELEASE=1.0
INSTALL_DATE=2020-03-16T18:32:18
UPGRADE_DATE=2020-06-16T22:43:29
"""


class AdministrationTestCase(unittest.HomeserverTestCase):
    def prepare(self, reactor, clock, hs):
        self.store = hs.get_datastore()
        self.time = int(hs.get_clock().time_msec())

    def test_watcha_user_list(self):

        register_users_list = [
            {
                "user_id": "@administrator:test",
                "make_partner": False,
                "admin": True,
                "create_profile_with_displayname": None,
                "email": None,
            },
            {
                "user_id": "@collaborator:test",
                "make_partner": False,
                "admin": False,
                "create_profile_with_displayname": "collaborator",
                "email": "example@example.com",
            },
            {
                "user_id": "@partner:test",
                "make_partner": True,
                "admin": False,
                "create_profile_with_displayname": None,
                "email": None,
            },
        ]

        for user in register_users_list:
            self.get_success(
                self.store.register_user(
                    user["user_id"],
                    password_hash=None,
                    make_partner=user["make_partner"],
                    create_profile_with_displayname=user[
                        "create_profile_with_displayname"
                    ],
                    admin=user["admin"],
                )
            )

            if user["email"]:
                self.get_success(
                    self.store.user_add_threepid(
                        "@collaborator:test",
                        "email",
                        "example@example.com",
                        self.time,
                        self.time,
                    )
                )

        users_informations = self.get_success(self.store.watcha_user_list())

        # Sorted the register_users_list like the function watcha_user_list do it :
        register_users_list_sorted = sorted(
            register_users_list, key=lambda i: i["user_id"]
        )

        for user in register_users_list_sorted:
            user_index = register_users_list_sorted.index(user)
            self.assertEquals(
                user["user_id"], users_informations[user_index]["user_id"]
            )
            self.assertEquals(
                user["make_partner"], users_informations[user_index]["is_partner"]
            )
            self.assertEquals(user["admin"], users_informations[user_index]["is_admin"])
            self.assertEquals(
                user["email"], users_informations[user_index]["email_address"]
            )
            self.assertEquals(
                user["create_profile_with_displayname"],
                users_informations[user_index]["display_name"],
            )
            self.assertEquals(None, users_informations[user_index]["last_seen"])
            self.assertEquals(self.time, users_informations[user_index]["creation_ts"])

    def test_watcha_update_user_role(self):
        user_id = "@administrator:test"
        self.get_success(self.store.register_user(user_id, admin=True))

        expected_values = [
            {"role": "partner", "values": {"is_partner": 1, "is_admin": 0}},
            {"role": "collaborator", "values": {"is_partner": 0, "is_admin": 0}},
            {"role": "administrator", "values": {"is_partner": 0, "is_admin": 1}},
        ]

        for element in expected_values:
            self.get_success(self.store.update_user_role(user_id, element["role"]))
            is_partner = self.get_success(self.store.is_partner(user_id))
            is_admin = self.get_success(
                self.store.is_server_admin(UserID.from_string(user_id))
            )
            self.assertEquals(is_partner, element["values"]["is_partner"])
            self.assertEquals(is_admin, element["values"]["is_admin"])

    @patch("builtins.open", new_callable=mock_open, read_data=SETUP_PROPERTIES)
    def test_get_install_information_from_file(self, mock_file):
        install_information = self.get_success(
            self.store._get_install_information_from_file()
        )
        self.assertEqual("1.0", install_information["watcha_release"])
        self.assertEqual("2020-03-16T18:32:18", install_information["install_date"])
        self.assertEqual("2020-06-16T22:43:29", install_information["upgrade_date"])
