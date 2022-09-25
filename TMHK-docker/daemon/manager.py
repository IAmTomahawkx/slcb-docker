from __future__ import annotations

import asyncio
import importlib
import os
import traceback
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Awaitable, Callable, Any

import interface
from common import MISSING
import ujson

if TYPE_CHECKING:
    from http import HTTPHandler

    from type.plugin import Config, PluginModule, UIConfig

DIR = Path(".")

class PluginLoadFailed(ValueError):
    def __init__(self, script_name: str, error: str, traceback: str | None = None):
        self.message = f"Failed to load script '{script_name}': {error}"
        self.original_traceback = traceback
        super().__init__(self.message)


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

        self.meta: PluginMeta | None = None
        self._listeners: dict[str, list[Callable[..., Awaitable[None]]]] = {}

    async def load(self, script_id: str | None) -> tuple[bool, str]:
        try:
            await self.try_load(script_id)
        except PluginLoadFailed as e:
            if self._listeners:
                await self.eject_listeners()

            if e.original_traceback:
                return False, f"{e.message}\n{e.original_traceback}"

            return False, e.message

        return True, self.meta.script_id

    def add_listeners(self, listeners: dict[str, Callable[..., Awaitable[None]]]):
        for name, cb in listeners.items():
            if name not in self._listeners:
                self._listeners[name] = []

            self._listeners[name].append(cb)

    def remove_listeners(self, listeners: dict[str, Callable[..., Awaitable[None]]]):
        for name, cb in listeners.items():
            if name not in self._listeners:
                continue

            try:
                self._listeners[name].remove(cb)
            except ValueError:
                continue

    async def try_load(self, script_id: str | None):
        files = set(os.listdir(self.directory))
        if "plugin.json" not in files:
            raise PluginLoadFailed(f"@{self.directory.name}", "directory does not contain a plugin.json file.")

        try:
            with (self.directory / "plugin.json").open() as f:
                config = self.config = ujson.loads(f.read())
        except:
            raise PluginLoadFailed(f"@{self.directory.name}", "unable to load plugin.json")

        try:
            self.meta = PluginMeta(config, script_id)
        except KeyError as e:
            raise PluginLoadFailed(f"@{self.directory.name}", f"plugin.json is missing key: {e.args[0]}")

        if ".__dock_store" not in files and not self.meta.script_id:
            script_id = str(uuid.uuid4())
            with (self.directory / ".__dock_store").open(mode="w") as f:
                f.write(script_id)

            self.meta.script_id = script_id

        elif ".__dock_store" not in files:
            with (self.directory / ".__dock_store").open() as f:
                self.meta.script_id = f.read()

        if "init.py" not in files:
            raise PluginLoadFailed(self.meta.name, "no init.py file found")

        try:
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
            module.init(self.interface)
        except Exception as e:
            trace = traceback.format_exception(type(e), e, e.__traceback__)
            raise PluginLoadFailed(self.meta.name, "Encountered an error while calling init", "".join(trace))

    async def eject_listeners(self):
        await self.call_listeners("unload")
        self._listeners.clear()

    async def eject(self):
        await self.eject_listeners()

    async def call_error_listeners(self, event: str, error: Exception):
        if "error" not in self._listeners: # edge case
            return

        caller = self._listeners["error"][0]
        try:
            try:
                response = await caller(event, error)
            except Exception as e:
                raise e from error
        except Exception as e: # we want to catch the double traceback to pass to the user
            response = "An error occurred in the error handler\n" + "".join(traceback.format_exception(type(e), e, e.__traceback__))

        if len(self._listeners["error"]) > 1:
            response += "\n\nMultiple error handlers registered. Only one will be used, and this message will not go away until there is only one"

        await self._manager._http.notify_error(response)

    async def call_listeners(self, event: str, data: Any = MISSING):
        if event in self._listeners:
            for caller in self._listeners[event]:
                try:
                    if data is not MISSING:
                        await caller(data)
                    else:
                        await caller()
                except Exception as e:
                    asyncio.create_task(self.call_error_listeners(event, e))


class PluginManager:
    def __init__(self, http: HTTPHandler):
        self.plugins = {}
        self._http = http

    async def handle_message(self, payload):
        pass

    async def load_script(self, directory: str, script_id: str | None) -> tuple[bool, str]:
        pth = DIR / "plugins" / directory
        if not pth.exists():
            return False, "The given directory does not exist"

        plug = Plugin(pth, self)
        ok, resp = await plug.load(script_id)
        if not ok:
            return ok, resp

        self.plugins[plug.meta.script_id] = plug
        return ok, resp

    async def unload_script(self, reload: bool):
        ... # TODO
