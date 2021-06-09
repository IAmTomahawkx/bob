import aiohttp

from typing import Optional
from discord.ext.commands import Converter, BadArgument
from .context import Context

from jishaku.codeblocks import codeblock_converter

__all__ = (
    "ConfigFileConverter",
)

class ConfigFileConverter(Converter):
    def __init__(self):
        self.session: Optional[aiohttp.ClientSession] = None

    async def convert(self, ctx: Context, argument: str):
        if not self.session:
            self.session = aiohttp.ClientSession(headers={"User-Agent": "BOB discord bot; Configuration sniffer"})

        if argument.startswith("http"): # looks like a url link, follow it
            try:
                async with self.session.get(argument) as resp:
                    if 200 > resp.status > 299:
                        raise BadArgument(f"Received a non-ok HTTP response from `{argument}`")

                    data = await resp.text()
                    return data

            except BadArgument:
                raise
            except: # noqa
                pass

        arg = codeblock_converter(argument)
        return arg.content