from synapse.storage.database import DatabasePool
import logging
from twisted.internet import defer
from synapse.storage._base import SQLBaseStore, make_in_list_sql_clause
logger = logging.getLogger(__name__)

# from synapse.api.errors import StoreError, Codes


# from synapse.util.caches.descriptors import cached, cachedInlineCallbacks


class ExternalInvitationStore(SQLBaseStore):
    def __init__(self, database: DatabasePool, db_conn, hs):
        super(ExternalInvitationStore, self).__init__(database, db_conn, hs)

        self.clock = hs.get_clock()

    async def insert_partner_invitation(
        self, partner_user_id, inviter_user_id, inviter_device_id, email_sent
    ):
        """Adds an access token for the given user.

        Args:
            user_id (str): The user ID.
            token (str): The new access token to add.
            device_id (str): ID of the device to associate with the access
               token
        Raises:
            StoreError if there was a problem adding this.
        """
        now = int(self.clock.time())
        logger.info(
            "insert_partner_invitation: partner="
            + str(partner_user_id)
            + " invited_by="
            + str(inviter_user_id)
            + " invitation_ts="
            + str(now)
            + " device_id="
            + str(inviter_device_id)
            + " email_sent="
            + str(email_sent)
        )
        await self.db_pool.simple_insert(
            "partners_invited_by",
            {
                "partner": str(partner_user_id),
                "invited_by": str(inviter_user_id),
                "invitation_ts": now,
                "device_id": str(inviter_device_id),
                "email_sent": email_sent,
            },
            desc="insert_partner_invitation",
        )
