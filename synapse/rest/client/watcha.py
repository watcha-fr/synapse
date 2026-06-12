import logging

from jsonschema.exceptions import SchemaError, ValidationError

from synapse.api.errors import (
    AuthError,
    HttpResponseException,
    NextcloudError,
    SynapseError,
)
""" watcha!
from synapse.config.emailconfig import ThreepidBehaviour
!watcha"""
from synapse.http.servlet import RestServlet, parse_json_object_from_request
from synapse.push.mailer import Mailer
from synapse.rest.admin._base import assert_requester_is_admin, assert_user_is_admin, admin_patterns
from synapse.rest.client._base import client_patterns
from synapse.util.watcha import Secrets, build_log_message
import time
from synapse.util import metrics
import json
import os
from synapse.util import json_encoder
from synapse.api.constants import EventTypes, Membership
from typing import Tuple, Dict, Any, List
from http import HTTPStatus
from synapse.types import create_requester
from synapse.types.state import StateFilter
from synapse.util.async_helpers import maybe_awaitable

logger = logging.getLogger(__name__)


class WatchaUserlistRestServlet(RestServlet):
    PATTERNS = client_patterns("/watcha_user_list", v1=True)

    def __init__(self, hs):
        super().__init__()
        self.auth = hs.get_auth()
        self.administration_handler = hs.get_watcha_administration_handler()

    async def on_GET(self, request):
        await assert_requester_is_admin(self.auth, request)
        result = await self.administration_handler.watcha_user_list()
        return 200, result


class WatchaRoomListRestServlet(RestServlet):
    PATTERNS = client_patterns("/watcha_room_list", v1=True)

    def __init__(self, hs):
        super().__init__()
        self.auth = hs.get_auth()
        self.store = hs.get_datastores().main

    async def on_GET(self, request):
        await assert_requester_is_admin(self.auth, request)
        result = await self.store.watcha_room_list()
        return 200, result


class WatchaUpdateUserRoleRestServlet(RestServlet):
    PATTERNS = client_patterns(
        "/watcha_update_user_role/(?P<target_user_id>[^/]*)", v1=True
    )

    def __init__(self, hs):
        super().__init__()
        self.auth = hs.get_auth()
        self.administration_handler = hs.get_watcha_administration_handler()

    async def on_PUT(self, request, target_user_id):
        await assert_requester_is_admin(self.auth, request)
        params = parse_json_object_from_request(request)

        users = await self.administration_handler.get_users()
        if target_user_id not in (user["name"] for user in users):
            raise SynapseError(
                400,
                build_log_message(
                    action="check if user is registered",
                    log_vars={"target_user_id": target_user_id},
                ),
            )

        role = params["role"]
        handled_role = ("partner", "collaborator", "admin")
        if role not in handled_role:
            raise SynapseError(
                400,
                build_log_message(
                    action="check if role is handled",
                    log_vars={"role": role, "handled_role": handled_role},
                ),
            )

        result = await self.administration_handler.update_user_role(
            target_user_id, role
        )
        return 200, {"new_role": result}


class WatchaAdminStatsRestServlet(RestServlet):
    """Get stats on the server.

    For POST, a optional 'ranges' parameters in JSON input made of a list of time ranges,
    will return stats for these ranges.

    The ranges must be arrays with three elements:
    label, start seconds since epoch, end seconds since epoch.
    """

    PATTERNS = client_patterns("/watcha_admin_stats", v1=True)

    def __init__(self, hs):
        super().__init__()
        self.auth = hs.get_auth()
        self.store = hs.get_datastores().main

    async def on_GET(self, request):
        await assert_requester_is_admin(self.auth, request)
        result = await self.store.watcha_admin_stats()
        return 200, result


class WatchaRegisterRestServlet(RestServlet):
    PATTERNS = client_patterns("/watcha_register", v1=True)

    def __init__(self, hs):
        super().__init__()
        self.auth = hs.get_auth()
        self.registration_handler = hs.get_watcha_registration_handler()

    async def on_POST(self, request):
        requester = await self.auth.get_user_by_req(request)
        await assert_user_is_admin(self.auth, requester)

        params = parse_json_object_from_request(request)

        email_address = params["email"].lower().strip()
        if not email_address:
            raise SynapseError(
                400,
                build_log_message(
                    action="check if email address is set",
                    log_vars={"params": params},
                ),
            )

        user_id = await self.registration_handler.register(
            sender_id=requester.user.to_string(),
            email_address=email_address,
            is_admin=params.get("admin", False),
            default_display_name=params.get("displayname", "").strip() or None,
            keycloak_username=params.get("keycloak_username"),
            keycloak_as_broker=params.get("keycloak_as_broker", False),
            localpart_id=params.get("localpart_id"),
        )

        return 200, {"user_id": user_id}

