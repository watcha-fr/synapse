from synapse.rest import admin
from synapse.rest.client import login, room

from tests import unittest


class WatchaPartnerDirectorySearchTestCase(unittest.HomeserverTestCase):
    """Visibilité des partenaires dans la recherche Watcha de l'annuaire.

    Un partenaire n'est visible que de celui qui l'a invité, sauf quand on tape
    son adresse exacte et qu'il est membre ou invité d'un salon dont on est
    membre : c'est ce qui permet de reconnaître, avant l'envoi, un partenaire
    déjà présent qu'on s'apprête à réinviter.
    """

    servlets = [
        admin.register_servlets,
        login.register_servlets,
        room.register_servlets,
    ]

    def prepare(self, reactor, clock, hs):
        self.store = hs.get_datastores().main
        auth = hs.get_auth_handler()
        now = clock.time_msec()

        self.inviter = self.register_user("inviter", "pass")
        self.inviter_tok = self.login("inviter", "pass")
        self.member = self.register_user("member", "pass")
        self.member_tok = self.login("member", "pass")
        self.partner = self.register_user("partner", "pass", is_partner=True)
        self.partner_tok = self.login("partner", "pass")
        self.pending = self.register_user("pending", "pass", is_partner=True)
        self.outsider = self.register_user("outsider", "pass", is_partner=True)

        for user_id, address, name in (
            (self.inviter, "inviter@example.org", "Inviter"),
            (self.member, "member@example.org", "Member"),
            (self.partner, "partner@example.org", "Partner"),
            (self.pending, "pending@example.org", "Pending"),
            (self.outsider, "outsider@example.org", "Outsider"),
        ):
            self.get_success(auth.add_threepid(user_id, "email", address, now))
            self.get_success(self.store.update_profile_in_user_dir(user_id, name, None))
        for partner in (self.partner, self.pending, self.outsider):
            self.get_success(self.store.add_partner_invitation(partner, self.inviter))

        # Le partenaire a rejoint le salon que partagent l'inviteur et le membre ;
        # `pending` y est seulement invité ; `outsider` n'y est pas.
        room_id = self.helper.create_room_as(self.inviter, tok=self.inviter_tok)
        self.helper.invite(room_id, self.inviter, self.member, tok=self.inviter_tok)
        self.helper.join(room_id, self.member, tok=self.member_tok)
        self.helper.invite(room_id, self.inviter, self.partner, tok=self.inviter_tok)
        self.helper.join(room_id, self.partner, tok=self.partner_tok)
        self.helper.invite(room_id, self.inviter, self.pending, tok=self.inviter_tok)

    def _search(self, searcher: str, term: str) -> list[str]:
        result = self.get_success(self.store.search_user_dir(searcher, term, 10))
        return [user["user_id"] for user in result["results"]]

    def test_inviter_sees_partner_by_partial_term(self) -> None:
        self.assertIn(self.partner, self._search(self.inviter, "partner"))

    def test_room_member_finds_partner_by_exact_address(self) -> None:
        # Insensible à la casse, comme une adresse électronique.
        self.assertIn(self.partner, self._search(self.member, "Partner@Example.org"))

    def test_room_member_cannot_browse_partner_by_partial_term(self) -> None:
        self.assertNotIn(self.partner, self._search(self.member, "partner"))
        self.assertNotIn(self.partner, self._search(self.member, "partner@example"))

    def test_invited_partner_is_found_by_exact_address(self) -> None:
        self.assertIn(self.pending, self._search(self.member, "pending@example.org"))

    def test_partner_outside_shared_rooms_stays_hidden(self) -> None:
        self.assertNotIn(self.outsider, self._search(self.member, "outsider@example.org"))

    def test_members_stay_visible_to_everyone(self) -> None:
        self.assertIn(self.member, self._search(self.partner, "member"))
