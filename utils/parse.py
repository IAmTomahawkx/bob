from __future__ import annotations
from typing import Optional, List, Dict, Union, Any

import datetime
import re
import random
import asyncpg
import discord
import ujson
from .models import *
from deps import arg_lex
from .bot import Bot

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
    def __init__(self, bot: Bot, guild: discord.Guild, invoker: Optional[discord.Member], is_dummy=False):
        self.bot = bot
        self.dummy = is_dummy
        self.guild = guild
        self.invoker = invoker
        self._cfg_id: Optional[int] = None
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
            query = "SELECT id FROM configs WHERE guild_id = $1 ORDER BY id DESC LIMIT 1"
            cfg_id = self._cfg_id = await conn.fetchval(query, self.guild.id)

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
                        {k.strip("$"): await self.format_fmt(v, conn, stack, args) for k, v in runner["args"].items()}
                    )

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
                args.update({k.strip("$"): await self.format_fmt(v, conn, stack, args) for k, v in act["args"].items()})

            r = await self.run_action(act, conn, args, stack, i)
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
        logger = self.loggers[name]
        stack.append(f"Logger '{name}' @ event '{event}'")
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

    async def format_fmt(self, fmt: str, conn: asyncpg.Connection, stack: List[str], vbls: PARSE_VARS = None):
        stack.append(f"formatting string '{fmt}'")
        as_ast = await self.parse_input(fmt, stack, strict_errors=False)
        try:
            v = [str(await x.access(self, vbls, conn)) for x in as_ast]
        except ExecutionInterrupt as e:
            e.msg = e.msg.format(parsable=fmt)
            raise

        resp = "".join(v)
        stack.pop()
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
        stack.append(f"Edit counter {counter}")
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
            await conn.execute(
                """
                INSERT INTO counter_values VALUES (
                $1,
                ($2::INT + $3::INT),
                (NOW() AT TIME ZONE 'utc'),
                $4
                ) ON CONFLICT (counter_id, user_id) DO UPDATE SET val = counter_values.val::INT + $3::INT
                """,
                cnt["id"],
                cnt["initial_count"],
                modify,
                target,
            )
        else:
            await conn.execute("UPDATE counter_values SET val = val + $1 WHERE counter_id = $2", modify, cnt["id"])

        stack.pop()

    async def run_action(
        self, action: AnyAction, conn: asyncpg.Connection, vbls: Optional[PARSE_VARS], stack: List[str], n: int = None
    ) -> Optional[str]:
        stack = stack.copy()
        stack.append(f"action #{n} (type: {ActionTypes.reversed[action['type']]})")

        if action["type"] == ActionTypes.dispatch:
            if await self.calculate_conditional(action["condition"], stack, vbls, conn):
                await self.run_event(action["main_text"], conn, stack, vbls)

        elif action["type"] == ActionTypes.log:
            if await self.calculate_conditional(action["condition"], stack, vbls, conn):
                await self.run_logger(action["main_text"], action["event"], conn, stack, vbls)

        elif action["type"] == ActionTypes.counter:
            if await self.calculate_conditional(action["condition"], stack, vbls, conn):
                await self.alter_counter(action["main_text"], conn, stack, action["modify"], action["target"], vbls)

        elif action["type"] == ActionTypes.reply:
            if await self.calculate_conditional(action["condition"], stack, vbls, conn):
                return await self.format_fmt(action["main_text"], conn, stack, vbls)

    async def calculate_conditional(
        self, condition: Optional[str], stack: List[str], vbls: Optional[PARSE_VARS], conn: asyncpg.Connection
    ) -> bool:
        if not condition:
            return True

        stack.append("<conditional>")

        data = await self.parse_input(condition, stack)
        if not data or len(data) != 1 or not isinstance(data[0], BiOpExpr):
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
        output: List[Union[BiOpExpr, CounterAccess, VariableAccess, Literal]] = []
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

        typs = {
            "Whitespace": _whitespace,
            "Var": _var,
            "Counter": _counter,
            "POut": _pout,
            "PIn": _pin,
            "Literal": _literal,
            "Error": _error,
        }
        oprs = {"EQ", "NEQ", "SEQ", "GEQ", "SQ", "GQ", "And", "Or"}
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
                        "Unexpected comparison here (missing something to compare to)",
                        stack,
                    )

                true_output.append(x)
                continue

            elif isinstance(x, (CounterAccess, VariableAccess, Literal)):
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
                "",
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
        if self.value in FROZEN_BUILTINS: # fast lookup
            if len(self.args) < BUILTINS[self.value][1]:
                raise ExecutionInterrupt(
                    f"| {{parsable}}\n| {' ' * self.token.start}{'^' * (self.token.end - self.token.start)}\n| "
                    f"Built in '{self.value}' expected at least {BUILTINS[self.value][1]} arguments, got {len(self.args)}",
                    self.stack,
                )
            return await BUILTINS[self.value][0](ctx, conn, vbls, self.args)

        if vbls and self.value in vbls: # potentially slow lookup
            return vbls[self.value]

        raise ExecutionInterrupt(
            f"| {{parsable}}\n| {' ' * self.token.start}{'^' * (self.token.end - self.token.start)}\n| "
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

    def EQ(self, l, r): # noqa
        return l == r

    def NEQ(self, l, r): # noqa
        return l != r

    def SEQ(self, l, r): # noqa
        return l <= r

    def GEQ(self, l, r): # noqa
        return l >= r

    def SQ(self, l, r): # noqa
        return l < r

    def GQ(self, l, r): # noqa
        return l > r

    def And(self, l, r): # noqa
        return l and r

    def Or(self, l, r): # noqa
        return l or r


class Literal(BaseAst):
    def __init__(self, t: arg_lex.Token, stack: List[str]):
        super().__init__(t, stack)
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

BUILTINS = dict()

def _name(n: str, args: int = None):
    def inner(func):
        if n in BUILTINS:
            raise RuntimeError(f"{n} is defined twice")

        BUILTINS[n] = func, args
        return func
    return inner

@_name("casecount", 1)
async def builtin_case_count(ctx: ParsingContext, conn: asyncpg.Connection, vbls: PARSE_VARS, stack: List[str], args: List[BaseAst]):
    user = await args[0].access(ctx, vbls, conn)
    if not isinstance(user, int):
        stack.append("builtin 'casecount', argument 1")
        raise ExecutionInterrupt(f"Expected a user id, got {user.__class__.__name__}", stack)

    query = "SELECT COUNT(*) FROM cases WHERE guild_id = $1 AND user_id = $2"
    return await conn.fetchval(query, ctx.guild.id, user)

link_regex = re.compile(
    r'https?://(?:(ptb|canary|www)\.)?discord(?:app)?\.com/channels/'
    r'(?:[0-9]{15,20}|@me)'
    r'/(?P<channel_id>[0-9]{15,20})/(?P<message_id>[0-9]{15,20})/?$'
)

@_name("savecase", 5)
async def builtin_save_case(ctx: ParsingContext, conn: asyncpg.Connection, vbls: PARSE_VARS, stack: List[str], args: List[BaseAst]):
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

@_name("editcase", 2) # case id, reason, action?
async def builtin_edit_case(ctx: ParsingContext, conn: asyncpg.Connection, vbls: PARSE_VARS, stack: List[str], args: List[BaseAst]):
    pargs = [await x.access(ctx, vbls, conn) for x in args]
    if 2 > len(pargs) > 3:
        stack.append("builtin 'editcase'")
        raise ExecutionInterrupt(f"Expected 2-3 arguments, got {len(pargs)}", stack)

    try:
        assert isinstance(pargs[0], int), (1, f"Expected a user id, got {pargs[0].__class__.__name__}")
        assert isinstance(pargs[1], str), (2, f"Expected a reason (text), got {pargs[1].__class__.__name__}")
        if len(pargs) > 2:
            assert isinstance(pargs[2], str), (3, f"Expected a moderation action (text), got {pargs[2].__class__.__name__}")
        else:
            pargs.append(None)
    except AssertionError as e:
        stack.append(f"builtins 'editcase', argument {e.args[0]}")
        raise ExecutionInterrupt(e.args[1], stack)

    query = "UPDATE cases SET reason = $2, action = COALESCE($3, action) WHERE guild_id = $4 AND id = $1 RETURNING id"
    return await conn.fetchval(query, *pargs, ctx.guild.id) is not None

@_name("usercases", 1)
async def builtin_user_cases(ctx: ParsingContext, conn: asyncpg.Connection, vbls: PARSE_VARS, stack: List[str], args: List[BaseAst]):
    user = await args[0].access(ctx, vbls, conn)
    if not isinstance(user, int):
        stack.append("builtin 'usercases', argument 1")
        raise ExecutionInterrupt(f"Expected a user id, got {user.__class__.__name__}", stack)

    query = "SELECT id FROM cases WHERE guild_id = $1 AND user_id = $2"
    data = await conn.fetch(query, ctx.guild.id, user)
    return ", ".join((x['id'] for x in data))

@_name("pick", 2)
async def builtin_random(ctx: ParsingContext, conn: asyncpg.Connection, vbls: PARSE_VARS, _, args: List[BaseAst]):
    return await random.choice(args).access(ctx, vbls, conn)

@_name("now")
async def builtin_now(*_):
    return datetime.datetime.utcnow().isoformat()

FROZEN_BUILTINS = set(BUILTINS.keys())