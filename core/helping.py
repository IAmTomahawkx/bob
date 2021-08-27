from typing import Any, Awaitable, Callable, Union
from .context import Context


class BaseHelper:
    __slots__ = ("optional", "name", "default")
    description: str
    example: str

    def __init__(self, name: str, optional: bool, default: Any = None):
        self.name = name
        self.optional = optional
        self.default = default

    @property
    def short(self) -> str:
        raise NotImplementedError

    @property
    def long(self) -> str:
        raise NotImplementedError


class Text(BaseHelper):
    description = 'A word of text. To include multiple words in this argument, wrap your words in quotes, "like this".'
    example = "Hi"

    @property
    def short(self) -> str:
        if self.optional:
            return "[Text]"

        return "<Text>"

    @property
    def long(self) -> str:
        if self.optional:
            return f"[{self.name}: Text]"

        return f"<{self.name}: Text>"


class RemainderText(BaseHelper):
    description = (
        "The rest of the command input. There is no need to quote words to have multiple of them in the argument."
    )
    example = "Oh hello there"

    @property
    def short(self) -> str:
        if self.optional:
            return "[Text]"

        return "<Text>"

    @property
    def long(self) -> str:
        if self.optional:
            return f"[{self.name}: Text]"

        return f"<{self.name}: Text>"


class Timestamp(BaseHelper):
    description = 'The time this is applicable until. This can be an offset ("2 hours") or a more concrete time ("until saturday")'
    example = "until january first"

    @property
    def short(self) -> str:
        if self.optional:
            return "[Timestamp]"

        return "<Timestamp>"

    long = short


class Number(BaseHelper):
    description = "A number (not a decimal)"
    example = "15"

    @property
    def short(self) -> str:
        if self.optional:
            return "[Number]"

        return "<Channel>"

    @property
    def long(self) -> str:
        if self.optional:
            return f"[{self.name}: Channel(s)]"

        return f"<{self.name}: Channel(s)>"


class Member(BaseHelper):
    description = "A member of the server. You can ping them, use their name, or their id as the argument."
    example = "@IAmTomahawkx"

    @property
    def short(self) -> str:
        if self.optional:
            return "[Member]"

        return "<Member>"

    @property
    def long(self) -> str:
        if self.optional:
            return f"[{self.name}: Member]"

        return f"<{self.name}: Member>"


class GreedyMember(BaseHelper):
    description = "Multiple members of the server can be used in this argument. You can also have just 1. You can ping them, use their name, or their id as the argument."
    example = "Velvet#0069 @IAmTomahawkx 605109308736405525"

    @property
    def short(self) -> str:
        if self.optional:
            return "[Member(s)]"

        return "<Member(s)>"

    @property
    def long(self) -> str:
        if self.optional:
            return f"[{self.name}: Member(s)]"

        return f"<{self.name}: Member(s)>"


class Channel(BaseHelper):
    description = "A channel in the server. This can take a channel name, a mention, or an id as the argument."
    example = "#bot-usage"

    @property
    def short(self) -> str:
        if self.optional:
            return "[Channel]"

        return "<Channel>"

    @property
    def long(self) -> str:
        if self.optional:
            return f"[{self.name}: Channel]"

        return f"<{self.name}: Channel>"


class GreedyChannel(BaseHelper):
    description = "Multiple channels in the server. Can take channel names, mentions, or ids."
    example = "#bot-usage #general 381963689470984203"

    @property
    def short(self) -> str:
        if self.optional:
            return "[Channel(s)]"

        return "<Channel(s)>"

    @property
    def long(self) -> str:
        if self.optional:
            return f"[{self.name}: Channel(s)]"

        return f"<{self.name}: Channel(s)>"


class Role(BaseHelper):
    description = "A role in the server. This can take a role name, a mention, or an id as the argument."
    example = "@Mods"

    @property
    def short(self) -> str:
        if self.optional:
            return "[Role]"

        return "<Role>"

    @property
    def long(self) -> str:
        if self.optional:
            return f"[{self.name}: Role]"

        return f"<{self.name}: Role>"


class GreedyRole(BaseHelper):
    description = "Multiple roles in the server. Can take role names, mentions, or ids."
    example = "@Mods Mods 381978546123440130"

    @property
    def short(self) -> str:
        if self.optional:
            return "[Role(s)]"

        return "<Role(s)>"

    @property
    def long(self) -> str:
        if self.optional:
            return f"[{self.name}: Role(s)]"

        return f"<{self.name}: Role(s)>"


class User(BaseHelper):
    description = "A user on discord. This should be in the form of a user id, as the user might not be in the server (read: name not available to the bot)."
    example = "80088516616269824"

    @property
    def short(self) -> str:
        if self.optional:
            return "[User]"

        return "<User>"

    @property
    def long(self) -> str:
        if self.optional:
            return f"[{self.name}: User]"

        return f"<{self.name}: User>"


