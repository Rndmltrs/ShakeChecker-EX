from __future__ import annotations

from core.app_state import DEX_SHOWN_MAX
from core.game_time import season_name
from dex.dex_session import LocationView
from dex.dex_tracker import select_display


def dex_panel_text(view: LocationView | None) -> str:
    """The console form of the dex panel: a header with the still-needed count,
    then up to DEX_SHOWN_MAX rows. Uncaught species come first by dex id ('+X' for
    the rest); once those fit, the tail is padded with the rarest already-caught
    species (marked ✓) so the notable rares stay visible. '' if no location."""
    if view is None:
        return ""
    needed = sum(1 for e in view.entries if not e.caught)
    header = (
        f"[dex] {view.route} ({view.region}) {view.period.value} {season_name(view.season)}"
        f" — {needed} needed"
    )
    rows, hidden = select_display(view.entries, DEX_SHOWN_MAX)
    if not rows:
        return header + "\n  (all caught here!)"
    lines = [header]
    for e in rows:
        check = " ✓" if e.caught else ""
        lines.append(f"  #{e.id:<4} {e.name} [{e.rarity}]{_ways_note(e.ways)}{check}")
    if hidden > 0:
        lines.append(f"  +{hidden}")
    return "\n".join(lines)


def _ways_note(ways: tuple[str, ...]) -> str:
    """Parenthesised non-default encounter ways for an entry, e.g. ' (Water)',
    ' (Good Rod/Old Rod)', ' (Lure)', ' (Grass Pheno)'. Empty for plain
    grass/cave walking (dex_tracker.encounter_tag already dropped those)."""
    return f" ({'/'.join(ways)})" if ways else ""
