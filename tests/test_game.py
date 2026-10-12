import pytest

from app import game
from app.models import Room


def add_players(room, *names):
    return [game.join_room(room, name) for name in names]


def test_join_room_assigns_first_player_as_host_and_rejoins_by_id():
    room = Room(code="PARTY1")

    host, guest = add_players(room, "Maya", "Sam")
    rejoined = game.join_room(room, "Maya Again", host.id)

    assert host.is_host is True
    assert guest.is_host is False
    assert rejoined.id == host.id
    assert rejoined.nickname == "Maya Again"
    assert len(room.players) == 2


def test_locked_room_rejects_new_players_but_allows_rejoin():
    room = Room(code="PARTY1")
    host, _guest = add_players(room, "Maya", "Sam")
    game.set_room_locked(room, host.id, True)

    with pytest.raises(game.GameError):
        game.join_room(room, "Alex")

    rejoined = game.join_room(room, "Maya Again", host.id)

    assert rejoined.id == host.id
    assert room.locked is True


def test_start_game_sets_category_turn_and_server_deadline():
    room = Room(code="PARTY1")
    host, _guest = add_players(room, "Maya", "Sam")

    game.start_game(room, host.id, timestamp_ms=1_000)

    assert room.phase == "game"
    assert room.current_category
    assert room.used_categories == [room.current_category]
    assert room.current_player() in room.players
    assert 11_000 <= room.deadline_timestamp_ms <= 41_000


def test_host_can_switch_game_type_in_lobby():
    room = Room(code="PARTY1")
    host, _guest = add_players(room, "Maya", "Sam")

    game.set_game_type(room, host.id, "truth_or_dare")

    assert room.game_type == "truth_or_dare"
    assert room.truth_or_dare.current_prompt_text is None
    assert room.last_event["kind"] == "game_changed"


def test_game_type_cannot_change_after_start():
    room = Room(code="PARTY1")
    host, _guest = add_players(room, "Maya", "Sam")
    game.start_game(room, host.id, timestamp_ms=1_000)

    with pytest.raises(game.GameError):
        game.set_game_type(room, host.id, "truth_or_dare")


def test_host_can_update_fuse_controls_and_custom_categories():
    room = Room(code="PARTY1")
    host, _guest = add_players(room, "Maya", "Sam")

    game.update_settings(
        room,
        host.id,
        fuse_min_seconds=7,
        fuse_max_seconds=9,
        custom_categories=["Dinosaurs", "dinosaurs", "Beach Snacks"],
    )
    game.start_game(room, host.id, timestamp_ms=1_000)

    assert room.fuse_min_ms == 7_000
    assert room.fuse_max_ms == 9_000
    assert room.custom_categories == ["Dinosaurs", "Beach Snacks"]
    assert 8_000 <= room.deadline_timestamp_ms <= 10_000


def test_non_host_cannot_update_controls():
    room = Room(code="PARTY1")
    _host, guest = add_players(room, "Maya", "Sam")

    with pytest.raises(game.GameError):
        game.update_settings(room, guest.id, 7, 9, ["Dinosaurs"])


def test_host_can_rename_remove_move_shuffle_and_transfer_in_lobby():
    room = Room(code="PARTY1")
    host, maya, sam = add_players(room, "Host", "Maya", "Sam")

    game.rename_player(room, host.id, maya.id, "Maya N")
    game.move_player(room, host.id, sam.id, "up")
    game.shuffle_players(room, host.id)
    game.transfer_host(room, host.id, sam.id)
    game.remove_player(room, sam.id, maya.id)

    assert maya not in room.players
    assert sam.is_host is True
    assert host.is_host is False


def test_lobby_controls_are_rejected_after_game_starts():
    room = Room(code="PARTY1")
    host, guest = add_players(room, "Host", "Maya")
    game.start_game(room, host.id, timestamp_ms=1_000)

    with pytest.raises(game.GameError):
        game.set_room_locked(room, host.id, True)
    with pytest.raises(game.GameError):
        game.rename_player(room, host.id, guest.id, "New Name")
    with pytest.raises(game.GameError):
        game.remove_player(room, host.id, guest.id)
    with pytest.raises(game.GameError):
        game.transfer_host(room, host.id, guest.id)
    with pytest.raises(game.GameError):
        game.move_player(room, host.id, guest.id, "up")
    with pytest.raises(game.GameError):
        game.shuffle_players(room, host.id)


def test_invalid_fuse_controls_are_rejected():
    room = Room(code="PARTY1")
    host, _guest = add_players(room, "Maya", "Sam")

    with pytest.raises(game.GameError):
        game.update_settings(room, host.id, 20, 10, [])


def test_pass_advances_turn_and_keeps_category():
    room = Room(code="PARTY1")
    host, guest = add_players(room, "Maya", "Sam")
    game.start_game(room, host.id, timestamp_ms=1_000)
    room.current_player_index = room.players.index(host)
    room.current_category = "Fruits"
    room.used_categories = ["Fruits"]

    game.pass_turn(room, host.id, timestamp_ms=2_000)

    assert room.current_player() == guest
    assert room.current_category == "Fruits"
    assert 12_000 <= room.deadline_timestamp_ms <= 42_000


