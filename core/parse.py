from __future__ import annotations
from typing import Optional, List, Dict, Union, Any

import datetime
import re
import random
import asyncpg
import discord
import ujson
from discord.ext import commands
from .models import *
from deps import arg_lex
from .bot import Bot
from .time import ShortTime, human_timedelta

PARSE_VARS = Optional[Dict[str, Union[str, int, bool]]]


class ExecutionInterrupt(Exception):
    def __init__(self, msg: str, stack: List[str]):
        self.msg = msg
        self.stack = stack
        super().__init__(msg)

    def __str__(self):
        stack = "\n".join([f"at {x}" for x in self.stack])
        return f"```\n{stack}\n~~~\n{self.msg}\n```"


class ParsingContext:
    def __init__(self, bot: Bot, guild: discord.Guild, is_dummy=False):
        self.bot = bot
        self.dummy = is_dummy
        self.guild = guild
        self._cfg_id: Optional[int] = None
        self.error_channel: Optional[int] = None
        self.mute_role: Optional[int] = None
        self.events = {}
        self.loggers = {}
        self.counters = {}  # lazy filled, don't assume the counter is in this
        self.commands = {}
        self.automod = {}
        self.actions = {}
        self._fetched = False

    async def fetch_required_data(self):
        if self._fetched:
            return

        async with self.bot.db.acquire() as conn:
            query = "SELECT id, error_channel, mute_role FROM configs WHERE guild_id = $1 ORDER BY id DESC LIMIT 1"
            data = await conn.fetchrow(query, self.guild.id)
            cfg_id = self._cfg_id = data["id"]
            self.error_channel = data["error_channel"]
            self.mute_role = data["mute_role"]

            query = """
            SELECT
                id, name, actions
            FROM events
            WHERE cfg_id = $1
            """
            events = await conn.fetch(query, cfg_id)

            query = """
            SELECT
                l.id, l.name, l.channel, format_name, response
            FROM logger_formats
            INNER JOIN loggers l on logger_formats.logger_id = l.id
            WHERE l.cfg_id = $1
            """
            loggers = await conn.fetch(query, cfg_id)

        self.events = {}
        for x in events:
            if x["name"] in self.events:
                self.events[x["name"]].append({"id": x["id"], "actions": x["actions"]})
            else:
                self.events[x["name"]] = [{"id": x["id"], "actions": x["actions"]}]

        logs = self.loggers = {}
        for x in loggers:
            if x["name"] in logs:
                logs[x["name"]]["formats"][x["format_name"]] = x["response"]
            else:
                logs[x["name"]] = {
                    "formats": {x["format_name"]: x["response"]},
                    "channel": self.guild.get_channel(x["channel"]),
                    "id": x["id"],
                }

        self._fetched = True

    async def link(self, actions: List[int], conn: asyncpg.Connection):
        query = """
                    SELECT
                        *
                    FROM actions
                    WHERE id = ANY($1)
                    """
        data = await conn.fetch(query, actions)

        for x in data:
            self.actions[x["id"]] = dict(x)
            self.actions[x["id"]]["args"] = x["args"] and ujson.loads(x["args"])

    async def run_event(
        self,
        name: str,
        conn: asyncpg.Connection,
        stack: List[str] = None,
        vbls: PARSE_VARS = None,
        messageable: discord.abc.Messageable = None,
    ):
        await self.fetch_required_data()
        stack = stack or ["<dispatch>"]

        if name not in self.events:
            raise ExecutionInterrupt(f"event '{name}' not found", stack)

        unlinked = []

        for dispatch in self.events[name]:
            unlinked += [x for x in dispatch["actions"] if x not in self.actions]

        if unlinked:
            await self.link(unlinked, conn)

        stack.append(f"event '{name}'")  # at this point it's safe to assume that the dispatching can go ahead

        for dispatch in self.events[name]:
            for i, runner in enumerate(dispatch["actions"]):
                runner = self.actions[runner]
                if not messageable and runner["type"] == ActionTypes.reply:
                    continue

                stack.append(f"parse action #{i}")
                args = (vbls and vbls.copy()) or {}

                if runner["args"]:
                    stack.append(f"'args' values parsing")
                    args.update(
                        {
                            k.strip("$"): await self.format_fmt(v, conn, stack, args, True)
                            for k, v in runner["args"].items()
                        }
                    )
                    stack.pop()

                stack.pop()

                r = await self.run_action(runner, conn, args, stack, i)
                if r and messageable:
                    await messageable.send(r)

    async def run_automod(
        self,
        automod: dict,
        conn: asyncpg.Connection,
        stack: List[str] = None,
        vbls: PARSE_VARS = None,
        messageable: discord.abc.Messageable = None,
    ):
        await self.fetch_required_data()
        stack = stack or ["<dispatch>"]

        unlinked = [x for x in automod["actions"] if x not in self.actions]

        if unlinked:
            await self.link(unlinked, conn)

        stack.append(
            f"automod trigger '{automod['event']}'"
        )  # at this point it's safe to assume that the dispatching can go ahead

        for i, runner in enumerate(automod["actions"]):
            act = self.actions[runner]
            stack.append(f"parse action #{i}")
            args = (vbls and vbls.copy()) or {}
            if act["args"]:
                stack.append(f"'args' values parsing")
                args.update(
                    {k.strip("$"): await self.format_fmt(v, conn, stack, args, True) for k, v in act["args"].items()}
                )
                stack.pop()

            stack.pop()

            r = await self.run_action(act, conn, args, stack, i, messageable)
            stack.pop()
            if r and messageable:
                try:
                    await messageable.send(r)
                except discord.HTTPException:
                    pass

    async def run_logger(
        self, name: str, event: str, conn: asyncpg.Connection, stack: List[str], vbls: PARSE_VARS = None
    ):
        await self.fetch_required_data()
        event = await self.format_fmt(event, conn, stack, vbls)

        logger = self.loggers[name]
        stack.append(f"logger '{name}' @ event '{event}'")
        if event in logger["formats"]:
            fmt = logger["formats"][event]
        elif "_" in logger["formats"]:
            fmt = logger["formats"]["_"]
        else:
            raise ExecutionInterrupt(f"Failed late to catch unknown logger ({name}) event: '{event}'", stack)

        channel = logger["channel"]
        if not channel:
            raise ExecutionInterrupt(f"Channel does not exist for logger {name}", stack)

        try:
            await channel.send(await self.format_fmt(fmt, conn, stack, vbls))
        except discord.HTTPException as e:
            raise ExecutionInterrupt(f"Failed to send message to logger '{name}': {e}", stack)

        stack.pop()

    async def run_command(self, name: str, msg: discord.Message):
        await self.fetch_required_data()

    async def format_fmt(
        self, fmt: str, conn: asyncpg.Connection, stack: List[str], vbls: PARSE_VARS = None, try_int=False
    ):
        stack.append(f"formatting string '{fmt}'")
        as_ast = await self.parse_input(fmt, stack, strict_errors=False)
        try:
            v = [str(await x.access(self, vbls, conn)) for x in as_ast]
        except ExecutionInterrupt as e:
            e.msg = e.msg.format(input=fmt)
            raise

        resp = "".join(v).strip()
        stack.pop()

        if try_int:
            try:
                return int(resp)
            except ValueError:
                pass

        return resp

    async def alter_counter(
        self,
        counter: str,
        conn: asyncpg.Connection,
        stack: List[str],
        modify: int,
        target: Optional[str] = None,
        vbls: PARSE_VARS = None,
    ):
        stack.append(f"edit counter {counter}")
        if target:
            t = await self.parse_input(target, stack)
            if not t:
                raise ExecutionInterrupt(f"Got an empty target", stack)

            elif not isinstance(t[0], VariableAccess):
                token = t[0].token
                raise ExecutionInterrupt(
                    f"| {target}\n| {' ' * token.start}{'^' * (token.end - token.start)}\n| Unacceptable value", stack
                )

            else:
                _target = await t[0].access(self, vbls, conn)
                if not isinstance(_target, int):
                    token = t[0].token
                    raise ExecutionInterrupt(
                        f"| {target}\n| {' ' * token.start}{'^' * (token.end - token.start)}\n| Expected a user id, got '{_target}'",
                        stack,
                    )

                target = _target

        if counter in self.counters:
            cnt = self.counters[counter]
        else:
            d = await conn.fetchrow("SELECT * FROM counters WHERE cfg_id = $1 AND name = $2", self._cfg_id, counter)
            if not d:
                raise ExecutionInterrupt(f"Unknown counter '{counter}'", stack)

            cnt = self.counters[counter] = ConfiguredCounter(
                id=d["id"],
                initial_count=d["start"],
                decay_per=d["decay_per"],
                decay_rate=d["decay_rate"],
                name=counter,
                per_user=d["per_user"],
            )
            if not cnt["per_user"]:
                c = await conn.fetchval("SELECT val FROM counter_values WHERE counter_id = $1", cnt["id"])
                if c is None:
                    await conn.execute(
                        "INSERT INTO counter_values VALUES ($1, $2, (NOW() AT TIME ZONE 'utc'), null)",
                        cnt["id"],
                        cnt["initial_count"],
                    )

        if cnt["per_user"]:
            if not target:
                raise ExecutionInterrupt(
                    f"No target given while modifying per-user counter '{counter}'",
                    stack,
                )
            else:
                await conn.execute(
                    """
                INSERT INTO counter_values VALUES (
                $1,
                ($2::INT + $3::INT),
                (NOW() AT TIME ZONE 'utc'),
                $4
                ) ON CONFLICT (counter_id, user_id) DO UPDATE SET val = excluded.val + $3::INT
                """,
                    cnt["id"],
                    cnt["initial_count"] or 0,
                    modify,
                    target,
                )
        else:
            await conn.execute("UPDATE counter_values SET val = val + $1 WHERE counter_id = $2", modify, cnt["id"])

        stack.pop()

    async def run_action(
        self,
        action: AnyAction,
        conn: asyncpg.Connection,
        vbls: Optional[PARSE_VARS],
        stack: List[str],
        n: int = None,
        messageable=None,
    ) -> Optional[str]:
        stack = stack.copy()
        stack.append(f"action #{n} (type: {ActionTypes.reversed[action['type']]})")

        if not await self.calculate_conditional(action["condition"], stack, vbls, conn):
            return

        acts = {
            ActionTypes.dispatch: (False, lambda: self.run_event(action["main_text"], conn, stack, vbls, messageable)),
            ActionTypes.log: (
                False,
                lambda: self.run_logger(action["main_text"], action["event"], conn, stack, vbls),
            ),
            ActionTypes.counter: (
                False,
                lambda: self.alter_counter(action["main_text"], conn, stack, action["modify"], action["target"], vbls),
            ),
            ActionTypes.reply: (True, lambda: self.format_fmt(action["main_text"], conn, stack, vbls)),
            ActionTypes.do: (False, lambda: self.format_fmt(action["main_text"], conn, stack, vbls)),
        }

        respond, fn = acts[action["type"]]

        if respond:
            return await fn()

        await fn()

    async def calculate_conditional(
        self, condition: Optional[str], stack: List[str], vbls: Optional[PARSE_VARS], conn: asyncpg.Connection
    ) -> bool:
        if not condition:
            return True

        stack.append("<conditional>")

        data = await self.parse_input(condition, stack)
        if not data or len(data) != 1 or not isinstance(data[0], (BiOpExpr, ChainedBiOpExpr)):
            raise ExecutionInterrupt("Expected a comparison", stack)

        try:
            cond = await data[0].access(self, vbls, conn)
        except ExecutionInterrupt as e:
            e.msg = e.msg.format(input=condition)
            raise

        stack.pop()
        return cond

    async def parse_input(self, parsable: str, stack: List[str], strict_errors=True) -> List[BaseAst]:
        tokens = arg_lex.run_lex(parsable)
        output: List[Union[BiOpExpr, ChainedBiOpExpr, CounterAccess, VariableAccess, Literal]] = []
        depth: List[Union[CounterAccess, VariableAccess, Literal]] = []  # noqa
        last = None

        it = iter(tokens)

        def _whitespace(token):
            if not strict_errors and not depth:
                output.append(Literal(token, stack))

        def _error(token):
            nonlocal depth, last
            if strict_errors:
                raise ExecutionInterrupt(
                    f"| {parsable}\n| {' ' * token.start}{'^' * (token.end - token.start)}\n| Unknown token", stack
                )
            else:
                try:
                    if depth:
                        depth[-1] += token.value
                    else:
                        output[-1] += token.value
                except:  # noqa
                    if depth:
                        depth.append(Literal(token, stack))
                    else:
                        output.append(Literal(token, stack))

        def _pin(token):
            nonlocal depth, last
            if not depth and isinstance(output[-1], Literal) and str(output[-1].value).endswith("\\"):
                output[-1].value = output[-1].value.rstrip("\\") + "("
                return

            if depth and last is depth[-1]:
                raise ExecutionInterrupt(
                    f"| {parsable}\n| {' '*token.start}{'^'*(token.end-token.start)}\n| Doubled in-parentheses",
                    stack,
                )

            if not isinstance(last, (CounterAccess, VariableAccess)):
                raise ExecutionInterrupt(
                    f"| {parsable}\n| {' '*token.start}{'^'*(token.end-token.start)}\n| Unexpected in-parentheses",
                    stack,
                )

            depth.append(last)

        def _pout(token):
            nonlocal depth, last
            if not depth and isinstance(output[-1], Literal) and str(output[-1].value).endswith("\\"):
                output[-1].value = output[-1].value.rstrip("\\") + ")"
                return

            if not depth:
                raise ExecutionInterrupt(
                    f"| {parsable}\n| {' '*token.start}{'^'*(token.end-token.start)}\n| Unexpected out-parentheses",
                    stack,
                )

            depth.pop()

        def _counter(token):
            nonlocal depth, last
            last = CounterAccess(token, stack)
            if depth:
                depth[-1].args.append(last)
            else:
                output.append(last)

        def _var(token):
            nonlocal depth, last
            last = VariableAccess(token, stack)
            if depth:
                depth[-1].args.append(last)
            else:
                output.append(last)

        def _literal(token):
            nonlocal depth, last
            last = Literal(token, stack)
            if depth:
                depth[-1].args.append(last)
            else:
                output.append(last)

        def _chained(token):
            nonlocal depth, last
            last = ChainedBiOpExpr(token, stack)
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
                    depth[-1].args.append(BiOpExpr(_token, stack))
                else:
                    output.append(BiOpExpr(_token, stack))

        true_output = []
        it = iter(enumerate(output))
        for i, x in it:
            if isinstance(x, BiOpExpr):
                if not true_output:
                    raise ExecutionInterrupt(
                        f"| {parsable}\n| {' '*x.token.start}{'^'*(x.token.end-x.token.start)}\n| Unexpected comparison here",
                        stack,
                    )

                x.left = true_output.pop()
                try:
                    x.right = next(it)[1]  # noqa
                except StopIteration:
                    raise ExecutionInterrupt(
                        f"| {parsable}\n| {' '*x.token.start}{'^'*(x.token.end-x.token.start)}\n| "
                        "Unexpected comparison here: missing something to compare to\n"
                        fr"| HINT: If you're not trying to compare something, escape the '{x.value}' like this: '\\{x.value}'",
                        stack,
                    )

                true_output.append(x)
                continue

            elif isinstance(x, (CounterAccess, VariableAccess, Literal, ChainedBiOpExpr)):
                true_output.append(x)

        output = true_output
        true_output = []
        it = iter(enumerate(output))

        # for those wondering, i do two loops here because i need to collect all the BiOpExprs before i can collect the ChainedBiOpExprs
        for i, x in it:
            if isinstance(x, ChainedBiOpExpr):
                if not true_output:
                    raise ExecutionInterrupt(
                        f"| {parsable}\n| {' '*x.token.start}{'^'*(x.token.end-x.token.start)}\n| Unexpected '{x.value}' here",
                        stack,
                    )

                x.left = true_output.pop()
                try:
                    x.right = next(it)[1]  # noqa
                except StopIteration:
                    raise ExecutionInterrupt(
                        f"| {parsable}\n| {' '*x.token.start}{'^'*(x.token.end-x.token.start)}\n| "
                        "Unexpected chained comparison here: missing something a comparison on the right side\n"
                        fr"| HINT: If you're not trying to chain something, escape the '{x.value}' like this: '\\{x.value}'",
                        stack,
                    )

                true_output.append(x)
                continue

            true_output.append(x)

        return true_output


