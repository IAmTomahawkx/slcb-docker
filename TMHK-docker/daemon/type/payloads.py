from typing import Any, Literal, TypedDict

ExecuteSources = Literal[0, 1, 2]  # twitch, discord, youtube
Reload = dict[str, str | int | bool]


class Execute(TypedDict):
    userid: str
    username: str
    message: str
    raw_data: str
    is_raw: bool
    is_dm: bool
    source: ExecuteSources
    service_type: int  # seriously have no clue what this is


class Parse(TypedDict):
    string: str
    trigger_message: str | None
    authorid: str
    authorname: str
    targetid: str | None
    targetname: str | None


class StateToggle(TypedDict):
    state: bool


class InboundBotPayload(TypedDict):
    script_id: str
    data: Execute | Reload | Parse | StateToggle


class InboundResponsePayload(TypedDict):
    nonce: str
    response: Any


class OutboundPayload(TypedDict):
    nonce: str

class ScriptLoadPayload(TypedDict):
    script_id: str | None
    directory: str

class ScriptUnloadPayload(TypedDict):
    script_id: str
    reload: bool
