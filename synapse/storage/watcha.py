import logging

logger = logging.getLogger(__name__)


# =================================================
# Executed at DB init, for DB schema customizations
# =================================================
def check_db_customization(db_conn, database_engine):
    # put here the list of db customizations
    # (database_engine will be used later to for postgres)
    create_table_partner_invited_by_query = "CREATE TABLE partners_invited_by (partner TEXT, invited_by TEXT, invitation_ts BIGINT, device_id TEXT, email_sent SMALLINT NOT NULL DEFAULT 0)"
    create_table_room_mapping_with_NC_query = "CREATE TABLE room_mapping_with_NC (room_id TEXT NOT NULL PRIMARY KEY, link_URL TEXT)"
    _drop_column_if_needed(db_conn, "users", "users_copy", "email")
    _add_column_if_needed(db_conn, "users", "is_partner", "DEFAULT 0")
    _add_column_if_needed(db_conn, "users", "is_active", "DEFAULT 1")
    _add_new_table_if_needed(db_conn, "partners_invited_by", create_table_partner_invited_by_query)
    _add_new_table_if_needed(db_conn, "room_mapping_with_NC", create_table_room_mapping_with_NC_query)


def _add_column_if_needed(db_conn, table, column, column_details):
    try:
        cur = db_conn.cursor()
        cur.execute("PRAGMA table_info(%s);" % table)
        if column not in [row[1] for row in cur.fetchall()]:
            cur.execute(
                "ALTER TABLE %s ADD COLUMN %s %s;" % (table, column, column_details)
            )
            logger.info(
                "check_db_customization: column %s added to table %s", column, table
            )
        else:
            logger.info(
                "check_db_customization: column %s.%s already present", column, table
            )
    except:
        logger.warn(
            "check_db_customization: could not check %s.%s column", column, table
        )
        db_conn.rollback()
        raise

def _drop_column_if_needed(db_conn, table, copy_table, column_to_drop):
    """ WARNING : if the table has default string value, PLEASE TEST as it may remove this default value."""

    try:
        cursor = db_conn.cursor()
        cursor.execute("PRAGMA table_info({});".format(table))
        columns = {
            row[1]: " ".join(
                [
                    row[1],
                    row[2],
                    "DEFAULT " + row[4] if row[4] else "",
                    "NOT NULL" if row[3] else "",
                    "PRIMARY KEY" if row[5] else "",
                ]
            )
            for row in cursor.fetchall()
        }

        if column_to_drop not in columns:
            logger.info(
                "check_db_customization: column %s. Already dropped from %s",
                column_to_drop,
                table,
            )
            return

        del columns[column_to_drop]

        sql_script = """
            BEGIN TRANSACTION;
            CREATE TABLE IF NOT EXISTS {new_table} (
                {columns_definition}
            , UNIQUE(name));
            INSERT INTO {new_table}({columns_name})
            SELECT {columns_name}
            FROM users;
            DROP TABLE {old_table};
            ALTER TABLE {new_table} RENAME TO {old_table};
        """.format(
            new_table=copy_table, columns_definition=",".join(columns.values()), columns_name=", ".join(columns.keys()), old_table=table
        )

        for line in sql_script.split(";"):
            cursor.execute(line)

        db_conn.commit()

        logger.info(
            "check_db_customization: column %s dropped to table %s",
            column_to_drop,
            table,
        )
    except:
        logger.warn(
            "check_db_customization: could not check %s.%s column",
            column_to_drop,
            table,
        )
        db_conn.rollback()
        raise

# add "partners_invited_by" table
# this is a no-op if it is already there.
def _add_new_table_if_needed(db_conn, table, create_table_query):
    try:
        cur = db_conn.cursor()
        cur.execute("PRAGMA table_info({});".format(table))
        has_table = False
        row = cur.fetchone()
        if row:
            logger.info("check_db_customization: table %s already exists" % table)
        else:
            logger.info("check_db_customization: table %s added" % table)
            cur.execute(create_table_query)

    except:
        logger.warn("check_db_customization: table %s could not be created" % table)
        db_conn.rollback()
        raise
