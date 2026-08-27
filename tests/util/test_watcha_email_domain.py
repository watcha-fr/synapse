from synapse.util.watcha import email_domain_matches

from tests import unittest


class EmailDomainMatchesTestCase(unittest.TestCase):
    """Garde de la whitelist `watcha.partner_email_whitelist`.

    Un partenaire dont l'adresse relève d'un domaine de l'organisation est
    déclassé en membre de plein droit : la règle accorde un privilège, elle doit
    donc être ancrée sur le domaine et non sur une sous-chaîne.
    """

    DOMAINS = ["universite-lyon.fr", "access-check.renater.fr"]

    def test_exact_domain(self):
        self.assertTrue(email_domain_matches("alice@universite-lyon.fr", self.DOMAINS))
        self.assertTrue(
            email_domain_matches("bob@access-check.renater.fr", self.DOMAINS)
        )

    def test_subdomain(self):
        self.assertTrue(
            email_domain_matches("alice@etu.universite-lyon.fr", self.DOMAINS)
        )

    def test_case_and_whitespace_insensitive(self):
        self.assertTrue(email_domain_matches("Alice@Universite-Lyon.FR", self.DOMAINS))
        self.assertTrue(
            email_domain_matches("alice@universite-lyon.fr.", self.DOMAINS)
        )
        self.assertTrue(
            email_domain_matches("alice@universite-lyon.fr", ["  UNIVERSITE-LYON.FR "])
        )

    def test_other_domain(self):
        self.assertFalse(email_domain_matches("alice@example.com", self.DOMAINS))

    def test_substring_is_not_enough(self):
        """Le point du correctif : un simple `in` laissait passer ces adresses."""
        self.assertFalse(
            email_domain_matches("alice@evil-universite-lyon.fr.example", self.DOMAINS)
        )
        self.assertFalse(
            email_domain_matches("alice@universite-lyon.fr.evil.com", self.DOMAINS)
        )
        self.assertFalse(
            email_domain_matches("universite-lyon.fr@example.com", self.DOMAINS)
        )

    def test_local_part_containing_domain(self):
        self.assertFalse(
            email_domain_matches("universite-lyon.fr.admin@example.com", self.DOMAINS)
        )

    def test_empty_whitelist_never_matches(self):
        """Comportement par défaut de toute la flotte : aucun déclassement."""
        self.assertFalse(email_domain_matches("alice@universite-lyon.fr", []))
        self.assertFalse(email_domain_matches("alice@universite-lyon.fr", None))

    def test_malformed_addresses(self):
        self.assertFalse(email_domain_matches(None, self.DOMAINS))
        self.assertFalse(email_domain_matches("", self.DOMAINS))
        self.assertFalse(email_domain_matches("alice", self.DOMAINS))
        self.assertFalse(email_domain_matches("alice@", self.DOMAINS))

    def test_ignores_blank_entries_in_whitelist(self):
        self.assertFalse(email_domain_matches("alice@example.com", ["", "   ", None]))
