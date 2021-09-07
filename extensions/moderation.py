from __future__ import annotations
import asyncio
import re
from typing import TYPE_CHECKING, Optional, Tuple, Set, Union, Literal

import asyncpg
import discord
from discord.ext import commands
from discord.ext.commands import converter

from core import helping, time
from core.context import Context
from core.converters import RegexConverter
from core.parse import ParsingContext
from deps.safe_regex import Re, compile

if TYPE_CHECKING:
    from core.bot import Bot
    from extensions.dispatch import Dispatch
    from extensions.timerdispatcher import Timers

MSGDAYS_RE = re.compile("(?:--delete-message-days|--dmd|--del)\s+(\d)")


class PurgeFlags(commands.FlagConverter, case_insensitive=True):
    users: Tuple[discord.User] = commands.flag(aliases=["user", "u", "member", "members", "m"], default=lambda _: [])
    contents: Optional[str] = commands.flag(aliases=["content", "c"])
    reason: Optional[str]
    embeds: Optional[bool] = commands.flag(aliases=["e"], default=lambda _: False)
    limit: Optional[int] = 1000


class _MassBanModeConverter(commands.Converter):
    MODES = {"any": 0, "all": 1, "none": 2}
    REVERSED = {v: k for k, v in MODES.items()}

    async def convert(self, ctx: Context, argument: str) -> converter.T_co:
        argument = argument.lower()
        if argument not in self.MODES:
            raise commands.BadArgument(f"Mode flag expected one of 'any', 'all', or 'none'. Got '{argument}'")

        return self.MODES[argument]


class MassBanFlags(commands.FlagConverter, case_insensitive=True):
    reason: Optional[str]

    users: Tuple[discord.User, ...] = commands.flag(
        aliases=["user", "u", "member", "members", "m"], default=lambda _: []
    )
    no_avatar: Optional[bool] = commands.flag(
        name="no-avatar", aliases=["noavy", "default-avatar", "defaultavy", "na", "da"]
    )
    no_roles: Optional[bool] = commands.flag(name="no-roles", aliases=["norole", "nr"])
    recent_joined: Optional[time.PastUserFriendlyTime] = commands.flag(name="joined", aliases=["j", "rj"])
    recent_created: Optional[time.PastUserFriendlyTime] = commands.flag(name="created", aliases=["c", "rc"])
    bots: bool = False
    name: Optional[RegexConverter]

    channel: Optional[discord.TextChannel]
    search: Optional[int] = 100

    regex: Optional[RegexConverter] = commands.flag(aliases=["r"])
    contents: Optional[str] = commands.flag(aliases=["content"])
    embeds: Optional[bool]
    files: Optional[bool]
    mention_count: Optional[int] = commands.flag(name="mention-count", aliases=["mc"])

    dry_run: Optional[bool] = commands.flag(name="dry-run", aliases=["dr", "show", "no-ban"])
    delete_message_days: Literal[0, 1, 2, 3, 4, 5, 6, 7] = commands.flag(
        name="delete-message-days", aliases=["d", "dmd"], default=lambda _: 1
    )
    mode: _MassBanModeConverter = _MassBanModeConverter.MODES["all"]


def setup(bot: Bot):
    bot.add_cog(Moderation(bot))


