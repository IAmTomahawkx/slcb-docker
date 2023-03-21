from __future__ import annotations
import traceback
from typing import TYPE_CHECKING, Awaitable, Callable

if TYPE_CHECKING:
    from .manager import Plugin, PluginManager
    from .http import HTTPHandler

class InjectorLoadUnloadError(ValueError):
    pass

class Interface:
    def __init__(self, manager: PluginManager, plugin: Plugin):
        self.__manager: PluginManager = manager
        self.__http: HTTPHandler = manager._http
        self.__plugin: Plugin = plugin
        self.__injectors: list[Injector] = []

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

    async def get_username(self, userid: str) -> str | None:
        """|coro|

        Fetches the user's username from the bot.

        Parameters
        ----------
        userid: :class:`str`
            The id of the user to fetch. On twitch this is usually, but not always, the lowercase version of their username.

        Returns
        --------
        :class:`str` | ``None``
            The user's display name. Could return ``None`` if the operation fails.
        """
        return await self.__http.api_get_username(userid)

    async def add_points(self, userid: str, username: str, amount: int) -> bool | None:
        """|coro|

        Adds points to a user.

        Parameters
        ----------
        userid: :class:`str`
            The user's ID.
        username: :class:`str`
            The user's display name. This can be retrived via :func:`~Interface.get_username`.
        amount: :class:`int`
            The amount of currency to add to the user.

        Returns
        --------
        :class:`bool` | ``None``
            Whether the operation was successful. Could return ``None`` if the operation fails to return to the dock.
        """
        return await self.__http.api_add_points(userid, username, amount)

    async def add_points_all(self, amounts: dict[str, int]) -> None:
        """|coro|

        Adds points to multiple users. Can be used to add points to a large amount of users.

        Parameters
        ----------
        amounts: dict[:class:`str`, :class:`int`]
            A dict of userid: amount.
        """
        return await self.__http.api_add_all_points(amounts)

    # TODO: add_points_all_async

    async def remove_points(self, userid: str, username: str, amount: int) -> bool | None:
        """|coro|

        Removes points from a user.

        Parameters
        ----------
        userid: :class:`str`
            The user's ID.
        username: :class:`str`
            The user's display name. This can be retrived via :func:`~Interface.get_username`.
        amount: :class:`int`
            The amount of currency to remove from the user.

        Returns
        --------
        :class:`bool` | ``None``
            Whether the operation was successful. Could return ``None`` if the operation fails to return to the dock.
        """
        return await self.__http.api_remove_points(userid, username, amount)

    async def remove_points_all(self, amounts: dict[str, int]) -> None:
        """|coro|

        Adds points to multiple users. Can be used to add points to a large amount of users.

        Parameters
        ----------
        amounts: dict[:class:`str`, :class:`int`]
            A dict of userid: amount.
        """
        return await self.__http.api_remove_all_points(amounts)



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