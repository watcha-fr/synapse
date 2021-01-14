from synapse.storage._base import SQLBaseStore
from synapse.storage.database import DatabasePool


class NextcloudStore(SQLBaseStore):
    def __init__(self, database: DatabasePool, db_conn, hs):
        super().__init__(database, db_conn, hs)

    async def get_path_from_room_id(self, room_id):
        """Get the Nextcloud folder path which is bound with room_id."""

        return await self.db_pool.simple_select_one_onecol(
            table="room_nextcloud_mapping",
            keyvalues={"room_id": room_id},
            retcol="directory_path",
            allow_none=True,
            desc="get_path_from_room_id",
        )

    async def get_nextcloud_share_id_from_room_id(self, room_id):
        """Get Nextcloud share id of the room id."""

        return await self.db_pool.simple_select_one_onecol(
            table="room_nextcloud_mapping",
            keyvalues={"room_id": room_id},
            retcol="share_id",
            allow_none=True,
            desc="get_nextcloud_share_id_from_room_id",
        )

    async def bind(self, room_id, path, share_id):
        """Bind a room with a Nextcloud folder."""

        await self.db_pool.simple_upsert(
            table="room_nextcloud_mapping",
            keyvalues={"room_id": room_id},
            values={"room_id": room_id, "directory_path": path, "share_id": share_id,},
            desc="bind",
        )

    async def unbind(self, room_id):
        """Delete mapping between Watcha room and Nextcloud directory for room_id."""

        await self.db_pool.simple_delete(
            table="room_nextcloud_mapping",
            keyvalues={"room_id": room_id},
            desc="unbind",
        )

    async def get_nextcloud_username(self, user_id):
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
