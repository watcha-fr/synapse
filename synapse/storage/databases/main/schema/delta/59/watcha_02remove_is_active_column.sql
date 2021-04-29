CREATE TABLE IF NOT EXISTS new_users(
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
    is_partner SMALLINT DEFAULT 0 NOT NULL,
    UNIQUE(name) 
);

INSERT INTO new_users (
    name,
    password_hash, 
    creation_ts, 
    admin, 
    upgrade_ts, 
    is_guest, 
    appservice_id, 
    consent_version, 
    consent_server_notice_sent, 
    user_type, 
    deactivated, 
    shadow_banned, 
    is_partner
)
SELECT
    name,
    password_hash, 
    creation_ts, 
    admin, 
    upgrade_ts, 
    is_guest, 
    appservice_id, 
    consent_version, 
    consent_server_notice_sent, 
    user_type, 
    deactivated, 
    shadow_banned, 
    is_partner
FROM users;

DROP TABLE users;

ALTER TABLE new_users RENAME TO users;
