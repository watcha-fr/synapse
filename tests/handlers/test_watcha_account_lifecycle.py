from unittest.mock import AsyncMock, Mock

from synapse.api.errors import HttpResponseException, NextcloudError
from synapse.rest import admin
from synapse.rest.client import login
from synapse.types import UserID, create_requester

from tests.unittest import HomeserverTestCase


class AccountLifecycleTestCase(HomeserverTestCase):
    """Deactivating a Synapse account locks the Keycloak and Nextcloud accounts
    bound to it, and reactivating unlocks them. Nothing is ever deleted."""

    servlets = [admin.register_servlets, login.register_servlets]

    def prepare(self, reactor, clock, hs):
        self.store = hs.get_datastores().main
        self.handler = hs.get_account_lifecycle_handler()
        self.deactivate_handler = hs.get_deactivate_account_handler()

        # `default_config()` declares none of the Watcha flags, so the handler
        # would consider both integrations disabled and skip everything.
        self.handler.config.watcha.managed_idp = True
        self.handler.config.watcha.nextcloud_integration = True

        self.keycloak_client = self.handler.keycloak_client
        self.nextcloud_client = self.handler.nextcloud_client
        self.keycloak_client.set_user_enabled = AsyncMock()
        self.nextcloud_client.set_user_enabled = AsyncMock()
        self.keycloak_client.delete_user = AsyncMock()
        self.nextcloud_client.delete_user = AsyncMock()

        self.user_id = self.register_user("8b1f3c", "pass")
        self.get_success(
            self.store.record_user_external_id(
                "oidc", "8b1f3c", self.user_id, "jdupont"
            )
        )

    def _deactivate(self, user_id):
        self.get_success(
            self.deactivate_handler.deactivate_account(
                user_id,
                erase_data=False,
                requester=create_requester(user_id),
                by_admin=True,
            )
        )

    def test_deactivation_locks_both_accounts(self):
        self._deactivate(self.user_id)

        self.keycloak_client.set_user_enabled.assert_called_once_with("8b1f3c", False)
        self.nextcloud_client.set_user_enabled.assert_called_once_with("jdupont", False)

    def test_reactivation_unlocks_both_accounts(self):
        self.get_success(self.deactivate_handler.activate_account(self.user_id))

        self.keycloak_client.set_user_enabled.assert_called_once_with("8b1f3c", True)
        self.nextcloud_client.set_user_enabled.assert_called_once_with("jdupont", True)

    # watcha+
    def _lock(self, locked):
        self.get_success(self.handler.set_account_locked(self.user_id, locked))

    def test_locking_suspends_the_three_systems(self):
        self._lock(True)

        self.keycloak_client.set_user_enabled.assert_called_once_with("8b1f3c", False)
        self.nextcloud_client.set_user_enabled.assert_called_once_with("jdupont", False)
        self.assertTrue(self.get_success(self.store.get_user_locked_status(self.user_id)))

    def test_unlocking_restores_the_three_systems(self):
        self._lock(True)
        self.keycloak_client.set_user_enabled.reset_mock()
        self.nextcloud_client.set_user_enabled.reset_mock()

        self._lock(False)

        self.keycloak_client.set_user_enabled.assert_called_once_with("8b1f3c", True)
        self.nextcloud_client.set_user_enabled.assert_called_once_with("jdupont", True)
        self.assertFalse(
            self.get_success(self.store.get_user_locked_status(self.user_id))
        )

    def test_locking_destroys_nothing(self):
        """Tout l'intérêt du verrou : il se lève sans rien avoir à reconstruire.
        La désactivation, elle, sort la personne de ses salons et efface son
        adresse comme son mot de passe, et rien ne les lui rend au retour."""
        self.get_success(
            self.store.user_add_threepid(
                self.user_id, "email", "jdupont@example.org", 0, 0
            )
        )

        self._lock(True)

        user = self.get_success(self.store.get_user_by_id(self.user_id))
        self.assertFalse(user.is_deactivated)
        self.assertIsNotNone(
            self.get_success(self.store.get_user_by_id(self.user_id))
        )
        self.assertEqual(
            len(self.get_success(self.store.user_get_threepids(self.user_id))), 1
        )
        self.assertIsNotNone(
            self.get_success(self.store.get_user_by_id(self.user_id)).password_hash
        )

    def test_locking_drops_the_pushers(self):
        """Le verrou n'arrête pas les notifications de lui-même : une personne
        suspendue continuerait d'être notifiée de messages qu'elle ne peut pas
        ouvrir."""
        pusher_pool = self.hs.get_pusherpool()
        pusher_pool.delete_all_pushers_for_user = AsyncMock()

        self._lock(True)

        pusher_pool.delete_all_pushers_for_user.assert_called_once_with(self.user_id)

    def test_unlocking_leaves_the_pushers_alone(self):
        pusher_pool = self.hs.get_pusherpool()
        pusher_pool.delete_all_pushers_for_user = AsyncMock()

        self._lock(False)

        pusher_pool.delete_all_pushers_for_user.assert_not_called()

    def test_disabling_in_nextcloud_locks_rather_than_deactivates(self):
        """Le geste venu de Nextcloud doit être réversible lui aussi."""
        self.get_success(
            self.handler.handle_nextcloud_change(
                "jdupont", "disable", create_requester(self.user_id)
            )
        )

        user = self.get_success(self.store.get_user_by_id(self.user_id))
        self.assertTrue(
            self.get_success(self.store.get_user_locked_status(self.user_id))
        )
        self.assertFalse(user.is_deactivated)

    def test_enabling_in_nextcloud_lifts_the_lock(self):
        self._lock(True)

        self.get_success(
            self.handler.handle_nextcloud_change(
                "jdupont", "enable", create_requester(self.user_id)
            )
        )

        self.assertFalse(
            self.get_success(self.store.get_user_locked_status(self.user_id))
        )

    # +watcha

    def test_erasing_deletes_both_accounts_instead_of_locking_them(self):
        """Le geste est le même d'où qu'il parte : un effacement supprime les
        comptes Keycloak et Nextcloud, là où une simple désactivation se
        contente de les verrouiller."""
        self.get_success(
            self.deactivate_handler.deactivate_account(
                self.user_id,
                erase_data=True,
                requester=create_requester(self.user_id),
                by_admin=True,
            )
        )

        self.nextcloud_client.delete_user.assert_called_once_with("jdupont")
        self.keycloak_client.delete_user.assert_called_once_with("8b1f3c")
        self.keycloak_client.set_user_enabled.assert_not_called()
        self.nextcloud_client.set_user_enabled.assert_not_called()

    def test_a_failed_nextcloud_deletion_spares_the_keycloak_identity(self):
        """Nextcloud passe en premier parce que c'est la moitié irréversible :
        si elle échoue, l'identité doit rester intacte et réessayable."""
        self.nextcloud_client.delete_user = AsyncMock(
            side_effect=NextcloudError(997, "unauthorised")
        )

        self.get_failure(
            self.deactivate_handler.deactivate_account(
                self.user_id,
                erase_data=True,
                requester=create_requester(self.user_id),
                by_admin=True,
            ),
            NextcloudError,
        )

        self.keycloak_client.delete_user.assert_not_called()
        user = self.get_success(self.store.get_user_by_id(self.user_id))
        self.assertFalse(user.is_deactivated)

    # watcha+
    def test_erasing_gives_the_nextcloud_name_back(self):
        """Le rattachement survit au compte — un localpart Matrix reste pris à
        vie — mais le nom Nextcloud n'a plus rien à désigner. Le garder le
        réservait pour rien, et la même personne revenue ramassait un suffixe à
        chaque passage : `dupont`, puis `dupont2`, puis `dupont3`."""
        self.get_success(
            self.deactivate_handler.deactivate_account(
                self.user_id,
                erase_data=True,
                requester=create_requester(self.user_id),
                by_admin=True,
            )
        )

        self.assertIsNone(self.get_success(self.store.get_username(self.user_id)))
        self.assertFalse(
            self.get_success(self.store.is_nextcloud_username_taken("jdupont"))
        )

    def test_a_failed_deletion_keeps_the_nextcloud_name(self):
        """Le nom n'est rendu qu'une fois le compte réellement supprimé : sinon
        un échec laisserait un rattachement amputé, et le geste ne serait plus
        réessayable."""
        self.nextcloud_client.delete_user = AsyncMock(
            side_effect=NextcloudError(997, "unauthorised")
        )

        self.get_failure(
            self.deactivate_handler.deactivate_account(
                self.user_id,
                erase_data=True,
                requester=create_requester(self.user_id),
                by_admin=True,
            ),
            NextcloudError,
        )

        self.assertEqual(
            self.get_success(self.store.get_username(self.user_id)), "jdupont"
        )

    def test_an_already_deleted_nextcloud_account_does_not_abort_the_deletion(self):
        """La suppression partie de Nextcloud y trouve forcément le compte déjà
        disparu. `delete` répond 998 là où `enable`/`disable` répondent 101 : ne
        tolérer que 101 faisait remonter une 500, et Keycloak comme Matrix
        survivaient à un compte pourtant supprimé."""
        self.nextcloud_client.delete_user = AsyncMock(
            side_effect=NextcloudError(998, "The requested user could not be found")
        )

        self.get_success(
            self.deactivate_handler.deactivate_account(
                self.user_id,
                erase_data=True,
                requester=create_requester(self.user_id),
                by_admin=True,
            )
        )

        self.keycloak_client.delete_user.assert_called_once_with("8b1f3c")
        user = self.get_success(self.store.get_user_by_id(self.user_id))
        self.assertTrue(user.is_deactivated)

    # +watcha

    def test_local_account_is_skipped(self):
        """An account with no external identity has nothing to lock elsewhere."""
        local_user = self.register_user("local", "pass")

        self._deactivate(local_user)

        self.keycloak_client.set_user_enabled.assert_not_called()
        self.nextcloud_client.set_user_enabled.assert_not_called()

    def test_nextcloud_is_left_alone_when_integration_is_off(self):
        self.handler.config.watcha.nextcloud_integration = False

        self._deactivate(self.user_id)

        self.keycloak_client.set_user_enabled.assert_called_once_with("8b1f3c", False)
        self.nextcloud_client.set_user_enabled.assert_not_called()

    def test_nothing_happens_without_a_managed_idp(self):
        self.handler.config.watcha.managed_idp = False

        self._deactivate(self.user_id)

        self.keycloak_client.set_user_enabled.assert_not_called()
        self.nextcloud_client.set_user_enabled.assert_not_called()

    def test_synapse_stays_active_when_keycloak_refuses(self):
        """The external accounts are locked first on purpose: if that fails the
        user must stay active everywhere, so the administrator can retry."""
        self.keycloak_client.set_user_enabled = AsyncMock(
            side_effect=HttpResponseException(503, "Service Unavailable", b"")
        )

        self.get_failure(
            self.deactivate_handler.deactivate_account(
                self.user_id,
                erase_data=False,
                requester=create_requester(self.user_id),
                by_admin=True,
            ),
            HttpResponseException,
        )

        user = self.get_success(self.store.get_user_by_id(self.user_id))
        self.assertFalse(user.is_deactivated)


