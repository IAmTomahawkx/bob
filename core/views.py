import discord
import os
from typing import List, Tuple, Dict
from .models import SelfRole


async def _dummy_callback(*args):
    pass


def create_selfrole_view(guild: discord.Guild, models: List[SelfRole]) -> Tuple[discord.ui.View, Dict[int, str]]:
    rows = {}

    class View(discord.ui.View):
        def __init__(self):
            super().__init__()

            for m in models:
                for role in m["roles"]:
                    text = emoji = None
                    if m["emoji"]:
                        emoji = discord.utils.get(guild.emojis, id=m["emoji"])
                        if emoji:
                            emoji = discord.PartialEmoji(name=emoji.name, animated=emoji.animated, id=emoji.id)
                        else:
                            emoji = m["emoji"]
                    else:
                        text = guild.get_role(role)

                    cid = os.urandom(32).hex()

                    rows[role] = cid

                    b = discord.ui.Button(style=discord.ButtonStyle.primary, label=text, emoji=emoji, custom_id=cid)
                    b.callback = _dummy_callback
                    self.add_item(b)

    return View(), rows


class Confirmation(discord.ui.View):
    def __init__(self, can_click: List[int], *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.can_click = can_click
        self.response = None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return interaction.user.id in self.can_click

    @discord.ui.button(label="Confirm", style=discord.ButtonStyle.danger)
    async def confirm(self, btn: discord.ui.Button, inter: discord.Interaction):
        await inter.response.defer()
        self.response = True

        for btn in self.children:
            btn.disabled = True

        self.stop()

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.green)
    async def cancel(self, btn: discord.ui.Button, inter: discord.Interaction):
        await inter.response.defer()
        self.response = False

        for btn in self.children:
            btn.disabled = True

        self.stop()
