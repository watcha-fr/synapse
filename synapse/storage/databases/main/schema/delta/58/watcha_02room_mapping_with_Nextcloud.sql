CREATE TABLE IF NOT EXISTS room_mapping_with_NC (
    room_id TEXT NOT NULL PRIMARY KEY, -- The room ID of the room which initiate a share with Nextcloud.
    directory_path TEXT -- The Nextcloud directory path to share in the room. 
);