class BaseAst:
    __slots__ = "value", "start", "token", "stack"

    def __init__(self, t: arg_lex.Token, stack: List[str]):
        self.stack = stack
        self.token = t
        self.value = t.value

    async def access(self, ctx: ParsingContext, vbls: Optional[PARSE_VARS], conn: asyncpg.Connection) -> Any:
        raise NotImplementedError


class CounterAccess(BaseAst):
    __slots__ = ("args",)

    def __init__(self, t: arg_lex.Token, stack: List[str]):
        super().__init__(t, stack)
        self.value = t.value.lstrip("%")
        self.args: List[BaseAst] = []

    def __repr__(self):
        return f"<CounterAccess {self.value} args={self.args}>"

    async def access(self, ctx: ParsingContext, vbls: Optional[PARSE_VARS], conn: asyncpg.Connection) -> int:
        if self.value not in ctx.counters:
            data = await conn.fetchrow(
                "SELECT * FROM counters WHERE cfg_id = $1 AND name = $2", ctx._cfg_id, self.value
            )
            if not data:
                raise ExecutionInterrupt(
                    f"| {{input}}\n| {' ' * self.token.start}{'^' * (self.token.end - self.token.start)}\n| "
                    f"Failed late to find counter '{self.value}'",
                    self.stack,
                )

            ctx.counters[self.value] = counter = ConfiguredCounter(
                name=data["name"],
                per_user=data["per_user"],
                initial_count=data["start"],
                decay_per=data["decay_per"],
                decay_rate=data["decay_rate"],
                id=data["id"],
            )

            if not counter["per_user"]:
                c = await conn.fetchval("SELECT val FROM counter_values WHERE counter_id = $1", counter["id"])
                if c is None:
                    await conn.execute(
                        "INSERT INTO counter_values VALUES ($1, $2, (NOW() AT TIME ZONE 'utc'), null)",
                        counter["id"],
                        counter["initial_count"],
                    )
                    return counter["initial_count"]
                else:
                    return c

        else:
            counter = ctx.counters[self.value]

        if counter["per_user"] and not self.args:
            raise ExecutionInterrupt(
                f"| {{input}}\n| {' ' * self.token.start}{'^' * (self.token.end - self.token.start)}\n| "
                f"No argument passed to per-user counter",
                self.stack,
            )

        elif counter["per_user"]:
            d = await self.args[0].access(ctx, vbls, conn)
            if not isinstance(d, int):
                raise ExecutionInterrupt(
                    f"| {{input}}\n| {' ' * self.args[0].token.start}{'^' * (self.args[0].token.end - self.args[0].token.start)}\n| "
                    f"Expected a user id to access per-user counter, got {d.__class__.__name__}",
                    self.stack,
                )

            return await conn.fetchval(
                "INSERT INTO counter_values VALUES ($1, $2, (now() at time zone 'utc'), $3) ON CONFLICT (counter_id, user_id) DO UPDATE set val = counter_values.val RETURNING counter_values.val",
                counter["id"],
                counter["initial_count"] or 0,
                d,
            )

        else:
            return await conn.fetchval("SELECT val FROM counter_values WHERE counter_id = $1", counter["id"])


