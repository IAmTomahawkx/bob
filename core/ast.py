from __future__ import annotations
from typing import List, Any, Optional, Dict, Union, TYPE_CHECKING

import asyncpg

from deps import arg_lex

if TYPE_CHECKING:
    from .parse import ParsingContext

__all__ = (
    "PARSE_VARS",
    "BaseAst",
    "CounterAccess",
    "VariableAccess",
    "BiOpExpr",
    "ChainedBiOpExpr",
    "Literal",
    "Whitespace",
)

PARSE_VARS = Optional[Dict[str, Union[str, int, bool]]]


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
