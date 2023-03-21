from __future__ import annotations
import asyncio
import logging
import secrets
import sys
import time
import uuid
from typing import TYPE_CHECKING, Any

from aiohttp import web, web_log
from .enums import AuthState

if TYPE_CHECKING:
    from .manager import PluginManager
    from .type.payloads import InboundBotPayload, InboundResponsePayload, ScriptLoadPayload, OutboundDataPayload

logger = logging.getLogger("dock.http")
access_log = logging.getLogger("dock.access")

kill_code = sys.argv[2] if len(sys.argv) >= 3 else None

class HTTPHandler:
    def __init__(self, manager: PluginManager | None):
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

        self.route_table = web.RouteTableDef()
        self.route_table.post("/auth")(self.route_auth)
        self.route_table.post("/pingpong")(self.route_pingpong)
        self.route_table.get("/kill")(self.route_kill_override)
        self.route_table.get("/authcheck")(self.route_ensure_auth)
        self.route_table.get("/outbound")(self.outbound)
        self.route_table.post("/inbound")(self.inbound)
        self.route_table.get("/inbound/parse")(self.inbound_parse)
        self.route_table.get("/inbound-ack")(self.inbound_ack)
        self.route_table.get("/inbound/load-script")(self.inbound_load_script)
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

        data: list[InboundBotPayload] = await request.json()
        for msg in data:
            self.loop.create_task(self.manager.handle_inbound(msg))

        return web.Response(status=204)

    async def inbound_parse(self, request: web.Request) -> web.Response:
        if "Authorization" not in request.headers or request.headers["Authorization"] != self._auth:
            return web.json_response({"error": "missing authorization"}, status=401)

        payload: InboundBotPayload = await request.json()
        try:
            resp = await self.manager.handle_parse(payload)
        except Exception as e:
            logger.error("Manager failed to handle inbound parse request. Falling back to input", exc_info=e)
            resp = payload['data']['string']

        return web.Response(status=200, content_type="text/plain", body=resp)

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

    async def inbound_load_script(self, request: web.Request) -> web.Response:
        if "Authorization" not in request.headers or request.headers["Authorization"] != self._auth:
            return web.json_response({"error": "missing authorization"}, status=401)

        data: ScriptLoadPayload = await request.json()
        ok, resp = await self.manager.load_plugin(data['directory'], data['script_id'])
        if ok:
            return web.Response(status=200, body=resp) # body confirms plugin id

        return web.Response(status=600, body=resp) # body contains the error message

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

    def notify_error(self, msg: str):
        self.waiting_for_poll.append({"nonce": None, "data": {"type": "error", "message": msg}})


    # --- API STUFF

    async def api_add_points(self, userid: str, username: str, amount: int) -> bool | None:
        payload = {
            "type": "AddPoints",
            "args": [userid, username, amount]
        }

        return await self.put_request(payload)

    async def api_add_all_points(self, data: dict[str, int]) -> list[str] | None:
        payload = {
            "type": "AddPointsAll",
            "args": [data]
        }

        return await self.put_request(payload)

    async def api_add_all_points_async(self, data: dict[str, int]) -> None:
        # TODO: https://streamlabs-chatbot-doc.readthedocs.io/en/latest/dev/developer.html#Dev.PythonManager.AddPointsAllAsync
        payload = {
            "type": "AddPointsAllAsync",
            "args": [data, "callable somehow?"]
        }

        return await self.put_request(payload)

    async def api_remove_points(self, userid: str, username: str, amount: int) -> bool | None:
        payload = {
            "type": "RemovePoints",
            "args": [userid, username, amount]
        }

        return await self.put_request(payload)

    async def api_remove_all_points(self, data: dict[str, int]) -> list[str] | None:
        payload = {
            "type": "RemovePointsAll",
            "args": [data]
        }

        return await self.put_request(payload)

    async def api_remove_all_points_async(self, data: dict[str, int]) -> None:
        # TODO: https://streamlabs-chatbot-doc.readthedocs.io/en/latest/dev/developer.html#Dev.PythonManager.RemovePointsAllAsync
        payload = {
            "type": "AddPointsAllAsync",
            "args": [data, "callable somehow?"]
        }

        return await self.put_request(payload)

    async def api_get_username(self, userid: str) -> str | None:
        payload = {
            "type": "GetDisplayName",
            "args": [userid]
        }

        return await self.put_request(payload)