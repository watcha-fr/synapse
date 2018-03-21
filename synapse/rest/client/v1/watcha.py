# -*- coding: utf-8 -*-
#
# *** Unused code **** kept for reference

#
# Specific Watcha register service:
# * Create new unprivileged user with random userid (ou hmac ?)
# * Sets  displayname for the newly created user
# * Create default room for this user (add also pattern so that the room is monitored by Watcha AS)
# * Automate internal user (who invokes the register) joining the created room
# * Send email with link the riot WEB client et userid
# * Send SMS with the password

from twisted.internet import defer
from email.mime.text import MIMEText
import bcrypt
import plivo

from .base import ClientV1RestServlet, client_path_patterns
from synapse.api.errors import AuthError, SynapseError
from synapse.util import stringutils
from synapse.http.servlet import parse_json_object_from_request
from synapse.types import UserID

# TODO: send password via SMS ("Votre mot de passe vous a été envoyé par SMS au numéro: ")

class WatchaRegister(ClientV1RestServlet):
    PATTERNS = client_path_patterns("/watcha/register$")

    def __init__(self, hs):
        super(WatchaRegister, self).__init__(hs)
        self.handlers = hs.get_handlers()
        #self.config = hs.get_config()
        #self.store = hs.get_datastore()

        # FIXME extraire de conf
        auth_id = "MANGRMOGU5YWE1ZWQ4MT"
        auth_token = "MWNlZTJlM2IzZTgzZWU4MzI4ZWUyYTliODYxNWJk"
        self.sms = plivo.RestAPI(auth_id, auth_token)

    @defer.inlineCallbacks
    def on_POST(self, request):
        requester = yield self.auth.get_user_by_req(request, allow_guest=False)
        is_admin = yield self.auth.is_server_admin(requester.user)
        if not is_admin:
            raise AuthError(403, "You are not a server admin")

        params = parse_json_object_from_request(request)
        try:
            user_name = params["username"]
            user_mail = params["email"]
            user_phone = params["phone"]
        except:
            defer.returnValue((400, "Unable to find required params: username, email and phone"))

        # Generate Random userID
        new_userid = stringutils.random_string(10)
        # Generate random Password
        new_pass = stringutils.random_string(8)
        # Create User
        # passwd = bcrypt.hashpw(new_pass + self.config.password_pepper,
        #                        bcrypt.gensalt(self.config.bcrypt_rounds))

        handler = self.handlers.registration_handler
        user_id, token = yield handler.register(
            localpart=new_userid,
            password=new_pass,
            admin=False,
        )

        # Set displayname for newly created user
        yield self.handlers.profile_handler.set_displayname(
            UserID.from_string(user_id),
            requester, user_name, by_admin=True)
        # Create Room
        # Set alias for new room
        # New user autojoin the room
        handler = self.handlers.room_creation_handler
        info = yield handler.create_room(
            requester, {
                "preset": "private_chat",
                "visibility": "private",
                "invite": [user_id],
                "name": "salon " + user_name,
                "room_alias_name": "fs_" + user_name,
                "creation_content": {
                    "m.federate": False
                }
            }
        )
        room_id = info["room_id"]

        # TODO: send email and/or SMS
        defer.returnValue((200, {}))

    def on_OPTIONS(self, request):
        return (200, {})

class WatchaPhone(ClientV1RestServlet):
    PATTERNS = client_path_patterns("/watcha/phone2user/(?P<number>[^/]*)$")

    def __init__(self, hs):
        super(WatchaPhone, self).__init__(hs)
        self.reg = hs.get_handlers().registration_handler

    @defer.inlineCallbacks
    def on_GET(self, request, number):
        requester = yield self.auth.get_user_by_req(request)
        userid = reg.get_user_by_phone(number)

        ret = {}
        if userid is not None:
            ret["user_id"] = userid
            defer.returnValue((200, ret))

def register_servlets(hs, http_server):
    WatchaRegister(hs).register(http_server)
    WatchaPhone(hs).register(http_server)
