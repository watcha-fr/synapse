from ._base import Config


class NextcloudIntegrationConfig(Config):
    """Nextcloud Integration Configuration
    Configuration for the behaviour of Nextcloud API and Keycloak API calls.
    """

    section = "nextcloudintegration"

    def read_config(self, config, **kwargs):
        self.nextcloud_integration_enabled = False
        nextcloud_integration_config = config.get("nextcloud_integration", None)
        if not nextcloud_integration_config:
            nextcloud_integration_config = {}

        self.keycloak_serveur = nextcloud_integration_config.get(
            "keycloak_serveur", ""
        )
        self.keycloak_realm = nextcloud_integration_config.get(
            "keycloak_realm", ""
        )
        self.nextcloud_server = nextcloud_integration_config.get(
            "nextcloud_server", ""
        )
        self.nextcloud_shared_secret = nextcloud_integration_config.get(
            "nextcloud_shared_secret", ""
        )
        self.service_account_name = nextcloud_integration_config.get(
            "service_account_name", ""
        )
        self.service_account_password = nextcloud_integration_config.get(
            "service_account_password", ""
        )

    def generate_config_section(self, config_dir_path, server_name, **kwargs):
        return """
        # Nextcloud Integration configuration
        #
        # 'keycloak_serveur' corresponds to the Keycloak server URL
        # use to handle authentification process.
        #
        # 'keycloak_realm' is the name of your Keycloak realm 
        # (https://www.keycloak.org/docs/latest/getting_started/#creating-a-realm-and-a-user)
        #
        # 'nextcloud_server' corresponds to the Nextcloud server URL.
        #
        # 'nextcloud_shared_secret' is the secret used to allow Synapse 
        # to logged as a user and to call Nextcloud APIs.
        #
        # 'service_account_name' is the name of the account service use to 
        # handle operations between keycloak, Synapse and Nextcloud.
        #
        # 'service_account_password' is the password or maybe more 
        # a shared secret for the service account.
        #
        #nextcloud_integration:
        #   keycloak_serveur: "https://example.com/auth"
        #   keycloak_realm: "example.com"
        #   nextcloud_server: "https://example.com/nextcloud"
        #   nextcloud_shared_secret: "YOUR_SHARED_SECRET"
        #   service_account_name: "example_account_service"
        #   service_account_password: "YOUR_SHARED_SECRET"
        """
