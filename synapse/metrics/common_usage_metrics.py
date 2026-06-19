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
import logging
from synapse.metrics.background_process_metrics import run_as_background_process

if TYPE_CHECKING:
    from synapse.server import HomeServer

from prometheus_client import Gauge

from synapse.util import metrics
import time

logger = logging.getLogger(__name__)
# Gauge to expose daily active users metrics
current_dau_gauge = Gauge(
    "synapse_admin_daily_active_users",
    "Current daily active users count",
)

# watcha+
# Nombre d'utilisateurs actifs sur les 5 dernières minutes
active_users_5m_gauge = Gauge(
    "synapse_active_users_5m",
    "Nombre d'utilisateurs actifs sur les 5 dernières minutes"
)

# Nombre total d'utilisateurs
total_users_gauge = Gauge(
    "synapse_total_users",
    "Nombre total d'utilisateurs"
)

# Nombre d'utilisateurs externe
partner_users_gauge = Gauge(
    "synapse_partner_users",
    "Nombre d'utilisateurs externe"
)

# Nombre de salons publics
rooms_public_gauge = Gauge(
    "synapse_rooms_public",
    "Nombre de salons publics"
)

# Nombre de salons privés
rooms_private_gauge = Gauge(
    "synapse_rooms_private",
    "Nombre de salons privés"
)

# Nombre de salons messages privés
rooms_dm_gauge = Gauge(
    "synapse_rooms_dm",
    "Nombre de salons messages privés"
)

# Nombre d'espcaces publics
spaces_public_gauge = Gauge(
    "synapse_spaces_public",
    "Nombre d'espace publics"
)

# Nombre d'espcaces privés
spaces_private_gauge = Gauge(
    "synapse_spaces_private",
    "Nombre d'espace privés"
)

# Nombre d'appels Jitsi
jitsi_calls_gauge = Gauge(
    "synapse_jitsi_calls",
    "Nombre d'appels Jitsi"
)

# Nombre d'utilisateurs iOS
ios_users_gauge = Gauge(
    "synapse_ios_users",
    "Nombre d'utilisateurs iOS"
)

# Nombre d'utilisateurs Android
android_users_gauge = Gauge(
    "synapse_android_users",
    "Nombre d'utilisateurs Android"
)

# Nombre d'utilisateurs Web
web_users_gauge = Gauge(
    "synapse_web_users",
    "Nombre d'utilisateurs Web"
)

# Etat de sygnal
sygnal_up_gauge = Gauge(
    "synapse_sygnal_up",
    "Sygnal ping status (1 if recent ping, 0 if not)"
)

# Indicateurs "par ville" (filtre dashboard SITIV). Exposés uniquement si la
# config `watcha.cities_by_domain` est renseignée (instance sitiv).
total_users_by_city_gauge = Gauge(
    "synapse_total_users_by_city",
    "Nombre total d'utilisateurs par ville",
    ["ville"],
)
active_users_5m_by_city_gauge = Gauge(
    "synapse_active_users_5m_by_city",
    "Nombre d'utilisateurs actifs sur 5 min par ville",
    ["ville"],
)
rooms_by_city_gauge = Gauge(
    "synapse_rooms_by_city",
    "Nombre de salons par ville",
    ["ville"],
)
spaces_by_city_gauge = Gauge(
    "synapse_spaces_by_city",
    "Nombre d'espaces par ville",
    ["ville"],
)
# +watcha

@attr.s(auto_attribs=True)
class CommonUsageMetrics:
    """Usage metrics shared between the phone home stats and the prometheus exporter."""

    daily_active_users: int
    # watcha+
    active_users_5m: int
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
        self._store = hs.get_datastores().main
        self._clock = hs.get_clock()
        # watcha+
        # Mapping domaine -> ville (vide hors sitiv => métriques by_city désactivées).
        self._domain_to_city = hs.config.watcha.domain_to_city
        self._cities = list(hs.config.watcha.cities_by_domain.keys())
        # +watcha

    async def get_metrics(self) -> CommonUsageMetrics:
        """Get the CommonUsageMetrics object. If no collection has happened yet, do it
        before returning the metrics.

        Returns:
            The CommonUsageMetrics object to read common metrics from.
        """
        return await self._collect()

    async def setup(self) -> None:
        """Keep the gauges for common usage metrics up to date."""
        run_as_background_process(
            desc="common_usage_metrics_update_gauges", func=self._update_gauges
        )
        self._clock.looping_call(
            run_as_background_process,
            5 * 60 * 1000,
            desc="common_usage_metrics_update_gauges",
            func=self._update_gauges,
        )

    async def _collect(self) -> CommonUsageMetrics:
        """Collect the common metrics and either create the CommonUsageMetrics object to
        use if it doesn't exist yet, or update it.
        """
        dau_count = await self._store.count_daily_users()
        # watcha+
        active_users_5m = await self._store.count_users_active_last_5min()
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
            active_users_5m=active_users_5m,
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

        current_dau_gauge.set(float(metrics.daily_active_users))
        # watcha+
        active_users_5m_gauge.set(float(metrics.active_users_5m))
        total_users_gauge.set(float(metrics.total_users))
        partner_users_gauge.set(float(metrics.partner_users))
        rooms_public_gauge.set(float(metrics.rooms_public))
        rooms_private_gauge.set(float(metrics.rooms_private))
        rooms_dm_gauge.set(float(metrics.rooms_dm))
        spaces_public_gauge.set(float(metrics.spaces_public))
        spaces_private_gauge.set(float(metrics.spaces_private))
        jitsi_calls_gauge.set(float(metrics.jitsi_calls))
        ios_users_gauge.set(float(metrics.ios_users))
        android_users_gauge.set(float(metrics.android_users))
        web_users_gauge.set(float(metrics.web_users))
        sygnal_up_gauge.set(float(metrics.up_sygnal))

        await self._update_city_gauges()
        # +watcha

    # watcha+
    async def _update_city_gauges(self) -> None:
        """Met à jour les gauges `*_by_city`. No-op si aucun mapping ville
        n'est configuré (cas mdl/vdl)."""
        if not self._domain_to_city:
            return

        from synapse.storage.databases.main.metrics import CITY_OTHER, CITY_INTER

        users = await self._store.count_users_by_city(self._domain_to_city)
        active = await self._store.count_active_users_5m_by_city(self._domain_to_city)
        rooms, spaces = await self._store.count_rooms_and_spaces_by_city(
            self._domain_to_city
        )

        # On (ré)expose toutes les villes connues à 0 avant de poser les valeurs,
        # pour éviter les libellés fantômes quand un compte retombe à 0.
        user_labels = self._cities + [CITY_OTHER]
        room_labels = self._cities + [CITY_OTHER, CITY_INTER]

        def _apply(gauge, counts, labels):
            gauge.clear()
            for ville in labels:
                gauge.labels(ville=ville).set(float(counts.get(ville, 0)))

        _apply(total_users_by_city_gauge, users, user_labels)
        _apply(active_users_5m_by_city_gauge, active, user_labels)
        _apply(rooms_by_city_gauge, rooms, room_labels)
        _apply(spaces_by_city_gauge, spaces, room_labels)
    # +watcha