from __future__ import annotations
from typing import Union, List, Dict, Any

import re
import toml
import discord
from discord.ext import commands

from deps import arg_lex
from .context import Context
from .models import *
from .ast import *

with open("assets/emoji.regex", encoding="utf8") as f:
    _emoji_re = f.read()

EMOJI_RE = re.compile(_emoji_re)
FAST_EMOJI_RE = re.compile(r"<a?:([a-zA-Z0-9_]+):([0-9]+)>")
EMOJI_FULL_RE = re.compile(r"<a?:[a-zA-Z0-9_]{2,32}:[0-9]{18,22}>|" + _emoji_re)

del _emoji_re  # useless once it's compiled

ROLE_PING_RE = re.compile(r"<@&([0-9]+)>")
DECAY_RE = re.compile(r"(\d+)/(\d+)(m|h|d|w|mo|y)")

DECAY_INTERVAL = {"m": 60, "h": 3600, "d": 86400, "w": 604800, "mo": 2592000, "y": 31536000}


class ConfigLoadError(Exception):
    def __init__(self, msg: str):
        self.msg = msg
        super().__init__(msg)


def _convert_bool(arg: Any):
    if arg is True or arg is False:
        return arg

    if isinstance(arg, str):
        if arg.lower() in ("true", "t", "yes", "y", "1"):
            return True
        return False

    elif isinstance(arg, int):
        return bool(arg)

    else:
        raise ValueError("bad argument given to convert_bool")


async def parse_guild_config(cfg: str, ctx: Context) -> GuildConfig:
    config = GuildConfig(ctx.guild.id)

    try:
        parsed = toml.loads(cfg)
    except toml.TomlDecodeError as err:
        raise ConfigLoadError(f"The structure of the file is invalid: {err.msg}")

    if "error-channel" not in parsed:
        raise ConfigLoadError(f"Missing required 'error-channel' key")

    config.error_channel = await resolve_channel(ctx, parsed["error-channel"], "error-channel")

    if "mute-role" in parsed:
        config.mute_role = await resolve_role(ctx, parsed["mute-role"], "mute-role")

    if "selfrole" in parsed:
        config.selfroles = await parse_guild_selfroles(ctx, parsed["selfrole"])

    if "counter" in parsed:
        config.counters = await parse_guild_counters(parsed["counter"])

    if "event" in parsed:
        config.events = await parse_guild_events(parsed["event"])
    else:
        raise ConfigLoadError(f"Due to internal constraints, you must create at least one event")

    if "logging" in parsed:
        config.loggers = await parse_guild_logging(ctx, parsed["logging"])

    if "automod" in parsed:
        config.automod_events = await parse_guild_automod(ctx, parsed["automod"])

    if "command" in parsed:
        config.commands = await parse_guild_commands(parsed["command"])

    return config


async def parse_guild_selfroles(ctx: Context, cfg: Union[Dict[str, Any], List[Dict[str, Any]]]) -> List[SelfRole]:
    if isinstance(cfg, dict):
        cfg = [cfg]

    parsed: List[SelfRole] = []

    for i, r in enumerate(cfg):
        try:
            if not isinstance(r, dict):
                raise ConfigLoadError(
                    f"unable to parse selfrole #{i+1}. Expected a section, got {r.__class__.__name__}"
                )

            context = f"selfrole #{i+1}"

            if "message" in r:
                parsed += await resolve_auto_selfrole(ctx, r, context)
                continue

            mode = SelfRoleMode(r["mode"])
            roles = r.get("roles", None) or [r.get("role", None)]

            if not all(roles):
                raise ConfigLoadError(f"unable to parse selfrole #{i+1}. Invalid or no role(s) received")

            roles = [await resolve_role(ctx, x, context) for x in roles]
            resp = {
                "mode": mode,
                "roles": roles,
                "optin": bool(r.get("opt-in", True)),
                "optout": bool(r.get("opt-out", True)),
                "channel": None,
                "emoji": None,
            }
            if mode is SelfRoleMode.command:
                parsed.append(resp)
                continue

            elif mode is SelfRoleMode.button:
                resp["channel"] = await resolve_channel(ctx, r["channel"], context)
                resp["emoji"] = r.get("emoji", None) and await resolve_emoji(ctx, r["emoji"], context)
            else:
                resp["channel"] = await resolve_channel(ctx, r["channel"], context)
                resp["emoji"] = await resolve_emoji(ctx, r["emoji"], context)

            parsed.append(resp)

        except KeyError as e:
            raise ConfigLoadError(f"unable to parse selfrole #{i+1}. Missing the {e.args[0]} config key.")

    return parsed


