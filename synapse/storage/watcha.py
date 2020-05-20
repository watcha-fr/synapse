import logging

logger = logging.getLogger(__name__)


# =================================================
# Executed at DB init, for DB schema customizations
# =================================================
def check_db_customization(db_conn, database_engine):
    # put here the list of db customizations
    # (database_engine will be used later to for postgres)
    _drop_column_if_needed(db_conn, "users", "email", "TEXT")
    _add_column_if_needed(db_conn, "users", "is_partner", "DEFAULT 0")
    _add_column_if_needed(db_conn, "users", "is_active", "DEFAULT 1")
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

def _drop_column_if_needed(db_conn, table, column_to_drop, column_details):
    try:
        cur = db_conn.cursor()
        cur.execute("PRAGMA table_info(%s);" % table)
        columns = [ {"column_name": row[1], "type": row[2], "dflt_value": "DEFAULT "+row[4] if row[4] else "", "notnull": "NOT NULL" if row[3] else "", "pk": "PRIMARY KEY" if row[5] else ""} for row in cur.fetchall()]
        all_columns_name = [column["column_name"] for column in columns]

        if column_to_drop in all_columns_name:
            columns = [column for column in columns if column["column_name"] != column_to_drop]
            all_columns_name.remove(column_to_drop)

            sql_create_table_query = """CREATE TABLE IF NOT EXISTS users_copy (
                    %s
                , UNIQUE(name));""" % ",".join([" ".join(dict.values(column)) for column in columns])

            sql_copy_table_query = """INSERT INTO users_copy(%s)
                SELECT %s
                FROM users;""" % (", ".join(all_columns_name), ", ".join(all_columns_name))

            cur.execute("BEGIN TRANSACTION;")
            cur.execute(sql_create_table_query)
            cur.execute(sql_copy_table_query)
            cur.execute("DROP TABLE users;")
            cur.execute("ALTER TABLE users_copy RENAME TO users;")
            db_conn.commit()
            logger.info("check_db_customization: column %s dropped to table %s", column_to_drop, table)
        else:
            logger.info("check_db_customization: column %s. Already dropped from %s", column_to_drop, table)
    except:
        logger.warn("check_db_customization: could not check %s.%s column", column_to_drop, table)
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
