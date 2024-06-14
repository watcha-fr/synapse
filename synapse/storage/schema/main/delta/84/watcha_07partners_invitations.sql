CREATE TABLE IF NOT EXISTS partners_invitations (
    user_id TEXT NOT NULL,
    invited_by TEXT, -- The user_id of the sender.
    CONSTRAINT partners_invitations_uniqueness UNIQUE (user_id, invited_by)
);

INSERT INTO partners_invitations
SELECT DISTINCT
    partner,
    invited_by
FROM partners_invited_by;

DROP TABLE partners_invited_by;