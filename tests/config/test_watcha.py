from synapse.config import ConfigError
from synapse.config.watcha import WatchaConfig

from tests.unittest import TestCase


class WatchaConfigTestCase(TestCase):
    """Lecture des réglages `watcha:` introduits pour remplacer les bascules
    `#DLA` commentées à la main au déploiement."""

    def _read(self, watcha_section):
        config = WatchaConfig(None)
        raw = {} if watcha_section is None else {"watcha": watcha_section}
        config.read_config(raw, data_dir_path="/tmp")
        return config

    # -- partner_email_whitelist ------------------------------------------

    def test_whitelist_defaults_to_empty(self):
        """Défaut de toute la flotte : aucun déclassement de partenaire."""
        self.assertEqual(self._read(None).partner_email_whitelist, [])
        self.assertEqual(self._read({}).partner_email_whitelist, [])

    def test_whitelist_is_read_and_normalised(self):
        config = self._read(
            {
                "partner_email_whitelist": [
                    "Universite-Lyon.FR",
                    "  access-check.renater.fr  ",
                    "@example.com",
                ]
            }
        )
        self.assertEqual(
            config.partner_email_whitelist,
            ["universite-lyon.fr", "access-check.renater.fr", "example.com"],
        )

    def test_whitelist_accepts_a_single_string(self):
        config = self._read({"partner_email_whitelist": "universite-lyon.fr"})
        self.assertEqual(config.partner_email_whitelist, ["universite-lyon.fr"])

    def test_whitelist_drops_blank_entries(self):
        config = self._read({"partner_email_whitelist": ["", "   ", "example.com"]})
        self.assertEqual(config.partner_email_whitelist, ["example.com"])

    def test_whitelist_rejects_a_bad_type(self):
        with self.assertRaises(ConfigError):
            self._read({"partner_email_whitelist": {"domain": "example.com"}})
        with self.assertRaises(ConfigError):
            self._read({"partner_email_whitelist": ["example.com", 42]})

    # -- keycloak_required_actions ----------------------------------------

    def test_required_actions_default(self):
        """Sans réglage, Keycloak impose mot de passe et profil, comme avant."""
        for section in (None, {}):
            self.assertEqual(
                self._read(section).keycloak_required_actions,
                ["UPDATE_PASSWORD", "UPDATE_PROFILE"],
            )

    def test_required_actions_can_be_emptied(self):
        """Le cas ComUE : les comptes viennent de la fédération d'identité."""
        config = self._read({"keycloak_required_actions": []})
        self.assertEqual(config.keycloak_required_actions, [])

    def test_required_actions_can_be_overridden(self):
        config = self._read({"keycloak_required_actions": ["VERIFY_EMAIL"]})
        self.assertEqual(config.keycloak_required_actions, ["VERIFY_EMAIL"])

    def test_required_actions_rejects_a_bad_type(self):
        with self.assertRaises(ConfigError):
            self._read({"keycloak_required_actions": "UPDATE_PASSWORD"})
