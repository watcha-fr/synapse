from unittest.mock import AsyncMock, Mock

from synapse.api.errors import HttpResponseException
from synapse.rest import admin
from synapse.rest.client import login

from tests.unittest import HomeserverTestCase


class PartnerStatusFromKeycloakTestCase(HomeserverTestCase):
    """Ce qu'un externe classé par Keycloak devient au-delà de son statut : pas
    d'auto-join, une ligne d'invitation, un compte Nextcloud partenaire. Et ce
    qui arrive quand Keycloak ne répond pas. Les cas de base (statut repris,
    liste blanche, statut qui ne fait que monter) sont dans
    `test_watcha_account_lifecycle`."""

    servlets = [admin.register_servlets, login.register_servlets]

    KEYCLOAK_ID = "8b1f3c"
    EMAIL = "externe@partenaire.example"

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
        self.keycloak_client.is_member_of_group = AsyncMock(return_value=True)
        hs.get_nextcloud_handler().provision_account = AsyncMock()

        oidc_handler = Mock()
        oidc_handler._providers = {"keycloak": Mock()}
        hs._oidc_handler = oidc_handler

        self.auto_join = AsyncMock()
        hs.get_registration_handler()._auto_join_rooms = self.auto_join

        self.admin_id = self.register_user("admin", "pass", admin=True)
        self.auto_join.reset_mock()

    def _declared_by_nextcloud(self, is_admin=False):
        return self.get_success(
            self.handler.register(
                sender_id=self.admin_id,
                email_address=self.EMAIL,
                is_partner=False,
                is_admin=is_admin,
                default_display_name=self.KEYCLOAK_ID,
                nextcloud_username="externe",
                send_email=False,
            )
        )

    def test_partner_from_keycloak_does_not_join_the_auto_join_rooms(self):
        """Le symptôme vu par la ComUE : l'externe entrait d'office dans le
        salon réservé aux internes."""
        self._declared_by_nextcloud()

        self.auto_join.assert_not_called()

    def test_member_from_keycloak_still_joins_the_auto_join_rooms(self):
        self.keycloak_client.is_member_of_group = AsyncMock(return_value=False)

        user_id = self._declared_by_nextcloud()

        self.auto_join.assert_called_once_with(user_id)

    def test_partner_from_keycloak_gets_its_invitation_row(self):
        user_id = self._declared_by_nextcloud()

        invited_by = self.get_success(
            self.store.db_pool.simple_select_onecol(
                table="partners_invitations",
                keyvalues={"user_id": user_id},
                retcol="invited_by",
            )
        )
        self.assertEqual(invited_by, [self.admin_id])

    def test_nextcloud_is_provisioned_as_partner(self):
        self._declared_by_nextcloud()

        provision = self.hs.get_nextcloud_handler().provision_account
        self.assertTrue(provision.call_args.kwargs["is_partner"])

    def test_admin_in_the_partner_group_stays_admin(self):
        user_id = self._declared_by_nextcloud(is_admin=True)

        user = self.get_success(self.store.get_user_by_id(user_id))
        self.assertTrue(user.is_admin)
        self.assertFalse(self.get_success(self.store.is_partner(user_id)))

    def test_new_keycloak_account_does_not_ask_keycloak(self):
        """Sans 409, Synapse crée lui-même le compte Keycloak avec le statut
        demandé : rien à relire."""
        response = Mock()
        response.headers.getRawHeaders.return_value = [
            "https://keycloak/admin/realms/watcha/users/a1b2c3"
        ]
        self.keycloak_client.add_user = AsyncMock(return_value=response)

        self._declared_by_nextcloud()

        self.keycloak_client.is_member_of_group.assert_not_called()

    def test_keycloak_failure_creates_no_account(self):
        """Mieux vaut une déclaration en échec qu'un externe créé membre."""
        self.keycloak_client.is_member_of_group = AsyncMock(
            side_effect=HttpResponseException(500, "Server Error", b"")
        )

        self.get_failure(
            self.handler.register(
                sender_id=self.admin_id,
                email_address=self.EMAIL,
                is_partner=False,
                send_email=False,
            ),
            HttpResponseException,
        )

        user = self.get_success(
            self.store.get_user_by_id("@%s:test" % self.KEYCLOAK_ID)
        )
        self.assertIsNone(user)
        self.auto_join.assert_not_called()


class IsMemberOfGroupTestCase(HomeserverTestCase):
    def prepare(self, reactor, clock, hs):
        self.client = hs.get_keycloak_client()
        self.client._get_header = AsyncMock(return_value={})

    def _groups(self, groups):
        self.client.get_json = AsyncMock(return_value=groups)

    def test_matches_the_top_level_group(self):
        self._groups([{"id": "1", "name": "partner", "path": "/partner"}])

        self.assertTrue(
            self.get_success(self.client.is_member_of_group("u", "partner"))
        )
        uri = self.client.get_json.call_args.kwargs["uri"]
        self.assertTrue(uri.endswith("/users/u/groups"))

    def test_no_group(self):
        self._groups([])

        self.assertFalse(
            self.get_success(self.client.is_member_of_group("u", "partner"))
        )

    def test_a_subgroup_named_partner_does_not_count(self):
        self._groups([{"id": "2", "name": "partner", "path": "/labo/partner"}])

        self.assertFalse(
            self.get_success(self.client.is_member_of_group("u", "partner"))
        )
