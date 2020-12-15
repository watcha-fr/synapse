import logging
from urllib.parse import urlparse

from secrets import token_hex
from synapse.api.errors import AuthError, SynapseError
from synapse.config.emailconfig import ThreepidBehaviour
from synapse.http.servlet import RestServlet, parse_json_object_from_request
from synapse.push.mailer import Mailer
from synapse.rest.client.v2_alpha._base import client_patterns
from synapse.types import UserID, create_requester, map_username_to_mxid_localpart
from synapse.util.threepids import canonicalise_email

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
        ret = await self.administration_handler.watcha_user_list()
        return 200, ret


class WatchaRoomMembershipRestServlet(RestServlet):

    PATTERNS = client_patterns("/watcha_room_membership", v1=True)

    def __init__(self, hs):
        super().__init__()
        self.auth = hs.get_auth()
        self.administration_handler = hs.get_administration_handler()

    async def on_GET(self, request):
        await _check_admin(self.auth, request)
        ret = await self.administration_handler.watcha_room_membership()
        return 200, ret


class WatchaSendNextcloudActivityToWatchaRoomServlet(RestServlet):

    PATTERNS = client_patterns("/watcha_room_nextcloud_activity", v1=True)

    def __init__(self, hs):
        super().__init__()
        self.hs = hs
        self.auth = hs.get_auth()
        self.nextcloud_handler = hs.get_nextcloud_handler()

    async def on_POST(self, request):
        await _check_admin(
            self.auth,
            request,
        )
        params = parse_json_object_from_request(request)

        file_name = params["file_name"]
        file_url = params["file_url"]
        notifications = params["notifications"]

        if not file_name or not file_url or not notifications:
            raise SynapseError(
                400,
                "Some data in payload have empty value.",
            )

        server_name = self.hs.get_config().server_name

        if not server_name:
            raise SynapseError(400, "No server name in homeserver config.")

        file_url_parsed = urlparse(file_url)

        if (
            file_url_parsed.scheme not in ["http", "https"]
            or file_url_parsed.netloc != server_name
        ):
            raise SynapseError(
                400,
                "The Nextcloud url is not recognized.",
            )

        notifications_sent = []

        for notification in notifications:

            if list(notification.keys()) != [
                "activity_type",
                "directory",
                "limit_of_notification_propagation",
            ]:
                logger.warn("It missing some parameters to notify file operation")
                continue

            file_operation = notification["activity_type"]
            if file_operation not in [
                "file_created",
                "file_deleted",
                "file_moved",
                "file_restored",
            ]:
                logger.warn("This nextcloud file operation is not handled")
                continue

            try:
                rooms = await self.nextcloud_handler.get_rooms_to_send_notification(
                    notification["directory"],
                    notification["limit_of_notification_propagation"],
                )
            except SynapseError as e:
                logger.error("Error during getting rooms to send notifications : %s", e)
                continue

            try:
                notification_sent = (
                    await self.nextcloud_handler.send_nextcloud_notification_to_rooms(
                        rooms, file_name, file_url, file_operation
                    )
                )
            except SynapseError as e:
                logger.error("Error during sending notification to room : %s", e)
                continue

            notifications_sent.append(notification_sent)

        return (200, notifications_sent)


class WatchaRoomListRestServlet(RestServlet):
    PATTERNS = client_patterns("/watcha_room_list", v1=True)

    def __init__(self, hs):
        super().__init__()
        self.auth = hs.get_auth()
        self.administration_handler = hs.get_administration_handler()

    async def on_GET(self, request):
        await _check_admin(self.auth, request)
        ret = await self.administration_handler.watcha_room_list()
        return 200, ret


