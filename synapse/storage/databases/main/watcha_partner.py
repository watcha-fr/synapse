from synapse.storage._base import SQLBaseStore
from synapse.storage.database import DatabasePool


class PartnerStore(SQLBaseStore):
    def __init__(self, database: DatabasePool, db_conn, hs):
        super().__init__(database, db_conn, hs)

    async def add_partner_invitation(self, partner_id, sender_id):
        """Record a partner invitation

        Args:
            partner_id (str): the partner mxid
            sender_id (str): the sender mxid
        """
        await self.db_pool.simple_insert(
            table="partners_invitations",
            values={
                "user_id": partner_id,
                "invited_by": sender_id,
            },
            or_ignore=True,
            desc="add_partner_invitation",
        )
