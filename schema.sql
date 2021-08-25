CREATE OR REPLACE FUNCTION
    remove_guild_data(guildid bigint, rmactions int[])
RETURNS VOID
LANGUAGE plpgsql
as
$$
    DECLARE
        cfgid int;
    BEGIN
        SELECT id
        INTO cfgid
        FROM configs
        WHERE configs.guild_id = guildid;

        DELETE FROM actions WHERE id = ANY(rmactions);
        DELETE FROM automod WHERE cfg_id = cfgid;
        DELETE FROM events WHERE cfg_id = cfgid;
        DELETE FROM counters WHERE cfg_id = cfgid;
        DELETE FROM loggers WHERE cfg_id = cfgid;
        DELETE FROM commands WHERE cfg_id = cfgid;
        DELETE FROM messages WHERE guild_id = guildid;
        DELETE FROM mutes WHERE guild_id = guildid;
        DELETE FROM prefixes WHERE guild_id = guildid;
        DELETE FROM selfroles WHERE guild_id = guildid;
        DELETE FROM cases WHERE guild_id = guildid;
    END;
$$;

CREATE TABLE IF NOT EXISTS pages
(
    quick TEXT NOT NULL PRIMARY KEY,
    long  TEXT NOT NULL UNIQUE,
    url   TEXT NOT NULL UNIQUE
);
CREATE TABLE IF NOT EXISTS dispatchers
(
    id SERIAL PRIMARY KEY,
    dispatch_at TIMESTAMP WITHOUT TIME ZONE NOT NULL,
    event TEXT NOT NULL,
    data JSONB NOT NULL
);
CREATE TABLE IF NOT EXISTS configs
(
    id SERIAL PRIMARY KEY,
    guild_id BIGINT NOT NULL,
    store_messages BOOL NOT NULL,
    error_channel BIGINT NOT NULL,
    mute_role BIGINT
);
CREATE TABLE IF NOT EXISTS counters
(
    id SERIAL PRIMARY KEY,
    cfg_id INTEGER NOT NULL REFERENCES configs(id) ON DELETE CASCADE,
    deref_until TIMESTAMP,
    start INTEGER,
    per_user BOOLEAN NOT NULL DEFAULT FALSE,
    name TEXT NOT NULL,
    decay_rate INTEGER,
    decay_per INTEGER
);
CREATE TABLE IF NOT EXISTS counter_values
(
    counter_id INT NOT NULL REFERENCES counters(id),
    val INTEGER NOT NULL DEFAULT 0,
    last_decay TIMESTAMP NOT NULL,
    user_id BIGINT,
    UNIQUE (counter_id, user_id)
);
CREATE TABLE IF NOT EXISTS loggers
(
    id SERIAL PRIMARY KEY,
    cfg_id INTEGER NOT NULL REFERENCES configs(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    channel BIGINT NOT NULL
);
CREATE TABLE IF NOT EXISTS logger_formats
(
    logger_id INTEGER NOT NULL REFERENCES loggers(id) ON DELETE CASCADE,
    format_name VARCHAR(32) NOT NULL,
    response TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS events
(
    id SERIAL PRIMARY KEY,
    cfg_id INTEGER NOT NULL REFERENCES configs(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    actions INTEGER[] NOT NULL
);
CREATE TABLE IF NOT EXISTS commands
(
    id SERIAL PRIMARY KEY,
    cfg_id INTEGER NOT NULL REFERENCES configs(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    UNIQUE(cfg_id, name),
    actions INTEGER[] NOT NULL,
    help TEXT,
    permission_group TEXT
);
CREATE TABLE IF NOT EXISTS command_arguments
(
    id SERIAL,
    command_id INTEGER NOT NULL REFERENCES commands(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    type TEXT NOT NULL,
    optional BOOL NOT NULL DEFAULT FALSE
);
CREATE TABLE IF NOT EXISTS automod
(
    id SERIAL PRIMARY KEY,
    event TEXT NOT NULL,
    cfg_id INTEGER NOT NULL REFERENCES configs(id) ON DELETE CASCADE,
    actions INTEGER[] NOT NULL
);
CREATE TABLE IF NOT EXISTS automod_ignore
(
    event_id INTEGER NOT NULL REFERENCES automod(id) ON DELETE CASCADE,
    roles BIGINT[] NOT NULL,
    channels BIGINT[] NOT NULL
);
CREATE TABLE IF NOT EXISTS actions
(
    id SERIAL PRIMARY KEY,
    type INTEGER NOT NULL,
    main_text TEXT NOT NULL,
    condition TEXT,
    modify INTEGER,
    target TEXT,
    event TEXT,
    args JSONB
);
CREATE TABLE IF NOT EXISTS messages
(
    guild_id BIGINT NOT NULL,
    message_id BIGINT NOT NULL,
    PRIMARY KEY (guild_id, message_id),
    author_id BIGINT NOT NULL,
    channel_id BIGINT NOT NULL,
    content TEXT NOT NULL,
    image_urls TEXT[]
);
CREATE TABLE IF NOT EXISTS prefixes
(
    guild_id BIGINT NOT NULL,
    prefix TEXT NOT NULL,
    PRIMARY KEY (guild_id, prefix)
);
CREATE TABLE IF NOT EXISTS cases
(
    guild_id BIGINT NOT NULL,
    id INT NOT NULL,
    user_id BIGINT NOT NULL,
    mod_id BIGINT NOT NULL,
    action TEXT NOT NULL,
    reason TEXT,
    link TEXT
);
CREATE TABLE IF NOT EXISTS mutes
(
    guild_id BIGINT NOT NULL,
    user_id BIGINT NOT NULL,
    PRIMARY KEY (guild_id, user_id),
    dispatch_id INT
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
    interaction_cid TEXT,
    reaction TEXT
);
CREATE TABLE IF NOT EXISTS persist_roles
(
    guild_id BIGINT NOT NULL,
    user_id BIGINT NOT NULL,
    role_id BIGINT NOT NULL,
    PRIMARY KEY (guild_id, user_id, role_id)
)