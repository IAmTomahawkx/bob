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
            super().__init__(None)

            for m in models:
                for role in m['roles']:
                    text = emoji = None
                    if m['emoji']:
                        emoji = discord.utils.get(guild.emojis, id=m['emoji'])
                        emoji = discord.PartialEmoji(name=emoji.name, animated=emoji.animated, id=emoji.id)
                    else:
                        text = guild.get_role(role)

                    cid = os.urandom(32).hex()

                    rows[role] = cid

                    b = discord.ui.Button(style=discord.ButtonStyle.primary, label=text, emoji=emoji, custom_id=cid)
                    b.callback = _dummy_callback
                    self.add_item(b)

            print(self.children)

    return View(), rows