async def resolve_auto_selfrole(ctx: Context, section: Dict[str, Any], context: str) -> List[SelfRole]:
    """
    automatically determines emojis - roles to use for reaction/button roles.
    if there is a role ping and an emoji on the same line of the linked message, it will become a selfrole.
    """
    message = section["message"]
    optin = bool(section.get("opt-in", True))
    optout = bool(section.get("opt-out", True))
    mode = SelfRoleMode(section["mode"])

    if mode is SelfRoleMode.command:
        raise ConfigLoadError(f"Cannot use auto-message loader with the `command` mode. ({context})")

    try:
        msg = await commands.MessageConverter().convert(ctx, message)
    except commands.ChannelNotReadable:
        raise ConfigLoadError(f"The message linked is not in a readable channel ({context})")
    except commands.MessageNotFound:
        raise ConfigLoadError(f"Unable to find the message linked ({context})")

    roles = []
    for line in msg.content.split("\n"):
        role = ROLE_PING_RE.search(line)
        if not role:
            continue

        emoji = FAST_EMOJI_RE.search(line)
        if emoji is not None:
            emoji = int(emoji.group(2))
        else:
            emoji = EMOJI_RE.search(line)

            if emoji is None:
                continue

            emoji = emoji.group(0)

        r = SelfRole(
            mode=mode,
            roles=[int(role.group(1))],
            optin=optin,
            optout=optout,
            channel=msg.channel.id,
            message=msg.id,
            emoji=emoji,
        )
        roles.append(r)

    return roles


async def parse_guild_counters(section: Union[Dict[str, Any], List[Dict[str, Any]]]) -> Dict[str, ConfigCounter]:
    if isinstance(section, dict):
        section = [section]

    resp = {}
    for i, counter in enumerate(section):
        name = None
        try:
            name = counter["name"]
            if name in resp:
                raise ConfigLoadError(f"Duplicate counters with name '{name}'")

            per_user = bool(counter.get("per-user", False))
            try:
                initial_count = int(counter.get("initial-count", 0))
            except ValueError:
                raise ConfigLoadError(f"unable to parse counter '{name}'. Unable to convert initial-count to a number.")

            decay = counter.get("decay", None)
            decay_rate = None
            decay_per = None
            if decay:
                decay = DECAY_RE.match(decay)
                if not decay:
                    raise ConfigLoadError(f"Invalid decay for counter '{name}'")

                decay_rate = int(decay.group(1))
                decay_per = int(decay.group(2))
                decay_per *= DECAY_INTERVAL[decay.group(3)]

            resp[name] = ConfigCounter(
                name=name, per_user=per_user, initial_count=initial_count, decay_rate=decay_rate, decay_per=decay_per
            )
        except KeyError as e:
            if name:
                raise ConfigLoadError(f"Unable to parse counter '{name}'. Missing the {e.args[0]} config key.")
            else:
                raise ConfigLoadError(f"unable to parse counter #{i + 1}. Missing the {e.args[0]} config key.")

    return resp


