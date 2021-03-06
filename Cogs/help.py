import asyncio
import inspect

import discord

from utils import commands
from utils.paginator import Pages


def setup(bot):
    bot.help_command = PaginatedHelpCommand()

class HelpPaginator(Pages):
    def __init__(self, help_command, ctx, entries, *, per_page=4):
        super().__init__(ctx, entries=entries, per_page=per_page)
        self.reaction_emojis.append(('\N{WHITE QUESTION MARK ORNAMENT}', self.show_bot_help))
        self.total = len(entries)
        self.help_command = help_command
        self.prefix = help_command.clean_prefix
        self.is_bot = False

    def get_bot_page(self, page):
        cog, description, commands = self.entries[page - 1]
        self.title = f'{cog} Commands'
        self.description = description
        return commands

    def prepare_embed(self, entries, page, *, first=False):
        self.embed.clear_fields()
        self.embed.description = self.description
        self.embed.title = self.title

        if self.is_bot:
            value ='For more help, join the official B.O.B. [support server](https://discord.gg/wcVHh4h)'
            self.embed.add_field(name='Support', value=value, inline=False)

        self.embed.set_footer(text=f'Use "{self.prefix}help command" for more info on a command.')

        for entry in entries:
            signature = f'{entry.qualified_name} {entry.signature}'
            self.embed.add_field(name=signature, value=entry.brief or entry.short_doc or "No help given", inline=False)

        if self.maximum_pages:
            self.embed.set_author(name=f'Page {page}/{self.maximum_pages} ({self.total} commands)', icon_url="https://cdn.discordapp.com/attachments/646766038834479164/647215699437027339/Devision_eye.png")

    async def show_help(self):
        """shows this message"""

        self.embed.title = 'Paginator help'
        self.embed.description = 'Hello! Welcome to the help page.'

        messages = [f'{emoji} {func.__doc__}' for emoji, func in self.reaction_emojis]
        self.embed.clear_fields()
        self.embed.add_field(name='What are these reactions for?', value='\n'.join(messages), inline=False)

        self.embed.set_footer(text=f'We were on page {self.current_page} before this message.')
        await self.message.edit(embed=self.embed)

        async def go_back_to_current_page():
            await asyncio.sleep(30.0)
            await self.show_current_page()

        self.bot.loop.create_task(go_back_to_current_page())

    async def show_bot_help(self):
        """shows how to use the bot"""

        self.embed.title = 'Using the bot'
        self.embed.description = 'Hello! Welcome to the help page.'
        self.embed.clear_fields()

        entries = (
            ('<argument>', 'This means the argument is __**required**__.'),
            ('[argument]', 'This means the argument is __**optional**__.'),
            ('[A|B]', 'This means the it can be __**either A or B**__.'),
            ('[argument...]', 'This means you can have multiple arguments.\n' \
                              'Now that you know the basics, it should be noted that...\n' \
                              '__**You do not type in the brackets!**__')
        )

        for name, value in entries:
            self.embed.add_field(name=name, value=value, inline=False)

        self.embed.set_footer(text=f'last page: {self.current_page}')
        await self.message.edit(embed=self.embed)

        async def go_back_to_current_page():
            await asyncio.sleep(30.0)
            await self.show_current_page()

        self.bot.loop.create_task(go_back_to_current_page())

