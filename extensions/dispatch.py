import asyncio
import asyncpg
import discord
import itertools
from typing import Dict, Union

from discord.ext import commands
from core.bot import Bot
from core import parse


def setup(bot: Bot):
    bot.add_cog(Dispatch(bot))


class Dispatch(commands.Cog):
    def __init__(self, bot: Bot):
        self.bot = bot
        self.cached_triggers = {}
        self.ctx_cache = {}
        self.filled = asyncio.Event()
        bot.loop.create_task(self.fill_triggers())

    async def fill_triggers(self):
        if self.filled.is_set():
            return

        data = await self.bot.db.fetch(
            """
            SELECT
                name, actions, c.guild_id, cfg_id, c.store_messages, c.error_channel
            FROM events
            INNER JOIN configs c on c.id = events.cfg_id
            """
        )
        self.cached_triggers["configs"] = {
            x["guild_id"]: {
                "id": x["cfg_id"],
                "store_messages": x["store_messages"],
                "error_channel": x["error_channel"],
            }
            for x in data
        }
        guilds = itertools.groupby(data, lambda k: k["guild_id"])
        self.cached_triggers["events"] = {
            x[0]: {c["name"]: {"name": c["name"], "actions": c["actions"]} for c in x[1]} for x in guilds
        }

        data = await self.bot.db.fetch(
            """
            SELECT
                event, actions, ai.roles as ignore_roles, ai.channels as ignore_channels, c.guild_id
            FROM automod
            INNER JOIN automod_ignore ai on automod.id = ai.event_id
            INNER JOIN configs c on automod.cfg_id = c.id
            """
        )
        guilds = itertools.groupby(data, lambda k: k["guild_id"])
        self.cached_triggers["automod"] = {c[0]: {x["event"]: dict(x) for x in c[1]} for c in guilds}

        self.filled.set()

    def remove_cache_for(self, guild_id: int):
        if guild_id in self.cached_triggers["configs"]:
            del self.cached_triggers["configs"][guild_id]
            del self.cached_triggers["events"][guild_id]
            del self.cached_triggers["automod"][guild_id]

        if guild_id in self.ctx_cache:
            del self.ctx_cache[guild_id]

    async def invalidate_cache_for(self, guild_id: int, conn: asyncpg.Connection):
        await self.filled.wait()
        self.filled.clear()
        if guild_id in self.cached_triggers["configs"]:
            del self.cached_triggers["configs"][guild_id]
            del self.cached_triggers["events"][guild_id]
            del self.cached_triggers["automod"][guild_id]

        if guild_id in self.ctx_cache:
            del self.ctx_cache[guild_id]

        data = await conn.fetch(
            """
            SELECT
                name, actions, c.guild_id, cfg_id, c.store_messages, c.error_channel
            FROM events
            INNER JOIN configs c on c.id = events.cfg_id
            WHERE c.id = (SELECT MAX(id) FROM configs WHERE configs.guild_id = $1)
            """,
            guild_id,
        )
        self.cached_triggers["configs"][guild_id] = {
            "id": data[0]["cfg_id"],
            "store_messages": data[0]["store_messages"],
            "error_channel": data[0]["error_channel"],
        }
        self.cached_triggers["events"][guild_id] = {
            c["name"]: {"name": c["name"], "actions": c["actions"]} for c in data
        }

        data = await conn.fetch(
            """
            SELECT
                event, actions, ai.roles as ignore_roles, ai.channels as ignore_channels, c.guild_id
            FROM automod
            INNER JOIN automod_ignore ai on automod.id = ai.event_id
            INNER JOIN configs c on automod.cfg_id = c.id
            WHERE c.id = (SELECT MAX(id) FROM configs WHERE configs.guild_id = $1)
            """,
            guild_id,
        )
        self.cached_triggers["automod"][guild_id] = {x["event"]: dict(x) for x in data}

        self.filled.set()

    async def fire_event_dispatch(
        self,
        event: dict,
        guild: discord.Guild,
        kwargs: Dict[str, Union[str, int, bool]],
        conn: asyncpg.Connection,
        message: discord.Message = None,
    ):
        if guild.id in self.ctx_cache:
            ctx = self.ctx_cache[guild.id]
        else:
            ctx = self.ctx_cache[guild.id] = parse.ParsingContext(self.bot, guild)

        print(event)
        kwargs["__callerid__"] = self.bot.user.id

        try:
            await ctx.run_automod(event, conn, None, kwargs, messageable=message.channel)
        except parse.ExecutionInterrupt as e:
            g = guild.get_channel(self.cached_triggers["configs"][guild.id]["error_channel"])
            if g:  # drop it silently if it got deleted
                try:
                    await g.send(str(e))
                except discord.HTTPException:
                    pass

    # XXX dispatch firing mechanisms

    @commands.Cog.listener()
    async def on_mute_complete(self, guild_id: int, user_id: int):
        await self.bot.wait_until_ready()
        await self.filled.wait()

        guild = self.bot.get_guild(guild_id)
        if not guild:  # we've left the guild
            return

        member: discord.Member = guild.get_member(user_id)
        if guild_id in self.ctx_cache:
            ctx = self.ctx_cache[guild_id]
        else:
            ctx = self.ctx_cache[guild.id] = parse.ParsingContext(self.bot, guild)

        await ctx.fetch_required_data()

        mute_role = guild.get_role(ctx.mute_role)

        if member and mute_role:
            try:
                await member.remove_roles(mute_role)
            except discord.HTTPException as e:
                g = guild.get_channel(self.cached_triggers["configs"][guild.id]["error_channel"])
                try:
                    await g.send(f"Failed to unmute {member}:\n{e.text}")
                except discord.HTTPException:
                    pass

        if "unmute" in self.cached_triggers["automod"][guild_id]:
            vbls = {
                "userid": user_id,
                "username": str(member),
                "usernick": member.nick,
                "modname": str(self.bot.user),
                "modid": self.bot.user.id,
                "reason": "Timed mute expired",
            }
            async with self.bot.db.acquire() as conn:
                try:
                    await ctx.run_automod(self.cached_triggers["automod"][guild_id]["unmute"], conn, vbls=vbls)
                except parse.ExecutionInterrupt as e:
                    g = guild.get_channel(self.cached_triggers["configs"][guild.id]["error_channel"])
                    if g:  # drop it silently if it got deleted
                        try:
                            await g.send(str(e))
                        except discord.HTTPException:
                            pass

    @commands.Cog.listener()
    async def on_ban_complete(self, guild_id: int, user_id: int):
        await self.bot.wait_until_ready()
        await self.filled.wait()

        guild = self.bot.get_guild(guild_id)
        if not guild:  # we've left the guild
            return

        try:
            await guild.unban(discord.Object(id=user_id))
        except discord.HTTPException:
            pass  # member unbanned already
        else:
            if guild_id in self.ctx_cache:
                ctx = self.ctx_cache[guild_id]
            else:
                ctx = self.ctx_cache[guild.id] = parse.ParsingContext(self.bot, guild)

            await ctx.fetch_required_data()

            if "unban" in self.cached_triggers["automod"][guild_id]:
                vbls = {
                    "userid": user_id,
                    "usercreatedat": discord.utils.snowflake_time(user_id).isoformat(),
                    "reason": "Timed ban expired",
                    "moderator": str(self.bot.user),
                    "moderatorid": self.bot.user.id,
                }
                async with self.bot.db.acquire() as conn:
                    try:
                        await ctx.run_automod(self.cached_triggers["automod"][guild_id]["unban"], conn, vbls=vbls)
                    except parse.ExecutionInterrupt as e:
                        g = guild.get_channel(self.cached_triggers["configs"][guild.id]["error_channel"])
                        if g:  # drop it silently if it got deleted
                            try:
                                await g.send(str(e))
                            except discord.HTTPException:
                                pass

    # XXX discord dispatches

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild or message.guild.id not in self.cached_triggers["automod"]:
            return

        await self.filled.wait()
        if "message" in self.cached_triggers["automod"][message.guild.id]:
            even = {
                "content": message.content,
                "authorid": message.author.id,
                "authorname": str(message.author),
                "authornick": message.author.nick,
                "channelid": message.channel.id,
                "channelname": message.channel.name,
                "messageid": message.id,
                "messagelink": message.jump_url,
            }
            async with self.bot.db.acquire() as conn:
                await conn.execute(
                    "INSERT INTO messages VALUES ($1, $2, $3, $4, $5, $6)",
                    message.guild.id,
                    message.id,
                    message.author.id,
                    message.channel.id,
                    message.content,
                    [x.proxy_url for x in message.attachments],
                )
                await self.fire_event_dispatch(
                    self.cached_triggers["automod"][message.guild.id]["message"],
                    message.guild,
                    even,
                    conn=conn,
                    message=message,  # noqa
                )

    @commands.Cog.listener()
    async def on_raw_message_delete(self, payload: discord.RawMessageDeleteEvent):
        if not payload.guild_id:
            return
        if payload.guild_id not in self.cached_triggers["automod"]:
            return

        await self.filled.wait()
        if "message_delete" in self.cached_triggers["automod"][payload.guild_id]:
            async with self.bot.db.acquire() as conn:
                data = await conn.fetchrow(
                    "DELETE FROM messages WHERE guild_id = $1 AND message_id = $2 RETURNING *",
                    payload.guild_id,
                    payload.message_id,
                )
                guild = self.bot.get_guild(payload.guild_id)
                author = guild.get_member(data["author_id"])
                channel = guild.get_channel(data["channel_id"])
                even = {
                    "content": data["content"],
                    "authorid": data["author_id"],
                    "authorname": author and str(author),
                    "authornick": author and author.nick,
                    "channelid": data["channel_id"],
                    "channelname": channel and channel.name,
                    "messageid": data["message_id"],
                }
                await self.fire_event_dispatch(
                    self.cached_triggers["automod"][payload.guild_id]["message_delete"],
                    self.bot.get_guild(payload.guild_id),
                    even,
                    conn=conn,
                )

    @commands.Cog.listener()
    async def on_raw_bulk_message_delete(self, payload: discord.RawBulkMessageDeleteEvent):
        if not payload.guild_id:
            return
        if payload.guild_id not in self.cached_triggers["automod"]:
            return

        await self.filled.wait()
        if "message_edit" in self.cached_triggers["automod"][payload.guild_id]:
            async with self.bot.db.acquire() as conn:
                data = await conn.fetch(
                    "DELETE FROM messages WHERE guild_id = $1 AND message_id = ANY($2) RETURNING *",
                    payload.guild_id,
                    payload.message_ids,
                )
                for x in data:
                    guild = self.bot.get_guild(payload.guild_id)
                    author = guild.get_member(x["author_id"])
                    channel = guild.get_channel(x["channel_id"])
                    even = {
                        "content": x["content"],
                        "authorid": x["author_id"],
                        "authorname": author and str(author),
                        "authornick": author and author.nick,
                        "channelid": x["channel_id"],
                        "channelname": channel and channel.name,
                        "messageid": x["message_id"],
                    }
                    await self.fire_event_dispatch(
                        self.cached_triggers["automod"][payload.guild_id]["message_delete"], guild, even, conn=conn
                    )

    @commands.Cog.listener()
    async def on_raw_message_edit(self, payload: discord.RawMessageUpdateEvent):
        if not payload.guild_id:
            return
        if payload.guild_id not in self.cached_triggers["automod"]:
            return

        await self.filled.wait()
        if (
            payload.cached_message
            and [discord.Embed.from_dict(x) for x in payload.data["embeds"]] != payload.cached_message.embeds
        ):
            return

        if "message_edit" in self.cached_triggers["automod"][payload.guild_id]:
            async with self.bot.db.acquire() as conn:
                data = await conn.fetchrow(
                    "SELECT * FROM messages WHERE guild_id = $1 AND message_id = $2",
                    payload.guild_id,
                    payload.message_id,
                )
                if not data:
                    return

                await conn.execute(
                    "UPDATE messages SET content = $1 WHERE guild_id = $1 AND message_id = $2",
                    payload.data["content"],
                    payload.guild_id,
                    payload.message_id,
                )

                guild = self.bot.get_guild(payload.guild_id)
                author = guild.get_member(data["author_id"])
                channel = guild.get_channel(data["channel_id"])
                even = {
                    "content": payload.data["content"],
                    "prev-content": data["content"],
                    "authorid": data["author_id"],
                    "authorname": str(author),
                    "authornick": author.nick,
                    "channelid": data["channel_id"],
                    "channelname": channel.name,
                    "messageid": data["message_id"],
                }
                await self.fire_event_dispatch(
                    self.cached_triggers["automod"][payload.guild_id]["message_edit"], guild, even, conn=conn
                )

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent):
        if not payload.guild_id:
            return
        if payload.guild_id not in self.cached_triggers["automod"]:
            return

        await self.filled.wait()

        if "reaction_add" in self.cached_triggers["automod"][payload.guild_id]:
            even = {
                "messageid": payload.message_id,
                "channelid": payload.channel_id,
                "userid": payload.user_id,
                "reaction": payload.emoji.name,
            }
            async with self.bot.db.acquire() as conn:
                await self.fire_event_dispatch(
                    self.cached_triggers["automod"][payload.guild_id]["reaction_add"],
                    self.bot.get_guild(payload.guild_id),
                    even,
                    conn=conn,
                )

    @commands.Cog.listener()
    async def on_raw_reaction_remove(self, payload: discord.RawReactionActionEvent):
        if not payload.guild_id:
            return
        if payload.guild_id not in self.cached_triggers["automod"]:
            return

        await self.filled.wait()

        if "reaction_remove" in self.cached_triggers["automod"][payload.guild_id]:
            even = {
                "messageid": payload.message_id,
                "channelid": payload.channel_id,
                "userid": payload.user_id,
                "reaction": payload.emoji.name,
            }
            async with self.bot.db.acquire() as conn:
                await self.fire_event_dispatch(
                    self.cached_triggers["automod"][payload.guild_id]["reaction_remove"],
                    self.bot.get_guild(payload.guild_id),
                    even,
                    conn=conn,
                )

    @commands.Cog.listener()
    async def on_raw_reaction_clear(self, payload: discord.RawReactionClearEvent):
        if not payload.guild_id:
            return
        if payload.guild_id not in self.cached_triggers["automod"]:
            return

        await self.filled.wait()

        if "reaction_all_remove" in self.cached_triggers["automod"][payload.guild_id]:
            even = {"messageid": payload.message_id, "channelid": payload.channel_id, "reaction": None}
            async with self.bot.db.acquire() as conn:
                await self.fire_event_dispatch(
                    self.cached_triggers["automod"][payload.guild_id]["reaction_all_remove"],
                    self.bot.get_guild(payload.guild_id),
                    even,
                    conn=conn,
                )

    @commands.Cog.listener()
    async def on_raw_reaction_emoji_clear(self, payload: discord.RawReactionClearEmojiEvent):
        if not payload.guild_id:
            return
        if payload.guild_id not in self.cached_triggers["automod"]:
            return

        await self.filled.wait()

        if "reaction_all_remove" in self.cached_triggers["automod"][payload.guild_id]:
            even = {"messageid": payload.message_id, "channelid": payload.channel_id, "reaction": payload.emoji.name}
            async with self.bot.db.acquire() as conn:
                await self.fire_event_dispatch(
                    self.cached_triggers["automod"][payload.guild_id]["reaction_all_remove"],
                    self.bot.get_guild(payload.guild_id),
                    even,
                    conn=conn,
                )

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        await self.filled.wait()
        if member.guild.id not in self.cached_triggers["automod"]:
            return

        if "user_join" in self.cached_triggers["automod"][member.guild.id]:
            even = {
                "userid": member.id,
                "username": str(member),
                "userisbot": member.bot,
                "useravatar": member.avatar.with_format("gif").url
                if member.avatar.is_animated()
                else member.avatar.with_format("png").url,
                "usergatepending": member.pending,
                "userstatus": member.status.name,
                "usercreatedat": member.created_at,
                "usernick": member.nick,
            }
            async with self.bot.db.acquire() as conn:
                await self.fire_event_dispatch(
                    self.cached_triggers["automod"][member.guild.id]["user_join"], member.guild, even, conn=conn
                )

    @commands.Cog.listener()
    async def on_member_leave(self, member: discord.Member):
        await self.filled.wait()
        if member.guild.id not in self.cached_triggers["automod"]:
            return

        if "user_leave" in self.cached_triggers["automod"][member.guild.id]:
            even = {
                "userid": member.id,
                "username": str(member),
                "userisbot": member.bot,
                "useravatar": member.avatar.with_format("gif").url
                if member.avatar.is_animated()
                else member.avatar.with_format("png").url,
                "usergatepending": member.pending,
                "usercreatedat": member.created_at,
                "usernick": member.nick,
            }
            async with self.bot.db.acquire() as conn:
                await self.fire_event_dispatch(
                    self.cached_triggers["automod"][member.guild.id]["user_leave"], member.guild, even, conn=conn
                )

    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member):
        await self.filled.wait()
        if before.guild.id not in self.cached_triggers["automod"]:
            return

        if "user_update" in self.cached_triggers["automod"][before.guild.id]:
            even = {
                "userid": before.id,
                "usercreatedat": before.created_at,
                "userisbot": before.bot,
                "busername": str(before),
                "ausername": str(after),
                "buseravatar": before.avatar.with_format("gif").url
                if before.avatar.is_animated()
                else before.avatar.with_format("png").url,
                "auseravatar": after.avatar.with_format("gif").url
                if after.avatar.is_animated()
                else after.avatar.with_format("png").url,
                "busergatepending": before.pending,
                "ausergatepending": after.pending,
                "busernick": before.nick,
                "ausernick": after.nick,
            }
            async with self.bot.db.acquire() as conn:
                await self.fire_event_dispatch(
                    self.cached_triggers["automod"][before.guild.id]["user_leave"], before.guild, even, conn=conn
                )

    @commands.Cog.listener()
    async def on_member_ban(self, guild: discord.Guild, user: discord.User):
        await self.filled.wait()
        if guild.id not in self.cached_triggers["automod"]:
            return

        if "user_ban" in self.cached_triggers["automod"][guild.id]:
            await asyncio.sleep(0.5)

            if guild.me.guild_permissions.view_audit_log:
                async for ban in guild.audit_logs(action=discord.AuditLogAction.ban):  # type: discord.AuditLogEntry
                    if ban.target == user:
                        reason = ban.reason or "No reason provided"
                        moderator = str(ban.user)
                        modid = ban.user.id

                        break

                else:
                    reason = moderator = "<Ban not found>"
                    modid = 0

            else:
                reason = moderator = "<cannot see audit logs>"
                modid = 0

            even = {
                "userid": user.id,
                "usercreatedat": user.created_at,
                "userisbot": user.bot,
                "username": str(user),
                "useravatar": user.avatar.with_format("gif").url
                if user.avatar.is_animated()
                else user.avatar.with_format("png").url,
                "reason": reason,
                "moderator": moderator,
                "moderatorid": modid,
            }
            async with self.bot.db.acquire() as conn:
                await self.fire_event_dispatch(
                    self.cached_triggers["automod"][guild.id]["user_ban"], guild, even, conn=conn
                )

    @commands.Cog.listener()
    async def on_member_unban(self, guild: discord.Guild, user: discord.User):
        await self.filled.wait()
        if guild.id not in self.cached_triggers["automod"]:
            return

        if "user_unban" in self.cached_triggers["automod"][guild.id]:
            await asyncio.sleep(0.5)

            if guild.me.guild_permissions.view_audit_log:
                async for ban in guild.audit_logs(action=discord.AuditLogAction.unban):  # type: discord.AuditLogEntry
                    if ban.target == user:
                        reason = ban.reason or "No reason provided"
                        moderator = str(ban.user)
                        modid = ban.user.id

                        break

                else:
                    reason = moderator = "<Unban not found>"
                    modid = 0

            else:
                reason = moderator = "<cannot see audit logs>"
                modid = 0

            even = {
                "userid": user.id,
                "usercreatedat": user.created_at,
                "reason": reason,
                "moderator": moderator,
                "moderatorid": modid,
            }
            async with self.bot.db.acquire() as conn:
                await self.fire_event_dispatch(
                    self.cached_triggers["automod"][guild.id]["user_unban"], guild, even, conn=conn
                )
