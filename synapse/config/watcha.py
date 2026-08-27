import os
import re
from urllib.parse import urljoin

from synapse.util.watcha import build_log_message
from synapse.util.watcha_blocked_extensions import BLOCKED_EXT_FILE  # watcha+

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
        # watcha+
        # Domaines de messagerie de l'organisation. Un utilisateur invité comme
        # partenaire dont l'adresse relève de l'un d'eux est finalement
        # enregistré comme membre de plein droit. Vide => aucun déclassement,
        # ce qui est le comportement de toutes les instances sauf ComUE.
        self.partner_email_whitelist = []
        # Actions imposées par Keycloak à la première connexion d'un compte
        # créé par Synapse. Les instances dont les comptes proviennent d'une
        # fédération d'identité (ComUE / Renater) mettent une liste vide.
        self.keycloak_required_actions = ["UPDATE_PASSWORD", "UPDATE_PROFILE"]
        # +watcha
        self.user_audit_log_path = None
        self.retention_config_path = None  # watcha+
        self.blocked_extensions_path = None  # watcha+
        # watcha+
        # Mapping ville -> domaines email pour le filtre "par ville" du dashboard.
        # Présent uniquement sur l'instance sitiv ; absent => pas de label `ville`.
        self.cities_by_domain = {}
        # Dict inversé domaine (minuscule) -> ville, construit depuis cities_by_domain.
        self.domain_to_city = {}
        # +watcha

    def read_config(self, config, **kwargs):
        data_dir_path = kwargs.get("data_dir_path") or os.getcwd()

        watcha_config = config.get("watcha")

        # Path of the JSON file in which user lifecycle actions (CREATE, DELETE,
        # DEACTIVATE, REACTIVATE) are recorded. Enabled by default so the audit
        # log is produced out of the box.
        self.user_audit_log_path = (watcha_config or {}).get(
            "user_audit_log_path"
        ) or os.path.join(data_dir_path, "watcha_user_audit_log.json")

        # watcha+
        # Path of the JSON file holding the server-wide "message depth" settings
        # (default retention duration + whether room admins may override it),
        # editable at runtime from the admin console. Defaults to the data dir.
        self.retention_config_path = (watcha_config or {}).get(
            "retention_config_path"
        ) or os.path.join(data_dir_path, "watcha_retention_config.json")

        # Path of the JSON file holding the list of file extensions whose upload
        # is rejected, editable at runtime from the admin console. Defaults to
        # the historical location so existing instances keep their list.
        self.blocked_extensions_path = (watcha_config or {}).get(
            "blocked_extensions_path"
        ) or BLOCKED_EXT_FILE
        # +watcha

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

        # watcha+
        partner_email_whitelist = watcha_config.get("partner_email_whitelist")
        if partner_email_whitelist is not None:
            if isinstance(partner_email_whitelist, str):
                partner_email_whitelist = [partner_email_whitelist]
            if not isinstance(partner_email_whitelist, list) or not all(
                isinstance(domain, str) for domain in partner_email_whitelist
            ):
                raise ConfigError(
                    "watcha.partner_email_whitelist must be a list of domain names"
                )
            self.partner_email_whitelist = [
                domain.strip().lower().lstrip("@").rstrip(".")
                for domain in partner_email_whitelist
                if domain and domain.strip()
            ]

        keycloak_required_actions = watcha_config.get("keycloak_required_actions")
        if keycloak_required_actions is not None:
            if not isinstance(keycloak_required_actions, list) or not all(
                isinstance(action, str) for action in keycloak_required_actions
            ):
                raise ConfigError(
                    "watcha.keycloak_required_actions must be a list of strings"
                )
            self.keycloak_required_actions = keycloak_required_actions
        # +watcha

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

        # watcha+
        cities_by_domain = watcha_config.get("cities_by_domain")
        if isinstance(cities_by_domain, dict):
            self.cities_by_domain = cities_by_domain
            domain_to_city = {}
            for city, domains in cities_by_domain.items():
                if isinstance(domains, str):
                    domains = [domains]
                for domain in domains or []:
                    domain_to_city[domain.lower()] = city
            self.domain_to_city = domain_to_city
        # +watcha

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

          # Whether partner accounts are only created in the Synapse database
          # Optional, defaults to false.
          # Note: The value is ignored when managed_idp is false
          #
          #external_authentication_for_partners: true

          # watcha+
          # Domaines de messagerie de l'organisation. Un utilisateur invité
          # comme partenaire dont l'adresse relève de l'un de ces domaines (ou
          # d'un sous-domaine) est finalement enregistré comme membre de plein
          # droit, aussi bien à l'invitation qu'à l'inscription par SSO.
          # Optional, defaults to none (aucun déclassement).
          #
          #partner_email_whitelist:
          #  - universite-lyon.fr
          #  - access-check.renater.fr

          # Actions imposées par Keycloak à la première connexion d'un compte
          # créé par Synapse. Mettre une liste vide sur les instances dont les
          # comptes proviennent d'une fédération d'identité, où l'utilisateur
          # n'a ni mot de passe ni profil à renseigner côté Keycloak.
          # Optional, defaults to ["UPDATE_PASSWORD", "UPDATE_PROFILE"].
          #
          #keycloak_required_actions: []
          # +watcha

          # Path of the JSON file in which user lifecycle actions (CREATE,
          # DELETE, DEACTIVATE, REACTIVATE) are recorded.
          # Optional, defaults to "watcha_user_audit_log.json" in the data directory.
          #
          #user_audit_log_path: "/path/to/watcha_user_audit_log.json"

          # Path of the JSON file holding the server-wide "message depth"
          # settings (default retention duration and whether room admins may
          # override it per room), editable from the admin console.
          # Optional, defaults to "watcha_retention_config.json" in the data directory.
          #
          #retention_config_path: "/etc/opt/matrix-synapse/watcha_retention_config.json"

          # Path of the JSON file holding the list of file extensions whose
          # upload is rejected, editable from the admin console.
          # Optional, defaults to
          # "/etc/opt/matrix-synapse/blocked_extensions.json".
          #
          #blocked_extensions_path: "/etc/opt/matrix-synapse/blocked_extensions.json"

          # watcha+
          # Mapping ville -> domaines email pour le filtre "par ville" du dashboard
          # Grafana. À renseigner uniquement sur l'instance concernée (ex. sitiv) :
          # si absent, aucune métrique `*_by_city` n'est exposée.
          # Optional, defaults to none.
          #
          #cities_by_domain:
          #  Corbas:        ["ville-corbas.fr"]
          #  Saint-Chamond: ["saint-chamond.fr"]
          #  Vénissieux:    ["ville-venissieux.fr"]
          # +watcha
        """
