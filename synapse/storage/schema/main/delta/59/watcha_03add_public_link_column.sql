CREATE TABLE IF NOT EXISTS new_watcha_nextcloud_shares (
    room_id TEXT NOT NULL PRIMARY KEY,
    internal_share_id INTEGER,
    public_link_share_id INTEGER
);

INSERT INTO new_watcha_nextcloud_shares(
    room_id,
    internal_share_id
)
SELECT
    room_id,
    share_id
FROM watcha_nextcloud_shares;

DROP TABLE watcha_nextcloud_shares;

ALTER TABLE new_watcha_nextcloud_shares RENAME TO watcha_nextcloud_shares;

CREATE INDEX IF NOT EXISTS watcha_nextcloud_shares_room_id ON watcha_nextcloud_shares (room_id);
