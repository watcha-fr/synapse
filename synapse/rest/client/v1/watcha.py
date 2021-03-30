import logging

from jsonschema.exceptions import SchemaError, ValidationError

from synapse.api.errors import AuthError, HttpResponseException, SynapseError
from synapse.config.emailconfig import ThreepidBehaviour
from synapse.http.servlet import RestServlet, parse_json_object_from_request
from synapse.push.mailer import Mailer
from synapse.rest.client.v2_alpha._base import client_patterns
from synapse.util.watcha import Secrets

logger = logging.getLogger(__name__)


async def _check_admin(auth, request):
    requester = await auth.get_user_by_req(request)
    is_admin = await auth.is_server_admin(requester.user)
    if not is_admin:
        raise AuthError(403, "You are not a server admin")


class WatchaUserlistRestServlet(RestServlet):
    PATTERNS = client_patterns("/watcha_user_list", v1=True)

    def __init__(self, hs):
        super().__init__()
        self.auth = hs.get_auth()
        self.administration_handler = hs.get_administration_handler()

    async def on_GET(self, request):
        await _check_admin(self.auth, request)
        result = await self.administration_handler.watcha_user_list()
        return 200, result


class WatchaRoomListRestServlet(RestServlet):
    PATTERNS = client_patterns("/watcha_room_list", v1=True)

    def __init__(self, hs):
        super().__init__()
        self.auth = hs.get_auth()
        self.store = hs.get_datastore()

    async def on_GET(self, request):
        await _check_admin(self.auth, request)
        result = await self.store.watcha_room_list()
        return 200, result


class WatchaUpdateUserRoleRestServlet(RestServlet):
    PATTERNS = client_patterns(
        "/watcha_update_user_role/(?P<target_user_id>[^/]*)", v1=True
    )

    def __init__(self, hs):
        super().__init__()
        self.auth = hs.get_auth()
        self.administration_handler = hs.get_administration_handler()

    async def on_PUT(self, request, target_user_id):
        await _check_admin(self.auth, request)
        params = parse_json_object_from_request(request)

        users = await self.administration_handler.get_users()
        if target_user_id not in [user["name"] for user in users]:
            raise SynapseError(
                400, "The target user is not registered in this homeserver."
            )

        role = params["role"]
        if role not in ["partner", "collaborator", "admin"]:
            raise SynapseError(400, "%s is not a defined role." % role)

        result = await self.administration_handler.watcha_update_user_role(
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
        self.store = hs.get_datastore()

    async def on_GET(self, request):
        await _check_admin(self.auth, request)
        result = await self.store.watcha_admin_stats()
        return 200, result


class WatchaRegisterRestServlet(RestServlet):
    PATTERNS = client_patterns("/watcha_register", v1=True)

    def __init__(self, hs):
        super().__init__()
        self.config = hs.config
        self.auth = hs.get_auth()
        self.auth_handler = hs.get_auth_handler()
        self.registration_handler = hs.get_registration_handler()
        self.store = hs.get_datastore()
        self.keycloak_client = hs.get_keycloak_client()
        self.nextcloud_client = hs.get_nextcloud_client()
        self.secrets = Secrets(hs.config.word_list_path)

        if self.config.threepid_behaviour_email == ThreepidBehaviour.LOCAL:
            self.mailer = Mailer(
                hs=hs,
                app_name=self.config.email_app_name,
                template_html=self.config.watcha_registration_template_html,
                template_text=self.config.watcha_registration_template_text,
            )

    async def on_POST(self, request):
        await _check_admin(
            self.auth,
            request,
        )
        params = parse_json_object_from_request(request)

        displayname = params.get("displayname", "").strip()
        email = params["email"].strip()
        if not email:
            raise SynapseError(
                400,
                "Email address cannot be empty",
            )

        if await self.store.get_user_id_by_threepid("email", email):
            raise SynapseError(
                400,
                "A user with this email address already exists. Cannot create a new one.",
            )

        password = params.get("password") or self.secrets.passphrase()
        password_hash = await self.auth_handler.hash(password)
        is_admin = params["admin"]
        response = await self.keycloak_client.add_user(password_hash, email, is_admin)

        location = response.headers.getRawHeaders("location")[0]
        keycloak_user_id = location.split("/")[-1]

        try:
            await self.nextcloud_client.add_user(keycloak_user_id)
        except (SynapseError, HttpResponseException, ValidationError, SchemaError):
            await self.keycloak_client.delete_user(keycloak_user_id)
            raise

        try:
            user_id = await self.registration_handler.register_user(
                localpart=keycloak_user_id,
                admin=is_admin,
                default_display_name=displayname or email,
                bind_emails=[email],
            )
        except SynapseError:
            await self.keycloak_client.delete_user(keycloak_user_id)
            await self.nextcloud_client.delete_user(keycloak_user_id)
            raise

        sender = await self.auth.get_user_by_req(request)
        sender_id = sender.user.to_string()

        await self.mailer.send_watcha_registration_email(
            email_address=email,
            sender_id=sender_id,
            password=password,
        )

        return 200, {"user_id": user_id}


def register_servlets(hs, http_server):
    WatchaAdminStatsRestServlet(hs).register(http_server)
    WatchaRegisterRestServlet(hs).register(http_server)
    WatchaRoomListRestServlet(hs).register(http_server)
    WatchaUpdateUserRoleRestServlet(hs).register(http_server)
    WatchaUserlistRestServlet(hs).register(http_server)
