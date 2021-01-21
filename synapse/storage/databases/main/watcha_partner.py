import logging

from synapse.storage._base import SQLBaseStore
from synapse.storage.database import DatabasePool


class PartnerStore(SQLBaseStore):
    def __init__(self, database: DatabasePool, db_conn, hs):
        super().__init__(database, db_conn, hs)
        self.clock = hs.get_clock()

    async def insert_partner_invitation(
        self, partner_id, sender_id, sender_device_id, email_sent=False
    ):
        """Record a partner invitation

        Args:
            partner_id (str): the partner mxid
            sender_id (str): the mxid of the sender
            device_id (str): the device id of the sender
            email_sent (bool): True if email was sent to the partner
        """
        await self.db_pool.simple_insert(
            table="partners_invited_by",
            values={
                "partner": partner_id,
                "invited_by": sender_id,
                "invitation_ts": self.clock.time(),
                "device_id": sender_device_id,
                "email_sent": email_sent,
            },
            desc="insert_partner_invitation",
        )
