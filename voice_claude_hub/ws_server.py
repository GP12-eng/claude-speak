"""WebSocket server with client registry and typed message dispatch."""
from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any, Callable

import websockets
from websockets.server import WebSocketServerProtocol

from .models import ClientType

logger = logging.getLogger(__name__)

Handler = Callable[..., Any]


@dataclass
class Client:
    ws: WebSocketServerProtocol
    client_type: ClientType
    client_id: str


class ClientRegistry:
    def __init__(self) -> None:
        self._clients: dict[str, Client] = {}

    def register(self, client_id: str, ws: WebSocketServerProtocol, ctype: ClientType) -> None:
        self._clients[client_id] = Client(ws=ws, client_type=ctype, client_id=client_id)
        logger.info("Client connected: %s (%s)", client_id, ctype.value)

    def remove(self, client_id: str) -> None:
        self._clients.pop(client_id, None)
        logger.info("Client disconnected: %s", client_id)

    async def broadcast(self, msg_type: str, payload: dict[str, Any], exclude: str | None = None) -> None:
        message = json.dumps({"type": msg_type, "payload": payload, "ts": time.time()})
        dead: list[str] = []
        for cid, client in self._clients.items():
            if cid == exclude:
                continue
            try:
                await client.ws.send(message)
            except websockets.ConnectionClosed:
                dead.append(cid)
        for cid in dead:
            self.remove(cid)

    async def send_to(self, client_id: str, msg_type: str, payload: dict[str, Any]) -> None:
        client = self._clients.get(client_id)
        if not client:
            return
        message = json.dumps({"type": msg_type, "payload": payload, "ts": time.time()})
        try:
            await client.ws.send(message)
        except websockets.ConnectionClosed:
            self.remove(client_id)

    async def send_binary(self, client_id: str, data: bytes) -> None:
        client = self._clients.get(client_id)
        if not client:
            return
        try:
            await client.ws.send(data)
        except websockets.ConnectionClosed:
            self.remove(client_id)

    @property
    def count(self) -> int:
        return len(self._clients)


class HubServer:
    def __init__(self, host: str = "0.0.0.0", port: int = 9877) -> None:
        self.host = host
        self.port = port
        self.registry = ClientRegistry()
        self._msg_handlers: dict[str, Handler] = {}

    def on(self, msg_type: str) -> Callable[[Handler], Handler]:
        def decorator(func: Handler) -> Handler:
            self._msg_handlers[msg_type] = func
            return func

        return decorator

    async def _handle_client(self, ws: WebSocketServerProtocol) -> None:
        client_id = f"{ws.remote_address[0]}:{ws.remote_address[1]}"
        ctype = ClientType.BALL  # default; VSCode/mobile set via registration message

        try:
            async for raw in ws:
                try:
                    msg = json.loads(raw)
                    msg_type = msg.get("type", "")
                    payload = msg.get("payload", {})

                    if msg_type == "register":
                        ctype = ClientType(payload.get("client_type", "ball"))
                        client_id = payload.get("client_id", client_id)
                        self.registry.register(client_id, ws, ctype)
                        await self.registry.send_to(client_id, "registered", {"client_id": client_id})
                        continue

                    handler = self._msg_handlers.get(msg_type)
                    if handler:
                        await handler(client_id, payload)
                except json.JSONDecodeError:
                    logger.warning("Invalid JSON from %s", client_id)
        except websockets.ConnectionClosed:
            pass
        finally:
            self.registry.remove(client_id)

    async def start(self) -> None:
        logger.info("Hub WebSocket server starting on %s:%d", self.host, self.port)
        async with websockets.serve(self._handle_client, self.host, self.port):
            await asyncio.Future()  # run forever