def test_timeout_adds_letter_changes_category_and_moves_turn():
    room = Room(code="PARTY1")
    host, guest = add_players(room, "Maya", "Sam")
    game.start_game(room, host.id, timestamp_ms=1_000)
    room.current_player_index = room.players.index(host)
    room.current_category = "Fruits"
    room.used_categories = ["Fruits"]
    room.deadline_timestamp_ms = 5_000

    changed = game.resolve_timeout(room, timestamp_ms=5_000)

    assert changed is True
    assert host.letters == "B"
    assert host.eliminated is False
    assert room.current_player() == guest
    assert room.current_category != "Fruits"
    assert room.last_event["kind"] == "missed"


def test_fourth_letter_eliminates_player_and_game_over_when_one_remains():
    room = Room(code="PARTY1")
    host, guest = add_players(room, "Maya", "Sam")
    game.start_game(room, host.id, timestamp_ms=1_000)
    room.current_player_index = room.players.index(host)
    host.letters = "BOM"
    room.deadline_timestamp_ms = 5_000

    changed = game.resolve_timeout(room, timestamp_ms=5_000)

    assert changed is True
    assert host.letters == "BOMB"
    assert host.eliminated is True
    assert room.phase == "gameover"
    assert room.winner_id == guest.id


def test_only_host_can_reset_room():
    room = Room(code="PARTY1")
    host, guest = add_players(room, "Maya", "Sam")
    room.phase = "gameover"
    room.winner_id = host.id
    host.letters = "BO"

    with pytest.raises(game.GameError):
        game.play_again(room, guest.id)

    game.play_again(room, host.id)

    assert room.phase == "lobby"
    assert room.winner_id is None
    assert host.letters == ""


def test_truth_or_dare_mixed_mode_choose_skip_and_next_turn():
    room = Room(code="TOD1", game_type="truth_or_dare")
    host, guest = add_players(room, "Maya", "Sam")
    game.configure_truth_or_dare(
        room,
        host.id,
        scenario="college reunion",
        intensity="mild",
        mode="mixed",
    )

    game.start_truth_or_dare(room, host.id)
    room.current_player_index = room.players.index(host)

    assert room.phase == "game"
    assert room.truth_or_dare.waiting_for_choice is True
    assert len(room.truth_or_dare.truth_queue) == game.TOD_BATCH_SIZE
    assert len(room.truth_or_dare.dare_queue) == game.TOD_BATCH_SIZE

    game.choose_truth_or_dare(room, host.id, "truth")
    first_prompt = room.truth_or_dare.current_prompt_text
    assert room.truth_or_dare.current_prompt_type == "truth"
    assert "college reunion" in first_prompt
    assert len(room.truth_or_dare.truth_queue) == game.TOD_BATCH_SIZE - 1

    game.skip_truth_or_dare_prompt(room, host.id)
    assert room.truth_or_dare.current_prompt_text
    assert len(room.truth_or_dare.used_prompts) == 2
    assert len(room.truth_or_dare.truth_queue) == game.TOD_BATCH_SIZE - 2

    game.next_truth_or_dare_turn(room, host.id)
    assert room.current_player() == guest
    assert room.truth_or_dare.waiting_for_choice is True
    assert room.truth_or_dare.current_prompt_text is None


def test_truth_or_dare_fixed_mode_auto_generates_prompt_each_turn():
    room = Room(code="TOD1", game_type="truth_or_dare")
    host, guest = add_players(room, "Maya", "Sam")
    game.configure_truth_or_dare(room, host.id, "", "wild", "dare")

    game.start_truth_or_dare(room, host.id)
    room.current_player_index = room.players.index(host)

    assert room.truth_or_dare.waiting_for_choice is False
    assert room.truth_or_dare.current_prompt_type == "dare"
    assert len(room.truth_or_dare.dare_queue) == game.TOD_BATCH_SIZE - 1

    game.next_truth_or_dare_turn(room, host.id)

    assert room.current_player() == guest
    assert room.truth_or_dare.current_prompt_type == "dare"
    assert room.truth_or_dare.current_prompt_text


def test_truth_or_dare_refills_queue_when_low(monkeypatch):
    room = Room(code="TOD1", game_type="truth_or_dare")
    host, _guest = add_players(room, "Maya", "Sam")
    game.configure_truth_or_dare(room, host.id, "", "mild", "truth")
    room.truth_or_dare.truth_queue = [f"queued {idx}" for idx in range(game.TOD_REFILL_THRESHOLD + 1)]

    monkeypatch.setattr(
        game,
        "generate_truth_or_dare_batch",
        lambda request: [f"generated {idx}" for idx in range(request.count)],
    )

    prompt = game.pop_truth_or_dare_prompt(room, "truth")

    assert prompt == "queued 0"
    assert len(room.truth_or_dare.truth_queue) == game.TOD_BATCH_SIZE


def test_truth_or_dare_rejects_wrong_player_actions():
    room = Room(code="TOD1", game_type="truth_or_dare")
    host, guest = add_players(room, "Maya", "Sam")
    game.start_truth_or_dare(room, host.id)
    room.current_player_index = room.players.index(host)

    with pytest.raises(game.GameError):
        game.choose_truth_or_dare(room, guest.id, "truth")


def test_host_can_end_truth_or_dare_session():
    room = Room(code="TOD1", game_type="truth_or_dare")
    host, _guest = add_players(room, "Maya", "Sam")
    game.start_truth_or_dare(room, host.id)

    game.end_truth_or_dare(room, host.id)

    assert room.phase == "gameover"
    assert room.last_event["kind"] == "tod_ended"