class Moderation(commands.Cog):
    hidden = False

    def __init__(self, bot: Bot):
        self.bot = bot

    async def dispatch_automod(self, ctx: Context, event: str, conn: asyncpg.Connection, kwargs: dict):
        dispatch: Optional[Dispatch] = self.bot.get_cog("Dispatch")
        if not dispatch:
            return

        await dispatch.filled.wait()

        if event in dispatch.cached_triggers["automod"][ctx.guild.id]:
            kwargs["__callerid__"] = ctx.author.id
            await dispatch.fire_event_dispatch(
                dispatch.cached_triggers["automod"][ctx.guild.id][event], ctx.guild, kwargs, conn, ctx.message
            )

    @commands.command(
        name="warn",
        usage=[helping.GreedyMember("Target(s)", False), helping.RemainderText("Reason", True)],
        extras={"checks": [helping.CheckModerator()]},
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
        extras={"checks": [helping.CheckBanModerator(), helping.CheckBotHasPermission(ban_members=True)]},
    )
    @commands.guild_only()
    @commands.has_permissions(ban_members=True)
    @commands.bot_has_permissions(ban_members=True)
    async def ban(
        self, ctx: Context, users: commands.Greedy[discord.Member], *, timestamp: time.OptionalUserFriendlyTime = None
    ):
        """
        Bans user(s) from the server, creating a case for each one.
        Optionally will create a timer to unban them.

        In addition to the documented arguments, this command takes an optional flag argument, --delete-message-days (or --dmd for short),
        which can be used to specify how many days worth of messages to delete. This can be anywhere from 0 to 7 (discord limitation).
        Defaults to 1.
        """

        if not users:
            return await ctx.reply("Please pass one or more users", mention_author=False)

        msgdays = 1

        if timestamp:
            reason = timestamp.arg or "None Given"
            dt = timestamp.dt
        else:
            reason = "None Given"
            dt = None

        if timestamp and timestamp.arg:
            dmd = MSGDAYS_RE.search(reason)
            if dmd:
                msgdays = int(dmd.group(1))
                if 0 > msgdays > 7:
                    return await ctx.reply(
                        f"The delete message days flag value must be between 0 and 7 (including 0/7)",
                        delete_message_after=10,
                        mention_author=False,
                    )

                reason = reason.replace(dmd.string, "", 1)

        audit_reason = f"{reason} (Action by {ctx.author} {ctx.author.id})"

        fails = []
        dispatch: Optional[Dispatch] = self.bot.get_cog("Dispatch")
        if not dispatch:
            raise RuntimeError("Failed to acquire the dispatcher, cannot proceed. Please report this")

        async with self.bot.db.acquire() as conn:
            for user in users:
                try:
                    await user.ban(reason=audit_reason, delete_message_days=msgdays)
                except discord.HTTPException:
                    fails.append(user)
                    continue

                if timestamp and timestamp.dt:
                    timers: Optional[Timers] = ctx.bot.get_cog("Timers")
                    if not timers:
                        await ctx.send(
                            "Failed to schedule the unban timer! Please report this error! "
                            "Proceeding to ban without unban timer"
                        )
                    else:
                        await timers.schedule_task(
                            "ban_complete", timestamp.dt, conn=conn, guild_id=ctx.guild.id, user_id=user.id
                        )

                dispatch.recent_events[(ctx.guild.id, user.id, "ban")] = (
                    user,
                    ctx.author,
                    reason,
                    ctx.message.jump_url,
                    dt,
                )

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
        name="kick",
        usage=[helping.GreedyMember("Target(s)", False), helping.RemainderText("Reason", True)],
        extras={"checks": [helping.CheckKickModerator(), helping.CheckBotHasPermission(kick_members=True)]},
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

        dispatch: Optional[Dispatch] = self.bot.get_cog("Dispatch")
        if not dispatch:
            raise RuntimeError("Failed to acquire dispatcher, cannot continue. Please report this")

        for user in users:
            if user.top_role.position > ctx.guild.me.top_role.position:
                fails.append(user)
                continue

            try:
                await user.kick(reason=audit_reason)
            except discord.HTTPException:
                fails.append(user)
                continue

            dispatch.recent_events[(ctx.guild.id, user.id, "kick")] = (user, ctx.author, reason, ctx.message.jump_url)

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
    async def massban(self, ctx: Context, *, flags: MassBanFlags):
        print(flags, flags)

        targets: Set[Union[discord.Member, discord.User]] = set()

        if flags.users:
            targets.update(flags.users)

        async def channelcheck():
            pass

        usercheck = channelcheck
        if flags.mode == _MassBanModeConverter.MODES["any"]:
            strategy = any
        elif flags.mode == _MassBanModeConverter.MODES["all"]:
            strategy = all
        elif flags.mode == _MassBanModeConverter.MODES["none"]:
            strategy = lambda x: not any(x)
        else:
            raise RuntimeError(f"Unknown mode: {flags.mode}")

        if flags.channel:
            checks = [lambda m: ctx.guild.owner_id == ctx.author.id or ctx.author.top_role < m.author.top_role]
            if not flags.bots:
                checks.append(lambda m: not m.author.bot)

            if flags.contents:
                checks.append(lambda m: flags.contents in m.content)

            if flags.regex:
                checks.append(lambda m: flags.regex.regex.is_match(m.content))

            if flags.embeds is not None:
                checks.append(lambda m: bool(m.embeds) is flags.embeds)

            if flags.files is not None:
                checks.append(lambda m: bool(m.files) is flags.files)

            if flags.mention_count is not None:
                checks.append(lambda m: len(m.mentions) >= flags.mention_count)

            if checks:

                async def channelcheck():
                    async for msg in flags.channel.history(limit=max(1, min(flags.search, 2000))):
                        if strategy(x(msg) for x in checks):
                            targets.add(msg.author)

        if (
            flags.name
            or flags.recent_created
            or flags.recent_joined
            or flags.no_avatar is not None
            or flags.no_roles is not None
        ):

            userchecks = []
            if not flags.bots:
                userchecks.append(lambda u: not u.bot)

            if flags.name:
                userchecks.append(lambda u: flags.name.regex.is_match(u.name))

            if flags.no_roles is not None:
                userchecks.append(lambda u: bool(u.roles) is not flags.no_roles)

            if flags.no_avatar is not None:
                userchecks.append(lambda u: bool(u.avatar) is not flags.no_avatar)

            if flags.recent_joined:
                userchecks.append(lambda u: u.joined_at < flags.recent_joined.dt)

            if flags.recent_created:
                userchecks.append(lambda u: u.created_at < flags.recent_created.dt)

            if userchecks:

                async def usercheck():
                    if not ctx.guild.chunked:
                        await ctx.guild.chunk()

                    for user in ctx.guild.members:
                        await asyncio.sleep(0)  # large guilds could potentially freeze the bot
                        if strategy(x(user) for x in userchecks):
                            targets.add(user)

        async with ctx.typing():
            await asyncio.wait((channelcheck(), usercheck()), return_when=asyncio.ALL_COMPLETED)

            if not targets:
                return await ctx.reply("No targets matched the given parameters", mention_author=False)

            if not flags.dry_run:
                reason = flags.reason or "No reason provided"
                audit_reason = reason + f" (action by {ctx.author}, {ctx.author.id})"
                fails = []

                dispatch: Optional[Dispatch] = self.bot.get_cog("Dispatch")
                if not dispatch:
                    raise RuntimeError("Failed to acquire the dispatcher, cannot proceed. Please report this")

                for target in targets:
                    try:
                        await target.ban(reason=audit_reason, delete_message_days=flags.delete_message_days)
                    except discord.HTTPException:
                        fails.append(target)
                        continue

                    dispatch.recent_events[(ctx.guild.id, target.id, "ban")] = (
                        target,
                        ctx.author,
                        reason,
                        ctx.message.jump_url,
                        None,
                    )
                    return

        await ctx.paginate_text(
            "\n".join(f"{x.mention} - {x} ({x.id})" for x in targets),
            msg_kwargs={"allowed_mentions": discord.AllowedMentions.none()},
        )

    @commands.command(
        name="mute",
        usage=[
            helping.GreedyMember("Target(s)", False),
            helping.Timestamp("Mute Until", True),
            helping.RemainderText("Reason", True),
        ],
        extras={"checks": [helping.CheckRoleManage(), helping.CheckBotHasPermission(manage_roles=True)]},
    )
    @commands.bot_has_permissions(manage_roles=True)
    @commands.has_permissions(manage_roles=True)
    @commands.guild_only()
    async def mute(
        self,
        ctx: Context,
        users: commands.Greedy[discord.Member],
        *,
        timestamp: Optional[time.OptionalUserFriendlyTime],
    ):
        """
        Mutes one or more members, optionally unmuting them automatically after a specific duration.
        """
        if not users:
            return await ctx.reply("Please provide at least one user to mute.", mention_author=False)

        if timestamp is None:
            dt = reason = None
        else:
            dt = timestamp.dt
            reason = timestamp.arg

        reason = reason or "No reason given"
        audit_reason = reason + f" (action by {ctx.author} {ctx.author.id})"

        context = None
        dispatch: Optional[Dispatch] = self.bot.get_cog("Dispatch")
        if dispatch:
            context = await dispatch.get_context(ctx.guild.id)

        if not context:
            context = ParsingContext(self.bot, ctx.guild)
            await context.fetch_required_data()

        role = ctx.guild.get_role(context.mute_role)
        if not role:
            if ctx.author.guild_permissions.administrator:
                return await ctx.reply(
                    "There is no mute role set up. Please add a mute role to your server configuration"
                )

            return await ctx.reply("There is no mute role set up. Please tell a server admin to set one up")

        fails = []

        async with self.bot.db.acquire() as conn:
            for user in users:
                if dt:
                    timers: Optional[Timers] = self.bot.get_cog("Timers")
                    if not timers:
                        await ctx.send(
                            "Failed to schedule the unmute timer! Please report this error! "
                            "Proceeding to mute without unmute timer"
                        )

                    await timers.schedule_task("mute_complete", dt, conn=conn, guild_id=ctx.guild.id, user_id=user.id)

                try:
                    dispatch.recent_events[(ctx.guild.id, user.id, "mute")] = (
                        reason,
                        ctx.author,
                        ctx.message.jump_url,
                        dt,
                    )
                    await user.add_roles(role, reason=audit_reason)
                except discord.HTTPException:
                    del dispatch.recent_events[(ctx.guild.id, user.id, "mute")]
                    fails.append(user)
                    continue

        if fails:
            try:
                await ctx.message.add_reaction("\U0000203c\U0000fe0f")
            except discord.HTTPException:
                pass

            if len(users) > 1:
                await ctx.reply(
                    f"Muted {len(users) - len(fails)} users.\nFailed to mute the following users:\n{' '.join(x.mention for x in fails)}",
                    mention_author=False,
                )
            else:
                await ctx.reply(f"Could not mute {users[0]}", mention_author=False)

        else:
            try:
                await ctx.message.add_reaction("\U0001f44d")
            except discord.HTTPException:
                pass

            if len(users) > 1:
                await ctx.reply(f"Muted {len(users)} users", mention_author=False, delete_after=5)
            else:
                await ctx.reply(f"Muted {users[0]}", mention_author=False, delete_after=5)

    @commands.command(
        name="unmute",
        usage=[helping.GreedyMember("Member(s)", False), helping.RemainderText("Reason", True, "No reason given")],
        extras={"checks": [helping.CheckBotHasPermission(manage_roles=True), helping.CheckModerator()]},
    )
    @commands.bot_has_permissions(manage_roles=True)
    @commands.guild_only()
    @commands.has_permissions(manage_roles=True)
    async def unmute(self, ctx: Context, members: commands.Greedy[discord.Member], *, reason: str = None):
        reason = reason or "No reason given"
        audit_reason = reason + f" (action by {ctx.author} {ctx.author.id})"

        context = None
        dispatch: Optional[Dispatch] = self.bot.get_cog("Dispatch")
        if dispatch:
            context = await dispatch.get_context(ctx.guild.id)

        if not context:
            context = ParsingContext(self.bot, ctx.guild)
            await context.fetch_required_data()

        role = ctx.guild.get_role(context.mute_role)
        if not role:
            if ctx.author.guild_permissions.administrator:
                return await ctx.reply(
                    "There is no mute role set up. Please add a mute role to your server configuration"
                )

            return await ctx.reply("There is no mute role set up. Please tell a server admin to set one up")

        fails = set()

        for target in members:
            if not target._roles.has(role.id):
                pass

            try:
                await target.remove_roles(role, reason=audit_reason)
            except discord.HTTPException:
                fails.add(target)

        succeeds = [x for x in members if x not in fails]
        async with ctx.bot.db.acquire() as conn:
            await conn.executemany(
                "DELETE FROM mutes WHERE guild_id = $1 AND user_id = $2", [(ctx.guild.id, x.id) for x in succeeds]
            )

    @commands.command(
        name="purge",
        usage=[
            helping.NumberFlag("Search", True, default=100),
            helping.MemberFlag("Target", True),
            helping.TextFlag("Contents", True),
        ],
        extras={"checks": [helping.CheckBotHasPermission(manage_messages=True), helping.CheckModerator()]},
    )
    @commands.bot_has_permissions(manage_messages=True)
    @commands.guild_only()
    @commands.has_permissions(manage_messages=True)
    async def purge(self, ctx: Context, *, flags: PurgeFlags):
        """
        Purges a channel for the given criteria.
        """
        found = 0
        reg: Re = flags.contents and compile(re.escape(flags.contents))

        def predicate(msg: discord.Message):
            nonlocal found
            if reg and not reg.find(msg.content):
                return False

            if flags.embeds and not msg.embeds:
                return False

            if flags.users and msg.author in flags.users:  # slightly faster than a `not in` check
                found += 1
                return True

            return False

        chnl: discord.TextChannel = ctx.channel

        await chnl.purge(
            limit=flags.limit, check=predicate
        )  # TODO: implement purge myself to make the limit given be the limit removed.
