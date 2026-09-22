from unittest.mock import AsyncMock, Mock

from synapse.api.errors import HttpResponseException
from synapse.rest import admin
from synapse.rest.client import login
from synapse.types import create_requester

from tests.unittest import HomeserverTestCase


class NextcloudUsernameTestCase(HomeserverTestCase):
    """An invited account must get a readable Nextcloud name instead of the
    Keycloak UUID, while the UUID stays the identity pivot."""

    servlets = [admin.register_servlets, login.register_servlets]

    def prepare(self, reactor, clock, hs):
        self.hs = hs
        self.store = hs.get_datastores().main
        self.handler = hs.get_watcha_registration_handler()

        # `default_config()` declares none of the Watcha flags, so the handler
        # would consider both integrations disabled and skip everything.
        self.handler.config.watcha.managed_idp = True
        self.handler.config.watcha.nextcloud_integration = True

        self.keycloak_client = self.handler.keycloak_client
        self.keycloak_client.add_user = AsyncMock(
            side_effect=self._mint_keycloak_user
        )
        self.minted = []

        self.provision_account = AsyncMock()
        hs.get_nextcloud_handler().provision_account = self.provision_account

        # Désactiver un compte verrouille aussi Keycloak et Nextcloud.
        self.keycloak_client.set_user_enabled = AsyncMock()
        hs.get_nextcloud_client().set_user_enabled = AsyncMock()

        oidc_handler = Mock()
        oidc_handler._providers = {"keycloak": Mock()}
        hs._oidc_handler = oidc_handler

        self.admin_id = self.register_user("admin", "pass", admin=True)

    def _mint_keycloak_user(self, *args, **kwargs):
        """Stands in for Keycloak: hands back a fresh UUID in the location header."""
        uuid = f"uuid-{len(self.minted)}"
        self.minted.append((args, kwargs))
        response = Mock()
        response.headers.getRawHeaders.return_value = [
            f"https://auth.example.com/admin/realms/watcha/users/{uuid}"
        ]
        return response

    def _register(self, email_address):
        return self.get_success(
            self.handler.register(
                sender_id=self.admin_id, email_address=email_address
            )
        )

    def test_the_name_comes_from_the_address(self):
        user_id = self._register("jean.dupont@example.com")

        self.assertEqual(
            self.get_success(self.store.get_username(user_id)), "jean.dupont"
        )
        self.assertEqual(
            self.provision_account.call_args.kwargs["nextcloud_username"],
            "jean.dupont",
        )

    # watcha+
    def test_the_name_follows_the_keycloak_username(self):
        """One rule for every creation path: the Nextcloud name is derived from
        the Keycloak username. `add_user` names the account
        `keycloak_username or email_address`, so deriving from the address alone
        gave a person two different readable names as soon as the caller imposed
        one on Keycloak — the import does exactly that."""
        user_id = self.get_success(
            self.handler.register(
                sender_id=self.admin_id,
                email_address="d.lamarche+ri04@teamnet-fr.com",
                keycloak_username="recette-kc-01",
            )
        )

        self.assertEqual(
            self.get_success(self.store.get_username(user_id)), "recette-kc-01"
        )
        self.assertEqual(
            self.provision_account.call_args.kwargs["nextcloud_username"],
            "recette-kc-01",
        )

    def test_the_address_still_decides_without_a_keycloak_username(self):
        """The invitation path passes none, and must keep deriving as before."""
        user_id = self._register("d.lamarche+rc14@teamnet-fr.com")

        self.assertEqual(
            self.get_success(self.store.get_username(user_id)), "d.lamarcherc14"
        )

    # +watcha

    def test_the_mxid_stays_an_uuid(self):
        """Only the Nextcloud name becomes readable; the Matrix identity does not."""
        user_id = self._register("jean.dupont@example.com")

        self.assertEqual(user_id, "@uuid-0:test")

    def test_keycloak_carries_the_name_as_an_attribute(self):
        """Without the attribute, the claim falls back to the subject at login."""
        self._register("jean.dupont@example.com")

        args, _ = self.minted[0]
        self.assertEqual(args[-1], "jean.dupont")

    def test_a_second_person_with_the_same_prefix_is_deduplicated(self):
        first = self._register("jean.dupont@example.com")
        second = self._register("jean.dupont@autre.fr")

        self.assertEqual(
            self.get_success(self.store.get_username(first)), "jean.dupont"
        )
        self.assertEqual(
            self.get_success(self.store.get_username(second)), "jean.dupont2"
        )

    def test_an_address_yielding_nothing_usable_falls_back(self):
        user_id = self._register("!!!@example.com")

        self.assertEqual(self.get_success(self.store.get_username(user_id)), "user")

    def test_the_welcome_email_can_be_suppressed(self):
        """La console laisse le choix ; l'invitation, elle, l'envoie toujours."""
        self.handler.mailer = Mock()
        self.handler.mailer.send_watcha_registration_mail = AsyncMock()

        self._register("avec.mail@example.com")
        self.assertEqual(
            self.handler.mailer.send_watcha_registration_mail.await_count, 1
        )

        self.get_success(
            self.handler.register(
                sender_id=self.admin_id,
                email_address="sans.mail@example.com",
                send_email=False,
            )
        )
        # Toujours une seule : la seconde création n'a rien envoyé.
        self.assertEqual(
            self.handler.mailer.send_watcha_registration_mail.await_count, 1
        )

    def test_an_imposed_name_wins_over_the_derivation(self):
        """The Nextcloud connector imposes it: the account already exists there
        under that name, and deriving another would create a second one."""
        user_id = self.get_success(
            self.handler.register(
                sender_id=self.admin_id,
                email_address="jean.dupont@example.com",
                nextcloud_username="jdupont-nc",
            )
        )

        self.assertEqual(
            self.get_success(self.store.get_username(user_id)), "jdupont-nc"
        )
        self.assertEqual(
            self.provision_account.call_args.kwargs["nextcloud_username"],
            "jdupont-nc",
        )

    def test_a_reactivated_account_keeps_the_name_it_had(self):
        """Deriving a fresh name for a returning person would leave them a second
        Nextcloud account beside their own."""
        user_id = self._register("jean.dupont@example.com")
        self.get_success(
            self.hs.get_deactivate_account_handler().deactivate_account(
                user_id,
                erase_data=False,
                requester=create_requester(user_id),
                by_admin=True,
            )
        )

        # Keycloak keeps the account, so creating it again answers 409.
        self.keycloak_client.add_user = AsyncMock(
            side_effect=HttpResponseException(409, "Conflict", b"")
        )
        self.keycloak_client.get_user_by_email = AsyncMock(
            return_value={"id": "uuid-0", "username": "jean.dupont"}
        )
        self.provision_account.reset_mock()

        again = self._register("jean.dupont@example.com")

        self.assertEqual(again, user_id)
        self.assertEqual(
            self.get_success(self.store.get_username(user_id)), "jean.dupont"
        )
        self.assertEqual(
            self.provision_account.call_args.kwargs["nextcloud_username"],
            "jean.dupont",
        )