class VariableAccess(BaseAst):
    __slots__ = ("args",)

    def __init__(self, t: arg_lex.Token, stack: List[str]):
        super().__init__(t, stack)
        self.value = t.value.lstrip("$")
        self.args: List[BaseAst] = []

    def __repr__(self):
        return f"<VariableAccess {self.value} args={self.args}>"

    async def access(
        self, ctx: ParsingContext, vbls: Optional[PARSE_VARS], conn: asyncpg.Connection
    ) -> Union[int, str, bool]:
        if self.value in FROZEN_BUILTINS:  # fast lookup
            if len(self.args) < BUILTINS[self.value][1]:
                raise ExecutionInterrupt(
                    f"| {{input}}\n| {' ' * self.token.start}{'^' * (self.token.end - self.token.start)}\n| "
                    f"Built in '{self.value}' expected at least {BUILTINS[self.value][1]} arguments, got {len(self.args)}",
                    self.stack,
                )
            return await BUILTINS[self.value][0](ctx, conn, vbls, self.stack, self.args)

        if vbls and self.value in vbls:  # potentially slow lookup
            return vbls[self.value]

        raise ExecutionInterrupt(
            f"| {{input}}\n| {' ' * self.token.start}{'^' * (self.token.end - self.token.start)}\n| "
            f"Variable '{self.value}' not found in this context",
            self.stack,
        )


