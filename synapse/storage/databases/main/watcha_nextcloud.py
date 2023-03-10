from typing import TYPE_CHECKING

from synapse.storage._base import SQLBaseStore
from synapse.storage.database import DatabasePool

if TYPE_CHECKING:
    from synapse.server import HomeServer


class NextcloudStore(SQLBaseStore):
    def __init__(self, database: DatabasePool, db_conn, hs: "HomeServer"):
        super().__init__(database, db_conn, hs)

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
