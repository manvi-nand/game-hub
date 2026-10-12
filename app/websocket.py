from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from fastapi import WebSocket
from starlette.websockets import WebSocketDisconnect

from app.game import now_ms
from app.models import Room


@dataclass(eq=False)
class Client:
    websocket: WebSocket
    player_id: str


class ConnectionManager:
    def __init__(self) -> None:
        self._clients: dict[str, set[Client]] = defaultdict(set)

    async def connect(self, room_code: str, websocket: WebSocket, player_id: str) -> Client:
        await websocket.accept()
        client = Client(websocket=websocket, player_id=player_id)
        self._clients[room_code].add(client)
        return client

    def disconnect(self, room_code: str, client: Client) -> None:
        self._clients[room_code].discard(client)
        if not self._clients[room_code]:
            self._clients.pop(room_code, None)

    async def send_error(self, websocket: WebSocket, message: str) -> None:
        await websocket.send_json({"type": "error", "message": message})

    async def broadcast(self, room: Room) -> None:
        clients = list(self._clients.get(room.code, set()))
        stale: list[Client] = []
        timestamp = now_ms()
        for client in clients:
            try:
                await client.websocket.send_json(room.to_snapshot(client.player_id, timestamp))
            except WebSocketDisconnect:
                stale.append(client)
            except RuntimeError:
                stale.append(client)

        for client in stale:
            self.disconnect(room.code, client)
