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
        self.administration_handler = hs.get_administration_handler()

    async def on_GET(self, request):
        await assert_requester_is_admin(self.auth, request)
        result = await self.administration_handler.watcha_user_list()
        return 200, result


class WatchaRoomListRestServlet(RestServlet):
    PATTERNS = client_patterns("/watcha_room_list", v1=True)

    def __init__(self, hs):
        super().__init__()
        self.auth = hs.get_auth()
        self.store = hs.get_datastore()

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
        self.administration_handler = hs.get_administration_handler()

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
        self.store = hs.get_datastore()

    async def on_GET(self, request):
        await assert_requester_is_admin(self.auth, request)
        result = await self.store.watcha_admin_stats()
        return 200, result


class WatchaRegisterRestServlet(RestServlet):
    PATTERNS = client_patterns("/watcha_register", v1=True)

    def __init__(self, hs):
        super().__init__()
        self.hs = hs
        self.config = hs.config
        self.auth = hs.get_auth()
        self.auth_handler = hs.get_auth_handler()
        self.registration_handler = hs.get_registration_handler()
        self.store = hs.get_datastore()
        self.keycloak_client = hs.get_keycloak_client()
        self.nextcloud_client = hs.get_nextcloud_client()
        self.user_directory_handler = hs.get_user_directory_handler()
        self.secrets = Secrets()

        if self.config.email.threepid_behaviour_email == ThreepidBehaviour.LOCAL:
            self.mailer = Mailer(
                hs=hs,
                app_name=self.config.email.email_app_name,
                template_html=self.config.email.watcha_registration_template_html,
                template_text=self.config.email.watcha_registration_template_text,
            )

    async def on_POST(self, request):
        requester = await self.auth.get_user_by_req(request)
        await assert_user_is_admin(self.auth, requester.user)
        params = parse_json_object_from_request(request)

        displayname = params.get("displayname", "").strip()
        email = params["email"].strip()
        if not email:
            raise SynapseError(
                400,
                build_log_message(
                    action="check if email address is set",
                    log_vars={"params": params},
                ),
            )

        if await self.store.get_user_id_by_threepid("email", email):
            raise SynapseError(
                400,
                build_log_message(
                    action="check if email is available",
                    log_vars={
                        "email": email,
                    },
                ),
            )

        password = params.get("password") or self.secrets.gen_password()
        password_hash = await self.auth_handler.hash(password)
        is_admin = params["admin"]
        response = await self.keycloak_client.add_user(password_hash, email, is_admin)

        location = response.headers.getRawHeaders("location")[0]
        keycloak_user_id = location.split("/")[-1]

        try:
            await self.nextcloud_client.add_user(keycloak_user_id, displayname)
        except (
            NextcloudError,
            HttpResponseException,
            ValidationError,
            SchemaError,
        ) as error:
            if isinstance(error, NextcloudError) and error.code == 102:
                logger.warn(
                    build_log_message(
                        action="register user",
                        log_vars={"keycloak_user_id": keycloak_user_id, "error": error},
                    )
                )
            else:
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

        if self.hs.config.userdirectory.user_directory_search_all_users:
            profile = await self.store.get_profileinfo(keycloak_user_id)
            await self.user_directory_handler.handle_local_profile_change(
                user_id, profile
            )

        if self.config.email.threepid_behaviour_email == ThreepidBehaviour.LOCAL:
            await self.mailer.send_watcha_registration_email(
                email_address=email,
                sender_id=requester.user.to_string(),
                password=password,
            )

        return 200, {"user_id": user_id}


def register_servlets(hs, http_server):
    WatchaAdminStatsRestServlet(hs).register(http_server)
    WatchaRegisterRestServlet(hs).register(http_server)
    WatchaRoomListRestServlet(hs).register(http_server)
    WatchaUpdateUserRoleRestServlet(hs).register(http_server)
    WatchaUserlistRestServlet(hs).register(http_server)