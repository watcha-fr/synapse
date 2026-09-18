import logging
from typing import Optional, TYPE_CHECKING

from synapse.util.watcha import ActionStatus, build_log_message

if TYPE_CHECKING:
    from synapse.server import HomeServer

logger = logging.getLogger(__name__)


class AccountLifecycleHandler:
    """Propagates a Synapse account being deactivated or reactivated to Keycloak
    and Nextcloud.

    Nothing is deleted: Keycloak keeps the account and its UUID, Nextcloud keeps
    the files and the shares. Only the ability to log in is taken away, so the
    same identity can be brought back later.
    """

    def __init__(self, hs: "HomeServer"):
        self.config = hs.config
        self.store = hs.get_datastores().main
        self.keycloak_client = hs.get_keycloak_client()
        self.nextcloud_client = hs.get_nextcloud_client()

    async def set_account_enabled(self, user_id: str, enabled: bool) -> None:
        """Enable or disable the Keycloak and Nextcloud accounts bound to a user.

        Raises whatever the clients raise: the caller deactivates locally only
        once the external accounts are locked, so a failure leaves a consistent
        state rather than a user locked out of Synapse but still able to reach
        their documents.
        """
        await self._set_keycloak_enabled(user_id, enabled)
        await self._set_nextcloud_enabled(user_id, enabled)

    async def _set_keycloak_enabled(self, user_id: str, enabled: bool) -> None:
        if not self.config.watcha.managed_idp:
            return

        keycloak_id = await self._get_keycloak_id(user_id)
        if keycloak_id is None:
            logger.info(
                build_log_message(
                    action="skip Keycloak, no external identity",
                    status=ActionStatus.SUCCESS,
                    log_vars={"user_id": user_id},
                )
            )
            return

        await self.keycloak_client.set_user_enabled(keycloak_id, enabled)

    async def _set_nextcloud_enabled(self, user_id: str, enabled: bool) -> None:
        if not (
            self.config.watcha.managed_idp
            and self.config.watcha.nextcloud_integration
        ):
            return

        nextcloud_username = await self.store.get_username(user_id)
        if not nextcloud_username:
            logger.info(
                build_log_message(
                    action="skip Nextcloud, no account mapped",
                    status=ActionStatus.SUCCESS,
                    log_vars={"user_id": user_id},
                )
            )
            return

        await self.nextcloud_client.set_user_enabled(nextcloud_username, enabled)

    async def _get_keycloak_id(self, user_id: str) -> Optional[str]:
        """The Keycloak UUID recorded as the OIDC subject of this user, if any."""
        external_ids = await self.store.get_external_ids_by_user(user_id)
        return external_ids[0][1] if external_ids else None
