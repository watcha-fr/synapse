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
            desc="add_partner_invitation",
        )
        
    async def is_partner(self, user_id: str) -> bool:
            is_partner = await self.db_pool.simple_select_one_onecol(
                "users",
                keyvalues={"name": user_id},
                retcol="is_partner",
                allow_none=True,
                desc="is_partner",
            )
            return bool(is_partner)