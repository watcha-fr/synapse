from synapse.storage._base import SQLBaseStore
from synapse.storage.database import DatabasePool


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

    async def get_nextcloud_user_id(self, user_id: str):
        """Retrieve a Nextcloud user ID

        Args:
            user_id: The Matrix user ID

        Returns:
            the Nextcloud user ID bound to the provided Matrix user ID, or None if not known
        """
        return await self.db_pool.simple_select_one_onecol(
            table="user_external_ids",
            keyvalues={"auth_provider": "nextcloud", "user_id": user_id},
            retcol="external_id",
            allow_none=True,
            desc="get_nextcloud_user_id",
        )