class BiOpExpr(BaseAst):
    __slots__ = "left", "right"

    def __init__(self, t: arg_lex.Token, stack: List[str]):
        super().__init__(t, stack)
        self.left: Optional[BaseAst] = None
        self.right: Optional[BaseAst] = None

    def __repr__(self):
        return f"<BiOpExpr {self.value} left{self.left} right={self.right}>"

    async def access(self, ctx: ParsingContext, vbls: Optional[PARSE_VARS], conn: asyncpg.Connection) -> bool:
        condl = await self.left.access(ctx, vbls, conn)
        condr = await self.right.access(ctx, vbls, conn)
        if type(condl) != type(condr):
            raise ExecutionInterrupt(
                f"| {{input}}\n| {' '*self.token.start}{'^'*(self.token.end-self.token.start)}\n| "
                f"Cannot compare {condl.__class__.__name__} to {condr.__class__.__name__}",
                self.stack,
            )

        if type(condr) is not int and self.token.value in ("SEQ", "GEQ", "GQ", "SQ"):
            raise ExecutionInterrupt(
                f"| {{input}}\n| {' '*self.token.start}{'^'*(self.token.end-self.token.start)}\n| "
                f"Cannot apply operator '{self.token.value}' to {condr.__class__.__name__}",
                self.stack,
            )

        return getattr(self, self.token.name)(condl, condr)

    def EQ(self, l, r):  # noqa
        return l == r

    def NEQ(self, l, r):  # noqa
        return l != r

    def SEQ(self, l, r):  # noqa
        return l <= r

    def GEQ(self, l, r):  # noqa
        return l >= r

    def SQ(self, l, r):  # noqa
        return l < r

    def GQ(self, l, r):  # noqa
        return l > r

    def And(self, l, r):  # noqa
        return l and r

    def Or(self, l, r):  # noqa
        return l or r


