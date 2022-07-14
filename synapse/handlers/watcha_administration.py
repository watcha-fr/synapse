import logging

from synapse.api.errors import SynapseError
from synapse.types import UserID
from synapse.util.watcha import build_log_message

logger = logging.getLogger(__name__)


class AdministrationHandler:
    def __init__(self, hs: "HomeServer"):
        self.store = hs.get_datastores().main
        self.auth = hs.get_auth()
        self.auth_handler = hs.get_auth_handler()

    async def watcha_user_list(self):
        users = await self.store.watcha_user_list()

        result = []
        for user in users:
            role = await self.get_user_role(user["user_id"])

            result.append(
                {
                    "user_id": user["user_id"],
                    "email_address": user["email_address"],
                    "display_name": user["display_name"],
                    "role": role,
                    "last_seen": user["last_seen"],
                    "creation_ts": user["creation_ts"],
                }
            )

        return result

    async def update_user_role(self, user_id, target_role):
        """Update the user role

        Args:
            user_id: the id of the user
            target_role: role to be assigned to the user. It can be 'administrator', 'collaborator' or 'partner'
        """
        current_role = await self.get_user_role(user_id)

        if current_role == target_role:
            raise SynapseError(
                400,
                build_log_message(
                    log_vars={
                        "user_id": user_id,
                        "current_role": current_role,
                        "target_role": target_role,
                    }
                ),
            )

        await self.store.update_user_role(user_id, target_role)

        return target_role

    async def get_user_role(self, user_id):
        """Retrieve user role [administrator|collaborator|partner]

        Returns:
            The user role.
        """
        is_partner = await self.auth_handler.is_partner(user_id)
        is_admin = await self.auth.is_server_admin(UserID.from_string(user_id))

        if is_partner and is_admin:
            raise SynapseError(
                400,
                build_log_message(
                    log_vars={
                        "user_id": user_id,
                        "is_admin": is_admin,
                        "is_partner": is_partner,
                    }
                ),
            )
        elif is_partner:
            role = "partner"
        elif is_admin:
            role = "administrator"
        else:
            role = "collaborator"

        return role
