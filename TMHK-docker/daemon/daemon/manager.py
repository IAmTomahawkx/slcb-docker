from __future__ import annotations

import asyncio
import importlib
import logging
import os
import traceback
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Awaitable, Callable, Any

from . import interface
from .common import MISSING, RawMessage, Message, ParseData
from .enums import PayloadTypeEnum, try_enum
import ujson

if TYPE_CHECKING:
    from http import HTTPHandler

    from .type.payloads import GenericInboundBotPayload, InboundBotPayload, Parse as ParsePayload, InboundParsePayload
    from .type.plugin import Config, PluginModule, UIConfig
    from .interface import Injector

DIR = Path(".")
logger = logging.getLogger("dock.pluginmanager")

class PluginLoadFailed(ValueError):
    def __init__(self, script_name: str, error: str, traceback: str | None = None):
        self.message = f"Failed to load script '{script_name}': {error}"
        self.original_traceback = traceback
        super().__init__(self.message)

class PreLoadFailure(PluginLoadFailed):
    pass

class PluginMeta:
    def __init__(self, cfg: Config, script_id: str | None):
        self.name: str = cfg["name"]
        self.description: str = cfg["description"]
        self.author: str = cfg["author"]
        self.version: str = cfg["version"]

        self.config: UIConfig | None = cfg.get("ui_config")
        self.dock_version: str | None = cfg.get("dock_version")

        self.script_id: str = script_id  # type: ignore


class Plugin:
    def __init__(self, directory: Path, manager: PluginManager):
        self._manager: PluginManager = manager
        self.directory: Path = directory
        self.config: Config | None = None
        self.module: PluginModule | None = None
        self.interface: interface.Interface = interface.Interface(manager, self)
        self.enabled: bool = False # set to false by default

        self.meta: PluginMeta | None = None
        self._listeners: dict[str, list[tuple[Injector | None, Callable[..., Awaitable[None]]]]] = {}

        self._is_loaded: bool = False

    async def load(self, script_id: str | None) -> tuple[bool | Ellipsis, str]:
        try:
            await self.load_meta(script_id)
            if self.directory.name != self.meta.script_id:
                new = self.directory.parent / self.meta.script_id
                self.directory.rename(new)
                self.directory = new

            await self.try_load()
        except PreLoadFailure as e:
            return ..., f"Could not identify the plugin for loading:\n{e.message}"
        except PluginLoadFailed as e:
            if self._listeners:
                await self.eject_listeners()

            if e.original_traceback:
                return False, f"{e.message}\n{e.original_traceback}"

            return False, e.message

        self._is_loaded = True
        return True, self.meta.script_id

    def add_listeners(self, injector: Injector, listeners: dict[str, Callable[..., Awaitable[None]]]):
        for name, cb in listeners.items():
            if name not in self._listeners:
                self._listeners[name] = []

            self._listeners[name].append((injector, cb))

    def remove_listeners(self, listeners: dict[str, Callable[..., Awaitable[None]]]):
        for name, cb in listeners.items():
            if name not in self._listeners:
                continue

            try:
                self._listeners[name].remove(cb)
            except ValueError:
                continue

    async def load_meta(self, script_id: str | None) -> None:
        files = set(os.listdir(self.directory))
        if "plugin.json" not in files:
            raise PreLoadFailure(f"@{self.directory.name}", "directory does not contain a plugin.json file.")

        try:
            with (self.directory / "plugin.json").open() as f:
                config = self.config = ujson.loads(f.read())
        except:
            raise PreLoadFailure(f"@{self.directory.name}", "unable to load plugin.json")

        try:
            self.meta = PluginMeta(config, script_id)
        except KeyError as e:
            raise PreLoadFailure(f"@{self.directory.name}", f"plugin.json is missing key: {e.args[0]}")

        if ".__dock_store" not in files and not self.meta.script_id:
            script_id = str(uuid.uuid4()).replace("-", "")
            with (self.directory / ".__dock_store").open(mode="w") as f:
                f.write(script_id)

            self.meta.script_id = script_id

        elif ".__dock_store" not in files:
            with (self.directory / ".__dock_store").open() as f:
                self.meta.script_id = f.read()

        if "init.py" not in files:
            raise PreLoadFailure(self.meta.name, "no init.py file found")

    async def try_load(self):
        try:
            if self.module:
                module: PluginModule = importlib.reload(self.module) # type: ignore
            else:
                module: PluginModule = importlib.import_module(f"plugins.{self.directory.name}.init")  # type: ignore
            self.module = module
        except BaseException as e:
            split = '  File "<frozen importlib._bootstrap>", line 241, in _call_with_frames_removed\n'
            trace = traceback.format_exception(type(e), e, e.__traceback__)
            idx = trace.index(split)
            trace = trace[idx + 1 :]
            trace.insert(0, "Traceback (most recent call last):\n")
            raise PluginLoadFailed(self.meta.name, "Failed to load module", "".join(trace))

        try:
            await module.init(self.interface)
        except Exception as e:
            trace = traceback.format_exception(type(e), e, e.__traceback__)
            raise PluginLoadFailed(self.meta.name, "Encountered an error while calling init", "".join(trace))

    async def eject_listeners(self):
        await self.call_listeners("unload")
        self._listeners.clear()

    async def eject(self):
        self._is_loaded = False
        await self.eject_listeners()

    async def call_error_listeners(self, event: str, error: Exception):
        if "error" not in self._listeners: # edge case
            return

        cls, caller = self._listeners["error"][0]
        try:
            try:
                if cls:
                    response = await caller(cls, event, error)
                else:
                    response = await caller(event, error)
            except Exception as e:
                raise e from error
        except Exception as e: # we want to catch the double traceback to pass to the user
            response = "An error occurred in the error handler\n" + "".join(traceback.format_exception(type(e), e, e.__traceback__))

        if len(self._listeners["error"]) > 1:
            response += "\n\nMultiple error handlers registered. Only one will be used, and this message will not go away until there is only one"

        self._manager._http.notify_error(self.meta.script_id, response)

    async def call_listeners(self, event: str, data: Any = MISSING):
        if event in self._listeners:
            for cls, caller in self._listeners[event]:
                try:
                    if data is not MISSING:
                        await caller(cls, data)
                    else:
                        await caller(cls)
                except Exception as e:
                    asyncio.create_task(self.call_error_listeners(event, e))

    @property
    def has_parse_hook(self):
        return "parse" in self._listeners and self._listeners["parse"]

    async def call_parse_hook(self, payload: ParsePayload) -> str:
        if not self.has_parse_hook:
            return payload['string']

        hook = self._listeners["parse"][0]
        obj: ParseData = ParseData(payload)
        try:
            if hook[0]:
                return str(await hook[1](hook[0], obj))
            else:
                return str(await hook[1](obj))
        except Exception as e:
            asyncio.create_task(self.call_error_listeners("parse", e))
            return payload['string']


