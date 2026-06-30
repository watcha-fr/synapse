#
# This file is licensed under the Affero General Public License (AGPL) version 3.
#
# Copyright 2022 The Matrix.org Foundation C.I.C
# Copyright (C) 2023 New Vector, Ltd
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as
# published by the Free Software Foundation, either version 3 of the
# License, or (at your option) any later version.
#
# See the GNU Affero General Public License for more details:
# <https://www.gnu.org/licenses/agpl-3.0.html>.
#
# Originally licensed under the Apache License, Version 2.0:
# <http://www.apache.org/licenses/LICENSE-2.0>.
#
# [This file includes modifications made by New Vector Limited]
#
#
from typing import TYPE_CHECKING

import attr
import logging  # watcha+
import time  # watcha+

from synapse.metrics import SERVER_NAME_LABEL
from synapse.util import metrics  # watcha+
from synapse.util.duration import Duration

if TYPE_CHECKING:
    from synapse.server import HomeServer

from prometheus_client import Gauge

logger = logging.getLogger(__name__)  # watcha+

# Gauge to expose daily active users metrics
current_dau_gauge = Gauge(
    "synapse_admin_daily_active_users",
    "Current daily active users count",
    labelnames=[SERVER_NAME_LABEL],
)

# watcha+
total_users_gauge = Gauge(
    "synapse_total_users", "Nombre total d'utilisateurs", labelnames=[SERVER_NAME_LABEL]
)
partner_users_gauge = Gauge(
    "synapse_partner_users", "Nombre d'utilisateurs externe", labelnames=[SERVER_NAME_LABEL]
)
rooms_public_gauge = Gauge(
    "synapse_rooms_public", "Nombre de salons publics", labelnames=[SERVER_NAME_LABEL]
)
rooms_private_gauge = Gauge(
    "synapse_rooms_private", "Nombre de salons privés", labelnames=[SERVER_NAME_LABEL]
)
rooms_dm_gauge = Gauge(
    "synapse_rooms_dm", "Nombre de salons messages privés", labelnames=[SERVER_NAME_LABEL]
)
spaces_public_gauge = Gauge(
    "synapse_spaces_public", "Nombre d'espace publics", labelnames=[SERVER_NAME_LABEL]
)
spaces_private_gauge = Gauge(
    "synapse_spaces_private", "Nombre d'espace privés", labelnames=[SERVER_NAME_LABEL]
)
jitsi_calls_gauge = Gauge(
    "synapse_jitsi_calls", "Nombre d'appels Jitsi", labelnames=[SERVER_NAME_LABEL]
)
ios_users_gauge = Gauge(
    "synapse_ios_users", "Nombre d'utilisateurs iOS", labelnames=[SERVER_NAME_LABEL]
)
android_users_gauge = Gauge(
    "synapse_android_users", "Nombre d'utilisateurs Android", labelnames=[SERVER_NAME_LABEL]
)
web_users_gauge = Gauge(
    "synapse_web_users", "Nombre d'utilisateurs Web", labelnames=[SERVER_NAME_LABEL]
)
sygnal_up_gauge = Gauge(
    "synapse_sygnal_up",
    "Sygnal ping status (1 if recent ping, 0 if not)",
    labelnames=[SERVER_NAME_LABEL],
)
# +watcha


@attr.s(auto_attribs=True)
class CommonUsageMetrics:
    """Usage metrics shared between the phone home stats and the prometheus exporter."""

    daily_active_users: int
    # watcha+
    total_users: int
    partner_users: int
    rooms_public: int
    rooms_private: int
    rooms_dm: int
    spaces_public: int
    spaces_private: int
    jitsi_calls: int
    ios_users: int
    android_users: int
    web_users: int
    up_sygnal: int
    # +watcha


class CommonUsageMetricsManager:
    """Collects common usage metrics."""

    def __init__(self, hs: "HomeServer") -> None:
        self.server_name = hs.hostname
        self._store = hs.get_datastores().main
        self._clock = hs.get_clock()
        self._hs = hs

    async def get_metrics(self) -> CommonUsageMetrics:
        """Get the CommonUsageMetrics object. If no collection has happened yet, do it
        before returning the metrics.

        Returns:
            The CommonUsageMetrics object to read common metrics from.
        """
        return await self._collect()

    def setup(self) -> None:
        """Keep the gauges for common usage metrics up to date."""
        self._hs.run_as_background_process(
            desc="common_usage_metrics_update_gauges",
            func=self._update_gauges,
        )
        self._clock.looping_call(
            self._hs.run_as_background_process,
            Duration(minutes=5),
            desc="common_usage_metrics_update_gauges",
            func=self._update_gauges,
        )

    async def _collect(self) -> CommonUsageMetrics:
        """Collect the common metrics and either create the CommonUsageMetrics object to
        use if it doesn't exist yet, or update it.
        """
        dau_count = await self._store.count_daily_users()
        # watcha+
        total_users = await self._store.count_all_users()
        partner_users = await self._store.count_partner_users()

        rooms = await self._store.get_room_count()
        public_rooms = await self._store.count_public_rooms(None, False, None)
        private_rooms = rooms - public_rooms
        dm_rooms = await self._store._get_dm_rooms()
        public_spaces = await self._store.count_space_public()
        private_spaces = await self._store.count_space_private()
        r30v2_results = await self._store.count_r30v2_users()
        user_ios = r30v2_results.get("ios", 0)
        user_android = r30v2_results.get("android", 0)
        user_web = r30v2_results.get("web", 0)
        calls_jitsi = await self._store.count_jitsi_calls()
        sygnal_up = 1 if time.time() - metrics.last_sygnal_ping_time <= 600 else 0
        # +watcha

        return CommonUsageMetrics(
            daily_active_users=dau_count,
            # watcha+
            total_users=total_users,
            partner_users=partner_users,
            rooms_public=public_rooms,
            rooms_private=private_rooms,
            rooms_dm=len(dm_rooms),
            spaces_public=public_spaces,
            spaces_private=private_spaces,
            jitsi_calls=calls_jitsi,
            ios_users=user_ios,
            android_users=user_android,
            web_users=user_web,
            up_sygnal=sygnal_up,
            # +watcha
        )

    async def _update_gauges(self) -> None:
        """Update the Prometheus gauges."""
        metrics = await self._collect()

        current_dau_gauge.labels(
            **{SERVER_NAME_LABEL: self.server_name},
        ).set(float(metrics.daily_active_users))
        # watcha+
        labels = {SERVER_NAME_LABEL: self.server_name}
        total_users_gauge.labels(**labels).set(float(metrics.total_users))
        partner_users_gauge.labels(**labels).set(float(metrics.partner_users))
        rooms_public_gauge.labels(**labels).set(float(metrics.rooms_public))
        rooms_private_gauge.labels(**labels).set(float(metrics.rooms_private))
        rooms_dm_gauge.labels(**labels).set(float(metrics.rooms_dm))
        spaces_public_gauge.labels(**labels).set(float(metrics.spaces_public))
        spaces_private_gauge.labels(**labels).set(float(metrics.spaces_private))
        jitsi_calls_gauge.labels(**labels).set(float(metrics.jitsi_calls))
        ios_users_gauge.labels(**labels).set(float(metrics.ios_users))
        android_users_gauge.labels(**labels).set(float(metrics.android_users))
        web_users_gauge.labels(**labels).set(float(metrics.web_users))
        sygnal_up_gauge.labels(**labels).set(float(metrics.up_sygnal))
        # +watcha
