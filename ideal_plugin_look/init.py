from __future__ import annotations

import traceback
from daemon.common import RawMessage, Message, ParseData
from daemon.interface import Injector, Interface

async def init(parent: Interface) -> None:
    await parent.load_injector(MyInjector(parent))

class MyInjector(Injector):
    def __init__(self, parent: Interface):
        self.parent: Interface = parent

    async def on_error(self, event: str, exception: Exception) -> str:
        tb = ''.join(
            traceback.format_exception(type(exception), exception, exception.__traceback__)
        )
        return f"Error in event: {event}:\n{tb}"

    @Injector.listen("message")
    async def on_message(self, msg: Message):
        if "hi" in msg.content:
            await msg.respond("hi @{msg.author_name}")

    @Injector.listen("raw_message")
    async def got_a_raw_message(self, msg: RawMessage):
        pass

    @Injector.listen("parse")
    async def special_parse_hook(self, msg: ParseData) -> str:
        return msg.target_string.replace("$coolparameter", "that was cool")

    @Injector.listen("disable")
    async def script_disabled(self):
        pass

    @Injector.listen("enable")
    async def script_enabled(self):
        pass
