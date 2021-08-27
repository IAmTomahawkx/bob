import asyncpg
import discord
import itertools
import ujson
from discord.ext import commands
from core.bot import Bot
from core import extractor, context, converters, helping
from core.models import *
from core.views import Confirmation


def setup(bot: Bot):
    bot.add_cog(Config(bot))


STEPS = [
    "Parsing configuration file",
    "Removing old configuration (keeping removed counters intact for 24 hours)",
    "Linking static events",
    "Linking static loggers",
    "Linking static counters",
    "Linking static automod",
    "Linking static commands",
    "Updating selfroles",
]


def get_action_args(act: Actions) -> tuple:
    keys = set(act.keys())
    actions = {
        "counter" in keys
        or 0: lambda: (
            ActionTypes.counter,
            act["counter"],
            act["condition"],
            act["modify"],
            act["target"],
            None,
            act.get("args") and ujson.dumps(act["args"]),
        ),
        "do" in keys
        or 2: lambda: (
            ActionTypes.do,
            act["do"],
            act["condition"],
            None,
            None,
            None,
            act.get("args") and ujson.dumps(act["args"]),
        ),
        "log" in keys
        or 3: lambda: (
            ActionTypes.log,
            act["log"],
            act["condition"],
            None,
            None,
            act["event"],
            act.get("args") and ujson.dumps(act["args"]),
        ),
        "dispatch" in keys
        or 4: lambda: (
            ActionTypes.dispatch,
            act["dispatch"],
            act["condition"],
            None,
            None,
            None,
            act.get("args") and ujson.dumps(act["args"]),
        ),
        "reply" in keys
        or 5: lambda: (
            ActionTypes.reply,
            act["reply"],
            act["condition"],
            None,
            None,
            None,
            act.get("args") and ujson.dumps(act["args"]),
        ),
    }

    return actions[True]()  # do as i say, not as i do


