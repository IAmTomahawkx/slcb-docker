from __future__ import annotations
import traceback
from typing import TYPE_CHECKING, Awaitable, Callable

if TYPE_CHECKING:
    from manager import Plugin, PluginManager


class Interface:
    def __init__(self, manager: PluginManager, plugin: Plugin):
        self.__manager = manager
        self.__http = manager._http
        self.__plugin = plugin

    async def set_injector(self, injector: Injector):
        await injector._setup(self.__plugin)


class Injector:
    __inject_listeners__: dict[str, Callable[[], Awaitable[None]]]

    def __new__(cls, *args, **kwargs):
        if not hasattr(cls, "__inject_listeners__"):
            cls.__inject_listeners__ = {}

        if "error" not in cls.__inject_listeners__:
            cls.__inject_listeners__["error"] = cls.on_error # TODO: does this pass self?

        return super().__new__(cls, *args, **kwargs)

    async def _setup(self, plugin: Plugin) -> None:
        plugin.add_listeners(self.__inject_listeners__)

    @staticmethod
    def listen(name: str):
        def wrapped(meth):
            cls = meth.__class__
            if not hasattr(cls, "__inject_listeners__"):
                cls.__inject_listeners__ = {}

            cls.__inject_listeners__[name] = meth
            return meth

        return wrapped

    async def on_error(self, event: str, exception: Exception) -> str:
        return "".join(traceback.format_exception(type(exception), exception, exception.__traceback__))