import discord
from discord.ext import commands
from utils.bot import Bot
from utils import extractor, context


def setup(bot: Bot):
    bot.add_cog(Config(bot))


STEPS = ["Parsing configuration file", "Updating selfroles"]


class Config(commands.Cog):
    def __init__(self, bot: Bot):
        self.bot = bot

    async def deploy_config(self, ctx: context.Context, cfg: str):
        content = "Deploying new configuration:\n"
        step = 1

        async def update_msg(err=None, success=False):
            nonlocal ctx, content, step, msg
            _cont = "\n".join(f"{i+1}. {x}" for i, x in enumerate(STEPS) if i < step)
            if err:
                _cont = f"Failed to deploy new configuration:\n{_cont}\n{err}"
            elif success:
                _cont = f"{content}\n{_cont}\nSuccessfully deployed new configuration"
            else:
                _cont = content + _cont

            await msg.edit(content=_cont)

        msg = await ctx.reply(content, mention_author=False)
        try:
            cfg = await extractor.parse_guild_config(cfg, ctx)
        except extractor.ConfigLoadError as e:
            await update_msg(e.msg)
            return

        async with self.bot.db.acquire() as conn:
            async with conn.transaction():
                step += 1
                await update_msg()
                selfroles = self.bot.get_cog("Self Roles")
                if not selfroles and cfg.selfroles:
                    await update_msg("Failed to update selfroles: Extension not found")
                    return

                try:
                    await selfroles.config_hook(cfg, conn)
                except extractor.ConfigLoadError as e:
                    await update_msg(e.msg)
                    return

                await update_msg(success=True)
