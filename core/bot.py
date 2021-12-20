from __future__ import annotations

import asyncio
import os

import asyncpg
import calendar
import json
import aiohttp
import parsedatetime
import datetime
import discord
import sys
from discord.ext import commands
from . import time
from .context import Context
from .models import *

__all__ = ("Bot",)

try:
    import prettify_exceptions

    formatter = prettify_exceptions.DefaultFormatter()
except:
    import traceback as formatter


class _CaseInsensitiveDict(dict):
    def __contains__(self, k):
        return super().__contains__(k.lower())

    def __delitem__(self, k):
        return super().__delitem__(k.lower())

    def __getitem__(self, k):
        return super().__getitem__(k.lower())

    def get(self, k, default=None):
        return super().get(k.lower(), default)

    def pop(self, k, default=None):
        return super().pop(k.lower(), default)

    def __setitem__(self, k, v):
        super().__setitem__(k.lower(), v)


def parse_time(ps, return_times_instead=False):
    cal = parsedatetime.Calendar()
    v = cal.nlp(ps)[0]  # type: datetime.datetime
    if not return_times_instead:
        return calendar.timegm(v.replace(tzinfo=datetime.timezone.utc).timetuple())
    return time.human_timedelta(v)


async def get_pre(bot, message):
    if message.guild is None:
        return ["!", "?", ""]
    try:
        l = [*bot.guild_prefixes[message.guild.id]]
    except:
        l = ["["]
    if await bot.is_owner(message.author):
        l.append("$")
    return commands.when_mentioned_or(*l)(bot, message)


class Bot(commands.Bot):
    loop: asyncio.AbstractEventLoop

    def __init__(self, **settings):
        self.settings = {}
        self.reload_settings()
        self.beta = self.settings["beta"]
        self._token = self.settings["token"]
        self.error_channel = self.settings["error_channel"]
        self.db: asyncpg.pool.Pool = None  # noqa

        intents = discord.Intents.all()
        intents.presences = False # noqa
        allowed_mentions = discord.AllowedMentions.none()
        super().__init__(get_pre, intents=intents, allowed_mentions=allowed_mentions, **settings)

        if "owners" in self.settings and self.settings["owners"]:
            self.owner_ids = self.settings["owners"]

        self.session: aiohttp.ClientSession = None  # noqa
        self.uptime = datetime.datetime.utcnow()
        self.version = None

        self.guild_prefixes = {}
        self.bans = {}

        self.add_check(self.ban_check)

    def reload_settings(self):
        with open("config.json") as f:
            self.settings = json.load(f)

    #async def setup(self):
    #    await self.upload_guild_application_commands()

    async def start(self) -> None:  # noqa
        self.session = aiohttp.ClientSession()
        self.db: asyncpg.pool.Pool = await asyncpg.create_pool(self.settings["db_uri"], min_size=1)
        with open("schema.sql") as f:
            schema = f.read()

        await self.db.execute(schema)

        self.load_extension("jishaku")
        for ext in os.listdir("extensions"):
            if not ext.endswith(".py"):
                continue

            self.load_extension(f"extensions.{ext[:-3]}")

        await self.login(self._token)
        await self.setup()
        await self.connect(reconnect=True)

    async def on_interaction(self, interaction):
        await super().on_interaction(interaction)

    async def on_ready(self):
        print(self.user)

    async def on_command_error(self, context, exception):
        if isinstance(exception, commands.CheckFailure):
            return await context.send(exception.args[0])

        else:
            await super().on_command_error(context, exception)

    async def on_message(self, message: discord.Message):
        if message.author.bot:
            return

        ctx = await self.get_context(message, cls=Context)
        if not ctx.valid:
            cog = self.get_cog("Bull")
            await cog.run_ping(ctx) # type: ignore
        else:
            await self.invoke(ctx)

    async def close(self) -> None:
        await self.session.close()
        return await super().close()

    async def ban_check(self, ctx: Context):
        if ctx.author.id in self.bans:
            raise commands.CheckFailure("You have been banned from this bot.")

        return True

    async def on_error(self, event_method, *args, **kwargs):
        print("".join(formatter.format_exc()), file=sys.stderr)
