from __future__ import annotations

from typing import Any, TYPE_CHECKING
from .enums import SourcesEnum, try_enum

if TYPE_CHECKING:
    from .type.payloads import Execute as _ExecutePayload, Parse as _ParsePayload
    from .http import HTTPHandler

__all__ = (
    "MISSING",
    "User",
    "RawMessage",
    "Message",
    "ParseData"
)

MISSING: Any = object()


class User:
    """
    Represents a user.

    Attributes
    -----------
    id: :class:`str`
        The ID of the user. On Twitch this will be the login name of the user.
        On YouTube this will be the random characters that make up a UID
    name: :class:`str`
        The name of the user. On Twitch this will be the same as the id, but potentially with capitals (some exceptions apply, don't rely on it).
        On YouTube this will be the name displayed in chat
    """
    __slots__ = ("id", "name")
    def __init__(self, userid: str, username: str):
        self.id: str = userid
        self.name: str = username

    def __repr__(self):
        return f"<User id={self.id} name={self.name}>"

class RawMessage:
    """
    The contents of a raw message.
    This could include any data event, such as an IRC event from twitch.
    It does not include chat messages. Those will appear as :class:`Message`s.

    Attributes
    -----------
    raw_data: :class:`str`
        The contents of the event
    source: :class:`~enums.SourcesEnum`
        An enum that indicates where the message came from, and whether it's a direct message
    service_type: :class:`int` | ``None``
        Honestly, no clue what this is. Waiting to hear back from the bot devs. It's probably not useful to you
    """
    __slots__ = ("raw_data", "source", "service_type", "__state")
    def __init__(self, payload: _ExecutePayload, state: HTTPHandler):
        self.raw_data: str = payload['raw_data']
        self.source: SourcesEnum = try_enum(SourcesEnum, payload['source'])
        self.service_type: int | None = payload['service_type']
        self.__state: HTTPHandler = state

    def __repr__(self):
        return f"<RawMessage source={self.source.name}>"

class Message(RawMessage):
    """
    The contents of a chat message.

    Attributes
    -----------
    content: :class:`str`
        The contents of the message
    author: :class:`User`
        The author of the message
    """
    __slots__ = ("content", "author")

    def __init__(self, payload: _ExecutePayload, state: HTTPHandler):
        super().__init__(payload, state)
        self.content: str = payload['message']
        self.author: User = User(payload['userid'], payload['username'])

    def __repr__(self):
        return f"<Message source={self.source.name} author={self.author!r}"

    async def respond(self, content: str):
        pass # TODO

class ParseData:
    """
    Contains data for processing a Parse event

    Attributes
    -----------
    target_string: :class:`str`
        The string being parsed
    trigger_string: :class:`str` | ``None``
        The trigger of this Parse event. Usually this is a chat message containing a command
    author: :class:`User`
        The author of trigger. Usually this is the author of a chat message containing a command
    target: :class:`User` | ``None``
        The person being targeted. If present, this is usually the first parameter of a command (ex. ``!hug IAmTomahawkx``)
    """
    __slots__ = ("target_string", "trigger_string", "author", "target")

    def __init__(self, payload: _ParsePayload):
        self.target_string: str = payload['string']
        self.trigger_string: str | None = payload['trigger_message']
        self.author: User = User(payload['authorid'], payload['authorname'])
        self.target: User | None = User(payload['targetid'], payload['targetname']) if payload['targetid'] else None
