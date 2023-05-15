import logging

from jsonschema.exceptions import SchemaError, ValidationError

from synapse.api.errors import (
    AuthError,
    HttpResponseException,
    NextcloudError,
    SynapseError,
)
from synapse.config.emailconfig import ThreepidBehaviour
from synapse.http.servlet import RestServlet, parse_json_object_from_request
from synapse.push.mailer import Mailer
from synapse.rest.admin._base import assert_requester_is_admin, assert_user_is_admin
from synapse.rest.client._base import client_patterns
from synapse.util.watcha import Secrets, build_log_message

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
        await assert_user_is_admin(self.auth, requester.user)

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
        )

        return 200, {"user_id": user_id}


def register_servlets(hs, http_server):
    WatchaAdminStatsRestServlet(hs).register(http_server)
    WatchaRegisterRestServlet(hs).register(http_server)
    WatchaRoomListRestServlet(hs).register(http_server)
    WatchaUpdateUserRoleRestServlet(hs).register(http_server)
    WatchaUserlistRestServlet(hs).register(http_server)