class ChainedBiOpExpr(BaseAst):
    comps = {"And": lambda l, r: l and r, "Or": lambda l, r: l or r}

    def __init__(self, t: arg_lex.Token, stack: List[str]):
        super().__init__(t, stack)
        self.left: Optional[BaseAst] = None
        self.right: Optional[BaseAst] = None

    def __repr__(self):
        return f"<ChainedBiOpExpr {self.value} left{self.left} right={self.right}>"

    async def access(self, ctx: ParsingContext, vbls: Optional[PARSE_VARS], conn: asyncpg.Connection) -> bool:
        condl = await self.left.access(ctx, vbls, conn)
        condr = await self.right.access(ctx, vbls, conn)

        return self.comps[self.token.name](condl, condr)


class Literal(BaseAst):
    value: Union[str, int]

    def __init__(self, t: arg_lex.Token, stack: List[str]):
        super().__init__(t, stack)
        self.value = self.value.lstrip("\\").strip("'")
        try:
            self.value = int(self.value)
        except ValueError:
            pass

    def __iadd__(self, other):
        self.value += other
        return self

    def __repr__(self):
        return f"<Literal {self.value}>"

    async def access(self, ctx: ParsingContext, vbls: Optional[PARSE_VARS], conn: asyncpg.Connection) -> Any:
        return self.value


class Whitespace(BaseAst):
    async def access(self, ctx: ParsingContext, vbls: Optional[PARSE_VARS], conn: asyncpg.Connection) -> Any:
        return self.value


# builtins and stuff


async def resolve_channel(
    ctx: ParsingContext, arg: BaseAst, vbls: PARSE_VARS, conn: asyncpg.Connection, stack: List[str]
) -> discord.TextChannel:
    data = await arg.access(ctx, vbls, conn)
    if isinstance(data, int):
        if not any(x.id == arg and isinstance(x, discord.TextChannel) for x in ctx.guild.channels):
            raise ExecutionInterrupt(f"The referenced channel, {data}, is invalid (not found).", stack)

        return ctx.guild.get_channel(data)

    _arg = data.lstrip("#").lower()
    channels = tuple(x for x in ctx.guild.channels if x.name.lower() == _arg and isinstance(x, discord.TextChannel))
    if not channels:
        raise ExecutionInterrupt(f"The referenced channel, {data}, is invalid (not found).", stack)

    if len(channels) > 1:
        raise ExecutionInterrupt(
            f"| {{input}}\n| {' ' * arg.token.start}{'^' * (arg.token.end - arg.token.start)}\n| "
            f"There are multiple channels named '{_arg}'. Refusing to infer the correct one",
            arg.stack,
        )

    return channels[0]

async def resolve_role(
    ctx: ParsingContext, arg: BaseAst, vbls: PARSE_VARS, conn: asyncpg.Connection, stack: List[str]
) -> discord.Role:
    data = await arg.access(ctx, vbls, conn)
    if isinstance(arg, int):
        if not any(x.id == arg for x in ctx.guild.roles):
            raise ExecutionInterrupt(f"The referenced role, {data}, is invalid (not found).", stack)

        return ctx.guild.get_role(data)

    _arg = data.lstrip("@").lower()
    roles = tuple(x for x in ctx.guild.roles if x.name.lower() == _arg)
    if not roles:
        raise ExecutionInterrupt(f"The referenced role, {data}, is invalid (not found).", stack)

    if len(roles) > 1:
        raise ExecutionInterrupt(
            f"| {{input}}\n| {' ' * arg.token.start}{'^' * (arg.token.end - arg.token.start)}\n| "
            f"There are multiple roles named '{_arg}'. Refusing to infer the correct one",
            arg.stack,
        )

    return roles[0]



