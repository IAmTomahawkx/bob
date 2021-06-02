from discord import Enum
from typing import TypedDict, Optional, List, Union, Dict

__all__ = (
    "CounterAction",
    "DispatchAction",
    "LogAction",
    "DoAction",
    "Actions",
    "SelfRole",
    "SelfRoleMode",
    "ConfigCounter",
    "ConfigEvent",
    "Command",
    "CommandArgument",
    "CommandArgumentType",
    "Logger",
    "Automod",
    "AutomodIgnore",
    "GuildConfig",
)


class CounterAction(TypedDict):
    counter: str
    modify: int
    condition: str
    target: Optional[str]


class DispatchAction(TypedDict):
    dispatch: str
    condition: Optional[str]


class LogAction(TypedDict):
    log: str
    event: str
    condition: Optional[str]


class DoAction(TypedDict):
    do: str
    condition: Optional[str]


Actions = Union[CounterAction, DispatchAction, LogAction, DoAction]


class SelfRoleMode(Enum):
    reaction = "reaction"
    button = "button"
    command = "command"

    def to_int(self):
        if self is SelfRoleMode.reaction:
            return 1
        elif self is SelfRoleMode.button:
            return 2
        return 3

    @staticmethod
    def from_int(n: int) -> "SelfRoleMode":
        if n == 1:
            return SelfRoleMode.reaction  # noqa
        elif n == 2:
            return SelfRoleMode.button  # noqa
        elif n == 3:
            return SelfRoleMode.command  # noqa
        else:
            raise ValueError("Number was not a valid mode")


class SelfRole(TypedDict):
    mode: SelfRoleMode
    roles: List[int]
    optin: bool
    optout: bool
    channel: Optional[int]
    emoji: Optional[Union[str, int]]
    message: Optional[int]


class ConfigCounter(TypedDict):
    name: str
    per_user: bool
    initial_count: int
    decay_rate: Optional[int]
    decay_per: Optional[int]


class ConfigEvent(TypedDict):
    name: str
    actions: List[Actions]


class Logger(TypedDict):
    name: str
    channel: int
    format: Union[Dict[str, str], str]


class CommandArgumentType(Enum):
    user = "user"
    chan = "channel"
    role = "role"
    num = "number"
    text = "text"


class CommandArgument(TypedDict):
    name: str
    type: CommandArgumentType
    consume: int


class Command(TypedDict):
    name: str
    arguments: List[CommandArgument]
    actions: List[Union[Actions, str]]


class AutomodIgnore(TypedDict):
    roles: Optional[List[int]]
    channels: Optional[List[int]]


class Automod(TypedDict):
    event: str
    ignore: Optional[AutomodIgnore]
    actions: List[Actions]


class GuildConfig:
    def __init__(self, guild_id: int):
        self.guild_id = guild_id
        self.selfroles: List[SelfRole] = []
        self.counters: List[ConfigCounter] = []
        self.events = []
        self.automod_events = []
        self.loggers = {}
        self.commands = {}
