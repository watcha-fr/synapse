from synapse.http.client import SimpleHttpClient


class WatchaKeycloakClient(SimpleHttpClient):
    """ Interface for talking with Keycloak APIs
    """

    def __init__(self, hs):
        super(WatchaKeycloakClient, self).__init__(hs)

        self.keycloak_server = hs.config.keycloak_serveur
        self.keycloak_realm = hs.config.keycloak_realm
        self.service_account_name = hs.config.service_account_name
        self.service_account_password = hs.config.service_account_password

    async def _get_keycloak_access_token(self):
        """ Get the realm Keycloak access token in order to use Keycloak Admin API.

        Returns:
            The realm Keycloak access token.
        """

        response = await self.post_urlencoded_get_json(
            uri="{keycloak_server}/realms/{keycloak_realm}/protocol/openid-connect/token".format(
                keycloak_server=self.keycloak_server, keycloak_realm=self.keycloak_realm
            ),
            args={
                "client_id": "admin-cli",
                "username": self.service_account_name,
                "password": self.service_account_password,
                "grant_type": "password",
            },
        )
        return response["access_token"]

    async def get_all_keycloak_users(self):
        """ Get a list of all Keycloak users.

        Returns:
            A list of dict.
        """

        access_token = await self._get_keycloak_access_token()

        response = await self.get_json(
            "{keycloak_server}/admin/realms/{keycloak_realm}/users".format(
                keycloak_server=self.keycloak_server, keycloak_realm=self.keycloak_realm
            ),
            headers={"Authorization": ["Bearer {}".format(access_token)]},
        )
        return response

    async def get_keycloak_user(self, localpart):
        """ Get a list of all Keycloak users.

        Returns:
            A list of dict.
        """

        access_token = await self._get_keycloak_access_token()

        response = await self.get_json(
            "{keycloak_server}/admin/realms/{keycloak_realm}/users".format(
                keycloak_server=self.keycloak_server, keycloak_realm=self.keycloak_realm
            ),
            headers={"Authorization": ["Bearer {}".format(access_token)]},
            args={"username": localpart},
        )
        return response[0]
