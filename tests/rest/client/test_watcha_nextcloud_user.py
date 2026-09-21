from unittest.mock import AsyncMock, Mock

from synapse.api.errors import NextcloudError
from synapse.rest import admin
from synapse.rest.client import login, watcha

from tests.unittest import HomeserverTestCase


class WatchaNextcloudUserTestCase(HomeserverTestCase):
    """What the Nextcloud connector reports about an account there.

    Deleting it is an explicit, destructive gesture: Keycloak goes with it and
    Synapse is erased. Merely disabling it stays reversible.
    """

    servlets = [
        admin.register_servlets,
        login.register_servlets,
        watcha.register_servlets,
    ]

    KEYCLOAK_ID = "8b1f3c69"
    NEXTCLOUD_NAME = "jdupont"

    def prepare(self, reactor, clock, hs):
        self.store = hs.get_datastores().main
        self.lifecycle = hs.get_account_lifecycle_handler()

        # `default_config()` declares none of the Watcha flags, so the handler
        # would consider both integrations disabled and skip everything.
        self.lifecycle.config.watcha.managed_idp = True
        self.lifecycle.config.watcha.nextcloud_integration = True

        self.keycloak_client = self.lifecycle.keycloak_client
        self.keycloak_client.set_user_enabled = AsyncMock()
        self.keycloak_client.delete_user = AsyncMock()
        self.nextcloud_client = self.lifecycle.nextcloud_client
        self.nextcloud_client.set_user_enabled = AsyncMock()
        self.nextcloud_client.delete_user = AsyncMock()

        self.admin_id = self.register_user("admin", "pass", admin=True)
        self.admin_tok = self.login("admin", "pass")

        self.user_id = self.register_user(self.KEYCLOAK_ID, "pass")
        self.get_success(
            self.store.record_user_external_id(
                "oidc", self.KEYCLOAK_ID, self.user_id, self.NEXTCLOUD_NAME
            )
        )

    def _post(self, action, nextcloud_username=None):
        return self.make_request(
            "POST",
            "/_matrix/client/r0/watcha_nextcloud_user",
            {
                "nextcloud_username": nextcloud_username or self.NEXTCLOUD_NAME,
                "action": action,
            },
            access_token=self.admin_tok,
        )

    def test_disabling_there_disables_here(self):
        channel = self._post("disable")

        self.assertEqual(channel.code, 200, channel.json_body)
        self.assertEqual(channel.json_body["user_id"], self.user_id)

        user = self.get_success(self.store.get_user_by_id(self.user_id))
        self.assertTrue(user.is_deactivated)
        self.assertFalse(self.get_success(self.store.is_user_erased(self.user_id)))
        self.keycloak_client.set_user_enabled.assert_called_once_with(
            self.KEYCLOAK_ID, False
        )
        self.keycloak_client.delete_user.assert_not_called()

    def test_enabling_there_brings_the_account_back(self):
        self._post("disable")
        self.keycloak_client.set_user_enabled.reset_mock()

        channel = self._post("enable")

        self.assertEqual(channel.code, 200, channel.json_body)
        user = self.get_success(self.store.get_user_by_id(self.user_id))
        self.assertFalse(user.is_deactivated)
        self.keycloak_client.set_user_enabled.assert_called_once_with(
            self.KEYCLOAK_ID, True
        )

    def test_deleting_there_erases_here_and_drops_keycloak(self):
        channel = self._post("delete")

        self.assertEqual(channel.code, 200, channel.json_body)

        user = self.get_success(self.store.get_user_by_id(self.user_id))
        self.assertTrue(user.is_deactivated)
        self.assertTrue(self.get_success(self.store.is_user_erased(self.user_id)))
        self.keycloak_client.delete_user.assert_called_once_with(self.KEYCLOAK_ID)

    def test_a_deleted_nextcloud_account_does_not_abort_the_deletion(self):
        """The account is gone there — that is the whole point of the call — so
        deleting it answers 101. Treating that as a failure would leave the
        Matrix account untouched."""
        self.nextcloud_client.delete_user = AsyncMock(
            side_effect=NextcloudError(101, "user does not exist")
        )

        channel = self._post("delete")

        self.assertEqual(channel.code, 200, channel.json_body)
        self.assertTrue(self.get_success(self.store.is_user_erased(self.user_id)))
        self.keycloak_client.delete_user.assert_called_once_with(self.KEYCLOAK_ID)

    def test_another_nextcloud_failure_still_aborts(self):
        """A permission or transport problem must not pass for success."""
        self.nextcloud_client.set_user_enabled = AsyncMock(
            side_effect=NextcloudError(997, "unauthorised")
        )

        channel = self._post("disable")

        self.assertEqual(channel.code, 500, channel.json_body)
        user = self.get_success(self.store.get_user_by_id(self.user_id))
        self.assertFalse(user.is_deactivated)

    def test_an_unknown_name_is_reported_without_touching_anything(self):
        channel = self._post("delete", nextcloud_username="personne")

        self.assertEqual(channel.code, 200, channel.json_body)
        self.assertIsNone(channel.json_body["user_id"])
        self.keycloak_client.delete_user.assert_not_called()

    def test_an_unknown_action_is_refused(self):
        channel = self._post("incinerate")

        self.assertEqual(channel.code, 400, channel.json_body)

    def test_a_plain_user_may_not_call_it(self):
        self.register_user("bob", "pass")
        bob_tok = self.login("bob", "pass")

        channel = self.make_request(
            "POST",
            "/_matrix/client/r0/watcha_nextcloud_user",
            {"nextcloud_username": self.NEXTCLOUD_NAME, "action": "delete"},
            access_token=bob_tok,
        )

        self.assertEqual(channel.code, 403, channel.json_body)
        self.keycloak_client.delete_user.assert_not_called()