BUILTINS = dict()


def _name(n: str, args: int = None):
    def inner(func):
        if n in BUILTINS:
            raise RuntimeError(f"{n} is defined twice")

        BUILTINS[n] = func, args
        return func

    return inner


@_name("casecount", 1)
async def builtin_case_count(
    ctx: ParsingContext, conn: asyncpg.Connection, vbls: PARSE_VARS, stack: List[str], args: List[BaseAst]
):
    user = await args[0].access(ctx, vbls, conn)
    if not isinstance(user, int):
        stack.append("builtin 'casecount', argument 1")
        raise ExecutionInterrupt(f"Expected a user id, got {user.__class__.__name__}", stack)

    query = "SELECT COUNT(*) FROM cases WHERE guild_id = $1 AND user_id = $2"
    return await conn.fetchval(query, ctx.guild.id, user)


link_regex = re.compile(
    r"https?://(?:(ptb|canary|www)\.)?discord(?:app)?\.com/channels/"
    r"(?:[0-9]{15,20}|@me)"
    r"/(?P<channel_id>[0-9]{15,20})/(?P<message_id>[0-9]{15,20})/?$"
)


@_name("savecase", 5)
async def builtin_save_case(
    ctx: ParsingContext, conn: asyncpg.Connection, vbls: PARSE_VARS, stack: List[str], args: List[BaseAst]
):
    pargs = [await x.access(ctx, vbls, conn) for x in args]
    if len(pargs) != 5:
        stack.append("builtin 'savecase'")
        raise ExecutionInterrupt(f"Expected exactly 5 arguments, got {len(pargs)}", stack)

    try:
        assert isinstance(pargs[0], int), (1, f"Expected a user id, got {pargs[0].__class__.__name__}")
        assert isinstance(pargs[1], int), (2, f"Expected a user id, got {pargs[1].__class__.__name__}")
        assert isinstance(pargs[2], str), (3, f"Expected a reason (text), got {pargs[2].__class__.__name__}")
        assert isinstance(pargs[3], str) and link_regex.match(pargs[3]), (4, f"Expected a message link (text)")
        assert isinstance(pargs[4], str), (5, f"Expected a moderation action (text), got {pargs[4].__class__.__name__}")
    except AssertionError as e:
        stack.append(f"builtins 'savecase', argument {e.args[0]}")
        raise ExecutionInterrupt(e.args[1], stack)

    query = "INSERT INTO cases VALUES ($1, (SELECT MAX(id) FROM cases WHERE guild_id = $1) + 1, $2, $3, $4, $5, $6) RETURNING id"
    return await conn.fetchval(query, ctx.guild.id, *pargs)


@_name("editcase", 2)  # case id, reason, action?
async def builtin_edit_case(
    ctx: ParsingContext, conn: asyncpg.Connection, vbls: PARSE_VARS, stack: List[str], args: List[BaseAst]
):
    pargs = [await x.access(ctx, vbls, conn) for x in args]
    if 2 > len(pargs) > 3:
        stack.append("builtin 'editcase'")
        raise ExecutionInterrupt(f"Expected 2-3 arguments, got {len(pargs)}", stack)

    try:
        assert isinstance(pargs[0], int), (1, f"Expected a user id, got {pargs[0].__class__.__name__}")
        assert isinstance(pargs[1], str), (2, f"Expected a reason (text), got {pargs[1].__class__.__name__}")
        if len(pargs) > 2:
            assert isinstance(pargs[2], str), (
                3,
                f"Expected a moderation action (text), got {pargs[2].__class__.__name__}",
            )
        else:
            pargs.append(None)
    except AssertionError as e:
        stack.append(f"builtins 'editcase', argument {e.args[0]}")
        raise ExecutionInterrupt(e.args[1], stack)

    query = "UPDATE cases SET reason = $2, action = COALESCE($3, action) WHERE guild_id = $4 AND id = $1 RETURNING id"
    return await conn.fetchval(query, *pargs, ctx.guild.id) is not None


@_name("usercases", 1)
async def builtin_user_cases(
    ctx: ParsingContext, conn: asyncpg.Connection, vbls: PARSE_VARS, stack: List[str], args: List[BaseAst]
):
    user = await args[0].access(ctx, vbls, conn)
    if not isinstance(user, int):
        stack.append("builtin 'usercases', argument 1")
        raise ExecutionInterrupt(f"Expected a user id, got {user.__class__.__name__}", stack)

    query = "SELECT id FROM cases WHERE guild_id = $1 AND user_id = $2"
    data = await conn.fetch(query, ctx.guild.id, user)
    return ", ".join((x["id"] for x in data))


@_name("pick", 2)
async def builtin_random(ctx: ParsingContext, conn: asyncpg.Connection, vbls: PARSE_VARS, _, args: List[BaseAst]):
    return await random.choice(args).access(ctx, vbls, conn)


@_name("now")
async def builtin_now(*_):
    return datetime.datetime.utcnow().isoformat()


