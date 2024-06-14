CREATE TABLE IF NOT EXISTS watcha_nextcloud_shares (
    room_id TEXT NOT NULL PRIMARY KEY,
    share_id INTEGER
);

INSERT INTO watcha_nextcloud_shares
SELECT DISTINCT
    room_id,
    share_id
FROM room_nextcloud_mapping;

DROP TABLE room_nextcloud_mapping;