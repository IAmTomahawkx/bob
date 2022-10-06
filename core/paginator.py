import asyncio
from typing import Dict, Any, Optional, List, Callable, Awaitable

import discord
from discord.utils import MISSING
from discord import ui  # shortcut because I'm lazy
from discord.ext.commands import Paginator as CommandPaginator, CommandError


class CannotPaginate(CommandError):
    pass


class Pages(ui.View):
    """Implements a paginator that queries the user for the
    pagination interface.
    Pages are 1-index based, not 0-index based.
    If the user does not reply within 1 minute then the pagination
    interface exits automatically.
    Parameters
    ------------
    ctx: Context
        The context of the command.
    entries: List[str]
        A list of entries to paginate.
    per_page: int
        How many entries show up per page.
    show_entry_count: bool
        Whether to show an entry count in the footer.
    Attributes
    -----------
    embed: discord.Embed
        The embed object that is being used to send pagination info.
        Feel free to modify this externally. Only the description,
        footer fields, and colour are internally modified.
    permissions: discord.Permissions
        Our permissions for the channel.
    """

    message: Optional[discord.Message] = None

    def __init__(
        self,
        ctx,
        *,
        entries,
        per_page=12,
        show_entry_count=True,
        title=None,
        embed_color=discord.Color.blurple(),
        nocount=False,
        delete_after=True,
        author=None,
        author_url=None,
        stop=False,
    ):
        super().__init__()
        self.bot = ctx.bot
        self.stoppable = stop
        self.ctx = ctx
        self.delete_after = delete_after
        self.entries = entries
        self.embed_author = author, author_url
        self.channel = ctx.channel
        self.author = ctx.author
        self.nocount = nocount
        self.title = title
        self.per_page = per_page

        pages, left_over = divmod(len(self.entries), self.per_page)
        if left_over:
            pages += 1

        self.maximum_pages = pages
        self.embed = discord.Embed(colour=embed_color)
        self.paginating = len(entries) > per_page
        self.show_entry_count = show_entry_count
        self.reaction_emojis = [
            ("\N{BLACK LEFT-POINTING DOUBLE TRIANGLE WITH VERTICAL BAR}", self.first_page),
            ("\N{BLACK LEFT-POINTING TRIANGLE}", self.previous_page),
            ("\N{BLACK RIGHT-POINTING TRIANGLE}", self.next_page),
            ("\N{BLACK RIGHT-POINTING DOUBLE TRIANGLE WITH VERTICAL BAR}", self.last_page),
        ]

        if stop:
            self.reaction_emojis.append(("\N{BLACK SQUARE FOR STOP}", self.stop_pages))

        if ctx.guild is not None:
            self.permissions = self.channel.permissions_for(ctx.guild.me)
        else:
            self.permissions = self.channel.permissions_for(ctx.bot.user)

        if not self.permissions.embed_links:
            raise CannotPaginate("Bot does not have embed links permission.")

        if not self.permissions.send_messages:
            raise CannotPaginate("Bot cannot send messages.")

    def setup_buttons(self):
        self.clear_items()
        for (emoji, btn) in self.reaction_emojis:
            btn = ui.Button(emoji=emoji)
            btn.callback = btn
            self.add_item(btn)

    def get_page(self, page: int):
        base = (page - 1) * self.per_page
        return self.entries[base : base + self.per_page]

    def get_content(self, entries: List[Any], page: int, *, first=False):
        return None

    def get_embed(self, entries: List[Any], page: int, *, first=False):
        self.prepare_embed(entries, page, first=first)
        return self.embed

    def prepare_embed(self, entries: List[Any], page: int, *, first=False):
        p = []
        for index, entry in enumerate(entries, 1 + ((page - 1) * self.per_page)):
            if self.nocount:
                p.append(entry)
            else:
                p.append(f"{index}. {entry}")

        if self.maximum_pages > 1:
            if self.show_entry_count:
                text = f"Page {page}/{self.maximum_pages} ({len(self.entries)} entries)"
            else:
                text = f"Page {page}/{self.maximum_pages}"

            self.embed.set_footer(text=text)

        if self.paginating and first:
            p.append("")

        if self.embed_author[0]:
            self.embed.set_author(name=self.embed_author[0], icon_url=self.embed_author[1] or MISSING)

        self.embed.description = "\n".join(p)
        self.embed.title = self.title or MISSING

    async def show_page(self, page: int, *, first=False, msg_kwargs: Dict[str, Any] = None):
        self.current_page = page
        entries = self.get_page(page)
        content = self.get_content(entries, page, first=first)
        embed = self.get_embed(entries, page, first=first)

        if not self.paginating:
            return await self.channel.send(content=content, embed=embed, view=self, **msg_kwargs or {})

        if not first:
            await self.message.edit(content=content, embed=embed, view=self)
            return

        self.message = await self.channel.send(content=content, embed=embed, view=self)

    async def checked_show_page(self, page: int):
        if page != 0 and page <= self.maximum_pages:
            await self.show_page(page)

    async def first_page(self, inter: discord.Interaction):
        """goes to the first page"""
        await inter.response.defer()
        await self.show_page(1)

    async def last_page(self, inter: discord.Interaction):
        """goes to the last page"""
        await inter.response.defer()
        await self.show_page(self.maximum_pages)

    async def next_page(self, inter: discord.Interaction):
        """goes to the next page"""
        await inter.response.defer()
        await self.checked_show_page(self.current_page + 1)

    async def previous_page(self, inter: discord.Interaction):
        """goes to the previous page"""
        await inter.response.defer()
        await self.checked_show_page(self.current_page - 1)

    async def show_current_page(self, inter: discord.Interaction):
        await inter.response.defer()
        if self.paginating:
            await self.show_page(self.current_page)

    async def numbered_page(self, inter: discord.Interaction):
        """lets you type a page number to go to"""
        await inter.response.defer()
        to_delete = [await self.channel.send("What page do you want to go to?")]

        def message_check(m):
            return m.author == self.author and self.channel == m.channel and m.content.isdigit()

        try:
            msg = await self.bot.wait_for("message", check=message_check, timeout=30.0)
        except asyncio.TimeoutError:
            to_delete.append(await self.channel.send("Took too long."))
            await asyncio.sleep(5)
        else:
            page = int(msg.content)
            to_delete.append(msg)
            if page != 0 and page <= self.maximum_pages:
                await self.show_page(page)
            else:
                to_delete.append(await self.channel.send(f"Invalid page given. ({page}/{self.maximum_pages})"))
                await asyncio.sleep(5)

        try:
            await self.channel.delete_messages(to_delete)
        except Exception:  # noqa
            pass

    async def stop_pages(self):
        """stops the interactive pagination session"""
        if self.delete_after:
            await self.message.delete()

        super().stop()

    stop = stop_pages

    def _check(self, interaction: discord.Interaction):
        if interaction.user.id != self.author.id:
            return False

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        resp = self._check(interaction)

        if not resp:
            await interaction.response.send_message("You cannot use this menu", ephemeral=True)

        return resp

    async def paginate(self, msg_kwargs: Dict[str, Any] = None):
        if self.maximum_pages > 1:
            self.paginating = True

        await self.show_page(1, first=True, msg_kwargs=msg_kwargs)

        await self.wait()
        if self.delete_after and self.paginating:
            try:
                await self.message.delete()
            except discord.HTTPException:
                pass


