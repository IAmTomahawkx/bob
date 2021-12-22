from __future__ import annotations
import math
from typing import TYPE_CHECKING, Optional, Union, Mapping, Any, Callable, List

import discord
from discord import ui
from discord.ext import commands

from core import helping

if TYPE_CHECKING:
    from core.bot import Bot
    from core.context import Context
    from core.parse import ParsingContext


def setup(bot: Bot):
    bot.help_command = HelpCommand()


class HelpMenu(ui.View):
    MAX_COMMANDS_PER_PAGE = 5

    get_page_count: Callable[[], int] = lambda: 0

    def __init__(self, context: Context, timeout: int = None):
        super().__init__(timeout=timeout)
        self.message: Optional[discord.Message] = None
        self.context = context

        self.return_to: Optional[
            Union[Ellipsis, commands.Cog, commands.Command]
        ] = None  # Ellipsis is the lazy bot help
        self.current: Union[Ellipsis, commands.Cog, commands.Command] = ...
        self.page = 0

    def get_command_signature(self, command: commands.Command, short: bool) -> str:
        usage: List[helping.BaseHelper] = command.usage  # noqa
        if not usage:
            return command.signature

        if short:
            resp = " ".join(x.short for x in usage)
        else:
            resp = " ".join(x.long for x in usage)

        return resp

    async def can_run_any_commands(self, cog: commands.Cog) -> bool:
        for command in cog.get_commands():
            try:
                if await command.can_run(self.context):
                    return True
            except:
                pass

        return False

    async def get_bot_help(self) -> discord.Embed:
        self.return_to = self.current
        self.current = ...
        sections = self.context.bot.cogs
        self.clear_items()
        e = discord.Embed(title="Help", description="", timestamp=discord.utils.utcnow())

        for cog in sections.values():
            if not hasattr(cog, "hidden") or cog.hidden:  # noqa
                continue

            if not await self.can_run_any_commands(cog):
                continue

            e.add_field(
                name=cog.qualified_name,
                value=(cog.description and cog.description.split("\n")[0]) or "No description provided",
                inline=False,
            )
            btn = ui.Button(style=discord.ButtonStyle.grey, label=cog.qualified_name, custom_id=cog.qualified_name)
            btn.callback = self.handle_cog_press
            self.add_item(btn)

        return e

    async def get_cog_help(self, cog: commands.Cog):
        self.return_to = ...
        self.current = cog

        e = discord.Embed(title=cog.qualified_name, timestamp=discord.utils.utcnow())
        cmds = sorted(cog.get_commands(), key=lambda c: c.qualified_name)
        self.get_page_count = lambda: math.floor(len(cmds) / self.MAX_COMMANDS_PER_PAGE) or 1
        self.page = 0
        self.clear_items()

        btn = ui.Button(emoji="\U000021aa\U0000fe0f", style=discord.ButtonStyle.primary, row=1)
        btn.callback = self.handle_back_button
        self.add_item(btn)

        if self.get_page_count() > 1:
            e.set_footer(text=f"Page 1/{self.get_page_count()}")

            btn = ui.Button(emoji="\U000025c0\U0000fe0f", style=discord.ButtonStyle.primary, row=1)
            btn.callback = self.handle_page_back
            self.add_item(btn)
            btn = ui.Button(emoji="\U000025b6\U0000fe0f", style=discord.ButtonStyle.primary, row=1)
            btn.callback = self.handle_page_next
            self.add_item(btn)

        for command in cmds[0 : self.MAX_COMMANDS_PER_PAGE]:
            e.add_field(
                name=command.qualified_name,
                value=f"`{self.get_command_signature(command, False)}`\n{command.short_doc}",
                inline=False,
            )
            btn = ui.Button(style=discord.ButtonStyle.grey, label=command.qualified_name, custom_id=command.name, row=2)
            btn.callback = self.handle_command_press
            self.add_item(btn)

        return e

    async def get_command_help(self, command: Union[commands.Command, commands.Group]):
        self.return_to = self.current
        self.current = command

        self.clear_items()
        btn = ui.Button(emoji="\U000021aa\U0000fe0f", style=discord.ButtonStyle.primary, row=1)
        btn.callback = self.handle_back_button
        self.add_item(btn)

        usage: List[helping.BaseHelper] = command.usage or []  # noqa

        desc = f"```toml\n{self.context.clean_prefix}{command.qualified_name} {self.get_command_signature(command, False)}\n```\n"
        n = "\n"
        desc += f"{command.help}\n\n{n.join(f'{x.short}: {x.description} (Ex. *{x.example}*)' for x in usage)}\n\n"

        checks: List[helping.Check] = command.extras.get("checks")
        if checks:
            checks = sorted(checks, key=lambda c: c.priority)
            y = "\U00002705"
            n = "\U0000274c"
            for x in checks:
                desc += f"{y if x.predicate(self.context) else n} {x.fast}\n>>{x.description}\n"

        e = discord.Embed(title=command.qualified_name, timestamp=discord.utils.utcnow(), description=desc)
        return e

    async def start(self, target: Optional[Union[commands.Command, commands.Cog]]):
        if not target:
            embed = await self.get_bot_help()
        elif isinstance(target, commands.Cog):
            embed = await self.get_cog_help(target)
        else:
            embed = await self.get_command_help(target)

        self.message = await self.context.reply(embed=embed, view=self, mention_author=False)

    ## button handlers

    async def handle_back_button(self, _):
        if self.return_to is ...:
            embed = await self.get_bot_help()

        elif isinstance(self.return_to, commands.Cog):
            embed = await self.get_cog_help(self.return_to)

        else:
            embed = await self.get_command_help(self.return_to)

        await self.message.edit(embed=embed, view=self)

    async def handle_command_press(self, interaction: discord.Interaction):
        print(interaction.data)
        embed = await self.get_command_help(self.context.bot.get_command(interaction.data["custom_id"]))
        await self.message.edit(embed=embed, view=self)

    async def handle_cog_press(self, interaction: discord.Interaction):
        print(interaction.data)
        embed = await self.get_cog_help(self.context.bot.get_cog(interaction.data["custom_id"]))
        await self.message.edit(embed=embed, view=self)

    async def handle_page_next(self, interaction: discord.Interaction):
        pass

    async def handle_page_back(self, interaction: discord.Interaction):
        pass


class HelpCommand(commands.HelpCommand):
    async def send_bot_help(self, mapping: Mapping):
        menu = HelpMenu(self.context)
        await menu.start(None)

    async def send_command_help(self, command: commands.Command):
        menu = HelpMenu(self.context)
        await menu.start(command)

    async def command_not_found(self, string):
        string = string.lower()
        dispatch = self.context.bot.get_cog("Dispatch")  # type: Any
        if dispatch:
            ctx: ParsingContext = await dispatch.get_context(self.context.guild.id)
            if string in ctx.commands:
                pass