class WatchaUpdateMailRestServlet(RestServlet):
    PATTERNS = client_patterns(
        "/watcha_update_email/(?P<target_user_id>[^/]*)", v1=True
    )

    def __init__(self, hs):
        super().__init__()
        self.hs = hs
        self.auth = hs.get_auth()
        self.admin_handler = hs.get_admin_handler()
        self.auth_handler = hs.get_auth_handler()
        self.account_activity_handler = hs.get_account_validity_handler()

    async def on_PUT(self, request, target_user_id):
        await _check_admin(self.auth, request)
        params = parse_json_object_from_request(request)
        new_email = params["new_email"]

        if not new_email:
            raise SynapseError(400, "Missing 'new_email' arg")

        users = await self.admin_handler.get_users()
        if not target_user_id in [user["name"] for user in users]:
            raise SynapseError(
                400, "The target user is not registered in this homeserver."
            )

        try:
            email = await self.account_activity_handler.get_email_address_for_user(
                target_user_id
            )
        except SynapseError:
            logger.error("No email are defined for this user.")
            raise

        await self.auth_handler.delete_threepid(
            target_user_id, "email", email, id_server=None
        )
        await self.auth_handler.add_threepid(
            target_user_id, "email", new_email, self.hs.get_clock().time_msec()
        )

        return 200, {}


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
        self.administration_handler = hs.get_administration_handler()

    async def on_GET(self, request):
        await _check_admin(self.auth, request)
        ret = await self.administration_handler.watcha_admin_stat()
        return 200, ret


class WatchaUserIp(RestServlet):

    PATTERNS = client_patterns("/watcha_user_ip/(?P<target_user_id>[^/]*)", v1=True)

    def __init__(self, hs):
        super().__init__()
        self.auth = hs.get_auth()
        self.administration_handler = hs.get_administration_handler()

    async def on_GET(self, request, target_user_id):
        await _check_admin(self.auth, request)
        ret = await self.administration_handler.watcha_user_ip(target_user_id)
        return 200, ret


class WatchaRegisterRestServlet(RestServlet):
    """
    Registration of users.
    Requester must either be logged in as an admin, or supply a valid HMAC (generated from the registration_shared_secret)
    """

    PATTERNS = client_patterns("/watcha_register", v1=True)

    def __init__(self, hs):
        super().__init__()
        self.config = hs.config
        self.auth = hs.get_auth()
        self.auth_handler = hs.get_auth_handler()
        self.nextcloud_handler = hs.get_nextcloud_handler()
        self.profile_handler = hs.get_profile_handler()
        self.registration_handler = hs.get_registration_handler()

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
        logger.info("Adding Watcha user...")

        email = params["email"].strip()
        if not email:
            raise SynapseError(
                400,
                "Email address cannot be empty",
            )

        try:
            email = canonicalise_email(email)
        except ValueError as e:
            raise SynapseError(400, str(e))

        user_id = await self.auth_handler.find_user_id_by_email(email)
        if user_id:
            raise SynapseError(
                400,
                "A user with this email address already exists. Cannot create a new one.",
            )

        requester = await self.auth.get_user_by_req(request)

        send_email = False

        if hasattr(params, "password"):
            password = params["password"]
        else:
            password = token_hex(6)
            send_email = True

        password_hash = await self.auth_handler.hash(password)
        admin = params["admin"]

        role = "admin" if admin else None
        await self.nextcloud_handler.create_keycloak_and_nextcloud_user(email, password_hash, role)

        user_id = await self.registration_handler.register_user(
            localpart=map_username_to_mxid_localpart(email),
            password_hash=None,
            admin=admin,
            bind_emails=[email],
        )

        user = UserID.from_string(user_id)
        await self.profile_handler.set_displayname(
            user, requester, params["displayname"], by_admin=True
        )

        display_name = await self.profile_handler.get_displayname(user)

        if send_email:
            await self.mailer.send_watcha_registration_email(
                email_address=email,
                host_id=requester.user.to_string(),
                password=password,
            )
        else:
            logger.info(
                "Not sending email for user password for user %s, password is defined by sender",
                user_id,
            )

        return 200, {"display_name": display_name, "user_id": user_id}


def register_servlets(hs, http_server):
    WatchaAdminStatsRestServlet(hs).register(http_server)
    WatchaRegisterRestServlet(hs).register(http_server)
    WatchaRoomListRestServlet(hs).register(http_server)
    WatchaRoomMembershipRestServlet(hs).register(http_server)
    WatchaSendNextcloudActivityToWatchaRoomServlet(hs).register(http_server)
    WatchaUpdateMailRestServlet(hs).register(http_server)
    WatchaUpdateUserRoleRestServlet(hs).register(http_server)
    WatchaUserIp(hs).register(http_server)
    WatchaUserlistRestServlet(hs).register(http_server)
