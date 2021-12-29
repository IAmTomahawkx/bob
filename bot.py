from core.bot import Bot

try:
    import prettify_exceptions

    prettify_exceptions.hook()
except:
    pass

if __name__ == "__main__":
    bot = Bot()
    try:
        bot.loop.run_until_complete(bot.start())
    finally:
        import core.converters

        if core.converters.config_session is not None:
            bot.loop.run_until_complete(core.converters.config_session.close())

        bot.loop.run_until_complete(bot.close())
        bot.loop.close()