class FieldPages(Pages):
    """Similar to Pages except entries should be a list of
    tuples having (key, value) to show as embed fields instead.
    """

    def __init__(
        self,
        ctx,
        *,
        entries,
        per_page=12,
        show_entry_count=True,
        description=None,
        title=None,
        embed_color=discord.Color.blurple(),
        **kwargs,
    ):
        super().__init__(
            ctx,
            entries=entries,
            per_page=per_page,
            show_entry_count=show_entry_count,
            title=title,
            embed_color=embed_color,
            **kwargs,
        )
        self.description = description

    def prepare_embed(self, entries: List[Any], page: int, *, first=False):
        self.embed.clear_fields()
        self.embed.description = self.description or MISSING
        self.embed.title = self.title or MISSING

        for key, value in entries:
            self.embed.add_field(name=key, value=value, inline=False)

        if self.maximum_pages > 1:
            if self.show_entry_count:
                text = f"Page {page}/{self.maximum_pages} ({len(self.entries)} entries)"
            else:
                text = f"Page {page}/{self.maximum_pages}"

            self.embed.set_footer(text=text)


class TextPages(Pages):
    """Uses a commands.Paginator internally to paginate some text."""

    def __init__(self, ctx, text, *, prefix="```", suffix="```", max_size=2000, stop=False):
        paginator = CommandPaginator(prefix=prefix, suffix=suffix, max_size=max_size - 200)
        for line in text.split("\n"):
            paginator.add_line(line)

        super().__init__(ctx, entries=paginator.pages, per_page=1, show_entry_count=False, stop=stop)

    def get_page(self, page):
        return self.entries[page - 1]

    def get_embed(self, entries, page, *, first=False):
        return None

    def get_content(self, entry, page, *, first=False):
        if self.maximum_pages > 1:
            return f"{entry}\nPage {page}/{self.maximum_pages}"
        return entry


