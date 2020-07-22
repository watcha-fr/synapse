# -*- coding: utf-8 -*-

import sys
import json
import hmac
from hashlib import sha1
from urllib.parse import urlparse

import logging


# requires python 2.7.7 or later
from hmac import compare_digest

from twisted.internet import defer

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


def _decode_share_secret_parameters(config, parameter_names, parameters):
    for parameter_name in parameter_names:
        if parameter_name not in parameters:
            raise SynapseError(400, "Expected %s." % parameter_name)

    if not config.registration_shared_secret:
        raise SynapseError(400, "Shared secret registration is not enabled")

    # Its important to check as we use null bytes as HMAC field separators
    if any("\x00" in parameters[parameter_name] for parameter_name in parameter_names):
        raise SynapseError(400, "Invalid message")

    got_mac = str(parameters["mac"])

    want_mac = hmac.new(
        key=config.registration_shared_secret.encode("utf-8"), digestmod=sha1,
    )
    for parameter_name in parameter_names:
        want_mac.update(repr(parameters[parameter_name]).encode("utf-8"))
        want_mac.update(b"\x00")
    if not compare_digest(want_mac.hexdigest(), got_mac):
        logger.error(
            "Failed to decode HMAC for parameters names: "
            + repr(parameter_names)
            + " and values: "
            + repr(parameters)
        )

        raise SynapseError(
            403, "HMAC incorrect",
        )
    return parameters


@defer.inlineCallbacks
def _check_admin(auth, request):
    requester = yield auth.get_user_by_req(request)
    is_admin = yield auth.is_server_admin(requester.user)
    if not is_admin:
        raise AuthError(403, "You are not a server admin")


@defer.inlineCallbacks
def _check_admin_or_secret(config, auth, request, parameter_names):
    auth_headers = request.requestHeaders.getRawHeaders("Authorization")
    parameter_json = parse_json_object_from_request(request)
    if auth_headers:
        yield _check_admin(auth, request)
        ret = parameter_json
    else:
        # auth by checking that the HMAC is valid. this raises an error otherwise.
        ret = _decode_share_secret_parameters(config, parameter_names, parameter_json)

    defer.returnValue(ret)


class WatchaUserlistRestServlet(RestServlet):

    PATTERNS = client_patterns("/watcha_user_list", v1=True)

    def __init__(self, hs):
        super(WatchaUserlistRestServlet, self).__init__()
        self.auth = hs.get_auth()
        self.handlers = hs.get_handlers()

    @defer.inlineCallbacks
    def on_GET(self, request):
        yield _check_admin(self.auth, request)
        ret = yield self.handlers.watcha_admin_handler.watcha_user_list()
        defer.returnValue((200, ret))


class WatchaRoomMembershipRestServlet(RestServlet):

    PATTERNS = client_patterns("/watcha_room_membership", v1=True)

    def __init__(self, hs):
        super(WatchaRoomMembershipRestServlet, self).__init__()
        self.auth = hs.get_auth()
        self.handlers = hs.get_handlers()

    @defer.inlineCallbacks
    def on_GET(self, request):
        yield _check_admin(self.auth, request)
        ret = yield self.handlers.watcha_admin_handler.watcha_room_membership()
        defer.returnValue((200, ret))


class WatchaRoomNameRestServlet(RestServlet):

    PATTERNS = client_patterns("/watcha_room_name", v1=True)

    def __init__(self, hs):
        super(WatchaRoomNameRestServlet, self).__init__()
        self.auth = hs.get_auth()
        self.handlers = hs.get_handlers()

    @defer.inlineCallbacks
    def on_GET(self, request):
        yield _check_admin(self.auth, request)
        ret = yield self.handlers.watcha_admin_handler.watcha_room_name()
        defer.returnValue((200, ret))


class WatchaSendNextcloudActivityToWatchaRoomServlet(RestServlet):

    PATTERNS = client_patterns("/watcha_room_nextcloud_activity", v1=True)

    def __init__(self, hs):
        super().__init__()
        self.hs = hs
        self.auth = hs.get_auth()
        self.event_creation_handler = hs.get_event_creation_handler()
        self.handler = hs.get_handlers()

    @defer.inlineCallbacks
    def on_POST(self, request):
        params = yield _check_admin_or_secret(
            self.hs.config, self.auth, request, ["file_name", "link", "directory"],
        )

        nc_file_name = params["file_name"]
        nc_link = params["link"]
        nc_directory = params["directory"]

        if not nc_file_name or not nc_link or not nc_directory:
            raise SynapseError(
                400, "'file_name', 'link' and 'directory args cannot be empty.",
            )

        server_name = self.hs.get_config().server_name

        nc_directory_parsed = urlparse(nc_directory)
        nc_link_parsed = urlparse(nc_link)

        if not {"http", "https"}.issuperset((nc_directory_parsed.scheme, nc_link_parsed.scheme)):
            raise SynapseError(
                400, "Wrong Nextcloud URL scheme.",
            )

        if {server_name} != {nc_directory_parsed.netloc, nc_link_parsed.netloc}:
            raise SynapseError(
                400, "Wrong Nextcloud URL netloc.",
            )

        room_id = yield self.handler.watcha_room_handler.get_roomId_from_NC_folder_url(nc_directory)

        if not room_id:
            raise SynapseError(
                400, "No room has linked with this Nextcloud folder url."
            )

        first_room_admin = yield self.handler.watcha_room_handler.get_first_room_admin(room_id)

        if not first_room_admin:
            raise SynapseError(
                400,
                "No administrators are in the room. The Nextcloud notification cannot be posted.",
            )

        requester = create_requester(first_room_admin)

        event_dict = {
            "type": EventTypes.Message,
            "content": {
                "body": nc_file_name,
                "filename": nc_file_name,
                "msgtype": "m.file",
                "url": nc_link,
            },
            "room_id": room_id,
            "sender": requester.user.to_string(),
        }

        event = yield self.event_creation_handler.create_and_send_nonmember_event(
            requester, event_dict
        )

        return (200, {"event_id": event.event_id})


