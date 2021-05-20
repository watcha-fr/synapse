from synapse.storage._base import SQLBaseStore
from synapse.storage.database import DatabasePool


class NextcloudStore(SQLBaseStore):
    def __init__(self, database: DatabasePool, db_conn, hs: "Homeserver"):
        super().__init__(database, db_conn, hs)

    async def get_internal_share_id(self, room_id: str):
        """Get the internal share id of a room.

        Args:
            room_id: id of the room

        Returns:
            the internal share id of a room
        """
        return await self.db_pool.simple_select_one_onecol(
            table="watcha_nextcloud_shares",
            keyvalues={
                "room_id": room_id,
            },
            retcol="internal_share_id",
            allow_none=True,
            desc="get_internal_share_id",
        )

    async def get_public_link_share_id(self, room_id: str):
        """Get the public link share id of a room.

        Args:
            room_id: id of the room

        Returns:
            the public link share id of a room
        """
        return await self.db_pool.simple_select_one_onecol(
            table="watcha_nextcloud_shares",
            keyvalues={
                "room_id": room_id,
            },
            retcol="public_link_share_id",
            allow_none=True,
            desc="get_public_link_share_id",
        )

    async def register_internal_share(self, room_id: str, internal_share_id: str):
        """Register an internal share between a room and a Nextcloud folder

        Args:
            room_id: id of the room
            internal_share_id: id of the internal share
        """
        await self.db_pool.simple_upsert(
            table="watcha_nextcloud_shares",
            keyvalues={"room_id": room_id},
            values={
                "room_id": room_id,
                "internal_share_id": internal_share_id,
            },
            desc="register_internal_share",
        )

    async def register_public_link_share(self, room_id: str, public_link_share_id: str):
        """Register an public link share between a room and a Nextcloud folder

        Args:
            room_id: id of the room
            public_link_share_id: id of the public link share
        """
        await self.db_pool.simple_upsert(
            table="watcha_nextcloud_shares",
            keyvalues={
                "room_id": room_id,
            },
            values={
                "room_id": room_id,
                "public_link_share_id": public_link_share_id,
            },
            desc="register_public_link_share",
        )

    async def delete_internal_share(self, room_id: str):
        """Delete the existing internal share of a room

        Args:
            room_id: id of the room where the share is associated
        """
        await self.db_pool.simple_update_one(
            table="watcha_nextcloud_shares",
            keyvalues={"room_id": room_id},
            updatevalues={"internal_share_id": None},
            desc="delete_internal_share",
        )

    async def delete_public_link_share(self, room_id: str):
        """Delete the existing public link share of a room

        Args:
            room_id: id of the room where the share is associated
        """
        await self.db_pool.simple_update_one(
            table="watcha_nextcloud_shares",
            keyvalues={"room_id": room_id},
            updatevalues={"public_link_share_id": None},
            desc="delete_public_link_share",
        )

    async def delete_all_shares(self, room_id: str):
        """Delete all existing shares of a room

        Args:
            room_id: id of the room where shares are associated
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
