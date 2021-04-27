from synapse.storage._base import SQLBaseStore
from synapse.storage.database import DatabasePool


class NextcloudStore(SQLBaseStore):
    def __init__(self, database: DatabasePool, db_conn, hs: "Homeserver"):
        super().__init__(database, db_conn, hs)

    async def get_path_folder(self, room_id: str):
        """Get the Nextcloud folder path which is bound with room_id."""

        return await self.db_pool.simple_select_one_onecol(
            table="room_nextcloud_mapping",
            keyvalues={"room_id": room_id},
            retcol="directory_path",
            allow_none=True,
            desc="get_path_folder",
        )

    async def get_share_id(self, room_id: str):
        """Get Nextcloud share id of the room id."""

        return await self.db_pool.simple_select_one_onecol(
            table="room_nextcloud_mapping",
            keyvalues={"room_id": room_id},
            retcol="share_id",
            allow_none=True,
            desc="get_share_id",
        )

    async def register_share(self, room_id: str, path: str, share_id: str):
        """Bind a room with a Nextcloud folder."""

        await self.db_pool.simple_upsert(
            table="room_nextcloud_mapping",
            keyvalues={"room_id": room_id},
            values={
                "room_id": room_id,
                "directory_path": path,
                "share_id": share_id,
            },
            desc="bind",
        )

    async def delete_share(self, room_id: str):
        """Delete mapping between Watcha room and Nextcloud directory for room_id."""

        await self.db_pool.simple_delete(
            table="room_nextcloud_mapping",
            keyvalues={"room_id": room_id},
            desc="unbind",
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
            desc="get_username",
        )
