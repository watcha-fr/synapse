from unittest.mock import AsyncMock, Mock

from synapse.api.errors import HttpResponseException
from synapse.rest import admin
from synapse.rest.client import login

from tests.unittest import HomeserverTestCase


class AdminCreateUserProvisioningTestCase(HomeserverTestCase):
    """Creating an account from the administration console must also create it in
    Keycloak and Nextcloud, without touching the console itself.

    The account keeps the localpart the administrator chose: the Keycloak UUID is
    recorded as the external id, which the login path resolves on its own.
    """

    servlets = [admin.register_servlets, login.register_servlets]

    KEYCLOAK_ID = "8b1f3c69-7d4b-4a23-bc24-26a441bb0000"

    def prepare(self, reactor, clock, hs):
        self.hs = hs
        self.store = hs.get_datastores().main
        self.handler = hs.get_watcha_registration_handler()

        # `default_config()` declares none of the Watcha flags, so the handler
        # would consider both integrations disabled and skip everything.
        self.handler.config.watcha.managed_idp = True
        self.handler.config.watcha.nextcloud_integration = True

        response = Mock()
        response.headers.getRawHeaders.return_value = [
            f"https://auth.example.com/admin/realms/watcha/users/{self.KEYCLOAK_ID}"
        ]
        self.keycloak_client = self.handler.keycloak_client
        self.keycloak_client.add_user = AsyncMock(return_value=response)
        self.keycloak_client.get_user_by_email = AsyncMock(
            return_value={"id": self.KEYCLOAK_ID, "username": "jdupont"}
        )
        self.provision_account = AsyncMock()
        hs.get_nextcloud_handler().provision_account = self.provision_account

        oidc_handler = Mock()
        oidc_handler._providers = {"keycloak": Mock()}
        hs._oidc_handler = oidc_handler

        self.admin_id = self.register_user("admin", "pass", admin=True)
        self.admin_tok = self.login("admin", "pass")

    def _create(self, localpart="jdupont", body=None):
        if body is None:
            body = {
                "password": "secret",
                "displayname": "Jean Dupont",
                "threepids": [{"medium": "email", "address": "jdupont@example.com"}],
            }
        return self.make_request(
            "PUT",
            f"/_synapse/admin/v2/users/@{localpart}:test",
            body,
            access_token=self.admin_tok,
        )

    def test_creation_provisions_keycloak_and_nextcloud(self):
        channel = self._create()

        self.assertEqual(channel.code, 201, channel.json_body)
        self.keycloak_client.add_user.assert_called_once()
        self.provision_account.assert_called_once()
        self.assertEqual(
            self.provision_account.call_args.kwargs["nextcloud_username"], "jdupont"
        )

    def test_localpart_stays_readable_and_the_uuid_is_the_external_id(self):
        """The whole point: the administrator's identifier survives, and the
        Keycloak UUID is recorded beside it rather than replacing it."""
        self._create()

        user_id = "@jdupont:test"
        external_ids = self.get_success(self.store.get_external_ids_by_user(user_id))
        self.assertEqual(external_ids, [("keycloak", self.KEYCLOAK_ID)])
        self.assertEqual(
            self.get_success(self.store.get_username(user_id)), "jdupont"
        )

    # watcha+
    def test_editing_the_account_keeps_the_nextcloud_mapping(self):
        """The console sends the whole record back, `external_ids` included, so
        every edit replaces the mappings. Losing the Nextcloud name there made
        the column fall back to the Keycloak UUID: the Nextcloud account became
        unreachable, and the deactivation carried in the same request left the
        person's files wide open while every other system showed them locked."""
        self._create()
        user_id = "@jdupont:test"

        channel = self.make_request(
            "PUT",
            f"/_synapse/admin/v2/users/{user_id}",
            {
                "displayname": "Jean Dupont",
                "external_ids": [
                    {"auth_provider": "keycloak", "external_id": self.KEYCLOAK_ID}
                ],
            },
            access_token=self.admin_tok,
        )

        self.assertEqual(channel.code, 200, channel.json_body)
        self.assertEqual(
            self.get_success(self.store.get_username(user_id)), "jdupont"
        )

    def test_deactivating_from_the_console_locks_the_right_nextcloud_account(self):
        """The deactivation travels in the same request as `external_ids`, and
        reads the mapping after it has been rewritten."""
        self._create()
        user_id = "@jdupont:test"

        self.make_request(
            "PUT",
            f"/_synapse/admin/v2/users/{user_id}",
            {
                "deactivated": True,
                "external_ids": [
                    {"auth_provider": "keycloak", "external_id": self.KEYCLOAK_ID}
                ],
            },
            access_token=self.admin_tok,
        )

        self.assertEqual(
            self.get_success(self.store.get_username(user_id)), "jdupont"
        )

    # +watcha

    def test_login_resolves_the_account_from_the_keycloak_uuid(self):
        """A localpart different from the subject must still resolve at login."""
        self._create()

        resolved = self.get_success(
            self.hs.get_sso_handler().get_sso_user_by_remote_user_id(
                "keycloak", self.KEYCLOAK_ID
            )
        )
        self.assertEqual(resolved, "@jdupont:test")

    def test_existing_keycloak_account_is_adopted(self):
        """Keycloak keeps accounts of deactivated users, so a 409 is expected and
        the existing UUID must be reused rather than raising."""
        self.keycloak_client.add_user = AsyncMock(
            side_effect=HttpResponseException(409, "Conflict", b"")
        )

        channel = self._create()

        self.assertEqual(channel.code, 201, channel.json_body)
        external_ids = self.get_success(
            self.store.get_external_ids_by_user("@jdupont:test")
        )
        self.assertEqual(external_ids, [("keycloak", self.KEYCLOAK_ID)])

    def test_account_without_email_is_refused(self):
        """Keycloak needs an address. Failing loudly beats creating the isolated
        Synapse account this change exists to prevent."""
        channel = self._create(body={"password": "secret", "displayname": "Sans mail"})

        self.assertEqual(channel.code, 400, channel.json_body)
        self.keycloak_client.add_user.assert_not_called()

    def test_nextcloud_is_left_alone_when_integration_is_off(self):
        self.handler.config.watcha.nextcloud_integration = False

        self._create()

        self.keycloak_client.add_user.assert_called_once()
        self.provision_account.assert_not_called()

    def test_instance_without_managed_idp_is_untouched(self):
        """An instance with no identity provider must behave exactly as before."""
        self.handler.config.watcha.managed_idp = False

        channel = self._create()

        self.assertEqual(channel.code, 201, channel.json_body)
        self.keycloak_client.add_user.assert_not_called()
        self.provision_account.assert_not_called()
        self.assertEqual(
            self.get_success(self.store.get_external_ids_by_user("@jdupont:test")), []
        )
