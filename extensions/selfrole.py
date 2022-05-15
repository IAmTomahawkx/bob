from __future__ import annotations

import asyncio
import itertools
from typing import List, TYPE_CHECKING

import asyncpg
import discord
from discord.ext import commands
from core.context import Context
from core.bot import Bot
from core.extractor import ConfigLoadError
from core import views, models

if TYPE_CHECKING:
    from .dispatch import Dispatch


def setup(bot):
    bot.add_cog(SelfRoles(bot))


class SelfRoles(commands.Cog, name="Self Roles"):
    hidden = True

    def __init__(self, bot: Bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_interaction(self, interaction: discord.Interaction):
        if interaction.type is not discord.InteractionType.component:
            return

        query = "SELECT role_id, optin, optout FROM selfroles_roles INNER JOIN selfroles s on selfroles_roles.cfg_id = s.id WHERE interaction_cid = $1"
        data = await self.bot.db.fetchrow(query, interaction.data["custom_id"])

        if not data:
            return

        member: List[discord.Member] = await interaction.guild.query_members(user_ids=[interaction.user.id])
        if not member:  # ???
            print("no member?")
            return

        member: discord.Member = member[0]
        role: discord.Role = interaction.guild.get_role(data["role_id"])  # noqa

        if discord.utils.get(member.roles, id=data["role_id"]):
            if data["optout"]:
                try:
                    await member.remove_roles(role)  # noqa
                except discord.Forbidden:
                    await interaction.response.send_message(
                        f"Failed to remove the role due to your server's role hierarchy", ephemeral=True
                    )
                    await self.dispatch_error(
                        f"Cannot remove role {role.mention} from user {member.mention} due to your role heiarchy. Please place the bot's top role above the role you're trying to manage",
                        member.guild.id,
                    )

                else:
                    await interaction.response.send_message(
                        f"You no longer have the {role.mention} role", ephemeral=True
                    )
            else:
                await interaction.response.send_message(
                    f"You cannot opt out of the {role.mention} role", ephemeral=True
                )

        else:
            if data["optin"]:
                try:
                    await member.add_roles(role)  # noqa
                except discord.Forbidden:
                    await interaction.response.send_message(
                        f"Failed to add the role due to your server's role hierarchy", ephemeral=True
                    )
                    await self.dispatch_error(
                        f"Cannot add role {role.mention} to user {member.mention} due to your role heiarchy. Please place the bot's top role above the role you're trying to manage",
                        member.guild.id,
                    )

                else:
                    await interaction.response.send_message(f"You now have the {role.mention} role", ephemeral=True)
            else:
                await interaction.response.send_message(f"You cannot opt in to the {role.mention} role", ephemeral=True)

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent):
        if self.bot.get_user(payload.user_id).bot:  # noqa
            return

        if not payload.guild_id:
            return

        query = (
            "SELECT role_id, optin FROM selfroles_roles INNER JOIN selfroles s on s.id = selfroles_roles.cfg_id "
            "WHERE s.guild_id = $1 AND msg_id = $2 AND reaction = $3"
        )
        s = await self.bot.db.fetchrow(
            query,
            payload.guild_id,
            payload.message_id,
            payload.emoji.name if payload.emoji.is_unicode_emoji() else str(payload.emoji.id),
        )
        if s is None:
            return

        match, optin = s
        if optin:
            guild = self.bot.get_guild(payload.guild_id)
            member = guild.get_member(payload.user_id)
            try:
                await member.add_roles(discord.Object(id=match))
            except discord.HTTPException:
                if not guild.get_role(match):
                    await self.bot.db.execute(
                        "DELETE FROM selfroles_roles WHERE role_id = $1", match
                    )  # the role has been deleted
                    return

                await guild.get_channel(payload.channel_id).send(
                    f"I do not have permission to add {guild.get_role(match).mention} role to {member.mention}",
                    delete_after=5,
                )

    @commands.Cog.listener()
    async def on_raw_reaction_remove(self, payload: discord.RawReactionActionEvent):
        if self.bot.get_user(payload.user_id).bot:  # noqa
            return

        if not payload.guild_id:
            return

        query = (
            "SELECT role_id, optout FROM selfroles_roles INNER JOIN selfroles s on s.id = selfroles_roles.cfg_id "
            "WHERE s.guild_id = $1 AND msg_id = $2 AND reaction = $3"
        )
        s = await self.bot.db.fetchrow(
            query,
            payload.guild_id,
            payload.message_id,
            payload.emoji.name if payload.emoji.is_unicode_emoji() else str(payload.emoji.id),
        )
        if s is None:
            return

        match, optout = s
        if optout:
            guild = self.bot.get_guild(payload.guild_id)
            member = guild.get_member(payload.user_id)
            try:
                await member.remove_roles(discord.Object(id=match))
            except discord.HTTPException:
                if not guild.get_role(match):
                    await self.bot.db.execute(
                        "DELETE FROM selfroles_roles WHERE role_id = $1", match
                    )  # the role has been deleted
                    return

                await guild.get_channel(payload.channel_id).send(
                    f"I do not have permission to remove {guild.get_role(match).mention} role from {member.mention}",
                    delete_after=5,
                )

    async def dispatch_error(self, error: str, guild_id: int):
        dispatch: Dispatch = self.bot.get_cog("Dispatch")  # type: ignore
        ctx = await dispatch.get_context(guild_id)
        await self.bot.get_guild(guild_id).get_channel(ctx.error_channel).send(error)

    async def config_hook(self, cfg: models.GuildConfig, conn: asyncpg.Connection):
        guild: discord.Guild = self.bot.get_guild(cfg.guild_id)
        error_channel = guild.get_channel(cfg.error_channel)
        previous = await conn.fetch("SELECT id FROM selfroles WHERE guild_id = $1", cfg.guild_id)
        if previous:
            query = "SELECT channel_id, msg_id FROM selfroles_roles WHERE msg_id IS NOT NULL AND cfg_id = ANY($1)"
            data = await conn.fetch(query, [x["id"] for x in previous])
            for d in data:
                channel: discord.TextChannel = guild.get_channel(d["channel_id"])
                try:
                    msg: discord.Message = await channel.fetch_message(d["msg_id"])
                except discord.NotFound:
                    continue

                if msg.author == self.bot.user:  # these will be recreated
                    try:
                        await msg.delete()
                    except:  # noqa
                        pass

        await conn.execute("DELETE FROM selfroles CASCADE WHERE guild_id = $1", cfg.guild_id)

        comms = list(
            filter(lambda x: x["mode"] is models.SelfRoleMode.command, cfg.selfroles)
        )  # these can be inserted directly into the db
        for x in comms:
            query = "INSERT INTO selfroles (mode, guild_id, optin, optout) VALUES ($1, $2, $3, $4) RETURNING id"
            sid = await conn.fetchval(query, x["mode"].to_int(), cfg.guild_id, x["optin"], x["optout"])
            await conn.executemany("INSERT INTO selfroles_roles VALUES ($1, $2)", [(sid, r) for r in x["roles"]])

        reactions = list(filter(lambda x: x["mode"] is models.SelfRoleMode.reaction, cfg.selfroles))
        errors = []

        for x in reactions:
            chnl: discord.TextChannel = guild.get_channel(x["channel"])
            if not x["message"]:
                msg: discord.PartialMessage = chnl.get_partial_message(chnl.last_message_id)
            else:
                msg: discord.PartialMessage = chnl.get_partial_message(x["message"])

            if isinstance(x["emoji"], int):
                emoji = discord.utils.get(guild.emojis, id=x["emoji"])

            else:
                emoji = x["emoji"]

            if emoji is None:
                errors.append((x["emoji"], msg.jump_url))
            else:
                try:
                    await msg.add_reaction(emoji)
                except:
                    errors.append((emoji, msg.jump_url))

            query = "INSERT INTO selfroles (mode, guild_id, optin, optout) VALUES ($1, $2, $3, $4) RETURNING id"
            sid = await conn.fetchval(query, x["mode"].to_int(), cfg.guild_id, x["optin"], x["optout"])
            await conn.executemany(
                "INSERT INTO selfroles_roles (cfg_id, role_id, msg_id, channel_id, reaction) VALUES ($1, $2, $3, $4, $5)",
                [(sid, r, msg.id, chnl.id, str(x["emoji"])) for r in x["roles"]],
            )

        fmt = "\n".join((f"{x[0]}: {x[1]}" for x in errors))
        await error_channel.send(
            f"Failed to react with the following emojis:\n{fmt}\nThey'll still work, but you'll have to react manually"
        )

        buttons = itertools.groupby(
            list(filter(lambda x: x["mode"] is models.SelfRoleMode.button, cfg.selfroles)), lambda x: x["channel"]
        )
        for ch, x in buttons:
            chnl: discord.TextChannel = guild.get_channel(ch)
            roles = list(x)
            view, cids = views.create_selfrole_view(guild, roles)
            content = "Press the button for the corresponding role:\n"
            content += "\n".join(
                f"{discord.utils.get(guild.emojis, id=r['emoji']) or r['emoji']} - <@&{r['roles'][0]}>" for r in roles
            )

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
            p = [
                (
                    models.SelfRoleMode.button.to_int(),
                    guild.id,
                    t["optin"],
                    t["optout"],
                    t["roles"][0],
                    msg.id,
                    chnl.id,
                    cids[t["roles"][0]],
                )
                for t in roles
            ]
            await conn.executemany(query, p)
