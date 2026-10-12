from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal
from uuid import uuid4


Phase = Literal["lobby", "game", "gameover"]
GameType = Literal["bomb_party", "truth_or_dare"]
TodIntensity = Literal["mild", "medium", "wild"]
TodMode = Literal["mixed", "truth", "dare"]
TodPromptType = Literal["truth", "dare"]
BOMB_LETTERS = ("B", "O", "M", "B")


@dataclass
class Player:
    nickname: str
    id: str = field(default_factory=lambda: uuid4().hex)
    letters: str = ""
    eliminated: bool = False
    connected: bool = True
    is_host: bool = False

    @property
    def initials(self) -> str:
        clean = self.nickname.strip()
        return clean[:1].upper() if clean else "?"

    def to_public_dict(self) -> dict:
        return {
            "id": self.id,
            "nickname": self.nickname,
            "initials": self.initials,
            "letters": self.letters,
            "eliminated": self.eliminated,
            "connected": self.connected,
            "is_host": self.is_host,
        }


@dataclass
class TruthOrDareSession:
    scenario: str = ""
    intensity: TodIntensity = "medium"
    mode: TodMode = "mixed"
    truth_queue: list[str] = field(default_factory=list)
    dare_queue: list[str] = field(default_factory=list)
    used_prompts: list[str] = field(default_factory=list)
    current_prompt_type: TodPromptType | None = None
    current_prompt_text: str | None = None
    waiting_for_choice: bool = True

    def to_public_dict(self) -> dict:
        return {
            "scenario": self.scenario,
            "intensity": self.intensity,
            "mode": self.mode,
            "truth_queue_count": len(self.truth_queue),
            "dare_queue_count": len(self.dare_queue),
            "used_prompt_count": len(self.used_prompts),
            "current_prompt_type": self.current_prompt_type,
            "current_prompt_text": self.current_prompt_text,
            "waiting_for_choice": self.waiting_for_choice,
        }


@dataclass
class Room:
    code: str
    game_type: GameType = "bomb_party"
    players: list[Player] = field(default_factory=list)
    phase: Phase = "lobby"
    locked: bool = False
    fuse_min_ms: int = 10_000
    fuse_max_ms: int = 40_000
    custom_categories: list[str] = field(default_factory=list)
    current_player_index: int = 0
    current_category: str | None = None
    deadline_timestamp_ms: int | None = None
    fuse_duration_ms: int | None = None
    used_categories: list[str] = field(default_factory=list)
    winner_id: str | None = None
    last_event: dict | None = None
    truth_or_dare: TruthOrDareSession = field(default_factory=TruthOrDareSession)

    def active_players(self) -> list[Player]:
        return [player for player in self.players if not player.eliminated]

    def current_player(self) -> Player | None:
        if self.phase != "game" or not self.players:
            return None
        if self.current_player_index >= len(self.players):
            return None
        return self.players[self.current_player_index]

    def get_player(self, player_id: str) -> Player | None:
        return next((player for player in self.players if player.id == player_id), None)

    def to_snapshot(self, viewer_id: str | None, server_time_ms: int) -> dict:
        current = self.current_player()
        return {
            "type": "room_state",
            "server_time_ms": server_time_ms,
            "viewer_id": viewer_id,
            "room": {
                "code": self.code,
                "game_type": self.game_type,
                "phase": self.phase,
                "locked": self.locked,
                "players": [player.to_public_dict() for player in self.players],
                "current_player_id": current.id if current else None,
                "current_category": self.current_category,
                "deadline_timestamp_ms": self.deadline_timestamp_ms,
                "fuse_duration_ms": self.fuse_duration_ms,
                "settings": {
                    "fuse_min_seconds": self.fuse_min_ms // 1000,
                    "fuse_max_seconds": self.fuse_max_ms // 1000,
                    "custom_categories": self.custom_categories,
                },
                "winner_id": self.winner_id,
                "last_event": self.last_event,
                "truth_or_dare": self.truth_or_dare.to_public_dict(),
            },
        }