class WatchaSygnalPingServlet(RestServlet):
    PATTERNS = client_patterns("/watcha_sygnal_ping", v1=True)

    def __init__(self, hs):
        super().__init__()
        self._clock = hs.get_clock()

    async def on_GET(self, request):
        # (Optionnel) Vérifie l'adresse IP autorisée
        if request.getClientAddress().host != "135.125.93.164":
             return 403, {"error": "Unauthorized"}
        # Met à jour le timestamp global
        metrics.last_sygnal_ping_time = time.time()
        return 200, {"ping": "pong"}

class WatchaDeleteUserMessagesRestServlet(RestServlet):
    """
    POST /_synapse/admin/v1/watcha_delete_user_messages
    Body:
      {
        "user_id": "@user:domain",
        "dry_run": true|false
      }
    Behavior:
      - finds rooms where the user had membership=leave (current_state_events)
      - in each room, finds events sent by the user
      - finds a local member with enough power in the room
      - uses that local member as fake_requester to redact each event
    """

    PATTERNS = client_patterns("/watcha_delete_user_messages", v1=True)

    def __init__(self, hs):
        super().__init__()
        self.hs = hs
        self.auth = hs.get_auth()
        self.store = hs.get_datastores().main
        # controllers / handlers
        self._state_storage_controller = hs.get_storage_controllers().state
        self.event_creation_handler = hs.get_event_creation_handler()
        self.room_member_handler = hs.get_room_member_handler()
        self.is_mine_id = hs.is_mine_id

    async def on_POST(self, request) -> Tuple[int, Dict[str, Any]]:
        requester = await self.auth.get_user_by_req(request)
        await assert_user_is_admin(self.auth, requester)

        params = parse_json_object_from_request(request)
        user_id = params.get("user_id")
        dry_run = bool(params.get("dry_run", False))

        if not user_id or not user_id.startswith("@"):
            raise SynapseError(HTTPStatus.BAD_REQUEST, "Invalid or missing 'user_id'")

        logger.info("[watcha] Début suppression messages de %s (dry_run=%s)", user_id, dry_run)

        # Nous récupérons les room_id depuis current_state_events pour les membership=leave
        rooms: List[str] = await self.store.db_pool.simple_select_onecol(
            table="current_state_events",
            keyvalues={
                "type": EventTypes.Member,
                "membership": Membership.LEAVE,
                "state_key": user_id,
            },
            retcol="room_id",
            desc="watcha_get_rooms_user_left",
        )

        logger.info("[watcha] %d salles trouvées pour %s", len(rooms), user_id)

        total_found = 0
        total_deleted = 0
        failed = []

        # Helper pour envoyer une redaction via event_creation_handler en mode compatible
        async def send_redaction(fake_requester, room_id: str, event_id: str) -> None:
            # Build event dict for redaction
            event_dict = {
                "type": "m.room.redaction",
                "room_id": room_id,
                "sender": fake_requester.user.to_string(),
                "redacts": event_id,
                "content": {"reason": "Suppression automatique d'un compte supprimé"},
            }

            # try create_and_send_nonmember_event if available else fallback to handle_new_client_event
            try:
                # many versions provide create_and_send_nonmember_event(handler)
                coro = self.event_creation_handler.create_and_send_nonmember_event(
                    fake_requester, event_dict
                )
                await maybe_awaitable(coro)
            except AttributeError:
                # fallback
                await self.event_creation_handler.handle_new_client_event(
                    requester=fake_requester,
                    event_dict=event_dict,
                    ratelimit=False,
                )
            except AuthError as e:
                # bubble auth errors up for handling by caller
                raise

        # Loop rooms
        for room_id in rooms:
            events = await self.store.db_pool.simple_select_list(
                table="events",
                keyvalues={"room_id": room_id, "sender": user_id},
                retcols=["event_id"],
                desc="watcha_get_events_by_user_in_room",
            )

            num_events = len(events)
            total_found += num_events
            logger.info("[watcha] %d messages trouvés dans %s pour %s", num_events, room_id, user_id)

            if num_events == 0:
                continue

            filtered_room_state = await self._state_storage_controller.get_current_state(
                room_id,
                StateFilter.from_types(
                    [
                        (EventTypes.Create, ""),
                        (EventTypes.PowerLevels, ""),
                        (EventTypes.JoinRules, ""),
                        (EventTypes.Member, user_id),  # just in case we need it
                    ]
                ),
            )

            if not filtered_room_state:
                logger.warning("[watcha] Pas d'état courant pour la salle %s — skip", room_id)
                failed.append({"room": room_id, "reason": "no_state"})
                continue

            create_event = filtered_room_state.get((EventTypes.Create, ""))
            power_levels = filtered_room_state.get((EventTypes.PowerLevels, ""))

            # Determine a local admin user in this room who is joined
            admin_user_id = None
            pl_content = {}

            if power_levels is not None:
                pl_content = power_levels.content or {}
                user_power = pl_content.get("users", {})
                # pick local users
                admin_users = [uid for uid in user_power.keys() if self.is_mine_id(uid)]
                admin_users.sort(key=lambda u: user_power.get(u, 0))
                if not admin_users:
                    logger.warning("[watcha] Pas d'utilisateur local avec power_levels dans %s", room_id)
                    failed.append({"room": room_id, "reason": "no_local_admin_in_pl"})
                    continue

                # pick highest joined
                chosen = None
                for admin_user in reversed(admin_users):  # highest first
                    membership = await self.store.get_local_current_membership_for_user_in_room(
                        admin_user, room_id
                    )
                    # membership is (membership_type, stream_id)
                    if membership and membership[0] == Membership.JOIN:
                        chosen = admin_user
                        break

                if not chosen:
                    logger.warning("[watcha] Aucun local admin en JOIN dans %s", room_id)
                    failed.append({"room": room_id, "reason": "no_local_joined_admin"})
                    continue

                admin_user_id = chosen
            else:
                # no power levels -> fallback to creator if local
                if create_event and self.is_mine_id(create_event.sender):
                    admin_user_id = create_event.sender
                else:
                    logger.warning("[watcha] pas de power_levels et create_event n'est pas local pour %s", room_id)
                    failed.append({"room": room_id, "reason": "no_pl_no_local_creator"})
                    continue

            # create fake_requester
            fake_requester = create_requester(
                admin_user_id,
                authenticated_entity=requester.authenticated_entity,
            )

            for ev in events:
                ev_id = ev["event_id"]
                if dry_run:
                    logger.info("[watcha][DRY] would redact %s in %s as %s", ev_id, room_id, admin_user_id)
                    continue

                try:
                    await send_redaction(fake_requester, room_id, ev_id)
                    total_deleted += 1
                except AuthError as e:
                    # Not permitted (e.g. despite being the local admin, AuthError returned)
                    logger.warning("[watcha] AuthError redacting %s in %s: %s", ev_id, room_id, e)
                    failed.append({"room": room_id, "event": ev_id, "reason": "auth"})
                except Exception as e:
                    logger.exception("[watcha] Erreur en redacting %s in %s: %s", ev_id, room_id, e)
                    failed.append({"room": room_id, "event": ev_id, "reason": "error", "error": str(e)})

        logger.info("[watcha] Fin : %d trouvés, %d supprimés", total_found, total_deleted)

        return HTTPStatus.OK, {
            "user_id": user_id,
            "dry_run": dry_run,
            "messages_found": total_found,
            "messages_deleted": total_deleted,
            "failed": failed,
        }


def register_servlets(hs, http_server):
    WatchaAdminStatsRestServlet(hs).register(http_server)
    WatchaRegisterRestServlet(hs).register(http_server)
    WatchaRoomListRestServlet(hs).register(http_server)
    WatchaUpdateUserRoleRestServlet(hs).register(http_server)
    WatchaUserlistRestServlet(hs).register(http_server)
    WatchaSygnalPingServlet(hs).register(http_server)
    WatchaDeleteUserMessagesRestServlet(hs).register(http_server)
