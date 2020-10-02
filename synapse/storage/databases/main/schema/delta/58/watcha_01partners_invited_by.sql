CREATE TABLE IF NOT EXISTS partners_invited_by(
    partner TEXT NOT NULL, -- The user_id created for the partner.
    invited_by TEXT NOT NULL, -- The user_id of the inviter.
    invitation_ts BIGINT NOT NULL,
    device_id TEXT,
    email_sent SMALLINT NOT NULL DEFAULT 0
);