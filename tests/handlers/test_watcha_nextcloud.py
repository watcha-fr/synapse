from mock import AsyncMock

from synapse.api.errors import Codes, SynapseError
from synapse.rest.client.v1 import login, room
from synapse.rest import admin
from tests.unittest import HomeserverTestCase

NEXTCLOUD_GROUP_NAME_PREFIX = "c4d96a06b7_"


class NextcloudHandlerTestCase(HomeserverTestCase):
    servlets = [
        admin.register_servlets,
        login.register_servlets,
        room.register_servlets,
    ]

    def prepare(self, reactor, clock, hs):
        self.store = hs.get_datastore()
        self.nextcloud_handler = hs.get_nextcloud_handler()

        self.keycloak_client = self.nextcloud_handler.keycloak_client
        self.nextcloud_client = self.nextcloud_handler.nextcloud_client

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

        # Mock Nextcloud client functions :
        self.nextcloud_client.add_group = AsyncMock()
        self.nextcloud_client.delete_group = AsyncMock()
        self.nextcloud_client.add_user_to_group = AsyncMock()
        self.nextcloud_client.remove_user_from_group = AsyncMock()
        self.nextcloud_client.unshare = AsyncMock()
        self.nextcloud_client.share = AsyncMock(return_value=1)

    def test_set_a_new_bind(self):
        self.get_success(
            self.nextcloud_handler.bind(self.creator, self.room_id, "/directory")
        )

        mapped_directory = self.get_success(
            self.store.get_path_from_room_id(self.room_id)
        )

        share_id = self.get_success(
            self.store.get_nextcloud_share_id_from_room_id(self.room_id)
        )

        # Verify that mocked functions are called once
        self.nextcloud_client.add_group.assert_called_once()
        self.nextcloud_client.share.assert_called_once()

        # Verify that mocked functions are called twice
        self.assertEquals(self.nextcloud_client.add_user_to_group.call_count, 2)

        # Verify that mocked functions are not called
        self.nextcloud_client.unshare.assert_not_called()

        self.assertEqual(mapped_directory, "/directory")

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
            self.nextcloud_handler.bind(self.creator, self.room_id, "/directory2")
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
        self.get_success(self.nextcloud_handler.unbind(self.room_id))

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
        self.nextcloud_client.add_user_to_group = AsyncMock(
            side_effect=SynapseError(code=400, msg="")
        )

        with self.assertLogs("synapse.handlers.watcha_nextcloud", level="WARN") as cm:
            self.get_success(
                self.nextcloud_handler.add_room_users_to_nextcloud_group(self.room_id)
            )

        self.assertIn(
            "Unable to add the user {} to the Nextcloud group {}".format(
                self.creator,
                NEXTCLOUD_GROUP_NAME_PREFIX + self.room_id,
            ),
            cm.output[0],
        )

        self.assertIn(
            "Unable to add the user {} to the Nextcloud group {}".format(
                self.inviter,
                NEXTCLOUD_GROUP_NAME_PREFIX + self.room_id,
            ),
            cm.output[1],
        )

    def test_add_user_to_nextcloud_group_with_exception(self):
        group_name = NEXTCLOUD_GROUP_NAME_PREFIX + self.room_id
        self.nextcloud_client.add_user_to_group = AsyncMock(
            side_effect=SynapseError(code=400, msg="")
        )

        with self.assertLogs("synapse.handlers.watcha_nextcloud", level="WARN") as cm:
            self.get_success(
                self.nextcloud_handler.add_room_users_to_nextcloud_group(self.room_id)
            )

        self.assertIn(
            "Unable to add the user {} to the Nextcloud group {}.".format(
                self.creator, group_name
            ),
            cm.output[0],
        )

        self.assertIn(
            "Unable to add the user {} to the Nextcloud group {}.".format(
                self.inviter, group_name
            ),
            cm.output[1],
        )

    def test_update_existing_nextcloud_share_on_invite_membership(self):
        self.get_success(
            self.nextcloud_handler.update_share(
                "@second_inviter:test", self.room_id, "invite"
            )
        )

        self.nextcloud_client.add_user_to_group.assert_called_once()
        self.nextcloud_client.remove_user_from_group.assert_not_called()

    def test_update_existing_nextcloud_share_on_join_membership(self):
        self.get_success(
            self.nextcloud_handler.update_share(
                "@second_inviter:test", self.room_id, "join"
            )
        )

        self.nextcloud_client.add_user_to_group.assert_called_once()
        self.nextcloud_client.remove_user_from_group.assert_not_called()

    def test_update_existing_nextcloud_share_on_leave_membership(self):
        self.get_success(
            self.nextcloud_handler.update_share(
                "@second_inviter:test", self.room_id, "leave"
            )
        )

        self.nextcloud_client.remove_user_from_group.assert_called_once()
        self.nextcloud_client.add_user_to_group.assert_not_called()

    def test_update_existing_nextcloud_share_on_kick_membership(self):
        self.get_success(
            self.nextcloud_handler.update_share(
                "@second_inviter:test", self.room_id, "kick"
            )
        )

        self.nextcloud_client.remove_user_from_group.assert_called_once()
        self.nextcloud_client.add_user_to_group.assert_not_called()

    def test_update_existing_nextcloud_share_on_invite_membership_with_exception(self):
        self.nextcloud_client.add_user_to_group = AsyncMock(
            side_effect=SynapseError(code=400, msg="")
        )
        second_inviter = "@second_inviter:test"

        with self.assertLogs("synapse.handlers.watcha_nextcloud", level="WARN") as cm:
            self.get_success(
                self.nextcloud_handler.update_share(
                    second_inviter, self.room_id, "invite"
                )
            )

        self.assertIn(
            "Unable to add the user {} to the Nextcloud group {}.".format(
                second_inviter, NEXTCLOUD_GROUP_NAME_PREFIX + self.room_id
            ),
            cm.output[0],
        )

    def test_update_existing_nextcloud_share_on_leave_membership_with_exception(self):
        self.nextcloud_client.remove_user_from_group = AsyncMock(
            side_effect=SynapseError(code=400, msg="")
        )
        second_inviter = "@second_inviter:test"

        with self.assertLogs("synapse.handlers.watcha_nextcloud", level="WARN") as cm:
            self.get_success(
                self.nextcloud_handler.update_share(
                    second_inviter, self.room_id, "leave"
                )
            )

        self.assertIn(
            "Unable to remove the user {} from the Nextcloud group {}.".format(
                second_inviter, NEXTCLOUD_GROUP_NAME_PREFIX + self.room_id
            ),
            cm.output[0],
        )