class WatchaDisplayNameRestServlet(RestServlet):

    PATTERNS = client_patterns("/watcha_display_name", v1=True)

    def __init__(self, hs):
        super(WatchaDisplayNameRestServlet, self).__init__()
        self.auth = hs.get_auth()
        self.handlers = hs.get_handlers()

    @defer.inlineCallbacks
    def on_GET(self, request):
        yield _check_admin(self.auth, request)
        ret = yield self.handlers.watcha_admin_handler.watcha_display_name()
        defer.returnValue((200, ret))


class WatchaRoomListRestServlet(RestServlet):
    PATTERNS = client_patterns("/watcha_room_list", v1=True)

    def __init__(self, hs):
        super(WatchaRoomListRestServlet, self).__init__()
        self.auth = hs.get_auth()
        self.handlers = hs.get_handlers()

    @defer.inlineCallbacks
    def on_GET(self, request):
        yield _check_admin(self.auth, request)
        ret = yield self.handlers.watcha_admin_handler.watcha_room_list()
        defer.returnValue((200, ret))


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

    @defer.inlineCallbacks
    def on_PUT(self, request, target_user_id):
        yield _check_admin(self.auth, request)
        params = parse_json_object_from_request(request)
        new_email = params["new_email"]

        if not new_email:
            raise SynapseError(400, "Missing 'new_email' arg")

        users = yield self.handlers.admin_handler.get_users()
        if not target_user_id in [user["name"] for user in users]:
            raise SynapseError(
                400, "The target user is not registered in this homeserver."
            )

        try:
            email = yield self.account_activity_handler.get_email_address_for_user(
                target_user_id
            )
        except SynapseError:
            logger.error("No email are defined for this user.")
            raise

        yield self.auth_handler.delete_threepid(
            target_user_id, "email", email, id_server=None
        )
        yield self.auth_handler.add_threepid(
            target_user_id, "email", new_email, self.hs.get_clock().time_msec()
        )

        defer.returnValue((200, {}))


class WatchaUpdateUserRoleRestServlet(RestServlet):
    PATTERNS = client_patterns(
        "/watcha_update_user_role/(?P<target_user_id>[^/]*)", v1=True
    )

    def __init__(self, hs):
        super(WatchaUpdateUserRoleRestServlet, self).__init__()
        self.auth = hs.get_auth()
        self.handlers = hs.get_handlers()
        self.admin_handler = hs.get_handlers().admin_handler

    @defer.inlineCallbacks
    def on_PUT(self, request, target_user_id):
        yield _check_admin(self.auth, request)
        params = parse_json_object_from_request(request)

        users = yield self.admin_handler.get_users()
        if not target_user_id in [user["name"] for user in users]:
            raise SynapseError(
                400, "The target user is not registered in this homeserver."
            )

        role = params["role"]
        if role not in ["partner", "collaborator", "admin"]:
            raise SynapseError(400, "%s is not a defined role." % role)

        result = yield self.handlers.watcha_admin_handler.watcha_update_user_role(
            target_user_id, role
        )
        defer.returnValue((200, {"new_role": result}))


class WatchaIsAdmin(RestServlet):

    PATTERNS = client_patterns("/watcha_is_admin", v1=True)

    def __init__(self, hs):
        super(WatchaIsAdmin, self).__init__()
        self.auth = hs.get_auth()

    @defer.inlineCallbacks
    def on_GET(self, request):
        requester = yield self.auth.get_user_by_req(request)
        is_admin = yield self.auth.is_server_admin(requester.user)
        defer.returnValue((200, {"is_admin": is_admin}))


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

    @defer.inlineCallbacks
    def on_GET(self, request):
        yield _check_admin(self.auth, request)
        ret = yield self.handlers.watcha_admin_handler.watcha_admin_stat()
        defer.returnValue((200, ret))


