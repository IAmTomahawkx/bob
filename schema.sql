CREATE TABLE IF NOT EXISTS reaction_roles
(
    guild_id   BIGINT NOT NULL,
    role_id    BIGINT NOT NULL,
    emoji_id   VARCHAR (32) NOT NULL,
    message_id BIGINT NOT NULL,
    channel_id BIGINT NOT NULL,
    mode       INTEGER NOT NULL,
    UNIQUE (message_id, emoji_id),
    PRIMARY KEY (guild_id, message_id, emoji_id)
);
CREATE TABLE IF NOT EXISTS pages
(
    quick TEXT NOT NULL PRIMARY KEY,
    long  TEXT NOT NULL UNIQUE,
    url   TEXT NOT NULL UNIQUE
);
CREATE TABLE IF NOT EXISTS prefixes
(
    guild_id BIGINT NOT NULL,
    prefix TEXT NOT NULL,
    PRIMARY KEY (guild_id, prefix)
);