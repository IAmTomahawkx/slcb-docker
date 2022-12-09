from __future__ import annotations
import traceback
from typing import TYPE_CHECKING, Awaitable, Callable

if TYPE_CHECKING:
    from .manager import Plugin, PluginManager

class InjectorLoadUnloadError(ValueError):
    pass

class Interface:
    def __init__(self, manager: PluginManager, plugin: Plugin):
        self.__manager = manager
        self.__http = manager._http
        self.__plugin = plugin
        self.__injectors = []

    async def load_injector(self, injector: Injector) -> None:
        if injector in self.__injectors:
            raise InjectorLoadUnloadError("Injector is already loaded")

        await injector._setup(self.__plugin)
        self.__injectors.append(injector)

    async def unload_injector(self, injector: Injector) -> None:
        try:
            self.__injectors.remove(injector)
        except KeyError:
            raise InjectorLoadUnloadError("Injector is not loaded")

        await injector._teardown(self.__plugin)



class Injector:
    __inject_listeners__: dict[str, Callable[[], Awaitable[None]]]

    def __new__(cls, *args, **kwargs):
        if not hasattr(cls, "__inject_listeners__"):
            cls.__inject_listeners__ = {}

        if "error" not in cls.__inject_listeners__:
            cls.__inject_listeners__["error"] = cls.on_error # TODO: does this pass self?

        return super().__new__(cls)

    async def _setup(self, plugin: Plugin) -> None:
        plugin.add_listeners(self, self.__inject_listeners__)

    async def _teardown(self, plugin: Plugin) -> None:
        plugin.remove_listeners(self.__inject_listeners__)

    @classmethod
    def listen(cls, name: str) -> Callable[[Callable[..., None]], Callable[..., None]]:
        def wrapped(meth: Callable[..., None]) -> Callable[..., None]:
            if not hasattr(cls, "__inject_listeners__"):
                cls.__inject_listeners__ = {}

            cls.__inject_listeners__[name] = meth
            return meth

        return wrapped

    async def on_error(self, event: str, exception: Exception) -> str:
        return "".join(traceback.format_exception(type(exception), exception, exception.__traceback__))