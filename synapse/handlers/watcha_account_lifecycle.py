import logging
from typing import Optional, TYPE_CHECKING

from synapse.api.errors import HttpResponseException, NextcloudError
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

    async def delete_external_accounts(self, user_id: str) -> None:
        """Delete the Keycloak and Nextcloud accounts bound to a user.

        The destructive counterpart of `set_account_enabled`, for when the
        gesture is a deletion rather than a deactivation. Whichever of the three
        systems it starts from, the outcome is the same: Keycloak and Nextcloud
        are deleted, Synapse is deactivated and erased — it cannot delete, a
        localpart stays taken for good.

        Nextcloud goes first on purpose: it is the irreversible half, since it
        destroys the person's files, so a failure there must leave the Keycloak
        identity — and therefore the whole account — intact and retryable.
        """
        await self._delete_nextcloud_account(user_id)
        await self._delete_keycloak_account(user_id)

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
            # La suppression des comptes Keycloak et Nextcloud est portée par
            # le fan-out de `deactivate_account`, sur le drapeau d'effacement :
            # le geste est le même d'où qu'il parte.
            await deactivate_handler.deactivate_account(
                user_id, erase_data=True, requester=requester, by_admin=True
            )
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

        try:
            await self.keycloak_client.delete_user(keycloak_id)
        except HttpResponseException as error:
            # Déjà supprimé, par exemple quand la demande vient de Keycloak
            # lui-même : l'état voulu est atteint.
            if error.code != 404:
                raise
            logger.warning(
                build_log_message(
                    action="Keycloak account already gone",
                    status=ActionStatus.SUCCESS,
                    log_vars={"keycloak_id": keycloak_id},
                )
            )

    async def _delete_nextcloud_account(self, user_id: str) -> None:
        """Détruit le compte et **ses fichiers**, dossiers documentaires de
        salons compris. C'est la moitié irréversible du geste."""

        if not (
            self.config.watcha.managed_idp
            and self.config.watcha.nextcloud_integration
        ):
            return

        nextcloud_username = await self.store.get_username(user_id)
        if not nextcloud_username:
            return

        try:
            await self.nextcloud_client.delete_user(nextcloud_username)
        except NextcloudError as error:
            # Le compte n'existe plus, ce qui est précisément le cas quand la
            # demande vient de sa suppression là-bas. Les deux codes valent
            # « inconnu » : `enable`/`disable` répondent 101, mais `delete`
            # répond 998. Ne tolérer que 101 faisait échouer la suppression
            # partie de Nextcloud — le geste le plus courant — et Keycloak
            # comme Matrix survivaient à un compte pourtant supprimé.
            if error.code not in (101, 998):
                raise
            logger.warning(
                build_log_message(
                    action="Nextcloud account already gone",
                    status=ActionStatus.SUCCESS,
                    log_vars={"nextcloud_username": nextcloud_username},
                )
            )

    async def _get_keycloak_id(self, user_id: str) -> Optional[str]:
        """The Keycloak UUID recorded as the OIDC subject of this user, if any."""
        external_ids = await self.store.get_external_ids_by_user(user_id)
        return external_ids[0][1] if external_ids else None
