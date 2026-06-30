# Copyright 2021 Watcha
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

from synapse.http.server import JsonResource
from synapse.rest.watcha.nextcloud import (
    GetCalendarRestServlet,
    ListUsersOwnCalendarsRestServlet,
    ReorderCalendarsRestServlet,
)


class WatchaRestResource(JsonResource):
    """
    The REST resource which gets mounted at /_watcha/, including:
       * /_watcha/nextcloud
       * etc
    """

    def __init__(self, hs):
        JsonResource.__init__(self, hs, canonical_json=False)
        register_servlets(hs, self)


def register_servlets(hs, http_server):
    """
    Register all the watcha servlets.
    """
    ListUsersOwnCalendarsRestServlet(hs).register(http_server)
    GetCalendarRestServlet(hs).register(http_server)
    ReorderCalendarsRestServlet(hs).register(http_server)