class PaginatedHelpCommand(commands.HelpCommand):
    default_help_categories = inspect.cleandoc("""
    <:wrench:585880691267469332> settings
    <:cctv:587262240688701440> automod
    <:filterremove:585880690839650352> modlogs
    <:notebooxmultiple:586931039100993567> customcommands
    <:clipboardtextoutline:585880690772672533>️ tags
    <:asterisk:586930584639635466> misc
    <:music:586930584627183646> music
    <:at:587264378731102218> highlight
    <:gavel:585880691011616789> moderation
    """)
    def __init__(self):
        super().__init__(command_attrs={
            'cooldown': commands.Cooldown(1, 3.0, commands.BucketType.member),
            'help': 'Shows help about the bot, a command, or a category'
        })
        self.verify_checks = False

    async def command_callback(self, ctx, *, command=None):
        await self.prepare_help_command(ctx, command)
        bot = ctx.bot

        if command is None:
            mapping = self.get_bot_mapping()
            return await self.send_bot_help(mapping)

        # Check if its a category
        cat = bot.get_category(command)
        if cat is not None:
            return await self.send_cat_help(cat)

        # Check if it's a cog
        cog = bot.get_cog(command)
        if cog is not None:
            if cog.hidden and not await bot.is_owner(self.context.author):
                return await self.send_error_message(f"No command called \"{command}\" found")
            return await self.send_cog_help(cog)

        maybe_coro = discord.utils.maybe_coroutine

        # If it's not a cog then it's a command.
        # Since we want to have detailed errors when someone
        # passes an invalid subcommand, we need to walk through
        # the command group chain ourselves.
        keys = command.split(' ')
        cmd = bot.all_commands.get(keys[0])
        if cmd is None:
            string = await maybe_coro(self.command_not_found, self.remove_mentions(keys[0]))
            return await self.send_error_message(string)

        for key in keys[1:]:
            try:
                found = cmd.all_commands.get(key)
            except AttributeError:
                string = await maybe_coro(self.subcommand_not_found, cmd, self.remove_mentions(key))
                return await self.send_error_message(string)
            else:
                if found is None:
                    string = await maybe_coro(self.subcommand_not_found, cmd, self.remove_mentions(key))
                    return await self.send_error_message(string)
                cmd = found

        if isinstance(cmd, commands.Group):
            return await self.send_group_help(cmd)
        else:
            return await self.send_command_help(cmd)

    async def on_help_command_error(self, ctx, error):
        if isinstance(error, commands.CommandInvokeError):
            await ctx.send(str(error.original))

    def get_command_signature(self, command):
        parent = command.full_parent_name
        if len(command.aliases) > 0:
            aliases = '|'.join(command.aliases)
            fmt = f'[{command.name}|{aliases}]'
            if parent:
                fmt = f'{parent} {fmt}'
            alias = fmt
        else:
            alias = command.name if not parent else f'{parent} {command.name}'
        return f'{alias} {command.signature}'

    def format_doc(self, doc: str)->str:
        if doc is None:
            return None
        doc = doc.format(ctx=self.context)
        return doc

    async def send_bot_help(self, mapping):
        e = self.context.embed_invis()
        e.add_field(name="Help Categories", value=self.default_help_categories)
        v = "[support server](https://discord.gg/wcVHh4h) | [invite!]" \
            "(https://discordapp.com/api/oauth2/authorize?client_id=587482154938794028&permissions=2146958839&scope=bot)"
        e.add_field(name=f"Updates in version {self.context.bot.version}", value=self.context.bot.most_recent_change)
        #guild_commands = await self.context.bot.get_cog("_CustomCommands").guild_commands(self.context.guild)
        #if guild_commands is not None:
        #    e.add_field(name="Server specific commands", value=guild_commands)
        e.add_field(name="Links", value=v, inline=False)
        targ = self.get_destination()
        await targ.send(embed=e)

    async def send_cat_help(self, cat: commands.Category):
        if cat.walk_on_help:
            entries = []
            for c in cat.walk_commands():
                if c not in entries:
                    entries.append(c)
        else:
            entries = [c for c in cat.commands]
        pages = HelpPaginator(self, self.context, entries)
        pages.title = cat.title
        pages.description = self.format_doc(cat.description)
        await pages.paginate()

    async def send_cog_help(self, cog: commands.Cog):
        if cog.walk_on_help:
            cogcoms = list(cog.walk_commands())
        else:
            cogcoms = cog.get_commands()
        entries = await self.filter_commands(cogcoms, sort=True)
        pages = HelpPaginator(self, self.context, entries)
        pages.title = f'{cog.qualified_name} Commands'
        pages.description = self.format_doc(cog.description)

        await pages.paginate()

    def common_command_formatting(self, page_or_embed, command):
        page_or_embed.title = self.get_command_signature(command)
        if command.description:
            page_or_embed.description = f'{self.format_doc(command.description)}\n\n{self.format_doc(command.help)}'
        else:
            page_or_embed.description = self.format_doc(command.help) or 'No help found...'

    def command_not_found(self, string):
        return f"Nope, no {string} command found here"

    async def send_command_help(self, command):
        # No pagination necessary for a single command.
        if command.hidden:
            return await self.context.send(self.command_not_found(command.qualified_name))

        embed = discord.Embed(colour=discord.Colour.teal())
        self.common_command_formatting(embed, command)
        await self.context.send(embed=embed)

    async def send_group_help(self, group: commands.Group):
        if group.hidden:
            return await self.context.send(self.command_not_found(group.qualified_name))

        subcommands = list(set(group.walk_commands())) if group.walk_help else list(group.commands)
        if len(subcommands) == 0:
            return await self.send_command_help(group)

        entries = await self.filter_commands(subcommands, sort=True)
        pages = HelpPaginator(self, self.context, entries)
        self.common_command_formatting(pages, group)
        await pages.paginate()
