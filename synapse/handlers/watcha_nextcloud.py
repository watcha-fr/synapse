import logging
from typing import Iterable, List, Optional, Set
from urllib import parse as urlparse

from jsonschema.exceptions import SchemaError, ValidationError
from prometheus_client import Counter

from synapse.api.constants import EventTypes, Membership
from synapse.api.errors import (
    Codes,
    HttpResponseException,
    NextcloudError,
    SynapseError,
)
from synapse.events import EventBase
from synapse.push.presentable_names import calculate_room_name
from synapse.types import Requester
from synapse.util.duration import Duration
from synapse.util.watcha import ActionStatus, build_log_message

logger = logging.getLogger(__name__)

# echo -n watcha | md5sum | head -c 10
NEXTCLOUD_GROUP_ID_PREFIX = "c4d96a06b7_"
# Nextcloud does not allow group id longer than 64 characters
NEXTCLOUD_GROUP_ID_LENGHT_LIMIT = 64
NEXTCLOUD_CLIENT_ERRORS = (
    NextcloudError,
    SchemaError,
    ValidationError,
    HttpResponseException,
)

NEXTCLOUD_RETRY_ATTEMPTS = 3
NEXTCLOUD_RETRY_BASE_DELAY_SECONDS = 0.5

# OCS status codes worth acting on rather than merely logging.
NEXTCLOUD_ERROR_GROUP_NOT_FOUND = 102
NEXTCLOUD_ERROR_USER_NOT_FOUND = 103

# A member left without access to their room's documents is invisible in the
# logs of a busy server, which is how dozens of accounts stayed broken for
# months. Counted so it can be alerted on.
nextcloud_sync_failures = Counter(
    "synapse_watcha_nextcloud_sync_failures",
    "Nextcloud synchronisation failures leaving a member without document access",
    ["reason"],
)

# Nextcloud OCS status codes that describe a stable state rather than
# contention: retrying them would fail identically every time.
NEXTCLOUD_PERMANENT_ERROR_CODES = frozenset(
    {
        101,  # invalid input data / no group specified
        102,  # group does not exist (or already exists, on creation)
        103,  # user does not exist
        104,  # insufficient privileges
        404,  # file or folder not found
    }
)


def _is_transient(error: Exception) -> bool:
    """Whether a failed Nextcloud call is worth retrying.

    A locked database, a timeout or a 5xx are transient. A malformed request or
    a missing user is not.
    """
    if isinstance(error, NextcloudError):
        return error.code not in NEXTCLOUD_PERMANENT_ERROR_CODES

    if isinstance(error, HttpResponseException):
        # Retry server-side failures only; a 4xx will not fix itself.
        return error.code >= 500

    # A schema violation means Nextcloud answered something unexpected, which a
    # retry can legitimately resolve (e.g. a truncated response under load).
    return True


