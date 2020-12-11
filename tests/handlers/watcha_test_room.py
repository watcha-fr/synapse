from .. import unittest
from mock import Mock

from synapse.api.errors import Codes, SynapseError
from synapse.http.watcha_keycloak_client import KeycloakClient
from synapse.http.watcha_nextcloud_client import NextcloudClient
from synapse.rest.client.v1 import login, room
from synapse.rest import admin
from synapse.types import get_localpart_from_id


def simple_async_mock(return_value=None, raises=None):
    # AsyncMock is not available in python3.5, this mimics part of its behaviour
    async def cb(*args, **kwargs):
        if raises:
            raise raises
        return return_value

    return Mock(side_effect=cb)


class NextcloudHandlerTestCase(unittest.HomeserverTestCase):

    servlets = [
        admin.register_servlets,
        login.register_servlets,
        room.register_servlets,
    ]

    def prepare(self, reactor, clock, hs):
        self.store = hs.get_datastore()
        self.watcha_room_nextcloud_mapping = hs.get_nextcloud_handler()

        self.keycloak_client = self.watcha_room_nextcloud_mapping.keycloak_client
        self.nextcloud_client = self.watcha_room_nextcloud_mapping.nextcloud_client

        # Create a room with two users :
        self.creator = self.register_user("creator", "pass", admin=True)
        self.creator_tok = self.login("creator", "pass")

        self.inviter = self.register_user("inviter", "pass")
        inviter_tok = self.login("inviter", "pass")

        self.room_id = self.helper.create_room_as(self.creator, tok=self.creator_tok)
        self.helper.invite(
            self.room_id, src=self.creator, targ=self.inviter, tok=self.creator_tok
        )
        self.helper.join(self.room_id, self.inviter, tok=inviter_tok)

        # Mock Keycloak client functions :
        self.keycloak_client.get_user = simple_async_mock(
            return_value={"id": "1234", "username": "creator"},
        )
        self.keycloak_client.get_users = simple_async_mock(
            return_value=[
                {"id": "1234", "username": "creator"},
                {"id": "56789", "username": "inviter"},
            ]
        )

        # Mock Nextcloud client functions :
        self.nextcloud_client.add_group = simple_async_mock()
        self.nextcloud_client.delete_group = simple_async_mock()
        self.nextcloud_client.get_user = simple_async_mock()
        self.nextcloud_client.add_user_to_group = simple_async_mock()
        self.nextcloud_client.remove_user_from_group = simple_async_mock()
        self.nextcloud_client.unshare = simple_async_mock()
        self.nextcloud_client.share = simple_async_mock(return_value=1)

    def test_set_a_new_bind(self):
        self.get_success(
            self.watcha_room_nextcloud_mapping.bind(
                self.room_id, self.creator, "/directory"
            )
        )

        mapped_directory = self.get_success(
            self.store.get_path_from_room_id(self.room_id)
        )

        share_id = self.get_success(
            self.store.get_nextcloud_share_id_from_room_id(self.room_id)
        )

        # Verify that mocked functions are called once
        self.keycloak_client.get_user.assert_called_once()
        self.nextcloud_client.add_group.assert_called_once()
        self.keycloak_client.get_users.assert_called_once()
        self.nextcloud_client.share.assert_called_once()

        # Verify that mocked functions are called twice
        self.assertEquals(self.nextcloud_client.get_user.call_count, 2)
        self.assertEquals(self.nextcloud_client.add_user_to_group.call_count, 2)

        # Verify that mocked functions are not called
        self.nextcloud_client.unshare.assert_not_called()

        self.assertEqual(mapped_directory, "/directory")
        self.assertEqual(share_id, 1)

    def test_update_an_existing_bind(self):
        self.get_success(self.store.bind(self.room_id, "/directory", 2))

        old_mapped_directory = self.get_success(
            self.store.get_path_from_room_id(self.room_id)
        )

        old_share_id = self.get_success(
            self.store.get_nextcloud_share_id_from_room_id(self.room_id)
        )

        self.assertEqual(old_mapped_directory, "/directory")
        self.assertEqual(old_share_id, 2)

        self.get_success(
            self.watcha_room_nextcloud_mapping.bind(
                self.room_id, self.creator, "/directory2"
            )
        )

        mapped_directory = self.get_success(
            self.store.get_path_from_room_id(self.room_id)
        )

        new_share_id = self.get_success(
            self.store.get_nextcloud_share_id_from_room_id(self.room_id)
        )

        # Verify that mocked functions has called :
        self.nextcloud_client.unshare.assert_called()

        self.assertEqual(mapped_directory, "/directory2")
        self.assertEqual(new_share_id, 1)

    def test_delete_an_existing_bind(self):
        self.get_success(self.store.bind(self.room_id, "/directory", 2))
        self.get_success(self.watcha_room_nextcloud_mapping.unbind(self.room_id))

        mapped_directory = self.get_success(
            self.store.get_path_from_room_id(self.room_id)
        )

        share_id = self.get_success(
            self.store.get_nextcloud_share_id_from_room_id(self.room_id)
        )

        self.nextcloud_client.delete_group.assert_called()
        self.assertIsNone(mapped_directory)
        self.assertIsNone(share_id)

    def test_add_user_to_nextcloud_group_without_nextcloud_account(self):
        self.nextcloud_client.get_user = simple_async_mock(raises=SynapseError)

        with self.assertLogs("synapse.handlers.room", level="WARN") as cm:
            self.get_success(
                self.watcha_room_nextcloud_mapping.add_room_users_to_nextcloud_group(
                    self.room_id
                )
            )

        self.assertIn(
            "The user {} does not have a Nextcloud account.".format(
                get_localpart_from_id(self.creator)
            ),
            cm.output[0],
        )

        self.assertIn(
            "The user {} does not have a Nextcloud account.".format(
                get_localpart_from_id(self.inviter)
            ),
            cm.output[1],
        )

    def test_add_user_to_nextcloud_group_with_exception(self):
        self.nextcloud_client.add_user_to_group = simple_async_mock(raises=SynapseError)

        with self.assertLogs("synapse.handlers.room", level="WARN") as cm:
            self.get_success(
                self.watcha_room_nextcloud_mapping.add_room_users_to_nextcloud_group(
                    self.room_id
                )
            )

        self.assertIn(
            "Unable to add the user {username} to the Nextcloud group {group_name}.".format(
                username=get_localpart_from_id(self.creator), group_name=self.room_id
            ),
            cm.output[0],
        )

        self.assertIn(
            "Unable to add the user {username} to the Nextcloud group {group_name}.".format(
                username=get_localpart_from_id(self.inviter), group_name=self.room_id
            ),
            cm.output[1],
        )

    def test_update_existing_nextcloud_share_on_invite_membership(self):
        self.get_success(
            self.watcha_room_nextcloud_mapping.update_share(
                "@second_inviter:test", self.room_id, "invite"
            )
        )

        self.keycloak_client.get_user.assert_called_once()
        self.nextcloud_client.add_user_to_group.assert_called_once()
        self.nextcloud_client.remove_user_from_group.assert_not_called()

    def test_update_existing_nextcloud_share_on_invite_membership(self):
        self.get_success(
            self.watcha_room_nextcloud_mapping.update_share(
                "@second_inviter:test", self.room_id, "join"
            )
        )

        self.keycloak_client.get_user.assert_called_once()
        self.nextcloud_client.add_user_to_group.assert_called_once()
        self.nextcloud_client.remove_user_from_group.assert_not_called()

    def test_update_existing_nextcloud_share_on_leave_membership(self):
        self.get_success(
            self.watcha_room_nextcloud_mapping.update_share(
                "@second_inviter:test", self.room_id, "leave"
            )
        )

        self.keycloak_client.get_user.assert_called_once()
        self.nextcloud_client.remove_user_from_group.assert_called_once()
        self.nextcloud_client.add_user_to_group.assert_not_called()

    def test_update_existing_nextcloud_share_on_kick_membership(self):
        self.get_success(
            self.watcha_room_nextcloud_mapping.update_share(
                "@second_inviter:test", self.room_id, "kick"
            )
        )

        self.keycloak_client.get_user.assert_called_once()
        self.nextcloud_client.remove_user_from_group.assert_called_once()
        self.nextcloud_client.add_user_to_group.assert_not_called()

    def test_update_existing_nextcloud_share_on_invite_membership_with_exception(self):
        self.nextcloud_client.add_user_to_group = simple_async_mock(raises=SynapseError)
        second_inviter = "@second_inviter:test"

        with self.assertLogs("synapse.handlers.room", level="WARN") as cm:
            self.get_success(
                self.watcha_room_nextcloud_mapping.update_share(
                    second_inviter, self.room_id, "invite"
                )
            )

        self.assertIn(
            "Unable to add the user {username} to the Nextcloud group {group_name}.".format(
                username=second_inviter, group_name=self.room_id
            ),
            cm.output[0],
        )

    def test_update_existing_nextcloud_share_on_leave_membership_with_exception(self):
        self.nextcloud_client.remove_user_from_group = simple_async_mock(
            raises=SynapseError
        )
        second_inviter = "@second_inviter:test"

        with self.assertLogs("synapse.handlers.room", level="WARN") as cm:
            self.get_success(
                self.watcha_room_nextcloud_mapping.update_share(
                    second_inviter, self.room_id, "leave"
                )
            )

        self.assertIn(
            "Unable to remove the user {username} from the Nextcloud group {group_name}.".format(
                username=second_inviter, group_name=self.room_id
            ),
            cm.output[0],
        )
