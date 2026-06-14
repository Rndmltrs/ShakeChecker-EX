from __future__ import annotations

from pathlib import Path

import cv2

from battle_log import (
    has_command_menu,
    is_catch_banner,
    parse_turn_number,
    read_battle_text,
    read_turn_number,
)
from battle_reader import load_calibration
from turn_tracker import TurnTracker

ROOT = Path(__file__).parent.parent
CAL = load_calibration(ROOT / "calibration.toml")


def test_read_turn_number_from_chat_fixture():
    # full_health_no_status.png's chat shows "[Battle] Turn 2 started!"
    img = cv2.imread(str(ROOT / "fixtures" / "full_health_no_status.png"))
    assert read_turn_number(img, CAL.chat) == 2


def test_read_turn_number_none_in_overworld():
    img = cv2.imread(str(ROOT / "fixtures" / "overworld_city_running.png"))
    assert read_turn_number(img, CAL.chat) is None


def test_is_catch_banner_keywords():
    # OCR mangles "Gotcha"->"Gotoha" and splits/drops "was"; detection keys on
    # the surviving "caught"/"gotcha" tokens, not the exact phrase.
    assert is_catch_banner(["Gotoha!", "Rhyhorn", "sEm", "Caught!"]) is True
    assert is_catch_banner(["Gotcha!", "Shellos was caught!"]) is True
    # a faint (the other reason the bar vanishes) must NOT read as a catch
    assert is_catch_banner(["Cascoon", "fainted!"]) is False
    assert is_catch_banner(["It's super effective!"]) is False
    assert is_catch_banner([]) is False


def test_has_command_menu_keywords():
    assert has_command_menu(["FIGHT", "BAG", "POKEMON", "RUN"], 2) is True
    assert has_command_menu(["fight", "bag"], 2) is True
    assert has_command_menu(["RUN"], 2) is False  # one stray word is not the menu
    # move submenu / narration / chat-style lines are not the command menu
    assert has_command_menu(["False Swipe", "Spore", "Soak"], 2) is False
    assert has_command_menu(["Monferno used Ember!"], 2) is False
    assert has_command_menu([], 2) is False


def test_read_battle_text_detects_command_menu():
    # command menu visible at two window aspect ratios
    for name in ("full_health_no_status.png", "1920x1080_resolution.png"):
        img = cv2.imread(str(ROOT / "fixtures" / name))
        assert read_battle_text(img, CAL.battle_text).menu_present is True, name


def test_read_battle_text_no_menu_during_action_or_submenu():
    for name in (
        "batle_action_attack_selected.png",  # action textbox
        "two_third_green_health_cave.png",  # move submenu
        "overworld_city_running.png",  # not in battle
    ):
        img = cv2.imread(str(ROOT / "fixtures" / name))
        assert read_battle_text(img, CAL.battle_text).menu_present is False, name


def test_read_battle_text_detects_catch_fixture():
    img = cv2.imread(
        str(ROOT / "fixtures" / "batle_action_pokemon_catched_text_after pokeball_disapeared.png")
    )
    bt = read_battle_text(img, CAL.battle_text)
    assert bt.caught is True
    # crucially, the catch is read from the in-viewport box, NOT the chat log's
    # stale "Geodude was caught!" line, which sits below this band.
    assert bt.menu_present is False


def test_read_battle_text_false_before_catch_text_appears():
    img = cv2.imread(str(ROOT / "fixtures" / "batle_action_pokemon_catched_dark_pokeballpng.png"))
    assert read_battle_text(img, CAL.battle_text).caught is False


def test_read_battle_text_no_catch_in_normal_battle():
    img = cv2.imread(str(ROOT / "fixtures" / "full_health_no_status.png"))
    assert read_battle_text(img, CAL.battle_text).caught is False


def test_parse_turn_number():
    assert parse_turn_number(["[Battle] Turn 2 started!"]) == 2
    assert parse_turn_number(["[Battle] Turn2started"]) == 2  # OCR drops spaces
    assert parse_turn_number(["[Battle] The wild Cascoon woke up!", "Turn 5 started!"]) == 5
    assert parse_turn_number(["nothing here", "[Battle] Cascoon used Tackle!"]) is None
    assert parse_turn_number([]) is None


def test_parse_turn_number_takes_highest():
    assert parse_turn_number(["Turn 3 started", "Turn 4 started", "Turn 2 started"]) == 4


def test_tracker_starts_at_zero():
    t = TurnTracker()
    assert t.turns_completed == 0
    assert t.turns_asleep == 0


def test_tracker_advances_with_turn_number():
    t = TurnTracker()
    t.observe(2, enemy_asleep=False)
    assert t.turns_completed == 1
    t.observe(5, enemy_asleep=False)
    assert t.turns_completed == 4


