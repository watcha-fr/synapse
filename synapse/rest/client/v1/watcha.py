import sys
import json
import hmac
from hashlib import sha1
from urllib.parse import urlparse, parse_qs

import logging


# requires python 2.7.7 or later
from hmac import compare_digest

from synapse.api.errors import AuthError, SynapseError
from synapse.http.servlet import RestServlet, parse_json_object_from_request
from synapse.rest.client.v2_alpha._base import client_patterns
from synapse.util.watcha import (
    generate_password,
    send_registration_email,
    compute_registration_token,
    create_display_inviter_name,
)
from synapse.types import UserID, create_requester
from synapse.api.constants import Membership, EventTypes

logger = logging.getLogger(__name__)


async def _check_admin(auth, request):
    requester = await auth.get_user_by_req(request)
    is_admin = await auth.is_server_admin(requester.user)
    if not is_admin:
        raise AuthError(403, "You are not a server admin")


class WatchaUserlistRestServlet(RestServlet):

    PATTERNS = client_patterns("/watcha_user_list", v1=True)

    def __init__(self, hs):
        super(WatchaUserlistRestServlet, self).__init__()
        self.auth = hs.get_auth()
        self.handlers = hs.get_handlers()

    async def on_GET(self, request):
        await _check_admin(self.auth, request)
        ret = await self.handlers.watcha_admin_handler.watcha_user_list()
        return 200, ret


class WatchaRoomMembershipRestServlet(RestServlet):

    PATTERNS = client_patterns("/watcha_room_membership", v1=True)

    def __init__(self, hs):
        super(WatchaRoomMembershipRestServlet, self).__init__()
        self.auth = hs.get_auth()
        self.handlers = hs.get_handlers()

    async def on_GET(self, request):
        await _check_admin(self.auth, request)
        ret = await self.handlers.watcha_admin_handler.watcha_room_membership()
        return 200, ret


class WatchaRoomNameRestServlet(RestServlet):

    PATTERNS = client_patterns("/watcha_room_name", v1=True)

    def __init__(self, hs):
        super(WatchaRoomNameRestServlet, self).__init__()
        self.auth = hs.get_auth()
        self.handlers = hs.get_handlers()

    async def on_GET(self, request):
        await _check_admin(self.auth, request)
        ret = await self.handlers.watcha_admin_handler.watcha_room_name()
        return 200, ret


