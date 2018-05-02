# -*- coding: utf-8 -*-

from twisted.internet import defer

from .base import ClientV1RestServlet, client_path_patterns
from synapse.http.servlet import parse_json_object_from_request

from synapse.rest.client.v1.register import RegisterRestServlet
from synapse.rest.client.v1.admin import ResetPasswordRestServlet

#from subprocess import call
import subprocess
#from os import system

import logging

logger = logging.getLogger(__name__)

'''(only inheriting from RegisterRestServlet to get the _do_shared_secret method)'''
class WatchaResetPasswordRestServlet(ResetPasswordRestServlet, RegisterRestServlet):
    PATTERNS = client_path_patterns("/reset_password")

    @defer.inlineCallbacks
    def on_POST(self, request):
        session_info = self._get_session_info(request, None)
        params = parse_json_object_from_request(request)

        # monkeypatch the handler to do a set_password instead of a register...
        servlet = self
        def set_password_register(self, localpart, password, admin):
            logger.info("Setting password for user %s", localpart)
            servlet._set_password_handler.set_password(
                localpart, password, None # no requester
            )
            return localpart, None # TODO: token

        handler = self.handlers.registration_handler
        import types
        register = handler.register
        try:
            logger.info("Monkeypatching registrations_handler...")
            handler.register = types.MethodType(set_password_register, handler)
            response = yield self._do_shared_secret(request, params, session_info)
        finally:
            logger.info("...Reverting monkeypatched registration_handler")
            handler.register = register
        defer.returnValue((200, response))


class WatchaStats(ClientV1RestServlet):
    PATTERNS = client_path_patterns("/stats")

    def __init__(self, hs):
        super(WatchaStats, self).__init__(hs)
        self.store = hs.get_datastore()

    @defer.inlineCallbacks
    def on_GET(self, request):
        ### fetch the number of local and external users.
        user_stats = yield self.store.get_count_users_partners()

        ### get the version of the synapse server, if installed with pip.

        # this method may block the synapse process for a while, as pip does not immediately return.
        #synapse_version = system('pip freeze | grep "matrix-synapse==="')

        try:
            proc = subprocess.Popen(['pip', 'freeze'], stdout=subprocess.PIPE)
            output = subprocess.check_output(('grep', 'matrix-synapse==='), stdin=proc.stdout)
            proc.wait()
            (synapse_version, err) = output.communicate()

        except subprocess.CalledProcessError as e:
            # when grep does not find any line, this error is thrown. it is normal behaviour during development.
            synapse_version = "unavailable"

        defer.returnValue((200, { "users": user_stats, "synapse_version": synapse_version }))


def register_servlets(hs, http_server):
    WatchaStats(hs).register(http_server)
    WatchaResetPasswordRestServlet(hs).register(http_server)
