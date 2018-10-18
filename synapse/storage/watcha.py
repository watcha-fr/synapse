import logging

logger = logging.getLogger(__name__)


# =================================================
# Executed at DB init, for DB schema customizations
# =================================================
def check_db_customization(db_conn, database_engine):
    # put here the list of db customizations
    # (database_engine will be used later to for postgres)
    _add_column_if_needed(db_conn, "users", "is_partner", "DEFAULT 0")
    _add_column_if_needed(db_conn, "users", "email", "TEXT")
    _add_column_if_needed(db_conn, "users", "is_deactivated", "DEFAULT 0")
    _add_table_partners_invited_by(db_conn)


def _add_column_if_needed(db_conn, table, column, column_details):
    try:
        cur = db_conn.cursor()
        cur.execute("PRAGMA table_info(%s);" % table)
        if column not in [row[1] for row in cur.fetchall()]:
            cur.execute("ALTER TABLE %s ADD COLUMN %s %s;" % (table, column, column_details))
            logger.info("check_db_customization: column %s added to table %s", column, table)
        else:
            logger.info("check_db_customization: column %s.%s already present", column, table)
    except:
        logger.warn("check_db_customization: could not check %s.%s column", column, table)
        db_conn.rollback()
        raise

# add "partners_invited_by" table
# this is a no-op if it is already there.
def _add_table_partners_invited_by(db_conn):
    try:
        cur = db_conn.cursor()
        cur.execute("PRAGMA table_info(partners_invited_by);")
        has_table = False
        row = cur.fetchone()
        if row:
            logger.info("check_db_customization: table partners_invited_by already exists")
        else:
            logger.info("check_db_customization: table partners_invited_by added")
            cur.execute("CREATE TABLE partners_invited_by (partner TEXT, invited_by TEXT, invitation_ts BIGINT, device_id TEXT, email_sent SMALLINT NOT NULL DEFAULT 0)")

    except:
        logger.warn("check_db_customization: table partners_invited_by could not be created")
        db_conn.rollback()
        raise
