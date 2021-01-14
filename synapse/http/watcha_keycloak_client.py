import logging
from jsonschema import validate
from typing import List

from synapse.api.errors import HttpResponseException
from synapse.http.client import SimpleHttpClient

logger = logging.getLogger(__name__)

TOKEN_SCHEMA = {
    "$schema": "http://json-schema.org/draft-04/schema#",
    "description": "Keycloak token schema",
    "type": "object",
    "properties": {
        "access_token": {
            "type": "string",
        },
    },
    "required": ["access_token"],
}

USER_SCHEMA = {
    "$schema": "http://json-schema.org/draft-04/schema#",
    "description": "Keycloak user schema",
    "type": "array",
    "properties": {
        "id": {
            "type": "string",
        },
        "username": {
            "type": "string",
        },
    },
    "required": ["id", "username"],
}


class KeycloakClient(SimpleHttpClient):
    """Interface for talking with Keycloak APIs"""

    def __init__(self, hs):
        super().__init__(hs)

        self.server_url = hs.config.keycloak_url
        self.realm_name = hs.config.realm_name
        self.service_account_name = hs.config.service_account_name
        self.service_account_password = hs.config.keycloak_service_account_password

    async def add_user(self, password_hash, email, is_admin=False):
        """Create a new user

        Args:
            password_hash: the synapse password hash
            email: email of the user
            is_admin: whether the user is a synapse administrator or not
        """

        user = {
            "enabled": True,
            "username": email,
            "email": email,
            "credentials": [
                {
                    "type": "password",
                    "secretData": '{{"value":"{}","salt":""}}'.format(password_hash),
                    "credentialData": '{"hashIterations":-1,"algorithm":"bcrypt"}',
                }
            ],
            "attributes": {"locale": ["fr"]},
            "requiredActions": ["UPDATE_PASSWORD", "UPDATE_PROFILE"],
        }

        if is_admin:
            user["attributes"]["isAdmin"] = True

        try:
            return await self.post_json_get_json(
                uri=self._get_endpoint("admin/realms/{}/users", self.realm_name),
                headers=await self._get_header(),
                post_json=user,
            )
        except HttpResponseException as e:
            if e.code == 409:
                logger.info(
                    "User with email {} already exists on Keycloak server.".format(
                        email
                    )
                )
            else:
                raise

    async def delete_user(self, user_id):
        """Delete an existing user

        Args:
            user_id: the Keycloak user id
        """

        await self.delete_get_json(
            uri=self._get_endpoint(
                "admin/realms/{}/users/{}", self.realm_name, user_id
            ),
            headers=await self._get_header(),
        )

    async def get_user(self, localpart) -> dict:
        """Get a specific Keycloak user.

        Returns:
            dict
            https://www.keycloak.org/docs-api/11.0/rest-api/#_userrepresentation
        """

        response = await self.get_json(
            uri=self._get_endpoint("admin/realms/{}/users", self.realm_name),
            headers=await self._get_header(),
            args={"username": localpart},
        )

        validate(response, USER_SCHEMA)

        return response[0]

    async def get_users(self) -> List[dict]:
        """Get a list of Keycloak users.

        Returns:
            Each user as a dictionary.
        """

        response = await self.get_json(
            uri=self._get_endpoint("admin/realms/{}/users", self.realm_name),
            headers=await self._get_header(),
        )

        validate(response, USER_SCHEMA)

        return response

    async def update_user(self, user_id, attributes):
        """Update specific attribute of a Keycloak user

        Args:
            user_id: the Keycloak user id
        """

        await self.put_json(
            uri=self._get_endpoint(
                "admin/realms/{}/users/{}", self.realm_name, user_id
            ),
            headers=await self._get_header(),
            json_body={"attributes": attributes},
        )

    async def _get_header(self):
        access_token = await self._get_access_token()
        return {"Authorization": ["Bearer {}".format(access_token)]}

    async def _get_access_token(self):
        """Get the realm Keycloak access token in order to use Keycloak Admin API.

        Returns:
            The realm Keycloak access token.
        """

        response = await self.post_urlencoded_get_json(
            uri=self._get_endpoint(
                "realms/{}/protocol/openid-connect/token", self.realm_name
            ),
            args={
                "client_id": "admin-cli",
                "grant_type": "password",
                "username": self.service_account_name,
                "password": self.service_account_password,
            },
        )

        validate(response, TOKEN_SCHEMA)

        return response["access_token"]

    def _get_endpoint(self, path, *args):
        if args:
            path = path.format(*args)
        return "{}/{}".format(self.server_url, path)