class WatchaSendNextcloudActivityToWatchaRoomServlet(RestServlet):

    PATTERNS = client_patterns("/watcha_room_nextcloud_activity", v1=True)

    def __init__(self, hs):
        super().__init__()
        self.hs = hs
        self.auth = hs.get_auth()
        self.handler = hs.get_handlers()

    async def on_POST(self, request):
        await _check_admin(
            self.auth, request,
        )
        params = parse_json_object_from_request(request)

        file_name = params["file_name"]
        file_url = params["file_url"]
        notifications = params["notifications"]

        if (
            not file_name
            or not file_url
            or not notifications
        ):
            raise SynapseError(
                400, "Some data in payload have empty value.",
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
                400, "The Nextcloud url is not recognized.",
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

            notification_sent = {
                "file_name": file_name,
                "file_operation": file_operation,
            }

            try:
                rooms = await self.handler.watcha_room_handler.get_room_list_to_send_NC_notification(
                    notification["directory"],
                    notification["limit_of_notification_propagation"],
                )
                notification_sent["rooms"] = rooms
            except SynapseError as e:
                logger.error("Error during getting rooms to send notifications : %s", e)
                continue

            try:
                await self.handler.watcha_room_handler.send_nextcloud_notification_to_rooms(
                    rooms, file_name, file_url, file_operation
                )
            except SynapseError as e:
                logger.error("Error during sending notification to room : %s", e)
                continue

            notifications_sent.append(notification_sent)

        return (200, notifications_sent)


class WatchaDisplayNameRestServlet(RestServlet):

    PATTERNS = client_patterns("/watcha_display_name", v1=True)

    def __init__(self, hs):
        super(WatchaDisplayNameRestServlet, self).__init__()
        self.auth = hs.get_auth()
        self.handlers = hs.get_handlers()

    async def on_GET(self, request):
        await _check_admin(self.auth, request)
        ret = await self.handlers.watcha_admin_handler.watcha_display_name()
        return 200, ret


class WatchaRoomListRestServlet(RestServlet):
    PATTERNS = client_patterns("/watcha_room_list", v1=True)

    def __init__(self, hs):
        super(WatchaRoomListRestServlet, self).__init__()
        self.auth = hs.get_auth()
        self.handlers = hs.get_handlers()

    async def on_GET(self, request):
        await _check_admin(self.auth, request)
        ret = await self.handlers.watcha_admin_handler.watcha_room_list()
        return 200, ret


class WatchaUpdateMailRestServlet(RestServlet):
    PATTERNS = client_patterns(
        "/watcha_update_email/(?P<target_user_id>[^/]*)", v1=True
    )

    def __init__(self, hs):
        super(WatchaUpdateMailRestServlet, self).__init__()
        self.hs = hs
        self.auth = hs.get_auth()
        self.handlers = hs.get_handlers()
        self.auth_handler = hs.get_auth_handler()
        self.account_activity_handler = hs.get_account_validity_handler()

    async def on_PUT(self, request, target_user_id):
        await _check_admin(self.auth, request)
        params = parse_json_object_from_request(request)
        new_email = params["new_email"]

        if not new_email:
            raise SynapseError(400, "Missing 'new_email' arg")

        users = await self.handlers.admin_handler.get_users()
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
        super(WatchaUpdateUserRoleRestServlet, self).__init__()
        self.auth = hs.get_auth()
        self.handlers = hs.get_handlers()
        self.admin_handler = hs.get_handlers().admin_handler

    async def on_PUT(self, request, target_user_id):
        await _check_admin(self.auth, request)
        params = parse_json_object_from_request(request)

        users = await self.admin_handler.get_users()
        if not target_user_id in [user["name"] for user in users]:
            raise SynapseError(
                400, "The target user is not registered in this homeserver."
            )

        role = params["role"]
        if role not in ["partner", "collaborator", "admin"]:
            raise SynapseError(400, "%s is not a defined role." % role)

        result = await self.handlers.watcha_admin_handler.watcha_update_user_role(
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
        super(WatchaAdminStatsRestServlet, self).__init__()
        self.hs = hs
        self.store = hs.get_datastore()
        self.auth = hs.get_auth()
        self.handlers = hs.get_handlers()

    async def on_GET(self, request):
        await _check_admin(self.auth, request)
        ret = await self.handlers.watcha_admin_handler.watcha_admin_stat()
        return 200, ret


class WatchaUserIp(RestServlet):

    PATTERNS = client_patterns("/watcha_user_ip/(?P<target_user_id>[^/]*)", v1=True)

    def __init__(self, hs):
        super(WatchaUserIp, self).__init__()
        self.hs = hs
        self.store = hs.get_datastore()
        self.auth = hs.get_auth()
        self.handlers = hs.get_handlers()

    async def on_GET(self, request, target_user_id):
        await _check_admin(self.auth, request)
        ret = await self.handlers.watcha_admin_handler.watcha_user_ip(target_user_id)
        return 200, ret


class WatchaRegisterRestServlet(RestServlet):
    """
    Registration of users.
    Requester must either be logged in as an admin, or supply a valid HMAC (generated from the registration_shared_secret)
    """

    PATTERNS = client_patterns("/watcha_register", v1=True)

    def __init__(self, hs):
        super(WatchaRegisterRestServlet, self).__init__()
        self.hs = hs
        self.auth = hs.get_auth()
        self.auth_handler = hs.get_auth_handler()
        self.registration_handler = hs.get_registration_handler()

    async def on_POST(self, request):
        await _check_admin(
            self.auth,
            request,
        )
        params = parse_json_object_from_request(request)
        logger.info("Adding Watcha user...")

        if params["user"].lower() != params["user"]:
            raise SynapseError(
                500, "User name must be lowercase",
            )

        email = params["email"]
        if not email.strip():
            # the admin seems to have a bug and send empty email adresses sometimes.
            # (never bad to be resilient in any case)
            raise SynapseError(
                500, "Email address cannot be empty",
            )

        full_user_id = await self.auth_handler.find_user_id_by_email(email)
        if full_user_id:
            raise SynapseError(
                500,
                "A user with this email address already exists. Cannot create a new one.",
            )

        try:
            requester = await self.auth.get_user_by_req(request)
        except Exception:
            # no token - not logged in - inviter should be provided
            requester = None

        if requester:
            inviter_name = await create_display_inviter_name(self.hs, requester.user)
        else:
            if not params["inviter"]:
                raise AuthError(
                    403,
                    "'inviter' field is needed if not called from logged in admin user",
                )
            inviter_name = params["inviter"]

        send_email = False
        password = params['password']

        if not password:
            password = generate_password()
            send_email = True

        password_hash = await self.auth_handler.hash(password)
        admin = params["admin"] == "admin"
        bind_emails = [params["email"]]

        user_id = await self.registration_handler.register_user(
            localpart=params["user"],
            password_hash=password_hash,
            admin=admin,
            bind_emails=bind_emails,
        )

        user = UserID.from_string(user_id)
        await self.hs.profile_handler.set_displayname(
            user, create_requester(user_id), params["full_name"], by_admin=True
        )

        display_name = await self.hs.profile_handler.get_displayname(user)

        if send_email:
            token = compute_registration_token(user_id, email, password)

            await send_registration_email(
                self.hs.config,
                email,
                template_name="invite_new_account",
                token=token,
                inviter_name=inviter_name,
                full_name=display_name,
            )
        else:
            logger.info("Not sending email for user password for user %s, password is defined by sender", user_id)
        return 200, {"display_name": display_name, "user_id": user_id}


class WatchaResetPasswordRestServlet(RestServlet):
    PATTERNS = client_patterns("/watcha_reset_password", v1=True)

    def __init__(self, hs):
        super(WatchaResetPasswordRestServlet, self).__init__()
        self.hs = hs
        self.handlers = hs.get_handlers()
        self.auth = hs.get_auth()
        self.auth_handler = hs.get_auth_handler()
        self.account_activity_handler = hs.get_account_validity_handler()

    async def on_POST(self, request):
        await _check_admin(
            self.auth, request,
        )
        params = parse_json_object_from_request(request)
        user_id = params["user"]
        # FIXME: when called from the 'watcha_users' script,
        # the user_id usually doesn't have the server name. add it.
        if not user_id.startswith("@"):
            user_id = "@" + params["user"] + ":" + self.hs.get_config().server_name

        password = generate_password()
        password_hash = await self.auth_handler.hash(password)

        logger.info("Setting password for user %s", user_id)
        user = UserID.from_string(user_id)

        email = await self.account_activity_handler.get_email_address_for_user(user_id)

        requester = create_requester(user_id)
        await self.hs.get_set_password_handler().set_password(
            user_id, password_hash, requester
        )
        await self.handlers.watcha_admin_handler.watcha_reactivate_account(user_id)

        try:
            display_name = await self.hs.profile_handler.get_displayname(user)
        except:
            display_name = None

        await send_registration_email(
            self.hs.config,
            email,
            template_name="reset_password",
            token=compute_registration_token(user_id, email, password),
            inviter_name=None,
            full_name=display_name,
        )

        return 200, {}

def register_servlets(hs, http_server):
    WatchaResetPasswordRestServlet(hs).register(http_server)
    WatchaRegisterRestServlet(hs).register(http_server)
    WatchaUpdateUserRoleRestServlet(hs).register(http_server)
    WatchaUserIp(hs).register(http_server)
    WatchaAdminStatsRestServlet(hs).register(http_server)
    WatchaUpdateMailRestServlet(hs).register(http_server)
    WatchaUserlistRestServlet(hs).register(http_server)
    WatchaRoomListRestServlet(hs).register(http_server)
    WatchaRoomMembershipRestServlet(hs).register(http_server)
    WatchaRoomNameRestServlet(hs).register(http_server)
    WatchaSendNextcloudActivityToWatchaRoomServlet(hs).register(http_server)
    WatchaDisplayNameRestServlet(hs).register(http_server)