async def parse_guild_events(cfg: Union[Dict[str, Any], List[Dict[str, Any]]]) -> List[ConfigEvent]:
    if isinstance(cfg, dict):
        cfg = [cfg]

    resp = []
    for i, event in enumerate(cfg):
        name = None
        try:
            name = str(event["name"])
            context = f"Event '{name}' (#{i})"
            actions = []
            for n, act in enumerate(event["actions"]):
                actions.append(await parse_action(act, context, n))
        except KeyError as e:
            if name:
                raise ConfigLoadError(f"Unable to parse event '{name}'. Missing the {e.args[0]} config key.")
            else:
                raise ConfigLoadError(f"unable to parse event #{i + 1}. Missing the {e.args[0]} config key.")

        resp.append(ConfigEvent(name=name, actions=actions))

    return resp


async def parse_guild_logging(ctx: Context, cfg: Union[Dict[str, Any], List[Dict[str, Any]]]) -> Dict[str, Logger]:
    if isinstance(cfg, dict):
        cfg = [cfg]

    resp = {}

    for i, logger in enumerate(cfg):
        name = None
        try:
            name = str(logger["name"])
            if name in resp:
                raise ConfigLoadError(f"Duplicate loggers with name '{name}'")

            channel = await resolve_channel(ctx, logger["channel"], f"logging #{i}")
            formats = logger["format"]
            if isinstance(formats, dict):
                formats = {str(x): str(t) for x, t in formats.items()}  # make sure it's all strings
            else:
                formats = str(formats)

            resp[name] = Logger(name=name, channel=channel, format=formats)

        except KeyError as e:
            if name:
                raise ConfigLoadError(f"Unable to parse logger '{name}'. Missing the {e.args[0]} config key.")
            else:
                raise ConfigLoadError(f"unable to parse logger #{i + 1}. Missing the {e.args[0]} config key.")

    return resp


async def parse_guild_automod(ctx: Context, cfg: Union[Dict[str, Any], List[Dict[str, Any]]]) -> Dict[str, Automod]:
    if isinstance(cfg, dict):
        cfg = [cfg]

    resp = {}

    for i, automod in enumerate(cfg):
        event = None
        try:
            event = str(automod["event"])
            if event in resp:
                raise ConfigLoadError(f"Automod trigger '{event}' is duplicated")

            context = f"automod '{event}' (#{i+1})"
            parsed_ignores = {"roles": [], "channels": []}

            ignores = automod.get("ignore")
            if ignores is not None and not isinstance(ignores, dict):
                raise ConfigLoadError(
                    f"Unable to parse automod ignores for {context}. Expected a dictionary, "
                    f"got {ignores.__class__.__name__}"  # noqa
                )

            elif ignores:
                if "roles" in ignores and isinstance(ignores["roles"], list):
                    parsed_ignores["roles"] = [await resolve_role(ctx, x, context) for x in ignores["roles"]]

                if "channels" in ignores and isinstance(ignores["channels"], list):
                    parsed_ignores["channels"] = [await resolve_channel(ctx, x, context) for x in ignores["channels"]]

            if not isinstance(automod["actions"], list):
                raise ConfigLoadError(
                    f"Unable to parse actions for {context}. Expected an array, got "
                    f"{automod['actions'].__class__.__name__}"
                )

            actions = [await parse_action(x, context, n) for n, x in enumerate(automod["actions"])]

            resp[event] = Automod(event=event, ignore=parsed_ignores, actions=actions)

        except KeyError as e:
            if event:
                raise ConfigLoadError(
                    f"Unable to parse automod '{event}' (#{i+1}). Missing the {e.args[0]} config key."
                )
            else:
                raise ConfigLoadError(f"unable to parse automod #{i + 1}. Missing the {e.args[0]} config key.")

    return resp