class Config(commands.Cog):
    hidden = False
    def __init__(self, bot: Bot):
        self.bot = bot

    async def insert_actions(
        self, conn: asyncpg.Connection, cfg_id: int, data: list, event=False, automod=False, cmd=False
    ) -> list:
        _evens = []
        for _event in data:
            # is this hellish? absolutely. But it works. and honestly i don't see a way around this horrid for loop
            acts = []
            for act in _event["actions"]:
                acts.append(
                    await conn.fetchval(
                        "INSERT INTO actions (type, main_text, condition, modify, target, event, args) VALUES ($1, $2, $3, $4, $5, $6, $7) RETURNING id",
                        *get_action_args(act),
                    )
                )

            if event:
                _evens.append((cfg_id, _event["name"], acts))
            elif cmd:
                _evens.append((cfg_id, _event["name"], acts, _event["help"], _event["group"]))
            elif automod:
                _evens.append((cfg_id, _event["event"], acts, _event["ignore"]["roles"], _event["ignore"]["channels"]))

        return _evens

    async def deploy_config(self, ctx: context.Context, cfg: str):
        content = "Deploying new configuration:\n"
        step = 1

        async def update_msg(err=None, success=False):
            nonlocal ctx, content, step, msg
            _cont = "\n".join(f"{i+1}. {x}" for i, x in enumerate(STEPS) if i < step)
            if err:
                _cont = f"Failed to deploy new configuration:\n{_cont}\nFailed to deploy, here's why:```\n{err}\n```"
            elif success:
                _cont = f"{content}\n{_cont}\nSuccessfully deployed new configuration"
            else:
                _cont = content + _cont

            await msg.edit(content=_cont)

        msg = await ctx.reply(content, mention_author=False)
        try:
            cfg = await extractor.parse_guild_config(cfg, ctx)
        except extractor.ConfigLoadError as e:
            await update_msg(e.msg)
            return

        async with self.bot.db.acquire() as conn:
            async with conn.transaction():
                step += 1
                await update_msg()

                new_id = await conn.fetchval(
                    "INSERT INTO configs (guild_id, store_messages, error_channel, mute_role) VALUES ($1, $2, $3, $4) RETURNING id",
                    ctx.guild.id,
                    any(x in cfg.automod_events for x in ("message_delete", "message_edit")),
                    cfg.error_channel,
                    cfg.mute_role,
                )
                rows = await conn.fetch(
                    "DELETE FROM events "
                    "WHERE $1 = (SELECT guild_id FROM configs WHERE id = events.cfg_id) AND cfg_id != $2 "
                    "RETURNING actions",
                    ctx.guild.id,
                    new_id,
                )
                await conn.execute(
                    "DELETE FROM loggers "
                    "WHERE $1 = (SELECT guild_id FROM configs WHERE id = loggers.cfg_id) AND cfg_id != $2",
                    ctx.guild.id,
                    new_id,
                )

                await conn.execute(
                    "DELETE FROM commands WHERE $1 = (SELECT guild_id FROM configs WHERE configs.id = commands.cfg_id)",
                    ctx.guild.id,
                )

                refed = list(cfg.counters.keys())
                derefed = await conn.fetch(
                    "UPDATE counters "
                    "SET deref_until = (NOW() AT TIME ZONE 'utc' + INTERVAL '24 hours') "
                    "WHERE deref_until IS NULL AND $1 = (SELECT guild_id FROM configs WHERE id = counters.cfg_id) AND name != ANY($2) RETURNING name",
                    ctx.guild.id,
                    refed,
                )
                derefed = {x["name"] for x in derefed}

                await conn.execute(
                    "DELETE FROM actions WHERE id = ANY($1)",
                    list(itertools.chain(x["actions"] for x in rows if x["actions"])),
                )

                step += 1
                await update_msg()

                _evens = await self.insert_actions(conn, new_id, cfg.events, event=True)
                await conn.executemany("INSERT INTO events (cfg_id, name, actions) VALUES ($1, $2, $3)", _evens)

                step += 1
                await update_msg()

                _evens.clear()
                for l in cfg.loggers.values():
                    nid = await conn.fetchval(
                        "INSERT INTO loggers (cfg_id, name, channel) VALUES ($1, $2, $3) RETURNING id",
                        new_id,
                        l["name"],
                        l["channel"],
                    )
                    if not isinstance(l["format"], dict):
                        l["format"] = {"_": l["format"]}
                    _evens += [(nid, x[0], x[1]) for x in l["format"].items()]

                await conn.executemany("INSERT INTO logger_formats VALUES ($1, $2, $3)", _evens)

                step += 1
                await update_msg()

                await conn.execute(
                    "UPDATE counters SET cfg_id = $1 WHERE deref_until IS NOT NULL AND $2 = (select guild_id FROM configs WHERE id = counters.cfg_id)",
                    new_id,
                    ctx.guild.id,
                )
                await conn.executemany(
                    "INSERT INTO counters (cfg_id, start, per_user, name, decay_rate, decay_per) VALUES ($1, $2, $3, $4, $5, $6)",
                    [
                        (new_id, x["initial_count"], x["per_user"], x["name"], x["decay_rate"], x["decay_per"])
                        for x in cfg.counters.values()
                        if x["name"] not in derefed
                    ],
                )

                step += 1
                await update_msg()

                _evens = await self.insert_actions(conn, new_id, list(cfg.automod_events.values()), automod=True)
                await conn.executemany(
                    """
                    WITH ins AS (INSERT INTO automod (cfg_id, event, actions) VALUES ($1, $2, $3) RETURNING id)
                    INSERT INTO automod_ignore VALUES ((select id FROM ins), $4, $5)
                    """,
                    _evens,
                )

                step += 1
                await update_msg()

                for cmd, data in cfg.commands.items():
                    _evens = await self.insert_actions(conn, new_id, [data], cmd=True)
                    cid = await conn.fetchval(
                        "INSERT INTO commands (cfg_id, name, actions, help, permission_group) VALUES ($1, $2, $3, $4, $5) RETURNING id",
                        *_evens[0],
                    )
                    await conn.executemany(
                        "INSERT INTO command_arguments (command_id, name, type, optional) VALUES ($1, $2, $3, $4)",
                        [(cid, x["name"], str(x["type"].name), x["optional"]) for x in data["arguments"]]  # noqa
                        or [(cid, "", "", False)],
                    )

                step += 1
                await update_msg()
                selfroles = self.bot.get_cog("Self Roles")
                if not selfroles and cfg.selfroles:
                    await update_msg("Failed to update selfroles: Extension not found")
                    raise RuntimeError  # break the transaction

                if cfg.selfroles:
                    try:
                        await selfroles.config_hook(cfg, conn)  # noqa
                    except extractor.ConfigLoadError as e:
                        await update_msg(e.msg)
                        raise RuntimeError

                await update_msg(success=True)

            dispatcher = self.bot.get_cog("Dispatch")
            if not dispatcher:
                return

            await dispatcher.invalidate_cache_for(ctx.guild.id, conn)  # noqa

    @commands.command("update-config", aliases=["deploy-config"], usage=[helping.ConfigFile("Config File", False)], extras={"checks": [helping.CheckAdmin()]})
    @commands.has_guild_permissions(administrator=True)
    async def update_config(self, ctx: context.Context, *, config: converters.ConfigFileConverter = None):
        if not config and not ctx.message.attachments:
            return await ctx.reply("You have not provided a configuration file", mention_author=False)

        if config and ctx.message.attachments:
            return await ctx.reply("Please provide either a file or text, not both", mention_author=False)

        if ctx.message.attachments:
            try:
                config = (await ctx.message.attachments[0].read()).decode(encoding="utf8")
            except:  # noqa
                return await ctx.reply("Could not download the configuration file provided", mention_author=False)

        try:
            await self.deploy_config(ctx, config)
        except RuntimeError:
            pass

    @commands.command("clear-config", extras={"checks": [helping.CheckAdmin()]})
    @commands.has_guild_permissions(administrator=True)
    async def clear_config(self, ctx: context.Context):
        """
        Deploys
        :param ctx:
        :return:
        """
        conf = Confirmation([ctx.author.id])
        rsp: discord.Message = await ctx.reply(
            "Are you sure you want to completely clear the configuration?", view=conf, mention_author=False
        )
        await conf.wait()
        await rsp.edit(view=conf)

        if not conf.response:
            await rsp.reply("Cancelling", mention_author=False)
        else:
            await ctx.trigger_typing()
            async with self.bot.db.acquire() as conn:
                rows = await conn.fetch(
                    "DELETE FROM events "
                    "WHERE $1 = (SELECT guild_id FROM configs WHERE id = events.cfg_id)"
                    "RETURNING actions",
                    ctx.guild.id,
                )
                await conn.execute(
                    "DELETE FROM loggers WHERE $1 = (SELECT guild_id FROM configs WHERE id = loggers.cfg_id)",
                    ctx.guild.id,
                )

                await conn.execute(
                    "UPDATE counters "
                    "SET deref_until = (NOW() AT TIME ZONE 'utc' + INTERVAL '24 hours') "
                    "WHERE deref_until IS NULL AND $1 = (SELECT guild_id FROM configs WHERE id = counters.cfg_id)",
                    ctx.guild.id,
                )

                await conn.execute(
                    "DELETE FROM actions WHERE id = ANY($1)",
                    list(itertools.chain(x["actions"] for x in rows if x["actions"])),
                )

                await conn.execute(
                    "DELETE FROM automod WHERE $1 = (SELECT guild_id FROM configs WHERE id = automod.cfg_id)",
                    ctx.guild.id,
                )

            dispatch = self.bot.get_cog("Dispatch")
            if dispatch:
                dispatch.remove_cache_for(ctx.guild.id)  # noqa

            await ctx.send("Successfully cleared configuration")
