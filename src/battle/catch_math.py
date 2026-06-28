from battle.catch_calc import BattleContext, catch_probability, ball_multiplier
from battle.name_reader import NameReader

def battle_context(
    enemy: dict,
    turns_completed: int = 0,
    turns_asleep: int = 0,
    enemy_asleep: bool = False,
    dusk_active: bool = False,
    repeat_chain: int = 0,
) -> BattleContext:
    """Build the conditional-ball context from a resolved enemy dict.

    turns_completed/turns_asleep default to 0 until the turn counter lands, so
    Quick Ball reads x5, Timer Ball x1 and Dream Ball x1 — all correct for the
    first turn with no accumulated sleep. repeat_chain is the current same-species
    catch streak (0 unless this enemy matches the active Repeat Ball chain)."""
    return BattleContext(
        turns_completed=turns_completed,
        turns_asleep=turns_asleep,
        enemy_asleep=enemy_asleep,
        enemy_types=tuple(enemy.get("types") or ()),
        enemy_level=enemy.get("level") or 1,
        dusk_active=dusk_active,
        repeat_chain=repeat_chain,
    )


def format_line(
    name: str, hp_pct: float, status: str, probs: list[tuple[str, float | None]]
) -> str:
    balls = "  ".join(f"{ball} {'??' if p is None else f'{100 * p:5.1f}%'}" for ball, p in probs)
    return f"{name:12.12s} HP {hp_pct:5.1f}% [{status}]  {balls}"


def ball_probs(
    hp_pct: float, base_rate: int | None, status_rate: float, balls: list[dict], ctx: BattleContext
) -> list[tuple[str, float | None]]:
    """Catch probability per ball. base_rate is None for species with no known
    catch rate (roaming Latias/Latios/Mesprit/Cresselia) -> every prob is None
    (the overlay/console then show "??")."""
    if base_rate is None:
        return [(b["name"], None) for b in balls]
    return [
        (
            b["name"],
            catch_probability(hp_pct / 100.0, base_rate, ball_multiplier(b, ctx), status_rate),
        )
        for b in balls
    ]


def resolve_enemy(
    species_override: dict | None,
    name_reader: NameReader | None,
    frame_bgr,
    bar,
) -> dict | None:
    """Enemy dict ({name, catch_rate, types, level}) for a bar: the override if
    given, else OCR. None when the name can't be read."""
    if species_override is not None:
        return species_override
    assert name_reader is not None
    return name_reader.read(frame_bgr, bar)