class PluginManager:
    def __init__(self, http: HTTPHandler):
        self.plugins = {}
        self._http = http

    async def _execute_callback(self, plugin: Plugin, payload: GenericInboundBotPayload):
        if payload['data']['is_raw']:
            message = RawMessage(payload['data'], self._http)
            await plugin.call_listeners("raw_message", data=message)
        else:
            message = Message(payload['data'], self._http)
            await plugin.call_listeners("message", data=message)
    async def handle_inbound(self, payload: GenericInboundBotPayload | InboundBotPayload) -> None:
        if payload['type'] == 0:
            for plugin in self.plugins.values():
                if plugin.enabled:
                    asyncio.create_task(self._execute_callback(plugin, payload))

            return

        sid = payload.get('script_id')
        if sid is None:
            ...

        if sid not in self.plugins:
            logger.warning("Inbound payload referencing unknown plugin %s. Discarding", sid)
    async def handle_parse(self, payload: InboundParsePayload) -> str:
        type_ = try_enum(PayloadTypeEnum, payload['type'])
        if type_ is not PayloadTypeEnum.parse:
            raise TypeError(f"Payload of type {type_.name} ({type_.value}) passed to handle_parse") # type: ignore # pycharm sucks

        data: ParsePayload = payload['data']

        for _ in range(2):
            for plugin in self.plugins.values():
                if not plugin.has_parse_hook:
                    continue

                data["string"] = await plugin.call_parse_hook(data)

        return data["string"]

    async def handle_button(self, payload: InboundBotPayload) -> None:
        type_ = try_enum(PayloadTypeEnum, payload['type'])
        if type_ is not PayloadTypeEnum.button:
            raise TypeError(
                f"Payload of type {type_.name} ({type_.value}) passed to handle_button")  # type: ignore # pycharm sucks

        sid: str = payload['plugin_id']
        if sid not in self.plugins:
            logger.warning("Inbound button payload referencing unknown plugin %s. Discarding", sid)
            raise ValueError("Unknown plugin id")

        plugin: Plugin = self.plugins[sid]

        logger.debug("Calling handlers for button: %s", payload["data"]["element"])
        await plugin.call_listeners(f"button", payload["data"]["element"])

    async def load_plugin(self, directory: str, plugin_id: str | None) -> tuple[bool, str | None, str]:
        if plugin_id and plugin_id in self.plugins:
            return False, None, "Plugin is already loaded"

        pth = DIR / "plugins" / directory
        if not pth.exists():
            return False, None, "The given directory does not exist"

        plug = Plugin(pth, self)
        ok, resp = await plug.load(plugin_id)
        if ok is not ...: # we want to attach the plugin to the dock if at all possible, as this allows the dev to reload it from the ui
            self.plugins[plug.meta.script_id] = plug
        else:
            ok = False

        try:
            sid = plug.meta.script_id
        except:
            sid = None

        return ok, sid, resp

    async def reload_plugin(self, script_id: str) -> tuple[bool, str]:
        if script_id not in self.plugins:
            return False, "Script is not loaded in the dock"

        plug: Plugin = self.plugins[script_id]
        if plug._is_loaded: # call cleanup hooks
            await plug.eject()

        try:
            await plug.try_load()
        except PluginLoadFailed as e:
            if e.original_traceback:
                return False, f"{e.message}\n{e.original_traceback}"

            return False, e.message

    async def unload_plugin(self, script_id: str):
        if script_id not in self.plugins:
            return False, "Script has not been loaded into the dock"

        plug: Plugin = self.plugins[script_id]
        if not plug._is_loaded:
            return False, "Script is not actively loaded"

    async def evict_plugins(self):
        """
        ungracefully ejects all plugins without calling their cleanup hooks.
        Should not be used when running normally
        """
        ... # TODO

    async def graceful_shutdown(self, has_connection: bool = True):
        ... # TODO