class WatchaUserIp(RestServlet):

    PATTERNS = client_patterns("/watcha_user_ip/(?P<target_user_id>[^/]*)", v1=True)

    def __init__(self, hs):
        super(WatchaUserIp, self).__init__()
        self.hs = hs
        self.store = hs.get_datastore()
        self.auth = hs.get_auth()
        self.handlers = hs.get_handlers()

    @defer.inlineCallbacks
    def on_GET(self, request, target_user_id):
        yield _check_admin(self.auth, request)
        ret = yield self.handlers.watcha_admin_handler.watcha_user_ip(target_user_id)
        defer.returnValue((200, ret))


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
        self.registration_handler = hs.get_registration_handler()

    @defer.inlineCallbacks
    def on_POST(self, request):
        params = yield _check_admin_or_secret(
            self.hs.config,
            self.auth,
            request,
            ["user", "full_name", "email", "admin", "inviter"],
        )

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

        full_user_id = yield self.hs.auth_handler.find_user_id_by_email(email)
        if full_user_id:
            raise SynapseError(
                500,
                "A user with this email address already exists. Cannot create a new one.",
            )

        try:
            requester = yield self.auth.get_user_by_req(request)
        except Exception:
            # no token - not logged in - inviter should be provided
            requester = None

        if requester:
            inviter_name = yield create_display_inviter_name(self.hs, requester.user)
        else:
            if not params["inviter"]:
                raise AuthError(
                    403,
                    "'inviter' field is needed if not called from logged in admin user",
                )
            inviter_name = params["inviter"]

        if 'password' in params:
            password = params['password']
        else:            
            password = generate_password()

        admin = params["admin"] == "admin"
        bind_emails = [params["email"]]
        user_id = yield self.registration_handler.register_user(
            localpart=params["user"],
            password=password,
            admin=admin,
            bind_emails=bind_emails,
        )
        user = UserID.from_string(user_id)
        yield self.hs.profile_handler.set_displayname(
            user, create_requester(user_id), params["full_name"], by_admin=True
        )

        display_name = yield self.hs.profile_handler.get_displayname(user)

        if 'password' not in params:
            token = compute_registration_token(user_id, email, password)

            send_registration_email(
                self.hs.config,
                email,
                template_name="invite_new_account",
                token=token,
                inviter_name=inviter_name,
                full_name=display_name,
            )
        else:
            logger.info("Not sending email for user password for user %s, password is defined by sender", user_id)

        return (200, {"display_name": display_name, "user_id": user_id})


class WatchaResetPasswordRestServlet(RestServlet):
    PATTERNS = client_patterns("/watcha_reset_password", v1=True)

    def __init__(self, hs):
        super(WatchaResetPasswordRestServlet, self).__init__()
        self.hs = hs
        self.handlers = hs.get_handlers()
        self.auth = hs.get_auth()
        # insertion for watcha
        self.account_activity_handler = hs.get_account_validity_handler()
        # end of insertion

    @defer.inlineCallbacks
    def on_POST(self, request):
        params = yield _check_admin_or_secret(
            self.hs.config, self.auth, request, ["user"]
        )

        user_id = params["user"]
        # FIXME: when called from the 'watcha_users' script,
        # the user_id usually doesn't have the server name. add it.
        if not user_id.startswith("@"):
            user_id = "@" + params["user"] + ":" + self.hs.get_config().server_name

        password = generate_password()
        logger.info("Setting password for user %s", user_id)
        user = UserID.from_string(user_id)

        email = yield self.account_activity_handler.get_email_address_for_user(user_id)

        requester = create_requester(user_id)
        yield self.hs.get_set_password_handler().set_password(
            user_id, password, requester
        )
        yield self.handlers.watcha_admin_handler.watcha_reactivate_account(user_id)

        try:
            display_name = yield self.hs.profile_handler.get_displayname(user)
        except:
            display_name = None

        send_registration_email(
            self.hs.config,
            email,
            template_name="reset_password",
            token=compute_registration_token(user_id, email, password),
            inviter_name=None,
            full_name=display_name,
        )

        defer.returnValue((200, {}))

def register_servlets(hs, http_server):
    WatchaResetPasswordRestServlet(hs).register(http_server)
    WatchaRegisterRestServlet(hs).register(http_server)
    WatchaUpdateUserRoleRestServlet(hs).register(http_server)
    WatchaUserIp(hs).register(http_server)
    WatchaAdminStatsRestServlet(hs).register(http_server)
    WatchaIsAdmin(hs).register(http_server)
    WatchaUpdateMailRestServlet(hs).register(http_server)
    WatchaUserlistRestServlet(hs).register(http_server)
    WatchaRoomListRestServlet(hs).register(http_server)
    WatchaRoomMembershipRestServlet(hs).register(http_server)
    WatchaRoomNameRestServlet(hs).register(http_server)
    WatchaSendNextcloudActivityToWatchaRoomServlet(hs).register(http_server)
    WatchaDisplayNameRestServlet(hs).register(http_server)
    