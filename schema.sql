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
CREATE TABLE IF NOT EXISTS selfroles
(
    id SERIAL PRIMARY KEY,
    mode INTEGER NOT NULL,
    guild_id BIGINT NOT NULL,
    optin BOOLEAN NOT NULL DEFAULT TRUE,
    optout BOOLEAN NOT NULL DEFAULT TRUE
);
CREATE TABLE IF NOT EXISTS selfroles_roles
(
    cfg_id INT PRIMARY KEY REFERENCES selfroles(id) ON DELETE CASCADE,
    role_id BIGINT NOT NULL,
    msg_id BIGINT,
    channel_id BIGINT,
    interaction_cid TEXT
);