# -*- coding: utf-8 -*-
# Copyright 2020 Watcha SAS
#
# This code is not licensed unless agreed with Watcha SAS.
#

import json
import hmac, hashlib
from tests import unittest
from mock import patch

from synapse.rest import admin
from synapse.rest.client.v1 import login, profile, room
from synapse.rest.client.v1 import watcha
from synapse.util.watcha import create_display_inviter_name
from synapse.types import UserID

from ..utils import setup_test_homeserver

myid = "@1234ABCD:test"
PATH_PREFIX = "/_matrix/client/r0"


# Inspired by devops.git/watcha_users
def _call_with_shared_secret(test, shared_secret, endpoint, parameters, additionnal_parameters={}):
    '''Order of parameters matters, so must be list of pairs'''
    mac = hmac.new(
        key=shared_secret.encode('utf-8'),
        digestmod=hashlib.sha1,
    )

    for _, parameter_value in parameters:
        mac.update(str(parameter_value).encode('utf-8'))
        mac.update(b"\x00")

    mac = mac.hexdigest()

    data = dict(parameters)
    data["mac"] = mac
    data.update(additionnal_parameters)

    request, channel = test.make_request(
        "POST",
        endpoint,
        content=json.dumps(data).encode('ascii')
    )

    test.render(request)
    return channel


class InvitationTestCase(unittest.HomeserverTestCase):

    servlets = [
        admin.register_servlets_for_client_rest_resource,
        login.register_servlets,
        profile.register_servlets,
        room.register_servlets,
        watcha.register_servlets,
    ]

    def make_homeserver(self, reactor, clock):

        self.hs = self.setup_test_homeserver(config={
            **self.default_config(),
            "require_auth_for_profile_requests": True,
            "email": {
                "riot_base_url": "http://localhost:8080",
                "smtp_host": "TEST",
                "smtp_port": 10,
                "notif_from": "TEST"
            },
            "public_baseurl": "TEST"
        })

        return self.hs

    def prepare(self, reactor, clock, hs):
        self.owner = self.register_user("owner", "pass")
        self.owner_tok = self.login("owner", "pass")

        self.other_user_id = self.register_user("otheruser", "pass")
        self.other_access_token = self.login("otheruser", "pass")
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

    def _do_external_invite(self, room_id, email):
        self._do_invite(room_id, {"id_server":"localhost",
                                  "medium":"email",
                                  "address":email})

    def test_simple_invite(self):
        self._do_invite(self.room_id, {"user_id":self.other_user_id})

    def _do_test_external_invite(self, email):
        with self.assertLogs('synapse.util.watcha', level='INFO') as cm:
            self._do_external_invite(self.room_id, email)
            self.assertIn("INFO:synapse.util.watcha:NOT Sending registration email to \'%s\', we are in test mode" % email,
                          cm.output[0])
            self.assertIn("INFO:synapse.util.watcha:Email subject is: Invitation à l'espace de travail sécurisé Watcha test",
                          cm.output[1])
            self.assertIn(" http://localhost:8080/#/login/t=",
                          cm.output[3])
            self.assertIn("Bonjour,\\n\\nowner vous a invit\\xc3",
                          cm.output[3])

    def test_external_invite(self):
        self._do_test_external_invite("asfsadf@qwf.com")
            
    def test_external_invite_with_plus_sign(self):
        self._do_test_external_invite("asfsadf+test@qwf.com")
            
    def test_external_invite_second_time(self):
        other_room_id = self.helper.create_room_as(self.owner, tok=self.owner_tok)
        self.test_external_invite()
        self._do_external_invite(other_room_id, "asfsadf@qwf.com")

    def test_external_invite_twice__by_different_inviters(self):
        self.test_external_invite()
        other_room_id = self.helper.create_room_as(self.other_user_id, tok=self.other_access_token)

        request, channel = self.make_request(
            "POST",
            "/rooms/%s/invite" % (other_room_id, ),
            content=json.dumps(
                {"id_server":"localhost",
                 "medium":"email",
                 "address":"asfsadf@qwf.com"}),
            access_token=self.other_access_token,
        )
        self.render(request)
        self.assertEqual(channel.code, 200)
        self.assertEqual(channel.result['body'], b'{}')


class NotAdminWatchaRegisterRestServletTestCase(unittest.HomeserverTestCase):

    servlets = [
        admin.register_servlets_for_client_rest_resource,
        login.register_servlets,
        profile.register_servlets,
        room.register_servlets,
        watcha.register_servlets,
    ]

    def make_homeserver(self, reactor, clock):

        config = self.default_config()
        self.hs = self.setup_test_homeserver(config={
            **self.default_config(),
            "require_auth_for_profile_requests": True,
            "registration_shared_secret": "shared", # also defined in tests/unittest.py, not sure why
            "email": {
                "riot_base_url": "http://localhost:8080",
                "smtp_host": "TEST",
                "smtp_port": 10,
                "notif_from": "TEST"
            },
            "public_baseurl": "TEST"
        })

        return self.hs

    def prepare(self, reactor, clock, hs):
        self.owner = self.register_user("owner", "pass", self.ADMIN)
        self.owner_tok = self.login("owner", "pass")

    def _do_request(self):
        request, channel = self.make_request(
            "POST",
            "/watcha_register",
            content=json.dumps({'user': 'new_user',
                                'full_name': "Full Name",
                                'email': "address@mail.com",
                                'admin': 'notadmin'}),
            access_token=self.owner_tok,
        )
        self.render(request)
        return channel

    ADMIN = False
    def test_watcha_register_servlet(self):
        channel = self._do_request()
        self.assertEqual(channel.code, 403)
        self.assertEqual(channel.result['body'],
                         b'{"errcode":"M_FORBIDDEN","error":"You are not a server admin"}')

