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
    """Dropping is_partner column from users table."""

    if isinstance(database_engine, PostgresEngine):
        return

    cur.execute(
        """UPDATE users SET user_type = "watcha_external" WHERE is_partner == 1;"""
    )

    cur.execute(
        """CREATE TABLE users2(
            name TEXT,
            password_hash TEXT,
            creation_ts BIGINT,
            admin SMALLINT DEFAULT 0 NOT NULL, 
            upgrade_ts BIGINT, 
            is_guest SMALLINT DEFAULT 0 NOT NULL, 
            appservice_id TEXT, 
            consent_version TEXT, 
            consent_server_notice_sent TEXT, 
            user_type TEXT DEFAULT NULL, 
            deactivated SMALLINT DEFAULT 0 NOT NULL, 
            shadow_banned BOOLEAN, 
            UNIQUE(name)
        );"""
    )

    cur.execute(
        """INSERT INTO users2(name, password_hash, creation_ts, admin, upgrade_ts, is_guest, appservice_id, consent_version, consent_server_notice_sent, user_type, deactivated, shadow_banned)
        SELECT name, password_hash, creation_ts, admin, upgrade_ts, is_guest, appservice_id, consent_version, consent_server_notice_sent, user_type, deactivated, shadow_banned FROM users;"""
    )

    cur.execute("""DROP TABLE users;""")

    cur.execute("""ALTER TABLE users2 RENAME TO users;""")

    cur.execute("""CREATE INDEX users_creation_ts ON users (creation_ts);""")
