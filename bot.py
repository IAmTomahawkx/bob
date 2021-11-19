from core.bot import Bot

try:
    import prettify_exceptions

    prettify_exceptions.hook()
except:
    pass

if __name__ == "__main__":
    bot = Bot()
    bot.run()
