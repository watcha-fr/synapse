from typing import List

from synapse.http.client import SimpleHttpClient


class WatchaKeycloakClient(SimpleHttpClient):
    """ Interface for talking with Keycloak APIs
    """

    def __init__(self, hs):
        super().__init__(hs)
    
        self.server_url = hs.config.keycloak_url
        self.realm_name = hs.config.realm_name
        self.service_account_name = hs.config.service_account_name
        self.service_account_password = hs.config.keycloak_service_account_password

    async def get_user(self, localpart) -> dict:
        """ Get a specific Keycloak user.

        Returns:
            dict
            https://www.keycloak.org/docs-api/11.0/rest-api/#_userrepresentation
        """

        response = await self.get_json(
            self._get_endpoint("admin/realms/{}/users".format(self.realm_name)),
            headers=await self._get_header(),
            args={"username": localpart},
        )
        return response[0]

    async def get_users(self) -> List[dict]:
        """ Get a list of Keycloak users.

        Returns:
            Each user as a dictionary.
        """

        response = await self.get_json(
            self._get_endpoint("admin/realms/{}/users".format(self.realm_name)),
            headers=await self._get_header(),
        )
        return response

    async def _get_header(self):
        access_token = await self._get_access_token()
        return {"Authorization": ["Bearer {}".format(access_token)]}

    async def _get_access_token(self):
        """ Get the realm Keycloak access token in order to use Keycloak Admin API.

        Returns:
            The realm Keycloak access token.
        """

        response = await self.post_urlencoded_get_json(
            uri=self._get_endpoint(
                "realms/{}/protocol/openid-connect/token".format(self.realm_name)
            ),
            args={
                "client_id": "admin-cli",
                "grant_type": "password",
                "username": self.service_account_name,
                "password": self.service_account_password,
            },
        )
        return response["access_token"]

    def _get_endpoint(self, path):
        return "{}/{}".format(self.server_url, path)
