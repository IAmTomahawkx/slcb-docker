from typing import Any, Literal, TypedDict

ExecuteSources = Literal[0, 1, 2, 3, 4]  # twitch, discord, youtube, twitchDM, discordDM
PayloadType = Literal[0, 1, 2, 3, 4] # execute, parse, state, reload, button
Reload = dict[str, str | int | bool]


class Execute(TypedDict):
    userid: str
    username: str
    message: str
    raw_data: str
    is_raw: bool
    is_chat: bool
    source: ExecuteSources


class Parse(TypedDict):
    string: str
    trigger_message: str | None
    authorid: str
    authorname: str
    targetid: str | None
    targetname: str | None


class StateToggle(TypedDict):
    state: bool

class ButtonClick(TypedDict):
    element: str

class GenericInboundBotPayload(TypedDict):
    type: Literal[0]
    data: Execute

class InboundBotPayload(TypedDict):
    plugin_id: str
    type: PayloadType
    data: Execute | Reload | Parse | StateToggle | ButtonClick


class InboundResponsePayload(TypedDict):
    nonce: str
    response: Any

class OutboundDataPayload(TypedDict):
    type: str
    args: list[Any]

class OutboundPayload(TypedDict):
    nonce: str
    data: OutboundDataPayload

class ScriptLoadPayload(TypedDict):
    plugin_id: str | None
    directory: str

class ScriptUnloadPayload(TypedDict):
    plugin_id: str
