from unittest.mock import Mock

from twisted.internet.defer import Deferred
from twisted.internet.testing import MemoryReactor

import synapse.rest.admin
from synapse.logging.context import make_deferred_yieldable
from synapse.rest.client import login, room
from synapse.server import HomeServer
from synapse.types import JsonDict
from synapse.util.clock import Clock

# Le module et non la classe : importée telle quelle, trial rejouerait ici
# toute la suite EmailPusherTests.
from tests.push import test_email
from tests.unittest import HomeserverTestCase


class LockedHttpPusherTestCase(HomeserverTestCase):
    """Un compte verrouillé garde ses pushers, mais ils se taisent : rien
    pendant la suspension, et rien à rattraper au déverrouillage."""

    servlets = [
        synapse.rest.admin.register_servlets_for_client_rest_resource,
        room.register_servlets,
        login.register_servlets,
    ]
    hijack_auth = False

    def make_homeserver(self, reactor: MemoryReactor, clock: Clock) -> HomeServer:
        self.push_attempts: list[tuple[Deferred, str, dict]] = []

        def post_json_get_json(url: str, body: JsonDict) -> Deferred:
            d: Deferred = Deferred()
            self.push_attempts.append((d, url, body))
            return make_deferred_yieldable(d)

        client = Mock()
        client.post_json_get_json = post_json_get_json
        return self.setup_test_homeserver(proxied_blocklisted_http_client=client)

    def prepare(self, reactor: MemoryReactor, clock: Clock, hs: HomeServer) -> None:
        self.store = hs.get_datastores().main

        self.user_id = self.register_user("user", "pass")
        self.token = self.login("user", "pass")
        self.other_id = self.register_user("other", "pass")
        self.other_token = self.login("other", "pass")

        user_tuple = self.get_success(self.store.get_user_by_access_token(self.token))
        assert user_tuple is not None
        self.get_success(
            hs.get_pusherpool().add_or_update_pusher(
                user_id=self.user_id,
                device_id=user_tuple.device_id,
                kind="http",
                app_id="m.http",
                app_display_name="HTTP Push Notifications",
                device_display_name="pushy push",
                pushkey="a@example.com",
                lang=None,
                data={"url": "http://example.com/_matrix/push/v1/notify"},
            )
        )

        self.room_id = self.helper.create_room_as(self.user_id, tok=self.token)
        self.helper.join(self.room_id, user=self.other_id, tok=self.other_token)

    def _pushed_bodies(self) -> list[str]:
        return [
            body["notification"]["content"]["body"]
            for _, _, body in self.push_attempts
        ]

    def _last_stream_ordering(self) -> int:
        pushers = list(
            self.get_success(self.store.get_pushers_by({"user_name": self.user_id}))
        )
        self.assertEqual(len(pushers), 1)
        return pushers[0].last_stream_ordering

    def _set_locked(self, locked: bool) -> None:
        self.get_success(self.store.set_user_locked_status(self.user_id, locked))

    def test_nothing_is_pushed_while_locked(self) -> None:
        self._set_locked(True)
        before = self._last_stream_ordering()

        self.helper.send(self.room_id, body="Pendant", tok=self.other_token)
        self.pump()

        self.assertEqual(self.push_attempts, [])
        # Le curseur avance : le message est tenu pour traité.
        self.assertGreater(self._last_stream_ordering(), before)

    def test_unlocking_resumes_without_the_backlog(self) -> None:
        self._set_locked(True)
        self.helper.send(self.room_id, body="Pendant", tok=self.other_token)
        self.pump()

        self._set_locked(False)
        self.helper.send(self.room_id, body="Après", tok=self.other_token)
        self.pump()

        self.assertEqual(self._pushed_bodies(), ["Après"])

    def test_pushers_still_push_when_not_locked(self) -> None:
        self.helper.send(self.room_id, body="Bonjour", tok=self.other_token)
        self.pump()

        self.assertEqual(self._pushed_bodies(), ["Bonjour"])


class LockedEmailPusherTestCase(HomeserverTestCase):
    """Même règle pour les courriels de notification."""

    servlets = test_email.EmailPusherTests.servlets
    hijack_auth = False
    make_homeserver = test_email.EmailPusherTests.make_homeserver
    prepare = test_email.EmailPusherTests.prepare

    def _room_with_other(self) -> str:
        room_id = self.helper.create_room_as(self.user_id, tok=self.access_token)
        self.helper.invite(
            room=room_id,
            src=self.user_id,
            tok=self.access_token,
            targ=self.others[0].id,
        )
        self.helper.join(room=room_id, user=self.others[0].id, tok=self.others[0].token)
        return room_id

    def test_no_email_while_locked_nor_after(self) -> None:
        room_id = self._room_with_other()
        self.get_success(self.store.set_user_locked_status(self.user_id, True))

        self.helper.send(room_id, body="Pendant", tok=self.others[0].token)
        self.reactor.advance(3600)
        self.assertEqual(self.email_attempts, [])

        self.get_success(self.store.set_user_locked_status(self.user_id, False))
        self.reactor.advance(3600)
        self.assertEqual(self.email_attempts, [])

    def test_email_resumes_after_unlocking(self) -> None:
        room_id = self._room_with_other()
        self.get_success(self.store.set_user_locked_status(self.user_id, True))
        self.helper.send(room_id, body="Pendant", tok=self.others[0].token)
        self.reactor.advance(3600)

        self.get_success(self.store.set_user_locked_status(self.user_id, False))
        self.helper.send(room_id, body="Après", tok=self.others[0].token)
        self.reactor.advance(3600)

        self.assertEqual(len(self.email_attempts), 1)
