from discord import Enum
from typing import TypedDict, Optional, List, Union, Dict

__all__ = (
    "AnyAction",
    "ActionTypes",
    "CounterAction",
    "ConfiguredCounter",
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
    "ReplyAction",
)


class ActionTypes:
    counter = 1
    dispatch = 2
    log = 3
    do = 4
    reply = 5
    reversed = {1: "counter", 2: "dispatch", 3: "log", 4: "do", 5: "reply"}


class AnyAction(TypedDict):
    id: int
    type: int
    main_text: str
    condition: Optional[str]
    modify: Optional[int]
    target: Optional[str]
    event: Optional[str]
    args: Optional[Dict[str, Union[str, int, bool]]]


class ReplyAction(TypedDict):
    reply: str
    condition: Optional[str]
    args: Optional[Dict[str, Union[str, int, bool]]]


class CounterAction(TypedDict):
    counter: str
    modify: int
    condition: Optional[str]
    target: Optional[str]
    args: Optional[Dict[str, Union[str, int, bool]]]


class DispatchAction(TypedDict):
    dispatch: str
    condition: Optional[str]
    args: Optional[Dict[str, Union[str, int, bool]]]


class LogAction(TypedDict):
    log: str
    event: str
    condition: Optional[str]
    args: Optional[Dict[str, Union[str, int, bool]]]


class DoAction(TypedDict):
    do: str
    condition: Optional[str]
    args: Optional[Dict[str, Union[str, int, bool]]]


Actions = Union[CounterAction, DispatchAction, LogAction, DoAction, ReplyAction]


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


class ConfiguredCounter(ConfigCounter):
    id: int


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
    optional: bool


class Command(TypedDict):
    name: str
    arguments: List[CommandArgument]
    actions: List[Union[Actions, str]]


class AutomodIgnore(TypedDict):
    roles: Optional[List[int]]
    channels: Optional[List[int]]


class Automod(TypedDict):
    event: str
    ignore: AutomodIgnore
    actions: List[Actions]


class GuildConfig:
    def __init__(self, guild_id: int):
        self.guild_id = guild_id
        self.error_channel: Optional[int] = None
        self.mute_role: Optional[int] = None
        self.id: Optional[int] = None
        self.selfroles: List[SelfRole] = []
        self.counters: Dict[str, ConfigCounter] = {}
        self.events = []
        self.automod_events: Dict[str, Automod] = {}
        self.loggers = {}
        self.commands: Dict[str, Command] = {}


class SparseGuildConfig:
    def __init__(self, guild_id: int):
        self.guild_id = guild_id
        self.error_channel: Optional[int] = None
        self.counters: List[str] = []
        self.events: List[str] = []
        self.loggers: List[str] = []
        self.commands: List[str] = []
