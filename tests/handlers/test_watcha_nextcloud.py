from unittest.mock import AsyncMock

from synapse.api.errors import NextcloudError, SynapseError
from synapse.rest import admin
from synapse.rest.client.v1 import login, room

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
        self.collaborator = self.register_user("collaborator", "pass")
        collaborator_tok = self.login("collaborator", "pass")
        self.partner = self.register_user("partner", "pass", is_partner=True)
        self.partner_tok = self.login("partner", "pass")
        self.room_id = self.helper.create_room_as(self.creator, tok=self.creator_tok)
        self.helper.invite(
            self.room_id, src=self.creator, targ=self.collaborator, tok=self.creator_tok
        )
        self.helper.join(self.room_id, self.collaborator, tok=collaborator_tok)
        self.group_id = self.get_success(
            self.nextcloud_handler.build_group_id(self.room_id)
        )

        self.nextcloud_client.add_group = AsyncMock()
        self.nextcloud_client.delete_group = AsyncMock()
        self.nextcloud_client.add_user_to_group = AsyncMock()
        self.nextcloud_client.remove_user_from_group = AsyncMock()
        self.nextcloud_client.set_group_displayname = AsyncMock()
        self.nextcloud_client.unshare = AsyncMock()
        self.nextcloud_client.create_internal_share = AsyncMock(
            return_value="internal_share_1"
        )
        self.nextcloud_client.create_public_link_share = AsyncMock(
            return_value=("public_link_share_1", "https://example.com/12345")
        )

    def _bind(self):
        self.get_success(
            self.nextcloud_handler.bind(self.creator, self.room_id, "/folder")
        )
        self.nextcloud_client.add_group.reset_mock()
        self.nextcloud_client.add_user_to_group.reset_mock()
        self.nextcloud_client.create_internal_share.reset_mock()
        self.nextcloud_client.create_public_link_share.reset_mock()

    def _add_partner_to_room(self):
        self.helper.invite(
            self.room_id, src=self.creator, targ=self.partner, tok=self.creator_tok
        )
        self.helper.join(self.room_id, self.partner, tok=self.partner_tok)

    def test_bind(self):
        self._bind()
        internal_share_id = self.get_success(
            self.store.get_internal_share_id(self.room_id)
        )

        self.assertEquals(internal_share_id, "internal_share_1")

    def test_bind_with_partner_in_room(self):
        self._add_partner_to_room()
        self._bind()

        public_link_share_id = self.get_success(
            self.store.get_public_link_share_id(self.room_id)
        )

        self.assertEqual("public_link_share_1", public_link_share_id)

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
        self.hs.get_administration_handler().calculate_room_name = AsyncMock(
            return_value=room_name
        )
        self.nextcloud_client.set_group_displayname = AsyncMock(
            side_effect=NextcloudError(code=101, msg="")
        )

        self.get_success(self.nextcloud_handler.create_group(self.room_id))

    def test_add_internal_members_to_group(self):
        internal_members = ["partner1", "partner2"]
        self.get_success(self.nextcloud_handler.add_internal_members_to_group(self.room_id, internal_members))

        self.assertEquals(self.nextcloud_client.add_user_to_group.call_count, len(internal_members))

    def test_add_internal_members_to_group_without_account(self):
        internal_members = ["partner1"]
        self.nextcloud_client.add_user_to_group = AsyncMock(
            side_effect=NextcloudError(code=103, msg="")
        )

        self.get_success(self.nextcloud_handler.add_internal_members_to_group(self.room_id, internal_members))

    def test_add_internal_members_to_unexisting_group(self):
        internal_members = ["partner1"]
        self.nextcloud_client.add_user_to_group = AsyncMock(
            side_effect=NextcloudError(code=102, msg="")
        )

        self.get_failure(
            self.nextcloud_handler.add_internal_members_to_group(self.room_id, internal_members),
            SynapseError,
        )

    def test_create_internal_share(self):
        self.get_success(
            self.nextcloud_handler.create_internal_share(
                self.creator, self.room_id, "/new_folder"
            )
        )

        self.nextcloud_client.unshare.assert_not_called()
        self.nextcloud_client.create_internal_share.assert_called_once()

    def test_create_internal_share_with_unexisting_folder(self):
        old_share_id = self.get_success(self.store.get_internal_share_id(self.room_id))
        self.nextcloud_client.create_internal_share = AsyncMock(
            side_effect=NextcloudError(code=404, msg="")
        )
        self.nextcloud_client.unshare = AsyncMock(
            side_effect=NextcloudError(code=404, msg="")
        )
        self.nextcloud_handler.unbind = AsyncMock()

        error = self.get_failure(
            self.nextcloud_handler.create_internal_share(
                self.creator, self.room_id, "/new_folder"
            ),
            SynapseError,
        )

        self.assertEquals(error.value.code, 404)
        self.nextcloud_handler.unbind.assert_called_once()

    def test_create_internal_share_with_other_exceptions(self):
        old_share_id = self.get_success(self.store.get_internal_share_id(self.room_id))
        self.nextcloud_client.create_internal_share = AsyncMock(
            side_effect=NextcloudError(code=400, msg="")
        )
        self.nextcloud_client.unshare = AsyncMock(
            side_effect=NextcloudError(code=404, msg="")
        )
        self.nextcloud_handler.unbind = AsyncMock()

        error = self.get_failure(
            self.nextcloud_handler.create_internal_share(
                self.creator, self.room_id, "/new_folder"
            ),
            SynapseError,
        )

        self.assertEquals(error.value.code, 500)
        self.nextcloud_handler.unbind.assert_called_once_with(self.room_id)

    def test_unbind(self):
        self._bind()
        self.get_success(self.nextcloud_handler.unbind(self.room_id))

        internal_share_id = self.get_success(self.store.get_internal_share_id(self.room_id))

        self.nextcloud_client.delete_group.assert_called_once_with(self.group_id)
        self.assertIsNone(internal_share_id)

    def test_unbind_with_partner_in_room(self):
        self._add_partner_to_room()
        self._bind()
        self.get_success(self.nextcloud_handler.unbind(self.room_id))

        public_link_share_id = self.get_success(self.store.get_public_link_share_id(self.room_id))

        self.nextcloud_client.delete_group.assert_called_once_with(self.group_id)
        self.assertIsNone(public_link_share_id)

    def test_unbind_with_unexisting_group(self):
        self.nextcloud_client.delete_group = AsyncMock(
            side_effect=NextcloudError(code=101, msg="")
        )
        self.get_success(self.nextcloud_handler.unbind(self.room_id))
        share_id = self.get_success(self.store.get_internal_share_id(self.room_id))

        self.nextcloud_client.delete_group.assert_called_once_with(self.group_id)
        self.assertIsNone(share_id)

    def test_update_existing_group_on_invite_membership(self):
        self.get_success(
            self.nextcloud_handler.update_group(
                "@second_collaborator:test", self.room_id, "invite"
            )
        )

        self.nextcloud_client.add_user_to_group.assert_called_once()
        self.nextcloud_client.remove_user_from_group.assert_not_called()

    def test_update_existing_group_on_join_membership(self):
        self.get_success(
            self.nextcloud_handler.update_group(
                "@second_collaborator:test", self.room_id, "join"
            )
        )

        self.nextcloud_client.add_user_to_group.assert_called_once()
        self.nextcloud_client.remove_user_from_group.assert_not_called()

    def test_update_existing_group_on_leave_membership(self):
        self.get_success(
            self.nextcloud_handler.update_group(
                "@second_collaborator:test", self.room_id, "leave"
            )
        )

        self.nextcloud_client.remove_user_from_group.assert_called_once()
        self.nextcloud_client.add_user_to_group.assert_not_called()

    def test_update_existing_group_on_kick_membership(self):
        self.get_success(
            self.nextcloud_handler.update_group(
                "@second_collaborator:test", self.room_id, "kick"
            )
        )

        self.nextcloud_client.remove_user_from_group.assert_called_once()
        self.nextcloud_client.add_user_to_group.assert_not_called()

    def test_update_existing_group_on_invite_membership_with_exception(self):
        self.nextcloud_client.add_user_to_group = AsyncMock(
            side_effect=NextcloudError(code=103, msg="")
        )
        second_collaborator = "@second_collaborator:test"

        self.get_success(
            self.nextcloud_handler.update_group(
                second_collaborator, self.room_id, "invite"
            )
        )

    def test_update_existing_group_on_leave_membership_with_exception(self):
        self.nextcloud_client.remove_user_from_group = AsyncMock(
            side_effect=NextcloudError(code=103, msg="")
        )
        second_collaborator = "@second_collaborator:test"

        self.get_success(
            self.nextcloud_handler.update_group(
                second_collaborator, self.room_id, "leave"
            )
        )
