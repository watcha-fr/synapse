from mock import AsyncMock

from synapse.api.errors import SynapseError
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
        share_id = self.get_success(self.store.get_share_id(self.room_id))

        self.nextcloud_client.add_group.assert_called_once()
        self.nextcloud_client.share.assert_called_once()
        self.assertEquals(self.nextcloud_client.add_user_to_group.call_count, 2)
        self.nextcloud_client.unshare.assert_not_called()

    def test_update_an_existing_bind(self):
        self.get_success(self.store.register_share(self.room_id, 2))
        old_share_id = self.get_success(self.store.get_share_id(self.room_id))

        self.assertEqual(old_share_id, 2)

        self.get_success(
            self.nextcloud_handler.bind(self.creator, self.room_id, "/directory2")
        )
        new_share_id = self.get_success(self.store.get_share_id(self.room_id))

        self.nextcloud_client.unshare.assert_called()
        self.assertEqual(new_share_id, 1)

    def test_delete_an_existing_bind(self):
        self.get_success(self.store.register_share(self.room_id, 2))
        self.get_success(self.nextcloud_handler.unbind(self.room_id))
        share_id = self.get_success(self.store.get_share_id(self.room_id))

        self.nextcloud_client.delete_group.assert_called()
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
            "[watcha] add user {} to group {} - failed".format(
                self.creator,
                NEXTCLOUD_GROUP_NAME_PREFIX + self.room_id,
            ),
            cm.output[0],
        )
        self.assertIn(
            "[watcha] add user {} to group {} - failed".format(
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
            "[watcha] add user {} to group {} - failed".format(
                self.creator, group_name
            ),
            cm.output[0],
        )
        self.assertIn(
            "[watcha] add user {} to group {} - failed".format(
                self.inviter, group_name
            ),
            cm.output[1],
        )

    def test_update_existing_nextcloud_share_on_invite_membership(self):
        self.get_success(
            self.nextcloud_handler.update_group(
                "@second_inviter:test", self.room_id, "invite"
            )
        )

        self.nextcloud_client.add_user_to_group.assert_called_once()
        self.nextcloud_client.remove_user_from_group.assert_not_called()

    def test_update_existing_nextcloud_share_on_join_membership(self):
        self.get_success(
            self.nextcloud_handler.update_group(
                "@second_inviter:test", self.room_id, "join"
            )
        )

        self.nextcloud_client.add_user_to_group.assert_called_once()
        self.nextcloud_client.remove_user_from_group.assert_not_called()

    def test_update_existing_nextcloud_share_on_leave_membership(self):
        self.get_success(
            self.nextcloud_handler.update_group(
                "@second_inviter:test", self.room_id, "leave"
            )
        )

        self.nextcloud_client.remove_user_from_group.assert_called_once()
        self.nextcloud_client.add_user_to_group.assert_not_called()

    def test_update_existing_nextcloud_share_on_kick_membership(self):
        self.get_success(
            self.nextcloud_handler.update_group(
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
                self.nextcloud_handler.update_group(
                    second_inviter, self.room_id, "invite"
                )
            )
        self.assertIn(
            "[watcha] add user {} to group {} - failed".format(
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
                self.nextcloud_handler.update_group(
                    second_inviter, self.room_id, "leave"
                )
            )
        self.assertIn(
            "[watcha] remove user {} from group {} - failed".format(
                second_inviter, NEXTCLOUD_GROUP_NAME_PREFIX + self.room_id
            ),
            cm.output[0],
        )
