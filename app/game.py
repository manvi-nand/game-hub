from __future__ import annotations

import random
import time
from collections.abc import Sequence

from app.categories import CATEGORIES
from app.llm_prompts import TruthOrDareBatchRequest, generate_truth_or_dare_batch
from app.models import BOMB_LETTERS, GameType, Player, Room, TodIntensity, TodMode, TodPromptType
from app.truth_or_dare_prompts import TRUTH_OR_DARE_PROMPTS

MIN_FUSE_MS = 10_000
MAX_FUSE_MS = 40_000
MIN_ALLOWED_FUSE_MS = 5_000
MAX_ALLOWED_FUSE_MS = 90_000
MAX_CUSTOM_CATEGORIES = 80
VALID_GAME_TYPES = {"bomb_party", "truth_or_dare"}
VALID_TOD_INTENSITIES = {"mild", "medium", "wild"}
VALID_TOD_MODES = {"mixed", "truth", "dare"}
VALID_TOD_PROMPT_TYPES = {"truth", "dare"}
TOD_BATCH_SIZE = 50
TOD_REFILL_THRESHOLD = 10


class GameError(ValueError):
    pass


def now_ms() -> int:
    return int(time.time() * 1000)


def random_fuse_ms(room: Room) -> int:
    return random.randint(room.fuse_min_ms // 1000, room.fuse_max_ms // 1000) * 1000


def normalize_game_type(value: str | None) -> GameType:
    if value not in VALID_GAME_TYPES:
        return "bomb_party"
    return value  # type: ignore[return-value]


def category_pool(room: Room) -> list[str]:
    seen = set()
    categories = []
    for category in [*CATEGORIES, *room.custom_categories]:
        normalized = category.strip()
        key = normalized.casefold()
        if normalized and key not in seen:
            categories.append(normalized)
            seen.add(key)
    return categories


def pick_category(room: Room, used_categories: Sequence[str]) -> str:
    categories = category_pool(room)
    pool = [category for category in categories if category not in used_categories]
    if not pool:
        pool = categories
    return random.choice(pool)


def next_active_index(room: Room, from_index: int) -> int:
    if not room.players:
        return 0
    for offset in range(1, len(room.players) + 1):
        index = (from_index + offset) % len(room.players)
        if not room.players[index].eliminated:
            return index
    return from_index


def join_room(room: Room, nickname: str, player_id: str | None = None) -> Player:
    clean_name = nickname.strip()[:24] or "Player"
    if player_id:
        existing = room.get_player(player_id)
        if existing:
            existing.nickname = clean_name
            existing.connected = True
            return existing

    if room.locked:
        raise GameError("This room is locked.")
    if len(room.players) >= 10:
        raise GameError("This room is full.")

    player = Player(nickname=clean_name, is_host=len(room.players) == 0)
    room.players.append(player)
    room.last_event = {"kind": "joined", "player_id": player.id}
    return player


def mark_disconnected(room: Room, player_id: str) -> None:
    player = room.get_player(player_id)
    if player:
        player.connected = False
        room.last_event = {"kind": "disconnected", "player_id": player.id}


def start_game(room: Room, player_id: str, timestamp_ms: int | None = None) -> None:
    if room.game_type != "bomb_party":
        raise GameError("This action is only available in Bomb Party.")
    if room.phase != "lobby":
        raise GameError("This game has already started.")
    player = room.get_player(player_id)
    if not player or not player.is_host:
        raise GameError("Only the host can start the game.")
    if len(room.players) < 2:
        raise GameError("At least two players are needed to start.")

    timestamp_ms = timestamp_ms or now_ms()
    room.phase = "game"
    room.winner_id = None
    room.used_categories = []
    room.current_category = pick_category(room, room.used_categories)
    room.used_categories.append(room.current_category)
    room.current_player_index = random.randrange(len(room.players))
    room.fuse_duration_ms = random_fuse_ms(room)
    room.deadline_timestamp_ms = timestamp_ms + room.fuse_duration_ms
    room.last_event = {
        "kind": "started",
        "player_id": room.players[room.current_player_index].id,
    }


def pass_turn(room: Room, player_id: str, timestamp_ms: int | None = None) -> None:
    if room.game_type != "bomb_party":
        raise GameError("This action is only available in Bomb Party.")
    if room.phase != "game":
        raise GameError("The game is not active.")
    current = room.current_player()
    if not current or current.id != player_id:
        raise GameError("It is not your turn.")
    if current.eliminated:
        raise GameError("Eliminated players cannot pass.")

    timestamp_ms = timestamp_ms or now_ms()
    room.current_player_index = next_active_index(room, room.current_player_index)
    room.fuse_duration_ms = random_fuse_ms(room)
    room.deadline_timestamp_ms = timestamp_ms + room.fuse_duration_ms
    room.last_event = {
        "kind": "passed",
        "player_id": player_id,
        "next_player_id": room.players[room.current_player_index].id,
    }


def resolve_timeout(room: Room, timestamp_ms: int | None = None) -> bool:
    if room.game_type != "bomb_party" or room.phase != "game" or not room.deadline_timestamp_ms:
        return False

    timestamp_ms = timestamp_ms or now_ms()
    if timestamp_ms < room.deadline_timestamp_ms:
        return False

    current_index = room.current_player_index
    current = room.current_player()
    if not current:
        return False

    next_letter_count = min(len(BOMB_LETTERS), len(current.letters) + 1)
    current.letters = "".join(BOMB_LETTERS[:next_letter_count])
    if next_letter_count >= len(BOMB_LETTERS):
        current.eliminated = True

    active = room.active_players()
    room.last_event = {
        "kind": "missed",
        "player_id": current.id,
        "letters": current.letters,
        "eliminated": current.eliminated,
    }

    if len(active) <= 1:
        winner = active[0] if active else current
        room.phase = "gameover"
        room.winner_id = winner.id
        room.deadline_timestamp_ms = None
        room.fuse_duration_ms = None
        room.current_category = None
        room.last_event = {"kind": "gameover", "winner_id": winner.id}
        return True

    room.current_player_index = next_active_index(room, current_index)
    room.current_category = pick_category(room, room.used_categories)
    room.used_categories.append(room.current_category)
    room.fuse_duration_ms = random_fuse_ms(room)
    room.deadline_timestamp_ms = timestamp_ms + room.fuse_duration_ms
    return True


def update_settings(
    room: Room,
    player_id: str,
    fuse_min_seconds: int,
    fuse_max_seconds: int,
    custom_categories: Sequence[str],
) -> None:
    player = room.get_player(player_id)
    if not player or not player.is_host:
        raise GameError("Only the host can update controls.")
    if room.phase != "lobby":
        raise GameError("Controls can only be changed in the lobby.")

    fuse_min_ms = int(fuse_min_seconds) * 1000
    fuse_max_ms = int(fuse_max_seconds) * 1000
    if fuse_min_ms < MIN_ALLOWED_FUSE_MS:
        raise GameError("Fuse minimum must be at least 5 seconds.")
    if fuse_max_ms > MAX_ALLOWED_FUSE_MS:
        raise GameError("Fuse maximum cannot be above 90 seconds.")
    if fuse_min_ms > fuse_max_ms:
        raise GameError("Fuse minimum cannot be greater than maximum.")

    cleaned_categories = []
    seen = set()
    for category in custom_categories:
        clean = str(category).strip()
        key = clean.casefold()
        if clean and key not in seen:
            cleaned_categories.append(clean[:50])
            seen.add(key)
        if len(cleaned_categories) >= MAX_CUSTOM_CATEGORIES:
            break

    room.fuse_min_ms = fuse_min_ms
    room.fuse_max_ms = fuse_max_ms
    room.custom_categories = cleaned_categories
    room.last_event = {"kind": "settings_updated", "player_id": player_id}


def set_game_type(room: Room, player_id: str, game_type: str) -> None:
    require_lobby_host(room, player_id)
    normalized = normalize_game_type(game_type)
    room.game_type = normalized
    room.winner_id = None
    room.current_player_index = 0
    room.current_category = None
    room.deadline_timestamp_ms = None
    room.fuse_duration_ms = None
    room.used_categories = []
    room.truth_or_dare.used_prompts = []
    room.truth_or_dare.truth_queue = []
    room.truth_or_dare.dare_queue = []
    room.truth_or_dare.current_prompt_type = None
    room.truth_or_dare.current_prompt_text = None
    room.truth_or_dare.waiting_for_choice = True
    room.last_event = {"kind": "game_changed", "player_id": player_id, "game_type": normalized}


def configure_truth_or_dare(
    room: Room,
    player_id: str,
    scenario: str,
    intensity: str,
    mode: str,
) -> None:
    require_lobby_host(room, player_id)
    if room.game_type != "truth_or_dare":
        raise GameError("This action is only available in Truth or Dare.")
    if intensity not in VALID_TOD_INTENSITIES:
        raise GameError("Pick a valid intensity.")
    if mode not in VALID_TOD_MODES:
        raise GameError("Pick a valid mode.")

    clean_scenario = " ".join(str(scenario).split())[:180]
    room.truth_or_dare.scenario = clean_scenario
    room.truth_or_dare.intensity = intensity  # type: ignore[assignment]
    room.truth_or_dare.mode = mode  # type: ignore[assignment]
    room.truth_or_dare.truth_queue = []
    room.truth_or_dare.dare_queue = []
    room.truth_or_dare.used_prompts = []
    room.truth_or_dare.current_prompt_type = None
    room.truth_or_dare.current_prompt_text = None
    room.truth_or_dare.waiting_for_choice = True
    room.last_event = {"kind": "tod_configured", "player_id": player_id}


def start_truth_or_dare(room: Room, player_id: str) -> None:
    if room.game_type != "truth_or_dare":
        raise GameError("This action is only available in Truth or Dare.")
    if room.phase != "lobby":
        raise GameError("This game has already started.")
    player = room.get_player(player_id)
    if not player or not player.is_host:
        raise GameError("Only the host can start the game.")
    if len(room.players) < 2:
        raise GameError("At least two players are needed to start.")

    room.phase = "game"
    room.current_player_index = random.randrange(len(room.players))
    room.winner_id = None
    room.deadline_timestamp_ms = None
    room.fuse_duration_ms = None
    room.current_category = None
    room.used_categories = []
    room.truth_or_dare.used_prompts = []
    room.truth_or_dare.truth_queue = []
    room.truth_or_dare.dare_queue = []
    room.truth_or_dare.current_prompt_type = None
    room.truth_or_dare.current_prompt_text = None
    room.truth_or_dare.waiting_for_choice = room.truth_or_dare.mode == "mixed"
    prepare_truth_or_dare_queues(room)

    if room.truth_or_dare.mode != "mixed":
        set_truth_or_dare_prompt(room, room.truth_or_dare.mode)

    room.last_event = {
        "kind": "tod_started",
        "player_id": room.players[room.current_player_index].id,
    }


def active_truth_or_dare_types(room: Room) -> list[TodPromptType]:
    mode = room.truth_or_dare.mode
    if mode == "mixed":
        return ["truth", "dare"]
    return [mode]


def prepare_truth_or_dare_queues(room: Room) -> None:
    for prompt_type in active_truth_or_dare_types(room):
        refill_truth_or_dare_queue(room, prompt_type, force=True)


def refill_truth_or_dare_queue(room: Room, prompt_type: TodPromptType, force: bool = False) -> None:
    queue = get_truth_or_dare_queue(room, prompt_type)
    if not force and len(queue) > TOD_REFILL_THRESHOLD:
        return

    needed = TOD_BATCH_SIZE if force else max(0, TOD_BATCH_SIZE - len(queue))
    if needed <= 0:
        return

    generated = generate_truth_or_dare_batch(
        TruthOrDareBatchRequest(
            scenario=room.truth_or_dare.scenario,
            intensity=room.truth_or_dare.intensity,
            mode=room.truth_or_dare.mode,
            prompt_type=prompt_type,
            player_names=[player.nickname for player in room.players],
            used_prompts=[*room.truth_or_dare.used_prompts, *queue],
            count=needed,
        )
    )
    queue.extend(dedupe_new_prompts(generated, [*room.truth_or_dare.used_prompts, *queue]))
    if len(queue) < needed:
        queue.extend(static_truth_or_dare_prompts(room, prompt_type, needed - len(queue)))


def get_truth_or_dare_queue(room: Room, prompt_type: TodPromptType) -> list[str]:
    return room.truth_or_dare.truth_queue if prompt_type == "truth" else room.truth_or_dare.dare_queue


def dedupe_new_prompts(prompts: Sequence[str], existing: Sequence[str]) -> list[str]:
    seen = {prompt.casefold() for prompt in existing}
    cleaned = []
    for prompt in prompts:
        clean = str(prompt).strip()
        key = clean.casefold()
        if clean and key not in seen:
            cleaned.append(clean)
            seen.add(key)
    return cleaned


def static_truth_or_dare_prompts(room: Room, prompt_type: TodPromptType, count: int) -> list[str]:
    base_prompts = TRUTH_OR_DARE_PROMPTS[room.truth_or_dare.intensity][prompt_type]
    existing = [*room.truth_or_dare.used_prompts, *get_truth_or_dare_queue(room, prompt_type)]
    pool = [prompt for prompt in base_prompts if prompt not in existing]
    if not pool:
        pool = list(base_prompts)

    prompts = []
    while len(prompts) < count:
        prompt = random.choice(pool)
        if room.truth_or_dare.scenario:
            prompt = f"{prompt} Keep it in the context of: {room.truth_or_dare.scenario}."
        prompts.append(prompt)
    return prompts


def pop_truth_or_dare_prompt(room: Room, prompt_type: TodPromptType) -> str:
    queue = get_truth_or_dare_queue(room, prompt_type)
    if not queue:
        refill_truth_or_dare_queue(room, prompt_type, force=True)
    if not queue:
        raise GameError("Could not generate a prompt.")

    prompt = queue.pop(0)
    refill_truth_or_dare_queue(room, prompt_type)
    return prompt


def set_truth_or_dare_prompt(room: Room, prompt_type: str) -> None:
    if prompt_type not in VALID_TOD_PROMPT_TYPES:
        raise GameError("Pick truth or dare.")
    session = room.truth_or_dare
    text = pop_truth_or_dare_prompt(room, prompt_type)  # type: ignore[arg-type]
    session.current_prompt_type = prompt_type  # type: ignore[assignment]
    session.current_prompt_text = text
    session.used_prompts.append(text)
    session.waiting_for_choice = False


def choose_truth_or_dare(room: Room, player_id: str, prompt_type: str) -> None:
    if room.game_type != "truth_or_dare":
        raise GameError("This action is only available in Truth or Dare.")
    if room.phase != "game":
        raise GameError("The game is not active.")
    current = room.current_player()
    if not current or current.id != player_id:
        raise GameError("It is not your turn.")
    if room.truth_or_dare.mode != "mixed":
        raise GameError("This room is not in mixed mode.")
    if not room.truth_or_dare.waiting_for_choice:
        raise GameError("A prompt has already been chosen.")

    set_truth_or_dare_prompt(room, prompt_type)
    room.last_event = {
        "kind": "tod_prompt",
        "player_id": player_id,
        "prompt_type": prompt_type,
    }


def skip_truth_or_dare_prompt(room: Room, player_id: str) -> None:
    if room.game_type != "truth_or_dare":
        raise GameError("This action is only available in Truth or Dare.")
    if room.phase != "game":
        raise GameError("The game is not active.")
    current = room.current_player()
    if not current or current.id != player_id:
        raise GameError("It is not your turn.")
    prompt_type = room.truth_or_dare.current_prompt_type
    if not prompt_type:
        raise GameError("Choose truth or dare first.")

    set_truth_or_dare_prompt(room, prompt_type)
    room.last_event = {
        "kind": "tod_skipped",
        "player_id": player_id,
        "prompt_type": prompt_type,
    }


def next_truth_or_dare_turn(room: Room, player_id: str) -> None:
    if room.game_type != "truth_or_dare":
        raise GameError("This action is only available in Truth or Dare.")
    if room.phase != "game":
        raise GameError("The game is not active.")
    current = room.current_player()
    if not current or current.id != player_id:
        raise GameError("It is not your turn.")

    room.current_player_index = next_active_index(room, room.current_player_index)
    session = room.truth_or_dare
    session.current_prompt_type = None
    session.current_prompt_text = None
    session.waiting_for_choice = session.mode == "mixed"
    if session.mode != "mixed":
        set_truth_or_dare_prompt(room, session.mode)
    room.last_event = {
        "kind": "tod_next_turn",
        "player_id": player_id,
        "next_player_id": room.players[room.current_player_index].id,
    }


def end_truth_or_dare(room: Room, player_id: str) -> None:
    player = room.get_player(player_id)
    if room.game_type != "truth_or_dare":
        raise GameError("This action is only available in Truth or Dare.")
    if not player or not player.is_host:
        raise GameError("Only the host can end the session.")
    if room.phase != "game":
        raise GameError("The game is not active.")
    room.phase = "gameover"
    room.truth_or_dare.current_prompt_type = None
    room.truth_or_dare.current_prompt_text = None
    room.truth_or_dare.waiting_for_choice = True
    room.last_event = {"kind": "tod_ended", "player_id": player_id}


def require_lobby_host(room: Room, player_id: str) -> Player:
    player = room.get_player(player_id)
    if not player or not player.is_host:
        raise GameError("Only the host can use lobby controls.")
    if room.phase != "lobby":
        raise GameError("Lobby controls are only available before the game starts.")
    return player


def set_room_locked(room: Room, player_id: str, locked: bool) -> None:
    require_lobby_host(room, player_id)
    room.locked = bool(locked)
    room.last_event = {
        "kind": "room_locked" if room.locked else "room_unlocked",
        "player_id": player_id,
    }


def rename_player(room: Room, player_id: str, target_player_id: str, nickname: str) -> None:
    require_lobby_host(room, player_id)
    target = room.get_player(target_player_id)
    if not target:
        raise GameError("Player not found.")
    target.nickname = nickname.strip()[:24] or "Player"
    room.last_event = {
        "kind": "player_renamed",
        "player_id": player_id,
        "target_player_id": target.id,
    }


def remove_player(room: Room, player_id: str, target_player_id: str) -> None:
    require_lobby_host(room, player_id)
    target = room.get_player(target_player_id)
    if not target:
        raise GameError("Player not found.")
    if target.is_host:
        raise GameError("Transfer host before removing the host.")
    room.players = [player for player in room.players if player.id != target_player_id]
    room.last_event = {
        "kind": "player_removed",
        "player_id": player_id,
        "target_player_id": target_player_id,
    }


def transfer_host(room: Room, player_id: str, target_player_id: str) -> None:
    require_lobby_host(room, player_id)
    target = room.get_player(target_player_id)
    if not target:
        raise GameError("Player not found.")
    for player in room.players:
        player.is_host = player.id == target.id
    room.last_event = {
        "kind": "host_transferred",
        "player_id": player_id,
        "target_player_id": target.id,
    }


def move_player(room: Room, player_id: str, target_player_id: str, direction: str) -> None:
    require_lobby_host(room, player_id)
    index = next((idx for idx, player in enumerate(room.players) if player.id == target_player_id), None)
    if index is None:
        raise GameError("Player not found.")

    if direction == "up":
        new_index = max(0, index - 1)
    elif direction == "down":
        new_index = min(len(room.players) - 1, index + 1)
    else:
        raise GameError("Move direction must be up or down.")

    if new_index != index:
        room.players[index], room.players[new_index] = room.players[new_index], room.players[index]

    room.last_event = {
        "kind": "player_moved",
        "player_id": player_id,
        "target_player_id": target_player_id,
        "direction": direction,
    }


def shuffle_players(room: Room, player_id: str) -> None:
    require_lobby_host(room, player_id)
    random.shuffle(room.players)
    room.last_event = {"kind": "players_shuffled", "player_id": player_id}


def play_again(room: Room, player_id: str) -> None:
    player = room.get_player(player_id)
    if not player or not player.is_host:
        raise GameError("Only the host can reset the room.")

    for room_player in room.players:
        room_player.letters = ""
        room_player.eliminated = False

    room.phase = "lobby"
    room.locked = False
    room.current_player_index = 0
    room.current_category = None
    room.deadline_timestamp_ms = None
    room.fuse_duration_ms = None
    room.used_categories = []
    room.winner_id = None
    room.truth_or_dare.used_prompts = []
    room.truth_or_dare.truth_queue = []
    room.truth_or_dare.dare_queue = []
    room.truth_or_dare.current_prompt_type = None
    room.truth_or_dare.current_prompt_text = None
    room.truth_or_dare.waiting_for_choice = True
    room.last_event = {"kind": "reset", "player_id": player_id}
