# -*- coding: utf-8 -*-
# Copyright 2017 New Vector Ltd
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
import logging

from twisted.internet import defer

from synapse.types import UserID

logger = logging.getLogger(__name__)


class ModuleApi(object):
    """A proxy object that gets passed to password auth providers so they
    can register new users etc if necessary.
    """

    def __init__(self, hs, auth_handler):
        self.hs = hs

        self._store = hs.get_datastore()
        self._auth = hs.get_auth()
        self._auth_handler = auth_handler

    def get_user_by_req(self, req, allow_guest=False, allow_partner=False):
        """Check the access_token provided for a request

        Args:
            req (twisted.web.server.Request): Incoming HTTP request
            allow_guest (bool): True if guest users should be allowed. If this
                is False, and the access token is for a guest user, an
                AuthError will be thrown
            allow_partner (bool): True if partner users should be allowed.
        Returns:
            twisted.internet.defer.Deferred[synapse.types.Requester]:
                the requester for this request
        Raises:
            synapse.api.errors.AuthError: if no user by that token exists,
                or the token is invalid.
        """
        return self._auth.get_user_by_req(req, allow_guest, allow_partner)

    def get_qualified_user_id(self, username):
        """Qualify a user id, if necessary

        Takes a user id provided by the user and adds the @ and :domain to
        qualify it, if necessary

        Args:
            username (str): provided user id

        Returns:
            str: qualified @user:id
        """
        if username.startswith("@"):
            return username
        return UserID(username, self.hs.hostname).to_string()

    def check_user_exists(self, user_id):
        """Check if user exists.

        Args:
            user_id (str): Complete @user:id

        Returns:
            Deferred[str|None]: Canonical (case-corrected) user_id, or None
               if the user is not registered.
        """
        return self._auth_handler.check_user_exists(user_id)

    @defer.inlineCallbacks
    def register(self, localpart, displayname=None, emails=[]):
        """Registers a new user with given localpart and optional displayname, emails.

        Also returns an access token for the new user.

        Deprecated: avoid this, as it generates a new device with no way to
        return that device to the user. Prefer separate calls to register_user and
        register_device.

        Args:
            localpart (str): The localpart of the new user.
            displayname (str|None): The displayname of the new user.
            emails (List[str]): Emails to bind to the new user.

        Returns:
            Deferred[tuple[str, str]]: a 2-tuple of (user_id, access_token)
        """
        logger.warning(
            "Using deprecated ModuleApi.register which creates a dummy user device."
        )
        user_id = yield self.register_user(localpart, displayname, emails)
        _, access_token = yield self.register_device(user_id)
        return (user_id, access_token)

    def register_user(self, localpart, displayname=None, emails=[]):
        """Registers a new user with given localpart and optional displayname, emails.

        Args:
            localpart (str): The localpart of the new user.
            displayname (str|None): The displayname of the new user.
            emails (List[str]): Emails to bind to the new user.

        Returns:
            Deferred[str]: user_id
        """
        return self.hs.get_registration_handler().register_user(
            localpart=localpart, default_display_name=displayname, bind_emails=emails
        )

    def register_device(self, user_id, device_id=None, initial_display_name=None):
        """Register a device for a user and generate an access token.

        Args:
            user_id (str): full canonical @user:id
            device_id (str|None): The device ID to check, or None to generate
                a new one.
            initial_display_name (str|None): An optional display name for the
                device.

        Returns:
            defer.Deferred[tuple[str, str]]: Tuple of device ID and access token
        """
        return self.hs.get_registration_handler().register_device(
            user_id=user_id,
            device_id=device_id,
            initial_display_name=initial_display_name,
        )

    @defer.inlineCallbacks
    def invalidate_access_token(self, access_token):
        """Invalidate an access token for a user

        Args:
            access_token(str): access token

        Returns:
            twisted.internet.defer.Deferred - resolves once the access token
               has been removed.

        Raises:
            synapse.api.errors.AuthError: the access token is invalid
        """
        # see if the access token corresponds to a device
        user_info = yield self._auth.get_user_by_access_token(access_token)
        device_id = user_info.get("device_id")
        user_id = user_info["user"].to_string()
        if device_id:
            # delete the device, which will also delete its access tokens
            yield self.hs.get_device_handler().delete_device(user_id, device_id)
        else:
            # no associated device. Just delete the access token.
            yield self._auth_handler.delete_access_token(access_token)

    def run_db_interaction(self, desc, func, *args, **kwargs):
        """Run a function with a database connection

        Args:
            desc (str): description for the transaction, for metrics etc
            func (func): function to be run. Passed a database cursor object
                as well as *args and **kwargs
            *args: positional args to be passed to func
            **kwargs: named args to be passed to func

        Returns:
            Deferred[object]: result of func
        """
        return self._store.runInteraction(desc, func, *args, **kwargs)
