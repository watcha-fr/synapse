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

        email_address = params["email"].strip()
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
            password=params.get("password"),
            is_admin=params.get("admin", False),
            default_display_name=params.get("displayname", "").strip() or None,
        )

        return 200, {"user_id": user_id}


def register_servlets(hs, http_server):
    WatchaRegisterRestServlet(hs).register(http_server)
