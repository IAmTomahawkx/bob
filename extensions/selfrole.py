from __future__ import annotations

import asyncio
import itertools

import asyncpg
import discord
from discord.ext import commands
from utils.context import Context
from utils.bot import Bot
from utils.extractor import ConfigLoadError
from utils import views, models


def setup(bot):
    bot.add_cog(SelfRoles(bot))


class SelfRoles(commands.Cog, name="Self Roles"):
    def __init__(self, bot: Bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_interaction(self, interation: discord.Interaction):
        if interation.type is not discord.InteractionType.component:
            return

        query = "SELECT role_id, interaction_cid FROM selfroles_roles WHERE interaction_id = $1"
        data = await self.bot.db.fetchrow(query)

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload):
        if self.bot.get_user(payload.user_id).bot: # noqa
            return

        if not payload.guild_id:
            return

        query = "SELECT role_id, mode FROM reaction_roles WHERE guild_id = $1 AND message_id = $2 AND emoji_id = $3"
        s = await self.bot.db.fetchrow(
            query,
            payload.guild_id,
            payload.message_id,
            payload.emoji.name if payload.emoji.is_unicode_emoji() else str(payload.emoji.id),
        )
        if s is None:
            return

        match, mode = s
        if match and mode in (1, 3):
            guild = self.bot.get_guild(payload.guild_id)
            member = guild.get_member(payload.user_id)
            try:
                await member.add_roles(discord.Object(id=match))
            except discord.HTTPException:
                if not guild.get_role(match):
                    await self.bot.db.execute(
                        "DELETE FROM reaction_roles WHERE role_id = $1", match
                    )  # the role has been deleted
                    return

                await guild.get_channel(payload.channel_id).send(
                    f"I do not have permission to add {guild.get_role(match).mention} role to {member.mention}",
                    delete_after=5,
                )

    @commands.Cog.listener()
    async def on_raw_reaction_remove(self, payload: discord.RawReactionActionEvent):
        if not payload.guild_id:
            return

        query = "SELECT role_id, mode FROM reaction_roles WHERE guild_id = $1 AND message_id = $2 AND emoji_id = $3"
        s = await self.bot.db.fetchrow(
            query,
            payload.guild_id,
            payload.message_id,
            payload.emoji.name if payload.emoji.is_unicode_emoji() else str(payload.emoji.id),
        )
        if s is None:
            return

        match, mode = s
        if match and mode in (2, 3):
            guild = self.bot.get_guild(payload.guild_id)
            member = guild.get_member(payload.user_id)
            try:
                await member.remove_roles(discord.Object(id=match))
            except discord.HTTPException:
                if not guild.get_role(match):
                    await self.bot.db.execute("DELETE FROM reaction_roles WHERE role_id = $1", match)
                    return

                await guild.get_channel(payload.channel_id).send(
                    f"I do not have permission to remove {guild.get_role(match).mention} role from {member.mention}",
                    delete_after=5,
                )

    async def config_hook(self, cfg: models.GuildConfig, conn: asyncpg.Connection):
        guild: discord.Guild = self.bot.get_guild(cfg.guild_id)
        previous = await conn.fetch("SELECT id FROM selfroles WHERE guild_id = $1", cfg.guild_id)
        if previous:
            query = "SELECT channel_id, msg_id FROM selfroles_roles WHERE msg_id IS NOT NULL AND cfg_id = ANY($1)"
            data = await conn.fetch(query, [x['id'] for x in previous])
            for d in data:
                channel: discord.TextChannel = guild.get_channel(d['channel_id'])
                msg: discord.Message = await channel.fetch_message(d['msg_id'])
                if msg.author == self.bot.user: # these will be recreated
                    try:
                        await msg.delete()
                    except: # noqa
                        pass

        await conn.execute("DELETE FROM selfroles CASCADE WHERE guild_id = $1", cfg.guild_id)

        comms = list(filter(lambda x: x['mode'] is models.SelfRoleMode.command, cfg.selfroles)) # these can be inserted directly into the db
        for x in comms:
            query = "INSERT INTO selfroles (mode, guild_id, optin, optout) VALUES ($1, $2, $3, $4) RETURNING id"
            sid = await conn.fetchval(query, x['mode'].to_int(), cfg.guild_id, x['optin'], x['optout'])
            await conn.executemany("INSERT INTO selfroles_roles VALUES ($1, $2)", [(sid, r) for r in x['roles']])

        reactions = list(filter(lambda x: x['mode'] is models.SelfRoleMode.reaction, cfg.selfroles))
        for x in reactions:
            chnl: discord.TextChannel = guild.get_channel(x['channel'])
            if not x['message']:
                msg: discord.PartialMessage = chnl.get_partial_message(chnl.last_message_id)
            else:
                msg: discord.PartialMessage = chnl.get_partial_message(x['message'])

            if isinstance(x['emoji'], int):
                emoji = discord.utils.get(guild.emojis, id=x['emoji'])
            else:
                emoji = x['emoji']

            try:
                await msg.add_reaction(emoji)
            except discord.Forbidden:
                raise ConfigLoadError(f"Could not add the reaction {emoji} to selfrole. Message id: {msg.id}. Channel: {chnl.mention}")
            except discord.HTTPException:
                pass

            query = "INSERT INTO selfroles (mode, guild_id, optin, optout) VALUES ($1, $2, $3, $4) RETURNING id"
            sid = await conn.fetchval(query, x['mode'].to_int(), cfg.guild_id, x['optin'], x['optout'])
            await conn.executemany("INSERT INTO selfroles_roles VALUES ($1, $2, $3, $4)", [(sid, r, msg.id, chnl.id) for r in x['roles']])

        buttons = itertools.groupby(list(filter(lambda x: x['mode'] is models.SelfRoleMode.button, cfg.selfroles)), lambda x: x['channel'])
        for ch, x in buttons:
            chnl: discord.TextChannel = guild.get_channel(ch)
            roles = list(x)
            view, cids = views.create_selfrole_view(guild, roles)
            content = "Press the button for the corresponding role:\n"
            content += "\n".join(f"{discord.utils.get(guild.emojis, id=r['emoji'])} - <@&{r['roles'][0]}>" for r in roles)

            msg = await chnl.send(content, view=view, allowed_mentions=discord.AllowedMentions.none())
            query = """
            WITH ins AS (
                INSERT INTO
                    selfroles
                    (mode, guild_id, optin, optout)
                VALUES
                    ($1, $2, $3, $4)
                RETURNING
                    id
            )
            INSERT INTO
                selfroles_roles
            VALUES
            ((SELECT id FROM ins), $5, $6, $7, $8)
            """
            await conn.executemany(query, [
                (models.SelfRoleMode.button.to_int(), guild.id, t['optin'], t['optout'], t['roles'][0], msg.id, chnl.id, cids[t['roles'][0]])
                for t in x
                ]
            )

    @commands.group(aliases=["rr"])
    @commands.guild_only()
    @commands.has_permissions(manage_guild=True)
    @commands.bot_has_guild_permissions(manage_roles=True, add_reactions=True)
    async def reactionrole(self, ctx: Context):
        """
        allows for the creation of reaction roles! react on a message, get the corresponding role!
        Use `reactionrole add` to add a new reaction role!
        """
        await ctx.send_help(ctx.command)

    @reactionrole.command(aliases=["+"])
    @commands.guild_only()
    @commands.has_permissions(manage_guild=True)
    @commands.bot_has_guild_permissions(manage_roles=True, add_reactions=True)
    async def add(self, ctx: Context):
        """
        Adds a new reaction role.
        Only works with the manage roles permission and the add reactions permission.
        This command will guide you through the process of adding a reaction role.

        You must have the Manage Server permission to use this command.
        The bot must have the Manage Roles and Add Reactions permission to run this command.
        """

        mode = None
        while not mode:
            _mode = await ctx.ask(
                "please respond with the mode you wish to set this reaction role to.\n```\n1: add on reaction\n2: remove "
                "on reaction\n3:add on reaction add, remove on reaction removal\n```",
                return_bool=False,
                reply=True,
            )
            if ctx.prefix + "cancel" in _mode.content:
                return await _mode.reply("Aborting")

            try:
                mode = int(_mode.content.strip())
                if mode not in (1, 2, 3):
                    mode = None
                    raise ValueError

            except ValueError:
                await _mode.reply("not a number, or invalid number, please try again")

        role = None
        while not role:
            _role = await ctx.ask("please respond with the role you wish to add", return_bool=False)
            if ctx.prefix + "cancel" in _role.content:
                return await _role.reply("Aborting")

            try:
                role = await commands.RoleConverter().convert(ctx, _role)
            except commands.RoleNotFound:
                await ctx.send("role not found. aborting")

        link = None
        while not link:
            _lnk = await ctx.ask(
                "Please provide a link to the message that should have the reaction role attached to it",
                return_bool=False,
                reply=True,
            )
            if ctx.prefix + "cancel" in _lnk.content:
                return await _lnk.reply("Aborting")

            try:
                link = await commands.MessageConverter().convert(ctx, _lnk.content)
            except commands.MessageNotFound:
                await _lnk.reply("Couldn't find a message there. Please try again")

            except commands.ChannelNotReadable:
                await _lnk.reply(
                    "This message links to a channel I can't read. Please either give me permission to that channel, or use a different message"
                )

        v = await ctx.reply(
            "please add a reaction to **this** message. it will be used as the reaction role emote.\n Please note that I must be able to use that emote (it should either be from this server, or a built in emote)",
            mention_author=False,
        )

        emote = is_custom = None

        while not emote:
            try:
                reaction, user = await self.bot.wait_for(
                    "reaction_add", check=lambda r, u: u == ctx.author and r.message.id == v.id, timeout=60
                )
                if isinstance(reaction.emoji, (discord.PartialEmoji, discord.Emoji)):
                    if reaction.emoji not in ctx.guild.emojis:
                        raise ValueError

                emote = reaction.emoji
                is_custom = reaction.custom_emoji
            except ValueError:
                await ctx.send("The provided emoji was not valid. Please add a valid emoji.")

            except asyncio.TimeoutError:
                return await v.reply("Sorry, you took too long. Aborting", mention_author=False)

        try:
            await link.add_reaction(emote)
        except discord.HTTPException:
            return await ctx.send("Sorry, I can't add reactions to the given message. Aborting")

        await self.bot.db.execute(
            "INSERT INTO reaction_roles VALUES ($1,$2,$3,$4,$5,$6);",
            ctx.guild.id,
            role.id,
            str(emote.id) if is_custom else emote,
            link.id,
            link.channel.id,
            mode,
        )
        await ctx.send("Complete!")

    @reactionrole.command()
    @commands.guild_only()
    @commands.has_permissions(manage_guild=True)
    @commands.bot_has_guild_permissions(manage_roles=True, add_reactions=True)
    async def remove(self, ctx: "Context"):
        """
        Removes a reaction role.
        The bot will guide you through the process.

        You must have the Manage Server permission to use this command.
        The bot must have the Manage Roles and Add Reactions permission to run this command.
        """
        link = None
        while not link:
            _lnk = await ctx.ask(
                f"Please provide a link to the message that should have the reaction role attached to it (type '{ctx.prefix}cancel' at any time to abort this process)",
                return_bool=False,
                reply=True,
            )
            if ctx.prefix + "cancel" in _lnk.content:
                return await _lnk.reply("Aborting", mention_author=False)

            try:
                link = await commands.MessageConverter().convert(ctx, _lnk.content)
            except commands.MessageNotFound:
                await _lnk.reply("Couldn't find a message there. Please try again")

            except commands.ChannelNotReadable:
                await _lnk.reply(
                    "This message links to a channel I can't read. Please either give me permission to that channel, or use a different message"
                )

        _msg = await ctx.send("please reply with the emoji you wish to remove")
        if ctx.prefix + "cancel" in _msg.content:
            return await _msg.reply("Aborting")

        while True:
            try:
                _msg = await self.bot.wait_for(
                    "message", check=lambda msg: msg.author == ctx.author and msg.channel == ctx.channel, timeout=60
                )
                if ctx.prefix + "cancel" in _msg.content:
                    return await _msg.reply("Aborting", mention_author=False)

                reaction = str((await commands.EmojiConverter().convert(ctx, _msg.content)).id)
            except commands.EmojiNotFound:
                reaction = _msg.content
            except asyncio.TimeoutError:
                return await ctx.send("Timed out. Please respond faster")

            if await self.bot.db.fetchrow(
                "DELETE FROM reaction_roles WHERE guild_id = $1 AND message_id = $3 AND emoji_id = $4 RETURNING *",
                ctx.guild.id,
                link.id,
                reaction,
            ):
                return await ctx.send("Reaction role successfully removed")
            else:
                _msg = await _msg.reply(
                    "The reaction role was not found. Please reply with the emoji you wish to remove"
                )
                if ctx.prefix + "cancel" in _msg.content:
                    return await _msg.reply("Aborting")
