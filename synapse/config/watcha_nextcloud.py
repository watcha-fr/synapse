from ._base import Config

DEFAULT_CONFIG = """
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
#nextcloud:
#   keycloak_serveur: "https://example.com/auth"
#   keycloak_realm: "example.com"
#   nextcloud_server: "https://example.com/nextcloud"
#   nextcloud_shared_secret: "YOUR_SHARED_SECRET"
#   service_account_name: "example_account_service"
#   service_account_password: "YOUR_SHARED_SECRET"
"""


class NextcloudIntegrationConfig(Config):

    section = "nextcloudintegration"

    def __init__(self, *args):
        super(NextcloudIntegrationConfig, self).__init__(*args)

        self.keycloak_serveur = None
        self.keycloak_realm = None
        self.nextcloud_server = None
        self.nextcloud_shared_secret = None
        self.service_account_name = None
        self.service_account_password = None

    def read_config(self, config, **kwargs):
        nextcloud_config = config.get("nextcloud", {})
        self.keycloak_serveur = nextcloud_config.get("keycloak_serveur")
        self.keycloak_realm = nextcloud_config.get("keycloak_realm")
        self.nextcloud_server = nextcloud_config.get("nextcloud_server")
        self.nextcloud_shared_secret = nextcloud_config.get(
            "nextcloud_shared_secret"
        )
        self.service_account_name = nextcloud_config.get(
            "service_account_name"
        )
        self.service_account_password = nextcloud_config.get(
            "service_account_password"
        )

    def generate_config_section(self, config_dir_path, server_name, **kwargs):
        return DEFAULT_CONFIG
