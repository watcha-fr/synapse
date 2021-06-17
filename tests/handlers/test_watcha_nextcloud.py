from unittest.mock import AsyncMock

from synapse.api.constants import Membership
from synapse.api.errors import NextcloudError, SynapseError
from synapse.rest import admin
from synapse.rest.client.v1 import login, room

from tests.unittest import HomeserverTestCase


class NextcloudBindHandlerTestCase(HomeserverTestCase):

    servlets = [
        admin.register_servlets,
        login.register_servlets,
        room.register_servlets,
    ]

    def prepare(self, reactor, clock, hs):
        self.store = hs.get_datastore()
        self.nextcloud_bind_handler = hs.get_nextcloud_bind_handler()
        self.nextcloud_group_handler = hs.get_nextcloud_group_handler()
        self.nextcloud_share_handler = hs.get_nextcloud_share_handler()
        self.nextcloud_client = hs.get_nextcloud_client()

        self.creator = self.register_user("creator", "pass", admin=True)
        self.creator_tok = self.login("creator", "pass")
        self.partner = self.register_user("partner", "pass", is_partner=True)
        self.partner_tok = self.login("partner", "pass")
        self.collaborator = self.register_user("collaborator", "pass")
        self.collaborator_tok = self.login("collaborator", "pass")
        self.room_id = self.helper.create_room_as(self.creator, tok=self.creator_tok)
        self.helper.invite(
            self.room_id, src=self.creator, targ=self.partner, tok=self.creator_tok
        )
        self.helper.join(self.room_id, self.partner, tok=self.partner_tok)
        self.group_id = self.get_success(
            self.nextcloud_group_handler.build_group_id(self.room_id)
        )

        self.nextcloud_client.add_group = AsyncMock()
        self.nextcloud_client.delete_group = AsyncMock()
        self.nextcloud_client.add_user_to_group = AsyncMock()
        self.nextcloud_client.set_group_display_name = AsyncMock()
        self.nextcloud_client.create_internal_share = AsyncMock(
            return_value="internal_share_1"
        )
        self.nextcloud_client.create_public_link_share = AsyncMock(
            return_value=("public_link_share_1", "https://example.com/12345")
        )

        self.get_success(
            self.nextcloud_bind_handler.bind(self.creator, self.room_id, "/folder")
        )
        self.nextcloud_client.add_group.reset_mock()
        self.nextcloud_client.add_user_to_group.reset_mock()
        self.nextcloud_client.create_internal_share.reset_mock()
        self.nextcloud_client.create_public_link_share.reset_mock()

    def test_bind(self):
        internal_share_id = self.get_success(
            self.store.get_internal_share_id(self.room_id)
        )

        self.assertEquals(internal_share_id, "internal_share_1")

    def test_bind_with_partner_in_room(self):
        public_link_share_id = self.get_success(
            self.store.get_public_link_share_id(self.room_id)
        )

        self.assertEqual("public_link_share_1", public_link_share_id)

    def test_unbind(self):
        self.get_success(self.nextcloud_bind_handler.unbind(self.room_id))

        internal_share_id = self.get_success(
            self.store.get_internal_share_id(self.room_id)
        )

        self.nextcloud_client.delete_group.assert_called_once_with(self.group_id)
        self.assertIsNone(internal_share_id)

    def test_unbind_with_partner_in_room(self):
        self.get_success(self.nextcloud_bind_handler.unbind(self.room_id))

        public_link_share_id = self.get_success(
            self.store.get_public_link_share_id(self.room_id)
        )

        self.nextcloud_client.delete_group.assert_called_once_with(self.group_id)
        self.assertIsNone(public_link_share_id)

    def test_unbind_with_unexisting_group(self):
        self.nextcloud_client.delete_group = AsyncMock(
            side_effect=NextcloudError(code=101, msg="")
        )
        self.get_success(self.nextcloud_bind_handler.unbind(self.room_id))
        share_id = self.get_success(self.store.get_internal_share_id(self.room_id))

        self.nextcloud_client.delete_group.assert_called_once_with(self.group_id)
        self.assertIsNone(share_id)

    def test_update_bind_on_user_membership(self):
        self.nextcloud_group_handler.update_group = AsyncMock()
        self.nextcloud_share_handler.handle_public_link_share_on_membership = (
            AsyncMock()
        )
        self.helper.invite(
            self.room_id, src=self.creator, targ=self.collaborator, tok=self.creator_tok
        )

        self.nextcloud_group_handler.update_group.assert_called_once_with(
            self.collaborator, self.room_id, Membership.INVITE
        )
        self.nextcloud_share_handler.handle_public_link_share_on_membership.assert_not_called()

    def test_update_bind_on_partner_membership(self):
        self.nextcloud_group_handler.update_group = AsyncMock()
        self.nextcloud_share_handler.handle_public_link_share_on_membership = (
            AsyncMock()
        )
        self.helper.leave(self.room_id, self.partner, tok=self.partner_tok)

        self.nextcloud_share_handler.handle_public_link_share_on_membership.assert_called_once_with(
            self.room_id, Membership.LEAVE
        )
        self.nextcloud_group_handler.update_group.assert_not_called()


