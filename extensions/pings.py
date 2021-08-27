import pathlib
import random
import json

from discord.ext import commands
from core.context import Context


def setup(bot):
    bot.add_cog(Bull(bot))


class Bull(commands.Cog):
    hidden = True
    def __init__(self, bot):
        self.bot = bot
        pth = pathlib.Path("assets", "pings.json")
        if pth.exists():
            with pth.open() as f:
                self.mention_messages = json.load(f)

        else:
            with pth.open(mode="w") as f:
                json.dump([], f)

            self.mention_messages = []

    @commands.command("addmention")
    @commands.is_owner()
    async def add_mention(self, ctx, *, entry):
        self.mention_messages.append(entry)

        with open("assets/pings.json", "w") as f:
            json.dump(self.mention_messages, f)

        await ctx.send("Done")

    async def run_ping(self, ctx: Context):
        if not self.mention_messages:
            return

        await ctx.reply(random.choice(self.mention_messages).replace("$m", f""), mention_author=False)
