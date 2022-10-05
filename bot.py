import asyncio

from core.bot import Bot

try:
    import prettify_exceptions

    prettify_exceptions.hook()
except:
    pass

async def main():
    bot = Bot()
    async with bot:
        try:
            await bot.start()
        finally:
            import core.converters

            if core.converters.config_session is not None:
                await core.converters.config_session.close()

            if not bot.is_closed():
                await bot.close()

if __name__ == "__main__":
    bot = Bot()
    bot.run(bot._token)
