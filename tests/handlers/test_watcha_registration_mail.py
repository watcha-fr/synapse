# watcha+
from unittest.mock import AsyncMock, Mock

from twisted.internet.defer import Deferred

from synapse.rest import admin
from synapse.rest.client import login

from tests.unittest import HomeserverTestCase


class RegistrationMailTestCase(HomeserverTestCase):
    """Le courriel d'inscription ne tient plus l'invitation.

    Mesuré sur watchatest le 2026-09-25 : 1,44 s des 6,4 s d'une invitation
    étaient passés à attendre le serveur SMTP, dans le chemin critique.
    """

    servlets = [admin.register_servlets, login.register_servlets]

    def prepare(self, reactor, clock, hs):
        self.hs = hs
        self.handler = hs.get_watcha_registration_handler()

        # `default_config()` ne déclare aucun drapeau Watcha : sans ça le
        # handler se croit sans IdP géré et n'envoie pas de courriel du tout.
        self.handler.config.watcha.managed_idp = True
        self.handler.config.watcha.nextcloud_integration = False

        self.handler.keycloak_client.add_user = AsyncMock(
            side_effect=self._mint_keycloak_user
        )
        self.minted = 0

        oidc_handler = Mock()
        oidc_handler._providers = {"keycloak": Mock()}
        hs._oidc_handler = oidc_handler

        self.mailer = Mock()
        self.handler.mailer = self.mailer

        self.admin_id = self.register_user("admin", "pass", admin=True)

    def _mint_keycloak_user(self, *args, **kwargs):
        uuid = f"uuid-{self.minted}"
        self.minted += 1
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

    def test_the_mail_is_still_sent(self):
        """Détacher n'est pas supprimer."""
        self.mailer.send_watcha_registration_mail = AsyncMock()

        self._register("jean.dupont@example.com")
        # Détaché : rien ne l’attend, il faut laisser tourner le reacteur.
        self.pump()

        self.assertEqual(self.mailer.send_watcha_registration_mail.await_count, 1)
        self.assertEqual(
            self.mailer.send_watcha_registration_mail.await_args.kwargs[
                "email_address"
            ],
            "jean.dupont@example.com",
        )

    def test_a_slow_smtp_no_longer_holds_the_registration(self):
        """Le cœur du changement : le compte est rendu sans attendre l'envoi."""
        never_fires = Deferred()
        self.mailer.send_watcha_registration_mail = Mock(return_value=never_fires)

        # Aboutit alors que l'envoi n'est toujours pas terminé.
        user_id = self._register("jean.dupont@example.com")
        self.assertEqual(user_id, "@uuid-0:test")
        self.assertFalse(never_fires.called)

        # Et l'envoi finit sa vie sans que personne ne l'attende.
        never_fires.callback(None)

    def test_a_failing_smtp_no_longer_fails_the_registration(self):
        """Avant, la panne remontait *après* création du compte : l'adresse
        était rapportée en erreur alors que le compte existait déjà."""
        self.mailer.send_watcha_registration_mail = AsyncMock(
            side_effect=Exception("smtp down")
        )

        with self.assertLogs("synapse.handlers.watcha_registration", "ERROR") as logs:
            user_id = self._register("jean.dupont@example.com")
            self.pump()

        self.assertEqual(user_id, "@uuid-0:test")
        # L'échec n'est plus rendu à l'invitant : il doit rester dans le journal,
        # avec l'adresse, sinon un envoi manquant devient introuvable.
        self.assertIn("jean.dupont@example.com", "\n".join(logs.output))
# +watcha
