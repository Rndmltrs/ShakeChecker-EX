import enum

from core import paths

DATA = paths.DATA_DIR  # bundled, read-only (frozen-aware via paths.py)
SPECIES_PATH = DATA / "species_core.json"
TEMPLATES_DIR = DATA / "templates"
ENCOUNTERS_PATH = DATA / "encounters.json"
LEGENDARIES_PATH = DATA / "legendaries.json"
AREA_INDEX_PATH = DATA / "area_index.json"
USERDATA = paths.userdata_dir()  # per-account caught lists (%APPDATA% when frozen)

WAITING_POLL_S = 2.0
IDLE_FRAME_S = 0.25
BATTLE_FRAME_S = 0.5  # ~5 fps
# How long the battle-specific signals (enemy bar + menu/action/catch templates)
# must ALL be gone before the battle ends. Short when the battle UI panel is
# already gone (back to the overworld -> clear the catch overlay promptly), but
# long while the dark command panel is still up: a 2-turn move (Fly/Dig/Solarbeam)
# hides the enemy bar with no menu for a couple seconds mid-battle, and that panel
# stays, so we must NOT end the battle then.
BATTLE_END_GRACE_S = 1.0
BATTLE_ANIM_GRACE_S = 4.0
# Trainer battles cycle through several Pokemon with multi-second gaps (faint +
# "sent out") that have no battle signal; a longer grace keeps those gaps from
# ending the battle (which would flash the overlays and re-run trainer detection).
TRAINER_END_GRACE_S = 6.0
# The command menu must hold present/absent this many battle frames before the
# turn counter accepts the change — filters brief template-match flicker during
# multi-target (horde) animations that would otherwise over-count turns.
MENU_STABLE_FRAMES = 2
# The chat ("Turn N started!") is ground truth and corrects the menu count in BOTH
# directions. A LOWER chat reading is only trusted (to fix an over-count) once the
# menu hasn't advanced for this long, so a stale async read right after a real
# turn advance can't briefly drag the count down.
TURN_DOWN_GUARD_S = 3.0
# Right after a battle starts, the previous battle's last "Turn N" can still be
# in-flight from the async chat OCR. Ignore a turn-1 chat reading only within this
# window; after it, trust the chat even from turn 1 so a stuck menu counter (e.g.
# command menu not detected) is still corrected up to the real turn.
BATTLE_START_GRACE_S = 3.0
# IDLE state location OCR throttle. Location changes are relatively infrequent.
# A lower interval increases UI responsiveness at the cost of slightly
# higher CPU usage while walking.
DEX_LOC_INTERVAL_S = 0.25
# How long the HUD location mask must remain perfectly still before OCR is allowed
# to run. Filters out blur from camera panning and rapid-fire UI transitions.
LOC_MASK_STABLE_S = 0.125
DEX_SHOWN_MAX = 5  # entries shown before collapsing the rest into "+X"


class AppState(enum.Enum):
    WAITING = "waiting"
    IDLE = "idle"
    BATTLE = "battle"
