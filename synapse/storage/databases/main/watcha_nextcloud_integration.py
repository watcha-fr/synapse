
from synapse.storage._base import SQLBaseStore
from synapse.storage.database import DatabasePool


class NextcloudStore(SQLBaseStore):
    def __init__(self, database: DatabasePool, db_conn, hs):
        super().__init__(database, db_conn, hs)


    async def get_nextcloud_directory_path_from_roomID(self, room_id):
        """ Get Nextcloud directory path which is mapped with room_id.
        """

        return await self.db_pool.simple_select_one_onecol(
            table="room_nextcloud_mapping",
            keyvalues={"room_id": room_id},
            retcol="directory_path",
            allow_none=True,
            desc="get_nextcloud_directory_path_from_roomID",
        )

    async def get_roomID_from_nextcloud_directory_path(self, directory_path):
        """ Get the room_id mapped with Nextcloud directory path.
        """

        return await self.db_pool.simple_select_one_onecol(
            table="room_nextcloud_mapping",
            keyvalues={"directory_path": directory_path},
            retcol="room_id",
            allow_none=True,
            desc="get_roomID_from_nextcloud_directory_path",
        )

    async def get_nextcloud_share_id_from_roomID(self, room_id):
        """ Get Nextcloud share id of the room id.
        """

        return await self.db_pool.simple_select_one_onecol(
            table="room_nextcloud_mapping",
            keyvalues={"room_id": room_id},
            retcol="share_id",
            allow_none=True,
            desc="get_nextcloud_share_id_from_roomID",
        )

    async def map_room_with_nextcloud_directory(
        self, room_id, directory_path, share_id
    ):
        """ Set mapping between Watcha room and Nextcloud directory.
        """

        await self.db_pool.simple_upsert(
            table="room_nextcloud_mapping",
            keyvalues={"room_id": room_id},
            values={
                "room_id": room_id,
                "directory_path": directory_path,
                "share_id": share_id,
            },
            desc="map_room_with_nextcloud_directory",
        )

    async def deleted_room_mapping_with_nextcloud_directory(self, room_id):
        """ Delete mapping between Watcha room and Nextcloud directory for room_id.
        """

        await self.db_pool.simple_delete(
            table="room_nextcloud_mapping",
            keyvalues={"room_id": room_id},
            desc="deleted_room_mapping_with_nextcloud_directory",
        )

    # +watcha