async def parse_guild_commands(cfg: Union[Dict[str, Any], List[Dict[str, Any]]]) -> Dict[str, Command]:
    if isinstance(cfg, dict):
        cfg = [cfg]

    resp = {}

    for i, cmd in enumerate(cfg):
        name = None
        try:
            name = str(cmd["name"])
            context = f"command '{name}'"
            arguments = []
            if not isinstance(cmd["arguments"], list):
                raise ConfigLoadError(
                    f"Unable to parse arguments for {context}. Expected an array, got "
                    f"{cmd['arguments'].__class__.__name__}"
                )

            for n, arg in enumerate(cmd["arguments"]):
                if not isinstance(arg, dict):
                    raise ConfigLoadError(
                        f"Unable to parse argument #{n+1} for {context}. Expected a dictionary, got "
                        f"{arg.__class__.__name__}"
                    )

                try:
                    _name = str(arg["name"])
                    _type = CommandArgumentType(arg["type"])
                    optional = _convert_bool(arg.get("optional", False))
                except KeyError as e:
                    raise ConfigLoadError(
                        f"Unable to parse argument #{n + 1} for {context}. Missing the '{e.args[0]}' " "config key"
                    )

                arguments.append(CommandArgument(name=_name, type=_type, optional=optional))

            if not isinstance(cmd["actions"], list):
                raise ConfigLoadError(
                    f"Unable to parse actions for {context}. Expected an array, got "
                    f"{cmd['actions'].__class__.__name__}"
                )

            actions = [await parse_action(x, context, n) for n, x in enumerate(cmd["actions"])]

            resp[name] = Command(name=name, arguments=arguments, actions=actions)
        except KeyError as e:
            if name:
                raise ConfigLoadError(f"Unable to parse command '{name}' (#{i+1}). Missing the {e.args[0]} config key.")
            else:
                raise ConfigLoadError(f"unable to parse command #{i + 1}. Missing the {e.args[0]} config key.")

    return resp


async def parse_action(action: Dict[str, Any], context: str, n: int) -> Actions:
    if "args" in action and not isinstance(action["args"], dict):
        raise ConfigLoadError(
            f"Failed to parse 'args' for action {n} ({context}). "
            f'Expected a dictionary of `variablename = "$some %stuff"'
        )

    if "if" in action:
        parsed = await static_parse(action["if"], context + " (conditional)")
        if not all(isinstance(x, (BiOpExpr, ChainedBiOpExpr)) for x in parsed) or 1 < len(parsed) < 1:
            raise ConfigLoadError(f"Failed to parse conditional for action {n} ({context}). " f"Expected a comparison.")

    if "counter" in action:
        try:
            return CounterAction(
                counter=str(action["counter"]),
                modify=int(action["modify"]),
                target=action.get("target") and str(action["target"]),
                condition=action.get("if") and str(action["if"]),
                args=action.get("args"),
            )
        except KeyError as e:
            raise ConfigLoadError(
                f"Failed to parse actions ({context}, #{n}). "
                f"Required key '{e.args[0]}' for action type 'counter' is missing"
            )

    elif "dispatch" in action:
        return DispatchAction(
            dispatch=str(action["dispatch"]), condition=action.get("if") and str(action["if"]), args=action.get("args")
        )

    elif "log" in action:
        try:
            return LogAction(
                log=str(action["log"]),
                event=str(action["event"]),
                condition=action.get("if") and str(action["if"]),
                args=action.get("args"),
            )
        except KeyError as e:
            raise ConfigLoadError(
                f"Failed to parse actions ({context}, #{n}). "
                f"Required key '{e.args[0]}' for action type 'log' is missing"
            )

    elif "do" in action:
        return DoAction(
            do=str(action["do"]),
            condition=action.get("if") and str(action["if"]) and str(action["if"]),
            args=action.get("args"),
        )

    elif "reply" in action:
        return ReplyAction(
            reply=action["reply"], condition=action.get("if") and str(action["if"]), args=action.get("args")
        )

    else:
        raise ConfigLoadError(f"Failed to parse actions ({context}, #{n}). Unknown action")