class GreedyUser(BaseHelper):
    description = "Multiple users on discord. This should be in the form of user ids, as the user might not be in the server (read: name not available to the bot)."
    example = "80088516616269824 184385816066392064"

    @property
    def short(self) -> str:
        if self.optional:
            return "[User(s)]"

        return "<User(s)>"

    @property
    def long(self) -> str:
        if self.optional:
            return f"[{self.name}: User(s)]"

        return f"<{self.name}: User(s)>"


class FlagHelper(BaseHelper):
    pass


class NumberFlag(FlagHelper):
    description = "A number"
    example = "{name}: 5"

    @property
    def long(self) -> str:
        if self.optional:
            return f"[{self.name}: Number]"

        return f"<{self.name}: Number>"

    short = long


class TextFlag(FlagHelper):
    description = "Some text"
    example = "{name}: hi hello"

    @property
    def long(self) -> str:
        if self.optional:
            return f"[{self.name}: Text]"

        return f"<{self.name}: Text>"

    short = long


class UserFlag(FlagHelper):
    description = "A user on discord. This should be in the form of a user id, as the user might not be in the server (read: name not available to the bot)."
    example = "{name}: 80088516616269824"

    @property
    def long(self) -> str:
        if self.optional:
            return f"[{self.name}: User]"

        return f"<{self.name}: User>"

    short = long


class MemberFlag(FlagHelper):
    description = "A member in your server. You can ping them, use their name, or their id as the argument."
    example = "{name}: @IAmTomahawkx"

    @property
    def long(self) -> str:
        if self.optional:
            return f"[{self.name}: Member]"

        return f"<{self.name}: Member>"

    short = long

# custom converters

class ConfigFile(BaseHelper):
    description = "A config file. This can be a code block, a hasteb.in or mystb.in link, or a file upload."
    example = "https://mystb.in/AlpacaReefsAtlantic"

    @property
    def short(self) -> str:
        if self.optional:
            return "[ConfigFile]"

        return "ConfigFile"

    @property
    def long(self) -> str:
        if self.optional:
            return f"[{self.name}: ConfigFile]"

        return f"<{self.name}: ConfigFile>"

# checks

class Check:
    fast: str
    priority: int # higher for higher priority
    description: str
    predicate: Union[Callable[[Context], bool], Awaitable[Callable[[Context], bool]]]

class CheckOwnerOnly(Check):
    priority = 100
    fast = "Owner Only"
    description = "You must own the bot to use this command"

    async def predicate(self, ctx: Context) -> bool:
        return await ctx.bot.is_owner(ctx.author)

class CheckAdmin(Check):
    priority = 50
    fast = "Locked to Server Administrators"
    description = "You must be an Administrator to use this command"

    def predicate(self, ctx: Context) -> bool:
        return ctx.guild and ctx.author.guild_permissions.administrator

class CheckModerator(Check):
    priority = 30
    fast = "Locked to Moderators"
    description = "You must be a Moderator (Manage Messages) to use this command"

    def predicate(self, ctx: Context) -> bool:
        return ctx.guild and ctx.channel.permissions_for(ctx.author).manage_messages

class CheckRoleManage(Check):
    priority = 33
    fast = "Locked to Moderators"
    description = "You must have the `Manage Roles` permission to use this command"

    def predicate(self, ctx: Context) -> bool:
        return ctx.guild and ctx.author.guild_permissions.manage_roles

class CheckKickModerator(Check):
    priority = 34
    fast = "Locked to Moderators"
    description = "You must have the `Kick Members` permission to use this command"

    def predicate(self, ctx: Context) -> bool:
        return ctx.guild and ctx.author.guild_permissions.kick_members

class CheckBanModerator(Check):
    priority = 35
    fast = "Locked to Moderators"
    description = "You must have the `Ban Members` permission to use this command"

    def predicate(self, ctx: Context) -> bool:
        return ctx.guild and ctx.author.guild_permissions.ban_members

class CheckBotHasPermission(Check):
    priority = 55

    def __init__(self, **flags):
        self.flags = flags

    @property
    def fast(self):
        return "Bot requires certain permissions"

    @property
    def description(self):
        return f"Bot requires the following permission{'s' if len(self.flags) > 1 else ''}: {', '.join(' '.join(x.split('_')).title() for x in self.flags)}"

    def predicate(self, ctx: Context) -> bool:
        guild = ctx.guild
        me = guild.me if guild is not None else ctx.bot.user
        permissions = ctx.channel.permissions_for(me)  # type: ignore

        missing = tuple(perm for perm, value in self.flags.items() if getattr(permissions, perm) != value) # pulled from dpy

        return not bool(missing)