class EmbedPages(Pages):
    """Similar to Pages except entries should be a list of embeds."""

    entries: List[discord.Embed]

    def __init__(
        self,
        ctx,
        *,
        entries,
        per_page=12,
        show_entry_count=True,
        description=None,
        title=None,
        embed_color=discord.Color.blurple(),
        **kwargs,
    ):
        super().__init__(
            ctx,
            entries=entries,
            per_page=per_page,
            show_entry_count=show_entry_count,
            title=title,
            embed_color=embed_color,
            **kwargs,
        )
        self.description = description

    def prepare_embed(self, entries: List[discord.Embed], page: int, *, first=False):
        self.embed = self.entries[page]

        if self.maximum_pages > 1:
            if self.show_entry_count:
                text = f"Page {page}/{self.maximum_pages} ({len(self.entries)} entries)"
            else:
                text = f"Page {page}/{self.maximum_pages}"

            self.embed.set_footer(text=text)


def split_text(page: str, max_len: int) -> List[str]:
    resp = []
    while len(page) > max_len:
        t = page[:max_len]
        resp.append(t)
        page = page[max_len:]

    resp.append(page)

    return resp


class EmbeddedMultiPaginator(ui.View):
    def __init__(
        self,
        sender: Callable[..., Awaitable[discord.Message]],
        pages: List[str],
        *,
        title: str = MISSING,
        per_page=1500,
        show_page_count=False,
        delete_after=False,
        codeblocks: Optional[str] = None,
    ):
        super().__init__()
        self.sender = sender
        self.title = title
        self.pages: List[List[str]] = [split_text(p, per_page) for p in pages]
        self.page_count = len(pages)
        self.per_page = per_page
        self.show_page_count = show_page_count
        self.delete_after = delete_after
        self.codeblocks = codeblocks

        self.paginating = False
        self.embed = discord.Embed()
        self.current_page = 0
        self.subpage = 0
        self.message: Optional[discord.Message] = None

    def get_page(self, page: int, subpage: int):
        base = (page - 1) * self.per_page
        return self.pages[base : base + self.per_page][subpage]

    def get_embed(self, page: int, subpage: int):
        self.prepare_embed(page, subpage)
        return self.embed

    def prepare_embed(self, page: int, subpage: int):
        if self.page_count > 1:
            if self.show_page_count:
                text = f"Subpage {subpage+1}/{len(self.pages[page])} (Page {self.current_page+1}/{self.page_count})"
            else:
                text = f"Subpage {subpage+1}/{len(self.pages[page])}"

            self.embed.set_footer(text=text)

        if self.codeblocks:
            self.embed.description = f"{self.codeblocks}\n{self.pages[page][subpage]}\n```"
        else:
            self.embed.description = self.pages[page][subpage]

        self.embed.title = self.title

    async def show_page(self, page: int, subpage: int, *, first=False, msg_kwargs: Dict[str, Any] = None):
        self.current_page = page
        embed = self.get_embed(page, subpage)

        if not self.paginating:
            return await self.sender(embed=embed, **msg_kwargs or {})

        if not first:
            return await self.message.edit(embed=embed, view=self)

        self.message = await self.sender(embed=embed, view=self)

    async def paginate(self, msg_kwargs: Dict[str, Any] = None):
        self.paginating = True

        await self.show_page(0, 0, first=True, msg_kwargs=msg_kwargs)
        await self.wait()

        if self.delete_after and self.paginating:
            try:
                await self.message.delete()
            except discord.HTTPException:
                pass

    @ui.button(emoji="\N{BLACK LEFT-POINTING DOUBLE TRIANGLE WITH VERTICAL BAR}", style=discord.ButtonStyle.secondary)
    async def first_subpage(self, _, interaction: discord.Interaction):
        await interaction.response.defer()
        self.subpage = 0

        await self.show_page(self.current_page, self.subpage)

    @ui.button(emoji="\N{BLACK LEFT-POINTING TRIANGLE}", style=discord.ButtonStyle.secondary)
    async def previous_subpage(self, _, interaction: discord.Interaction):
        await interaction.response.defer()
        self.subpage = max(0, self.subpage - 1)

        await self.show_page(self.current_page, self.subpage)

    @ui.button(emoji="\N{BLACK RIGHT-POINTING TRIANGLE}", style=discord.ButtonStyle.secondary)
    async def next_subpage(self, _, interaction: discord.Interaction):
        await interaction.response.defer()
        self.subpage = min(len(self.pages[self.current_page]), self.subpage + 1)

        await self.show_page(self.current_page, self.subpage)

    @ui.button(emoji="\N{BLACK RIGHT-POINTING DOUBLE TRIANGLE WITH VERTICAL BAR}", style=discord.ButtonStyle.secondary)
    async def last_subpage(self, _, interaction: discord.Interaction):
        await interaction.response.defer()
        self.subpage = len(self.pages[self.current_page]) - 1

        await self.show_page(self.current_page, self.subpage)

    @ui.button(
        emoji="\N{BLACK LEFT-POINTING DOUBLE TRIANGLE WITH VERTICAL BAR}", style=discord.ButtonStyle.primary, row=1
    )
    async def first_page(self, _, interaction: discord.Interaction):
        await interaction.response.defer()
        self.current_page = 0
        self.subpage = 0

        await self.show_page(self.current_page, self.subpage)

    @ui.button(emoji="\N{BLACK LEFT-POINTING TRIANGLE}", style=discord.ButtonStyle.primary, row=1)
    async def previous_page(self, _, interaction: discord.Interaction):
        await interaction.response.defer()
        self.subpage = 0
        self.current_page = max(0, self.current_page - 1)

        await self.show_page(self.current_page, self.subpage)

    @ui.button(emoji="\N{BLACK RIGHT-POINTING TRIANGLE}", style=discord.ButtonStyle.primary, row=1)
    async def next_page(self, _, interaction: discord.Interaction):
        await interaction.response.defer()
        self.subpage = 0
        self.current_page = min(self.page_count - 1, self.current_page + 1)

        await self.show_page(self.current_page, self.subpage)

    @ui.button(
        emoji="\N{BLACK RIGHT-POINTING DOUBLE TRIANGLE WITH VERTICAL BAR}", style=discord.ButtonStyle.primary, row=1
    )
    async def last_page(self, _, interaction: discord.Interaction):
        await interaction.response.defer()
        self.subpage = 0
        self.current_page = self.page_count - 1

        await self.show_page(self.current_page, self.subpage)
