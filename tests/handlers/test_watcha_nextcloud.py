from mock import AsyncMock

from synapse.api.errors import SynapseError, NextcloudError
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

        self.creator = self.register_user("creator", "pass", admin=True)
        self.creator_tok = self.login("creator", "pass")
        self.inviter = self.register_user("inviter", "pass")
        inviter_tok = self.login("inviter", "pass")
        self.room_id = self.helper.create_room_as(self.creator, tok=self.creator_tok)
        self.helper.invite(
            self.room_id, src=self.creator, targ=self.inviter, tok=self.creator_tok
        )
        self.helper.join(self.room_id, self.inviter, tok=inviter_tok)
        self.group_name = NEXTCLOUD_GROUP_NAME_PREFIX + self.room_id

        self.nextcloud_client.add_group = AsyncMock()
        self.nextcloud_client.delete_group = AsyncMock()
        self.nextcloud_client.add_user_to_group = AsyncMock()
        self.nextcloud_client.remove_user_from_group = AsyncMock()
        self.nextcloud_client.unshare = AsyncMock()
        self.nextcloud_client.share = AsyncMock(return_value="share_1")

        self.get_success(
            self.nextcloud_handler.bind(self.creator, self.room_id, "/folder")
        )
        self.nextcloud_client.add_group.reset_mock()
        self.nextcloud_client.add_user_to_group.reset_mock()
        self.nextcloud_client.share.reset_mock()

    def test_unbind(self):
        self.get_success(self.nextcloud_handler.unbind(self.room_id))
        share_id = self.get_success(self.store.get_share_id(self.room_id))

        self.nextcloud_client.delete_group.assert_called()
        self.assertIsNone(share_id)

    def test_unbind_with_unexisting_group(self):
        self.nextcloud_client.delete_group = AsyncMock(
            side_effect=NextcloudError(code=101, msg="")
        )
        with self.assertLogs("synapse.handlers.watcha_nextcloud", level="WARN") as cm:
            self.get_success(self.nextcloud_handler.unbind(self.room_id))

        share_id = self.get_success(self.store.get_share_id(self.room_id))

        self.assertIn(
            f"[watcha] delete nextcloud group {self.group_name} - failed:",
            cm.output[0],
        )
        self.nextcloud_client.delete_group.assert_called()
        self.assertIsNone(share_id)

    def test_update_bind(self):
        old_share_id = self.get_success(self.store.get_share_id(self.room_id))
        self.nextcloud_client.share = AsyncMock(return_value="share_2")
        self.get_success(
            self.nextcloud_handler.bind(self.creator, self.room_id, "/new_folder")
        )
        share_id = self.get_success(self.store.get_share_id(self.room_id))

        self.assertEqual(old_share_id, "share_1")
        self.nextcloud_client.add_group.assert_called_once()
        self.nextcloud_client.share.assert_called_once()
        self.assertEquals(self.nextcloud_client.add_user_to_group.call_count, 2)
        self.nextcloud_client.unshare.assert_called()
        self.assertEquals(share_id, "share_2")

    def test_update_bind_with_existing_group(self):
        self.nextcloud_client.add_group = AsyncMock(
            side_effect=NextcloudError(code=102, msg="")
        )

        with self.assertLogs("synapse.handlers.watcha_nextcloud", level="WARN") as cm:
            self.get_success(
                self.nextcloud_handler.bind(self.creator, self.room_id, "/new_folder")
            )

        self.assertIn(
            f"[watcha] add nextcloud group {self.group_name} - failed: the group already exists",
            cm.output[0],
        )

    def test_update_bind_with_invalid_input_data(self):
        self.nextcloud_client.add_group = AsyncMock(
            side_effect=NextcloudError(code=101, msg="")
        )
        self.get_failure(
            self.nextcloud_handler.bind(self.creator, self.room_id, "/new_folder"),
            SynapseError,
        )

    def test_add_user_to_group_without_account(self):
        self.nextcloud_client.add_user_to_group = AsyncMock(
            side_effect=NextcloudError(code=103, msg="")
        )

        with self.assertLogs("synapse.handlers.watcha_nextcloud", level="WARN") as cm:
            self.get_success(
                self.nextcloud_handler.add_room_members_to_group(self.room_id)
            )

        self.assertIn(
            f"[watcha] add user {self.creator} to group {self.group_name} - failed",
            cm.output[0],
        )
        self.assertIn(
            f"[watcha] add user {self.inviter} to group {self.group_name} - failed",
            cm.output[1],
        )

    def test_create_share_with_exceptions(self):
        old_share_id = self.get_success(self.store.get_share_id(self.room_id))
        self.nextcloud_client.share = AsyncMock(
            side_effect=NextcloudError(code=400, msg="")
        )
        self.nextcloud_client.unshare = AsyncMock(
            side_effect=NextcloudError(code=404, msg="")
        )
        self.nextcloud_handler.unbind = AsyncMock()

        with self.assertLogs("synapse.handlers.watcha_nextcloud", level="WARN") as cm:
            self.get_failure(
                self.nextcloud_handler.create_share(
                    self.creator, self.room_id, "/new_folder"
                ),
                SynapseError,
            )

        self.nextcloud_handler.unbind.assert_called_once()
        self.assertIn(f"[watcha] unshare {old_share_id} - failed", cm.output[0])

    def test_add_user_to_unexisting_group(self):
        self.nextcloud_client.add_user_to_group = AsyncMock(
            side_effect=NextcloudError(code=102, msg="")
        )

        self.get_failure(
            self.nextcloud_handler.add_room_members_to_group(self.room_id),
            SynapseError,
        )

    def test_update_existing_group_on_invite_membership(self):
        self.get_success(
            self.nextcloud_handler.update_group(
                "@second_inviter:test", self.room_id, "invite"
            )
        )

        self.nextcloud_client.add_user_to_group.assert_called_once()
        self.nextcloud_client.remove_user_from_group.assert_not_called()

    def test_update_existing_group_on_join_membership(self):
        self.get_success(
            self.nextcloud_handler.update_group(
                "@second_inviter:test", self.room_id, "join"
            )
        )

        self.nextcloud_client.add_user_to_group.assert_called_once()
        self.nextcloud_client.remove_user_from_group.assert_not_called()

    def test_update_existing_group_on_leave_membership(self):
        self.get_success(
            self.nextcloud_handler.update_group(
                "@second_inviter:test", self.room_id, "leave"
            )
        )

        self.nextcloud_client.remove_user_from_group.assert_called_once()
        self.nextcloud_client.add_user_to_group.assert_not_called()

    def test_update_existing_group_on_kick_membership(self):
        self.get_success(
            self.nextcloud_handler.update_group(
                "@second_inviter:test", self.room_id, "kick"
            )
        )

        self.nextcloud_client.remove_user_from_group.assert_called_once()
        self.nextcloud_client.add_user_to_group.assert_not_called()

    def test_update_existing_group_on_invite_membership_with_exception(self):
        self.nextcloud_client.add_user_to_group = AsyncMock(
            side_effect=NextcloudError(code=103, msg="")
        )
        second_inviter = "@second_inviter:test"

        with self.assertLogs("synapse.handlers.watcha_nextcloud", level="WARN") as cm:
            self.get_success(
                self.nextcloud_handler.update_group(
                    second_inviter, self.room_id, "invite"
                )
            )
        self.assertIn(
            f"[watcha] add user {second_inviter} to group {self.group_name} - failed",
            cm.output[0],
        )

    def test_update_existing_group_on_leave_membership_with_exception(self):
        self.nextcloud_client.remove_user_from_group = AsyncMock(
            side_effect=NextcloudError(code=103, msg="")
        )
        second_inviter = "@second_inviter:test"

        with self.assertLogs("synapse.handlers.watcha_nextcloud", level="WARN") as cm:
            self.get_success(
                self.nextcloud_handler.update_group(
                    second_inviter, self.room_id, "leave"
                )
            )
        self.assertIn(
            f"[watcha] remove user {second_inviter} from group {self.group_name} - failed",
            cm.output[0],
        )
