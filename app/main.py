from __future__ import annotations

import asyncio
import io
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Query, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from dotenv import load_dotenv
import qrcode
import qrcode.image.svg

from app import game
from app.game import GameError
from app.rooms import RoomManager
from app.websocket import ConnectionManager

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")
rooms = RoomManager()
connections = ConnectionManager()
state_lock = asyncio.Lock()


async def timeout_watcher() -> None:
    while True:
        changed_rooms = []
        async with state_lock:
            timestamp = game.now_ms()
            for room in rooms.rooms.values():
                if game.resolve_timeout(room, timestamp):
                    changed_rooms.append(room)

        for room in changed_rooms:
            await connections.broadcast(room)

        await asyncio.sleep(0.2)


@asynccontextmanager
async def lifespan(app: FastAPI):
    watcher = asyncio.create_task(timeout_watcher())
    try:
        yield
    finally:
        watcher.cancel()
        try:
            await watcher
        except asyncio.CancelledError:
            pass


app = FastAPI(title="Bomb Party", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(BASE_DIR / "templates" / "index.html")


@app.post("/api/rooms")
async def create_room(game_type: str = Query("bomb_party")) -> JSONResponse:
    async with state_lock:
        room = rooms.create_room(game.normalize_game_type(game_type))
    return JSONResponse({"room_code": room.code, "join_url": f"/?room={room.code}"})


@app.get("/api/qr")
async def qr_code(data: str) -> Response:
    if not data or len(data) > 500:
        return JSONResponse({"error": "Invalid QR data."}, status_code=400)

    image = qrcode.make(data, image_factory=qrcode.image.svg.SvgPathImage)
    buffer = io.BytesIO()
    image.save(buffer)
    return Response(content=buffer.getvalue(), media_type="image/svg+xml")


@app.get("/api/rooms/{room_code}")
async def get_room(room_code: str) -> JSONResponse:
    async with state_lock:
        room = rooms.get(room_code)
        if not room:
            return JSONResponse({"error": "Room not found."}, status_code=404)
        snapshot = room.to_snapshot(None, game.now_ms())
    return JSONResponse(snapshot)


@app.websocket("/ws/{room_code}")
async def websocket_endpoint(websocket: WebSocket, room_code: str) -> None:
    nickname = websocket.query_params.get("nickname", "Player")
    player_id = websocket.query_params.get("player_id") or None

    async with state_lock:
        try:
            room, player = rooms.join(room_code, nickname, player_id)
        except GameError as exc:
            await websocket.accept()
            await connections.send_error(websocket, str(exc))
            await websocket.close()
            return

    client = await connections.connect(room.code, websocket, player.id)
    await connections.broadcast(room)

    try:
        while True:
            payload = await websocket.receive_json()
            action = payload.get("action")
            changed = False
            async with state_lock:
                try:
                    if action == "start_game":
                        game.start_game(room, player.id)
                        changed = True
                    elif action == "pass_turn":
                        game.pass_turn(room, player.id)
                        changed = True
                    elif action == "play_again":
                        game.play_again(room, player.id)
                        changed = True
                    elif action == "configure_truth_or_dare":
                        settings = payload.get("settings") or {}
                        game.configure_truth_or_dare(
                            room,
                            player.id,
                            str(settings.get("scenario") or ""),
                            str(settings.get("intensity") or ""),
                            str(settings.get("mode") or ""),
                        )
                        changed = True
                    elif action == "start_truth_or_dare":
                        game.start_truth_or_dare(room, player.id)
                        changed = True
                    elif action == "choose_truth_or_dare":
                        game.choose_truth_or_dare(
                            room,
                            player.id,
                            str(payload.get("prompt_type") or ""),
                        )
                        changed = True
                    elif action == "skip_truth_or_dare_prompt":
                        game.skip_truth_or_dare_prompt(room, player.id)
                        changed = True
                    elif action == "next_truth_or_dare_turn":
                        game.next_truth_or_dare_turn(room, player.id)
                        changed = True
                    elif action == "end_truth_or_dare":
                        game.end_truth_or_dare(room, player.id)
                        changed = True
                    elif action == "update_settings":
                        settings = payload.get("settings") or {}
                        try:
                            fuse_min_seconds = int(
                                settings.get("fuse_min_seconds", room.fuse_min_ms // 1000)
                            )
                            fuse_max_seconds = int(
                                settings.get("fuse_max_seconds", room.fuse_max_ms // 1000)
                            )
                        except (TypeError, ValueError):
                            raise GameError("Fuse controls must be numbers.")
                        game.update_settings(
                            room,
                            player.id,
                            fuse_min_seconds,
                            fuse_max_seconds,
                            settings.get("custom_categories") or [],
                        )
                        changed = True
                    elif action == "set_game_type":
                        game.set_game_type(room, player.id, str(payload.get("game_type") or ""))
                        changed = True
                    elif action == "set_room_locked":
                        game.set_room_locked(room, player.id, bool(payload.get("locked")))
                        changed = True
                    elif action == "rename_player":
                        game.rename_player(
                            room,
                            player.id,
                            str(payload.get("target_player_id") or ""),
                            str(payload.get("nickname") or ""),
                        )
                        changed = True
                    elif action == "remove_player":
                        game.remove_player(
                            room,
                            player.id,
                            str(payload.get("target_player_id") or ""),
                        )
                        changed = True
                    elif action == "transfer_host":
                        game.transfer_host(
                            room,
                            player.id,
                            str(payload.get("target_player_id") or ""),
                        )
                        changed = True
                    elif action == "move_player":
                        game.move_player(
                            room,
                            player.id,
                            str(payload.get("target_player_id") or ""),
                            str(payload.get("direction") or ""),
                        )
                        changed = True
                    elif action == "shuffle_players":
                        game.shuffle_players(room, player.id)
                        changed = True
                    elif action == "sync":
                        changed = True
                    else:
                        await connections.send_error(websocket, "Unknown action.")
                except GameError as exc:
                    await connections.send_error(websocket, str(exc))

            if changed:
                await connections.broadcast(room)
    except WebSocketDisconnect:
        pass
    finally:
        connections.disconnect(room.code, client)
        async with state_lock:
            game.mark_disconnected(room, player.id)
        await connections.broadcast(room)