async def resolve_channel(ctx: Context, arg: Union[str, int], parse_context: str) -> int:
    if isinstance(arg, int):
        if not any(x.id == arg for x in ctx.guild.channels):
            raise ConfigLoadError(f"The referenced channel, {arg}, ({parse_context}), is invalid (not found).")

        return arg

    _arg = arg.lstrip("#").lower()
    channels = tuple(x for x in ctx.guild.channels if x.name.lower() == _arg and isinstance(x, discord.TextChannel))
    if not channels:
        raise ConfigLoadError(f"The referenced channel, {arg}, ({parse_context}), is invalid (not found).")

    if len(channels) > 1:
        raise ConfigLoadError(
            f"There are multiple channels named {arg}, refusing to infer the correct one. "
            f"Maybe use a channel id? ({parse_context})"
        )

    return channels[0].id


async def resolve_role(ctx: Context, arg: Union[str, int], parse_context: str) -> int:
    if isinstance(arg, int):
        if not any(x.id == arg for x in ctx.guild.roles):
            raise ConfigLoadError(f"The referenced role, {arg}, ({parse_context}), is invalid (not found).")

        return arg

    _arg = arg.lstrip("@").lower()
    roles = tuple(x for x in ctx.guild.roles if x.name.lower() == _arg)
    if not roles:
        raise ConfigLoadError(f"The referenced role, {arg}, ({parse_context}), is invalid (not found).")

    if len(roles) > 1:
        raise ConfigLoadError(
            f"There are multiple roles named {arg}, refusing to infer the correct one. "
            f"Maybe use a role id? ({parse_context})"
        )

    return roles[0].id


async def resolve_emoji(ctx: Context, arg: Union[str, int], parse_context: str) -> Union[str, int]:
    if isinstance(arg, int):
        if not any(x.id == arg for x in ctx.guild.emojis):
            raise ConfigLoadError(f"The referenced emoji, {arg}, ({parse_context}), is invalid (not found).")

        return arg

    _arg = arg.lower().strip(":")
    t = [x for x in ctx.guild.emojis if x.name.lower() == _arg]
    if t:
        return t[0].id
    else:
        if EMOJI_RE.fullmatch(arg):
            return arg

        raise ConfigLoadError(f"The referenced emoji, {arg}, ({parse_context}), is invalid (not found).")