class WatchaRegisterRestServletTestCase(NotAdminWatchaRegisterRestServletTestCase):
    ADMIN = True
    def test_watcha_register_servlet(self):
        channel = self._do_request()
        self.assertEqual(channel.code, 200)
        self.assertEqual(channel.result['body'], b'{"display_name":"Full Name","user_id":"@new_user:test"}')

class WatchaRegisterWithSharedSecretRestServletTestCase(NotAdminWatchaRegisterRestServletTestCase):
    def prepare(self, reactor, clock, hs):
        # no user, no login
        pass

    def _do_request(self, content, additionnal_parameters={}):
        return _call_with_shared_secret(self, "shared",
                                        '/watcha_register',
                                        content,
                                        additionnal_parameters)

    def test_watcha_register_servlet(self):
        with self.assertLogs('synapse.util.watcha', level='INFO') as cm:
            channel = self._do_request([('user', 'new_user'),
                                        ('full_name', "Full Name"),
                                        ('email', "address@mail.com"),
                                        ('admin', 'notadmin'),
                                        ('inviter', 'Some Admin User')])
            self.assertEqual(channel.code, 200)
            self.assertEqual(channel.result['body'], b'{"display_name":"Full Name","user_id":"@new_user:test"}')
            self.assertIn("INFO:synapse.util.watcha:NOT Sending registration email to \'address@mail.com\', we are in test mode",
                          cm.output[0])
            self.assertIn("INFO:synapse.util.watcha:Email subject is: Invitation à l'espace de travail sécurisé Watcha test",
                          cm.output[1])
            self.assertIn(" http://localhost:8080/#/login/t=",
                          cm.output[3])
            self.assertIn("Bonjour Full Name,\\n\\nSome Admin User vous a invit\\xc3",
                          cm.output[3])

    def test_watcha_register_servlet_without_inviter(self):
            channel = self._do_request([('user', 'new_user'),
                                        ('full_name', "Full Name"),
                                        ('email', "address@mail.com"),
                                        ('admin', 'notadmin'),
                                        ('inviter', '')]) # empty inviter
            self.assertEqual(channel.code, 403)
            self.assertEqual(channel.result['body'],
                             b'{"errcode":"M_FORBIDDEN","error":"\'inviter\' field is needed if not called from logged in admin user"}')

    def test_watcha_register_servlet_with_password(self):
        with self.assertLogs('synapse.rest.client.v1.watcha', level='INFO') as cm:
            channel = self._do_request([('user', 'new_user'),
                                        ('full_name', "Full Name"),
                                        ('email', "address@mail.com"),
                                        ('admin', 'notadmin'),
                                        ('inviter', 'Some Admin User')], {'password': '1234'})
            self.assertEqual(channel.code, 200)
            self.assertEqual(channel.result['body'], b'{"display_name":"Full Name","user_id":"@new_user:test"}')
            self.assertIn("INFO:synapse.rest.client.v1.watcha:Not sending email for user password for user @new_user:test, password is defined by sender",
                          cm.output[1])
            self.assertIsNotNone(self.login("address@mail.com", "1234"))
            self.assertIsNotNone(self.login("@new_user:test", "1234"))
            
class InvitationDisplayNameTestCase(unittest.HomeserverTestCase):
    def make_homeserver(self, reactor, clock):

        self.hs = self.setup_test_homeserver()
        store = self.hs.get_datastore()

        store.register_user(user_id="@userid:test", password_hash=None, create_profile_with_displayname="User Display")
        self.pump()

        now = int(self.hs.get_clock().time_msec())
        store.user_add_threepid("@userid:test", "email", "userid@email.com", now, now)
        self.pump()
        return self.hs

    def test_invitation_display_name(self):
        # TODO: not working
        pass
        #inviter_display_name = create_display_inviter_name(self.hs, UserID.from_string("@userid:test"))
        #self.assertEquals(list(inviter_display_name), "User Display (userid@email.com)")


class RegistrationTestCase(unittest.HomeserverTestCase):
    servlets = [
        admin.register_servlets_for_client_rest_resource,
        login.register_servlets,
        watcha.register_servlets
    ]

    def make_homeserver(self, reactor, clock):
        config = self.default_config()
        config["require_auth_for_profile_requests"] = True
        self.hs = self.setup_test_homeserver(config=config)
        return self.hs

    def prepare(self, reactor, clock, hs):
        self.owner = self.register_user("owner", "pass",True)
        self.owner_tok = self.login("owner", "pass")

    def test_register_user(self):
        request, channel = self.make_request(
            "POST",
            "/watcha_register",
            content=json.dumps({'user':'test',
                                'email':'test@mail.com',
                                'full_name':'FirstName LastName',
                                'admin':'false',
                                # not used yet... 'inviter':'@test:localhost',
                                }),
            access_token=self.owner_tok,

            )
        self.render(request)
        self.assertEqual(channel.code, 200)
        self.assertEqual(channel.result['body'], b'{"display_name":"FirstName LastName","user_id":"@test:test"}')