@_name("send", 2)
async def builtin_send(
    ctx: ParsingContext, conn: asyncpg.Connection, vbls: PARSE_VARS, stack: List[str], args: List[BaseAst]
):
    chnl = await resolve_channel(ctx, args[0], vbls, conn, stack)
    try:
        await chnl.send(str(await args[1].access(ctx, vbls, conn)))
    except discord.HTTPException as e:
        raise ExecutionInterrupt(e.args[0], stack)


async def make_case(
    ctx: ParsingContext, conn: asyncpg.Connection, userid: int, action: str, reason: str, modid: int = None
):
    modid = modid or ctx.bot.user.id
    query = """
    INSERT INTO
        cases
        (guild_id, id, user_id, mod_id, action, reason)
    VALUES 
        ($1, (SELECT COUNT(*) + 1 FROM cases WHERE guild_id = $1), $2, $3, $4, $5)
    RETURNING id
    """
    return await conn.fetchval(query, ctx.guild.id, userid, modid, action, reason)


@_name("kick", 1)
async def builtin_kick(
    ctx: ParsingContext, conn: asyncpg.Connection, vbls: PARSE_VARS, stack: List[str], args: List[BaseAst]
):
    user = await args[0].access(ctx, vbls, conn)
    if not isinstance(user, int):
        raise ExecutionInterrupt(f"Expected a user id, got {user.__class__.__name__}", stack)

    reason = None

    if len(args) > 1:
        reason = str(await args[1].access(ctx, vbls, conn))

    name = None
    _exs = ctx.guild.get_member(user)
    if _exs:
        name = str(_exs)

    try:
        await ctx.guild.kick(discord.Object(id=user), reason=reason)
    except discord.HTTPException as e:
        if name:
            return f"Cannot kick <@!{user}>:\n{e.args[0]}"
        else:
            return f"Cannot kick user with id {user}:\n{e.args[0]}"

    caseid = await make_case(ctx, conn, user, "kick", reason or "No reason given", modid=vbls["__callerid__"])

    if "case" in ctx.events:
        mutated = vbls.copy()
        mutated["caseid"] = caseid
        mutated["casereason"] = reason or "No reason given"
        mutated["caseaction"] = "kick"
        mutated["casemodid"] = vbls["__callerid__"]
        mutated["casemodname"] = str(ctx.guild.get_member(vbls["__callerid__"]))
        mutated["caseuserid"] = user
        mutated["caseusername"] = name

        await ctx.run_event("case", conn, stack, mutated)

    if name:
        return f"kicked <@!{user}>"
    else:
        return f"kicked user with id {user}"


@_name("ban", 1)
async def builtin_ban(
    ctx: ParsingContext, conn: asyncpg.Connection, vbls: PARSE_VARS, stack: List[str], args: List[BaseAst]
):
    user = await args[0].access(ctx, vbls, conn)
    if not isinstance(user, int):
        raise ExecutionInterrupt(f"Expected a user id, got {user.__class__.__name__}", stack)

    reason = duration = None

    if len(args) > 1:
        reason = str(await args[1].access(ctx, vbls, conn))

    if len(args) > 2:
        duration = str(await args[2].access(ctx, vbls, conn))
        try:
            duration = ShortTime(duration).dt
        except commands.BadArgument as e:
            return f"The duration ('{duration}') is invalid: {e.args[0]}"

    name = None
    _exs = ctx.guild.get_member(user)
    if _exs:
        name = str(_exs)

    timers = ctx.bot.get_cog("Timers")
    if not timers and duration:
        raise ExecutionInterrupt(
            "Failed to schedule the unban task. This is an internal error that you should not see.", stack
        )

    if duration:
        await timers.schedule_task("ban_complete", duration, conn=conn, guild_id=ctx.guild.id, user_id=user)

    try:
        await ctx.guild.ban(discord.Object(id=user), reason=reason)
    except discord.HTTPException as e:
        if name:
            return f"cannot ban <@!{user}>:\n{e.args[0]}"
        else:
            return f"cannot ban user with id {user}:\n{e.args[0]}"

    if duration:
        caseid = await make_case(ctx, conn, user, "tempban", reason or "No reason given", modid=vbls["__callerid__"])
    else:
        caseid = await make_case(ctx, conn, user, "ban", reason or "No reason given", modid=vbls["__callerid__"])

    if "case" in ctx.events:
        mutated = vbls.copy()
        mutated["caseid"] = caseid
        mutated["casereason"] = reason or "No reason given"
        mutated["caseaction"] = "ban"
        mutated["casemodid"] = vbls["__callerid__"]
        mutated["casemodname"] = str(ctx.guild.get_member(vbls["__callerid__"]))
        mutated["caseuserid"] = user
        mutated["caseusername"] = name

        await ctx.run_event("case", conn, stack, mutated)

    if name:
        return f"banned <@!{user}>"
    else:
        return f"banned user with id {user}"


