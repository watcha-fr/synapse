from typing import Optional  # watcha+

from synapse.storage._base import SQLBaseStore
from synapse.storage.database import DatabasePool, LoggingTransaction  # watcha+


class NextcloudStore(SQLBaseStore):
    def __init__(self, database: DatabasePool, db_conn, hs: "Homeserver"):
        super().__init__(database, db_conn, hs)

    async def get_share_id(self, room_id: str):
        """Get Nextcloud share id of a room.

        Args:
            room_id: id of the room
        """
        return await self.db_pool.simple_select_one_onecol(
            table="watcha_nextcloud_shares",
            keyvalues={"room_id": room_id},
            retcol="share_id",
            allow_none=True,
            desc="get_nextcloud_share_id",
        )

    async def register_share(self, room_id: str, share_id: str):
        """Register a share between a room and a Nextcloud folder

        Args:
            room_id: id of the room
            share_id: id of the Nextcloud share
        """
        await self.db_pool.simple_upsert(
            table="watcha_nextcloud_shares",
            keyvalues={"room_id": room_id},
            values={"share_id": share_id},
            desc="register_nextcloud_share",
        )

    async def delete_share(self, room_id: str):
        """Delete an existing share of a room

        Args:
            room_id: id of the room where the share is associated
        """
        await self.db_pool.simple_delete(
            table="watcha_nextcloud_shares",
            keyvalues={"room_id": room_id},
            desc="delete_nextcloud_share",
        )

    async def get_user_id_by_nextcloud_username(self, nextcloud_username: str):
        """Look up a Matrix user by their Nextcloud name.

        The Nextcloud connector only knows that name: it has no way of guessing
        the mxid, which the mapping alone relates to it.

        Args:
            nextcloud_username: the Nextcloud account name

        Returns:
            the matrix ID, or None if no account is mapped to that name
        """
        return await self.db_pool.simple_select_one_onecol(
            table="user_external_ids",
            keyvalues={"nextcloud_username": nextcloud_username},
            retcol="user_id",
            allow_none=True,
            desc="get_user_id_by_nextcloud_username",
        )

    async def is_nextcloud_username_taken(self, nextcloud_username: str) -> bool:
        """Whether a Nextcloud username is already mapped to someone.

        Args:
            nextcloud_username: the name to check
        """
        rows = await self.db_pool.simple_select_onecol(
            table="user_external_ids",
            keyvalues={"nextcloud_username": nextcloud_username},
            retcol="user_id",
            desc="is_nextcloud_username_taken",
        )
        return bool(rows)

    async def get_room_folder_heir(
        self, room_id: str, leaving_user_id: str
    ) -> Optional[str]:
        """Qui reprend le dossier d'un salon quand son propriétaire s'en va.

        Le plus ancien membre encore présent, à trois conditions : qu'il ait
        rejoint le salon, qu'il soit membre de plein droit, et qu'il ait un
        compte Nextcloud pour recevoir les fichiers.

        « Le plus ancien » se lit dans le salon, pas dans l'annuaire : c'est
        celui dont l'adhésion courante est la plus ancienne. Quelqu'un qui est
        parti puis revenu compte donc depuis son retour.

        Les partenaires sont écartés : ce sont des externes à l'organisation, et
        les documents d'un salon ne leur reviennent pas. Si seuls des partenaires
        restent, personne n'hérite — comme si le salon était vide.

        Args:
            room_id: le salon dont le dossier cherche un propriétaire
            leaving_user_id: la personne qui part, à ne pas désigner

        Returns:
            le nom Nextcloud de l'héritier, ou None si personne ne peut l'être
        """

        def _get_room_folder_heir_txn(txn: LoggingTransaction) -> Optional[str]:
            sql = """
                SELECT e.nextcloud_username
                FROM current_state_events c
                JOIN room_memberships m ON m.event_id = c.event_id
                JOIN events ev ON ev.event_id = c.event_id
                JOIN users u ON u.name = m.user_id
                JOIN user_external_ids e ON e.user_id = m.user_id
                WHERE c.room_id = ?
                  AND c.type = 'm.room.member'
                  AND m.membership = 'join'
                  AND m.user_id != ?
                  AND u.deactivated = 0
                  AND COALESCE(u.is_partner, 0) = 0
                  AND e.nextcloud_username IS NOT NULL
                  AND e.nextcloud_username != ''
                ORDER BY ev.stream_ordering ASC
                LIMIT 1
            """
            txn.execute(sql, (room_id, leaving_user_id))
            row = txn.fetchone()
            return row[0] if row else None

        return await self.db_pool.runInteraction(
            "get_room_folder_heir", _get_room_folder_heir_txn
        )

    async def release_nextcloud_username(self, user_id: str) -> None:
        """Give the Nextcloud name back once the account it designated is gone.

        The mapping row outlives the account: a Matrix localpart stays taken for
        good, so erasing keeps the row and only empties the readable name. Left
        in place it kept reserving a name nothing answered to any more, and the
        same person coming back collected a suffix at each return — `dupont`,
        then `dupont2`, then `dupont3`.

        Only ever called once the Nextcloud account has actually been deleted,
        so nothing can collide with the freed name.

        Args:
            user_id: the matrix ID whose Nextcloud name is released
        """
        await self.db_pool.simple_update(
            table="user_external_ids",
            keyvalues={"user_id": user_id},
            updatevalues={"nextcloud_username": None},
            desc="release_nextcloud_username",
        )

    async def get_username(self, user_id: str):
        """Look up a Nextcloud username by their user_id

        Args:
            user_id: The matrix ID of the user

        Returns:
            the Nextcloud username of the user, or None if they are not known
        """
        return await self.db_pool.simple_select_one_onecol(
            table="user_external_ids",
            keyvalues={"user_id": user_id},
            retcol="nextcloud_username",
            allow_none=True,
            desc="get_nextcloud_username",
        )
