import logging

logger = logging.getLogger(__name__)


# =================================================
# Executed at DB init, for DB schema customizations
# =================================================
def check_db_customization(db_conn, database_engine):
    # put here the list of db customizations
    _add_is_partner(db_conn, database_engine)
    _add_table_partners_invited_by(db_conn, database_engine)

# add "is_partner" column to the users table.
# this is a no-op if it is already there.
def _add_is_partner(db_conn, database_engine):
    try:
        cur = db_conn.cursor()
        cur.execute("PRAGMA table_info(users);")
        has_is_partner = False
        while True:
            row = cur.fetchone()
            if not row:
                break
            else:
                #logger.info("check_db_customization: users column=" + str(row))
                if (row[1] == "is_partner"):
                    #logger.info("is_partner found")
                    has_is_partner = True

        if not has_is_partner:
            logger.info("check_db_customization: column is_partner added to table users")
            cur.execute("ALTER TABLE users ADD COLUMN is_partner DEFAULT 0;")
        else:
            logger.info("check_db_customization: column is_partner is already in table users")

    except:
        logger.warn("check_db_customization: could not check is_partner column")
        db_conn.rollback()
        raise

# add "partners_invited_by" table
# this is a no-op if it is already there.
def _add_table_partners_invited_by(db_conn, database_engine):
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
