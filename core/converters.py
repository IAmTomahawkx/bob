from __future__ import annotations
from typing import Optional

import aiohttp
from discord.ext.commands import Converter, BadArgument
from jishaku.codeblocks import codeblock_converter

from deps import safe_regex as re
from .context import Context

__all__ = ("ConfigFileConverter", "RegexConverter")


class ConfigFileConverter(Converter):
    def __init__(self):
        self.session: Optional[aiohttp.ClientSession] = None

    async def convert(self, ctx: Context, argument: str):
        if not self.session:
            self.session = aiohttp.ClientSession(headers={"User-Agent": "BOB discord bot; Configuration sniffer"})

        if argument.startswith("http"):  # looks like a url link, follow it
            try:
                async with self.session.get(argument) as resp:
                    if 200 > resp.status > 299:
                        raise BadArgument(f"Received a non-ok HTTP response from `{argument}`")

                    data = await resp.text()
                    return data

            except BadArgument:
                raise
            except:  # noqa
                pass

        arg = codeblock_converter(argument)
        return arg.content

class RegexConverter(Converter):
    regex: Optional[re.Re]
    async def convert(self, ctx: Context, argument: str) -> RegexConverter:
        try:
            self.regex = re.compile(argument)
        except re.CompileError as e:
            bs = '\\`'
            raise BadArgument(f"`{argument.replace('`', bs)}` is not a valid regex. {' '.join(e.args)}")
        else:
            return self
