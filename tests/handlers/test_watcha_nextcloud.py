from unittest.mock import AsyncMock

from synapse.api.errors import HttpResponseException, NextcloudError, SynapseError
from synapse.rest import admin
from synapse.rest.client import login, room
from synapse.types import create_requester

from tests.unittest import HomeserverTestCase


class NextcloudHandlerTestCase(HomeserverTestCase):
    servlets = [
        admin.register_servlets,
        login.register_servlets,
        room.register_servlets,
    ]

    def prepare(self, reactor, clock, hs):
        self.store = hs.get_datastores().main
        self.nextcloud_handler = hs.get_nextcloud_handler()
        self.keycloak_client = self.nextcloud_handler.keycloak_client
        self.nextcloud_client = self.nextcloud_handler.nextcloud_client

        self.creator = self.register_user("creator", "pass", admin=True)
        self.creator_tok = self.login("creator", "pass")
        self.inviter = self.register_user("inviter", "pass")
        inviter_tok = self.login("inviter", "pass")
        # Nextcloud sync is skipped for users without a Nextcloud account, so
        # the mapping has to exist for these tests to exercise the real path.
        self._register_nextcloud_account(self.creator, "creator_nc")
        self._register_nextcloud_account(self.inviter, "inviter_nc")
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

    def _register_nextcloud_account(self, user_id, nextcloud_username):
        self.get_success(
            self.store.record_user_external_id(
                "oidc", nextcloud_username, user_id, nextcloud_username
            )
        )

    def test_unbind(self):
        self.get_success(self.nextcloud_handler.unbind(self.creator, self.room_id))
        share_id = self.get_success(self.store.get_share_id(self.room_id))

        self.nextcloud_client.delete_group.assert_called_once_with(self.group_id)
        self.assertIsNone(share_id)

    def test_unbind_with_unexisting_group(self):
        self.nextcloud_client.delete_group = AsyncMock(
            side_effect=NextcloudError(code=101, msg="")
        )
        self.get_success(self.nextcloud_handler.unbind(self.creator, self.room_id))
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
        self.nextcloud_handler.unbind.assert_called_once_with(
            self.creator, self.room_id
        )

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
            self.nextcloud_handler.update_group(self.inviter, self.room_id, "join")
        )

        self.nextcloud_client.add_user_to_group.assert_called_once()
        self.nextcloud_client.remove_user_from_group.assert_not_called()

    def test_update_existing_group_on_leave_membership(self):
        self.get_success(
            self.nextcloud_handler.update_group(self.inviter, self.room_id, "leave")
        )

        self.nextcloud_client.remove_user_from_group.assert_called_once()
        self.nextcloud_client.add_user_to_group.assert_not_called()

    def test_update_existing_group_on_kick_membership(self):
        self.get_success(
            self.nextcloud_handler.update_group(self.inviter, self.room_id, "kick")
        )

        self.nextcloud_client.remove_user_from_group.assert_called_once()
        self.nextcloud_client.add_user_to_group.assert_not_called()

    def test_update_existing_group_on_join_membership_with_exception(self):
        self.nextcloud_client.add_user_to_group = AsyncMock(
            side_effect=NextcloudError(code=103, msg="")
        )

        self.get_success(
            self.nextcloud_handler.update_group(self.inviter, self.room_id, "join")
        )

    def test_update_existing_group_on_leave_membership_with_exception(self):
        self.nextcloud_client.remove_user_from_group = AsyncMock(
            side_effect=NextcloudError(code=103, msg="")
        )

        self.get_success(
            self.nextcloud_handler.update_group(self.inviter, self.room_id, "leave")
        )


    # Nextcloud account provisioning
    # ==============================

    def test_provision_account_creates_the_account(self):
        """Single implementation shared by the invitation flow and SSO. SSO used to
        create the account under the Matrix localpart while recording a different
        identifier in the mapping, which made every later group call fail with 103."""
        self.nextcloud_client.add_user = AsyncMock()

        self.assertTrue(
            self.get_success(
                self.nextcloud_handler.provision_account(
                    nextcloud_username="cfau",
                    displayname="C. Fau",
                    email="c.fau@example.org",
                )
            )
        )
        self.nextcloud_client.add_user.assert_called_once_with(
            "cfau", "C. Fau", "c.fau@example.org", False, None
        )

    def test_provision_account_is_idempotent(self):
        """An account that already exists is a success: the client maps OCS 102
        "username already exists" to a warning rather than an error."""
        self.nextcloud_client.add_user = AsyncMock()

        for _ in range(3):
            self.assertTrue(
                self.get_success(
                    self.nextcloud_handler.provision_account(nextcloud_username="cfau")
                )
            )

    def test_provision_account_refuses_an_empty_username(self):
        """Guards against the `POST /cloud/users/None/groups` class of bug."""
        self.nextcloud_client.add_user = AsyncMock()

        self.assertFalse(
            self.get_success(
                self.nextcloud_handler.provision_account(nextcloud_username="")
            )
        )
        self.nextcloud_client.add_user.assert_not_called()

    def test_no_account_for_a_partner_when_external_auth_is_disabled(self):
        self.nextcloud_handler.config.watcha.external_authentication_for_partners = False
        self.nextcloud_client.add_user = AsyncMock()

        self.assertFalse(
            self.get_success(
                self.nextcloud_handler.provision_account(
                    nextcloud_username="ext", is_partner=True
                )
            )
        )
        self.nextcloud_client.add_user.assert_not_called()

    def test_account_for_a_partner_when_external_auth_is_enabled(self):
        self.nextcloud_handler.config.watcha.external_authentication_for_partners = True
        self.nextcloud_client.add_user = AsyncMock()

        self.assertTrue(
            self.get_success(
                self.nextcloud_handler.provision_account(
                    nextcloud_username="ext", is_partner=True
                )
            )
        )

    def test_no_account_when_nextcloud_integration_is_disabled(self):
        self.nextcloud_handler.config.watcha.nextcloud_integration = False
        self.nextcloud_client.add_user = AsyncMock()

        self.assertFalse(
            self.get_success(
                self.nextcloud_handler.provision_account(nextcloud_username="cfau")
            )
        )
        self.nextcloud_client.add_user.assert_not_called()

    # Group synchronisation must not fail silently
    # ============================================

    def test_join_without_a_mapping_never_sends_none_as_an_identifier(self):
        """`POST /cloud/users/None/groups` was issued on every first SSO login,
        because the membership was processed before the mapping was persisted."""
        stranger = self.register_user("stranger", "pass")

        self.get_success(
            self.nextcloud_handler.update_group(stranger, self.room_id, "join")
        )

        self.nextcloud_client.add_user_to_group.assert_not_called()

    def test_a_missing_nextcloud_account_is_provisioned_then_retried(self):
        """The 67 broken accounts: a valid mapping pointing at an account that
        does not exist. Repaired instead of being logged and forgotten."""
        self.nextcloud_client.add_user = AsyncMock()
        self.nextcloud_client.add_user_to_group = AsyncMock(
            side_effect=[NextcloudError(code=103, msg=""), None]
        )

        self.get_success(
            self.nextcloud_handler.update_group(self.inviter, self.room_id, "join")
        )

        self.nextcloud_client.add_user.assert_called_once()
        self.assertEqual(self.nextcloud_client.add_user_to_group.call_count, 2)

    def test_a_missing_group_is_recreated_then_retried(self):
        """A room that still holds a share but whose Nextcloud group is gone."""
        self.nextcloud_client.add_user_to_group = AsyncMock(
            side_effect=[NextcloudError(code=102, msg=""), None]
        )

        self.get_success(
            self.nextcloud_handler.update_group(self.inviter, self.room_id, "join")
        )

        self.nextcloud_client.add_group.assert_called_once_with(self.group_id)
        self.assertEqual(self.nextcloud_client.add_user_to_group.call_count, 2)

    def test_a_failure_surviving_the_repair_does_not_raise(self):
        """The member is in the room either way; the join must not fail. The point
        of the fix is that the failure is now logged as an error and counted."""
        self.nextcloud_client.add_user = AsyncMock()
        self.nextcloud_client.add_user_to_group = AsyncMock(
            side_effect=NextcloudError(code=103, msg="")
        )

        self.get_success(
            self.nextcloud_handler.update_group(self.inviter, self.room_id, "join")
        )

        self.assertEqual(self.nextcloud_client.add_user_to_group.call_count, 2)

    def test_the_mapping_is_persisted_before_any_auto_join(self):
        """Ordering guarantee behind B.2: an auto-join room holding a shared folder
        triggers a group sync during register_user, so the mapping must already be
        there when it runs."""
        seen = []

        async def before_auto_join(user_id):
            seen.append(("callback", user_id))

        original_auto_join = self.hs.get_registration_handler()._auto_join_rooms

        async def spy_auto_join(user_id):
            seen.append(("auto_join", user_id))
            return await original_auto_join(user_id)

        self.hs.get_registration_handler()._auto_join_rooms = spy_auto_join

        user_id = self.get_success(
            self.hs.get_registration_handler().register_user(
                localpart="ordered",
                before_auto_join=before_auto_join,
            )
        )

        self.assertEqual(seen[0], ("callback", user_id))
        self.assertIn(("auto_join", user_id), seen)

    # Room upgrade
    # ============

    def test_upgrade_carries_the_folder_binding_to_the_new_room(self):
        """The binding is keyed on the room id, so without this an upgraded room
        silently loses its document space."""
        self.helper.send_state(
            self.room_id,
            "im.vector.web.settings",
            {
                "nextcloudShare": "https://nextcloud.example.org/apps/files?dir=/folder&fileid=59"
            },
            tok=self.creator_tok,
        )
        new_room_id = self.helper.create_room_as(self.creator, tok=self.creator_tok)
        requester = create_requester(self.creator)

        self.get_success(
            self.nextcloud_handler.transfer_share_on_room_upgrade(
                requester, self.room_id, new_room_id
            )
        )

        # The new room is bound to the same folder, through its own group.
        self.nextcloud_client.share.assert_called_once()
        _, path, group_id = self.nextcloud_client.share.call_args.args
        self.assertEqual(path, "/folder")
        self.assertEqual(
            group_id, self.get_success(self.nextcloud_handler.build_group_id(new_room_id))
        )

    def test_upgrade_does_nothing_when_the_old_room_had_no_folder(self):
        unbound_room_id = self.helper.create_room_as(self.creator, tok=self.creator_tok)
        new_room_id = self.helper.create_room_as(self.creator, tok=self.creator_tok)

        self.get_success(
            self.nextcloud_handler.transfer_share_on_room_upgrade(
                create_requester(self.creator), unbound_room_id, new_room_id
            )
        )

        self.nextcloud_client.share.assert_not_called()

    def test_upgrade_does_not_fail_when_the_folder_path_is_unknown(self):
        """The share is registered but the room state carries no folder URL: log
        and move on rather than breaking the upgrade."""
        self.get_success(
            self.nextcloud_handler.transfer_share_on_room_upgrade(
                create_requester(self.creator),
                self.room_id,
                self.helper.create_room_as(self.creator, tok=self.creator_tok),
            )
        )

        self.nextcloud_client.share.assert_not_called()

    def test_upgrade_does_not_fail_when_nextcloud_is_unavailable(self):
        self.helper.send_state(
            self.room_id,
            "im.vector.web.settings",
            {"nextcloudShare": "https://nextcloud.example.org/apps/files?dir=/folder"},
            tok=self.creator_tok,
        )
        self.nextcloud_client.share = AsyncMock(
            side_effect=NextcloudError(code=404, msg="")
        )

        # An upgrade must not fail because Nextcloud is down.
        self.get_success(
            self.nextcloud_handler.transfer_share_on_room_upgrade(
                create_requester(self.creator),
                self.room_id,
                self.helper.create_room_as(self.creator, tok=self.creator_tok),
            )
        )

    # Folder resolution by stable identifier
    # ======================================

    def test_get_room_folder_returns_the_file_id_and_mounted_path(self):
        """The client must address the folder by file id: a mount name is
        per-recipient, so a name resolved for one member 404s for another."""
        self.nextcloud_client.get_room_folder = AsyncMock(
            return_value={
                "status": "ok",
                "fileId": 59,
                "path": "/FACILITATEURS",
                "shareId": "59",
            }
        )

        folder = self.get_success(
            self.nextcloud_handler.get_room_folder(self.room_id, self.inviter)
        )

        self.nextcloud_client.get_room_folder.assert_called_once_with(
            self.room_id, "inviter_nc"
        )
        self.assertEqual(folder["fileId"], 59)
        self.assertEqual(folder["path"], "/FACILITATEURS")

    def test_get_room_folder_fails_without_a_nextcloud_account(self):
        stranger = self.register_user("stranger2", "pass")
        self.nextcloud_client.get_room_folder = AsyncMock()

        self.get_failure(
            self.nextcloud_handler.get_room_folder(self.room_id, stranger),
            SynapseError,
        )

    def test_get_room_folder_surfaces_a_nextcloud_failure(self):
        """Unlike the write paths this must not be swallowed: a user is waiting in
        front of the panel and needs to be told something."""
        self.nextcloud_client.get_room_folder = AsyncMock(
            side_effect=NextcloudError(code=104, msg="")
        )

        self.get_failure(
            self.nextcloud_handler.get_room_folder(self.room_id, self.inviter),
            SynapseError,
        )

    def test_get_room_folder_is_retried_on_a_transient_failure(self):
        self.nextcloud_client.get_room_folder = AsyncMock(
            side_effect=[
                HttpResponseException(503, "Service Unavailable", b""),
                {"status": "ok", "fileId": 59, "path": "/x", "shareId": "59"},
            ]
        )

        folder = self.get_success(
            self.nextcloud_handler.get_room_folder(self.room_id, self.inviter),
            by=1.0,
        )

        self.assertEqual(folder["fileId"], 59)
        self.assertEqual(self.nextcloud_client.get_room_folder.call_count, 2)

