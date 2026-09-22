from synapse.rest import admin
from synapse.rest.client import login, room, watcha

from tests import unittest


class RoomFolderHeirTestCase(unittest.HomeserverTestCase):
    """Qui reprend le dossier d'un salon quand son propriétaire est supprimé.

    Supprimer un compte détruit ses fichiers, dossiers documentaires de salons
    compris : le connecteur Nextcloud demande ici un héritier avant de détruire
    quoi que ce soit.
    """

    servlets = [
        admin.register_servlets,
        login.register_servlets,
        room.register_servlets,
        watcha.register_servlets,
    ]

    url = "/_matrix/client/r0/watcha_room_folder_heir"

    def prepare(self, reactor, clock, hs):
        self.hs = hs
        self.store = hs.get_datastores().main

        self.admin_id = self.register_user("admin", "pass", admin=True)
        self.admin_tok = self.login("admin", "pass")

    def _member(self, localpart, nextcloud_username, is_partner=False):
        user_id = self.register_user(localpart, "pass")
        token = self.login(localpart, "pass")
        self.get_success(
            self.store.record_user_external_id(
                "oidc", f"uuid-{localpart}", user_id, nextcloud_username
            )
        )
        if is_partner:
            self.get_success(self.store.update_user_role(user_id, "partner"))
        return user_id, token

    def _ask(self, room_id, leaving):
        return self.make_request(
            "POST",
            self.url,
            {"room_id": room_id, "nextcloud_username": leaving},
            access_token=self.admin_tok,
        )

    def test_the_oldest_remaining_member_inherits(self):
        """L'ancienneté se lit dans le salon : celui qui l'a rejoint le premier."""
        owner_id, owner_tok = self._member("owner", "owner")
        first_id, first_tok = self._member("first", "first")
        second_id, second_tok = self._member("second", "second")

        room_id = self.helper.create_room_as(owner_id, tok=owner_tok)
        for uid, tok in ((first_id, first_tok), (second_id, second_tok)):
            self.helper.invite(room_id, src=owner_id, targ=uid, tok=owner_tok)
            self.helper.join(room_id, user=uid, tok=tok)

        channel = self._ask(room_id, "owner")

        self.assertEqual(channel.code, 200, channel.json_body)
        self.assertEqual(channel.json_body["nextcloud_username"], "first")

    def test_the_departing_member_is_never_the_heir(self):
        owner_id, owner_tok = self._member("owner", "owner")
        room_id = self.helper.create_room_as(owner_id, tok=owner_tok)

        channel = self._ask(room_id, "owner")

        self.assertEqual(channel.code, 200, channel.json_body)
        self.assertIsNone(channel.json_body["nextcloud_username"])

    def test_a_partner_does_not_inherit(self):
        """Un partenaire est extérieur à l'organisation : les documents d'un
        salon ne lui reviennent pas, quitte à ce que personne n'hérite."""
        owner_id, owner_tok = self._member("owner", "owner")
        partner_id, partner_tok = self._member("partner", "partner", is_partner=True)

        room_id = self.helper.create_room_as(owner_id, tok=owner_tok)
        self.helper.invite(room_id, src=owner_id, targ=partner_id, tok=owner_tok)
        self.helper.join(room_id, user=partner_id, tok=partner_tok)

        channel = self._ask(room_id, "owner")

        self.assertEqual(channel.code, 200, channel.json_body)
        self.assertIsNone(channel.json_body["nextcloud_username"])

    def test_a_member_without_a_nextcloud_account_is_skipped(self):
        """Sans compte Nextcloud, il n'y a nulle part où poser les fichiers."""
        owner_id, owner_tok = self._member("owner", "owner")
        sans_id = self.register_user("sans", "pass")
        sans_tok = self.login("sans", "pass")
        heir_id, heir_tok = self._member("heir", "heir")

        room_id = self.helper.create_room_as(owner_id, tok=owner_tok)
        for uid, tok in ((sans_id, sans_tok), (heir_id, heir_tok)):
            self.helper.invite(room_id, src=owner_id, targ=uid, tok=owner_tok)
            self.helper.join(room_id, user=uid, tok=tok)

        channel = self._ask(room_id, "owner")

        self.assertEqual(channel.code, 200, channel.json_body)
        self.assertEqual(channel.json_body["nextcloud_username"], "heir")

    def test_an_invited_member_does_not_inherit(self):
        """Inviter n'est pas rejoindre : tant qu'il n'est pas entré, le salon
        n'est pas le sien."""
        owner_id, owner_tok = self._member("owner", "owner")
        invited_id, _ = self._member("invited", "invited")

        room_id = self.helper.create_room_as(owner_id, tok=owner_tok)
        self.helper.invite(room_id, src=owner_id, targ=invited_id, tok=owner_tok)

        channel = self._ask(room_id, "owner")

        self.assertEqual(channel.code, 200, channel.json_body)
        self.assertIsNone(channel.json_body["nextcloud_username"])

    def test_an_unknown_nextcloud_name_is_not_an_error(self):
        """Un compte Nextcloud sans rattachement n'a rien à transmettre, et le
        connecteur ne doit pas être bloqué pour autant."""
        owner_id, owner_tok = self._member("owner", "owner")
        room_id = self.helper.create_room_as(owner_id, tok=owner_tok)

        channel = self._ask(room_id, "personne-de-ce-nom")

        self.assertEqual(channel.code, 200, channel.json_body)
        self.assertIsNone(channel.json_body["nextcloud_username"])

    def test_the_request_needs_a_room_and_a_name(self):
        channel = self.make_request(
            "POST", self.url, {"room_id": ""}, access_token=self.admin_tok
        )

        self.assertEqual(channel.code, 400, channel.json_body)
