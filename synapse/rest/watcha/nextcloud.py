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

from typing import Iterable, Pattern, Tuple

from synapse.http.servlet import RestServlet
from synapse.http.site import SynapseRequest
from synapse.types import JsonDict, UserID

from ._base import watcha_patterns


def nextcloud_patterns(path_regex: str) -> Iterable[Pattern]:
    """Returns the list of patterns for a nextcloud endpoint

    Args:
        path_regex: The regex string to match. This should NOT have a ^
            as this will be prefixed.

    Returns:
        A list of regex patterns.
    """
    nextcloud_prefix = "/nextcloud"
    patterns = watcha_patterns(nextcloud_prefix + path_regex)
    return patterns


class ListUsersOwnCalendarsRestServlet(RestServlet):
    """List all calendars owned by the current user"""

    PATTERNS = nextcloud_patterns("/calendars$")

    def __init__(self, hs: "HomeServer"):
        self.auth = hs.get_auth()
        self.nextcloud_handler = hs.get_nextcloud_handler()

    async def on_GET(self, request: SynapseRequest) -> Tuple[int, JsonDict]:
        requester = await self.auth.get_user_by_req(request, allow_partner=False)
        user_id = requester.user.to_string()
        response = await self.nextcloud_handler.list_users_own_calendars(user_id)
        return 200, response


class GetCalendarRestServlet(RestServlet):
    """Get properties for a specific calendar from the perspective of the current user"""

    PATTERNS = nextcloud_patterns("/calendars/(?P<calendar_id>\d+)$")

    def __init__(self, hs: "HomeServer"):
        self.auth = hs.get_auth()
        self.nextcloud_handler = hs.get_nextcloud_handler()

    async def on_GET(
        self, request: SynapseRequest, calendar_id: str
    ) -> Tuple[int, JsonDict]:
        requester = await self.auth.get_user_by_req(request, allow_partner=False)
        user_id = requester.user.to_string()
        response = await self.nextcloud_handler.get_calendar(user_id, calendar_id)
        return 200, response


class ReorderCalendarsRestServlet(RestServlet):
    """Move up a calendar at the top of the list for the current user"""

    PATTERNS = nextcloud_patterns("/calendars/(?P<calendar_id>[^/]+)/top$")

    def __init__(self, hs: "HomeServer"):
        self.auth = hs.get_auth()
        self.nextcloud_handler = hs.get_nextcloud_handler()

    async def on_PUT(
        self, request: SynapseRequest, calendar_id: str
    ) -> Tuple[int, JsonDict]:
        requester = await self.auth.get_user_by_req(request)
        user_id = requester.user.to_string()
        response = await self.nextcloud_handler.reorder_calendars(user_id, calendar_id)
        return 200, {}
