"""Per-account persistence for the dex tracker's caught list.

A player can have several PokeMMO accounts, and each has its own caught species,
so everything is namespaced by account ("profile"). Two pieces of local state,
both under a `userdata/` dir that is gitignored (private, editable):

- config.json: the known accounts and which one is active. The active account is
  chosen manually (set once, remembered) -- never inferred from fragile chat OCR,
  so we can't silently write a caught species into the wrong account's file.
- accounts/<account>/caught.json: the set of National Dex ids caught on that
  account. The dex tracker subtracts this from each location's spawn list.

All paths are injectable so the store is unit-tested against a tmp dir.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

# Keep account ids filesystem-safe (they become directory names).
_SAFE = re.compile(r"[^A-Za-z0-9_.-]+")


def _safe_account(name: str) -> str:
    cleaned = _SAFE.sub("_", name.strip())
    if not cleaned or cleaned in (".", ".."):
        raise ValueError(f"invalid account name: {name!r}")
    return cleaned


class AccountConfig:
    """The set of known accounts and the active one (userdata/config.json)."""

    def __init__(self, path: Path, active: str | None, accounts: list[str]) -> None:
        self.path = path
        self.active = active
        self.accounts = accounts

    @classmethod
    def load(cls, userdata_dir: Path | str) -> AccountConfig:
        path = Path(userdata_dir) / "config.json"
        if not path.exists():
            return cls(path, active=None, accounts=[])
        raw = json.loads(path.read_text("utf-8"))
        return cls(path, active=raw.get("active"), accounts=list(raw.get("accounts", [])))

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"active": self.active, "accounts": self.accounts}
        self.path.write_text(json.dumps(payload, ensure_ascii=False, indent=1), "utf-8")

    def use(self, name: str) -> str:
        """Set `name` active (registering it if new) and persist. Returns the
        sanitized account id actually used."""
        account = _safe_account(name)
        if account not in self.accounts:
            self.accounts.append(account)
        self.active = account
        self.save()
        return account

    def resolve_active(self, override: str | None = None) -> str | None:
        """The account to use this run: an explicit override wins, else the
        remembered active one. None if neither is set (first run)."""
        if override:
            return self.use(override)
        return self.active


class CaughtStore:
    """The caught-species set for one account (accounts/<account>/caught.json)."""

    def __init__(self, path: Path, caught: set[int]) -> None:
        self.path = path
        self.caught = caught

    @classmethod
    def for_account(cls, userdata_dir: Path | str, account: str) -> CaughtStore:
        path = Path(userdata_dir) / "accounts" / _safe_account(account) / "caught.json"
        caught: set[int] = set()
        if path.exists():
            caught = {int(x) for x in json.loads(path.read_text("utf-8")).get("caught", [])}
        return cls(path, caught)

    def has(self, species_id: int) -> bool:
        return species_id in self.caught

    def add(self, species_id: int) -> bool:
        """Record a caught species. Returns True if it was newly added (so the
        caller can persist / log only on a real change)."""
        if species_id in self.caught:
            return False
        self.caught.add(species_id)
        self.save()
        return True

    def remove(self, species_id: int) -> bool:
        """Un-mark a species (manual correction). Returns True if it was present."""
        if species_id not in self.caught:
            return False
        self.caught.discard(species_id)
        self.save()
        return True

    def toggle(self, species_id: int) -> bool:
        """Flip the caught state. Returns the new state (True = now caught)."""
        if species_id in self.caught:
            self.remove(species_id)
            return False
        self.add(species_id)
        return True

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"caught": sorted(self.caught)}
        self.path.write_text(json.dumps(payload, ensure_ascii=False, indent=1), "utf-8")
