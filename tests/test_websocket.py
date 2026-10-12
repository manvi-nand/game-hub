from fastapi.testclient import TestClient

from app.main import app, rooms


def test_websocket_join_returns_viewer_room_snapshot():
    rooms.rooms.clear()

    with TestClient(app) as client:
        created = client.post("/api/rooms").json()
        room_code = created["room_code"]

        with client.websocket_connect(f"/ws/{room_code}?nickname=Maya") as websocket:
            snapshot = websocket.receive_json()

    assert snapshot["type"] == "room_state"
    assert snapshot["viewer_id"]
    assert snapshot["room"]["code"] == room_code
    assert snapshot["room"]["players"][0]["nickname"] == "Maya"
    assert snapshot["room"]["players"][0]["is_host"] is True


def test_websocket_rejects_unknown_room():
    rooms.rooms.clear()

    with TestClient(app) as client:
        with client.websocket_connect("/ws/MISSING?nickname=Maya") as websocket:
            error = websocket.receive_json()

    assert error == {"type": "error", "message": "Room not found."}


def test_qr_endpoint_returns_svg():
    with TestClient(app) as client:
        response = client.get("/api/qr", params={"data": "http://127.0.0.1:8002/?room=PARTY1"})

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("image/svg+xml")
    assert b"<svg" in response.content


def test_create_room_accepts_game_type():
    rooms.rooms.clear()

    with TestClient(app) as client:
        created = client.post("/api/rooms", params={"game_type": "truth_or_dare"}).json()
        snapshot = client.get(f"/api/rooms/{created['room_code']}").json()

    assert snapshot["room"]["game_type"] == "truth_or_dare"
