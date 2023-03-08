import re
from urllib.parse import urljoin

from synapse.util.watcha import build_log_message

from ._base import Config, ConfigError


class WatchaConfig(Config):
    section = "watcha"

    def __init__(self, *args):
        super().__init__(*args)

        self.managed_idp = False
        self.keycloak_url = None
        self.realm_name = None
        self.keycloak_service_account_name = "watcha"
        self.keycloak_service_account_password = None
        self.nextcloud_integration = False
        self.nextcloud_service_account_name = "watcha"
        self.nextcloud_service_account_password = None
        self.nextcloud_url = None
        self.external_authentication_for_partners = False

    def read_config(self, config, **kwargs):
        watcha_config = config.get("watcha")

        if watcha_config is None:
            return

        managed_idp = watcha_config.get("managed_idp")
        if isinstance(managed_idp, bool):
            self.managed_idp = managed_idp

        if self.managed_idp:

            oidc_providers = config.get("oidc_providers")
            if not oidc_providers or oidc_providers[0].get("idp_id") != "oidc":
                raise ConfigError('the first idp_id must be "oidc"')
            issuer = oidc_providers[0].get("issuer", "")
            match = re.match("(https?://.+?)/realms/([^/]+)", issuer)
            if match:
                self.keycloak_url = match.group(1)
                self.realm_name = match.group(2)

            service_account_name = watcha_config.get("keycloak_service_account_name")
            if service_account_name:
                self.keycloak_service_account_name = service_account_name

            self.keycloak_service_account_password = watcha_config[
                "keycloak_service_account_password"
            ]

            external_authentication_for_partners = watcha_config.get(
                "external_authentication_for_partners"
            )
            if isinstance(external_authentication_for_partners, bool):
                self.external_authentication_for_partners = (
                    external_authentication_for_partners
                )

        nextcloud_integration = watcha_config.get("nextcloud_integration")
        if isinstance(nextcloud_integration, bool):
            self.nextcloud_integration = nextcloud_integration

        if nextcloud_integration:

            service_account_name = watcha_config.get("nextcloud_service_account_name")
            if service_account_name:
                self.nextcloud_service_account_name = service_account_name

            self.nextcloud_service_account_password = watcha_config[
                "nextcloud_service_account_password"
            ]

            nextcloud_url = watcha_config.get("nextcloud_url")
            if nextcloud_url is None:
                client_base_url = config.get("email", {}).get("client_base_url")
                if client_base_url is None:
                    raise ConfigError(
                        build_log_message(
                            action="get `client_base_url` from config",
                            log_vars={"client_base_url": client_base_url},
                        )
                    )
                nextcloud_url = urljoin(client_base_url, "nextcloud")
            self.nextcloud_url = nextcloud_url

    def generate_config_section(self, config_dir_path, server_name, **kwargs):
        return """\
        # Specific configuration for Watcha
        #
        watcha:
          # Whether to use an IDP (Keycloak) managed by Watcha
          # Optional, defaults to false.
          #
          #managed_idp: true

          # Optional, defaults to "watcha".
          #
          #keycloak_service_account_name: watcha

          # Required if managed_idp is true.
          #
          #keycloak_service_account_password: <keycloak_service_account_password>

          # Whether to enable Nextcloud integration:
          #   - support for Nextcloud document, calendar and task list sharing within Matrix rooms
          #   - Nextcloud account creation if nonexistent
          # Optional, defaults to false.
          #
          #nextcloud_integration: true

          # Optional, defaults to "watcha".
          #
          #nextcloud_service_account_name: watcha

          # Required if nextcloud_integration is true.
          #
          #nextcloud_service_account_password: <nextcloud_service_account_password>

          # Optional, default domaine infered from email.client_base_url, with "nextcloud" as path.
          #
          #nextcloud_url: "https://example.com/nextcloud"

          # Whether external user accounts are only created in the Synapse database
          # Optional, defaults to false.
          # Note: The value is ignored when managed_idp is false
          #
          #external_authentication_for_partners: true
        """
