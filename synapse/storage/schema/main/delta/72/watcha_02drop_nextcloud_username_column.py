import synapse.config.homeserver
import synapse.storage.engines
import synapse.storage.types
from synapse.storage.engines import PostgresEngine


def run_create(
    cur: synapse.storage.types.Cursor,
    database_engine: synapse.storage.engines.BaseDatabaseEngine,
) -> None:
    pass


def run_upgrade(
    cur: synapse.storage.types.Cursor,
    database_engine: synapse.storage.engines.BaseDatabaseEngine,
    config: synapse.config.homeserver.HomeServerConfig,
) -> None:
    """Dropping nextcloud_username column from user_external_ids table."""

    if isinstance(database_engine, PostgresEngine):
        return

    cur.execute(
        """INSERT INTO user_external_ids (auth_provider, external_id, user_id)
            SELECT "nextcloud",	nextcloud_username, user_id FROM user_external_ids WHERE nextcloud_username IS NOT NULL;"""
    )

    cur.execute(
        """CREATE TABLE user_external_ids2(
            auth_provider TEXT NOT NULL,
            external_id TEXT NOT NULL,
            user_id TEXT NOT NULL,
            UNIQUE (auth_provider, external_id)
        );"""
    )

    cur.execute(
        """INSERT INTO user_external_ids2(auth_provider, external_id, user_id)
            SELECT auth_provider, external_id, user_id FROM user_external_ids;"""
    )

    cur.execute("""DROP TABLE user_external_ids;""")

    cur.execute("""ALTER TABLE user_external_ids2 RENAME TO user_external_ids;""")

    cur.execute("""CREATE INDEX user_external_ids_user_id_idx ON user_external_ids (user_id);""")
