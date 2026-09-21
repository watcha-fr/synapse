import logging
from typing import Optional, TYPE_CHECKING

from synapse.api.errors import NextcloudError
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
        self.hs = hs
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

        try:
            await self.nextcloud_client.set_user_enabled(nextcloud_username, enabled)
        except NextcloudError as error:
            # 101 : le compte n'existe plus côté Nextcloud. C'est le cas quand
            # la désactivation vient justement de sa suppression là-bas : il n'y
            # a rien à verrouiller, et l'état voulu est déjà atteint. Toute
            # autre défaillance, transport ou authentification, remonte.
            if error.code != 101:
                raise
            logger.warning(
                build_log_message(
                    action="Nextcloud account already gone, nothing to lock",
                    status=ActionStatus.SUCCESS,
                    log_vars={"nextcloud_username": nextcloud_username},
                )
            )

    async def handle_nextcloud_change(
        self, nextcloud_username: str, action: str, requester
    ) -> Optional[str]:
        """Carry over to Matrix and Keycloak what just happened in Nextcloud.

        Deleting an account there is an explicit, destructive gesture: it takes
        the Keycloak account with it and erases the Synapse one, short-circuiting
        the retention period. Merely disabling it is the reversible path.

        Returns:
            the matrix ID the name pointed at, or None if nothing is mapped.
        """

        user_id = await self.store.get_user_id_by_nextcloud_username(
            nextcloud_username
        )
        if user_id is None:
            logger.info(
                build_log_message(
                    action="no Matrix account mapped to that Nextcloud name",
                    status=ActionStatus.SUCCESS,
                    log_vars={"nextcloud_username": nextcloud_username},
                )
            )
            return None

        deactivate_handler = self.hs.get_deactivate_account_handler()

        if action == "enable":
            await deactivate_handler.activate_account(user_id)
        elif action == "disable":
            await deactivate_handler.deactivate_account(
                user_id, erase_data=False, requester=requester, by_admin=True
            )
        elif action == "delete":
            await deactivate_handler.deactivate_account(
                user_id, erase_data=True, requester=requester, by_admin=True
            )
            await self._delete_keycloak_account(user_id)
        else:
            raise ValueError(f"unknown action {action!r}")

        logger.info(
            build_log_message(
                status=ActionStatus.SUCCESS,
                log_vars={"user_id": user_id, "action": action},
            )
        )
        return user_id

    async def _delete_keycloak_account(self, user_id: str) -> None:
        """Point de non-retour : l'UUID disparaît, la personne ne peut plus
        revenir sous la même identité."""

        if not self.config.watcha.managed_idp:
            return

        keycloak_id = await self._get_keycloak_id(user_id)
        if keycloak_id is None:
            return

        await self.keycloak_client.delete_user(keycloak_id)

    async def _get_keycloak_id(self, user_id: str) -> Optional[str]:
        """The Keycloak UUID recorded as the OIDC subject of this user, if any."""
        external_ids = await self.store.get_external_ids_by_user(user_id)
        return external_ids[0][1] if external_ids else None
