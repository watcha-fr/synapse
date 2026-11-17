from unittest.mock import AsyncMock, Mock

from synapse.api.errors import HttpResponseException
from synapse.rest import admin
from synapse.rest.client import login

from tests.unittest import HomeserverTestCase


class RegisterLinkedAccountTestCase(HomeserverTestCase):
    """Le connecteur Nextcloud déclare une personne dont le compte Synapse
    existe déjà sous un autre localpart que son UUID Keycloak (trigramme né par
    SSO, compte créé depuis la console), rattaché par `user_external_ids`.

    Vu à Villeurbanne du 20/10 au 16/11 : 84 comptes `@<uuid>` fantômes, un par
    première visite dans Nextcloud, et un 500 sur ExternalIDReuseException."""

    servlets = [admin.register_servlets, login.register_servlets]

    KEYCLOAK_ID = "0e7a0a8e-1100-4de6-b6d1-582cbf76981e"
    EMAIL = "agent@mairie.example"
    IDP_ID = "oidc"

    def prepare(self, reactor, clock, hs):
        self.store = hs.get_datastores().main
        self.handler = hs.get_watcha_registration_handler()

        self.handler.config.watcha.managed_idp = True
        self.handler.config.watcha.nextcloud_integration = True
        self.handler.config.watcha.partner_email_whitelist = []

        self.keycloak_client = self.handler.keycloak_client
        # La connexion SSO a déjà créé le compte Keycloak.
        self.keycloak_client.add_user = AsyncMock(
            side_effect=HttpResponseException(409, "Conflict", b"")
        )
        self.keycloak_client.get_user_by_email = AsyncMock(
            return_value={"id": self.KEYCLOAK_ID, "username": self.EMAIL}
        )
        self.keycloak_client.is_member_of_group = AsyncMock(return_value=False)
        self.keycloak_client.set_user_enabled = AsyncMock()
        hs.get_nextcloud_handler().provision_account = AsyncMock()
        hs.get_nextcloud_client().set_user_enabled = AsyncMock()

        oidc_handler = Mock()
        oidc_handler._providers = {self.IDP_ID: Mock()}
        hs._oidc_handler = oidc_handler

        self.auto_join = AsyncMock()
        hs.get_registration_handler()._auto_join_rooms = self.auto_join

        self.admin_id = self.register_user("admin", "pass", admin=True)

        # Le compte de la personne : un trigramme, rattaché à son UUID Keycloak.
        self.agent_id = self.register_user("jdu", "pass")
        self.get_success(
            self.store.record_user_external_id(
                self.IDP_ID, self.KEYCLOAK_ID, self.agent_id
            )
        )
        now = self.hs.get_clock().time_msec()
        self.get_success(
            self.store.user_add_threepid(self.agent_id, "email", self.EMAIL, now, now)
        )
        self.auto_join.reset_mock()

    def _declared_by_nextcloud(self):
        return self.get_success(
            self.handler.register(
                sender_id=self.admin_id,
                email_address=self.EMAIL,
                is_partner=False,
                default_display_name=self.KEYCLOAK_ID,
                nextcloud_username=self.KEYCLOAK_ID,
                send_email=False,
            )
        )

    def _uuid_account(self):
        return self.get_success(
            self.store.get_user_by_id("@%s:test" % self.KEYCLOAK_ID)
        )

    def test_linked_account_is_returned(self):
        self.assertEqual(self._declared_by_nextcloud(), self.agent_id)

    def test_no_uuid_account_is_created(self):
        self._declared_by_nextcloud()

        self.assertIsNone(self._uuid_account())
        self.auto_join.assert_not_called()

    def test_declaring_twice_is_harmless(self):
        """Le connecteur rappelle quand il croit avoir échoué."""
        self.assertEqual(self._declared_by_nextcloud(), self.agent_id)
        self.assertEqual(self._declared_by_nextcloud(), self.agent_id)

        self.assertIsNone(self._uuid_account())

    def test_address_is_not_bound_twice(self):
        self._declared_by_nextcloud()

        threepids = self.get_success(self.store.user_get_threepids(self.agent_id))
        self.assertEqual(len(threepids), 1)

    def test_link_is_left_untouched(self):
        self._declared_by_nextcloud()

        user_id = self.get_success(
            self.store.get_user_by_external_id(self.IDP_ID, self.KEYCLOAK_ID)
        )
        self.assertEqual(user_id, self.agent_id)

    def test_deactivated_linked_account_is_reactivated(self):
        """Une personne revenue garde son compte, pas un `@<uuid>` neuf."""
        self.get_success(self.store.set_user_deactivated_status(self.agent_id, True))

        self.assertEqual(self._declared_by_nextcloud(), self.agent_id)

        user = self.get_success(self.store.get_user_by_id(self.agent_id))
        self.assertFalse(user.is_deactivated)
        self.assertIsNone(self._uuid_account())

    def test_unlinked_person_still_gets_a_uuid_account(self):
        """Sans rattachement, rien ne change : le compte prend l'UUID."""
        self.keycloak_client.get_user_by_email = AsyncMock(
            return_value={"id": "a1b2c3", "username": "autre@mairie.example"}
        )

        user_id = self.get_success(
            self.handler.register(
                sender_id=self.admin_id,
                email_address="autre@mairie.example",
                is_partner=False,
                send_email=False,
            )
        )

        self.assertEqual(user_id, "@a1b2c3:test")
        linked = self.get_success(
            self.store.get_user_by_external_id(self.IDP_ID, "a1b2c3")
        )
        self.assertEqual(linked, user_id)
