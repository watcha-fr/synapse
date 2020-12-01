import re
from urllib.parse import urljoin

from ._base import Config, ConfigError


class NextcloudIntegrationConfig(Config):

    section = "nextcloudintegration"

    # echo -n watcha | md5sum
    SERVICE_ACCOUNT_NAME = "c4d96a06b758a7ed12f897690828e414_watcha_service_account"

    def __init__(self, *args):
        super().__init__(*args)

        self.keycloak_url = None
        self.realm_name = None
        self.nextcloud_url = None
        self.service_account_name = None
        self.keycloak_service_account_password = None
        self.nextcloud_service_account_password = None

    def read_config(self, config, **kwargs):
        self.nextcloud_enabled = False

        nextcloud_config = config.get("nextcloud_integration")
        if not nextcloud_config or not nextcloud_config.get("enabled", False):
            return

        oidc_config = config.get("oidc_config")
        if not oidc_config or not oidc_config.get("enabled", False):
            return

        issuer = oidc_config.get("issuer", "")
        match = re.match("(https?://.+?)/realms/([^/]+)", issuer)
        if match is None:
            raise ConfigError(
                "nextcloud_integration requires oidc_config.issuer to be of the form https://example/realms/xxx"
            )
        self.keycloak_url = match.group(1)
        self.realm_name = match.group(2)

        nextcloud_url = nextcloud_config.get("nextcloud_url")
        if nextcloud_url is None:
            client_base_url = config.get("email", {}).get("client_base_url")
            if client_base_url is None:
                raise ConfigError(
                    "nextcloud_integration requires nextcloud_url or email.client_base_url to be set"
                )
            nextcloud_url = urljoin(client_base_url, "nextcloud")
        self.nextcloud_url = nextcloud_url

        self.service_account_name = self.SERVICE_ACCOUNT_NAME

        self.keycloak_service_account_password = nextcloud_config[
            "keycloak_service_account_password"
        ]
        self.nextcloud_service_account_password = nextcloud_config[
            "nextcloud_service_account_password"
        ]

    def generate_config_section(self, config_dir_path, server_name, **kwargs):
        return """\
        # Configuration for the Nextcloud integration
        #
        nextcloud_integration:
          # Uncomment the below to enable the Nextcloud integration
          #
          #enabled: true

          # Optional
          # Default domaine infered from email.client_base_url, with "nextcloud" as path.
          #
          #nextcloud_url: "https://example.com/nextcloud"

          #keycloak_service_account_password: "examplepassword"

          #nextcloud_service_account_password: "examplepassword"
        """
