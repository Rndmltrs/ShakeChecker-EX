"""Track the battle turn count and the enemy's accumulated sleep turns.

Pure/stateful (no I/O). Fed observations each frame; produces the numbers the
conditional balls need: turns_completed (Quick/Timer) and turns_asleep (Dream).

Turn numbers are 1-based as PokeMMO reports them ("Turn N started!"); a turn
that has fully begun N means N-1 turns completed. Signals can come from chat
OCR now and the menu/action fallback later — both funnel through observe().
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class TurnTracker:
    turns_completed: int = 0
    turns_asleep: int = 0
    _turn_number: int = 1  # highest 1-based turn seen this battle
    _bar_present: bool = False
    _saw_bar_gap: bool = False
    _menu_present: bool = False
    _menu_turns: int = 0  # turns counted from command-menu reappearances
    _action_since_menu: bool = False  # an action animation ran since the menu

    def reset(self) -> None:
        """Call at the start of each battle."""
        self.turns_completed = 0
        self.turns_asleep = 0
        self._turn_number = 1
        self._bar_present = False
        self._saw_bar_gap = False
        self._menu_present = False
        self._menu_turns = 0
        self._action_since_menu = False

    def observe(self, turn_number: int | None, enemy_asleep: bool) -> None:
        """Fold in one frame's chat observation.

        `turn_number` is the latest turn read from chat OCR, or None if unknown
        this frame. `enemy_asleep` is the current sleep status. This is the
        authoritative, exact source when the chat is visible.
        """
        # Sleep resets the moment the enemy is awake; it only accrues per turn
        # while asleep (so Dream Ball is x1 again immediately on wake-up).
        if not enemy_asleep:
            self.turns_asleep = 0

        if turn_number is not None and turn_number > self._turn_number:
            if enemy_asleep:
                self.turns_asleep += turn_number - self._turn_number
            self._turn_number = turn_number
            self.turns_completed = max(self.turns_completed, turn_number - 1)

    def observe_bar(self, bar_present: bool) -> None:
        """Chat-independent fallback: the enemy HP bar vanishes during an
        action's zoom/attack animation and returns afterwards. One such
        vanish->return cycle proves at least one action has resolved, so we are
        past turn 1. This only raises a *floor* (turns_completed >= 1); it never
        advances further on its own, to avoid over-counting (which would
        overstate Timer/Dream catch chances). Chat OCR remains authoritative.

        The vanish also marks that a real action ran (used by observe_menu to
        tell a committed turn from a menu the player merely opened and cancelled).
        """
        if self._bar_present and not bar_present:
            self._saw_bar_gap = True
            self._action_since_menu = True
        elif self._saw_bar_gap and bar_present:
            self._saw_bar_gap = False
            self.turns_completed = max(self.turns_completed, 1)
        self._bar_present = bar_present

    def observe_menu(self, menu_present: bool) -> None:
        """Chat-independent turn count from the command menu (FIGHT/BAG/POKEMON/
        RUN), which reappears at the start of every turn while waiting for input.

        A turn is counted on each menu absent->present transition, but only if a
        real action ran since the menu was last up (the HP bar vanished). That
        gate filters the two non-turn ways the menu reappears: the player opening
        a submenu (FIGHT/BAG) and cancelling, and a single missed OCR frame. The
        first appearance (turn 1) has no prior action, so it counts as 0 completed.
        Like observe_bar this only raises turns_completed; chat stays authoritative.
        """
        if menu_present and not self._menu_present and self._action_since_menu:
            self._menu_turns += 1
            self._action_since_menu = False
            self.turns_completed = max(self.turns_completed, self._menu_turns)
        self._menu_present = menu_present
