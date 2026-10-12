from __future__ import annotations

import random
import string
from dataclasses import dataclass, field

from app import game
from app.models import GameType, Player, Room


@dataclass
class RoomManager:
    rooms: dict[str, Room] = field(default_factory=dict)

    def create_room(self, game_type: GameType = "bomb_party") -> Room:
        code = self._new_code()
        room = Room(code=code, game_type=game_type)
        self.rooms[code] = room
        return room

    def get(self, code: str) -> Room | None:
        return self.rooms.get(code.upper())

    def join(self, code: str, nickname: str, player_id: str | None = None) -> tuple[Room, Player]:
        room = self.get(code)
        if not room:
            raise game.GameError("Room not found.")
        player = game.join_room(room, nickname, player_id)
        return room, player

    def _new_code(self) -> str:
        alphabet = string.ascii_uppercase + string.digits
        while True:
            code = "".join(random.choice(alphabet) for _ in range(6))
            if code not in self.rooms:
                return code