class ReinviteDeactivatedAccountTestCase(HomeserverTestCase):
    """Inviting an address that already had an account must bring that account
    back, instead of failing with "User ID already taken"."""

    servlets = [admin.register_servlets, login.register_servlets]

    KEYCLOAK_ID = "8b1f3c"
    EMAIL = "caroline@example.com"

    def prepare(self, reactor, clock, hs):
        self.store = hs.get_datastores().main
        self.handler = hs.get_watcha_registration_handler()
        self.deactivate_handler = hs.get_deactivate_account_handler()

        self.handler.config.watcha.managed_idp = True
        self.handler.config.watcha.nextcloud_integration = True

        self.keycloak_client = self.handler.keycloak_client
        # Keycloak keeps the account when Synapse deactivates it, so creating it
        # again answers 409 and the handler reuses the existing UUID.
        self.keycloak_client.add_user = AsyncMock(
            side_effect=HttpResponseException(409, "Conflict", b"")
        )
        self.keycloak_client.get_user_by_email = AsyncMock(
            return_value={"id": self.KEYCLOAK_ID, "username": self.EMAIL}
        )
        self.keycloak_client.set_user_enabled = AsyncMock()
        self.keycloak_client.delete_user = AsyncMock()
        hs.get_nextcloud_client().set_user_enabled = AsyncMock()
        hs.get_nextcloud_client().delete_user = AsyncMock()
        hs.get_nextcloud_handler().provision_account = AsyncMock()

        # The registration path reads the configured providers to name the one
        # the mapping is recorded against; `default_config()` declares none.
        oidc_handler = Mock()
        oidc_handler._providers = {"keycloak": Mock()}
        hs._oidc_handler = oidc_handler

        self.admin_id = self.register_user("admin", "pass", admin=True)

    def _deactivated_account(self):
        """Une désactivation, pas un effacement. C'est le geste réversible :
        Keycloak garde le compte, et c'est ce qui permet de le retrouver. Un
        effacement supprimerait l'identité, et la personne qui revient
        recevrait un compte neuf."""
        user_id = self.register_user(self.KEYCLOAK_ID, "pass")
        self.get_success(
            self.store.record_user_external_id(
                "oidc", self.KEYCLOAK_ID, user_id, "caroline"
            )
        )
        self.get_success(
            self.deactivate_handler.deactivate_account(
                user_id,
                erase_data=False,
                requester=create_requester(user_id),
                by_admin=True,
            )
        )
        return user_id

    def test_reinvite_reactivates_instead_of_failing(self):
        user_id = self._deactivated_account()

        returned = self.get_success(
            self.handler.register(sender_id=self.admin_id, email_address=self.EMAIL)
        )

        self.assertEqual(returned, user_id)
        user = self.get_success(self.store.get_user_by_id(user_id))
        self.assertFalse(user.is_deactivated)
        self.assertFalse(self.get_success(self.store.is_user_erased(user_id)))

    def test_reinvite_restores_the_email_and_display_name(self):
        user_id = self._deactivated_account()

        self.get_success(
            self.handler.register(
                sender_id=self.admin_id,
                email_address=self.EMAIL,
                default_display_name="Caroline",
            )
        )

        threepids = self.get_success(self.store.user_get_threepids(user_id))
        self.assertEqual(
            [(threepid.medium, threepid.address) for threepid in threepids],
            [("email", self.EMAIL)],
        )
        profile = self.get_success(
            self.store.get_profileinfo(UserID.from_string(user_id))
        )
        self.assertEqual(profile.display_name, "Caroline")

    def test_reinvite_unlocks_keycloak_and_nextcloud(self):
        self._deactivated_account()
        self.keycloak_client.set_user_enabled.reset_mock()

        self.get_success(
            self.handler.register(sender_id=self.admin_id, email_address=self.EMAIL)
        )

        self.keycloak_client.set_user_enabled.assert_called_once_with(
            self.KEYCLOAK_ID, True
        )

    def test_an_erased_account_comes_back_as_a_fresh_one(self):
        """Un effacement supprime l'identité Keycloak : la personne qui revient
        n'est plus la même, et reçoit un compte neuf. C'est la contrepartie
        assumée de la symétrie du geste de suppression."""
        old_user_id = self.register_user(self.KEYCLOAK_ID, "pass")
        self.get_success(
            self.store.record_user_external_id(
                "oidc", self.KEYCLOAK_ID, old_user_id, "caroline"
            )
        )
        self.get_success(
            self.deactivate_handler.deactivate_account(
                old_user_id,
                erase_data=True,
                requester=create_requester(old_user_id),
                by_admin=True,
            )
        )
        self.keycloak_client.delete_user.assert_called_once_with(self.KEYCLOAK_ID)

        # Le compte Keycloak n'existe plus : la création réussit, sans 409.
        response = Mock()
        response.headers.getRawHeaders.return_value = [
            "https://auth.example.com/admin/realms/watcha/users/uuid-neuf"
        ]
        self.keycloak_client.add_user = AsyncMock(return_value=response)

        new_user_id = self.get_success(
            self.handler.register(sender_id=self.admin_id, email_address=self.EMAIL)
        )

        self.assertEqual(new_user_id, "@uuid-neuf:test")
        self.assertNotEqual(new_user_id, old_user_id)
        # L'ancien reste là, effacé : un localpart ne se réutilise jamais.
        old = self.get_success(self.store.get_user_by_id(old_user_id))
        self.assertTrue(old.is_deactivated)

    def test_unknown_address_still_registers_a_new_account(self):
        """The reactivation branch must not disturb the ordinary path."""
        response = Mock()
        response.headers.getRawHeaders.return_value = [
            "https://keycloak/admin/realms/watcha/users/a1b2c3"
        ]
        self.keycloak_client.add_user = AsyncMock(return_value=response)

        user_id = self.get_success(
            self.handler.register(
                sender_id=self.admin_id, email_address="new@example.com"
            )
        )

        self.assertEqual(user_id, "@a1b2c3:test")
        user = self.get_success(self.store.get_user_by_id(user_id))
        self.assertFalse(user.is_deactivated)