def test_tracker_ignores_none_and_non_increasing():
    t = TurnTracker()
    t.observe(3, enemy_asleep=False)
    t.observe(None, enemy_asleep=False)
    t.observe(2, enemy_asleep=False)  # stale/lower reading
    assert t.turns_completed == 2  # stayed at turn 3 -> 2 completed


def test_sleep_turns_accumulate_while_asleep():
    t = TurnTracker()
    t.observe(2, enemy_asleep=True)
    assert t.turns_asleep == 1
    t.observe(3, enemy_asleep=True)
    assert t.turns_asleep == 2


def test_sleep_resets_on_wake():
    t = TurnTracker()
    t.observe(2, enemy_asleep=True)
    t.observe(3, enemy_asleep=True)
    assert t.turns_asleep == 2
    t.observe(4, enemy_asleep=False)  # woke up
    assert t.turns_asleep == 0


def test_reset_clears_battle_state():
    t = TurnTracker()
    t.observe(4, enemy_asleep=True)
    t.reset()
    assert t.turns_completed == 0
    assert t.turns_asleep == 0
    t.observe(2, enemy_asleep=False)  # next battle starts counting fresh
    assert t.turns_completed == 1


# --- chat-independent HP-bar-cycle fallback ---


def feed_bar(t: TurnTracker, presence: list[bool]) -> None:
    for p in presence:
        t.observe_bar(p)


def test_bar_present_throughout_turn_one_stays_zero():
    t = TurnTracker()
    feed_bar(t, [True, True, True])  # no animation yet
    assert t.turns_completed == 0


def test_bar_vanish_and_return_marks_past_turn_one():
    t = TurnTracker()
    feed_bar(t, [True, True, False, False, True])  # action animation cycle
    assert t.turns_completed == 1


def test_bar_cycle_only_raises_a_floor_not_a_count():
    t = TurnTracker()
    # several animation cycles must not push turns beyond 1 on their own
    feed_bar(t, [True, False, True, False, True, False, True])
    assert t.turns_completed == 1


def test_chat_overrides_bar_floor_upward():
    t = TurnTracker()
    feed_bar(t, [True, False, True])  # floor -> 1
    t.observe(5, enemy_asleep=False)  # chat is authoritative
    assert t.turns_completed == 4


def test_bar_floor_never_lowers_chat_value():
    t = TurnTracker()
    t.observe(5, enemy_asleep=False)
    feed_bar(t, [True, False, True])  # floor 1 must not reduce 4
    assert t.turns_completed == 4


# --- chat-independent command-menu turn counter ---


def play_turn(t: TurnTracker) -> None:
    """Simulate one committed turn: menu up -> player acts (bar vanishes during
    the animation) -> menu reappears for the next turn."""
    t.observe_menu(True)  # waiting for input
    t.observe_menu(False)  # action committed, menu closes
    feed_bar(t, [True, False, True])  # attack animation: bar vanishes & returns


def test_menu_first_appearance_is_turn_one():
    t = TurnTracker()
    t.observe_menu(True)  # turn 1 prompt, no action yet
    assert t.turns_completed == 0


def test_menu_counts_each_committed_turn():
    t = TurnTracker()
    play_turn(t)  # turn 1 committed
    t.observe_menu(True)  # turn 2 prompt
    assert t.turns_completed == 1
    play_turn(t)  # turn 2 committed (already at menu, re-open after action)
    t.observe_menu(True)  # turn 3 prompt
    assert t.turns_completed == 2


def test_menu_reopen_without_action_does_not_count():
    # player opens FIGHT/BAG then cancels: menu closes and reopens with NO action
    t = TurnTracker()
    t.observe_menu(True)
    t.observe_menu(False)  # opened a submenu
    t.observe_menu(True)  # cancelled back to the menu
    assert t.turns_completed == 0


def test_menu_ocr_flicker_does_not_count():
    # a single missed OCR frame (menu briefly reads absent) is not a turn
    t = TurnTracker()
    t.observe_menu(True)
    t.observe_menu(False)  # flicker
    t.observe_menu(True)
    t.observe_menu(False)  # flicker
    t.observe_menu(True)
    assert t.turns_completed == 0


def test_chat_overrides_menu_count_upward():
    t = TurnTracker()
    play_turn(t)  # menu count -> 1
    t.observe(5, enemy_asleep=False)  # chat is authoritative
    assert t.turns_completed == 4


def test_menu_count_never_lowers_chat_value():
    t = TurnTracker()
    t.observe(5, enemy_asleep=False)
    play_turn(t)
    t.observe_menu(True)  # would be turn 2 from menu, must not reduce 4
    assert t.turns_completed == 4


def test_menu_count_survives_reset():
    t = TurnTracker()
    play_turn(t)
    t.observe_menu(True)
    assert t.turns_completed == 1
    t.reset()
    t.observe_menu(True)
    assert t.turns_completed == 0  # fresh battle, turn 1
