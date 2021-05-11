from synapse.storage._base import SQLBaseStore
from synapse.storage.database import DatabasePool


class NextcloudStore(SQLBaseStore):
    def __init__(self, database: DatabasePool, db_conn, hs: "Homeserver"):
        super().__init__(database, db_conn, hs)

    async def get_share_ids(self, room_id: str):
        """Get the internal share id of a room.

        Args:
            room_id: id of the room

        Returns:
            a list of all share ids of the room
        """
        return await self.db_pool.simple_select_list(
            table="watcha_nextcloud_shares",
            keyvalues={
                "room_id": room_id,
            },
            retcols={"share_id"},
            allow_none=True,
            desc="get_share_ids",
        )

    async def register_share(
        self, room_id: str, share_id: str, public_link: str = None
    ):
        """Register a public link or an internal share between a room and a Nextcloud folder

        Args:
            room_id: id of the room
            share_id: id of the Nextcloud share
            public_link: url of the public link
        """
        await self.db_pool.simple_upsert(
            table="watcha_nextcloud_shares",
            keyvalues={"room_id": room_id, "share_id": share_id},
            values={
                "room_id": room_id,
                "share_id": share_id,
                "public_link": public_link,
            },
            desc="register_share",
        )

    async def delete_all_shares(self, room_id: str):
        """Delete all existing shares of a room

        Args:
            room_id: id of the room where the share is associated
        """
        await self.db_pool.simple_delete(
            table="watcha_nextcloud_shares",
            keyvalues={"room_id": room_id},
            desc="delete_all_shares",
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
