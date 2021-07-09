[![code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)
[![made-with-python](https://img.shields.io/badge/Made%20with-Python-1f425f.svg)](https://www.python.org/)
![license](https://img.shields.io/github/license/IAmTomahawkx/bob)
[![dev status](https://img.shields.io/badge/Development%20Status-3%20--%20Alpha-yellow)](https://pypi.org/classifiers)
[![discord](https://discord.com/api/guilds/604085864514977813/embed.png)](https://discord.gg/wcVHh4h)

___
<div align="center" style="font-size: 70px">
<strong>
Bob
</strong>
</div>
<div align="center">
An extremely flexible discord moderation bot
</div>

___

Want to create a spam filter? No problem. Want to mute people who say slurs? Easy. 
Want to create a system completely customized to your discord server? Go right on ahead.\
Bob puts the controls in your hands, and lets you define what happens when,
through powerful TOML configuration.
For example: a simple spam filter

```toml
error-channel = "#errors"
mute-role = "Muted"

[[counter]]
name = "spam"
per-user = true
initial-count = 0
decay = "5/5s"

[[automod]]
event = "message"
actions = [
    { counter = "spam", modify = 1, target = "$userid" },
    { do = "$mute($userid, 'Spamming messages', '10 minutes')", if = "%spam($userid) > 5" }
]
```

Upload this to Bob, and you're now muting people who send more than 5 messages in a 5-second period.

Bob allows you to preform actions on every event (... that discord provides.
Before you ask, no, discord doesn't provide boost events) in your server.
This includes making your own commands, through the `command` configuration:

```toml
[[command]]
name = "wave"
arguments = [
    { name = "target", type = "user" },
    { name = "_", type = "text" } # last argument will always get the full remaining text, so we'll just ignore it
]
actions = [
    { reply = ":wave: <@$userid>, $authorname says hello!" }
]
```

## Contributing
If you wish to help develop this bot, please join me in the discord linked above!

## Self-Hosting
This bot is freely available for self-hosting, you'll need the following:
- Python 3.8+
- Rust 1.53+ (and Cargo of course)
- Postgresql 11+

Create a new database in postgresql, and ensure the account the bot is connecting with has permission to create tables.
Copy the `config.example.json` file into `config.json`, and fill out the fields. `owners` can be left blank unless you
want to specify someone else as the owner, otherwise the owner of the bot account will be the owner. \
Before running the bot for the first time (and after you update), make sure to run the `build-dependancies.py` to build
the rust dependancies. \
The bot itself can be started by running the `bot.py` file.