class NextcloudHandler:
    def __init__(self, hs: "Homeserver"):
        self.config = hs.config
        self.auth = hs.get_auth()
        self.auth_handler = hs.get_auth_handler()
        self.clock = hs.get_clock()
        self.store = hs.get_datastores().main
        self.administration_handler = hs.get_watcha_administration_handler()
        self.event_creation_handler = hs.get_event_creation_handler()
        self._storage_controllers = hs.get_storage_controllers()
        self.keycloak_client = hs.get_keycloak_client()
        self.nextcloud_client = hs.get_nextcloud_client()

    async def handle_room_member_event(
        self, requester: Requester, room_id: str, user_id: str, membership: str
    ):
        """ watcha!
        if (
            await self.administration_handler.get_user_role(user_id) == "partner"
            and not self.config.watcha.external_authentication_for_partners
        ):
        !watcha """
        # watcha+
        # The role that matters is the *target's*, not the requester's: the point
        # of this guard is that a partner has no Nextcloud account to add to the
        # room group. Testing the requester instead meant that a member who
        # accepted their own invitation was their own requester, so a partner
        # joining was skipped entirely — and, symmetrically, that a collaborator
        # invited by a partner was skipped too. Both left the member out of the
        # Nextcloud group, with no document space and nothing in the logs.
        if (
            await self.auth_handler.is_partner(user_id)
            and not self.config.watcha.external_authentication_for_partners
        ):
        # +watcha
            return

        if await self.store.get_share_id(room_id):
            await self.update_group(user_id, room_id, membership)

        events = await self._get_calendar_events(room_id)
        if events:
            await self.update_calendar_access(
                requester, room_id, user_id, membership, events
            )

    async def handle_room_name_event(
        self, requester: Requester, event_dict: dict, txn_id: Optional[str] = None
    ):
        event, _ = await self.event_creation_handler.create_and_send_nonmember_event(
            requester, event_dict, txn_id=txn_id
        )

        room_id = event_dict["room_id"]
        displayname = await self.build_group_displayname(room_id)

        if await self.store.get_share_id(room_id):
            group_id = await self.build_group_id(room_id)
            await self.set_group_displayname(group_id, displayname)

        calendar_ids = await self._get_calendar_ids(room_id)
        if calendar_ids:
            await self.nextcloud_client.rename_calendars(
                calendar_ids, room_id, displayname
            )

        return event.event_id

    # file sharing
    # ============

    """watcha!
    async def update_share(self, room_id: str, user_id: str, event_content: dict):
        await self.auth.check_user_in_room(room_id, user_id)
    !watcha"""
    # watcha+
    async def update_share(self, room_id: str, requester: Requester, event_content: dict):
        await self.auth.check_user_in_room(room_id, requester)
    # +watcha

        nextcloud_url = event_content["nextcloudShare"]

        if nextcloud_url:
            url_query = urlparse.parse_qs(urlparse.urlparse(nextcloud_url).query)
            if "dir" not in url_query:
                raise SynapseError(
                    400,
                    build_log_message(
                        action="get `nextcloud_folder_path` from `im.vector.web.settings` event",
                        log_vars={"nextcloud_url": nextcloud_url},
                    ),
                )
            nextcloud_folder_path = url_query["dir"][0]
            """watcha!
            await self.bind(user_id, room_id, nextcloud_folder_path)
            !watcha"""
            await self.bind(requester.user.to_string(), room_id, nextcloud_folder_path) # watcha+

        else:
            """watcha!
            await self.unbind(user_id, room_id)
            !watcha"""
            await self.unbind(requester.user.to_string(), room_id) # watcha+

    async def bind(self, requester_id: str, room_id: str, path: str):
        """Bind a Nextcloud folder with a room in three steps :
            1 - create a new Nextcloud group
            2 - add all room members in the new group
            3 - create a share on folder for the new group

        Args :
           requester_id: the mxid of the requester.
           room_id: the id of the room to bind.
           path: the path of the Nextcloud folder to bind.
        """
        await self.create_group(room_id)
        await self.add_room_members_to_group(room_id)
        await self.create_share(requester_id, room_id, path)

    async def create_group(self, room_id: str):
        """Create a Nextcloud group with specific id and displayname.

        Args:
            room_id: the id of the room
        """
        group_id = await self.build_group_id(room_id)
        group_displayname = await self.build_group_displayname(room_id)

        try:
            await self.nextcloud_client.add_group(group_id)
        except NEXTCLOUD_CLIENT_ERRORS as error:
            # Do not raise error if Nextcloud group already exist
            log_message = build_log_message(
                log_vars={"group_id": group_id, "error": error}
            )
            if isinstance(error, NextcloudError) and error.code == 102:
                logger.warn(log_message)
            else:
                raise SynapseError(
                    500,
                    log_message,
                    Codes.NEXTCLOUD_CAN_NOT_CREATE_GROUP,
                )

        await self.set_group_displayname(group_id, group_displayname)

    async def build_group_id(self, room_id: str):
        """Build the Nextcloud group id corresponding to an association of a pattern and room id

        Args:
            room_id: the id of the room
        """
        group_id = NEXTCLOUD_GROUP_ID_PREFIX + room_id
        return group_id[:NEXTCLOUD_GROUP_ID_LENGHT_LIMIT]

    async def build_group_displayname(self, room_id):
        """Build the Nextcloud group name corresponding to an association of a pattern and room name

        Args:
            room_id: the id of the room
        """
        room_state_ids = await self._storage_controllers.state.get_current_state_ids(room_id)
        room_name = await calculate_room_name(self.store, room_state_ids, None)
        return f"[Watcha] {room_name}"

    async def set_group_displayname(self, group_id: str, group_displayname: str):
        """Set the displayname of a Nextcloud group

        Args:
            group_id: the id of group
            group_displayname: the displayname of the group
        """
        try:
            await self.nextcloud_client.set_group_displayname(
                group_id, group_displayname
            )
        except NEXTCLOUD_CLIENT_ERRORS as error:
            logger.warn(
                build_log_message(
                    log_vars={
                        "group_id": group_id,
                        "group_displayname": group_displayname,
                        "error": error,
                    }
                )
            )

    async def add_room_members_to_group(self, room_id: str):
        """Add all members of a room to a Nextcloud group.

        Args:
            room_id: the id of the room which the Nextcloud group name is infered from.
        """
        group_id = await self.build_group_id(room_id)
        user_ids = await self.store.get_users_in_room(room_id)

        for user_id in user_ids:
            nextcloud_username = await self.store.get_username(user_id)
            try:
                await self.nextcloud_client.add_user_to_group(
                    nextcloud_username, group_id
                )
            except NEXTCLOUD_CLIENT_ERRORS as error:
                log_message = build_log_message(
                    log_vars={
                        "user_id": user_id,
                        "nextcloud_username": nextcloud_username,
                        "group_id": group_id,
                        "room_id": room_id,
                        "error": error,
                    }
                )
                # Do not raise error if some users can not be added to group
                if isinstance(error, NextcloudError) and (error.code in (103, 105)):
                    logger.error(log_message)
                else:
                    raise SynapseError(
                        500,
                        log_message,
                        Codes.NEXTCLOUD_CAN_NOT_ADD_MEMBERS_TO_GROUP,
                    )

    async def create_share(self, requester_id: str, room_id: str, path: str):
        """Create a new share on folder for a specific Nextcloud group.
        Before that, delete old existing share for this group if it exist.

        Args:
            requester_id: the mxid of the requester.
            room_id: the id of the room to bind.
            path: the path of the Nextcloud folder to bind.
        """
        group_id = await self.build_group_id(room_id)
        nextcloud_username = await self.store.get_username(requester_id)

        old_share_id = await self.store.get_share_id(room_id)
        if old_share_id:
            try:
                await self.nextcloud_client.unshare(nextcloud_username, old_share_id)
            except NEXTCLOUD_CLIENT_ERRORS as error:
                logger.error(
                    build_log_message(
                        log_vars={
                            "nextcloud_username": nextcloud_username,
                            "old_share_id": old_share_id,
                            "error": error,
                        }
                    )
                )

        try:
            new_share_id = await self.nextcloud_client.share(
                nextcloud_username, path, group_id
            )
        except NEXTCLOUD_CLIENT_ERRORS as error:
            await self.unbind(requester_id, room_id)
            # raise 404 error if folder to share do not exist
            http_code = (
                error.code
                if isinstance(error, NextcloudError) and error.code == 404
                else 500
            )
            raise SynapseError(
                http_code,
                build_log_message(
                    log_vars={
                        "nextcloud_username": nextcloud_username,
                        "path": path,
                        "group_id": group_id,
                        "error": error,
                    }
                ),
                Codes.NEXTCLOUD_CAN_NOT_SHARE,
            )

        await self.store.register_share(room_id, new_share_id)

    async def transfer_share_on_room_upgrade(
        self, requester: Requester, old_room_id: str, new_room_id: str
    ):
        """Carry a room's Nextcloud folder binding over to its upgraded room.

        The binding is keyed on the room id, both in `watcha_nextcloud_shares`
        and in the group name, so an upgrade would otherwise orphan the document
        space: the old room is tombstoned and the new one has no share at all.

        Best effort by design — an upgrade must not fail because Nextcloud is
        unavailable — but never silent: the failure is logged with both room ids
        so the binding can be recreated from the room settings.
        """
        if not await self.store.get_share_id(old_room_id):
            return

        folder_path = await self._get_bound_folder_path(old_room_id)
        if folder_path is None:
            logger.warning(
                build_log_message(
                    log_vars={
                        "old_room_id": old_room_id,
                        "new_room_id": new_room_id,
                        "reason": "no Nextcloud folder path found in the old room state",
                    }
                )
            )
            return

        try:
            await self.bind(requester.user.to_string(), new_room_id, folder_path)
        except Exception as error:
            logger.error(
                build_log_message(
                    log_vars={
                        "old_room_id": old_room_id,
                        "new_room_id": new_room_id,
                        "folder_path": folder_path,
                        "error": error,
                    }
                )
            )
            return

        logger.info(
            build_log_message(
                status=ActionStatus.SUCCESS,
                log_vars={
                    "old_room_id": old_room_id,
                    "new_room_id": new_room_id,
                    "folder_path": folder_path,
                },
            )
        )

    async def _get_bound_folder_path(self, room_id: str) -> Optional[str]:
        """The Nextcloud folder path a room is bound to, from its room state."""
        event = await self._storage_controllers.state.get_current_state_event(
            room_id, EventTypes.VectorSetting, ""
        )
        if event is None:
            return None

        nextcloud_url = event.content.get("nextcloudShare")
        if not nextcloud_url:
            return None

        url_query = urlparse.parse_qs(urlparse.urlparse(nextcloud_url).query)
        if "dir" not in url_query:
            return None

        return url_query["dir"][0]

    async def unbind(self, requester_id: str, room_id: str):
        """Unbind a Nextcloud folder from a room.

        Args :
            requester_id: the mxid of the requester.
            room_id: the id of the room to bind
        """
        nextcloud_username = await self.store.get_username(requester_id)
        share_id = await self.store.get_share_id(room_id)
        if share_id:
            try:
                await self.nextcloud_client.unshare(nextcloud_username, share_id)
            except NEXTCLOUD_CLIENT_ERRORS as error:
                logger.error(
                    build_log_message(
                        log_vars={
                            "nextcloud_username": nextcloud_username,
                            "share_id": share_id,
                            "error": error,
                        }
                    )
                )

        group_id = await self.build_group_id(room_id)
        try:
            await self.nextcloud_client.delete_group(group_id)
        except NEXTCLOUD_CLIENT_ERRORS as error:
            logger.error(
                build_log_message(log_vars={"group_id": group_id, "error": error})
            )

        await self.store.delete_share(room_id)

    async def update_group(self, user_id: str, room_id: str, membership: str):
        """Update a Nextcloud group by adding or removing users.

        Repairs the two states that used to make a member lose access to the
        room's documents for good, silently:

        - the member has a `nextcloud_username` mapping but no Nextcloud account
          under that name (OCS 103). This is what happens to every account whose
          Nextcloud user was created under a *different* identifier than the one
          recorded in the mapping;
        - the room has a share but its Nextcloud group is gone (OCS 102).

        Both are retried once after provisioning, respectively, the account and
        the group. A failure that survives that is logged at `error` level with
        every identifier needed to act on it, and counted in a metric — the point
        being that such a failure can no longer stay invisible for months.

        Args:
            user_id: The mxid whose membership has been updated
            room_id: The id of the room where the membership event was sent
            membership: The type of membership event
        """
        group_id = await self.build_group_id(room_id)
        nextcloud_username = await self.store.get_username(user_id)

        log_vars = {
            "user_id": user_id,
            "room_id": room_id,
            "membership": membership,
            "nextcloud_username": nextcloud_username,
            "group_id": group_id,
        }

        # Guard: never issue a request whose path contains "None" or an empty
        # identifier. That produced literal `POST /cloud/users/None/groups` calls
        # on every first SSO login, because the membership was processed before
        # the mapping had been persisted.
        if not nextcloud_username:
            nextcloud_sync_failures.labels(reason="no_mapping").inc()
            logger.error(
                build_log_message(
                    log_vars={
                        **log_vars,
                        "reason": "no nextcloud_username recorded for this user; "
                        "cannot be inferred, use the reconciliation command",
                    }
                )
            )
            return

        if membership == Membership.JOIN:
            await self._add_user_to_group(user_id, nextcloud_username, group_id, log_vars)
            return

        try:
            await self._with_retry(
                lambda: self.nextcloud_client.remove_user_from_group(
                    nextcloud_username, group_id
                ),
                log_vars,
            )
        except NEXTCLOUD_CLIENT_ERRORS as error:
            # Losing this is benign: the member keeps a group membership they no
            # longer should have, which the reconciliation command settles.
            logger.warning(build_log_message(log_vars={**log_vars, "error": error}))

    async def _add_user_to_group(
        self, user_id: str, nextcloud_username: str, group_id: str, log_vars: dict
    ):
        """Add a member to a room group, repairing the two recoverable causes.

        Idempotent: Nextcloud accepts adding a user who is already a member.
        """
        try:
            await self._with_retry(
                lambda: self.nextcloud_client.add_user_to_group(
                    nextcloud_username, group_id
                ),
                log_vars,
            )
            return
        except NEXTCLOUD_CLIENT_ERRORS as error:
            code = getattr(error, "code", None)
            if code == NEXTCLOUD_ERROR_USER_NOT_FOUND:
                repaired = await self._repair_missing_account(user_id, nextcloud_username)
                reason = "nextcloud_account_missing"
            elif code == NEXTCLOUD_ERROR_GROUP_NOT_FOUND:
                repaired = await self._repair_missing_group(log_vars["room_id"])
                reason = "nextcloud_group_missing"
            else:
                nextcloud_sync_failures.labels(reason="add_to_group_failed").inc()
                logger.error(build_log_message(log_vars={**log_vars, "error": error}))
                return

        if not repaired:
            nextcloud_sync_failures.labels(reason=reason).inc()
            logger.error(
                build_log_message(
                    log_vars={**log_vars, "reason": f"could not repair: {reason}"}
                )
            )
            return

        try:
            await self._with_retry(
                lambda: self.nextcloud_client.add_user_to_group(
                    nextcloud_username, group_id
                ),
                log_vars,
            )
        except NEXTCLOUD_CLIENT_ERRORS as error:
            nextcloud_sync_failures.labels(reason=reason).inc()
            logger.error(
                build_log_message(
                    log_vars={
                        **log_vars,
                        "reason": f"still failing after repairing {reason}",
                        "error": error,
                    }
                )
            )
            return

        logger.info(
            build_log_message(
                action=f"repair {reason} and add user to group",
                status=ActionStatus.SUCCESS,
                log_vars=log_vars,
            )
        )

    async def _repair_missing_account(self, user_id: str, nextcloud_username: str) -> bool:
        """Create the Nextcloud account a mapping points at but which is absent."""
        is_partner = await self.auth_handler.is_partner(user_id)
        return await self.provision_account(
            nextcloud_username=nextcloud_username,
            is_partner=is_partner,
        )

    async def _repair_missing_group(self, room_id: str) -> bool:
        """Recreate the Nextcloud group of a room that still holds a share."""
        try:
            await self.create_group(room_id)
            return True
        except Exception as error:
            logger.error(
                build_log_message(log_vars={"room_id": room_id, "error": error})
            )
            return False

    async def provision_account(
        self,
        nextcloud_username: str,
        displayname: Optional[str] = None,
        email: Optional[str] = None,
        is_admin: bool = False,
        is_partner: bool = False,
        groups: Optional[list] = None,
    ) -> bool:
        """Create the Nextcloud account of a Watcha user, if the deployment wants one.

        Single implementation for every path a user can arrive through — the
        Watcha invitation flow and SSO alike. Both used to provision separately,
        and SSO created the account under the Matrix localpart while recording
        `nextcloud_username` in the mapping: whenever those two differ, every
        later group operation fails with OCS 103 and the member never sees a
        document space.

        `nextcloud_username` must therefore be the *same* identifier that is
        recorded in `user_external_ids.nextcloud_username`.

        Idempotent: an account that already exists is a success (the client maps
        OCS 102 "username already exists" to a warning, not an error).

        Returns:
            True when the deployment provisions accounts and this one now exists.
        """
        if not self.should_provision_account(is_partner):
            return False

        if not nextcloud_username:
            logger.error(
                build_log_message(
                    log_vars={"reason": "refusing to provision an empty username"}
                )
            )
            return False

        try:
            await self._with_retry(
                lambda: self.nextcloud_client.add_user(
                    nextcloud_username, displayname, email, is_admin, groups
                ),
                {"nextcloud_username": nextcloud_username},
            )
        except Exception as error:
            # Deliberately broader than NEXTCLOUD_CLIENT_ERRORS: this runs on the
            # membership path, where an unexpected failure (a DNS error, an
            # unreachable host) must not make the join itself fail. The member is
            # in the room either way; the reconciliation command repairs the rest.
            logger.error(
                build_log_message(
                    log_vars={
                        "nextcloud_username": nextcloud_username,
                        "error": error,
                    }
                )
            )
            return False

        logger.info(
            build_log_message(
                status=ActionStatus.SUCCESS,
                log_vars={"nextcloud_username": nextcloud_username},
            )
        )
        return True

    def should_provision_account(self, is_partner: bool) -> bool:
        """Whether this deployment gives this kind of user a Nextcloud account."""
        return bool(
            self.config.watcha.managed_idp
            and self.config.watcha.nextcloud_integration
            and (
                not is_partner
                or self.config.watcha.external_authentication_for_partners
            )
        )

    async def get_room_folder(self, room_id: str, user_id: str):
        """Resolve a room's document folder for a member, by stable identifier.

        Returns the Nextcloud file id and the path as currently mounted for that
        member, so the client never has to guess a folder name — a mount can be
        renamed by each recipient, and Nextcloud appends a suffix on collision.

        Unlike the write paths, failure is raised rather than swallowed: the
        caller is a user waiting in front of the document panel, and it needs to
        tell "not accepted yet" apart from "folder deleted" to say anything
        useful.
        """
        nextcloud_username = await self.store.get_username(user_id)
        if not nextcloud_username:
            raise SynapseError(
                404,
                build_log_message(
                    log_vars={
                        "user_id": user_id,
                        "room_id": room_id,
                        "reason": "no Nextcloud account registered for this user",
                    }
                ),
                Codes.NOT_FOUND,
            )

        log_vars = {
            "user_id": user_id,
            "room_id": room_id,
            "nextcloud_username": nextcloud_username,
        }

        try:
            return await self._with_retry(
                lambda: self.nextcloud_client.get_room_folder(
                    room_id, nextcloud_username
                ),
                log_vars,
            )
        except NEXTCLOUD_CLIENT_ERRORS as error:
            logger.error(build_log_message(log_vars={**log_vars, "error": error}))
            raise SynapseError(
                502,
                build_log_message(log_vars={**log_vars, "error": error}),
                Codes.UNKNOWN,
            )

    async def _with_retry(self, operation, log_vars: dict):
        """Run a Nextcloud call, retrying transient failures with backoff.

        Watcha deployments may still run on SQLite, where a single writer lock
        makes contention — not misuse — the usual cause of failure. Retrying
        turns an intermittent user-visible breakage into a slower success.

        Client errors that describe a stable state (a missing user, a missing
        group) are not retried: they would fail identically every time.
        """
        for attempt in range(1, NEXTCLOUD_RETRY_ATTEMPTS + 1):
            try:
                return await operation()
            except NEXTCLOUD_CLIENT_ERRORS as error:
                is_last_attempt = attempt == NEXTCLOUD_RETRY_ATTEMPTS
                if is_last_attempt or not _is_transient(error):
                    raise

                delay = NEXTCLOUD_RETRY_BASE_DELAY_SECONDS * (2 ** (attempt - 1))
                logger.warning(
                    build_log_message(
                        action="retry Nextcloud call",
                        log_vars={
                            **log_vars,
                            "attempt": attempt,
                            "retry_in_seconds": delay,
                            "error": error,
                        },
                    )
                )
                # Duration, not a float: `Clock.sleep` calls `duration.as_secs()`.
                await self.clock.sleep(Duration(seconds=delay))

    # calendar sharing
    # ================

    async def list_users_own_calendars(self, user_id: str):
        nextcloud_username = await self.store.get_username(user_id)
        calendars = await self.nextcloud_client.get_users_own_calendars(
            nextcloud_username
        )
        aggregated_calendars = {key: list() for key in CalendarComponentTypes.ALL}
        for calendar in calendars:
            components = calendar["components"]
            key = CalendarComponentTypes.serialize(components)
            aggregated_calendars[key].append(
                {
                    "id": calendar["id"],
                    "displayname": calendar["displayname"],
                }
            )
        return aggregated_calendars

    async def get_calendar(self, user_id: str, calendar_id: str):
        nextcloud_username = await self.store.get_username(user_id)
        return await self.nextcloud_client.get_calendar(nextcloud_username, calendar_id)

    async def reorder_calendars(self, user_id: str, calendar_id: str):
        nextcloud_username = await self.store.get_username(user_id)
        return await self.nextcloud_client.reorder_calendars(
            nextcloud_username, calendar_id
        )

    async def update_calendar_share(
        self, requester: Requester, event_dict: dict, txn_id: Optional[str] = None
    ):
        user_id = event_dict["sender"]
        room_id = event_dict["room_id"]
        content = event_dict["content"]

        await self.auth.check_user_in_room(room_id, requester)

        if not content:
            state_key = event_dict["state_key"]
            calendar_event = await self._storage_controllers.state.get_current_state_event(
                room_id, EventTypes.NextcloudCalendar, state_key
            )
            if calendar_event is None or not calendar_event["content"]:
                raise SynapseError(
                    400,
                    f"[Watcha] No such iCalendar component shared with this room",
                    Codes.BAD_STATE,
                )
            calendar_ids = [calendar_event.content["id"]]
            # FIXME: infer delete_group also from share_state
            delete_group = len(await self._get_calendar_events(room_id)) == 1
            await self.nextcloud_client.unshare_calendar(
                calendar_ids, room_id, delete_group
            )
            event_dict["content"] = {}

        elif content.get("id") is None:
            fake_calendar = {
                "components": [
                    CalendarComponentTypes.VEVENT,
                    CalendarComponentTypes.VTODO,
                ]
            }
            await self._validate_calendar(room_id, fake_calendar)
            displayname = await self.build_group_displayname(room_id)
            user_ids = await self.store.get_users_in_room(room_id)
            nextcloud_usernames = [
                await self.store.get_username(user_id) for user_id in user_ids
            ]
            calendar = await self.nextcloud_client.create_and_share_calendar(
                room_id, displayname, nextcloud_usernames
            )
            event_dict["content"] = self._make_calendar_event_content(calendar)
            event_dict["state_key"] = CalendarComponentTypes.VEVENT_VTODO

        else:
            nextcloud_username = await self.store.get_username(user_id)
            calendar_id = content["id"]
            calendar = await self.nextcloud_client.get_calendar(
                nextcloud_username, calendar_id
            )
            await self._validate_calendar(room_id, calendar)
            components = calendar["components"]
            event_dict["state_key"] = CalendarComponentTypes.serialize(components)
            displayname = await self.build_group_displayname(room_id)
            user_ids = await self.store.get_users_in_room(room_id)
            nextcloud_usernames = [
                await self.store.get_username(user_id) for user_id in user_ids
            ]
            calendar = await self.nextcloud_client.share_calendar(
                nextcloud_username,
                calendar_id,
                room_id,
                displayname,
                nextcloud_usernames,
            )
            event_dict["content"] = self._make_calendar_event_content(calendar)

        event, _ = await self.event_creation_handler.create_and_send_nonmember_event(
            requester, event_dict, txn_id=txn_id
        )
        return event.event_id

    async def update_calendar_access(
        self,
        requester: Requester,
        room_id: str,
        user_id: str,
        membership: str,
        calendar_events: List[EventBase],
    ):
        if membership == Membership.JOIN:
            nextcloud_username = await self.store.get_username(user_id)
            calendar_ids = [event["content"]["id"] for event in calendar_events]
            displayname = await self.build_group_displayname(room_id)
            await self.nextcloud_client.add_user_access_to_calendars(
                nextcloud_username, room_id, calendar_ids, displayname
            )
            return

        own_calendar_ids = []

        for event in calendar_events:
            if self._is_own_calendar(user_id, event):
                own_calendar_ids.append(event["content"]["id"])
                event_dict = {
                    "type": EventTypes.NextcloudCalendar,
                    "content": {},
                    "room_id": room_id,
                    "sender": user_id,
                    "state_key": event["state_key"],
                }
                await self.event_creation_handler.create_and_send_nonmember_event(
                    requester, event_dict
                )

        # FIXME: infer delete_group also from share_state
        delete_group = all(
            self._is_own_calendar(user_id, event) for event in calendar_events
        )

        if own_calendar_ids:
            await self.nextcloud_client.unshare_calendar(
                own_calendar_ids, room_id, delete_group
            )

        if not delete_group:
            nextcloud_username = await self.store.get_username(user_id)
            await self.nextcloud_client.remove_user_access_to_calendars(
                nextcloud_username, room_id
            )

    def _is_own_calendar(self, user_id: str, calendar_event: EventBase):
        return (
            calendar_event["sender"] == user_id
            and calendar_event["content"]["is_personal"] == True
        )

    async def _validate_calendar(self, room_id: str, calendar: dict):
        components = CalendarComponentTypes.from_calendar(calendar)
        state_keys = [
            event["state_key"] for event in await self._get_calendar_events(room_id)
        ]
        current_components = CalendarComponentTypes.deserialize_from_state_keys(
            state_keys
        )
        if not components.isdisjoint(current_components):
            raise SynapseError(
                400,
                f"[Watcha] Some of the iCalendar components are already shared with this room",
                Codes.BAD_STATE,
            )

    async def _get_calendar_events(self, room_id: str) -> List[EventBase]:
        calendar_events = []
        room_state = await self._storage_controllers.state.get_current_state(room_id)
        for state_key in CalendarComponentTypes.ALL:
            event = room_state.get((EventTypes.NextcloudCalendar, state_key))
            if event is not None and event["content"]:
                calendar_events.append(event)
        return calendar_events

    async def _get_calendar_ids(self, room_id: str) -> List[int]:
        calendar_ids = []
        for event in await self._get_calendar_events(room_id):
            calendar_ids.append(event["content"]["id"])
        return calendar_ids

    def _make_calendar_event_content(self, calendar: dict) -> dict:
        return {
            "id": calendar["id"],
            "is_personal": calendar["is_personal"],
        }


class CalendarComponentTypes:
    VEVENT_VTODO = "VEVENT_VTODO"
    VEVENT = "VEVENT"
    VTODO = "VTODO"
    ALL = (VEVENT_VTODO, VEVENT, VTODO)

    @classmethod
    def serialize(cls, components: List[str]) -> str:
        key = set(components)
        if key == {cls.VEVENT, cls.VTODO}:
            return cls.VEVENT_VTODO
        if key == {cls.VEVENT}:
            return cls.VEVENT
        if key == {cls.VTODO}:
            return cls.VTODO

    @classmethod
    def deserialize(cls, components: str) -> Set[str]:
        types = {
            cls.VEVENT_VTODO: {cls.VEVENT, cls.VTODO},
            cls.VEVENT: {cls.VEVENT},
            cls.VTODO: {cls.VTODO},
        }
        return types.get(components)

    @classmethod
    def deserialize_from_state_keys(cls, state_keys: List[str]) -> Set[str]:
        component_set = set()
        for key in state_keys:
            component_set.update(cls.deserialize(key))
        return component_set

    @classmethod
    def from_calendar(cls, calendar: dict) -> Set[str]:
        return set(calendar["components"])
