from __future__ import annotations

import traceback
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from interface import Injector, Interface

async def setup(parent: Interface) -> None:
    await parent.set_injector(MyInjector(parent))

class MyInjector(Injector):
    def __init__(self, parent: Interface):
        self.parent: Interface = parent

    @Injector.listen("message")
    async def on_message(self, msg):
        if "hi" in msg.content:
            await msg.respond("hi @{msg.author_name}")

    @Injector.listen("disable")
    async def script_disabled(self):
        pass

    @Injector.listen("enable")
    async def script_enabled(self):
        pass

    async def on_error(self, event: str, exception: Exception) -> str:
        tb = ''.join(
            traceback.format_exception(type(exception), exception, exception.__traceback__)
        )
        return f"Error in event: {event}:\n{tb}"