async def static_parse(parsable: str, context: str) -> List[BaseAst]:
    tokens = arg_lex.run_lex(parsable)
    output: List[Union[BiOpExpr, ChainedBiOpExpr, CounterAccess, VariableAccess, Literal]] = []
    depth: List[Union[CounterAccess, VariableAccess, Literal]] = []  # noqa
    last = None

    it = iter(tokens)

    def _whitespace(token):
        if not depth:
            output.append(Literal(token, []))

    def _error(token):
        nonlocal depth, last
        try:
            if depth:
                depth[-1] += token.value
            else:
                output[-1] += token.value
        except:  # noqa
            if depth:
                depth.append(Literal(token, []))
            else:
                output.append(Literal(token, []))

    def _pin(token):
        nonlocal depth, last
        if not depth and isinstance(output[-1], Literal) and str(output[-1].value).endswith("\\"):
            output[-1].value = output[-1].value.rstrip("\\") + "("
            return

        if depth and last is depth[-1]:
            raise ConfigLoadError(
                f"{context}\n| {parsable}\n| {' '*token.start}{'^'*(token.end-token.start)}\n| Doubled in-parentheses"
            )

        if not isinstance(last, (CounterAccess, VariableAccess)):
            raise ConfigLoadError(
                f"{context}\n| {parsable}\n| {' '*token.start}{'^'*(token.end-token.start)}\n| Unexpected in-parentheses"
            )

        depth.append(last)

    def _pout(token):
        nonlocal depth, last
        if not depth and isinstance(output[-1], Literal) and str(output[-1].value).endswith("\\"):
            output[-1].value = output[-1].value.rstrip("\\") + ")"
            return

        if not depth:
            raise ConfigLoadError(
                f"{context}\n| {parsable}\n| {' '*token.start}{'^'*(token.end-token.start)}\n| Unexpected out-parentheses",
            )

        depth.pop()

    def _counter(token):
        nonlocal depth, last
        last = CounterAccess(token, [])
        if depth:
            depth[-1].args.append(last)
        else:
            output.append(last)

    def _var(token):
        nonlocal depth, last
        last = VariableAccess(token, [])
        if depth:
            depth[-1].args.append(last)
        else:
            output.append(last)

    def _literal(token):
        nonlocal depth, last
        last = Literal(token, [])
        if depth:
            depth[-1].args.append(last)
        else:
            output.append(last)

    def _chained(token):
        nonlocal depth, last
        last = ChainedBiOpExpr(token, [])
        if depth:
            depth[-1].args.append(last)
        else:
            output.append(last)

    def _var_sep(token):
        nonlocal depth, last
        if not depth:
            _error(token)

    typs = {
        "Whitespace": _whitespace,
        "Var": _var,
        "Counter": _counter,
        "POut": _pout,
        "PIn": _pin,
        "Literal": _literal,
        "Error": _error,
        "And": _chained,
        "Or": _chained,
        "VarSep": _var_sep,
    }
    oprs = {"EQ", "NEQ", "SEQ", "GEQ", "SQ", "GQ"}
    for _token in it:
        t = typs.get(_token.name)
        if t:
            t(_token)

        elif _token.name in oprs:
            if depth:
                depth[-1].args.append(BiOpExpr(_token, []))
            else:
                output.append(BiOpExpr(_token, []))

    true_output = []
    it = iter(enumerate(output))
    for i, x in it:
        if isinstance(x, BiOpExpr):
            if not true_output:
                raise ConfigLoadError(
                    f"{context}\n| {parsable}\n| {' '*x.token.start}{'^'*(x.token.end-x.token.start)}\n| Unexpected comparison here"
                )

            x.left = true_output.pop()
            try:
                x.right = next(it)[1]  # noqa
            except StopIteration:
                raise ConfigLoadError(
                    f"{context}\n| {parsable}\n| {' '*x.token.start}{'^'*(x.token.end-x.token.start)}\n| "
                    "Unexpected comparison here: missing something to compare to\n"
                    fr"| HINT: If you're not trying to compare something, escape the '{x.value}' like this: '\\{x.value}'"
                )

            true_output.append(x)
            continue

        elif isinstance(x, ChainedBiOpExpr):
            true_output.append(x)

        else:
            cont = "'" + x.value + "'"
            raise ConfigLoadError(
                f"{context}\n| {parsable}\n| {' ' * x.token.start}{'^' * len(x.value)}\n| "
                f"Unexpected value here\n| "
                f"HINT: conditionals must be only comparisons. If you meant to compare text, wrap it in quotation marks:\n| "
                f"{parsable.replace(x.value, cont, 1)}"
            )

    output = true_output
    true_output = []
    it = iter(enumerate(output))

    # for those wondering, i do two loops here because i need to collect all the BiOpExprs before i can collect the ChainedBiOpExprs
    for i, x in it:
        if isinstance(x, ChainedBiOpExpr):
            if not true_output:
                raise ConfigLoadError(
                    f"{context}\n| {parsable}\n| {' '*x.token.start}{'^'*(x.token.end-x.token.start)}\n| Unexpected '{x.value}' here"
                )

            x.left = true_output.pop()
            try:
                x.right = next(it)[1]  # noqa
            except StopIteration:
                raise ConfigLoadError(
                    f"{context}\n| {parsable}\n| {' '*x.token.start}{'^'*(x.token.end-x.token.start)}\n| "
                    "Unexpected chained comparison here: missing something a comparison on the right side\n"
                    fr"| HINT: If you're not trying to chain something, escape the '{x.value}' like this: '\\{x.value}'"
                )

            true_output.append(x)
            continue

        true_output.append(x)

    return true_output
