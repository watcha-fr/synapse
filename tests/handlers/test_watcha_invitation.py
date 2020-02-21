# -*- coding: utf-8 -*-
# Copyright 2020 Watcha SAS
#
# This code is not licensed unless agreed with Watcha SAS.
#

import json

from synapse.rest import admin
from synapse.rest.client.v1 import login, profile, room
from synapse.rest.client.v1 import watcha
from tests import unittest

from ..utils import setup_test_homeserver

myid = "@1234ABCD:test"
PATH_PREFIX = "/_matrix/client/r0"

class InvitationTestCase(unittest.HomeserverTestCase):

    servlets = [
        admin.register_servlets_for_client_rest_resource,
        login.register_servlets,
        profile.register_servlets,
        room.register_servlets,
        watcha.register_servlets,
    ]

    def make_homeserver(self, reactor, clock):

        config = self.default_config()
        config["require_auth_for_profile_requests"] = True
        self.hs = self.setup_test_homeserver(config=config)

        return self.hs

    def prepare(self, reactor, clock, hs):
        # User owning the requested profile.
        self.owner = self.register_user("owner", "pass",True)
        self.owner_tok = self.login("owner", "pass")

        self.other_user_id = self.register_user("otheruser", "pass")
        self.other_access_token = self.login("otheruser", "pass")
        
        # User requesting the profile.
        self.requester = self.register_user("requester", "pass")
        self.requester_tok = self.login("requester", "pass")

        self.room_id = self.helper.create_room_as(self.owner, tok=self.owner_tok)

    def _do_invite(self, room_id, request_content):
        request, channel = self.make_request(
            "POST",
            "/rooms/%s/invite" % (room_id, ),
            content=json.dumps(request_content),
            access_token=self.owner_tok,
        )
        self.render(request)
        self.assertEqual(channel.code, 200)
        self.assertEqual(channel.result['body'], b'{}')

    def test_register_user(self):
    #/_matrix/client/r0/watcha_register
        request, channel = self.make_request(
            "POST",
            "/watcha_register",
            content=json.dumps({'user':'test',
                                'email':'test@mail.com',
                                'full_name':'test sdsads',
                                'admin':'false',
                                'inviter':'@test:localhost',
                                }),
            access_token=self.owner_tok,

            )
        self.render(request)                                  
        self.assertEqual(channel.code, 200)
        #self.assertEqual(channel.result['body'], b'{}')

    def _do_external_invite(self, room_id):
        self._do_invite(room_id, {"id_server":"localhost",
                                  "medium":"email",
                                  "address":"asfsadf@qwf.com"})
        
    def test_simple_invite(self):
        self._do_invite(self.room_id, {"user_id":self.other_user_id})

    def test_external_invite(self):
        self._do_external_invite(self.room_id)

    def test_external_invite_second_time(self):
        other_room_id = self.helper.create_room_as(self.owner, tok=self.owner_tok)
        self.test_external_invite()
        self._do_external_invite(other_room_id)
