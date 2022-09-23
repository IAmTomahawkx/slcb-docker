import asyncio
import logging
import uuid
from typing import TYPE_CHECKING, Any

from aiohttp import web

if TYPE_CHECKING:
    from manager import PluginManager
    from type.payloads import InboundBotPayload, InboundResponsePayload, ScriptLoadPayload, ScriptUnloadPayload

logger = logging.getLogger("dock.http")


class HTTPHandler:
    def __init__(self, manager: PluginManager):
        self.manager: PluginManager = manager
        self.auth_state = None
        self.server: web.Application | None = None
        self.nonces: dict[str, asyncio.Future] = dict()
        self.waiting_for_poll: list[dict[str, Any]] = []

        self.route_table = web.RouteTableDef()
        self.route_table.get("/outbound")(self.outbound)
        self.route_table.get("/inbound")(self.inbound)
        self.route_table.get("/inbound-ack")(self.inbound_ack)
        self.route_table.get("/inbound/load-script")(self.inbound_load_script)
        self.route_table.get("/inbound/unload-script")(self.inbound_unload_script)

    async def setup(self):
        self.loop = asyncio.get_running_loop()
        self.server = web.Application(loop=self.loop)
        self.server.add_routes(self.route_table)

    async def outbound(self, request: web.Request) -> web.Response:
        if "Authorization" not in request.headers or request.headers["Authorization"] != self.auth_state:
            return web.json_response({"error": "missing authorization"}, status=401)

        resp = web.json_response(self.waiting_for_poll.copy())
        self.waiting_for_poll.clear()
        return resp

    async def inbound(self, request: web.Request) -> web.Response:
        if "Authorization" not in request.headers or request.headers["Authorization"] != self.auth_state:
            return web.json_response({"error": "missing authorization"}, status=401)

        data: list[InboundBotPayload] = await request.json()
        for msg in data:
            self.loop.create_task(self.manager.handle_message(msg))

        return web.Response(status=204)

    async def inbound_ack(self, request: web.Request) -> web.Response:
        if "Authorization" not in request.headers or request.headers["Authorization"] != self.auth_state:
            return web.json_response({"error": "missing authorization"}, status=401)

        data: list[InboundResponsePayload] = await request.json()
        for msg in data:
            if msg["nonce"] in self.nonces:
                fut = self.nonces.pop(msg["nonce"])
                fut.set_result(msg["response"])

            else:
                logger.warning(f"Received response for unknown nonce '{msg['nonce']}'")

        return web.Response(status=204)

    async def inbound_load_script(self, request: web.Request) -> web.Response:
        if "Authorization" not in request.headers or request.headers["Authorization"] != self.auth_state:
            return web.json_response({"error": "missing authorization"}, status=401)

        data: ScriptLoadPayload = await request.json()
        resp = await self.manager.load_script(data['directory'], data['script_id'])


    async def put_request(self, payload: dict[str, Any], timeout: float = 5.0) -> Any:
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
