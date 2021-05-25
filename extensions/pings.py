import random
import json

from discord.ext import commands

def setup(bot):
    bot.add_cog(Bull(bot))

class Bull(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        with open("data/bullshit.json") as f:
            self.mention_messages = json.load(f)

    @commands.command("addmention")
    @commands.is_owner()
    async def add_mention(self, ctx, *, entry):
        self.mention_messages.append(entry)

        with open("data/bullshit.json", "w") as f:
            json.dump(self.mention_messages, f)

        await ctx.send("Done")

    async def run_ping(self, ctx):
        await ctx.send(random.choice(self.mention_messages).replace("$m", f""))
