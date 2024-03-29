from __future__ import annotations
import asyncio
import json
import logging
import secrets
import sys
import time
import uuid
from os import PathLike
from typing import TYPE_CHECKING, Any, Literal, TypedDict

from aiohttp import web, web_log
from .enums import AuthState

if TYPE_CHECKING:
    from .manager import PluginManager
    from .type.payloads import InboundBotPayload, InboundParsePayload, InboundResponsePayload, ScriptLoadPayload, ScriptUnloadPayload, OutboundDataPayload

logger = logging.getLogger("dock.http")
access_log = logging.getLogger("dock.access")

kill_code = sys.argv[2] if len(sys.argv) >= 3 else None

class NowPlaying(TypedDict):
    Key: str
    Value: str

class HTTPHandler:
    def __init__(self, manager: PluginManager | None, version: str, version_tuple: tuple[int, int, int]):
        self.manager: PluginManager | None = manager
        self._auth: str | None = None
        self._auth_state: AuthState | None = None
        self._auth_event: asyncio.Event | None = None
        self.server: web.Application | None = None
        self.__runner: web.AppRunner | None = None
        self.__site: web.TCPSite | None = None
        self.challenge: str | None = None
        self.last_poll: int | None = None
        self.nonces: dict[str, asyncio.Future] = dict()
        self.waiting_for_poll: list[dict[str, Any]] = []

        self.version: str = version
        self.version_tuple: tuple[int, int, int] = version_tuple

        self.route_table = web.RouteTableDef()
        self.route_table.get("/version")(self.route_version)
        self.route_table.post("/auth")(self.route_auth)
        self.route_table.post("/pingpong")(self.route_pingpong)
        self.route_table.get("/kill")(self.route_kill_override)
        self.route_table.get("/authcheck")(self.route_ensure_auth)
        self.route_table.get("/outbound")(self.outbound)
        self.route_table.post("/inbound")(self.inbound)
        self.route_table.post("/inbound/parse")(self.inbound_parse)
        self.route_table.post("/inbound/button")(self.inbound_button)
        self.route_table.get("/inbound-ack")(self.inbound_ack)
        self.route_table.post("/inbound/load-plugin")(self.inbound_load_plugin)
        self.route_table.post("/inbound/reload-plugin")(self.inbound_reload_plugin)
        #self.route_table.get("/inbound/unload-script")(self.inbound_unload_script) # TODO

    @property
    def auth_state(self):
        return self._auth_state

    @auth_state.setter
    def auth_state(self, value: AuthState):
        if self._auth_state is None:
            logger.debug("Setting initial AuthState to %d (%s)", value.value, value.name) # noqa
        else:
            logger.debug("Changing AuthState from %d (%s) to %d (%s)",
                        self._auth_state.value, self._auth_state.name, value.value, value.name) # noqa
        self._auth_state = value

    async def setup(self):
        self.loop = asyncio.get_running_loop()
        self._auth_event = asyncio.Event()
        self.auth_state = AuthState.WaitingForClient
        self.server = web.Application(loop=self.loop)
        self.server.add_routes(self.route_table)

        logger.debug("HTTPHandler ready for service")

    async def start_service(self, debug: bool):
        if not self.server:
            raise RuntimeError("Call to start_service before call to setup")

        kwargs = {
            "keepalive_timeout": 75,
            "handle_signals": False
        }

        if debug:
            kwargs["access_log_class"] = web_log.AccessLogger
            kwargs["access_log_format"] = web_log.AccessLogger.LOG_FORMAT
            kwargs["access_log"] = access_log

        runner = self.__runner = web.AppRunner(self.server, **kwargs)

        await runner.setup()

        site = self.__site = web.TCPSite(runner, host="127.0.0.1", port=1006)
        await site.start()
        self.auth_state = AuthState.PendingPingPong

    async def end_service(self, error=True):
        if not self.__site or not self.__runner:
            if error:
                raise RuntimeError("Call to end_service with no active server")

            return

        logger.info("Received call to end service")
        await self.__runner.cleanup()
        self.__site = None
        self.__runner = None
        self.auth_state = AuthState.Closing
        self._auth = None

    async def wait_for_pingpong(self, timeout: int | None = None):
        if self.auth_state == AuthState.AuthOK:
            return

        while self._auth_event is None:
            raise RuntimeError("Call to wait_for_pingpong before setup")

        if timeout:
            return await asyncio.wait_for(self._auth_event.wait(), timeout=timeout)

        return await self._auth_event.wait()

    async def route_version(self, request: web.Request) -> web.Response:
        return web.json_response({"version": self.version, "comparable_version": self.version_tuple})

    async def route_auth(self, request: web.Request) -> web.Response:
        if self._auth:
            logger.debug("Received AUTH setup, but auth is already set!")
            return web.Response(status=401, body="Auth already set")

        data = await request.json()
        code = data["code"]
        self._auth = code # TODO: need a more resilient authorization method
        self.auth_state = AuthState.PendingPingPong
        challenge = self.challenge = secrets.token_urlsafe(16)
        logger.debug("Received AUTH setup with code %s. Responding with challenge %s", code, challenge)
        return web.json_response({"challenge": challenge})

    async def route_pingpong(self, request: web.Request) -> web.Response:
        if "Authorization" not in request.headers or request.headers["Authorization"] != self._auth:
            return web.json_response({"error": "missing authorization"}, status=401)

        if self.challenge is None:
            logger.debug("Received pingpong, but no challenge is pending")
            return web.Response(status=404)

        data = await request.json()
        challenge = data["challenge"]

        if challenge != self.challenge:
            logger.warning("Received invalid challenge %s, expected %s", challenge, self.challenge)
            self.auth_state = AuthState.ClientServerMismatch
            self._auth_event.set()

            return web.Response(status=400, body="Failed pingpong")

        logger.debug("Received pingpong with OK challenge response %s", challenge)
        self.auth_state = AuthState.AuthOK
        self._auth_event.set()

        return web.Response(status=204)

    async def route_kill_override(self, request: web.Request) -> web.Response:
        if not kill_code:
            return web.json_response({"error": "killcode not provided on startup"}, status=401)

        if "code" not in request.query or request.query["code"] != kill_code:
            return web.json_response({"error": "missing code"}, status=401)

        graceful = request.query.get("graceful", "1") != "0"

        logger.info("Received call to kill server (graceful=%s)", "yes" if graceful else "no")
        async def to_call():
            if graceful:
                await self.manager.graceful_shutdown()
            else:
                await self.manager.evict_plugins()
                await self.end_service()

            await self.end_service()

        def cb():
            self.loop.create_task(to_call())

        self.loop.call_later(1, cb)
        return web.Response(status=204)

    async def route_ensure_auth(self, request: web.Request) -> web.Response:
        if "Authorization" not in request.headers or request.headers["Authorization"] != self._auth:
            return web.json_response({"error": "bad authorization"}, status=401)

        return web.Response(status=204)


    async def outbound(self, request: web.Request) -> web.Response:
        if "Authorization" not in request.headers or request.headers["Authorization"] != self._auth:
            return web.json_response({"error": "missing authorization"}, status=401)

        resp = web.json_response(self.waiting_for_poll.copy())
        self.waiting_for_poll.clear()
        self.last_poll = int(time.time())
        return resp

    async def inbound(self, request: web.Request) -> web.Response:
        if "Authorization" not in request.headers or request.headers["Authorization"] != self._auth:
            return web.json_response({"error": "missing authorization"}, status=401)

        data: InboundBotPayload = await request.json()
        self.loop.create_task(self.manager.handle_inbound(data))

        return web.Response(status=204)

    async def inbound_parse(self, request: web.Request) -> web.Response:
        if "Authorization" not in request.headers or request.headers["Authorization"] != self._auth:
            return web.json_response({"error": "missing authorization"}, status=401)

        payload: InboundParsePayload = await request.json()
        try:
            resp = await self.manager.handle_parse(payload)
        except Exception as e:
            logger.error("Manager failed to handle inbound parse request. Falling back to input", exc_info=e)
            resp = payload['data']['string']

        return web.json_response({"text": resp})

    async def inbound_button(self, request: web.Request) -> web.Response:
        if "Authorization" not in request.headers or request.headers["Authorization"] != self._auth:
            return web.json_response({"error": "missing authorization"}, status=401)

        payload: InboundBotPayload = await request.json()
        await self.manager.handle_button(payload)
        return web.Response(status=204)

    async def inbound_ack(self, request: web.Request) -> web.Response:
        if "Authorization" not in request.headers or request.headers["Authorization"] != self._auth:
            return web.json_response({"error": "missing authorization"}, status=401)

        data: list[InboundResponsePayload] = (await request.json())["response"]
        for msg in data:
            if msg["nonce"] in self.nonces:
                fut = self.nonces.pop(msg["nonce"])
                fut.set_result(msg["response"]) # TODO deal with error field

            else:
                logger.warning(f"Received response for unknown nonce '{msg['nonce']}'")

        return web.Response(status=204)

    async def inbound_load_plugin(self, request: web.Request) -> web.Response:
        if "Authorization" not in request.headers or request.headers["Authorization"] != self._auth:
            return web.json_response({"error": "missing authorization"}, status=401)

        data: ScriptLoadPayload = await request.json()
        ok, sid, resp = await self.manager.load_plugin(data['directory'], data['plugin_id'])
        if ok:
            return web.json_response({"id": resp})

        return web.json_response({"id": sid, "error": resp}, status=203)

    async def inbound_reload_plugin(self, request: web.Request) -> web.Response:
        if "Authorization" not in request.headers or request.headers["Authorization"] != self._auth:
            return web.json_response({"error": "missing authorization"}, status=401)

        data: ScriptUnloadPayload = await request.json()
        ok, reason = await self.manager.reload_plugin(data["plugin_id"])
        if ok:
            return web.Response(status=204)

        return web.json_response({"error": reason}, status=203)

    async def put_request(self, payload: OutboundDataPayload, timeout: float = 5.0) -> Any:
        nonce = str(uuid.uuid4())
        waiter = self.loop.create_future()
        self.nonces[nonce] = waiter
        self.waiting_for_poll.append({"nonce": nonce, "data": payload})

        try:
            response = await asyncio.wait_for(waiter, timeout=timeout)
        except asyncio.CancelledError:
            logger.warning("Timed out waiting for nonce %s", nonce)
            del self.nonces[nonce]
            return None

        return response

    def notify_error(self, plugin_id: str, msg: str):
        self.waiting_for_poll.append({"nonce": None, "data": {"type": "@error", "plugin_id": plugin_id, "message": msg}})

    def send_log(self, plugin_id: str, msg: str) -> None:
        self.waiting_for_poll.append({"nonce": None, "data": {"type": "@log", "plugin_id": plugin_id, "message": msg}})

    # --- API STUFF

    async def get_currency_name(self) -> str:
        payload = {
            "type": "GetCurrencyName",
            "args": []
        }

        return await self.put_request(payload)

    async def add_points(self, userid: str, username: str, amount: int) -> bool:
        payload = {
            "type": "AddPoints",
            "args": [userid, username, amount]
        }

        return await self.put_request(payload)

    async def remove_points(self, userid: str, username: str, amount: int) -> bool:
        payload = {
            "type": "RemovePoints",
            "args": [userid, username, amount]
        }

        return await self.put_request(payload)

    async def add_points_all(self, users: dict[str, int]) -> list[str]:
        payload = {
            "type": "AddPointsAll",
            "args": [users]
        }

        return await self.put_request(payload) # returns failed users

    async def remove_points_all(self, users: dict[str, int]) -> list[str]:
        payload = {
            "type": "RemovePointsAll",
            "args": [users]
        }

        return await self.put_request(payload) # returns failed users

    async def get_points(self, userid: str) -> int:
        payload = {
            "type": "GetPoints",
            "args": [userid]
        }

        return await self.put_request(payload)

    async def get_rank(self, userid: str) -> str:
        payload = {
            "type": "GetRank",
            "args": [userid]
        }

        return await self.put_request(payload)

    async def get_hours(self, userid: str) -> float:
        payload = {
            "type": "GetHours",
            "args": [userid]
        }

        return await self.put_request(payload)

    async def get_currency_users(self, userids: list[str]) -> Any: # TODO need a currency object to deserialize
        payload = {
            "type": "GetCurrencyUsers",
            "args": [userids]
        }

        return await self.put_request(payload)

    # stream related stuff

    async def send_stream_message(self, text: str) -> None:
        payload = {
            "type": "SendStreamMessage",
            "args": [text]
        }

        return await self.put_request(payload)

    async def send_stream_whisper(self, text: str) -> None:
        payload = {
            "type": "SendStreamWhisper",
            "args": [text]
        }

        return await self.put_request(payload)

    async def send_discord_message(self, text: str) -> None:
        payload = {
            "type": "SendDiscordMessage",
            "args": [text]
        }

        return await self.put_request(payload)

    async def send_discord_dm(self, text: str) -> None:
        payload = {
            "type": "SendDiscordDM",
            "args": [text]
        }

        return await self.put_request(payload)

    async def broadcast_ws_event(self, event_name: str, data: dict) -> None:
        payload = {
            "type": "BroadcastWSEvent",
            "args": [event_name, json.dumps(data)]
        }

        return await self.put_request(payload)

    async def has_permission(self, userid: str, permission: str, additional_info: str | None) -> bool:
        payload = {
            "type": "HasPermission",
            "args": [userid, permission, additional_info or ""]
        }

        return await self.put_request(payload)

    async def get_viewer_list(self) -> list[str]:
        payload = {
            "type": "GetViewerList",
            "args": []
        }

        return await self.put_request(payload)

    async def get_active_viewer_list(self) -> list[str]:
        payload = {
            "type": "GetActiveViewers",
            "args": []
        }

        return await self.put_request(payload)

    async def get_random_active_viewer(self) -> str:
        payload = {
            "type": "GetRandomActiveViewer",
            "args": []
        }

        return await self.put_request(payload)

    async def get_display_name(self, userid: str) -> str:
        payload = {
            "type": "GetDisplayName",
            "args": [userid]
        }

        return await self.put_request(payload)

    async def is_live(self) -> bool:
        payload = {
            "type": "IsLive",
            "args": []
        }

        return await self.put_request(payload)

    async def get_streaming_service(self) -> Literal["twitch", "youtube"]:
        payload = {
            "type": "GetStreamingService",
            "args": []
        }

        return await self.put_request(payload)

    async def get_channel_name(self) -> str: # note: only works on twitch
        payload = {
            "type": "GetChannelName",
            "args": []
        }

        return await self.put_request(payload)

    async def play_sound(self, filepath: PathLike, volume: int) -> bool: # volume between 0-100
        payload = {
            "type": "PlaySound",
            "args": [str(filepath), volume/100]
        }

        return await self.put_request(payload)

    async def get_queue_entries(self, n: int) -> dict[int, str]:
        payload = {
            "type": "GetQueue",
            "args": [n]
        }

        return await self.put_request(payload)

    async def get_song_queue(self, n: int) -> Any: # TODO: need song object
        payload = {
            "type": "GetSongQueue",
            "args": [n]
        }

        return await self.put_request(payload)

    async def get_playlist_queue(self, n: int) -> Any: # TODO: need song object
        payload = {
            "type": "GetSongPlaylist",
            "args": [n]
        }

        return await self.put_request(payload)

    async def get_now_playing(self) -> NowPlaying:
        payload = {
            "type": "GetNowPlaying",
            "args": []
        }

        return await self.put_request(payload)