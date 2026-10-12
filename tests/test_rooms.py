import pytest

from app.game import GameError
from app.rooms import RoomManager


def test_create_room_generates_unique_six_character_codes():
    manager = RoomManager()

    first = manager.create_room()
    second = manager.create_room()

    assert first.code != second.code
    assert len(first.code) == 6
    assert len(second.code) == 6
    assert first.code in manager.rooms
    assert second.code in manager.rooms


def test_create_room_can_select_game_type():
    manager = RoomManager()

    room = manager.create_room("truth_or_dare")

    assert room.game_type == "truth_or_dare"


def test_join_requires_existing_room():
    manager = RoomManager()

    with pytest.raises(GameError):
        manager.join("party1", "Maya")

    room = manager.create_room()
    joined_room, player = manager.join(room.code.lower(), "Maya")

    assert joined_room == room
    assert player.nickname == "Maya"