class NextcloudGroupHandlerTestCase(HomeserverTestCase):
    servlets = [
        admin.register_servlets,
        login.register_servlets,
        room.register_servlets,
    ]

    def prepare(self, reactor, clock, hs):
        self.nextcloud_group_handler = hs.get_nextcloud_group_handler()
        self.nextcloud_client = hs.get_nextcloud_client()

        creator = self.register_user("creator", "pass", admin=True)
        self.creator_tok = self.login("creator", "pass")
        self.room_id = self.helper.create_room_as(creator, tok=self.creator_tok)
        self.group_id = self.get_success(
            self.nextcloud_group_handler.build_group_id(self.room_id)
        )

        self.nextcloud_client.add_group = AsyncMock()
        self.nextcloud_client.delete_group = AsyncMock()
        self.nextcloud_client.add_user_to_group = AsyncMock()
        self.nextcloud_client.remove_user_from_group = AsyncMock()
        self.nextcloud_client.set_group_display_name = AsyncMock()

    def test_create_group(self):
        self.helper.send_state(
            self.room_id,
            "m.room.name",
            {"name": "default room"},
            tok=self.creator_tok,
        )
        self.nextcloud_client.set_group_display_name.reset_mock()
        self.get_success(self.nextcloud_group_handler.create_group(self.room_id))

        group_displayname = self.get_success(
            self.nextcloud_group_handler.build_group_display_name(self.room_id)
        )

        self.nextcloud_client.add_group.assert_called_once_with(self.group_id)
        self.nextcloud_client.set_group_display_name.assert_called_once_with(
            self.group_id, group_displayname
        )

    def test_create_existing_group(self):
        self.nextcloud_client.add_group = AsyncMock(
            side_effect=NextcloudError(code=102, msg="")
        )

        self.get_success(self.nextcloud_group_handler.create_group(self.room_id))

    def test_create_group_with_invalid_input_data(self):
        self.nextcloud_client.add_group = AsyncMock(
            side_effect=NextcloudError(code=101, msg="")
        )
        self.get_failure(
            self.nextcloud_group_handler.create_group(self.room_id),
            SynapseError,
        )

    def test_create_group_with_set_displayname_exception(self):
        self.nextcloud_client.set_group_displayname = AsyncMock(
            side_effect=NextcloudError(code=101, msg="")
        )

        self.get_success(self.nextcloud_group_handler.create_group(self.room_id))

    def test_add_internal_members_to_group(self):
        internal_members = ["partner1", "partner2"]
        self.get_success(
            self.nextcloud_group_handler.add_internal_members_to_group(
                self.room_id, internal_members
            )
        )

        self.assertEquals(
            self.nextcloud_client.add_user_to_group.call_count, len(internal_members)
        )

    def test_add_internal_members_to_group_without_account(self):
        internal_members = ["partner1"]
        self.nextcloud_client.add_user_to_group = AsyncMock(
            side_effect=NextcloudError(code=103, msg="")
        )

        self.get_success(
            self.nextcloud_group_handler.add_internal_members_to_group(
                self.room_id, internal_members
            )
        )

    def test_add_internal_members_to_unexisting_group(self):
        internal_members = ["partner1"]
        self.nextcloud_client.add_user_to_group = AsyncMock(
            side_effect=NextcloudError(code=102, msg="")
        )

        self.get_failure(
            self.nextcloud_group_handler.add_internal_members_to_group(
                self.room_id, internal_members
            ),
            SynapseError,
        )

    def test_update_existing_group_on_invite_membership(self):
        self.get_success(
            self.nextcloud_group_handler.update_group(
                "@second_collaborator:test", self.room_id, "invite"
            )
        )

        self.nextcloud_client.add_user_to_group.assert_called_once()
        self.nextcloud_client.remove_user_from_group.assert_not_called()

    def test_update_existing_group_on_join_membership(self):
        self.get_success(
            self.nextcloud_group_handler.update_group(
                "@second_collaborator:test", self.room_id, "join"
            )
        )

        self.nextcloud_client.add_user_to_group.assert_called_once()
        self.nextcloud_client.remove_user_from_group.assert_not_called()

    def test_update_existing_group_on_leave_membership(self):
        self.get_success(
            self.nextcloud_group_handler.update_group(
                "@second_collaborator:test", self.room_id, "leave"
            )
        )

        self.nextcloud_client.remove_user_from_group.assert_called_once()
        self.nextcloud_client.add_user_to_group.assert_not_called()

    def test_update_existing_group_on_kick_membership(self):
        self.get_success(
            self.nextcloud_group_handler.update_group(
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
            self.nextcloud_group_handler.update_group(
                second_collaborator, self.room_id, "invite"
            )
        )

    def test_update_existing_group_on_leave_membership_with_exception(self):
        self.nextcloud_client.remove_user_from_group = AsyncMock(
            side_effect=NextcloudError(code=103, msg="")
        )
        second_collaborator = "@second_collaborator:test"

        self.get_success(
            self.nextcloud_group_handler.update_group(
                second_collaborator, self.room_id, "leave"
            )
        )


class NextcloudInternalShareHandlerTestCase(HomeserverTestCase):

    servlets = [
        admin.register_servlets,
        login.register_servlets,
        room.register_servlets,
    ]

    def prepare(self, reactor, clock, hs):
        self.nextcloud_bind_handler = hs.get_nextcloud_bind_handler()
        self.nextcloud_share_handler = hs.get_nextcloud_share_handler()
        self.nextcloud_client = hs.get_nextcloud_client()

        self.creator = self.register_user("creator", "pass", admin=True)
        creator_tok = self.login("creator", "pass")
        self.room_id = self.helper.create_room_as(self.creator, tok=creator_tok)

        self.nextcloud_client.add_group = AsyncMock()
        self.nextcloud_client.add_user_to_group = AsyncMock()
        self.nextcloud_client.set_group_display_name = AsyncMock()
        self.nextcloud_client.unshare = AsyncMock()
        self.nextcloud_client.create_internal_share = AsyncMock(
            return_value="internal_share_1"
        )

    def test_create_internal_share(self):
        self.get_success(
            self.nextcloud_share_handler.create_internal_share(
                self.creator, self.room_id, "/new_folder"
            )
        )

        self.nextcloud_client.unshare.assert_not_called()
        self.nextcloud_client.create_internal_share.assert_called_once()

    def test_overwrite_existing_internal_share(self):
        self.get_success(
            self.nextcloud_bind_handler.bind(self.creator, self.room_id, "/folder")
        )
        self.nextcloud_client.create_internal_share.reset_mock()

        self.get_success(
            self.nextcloud_share_handler.create_internal_share(
                self.creator, self.room_id, "/new_folder"
            )
        )

        self.nextcloud_client.unshare.assert_called_once()
        self.nextcloud_client.create_internal_share.assert_called_once()

    def test_create_internal_share_with_unexisting_folder(self):
        self.nextcloud_client.create_internal_share = AsyncMock(
            side_effect=NextcloudError(code=404, msg="")
        )
        self.nextcloud_client.unshare = AsyncMock(
            side_effect=NextcloudError(code=404, msg="")
        )
        self.nextcloud_bind_handler.unbind = AsyncMock()

        error = self.get_failure(
            self.nextcloud_share_handler.create_internal_share(
                self.creator, self.room_id, "/new_folder"
            ),
            SynapseError,
        )

        self.assertEquals(error.value.code, 404)
        self.nextcloud_bind_handler.unbind.assert_called_once()

    def test_create_internal_share_with_other_exceptions(self):
        self.nextcloud_client.create_internal_share = AsyncMock(
            side_effect=NextcloudError(code=400, msg="")
        )
        self.nextcloud_client.unshare = AsyncMock(
            side_effect=NextcloudError(code=404, msg="")
        )
        self.nextcloud_bind_handler.unbind = AsyncMock()

        error = self.get_failure(
            self.nextcloud_share_handler.create_internal_share(
                self.creator, self.room_id, "/new_folder"
            ),
            SynapseError,
        )

        self.assertEquals(error.value.code, 500)
        self.nextcloud_bind_handler.unbind.assert_called_once_with(self.room_id)


class NextcloudPublicShareHandlerTestCase(HomeserverTestCase):

    servlets = [
        admin.register_servlets,
        login.register_servlets,
        room.register_servlets,
    ]

    def prepare(self, reactor, clock, hs):
        self.nextcloud_bind_handler = hs.get_nextcloud_bind_handler()
        self.nextcloud_share_handler = hs.get_nextcloud_share_handler()
        self.nextcloud_client = hs.get_nextcloud_client()

        self.creator = self.register_user("creator", "pass", admin=True)
        self.creator_tok = self.login("creator", "pass")
        self.partner = self.register_user("partner", "pass", is_partner=True)
        self.partner_tok = self.login("partner", "pass")
        self.room_id = self.helper.create_room_as(self.creator, tok=self.creator_tok)

        self.nextcloud_client.unshare = AsyncMock()
        self.nextcloud_client.create_internal_share = AsyncMock(
            return_value="internal_share_1"
        )
        self.nextcloud_client.create_public_link_share = AsyncMock(
            return_value=("public_link_share_1", "https://example.com/12345")
        )

        self.get_success(
            self.nextcloud_share_handler.create_internal_share(
                self.creator, self.room_id, "/folder"
            )
        )

    def _join_room_as_partner(self, partner_id, partner_token):
        self.helper.invite(
            self.room_id, src=self.creator, targ=partner_id, tok=self.creator_tok
        )
        self.helper.join(self.room_id, partner_id, tok=partner_token)

    def test_create_public_link_share(self):
        self.get_success(
            self.nextcloud_share_handler.create_public_link_share(
                self.creator, self.room_id, "/folder"
            )
        )

        self.nextcloud_client.unshare.assert_not_called()
        self.nextcloud_client.create_public_link_share.assert_called_once()

    def test_overwrite_existing_public_link_share(self):
        self.get_success(
            self.nextcloud_share_handler.create_public_link_share(
                self.creator, self.room_id, "/folder"
            )
        )
        self.nextcloud_client.create_public_link_share.reset_mock()

        self.get_success(
            self.nextcloud_share_handler.create_public_link_share(
                self.creator, self.room_id, "/new_folder"
            )
        )

        self.nextcloud_client.unshare.assert_called_once()
        self.nextcloud_client.create_public_link_share.assert_called_once()

    def test_create_public_link_share_with_unexisting_folder(self):
        self.nextcloud_client.create_public_link_share = AsyncMock(
            side_effect=NextcloudError(code=404, msg="")
        )
        self.nextcloud_client.unshare = AsyncMock(
            side_effect=NextcloudError(code=404, msg="")
        )
        self.nextcloud_bind_handler.unbind = AsyncMock()

        error = self.get_failure(
            self.nextcloud_share_handler.create_public_link_share(
                self.creator, self.room_id, "/new_folder"
            ),
            SynapseError,
        )

        self.assertEquals(error.value.code, 404)
        self.nextcloud_bind_handler.unbind.assert_not_called()

    def test_create_public_link_share_with_other_exceptions(self):
        self.nextcloud_client.create_public_link_share = AsyncMock(
            side_effect=NextcloudError(code=400, msg="")
        )
        self.nextcloud_client.unshare = AsyncMock(
            side_effect=NextcloudError(code=404, msg="")
        )
        self.nextcloud_bind_handler.unbind = AsyncMock()

        error = self.get_failure(
            self.nextcloud_share_handler.create_public_link_share(
                self.creator, self.room_id, "/new_folder"
            ),
            SynapseError,
        )

        self.assertEquals(error.value.code, 500)
        self.nextcloud_bind_handler.unbind.assert_not_called()

    def test_handle_public_share_link_on_first_partner_join_room(self):
        self.nextcloud_client.create_public_link_share.reset_mock()
        self._join_room_as_partner(self.partner, self.partner_tok)

        self.nextcloud_client.unshare.assert_not_called()
        self.nextcloud_client.create_public_link_share.assert_called_once()

    def test_handle_public_share_link_on_last_partner_leave_room(self):
        self._join_room_as_partner(self.partner, self.partner_tok)
        self.nextcloud_client.unshare.reset_mock()
        self.nextcloud_client.create_public_link_share.reset_mock()

        self.helper.leave(self.room_id, self.partner, tok=self.partner_tok)

        self.nextcloud_client.unshare.assert_called_once()
        self.nextcloud_client.create_public_link_share.assert_not_called()

    def test_handle_public_share_link_on_not_last_partner_leave_room(self):
        second_partner = self.register_user("second_partner", "pass", is_partner=True)
        second_partner_tok = self.login("second_partner", "pass")

        self._join_room_as_partner(second_partner, second_partner_tok)
        self._join_room_as_partner(self.partner, self.partner_tok)
        self.nextcloud_client.unshare.reset_mock()
        self.nextcloud_client.create_public_link_share.reset_mock()

        self.helper.leave(self.room_id, self.partner, tok=self.partner_tok)

        self.nextcloud_client.unshare.assert_called_once()
        self.nextcloud_client.create_public_link_share.assert_called_once()
