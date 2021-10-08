from unittest.mock import AsyncMock

from synapse.api.errors import NextcloudError, SynapseError
from synapse.rest import admin
from synapse.rest.client.v1 import login, room
from synapse.util.watcha import calculate_room_name

from tests.unittest import HomeserverTestCase


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
        self.group_id = self.get_success(
            self.nextcloud_handler.build_group_id(self.room_id)
        )

        self.nextcloud_client.add_group = AsyncMock()
        self.nextcloud_client.delete_group = AsyncMock()
        self.nextcloud_client.add_user_to_group = AsyncMock()
        self.nextcloud_client.remove_user_from_group = AsyncMock()
        self.nextcloud_client.set_group_displayname = AsyncMock()
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

        self.nextcloud_client.delete_group.assert_called_once_with(self.group_id)
        self.assertIsNone(share_id)

    def test_unbind_with_unexisting_group(self):
        self.nextcloud_client.delete_group = AsyncMock(
            side_effect=NextcloudError(code=101, msg="")
        )
        self.get_success(self.nextcloud_handler.unbind(self.room_id))
        share_id = self.get_success(self.store.get_share_id(self.room_id))

        self.nextcloud_client.delete_group.assert_called_once_with(self.group_id)
        self.assertIsNone(share_id)

    def test_update_bind(self):
        old_share_id = self.get_success(self.store.get_share_id(self.room_id))
        self.nextcloud_client.share = AsyncMock(return_value="share_2")
        self.get_success(
            self.nextcloud_handler.bind(self.creator, self.room_id, "/new_folder")
        )
        share_id = self.get_success(self.store.get_share_id(self.room_id))

        self.assertEquals(old_share_id, "share_1")
        self.assertEquals(share_id, "share_2")

    def test_create_group(self):
        self.helper.send_state(
            self.room_id,
            "m.room.name",
            {"name": "default room"},
            tok=self.creator_tok,
        )
        self.nextcloud_client.set_group_displayname.reset_mock()
        self.get_success(self.nextcloud_handler.create_group(self.room_id))

        group_displayname = self.get_success(
            self.nextcloud_handler.build_group_displayname(self.room_id)
        )

        self.nextcloud_client.add_group.assert_called_once_with(self.group_id)
        self.nextcloud_client.set_group_displayname.assert_called_once_with(
            self.group_id, group_displayname
        )

    def test_create_existing_group(self):
        self.nextcloud_client.add_group = AsyncMock(
            side_effect=NextcloudError(code=102, msg="")
        )

        self.get_success(self.nextcloud_handler.create_group(self.room_id))

    def test_create_group_with_invalid_input_data(self):
        self.nextcloud_client.add_group = AsyncMock(
            side_effect=NextcloudError(code=101, msg="")
        )
        self.get_failure(
            self.nextcloud_handler.create_group(self.room_id),
            SynapseError,
        )

    def test_create_group_with_set_displayname_exception(self):
        room_name = "default room"
        calculate_room_name = AsyncMock(return_value=room_name)
        self.nextcloud_client.set_group_displayname = AsyncMock(
            side_effect=NextcloudError(code=101, msg="")
        )

        self.get_success(self.nextcloud_handler.create_group(self.room_id))

    def test_add_room_members_to_group(self):
        self.get_success(self.nextcloud_handler.add_room_members_to_group(self.room_id))

        self.assertEquals(self.nextcloud_client.add_user_to_group.call_count, 2)

    def test_add_room_members_to_group_without_account(self):
        self.nextcloud_client.add_user_to_group = AsyncMock(
            side_effect=NextcloudError(code=103, msg="")
        )

        self.get_success(self.nextcloud_handler.add_room_members_to_group(self.room_id))

    def test_create_share(self):
        self.get_success(
            self.nextcloud_handler.create_share(
                self.creator, self.room_id, "/new_folder"
            )
        )

        self.nextcloud_client.unshare.assert_called_once()
        self.nextcloud_client.share.assert_called_once()

    def test_create_share_with_unexisting_folder(self):
        old_share_id = self.get_success(self.store.get_share_id(self.room_id))
        self.nextcloud_client.share = AsyncMock(
            side_effect=NextcloudError(code=404, msg="")
        )
        self.nextcloud_client.unshare = AsyncMock(
            side_effect=NextcloudError(code=404, msg="")
        )
        self.nextcloud_handler.unbind = AsyncMock()

        error = self.get_failure(
            self.nextcloud_handler.create_share(
                self.creator, self.room_id, "/new_folder"
            ),
            SynapseError,
        )

        self.assertEquals(error.value.code, 404)
        self.nextcloud_handler.unbind.assert_called_once()

    def test_create_share_with_other_exceptions(self):
        old_share_id = self.get_success(self.store.get_share_id(self.room_id))
        self.nextcloud_client.share = AsyncMock(
            side_effect=NextcloudError(code=400, msg="")
        )
        self.nextcloud_client.unshare = AsyncMock(
            side_effect=NextcloudError(code=404, msg="")
        )
        self.nextcloud_handler.unbind = AsyncMock()

        error = self.get_failure(
            self.nextcloud_handler.create_share(
                self.creator, self.room_id, "/new_folder"
            ),
            SynapseError,
        )

        self.assertEquals(error.value.code, 500)
        self.nextcloud_handler.unbind.assert_called_once_with(self.room_id)

    def test_add_user_to_unexisting_group(self):
        self.nextcloud_client.add_user_to_group = AsyncMock(
            side_effect=NextcloudError(code=102, msg="")
        )

        self.get_failure(
            self.nextcloud_handler.add_room_members_to_group(self.room_id),
            SynapseError,
        )

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

    def test_update_existing_group_on_join_membership_with_exception(self):
        self.nextcloud_client.add_user_to_group = AsyncMock(
            side_effect=NextcloudError(code=103, msg="")
        )
        second_inviter = "@second_inviter:test"

        self.get_success(
            self.nextcloud_handler.update_group(second_inviter, self.room_id, "join")
        )

    def test_update_existing_group_on_leave_membership_with_exception(self):
        self.nextcloud_client.remove_user_from_group = AsyncMock(
            side_effect=NextcloudError(code=103, msg="")
        )
        second_inviter = "@second_inviter:test"

        self.get_success(
            self.nextcloud_handler.update_group(second_inviter, self.room_id, "leave")
        )