@_name("mute", 1)
async def builtin_mute(
    ctx: ParsingContext, conn: asyncpg.Connection, vbls: PARSE_VARS, stack: List[str], args: List[BaseAst]
):
    user = await args[0].access(ctx, vbls, conn)
    if not isinstance(user, int):
        raise ExecutionInterrupt(f"Expected a user id, got {user.__class__.__name__}", stack)

    _arglen = len(args)
    reason = duration = None

    if _arglen > 2:
        reason = str(await args[1].access(ctx, vbls, conn))
        duration = str(await args[2].access(ctx, vbls, conn))
        try:
            duration = ShortTime(duration).dt
        except commands.BadArgument as e:
            return f"The duration ('{duration}') is invalid: {e.args[0]}"

    elif _arglen > 1:
        reason = str(await args[1].access(ctx, vbls, conn))

    mute_role: discord.Role = ctx.mute_role is not None and ctx.guild.get_role(ctx.mute_role)

    if not mute_role:
        raise ExecutionInterrupt("The configured mute role has been deleted", stack)

    if mute_role.position >= ctx.guild.me.top_role.position:
        raise ExecutionInterrupt("The configured mute role has been moved above the bots highest role", stack)

    member: discord.Member = ctx.guild.get_member(user)  # noqa

    timers = ctx.bot.get_cog("Timers")
    if not timers and duration:
        raise ExecutionInterrupt(
            "Failed to schedule the unmute task. This is an internal error that you should not see.", stack
        )

    tid = None
    if duration:
        _data = await timers.schedule_task("mute_complete", duration, conn=conn, guild_id=ctx.guild.id, user_id=user)
        tid = _data["id"]

    # TODO: if someone knows how to do this in one query feel free to do so

    exists = await conn.fetchval(
        "SELECT dispatch_id FROM mutes WHERE guild_id = $1 AND user_id = $2", ctx.guild.id, user
    )
    if exists:
        await timers.cancel_task(exists, conn=conn)

    await conn.execute(
        "INSERT INTO mutes VALUES ($1, $2, $3) ON CONFLICT (guild_id, user_id) DO UPDATE SET dispatch_id = $3",
        ctx.guild.id,
        user,
        tid,
    )

    if duration:
        caseid = await make_case(ctx, conn, user, "tempmute", reason or "No reason given", modid=vbls["__callerid__"])
    else:
        caseid = await make_case(ctx, conn, user, "mute", reason or "No reason given", modid=vbls["__callerid__"])

    if "case" in ctx.events:
        mutated = vbls.copy()
        mutated["caseid"] = caseid
        mutated["casereason"] = reason or "No reason given"
        mutated["caseaction"] = "mute" if member else "forcemute"
        mutated["casemodid"] = vbls["__callerid__"]
        mutated["casemodname"] = str(ctx.guild.get_member(vbls["__callerid__"]))
        mutated["caseuserid"] = user
        mutated["caseusername"] = member and str(member)
        mutated["muteexpires"] = "indefinitely" if not duration else f"until {duration.isoformat()}"
        mutated["muteduration"] = human_timedelta(duration)

        await ctx.run_event("case", conn, stack, mutated)

    if member:
        try:
            await member.add_roles(mute_role)
        except discord.HTTPException as e:
            return f"cannot mute <@!{user}>:\n{e.args[0]}"

    return f"muted {member}{f' until {duration.isoformat()}' if duration else ''}"


@_name("addrole", 2)
async def builtin_give_role(
    ctx: ParsingContext, conn: asyncpg.Connection, vbls: PARSE_VARS, stack: List[str], args: List[BaseAst]
):
    user = await args[0].access(ctx, vbls, conn)
    if not isinstance(user, int):
        raise ExecutionInterrupt(f"Argument 1: expected a user id, got {user.__class__.__name__}", stack)

    member = ctx.guild.get_member(user)
    if not member:
        raise ExecutionInterrupt(f"Argument 1: the given member id is invalid", stack)

    role = await args[1].access(ctx, vbls, conn)
    if not isinstance(role, int):
        raise ExecutionInterrupt(f"Argument 2: expected a role id, got {user.__class__.__name__}", stack)

    r = ctx.guild.get_role(role)
    if not r:
        raise ExecutionInterrupt(f"Argument 2: the given role id is invalid", stack)

    if r.position <= ctx.guild.me.top_role.position:
        return

    if r in member.roles: # at worst this is like 250 iterations
        return

    try:
        await member.add_roles(r)
    except discord.HTTPException:
        pass

@_name("removerole", 2)
async def builtin_give_role(
    ctx: ParsingContext, conn: asyncpg.Connection, vbls: PARSE_VARS, stack: List[str], args: List[BaseAst]
):
    user = await args[0].access(ctx, vbls, conn)
    if not isinstance(user, int):
        raise ExecutionInterrupt(f"Argument 1: expected a user id, got {user.__class__.__name__}", stack)

    member = ctx.guild.get_member(user)
    if not member:
        raise ExecutionInterrupt(f"Argument 1: the given member id is invalid", stack)

    r = await resolve_role(ctx, args[1], vbls, conn, stack)

    if r.position <= ctx.guild.me.top_role.position:
        return

    if r not in member.roles: # at worst this is like 250 iterations
        return

    try:
        await member.remove_roles(r)
    except discord.HTTPException:
        pass


@_name("coalesce")
async def builtin_first_exists(
    ctx: ParsingContext, conn: asyncpg.Connection, vbls: PARSE_VARS, stack: List[str], args: List[BaseAst]
):
    t = None
    for x in args:
        t = await x.access(ctx, vbls, conn)
        if t in vbls:
            return vbls[t]

    else:
        return t


FROZEN_BUILTINS = set(BUILTINS.keys())
