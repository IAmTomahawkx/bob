from __future__ import annotations
import re
from typing import TYPE_CHECKING

import asyncpg
import discord
from discord.ext import commands

from core import helping, time
from core.context import Context

if TYPE_CHECKING:
    from core.bot import Bot

MSGDAYS_RE = re.compile("(?:--delete-message-days|--dmd|--del)\s+(\d)")


def setup(bot: Bot):
    bot.add_cog(Moderation(bot))


class Moderation(commands.Cog):
    def __init__(self, bot: Bot):
        self.bot = bot

    async def dispatch_automod(self, ctx: Context, event: str, conn: asyncpg.Connection, kwargs: dict):
        dispatch = self.bot.get_cog("Dispatch")
        if not dispatch:
            return

        await dispatch.filled.wait()

        if event in dispatch.cached_triggers["automod"][ctx.guild.id]:
            kwargs["__callerid__"] = ctx.author.id
            await dispatch.fire_event_dispatch(
                dispatch.cached_triggers["automod"][ctx.guild.id][event], ctx.guild, kwargs, conn, ctx.message
            )

    @commands.command(
        name="warn", usage=[helping.GreedyMember("Target(s)", False), helping.RemainderText("Reason", True)]
    )
    @commands.guild_only()
    @commands.has_permissions(manage_messages=True)
    async def warn(self, ctx: Context, users: commands.Greedy[discord.Member], *, reason: str):
        """
        Adds a warning to a user, automatically creating a new moderation case, and dispatching the `warn` and `case` automod events.
        This command can take one or more users, and will process each one individually.
        """
        if not users:
            return await ctx.reply("Please pass one or more users", mention_author=False)

        query = """
        INSERT INTO
            cases
            (guild_id, id, user_id, mod_id, action, reason, link)
        VALUES 
            ($1, (SELECT COUNT(*) + 1 FROM cases WHERE guild_id = $1), $2, $3, $4, $5, $6)
        RETURNING id
        """

        async with self.bot.db.acquire() as conn:
            for user in users:
                context = {
                    "username": str(user),
                    "userid": user.id,
                    "modname": str(ctx.author),
                    "modid": ctx.author.id,
                    "reason": reason,
                }
                await self.dispatch_automod(ctx, "warn", conn, context)

                resp = await conn.fetchval(
                    query, ctx.guild.id, user.id, ctx.author.id, "warn", reason, ctx.message.jump_url
                )
                context = {
                    "caseid": resp,
                    "casereason": reason,
                    "caseaction": "warn",
                    "casemodid": ctx.author.id,
                    "casemodname": str(ctx.author),
                    "caseuserid": user.id,
                    "caseusername": str(user),
                }
                await self.dispatch_automod(ctx, "case", conn, context)

        try:
            await ctx.message.add_reaction("\U0001f44d")
        except discord.HTTPException:  # in case we're blocked or something funky
            pass

        if len(users) > 1:
            await ctx.reply(f"Warned {len(users)} users", mention_author=False, delete_after=5)
        else:
            await ctx.reply(f"Warned {users[0]}", mention_author=False, delete_after=5)

    @commands.command(
        name="ban",
        usage=[
            helping.GreedyUser("Target(s)", False),
            helping.Timestamp("Ban Until", True),
            helping.RemainderText("Reason", True),
        ],
    )
    @commands.guild_only()
    @commands.has_permissions(ban_members=True)
    @commands.bot_has_permissions(ban_members=True)
    async def ban(
        self, ctx: Context, users: commands.Greedy[discord.Member], *, timestamp: time.UserFriendlyTime = None
    ):
        """
        Bans user(s) from the server, creating a case for each one. Optionally will create a timer to unban them

        In addition to the documented arguments, this command takes an optional flag argument, --delete-message-days (or --dmd for short),
        which can be used to specify how many days worth of messages to delete. This can be anywhere from 0 to 7 (discord limitation).
        Defaults to 1.
        """

        if not users:
            return await ctx.reply("Please pass one or more users", mention_author=False)

        reason = None
        msgdays = 1

        if timestamp:
            reason = timestamp.arg or "None Given"

        if timestamp and timestamp.arg:
            dmd = MSGDAYS_RE.search(reason)
            if dmd:
                msgdays = int(dmd.group(1))
                if 0 > msgdays > 7:
                    return ctx.reply(
                        f"The delete message days flag value must be between 0 and 7 (including 0/7)",
                        delete_message_after=10,
                        mention_author=False,
                    )

                reason = reason.replace(dmd.string, "", 1)

        audit_reason = reason + f" (Action by {ctx.author} {ctx.author.id})"

        query = """
        INSERT INTO
            cases
            (guild_id, id, user_id, mod_id, action, reason, link)
        VALUES 
            ($1, (SELECT COUNT(*) + 1 FROM cases WHERE guild_id = $1), $2, $3, $4, $5, $6)
        RETURNING id
        """

        fails = []

        async with self.bot.db.acquire() as conn:
            for user in users:
                try:
                    await user.ban(reason=audit_reason, delete_message_days=msgdays)
                except discord.HTTPException:
                    fails.append(user)
                    continue

                if timestamp and timestamp.dt:
                    timers = ctx.bot.get_cog("Timers")
                    if not timers:
                        await ctx.send(
                            "Failed to schedule the unban timer! Please report this error! "
                            "Proceeding to ban without unban timer"
                        )

                    await timers.schedule_task(
                        "ban_complete", timestamp.dt, conn=conn, guild_id=ctx.guild.id, user_id=user.id
                    )

                # we don't dispatch the ban event here because that will be dispatched by the user_ban handler
                # when the event is received

                resp = await conn.fetchval(
                    query, ctx.guild.id, user.id, ctx.author.id, "ban", reason, ctx.message.jump_url
                )
                context = {
                    "caseid": resp,
                    "casereason": reason,
                    "caseaction": "ban",
                    "casemodid": ctx.author.id,
                    "casemodname": str(ctx.author),
                    "caseuserid": user.id,
                    "caseusername": str(user),
                }
                await self.dispatch_automod(ctx, "case", conn, context)

        if fails:
            try:
                await ctx.message.add_reaction("\U0000203c\U0000fe0f")
            except discord.HTTPException:
                pass

            if len(users) > 1:
                await ctx.reply(
                    f"Banned {len(users)-len(fails)} users.\nFailed to ban the following users:\n{' '.join(x.mention for x in fails)}",
                    mention_author=False,
                )
            else:
                await ctx.reply(f"Could not ban {users[0]}", mention_author=False)

        else:
            try:
                await ctx.message.add_reaction("\U0001f44d")
            except discord.HTTPException:
                pass

            if len(users) > 1:
                await ctx.reply(f"Banned {len(users)} users", mention_author=False, delete_after=5)
            else:
                await ctx.reply(f"Banned {users[0]}", mention_author=False, delete_after=5)

    @commands.command(
        name="kick", usage=[helping.GreedyMember("Target(s)", False), helping.RemainderText("Reason", True)]
    )
    @commands.guild_only()
    @commands.has_permissions(kick_members=True)
    @commands.bot_has_guild_permissions(kick_members=True)
    async def kick(self, ctx: Context, users: commands.Greedy[discord.Member], *, reason: str = None):
        """
        Kicks one or more members from the server. For every member kicked, a case will be created.
        """
        if not users:
            return await ctx.reply("Please provide one or more member.", mention_author=False)

        reason = reason or "None Provided"
        audit_reason = reason + f" (Action by {ctx.author} {ctx.author.id})"
        fails = []

        query = """
        INSERT INTO
            cases
            (guild_id, id, user_id, mod_id, action, reason, link)
        VALUES 
            ($1, (SELECT COUNT(*) + 1 FROM cases WHERE guild_id = $1), $2, $3, $4, $5, $6)
        RETURNING id
        """

        async with self.bot.db.acquire() as conn:
            for user in users:
                if user.top_role.position > ctx.guild.me.top_role.position:
                    fails.append(user)
                    continue

                try:
                    await user.kick(reason=audit_reason)
                except discord.HTTPException:
                    fails.append(user)
                    continue

            for user in users:  # do the kicks quickly, then proceed to dispatching
                if user in fails:
                    continue

                resp = await conn.fetchval(
                    query, ctx.guild.id, user.id, ctx.author.id, "kick", reason, ctx.message.jump_url
                )
                context = {
                    "caseid": resp,
                    "casereason": reason,
                    "caseaction": "kick",
                    "casemodid": ctx.author.id,
                    "casemodname": str(ctx.author),
                    "caseuserid": user.id,
                    "caseusername": str(user),
                }
                await self.dispatch_automod(ctx, "case", conn, context)

        if fails:
            try:
                await ctx.message.add_reaction("\U0000203c\U0000fe0f")
            except discord.HTTPException:
                pass

            if len(users) > 1:
                await ctx.reply(
                    f"Kicked {len(users) - len(fails)} users.\nFailed to kick the following users:\n{' '.join(x.mention for x in fails)}",
                    mention_author=False,
                )
            else:
                await ctx.reply(f"Could not kick {users[0]}", mention_author=False)

        else:
            try:
                await ctx.message.add_reaction("\U0001f44d")
            except discord.HTTPException:
                pass

            if len(users) > 1:
                await ctx.reply(f"Kicked {len(users)} users", mention_author=False, delete_after=5)
            else:
                await ctx.reply(f"Kicked {users[0]}", mention_author=False, delete_after=5)

    @commands.command(
        name="massban",
        # TODO: gotta figure out how to document flags
    )
    @commands.has_permissions(ban_members=True)
    @commands.has_guild_permissions(ban_members=True)
    @commands.guild_only()
    async def massban(self, ctx: Context):  # TODO: massban args
        pass

    @commands.command(
        name="mute",
        usage=[
            helping.GreedyMember("Target(s)", False),
            helping.Timestamp("Mute Until", True),
            helping.RemainderText("Reason", True),
        ],
    )
    @commands.bot_has_permissions(manage_roles=True)
    @commands.has_permissions(manage_roles=True)
    @commands.guild_only()
    async def mute(self, ctx: Context, users: commands.Greedy[discord.Member], *, timestamp: time.UserFriendlyTime):
        pass

    @commands.command(
        name="purge",
        usage=[
            helping.Number("Search Messages", False),
            helping.MemberFlag("Target", True),
            helping.TextFlag("Contents", True)
        ]
    )
    @commands.bot_has_guild_permissions(manage_messages=True)
    @commands.guild_only()
    @commands.has_permissions(manage_messages=True)
    async def purge(self, ctx: Context, amount: int, target: commands.flag(max_args=1, override=True), contents: commands.flag(max_args=1, override=True)):
        pass # TODO