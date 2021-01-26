from synapse.storage._base import SQLBaseStore
from synapse.storage.database import DatabasePool


class PartnerStore(SQLBaseStore):
    async def add_partner_invitation(self, partner_id: str, sender_id: str):
        """Record a partner invitation

        Args:
            partner_id: the partner mxid
            sender_id: the sender mxid
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
