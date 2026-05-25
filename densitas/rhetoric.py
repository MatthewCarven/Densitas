"""Rhetoric — picks a scripture-log line per cast.

JSON pool keyed on (power, god, voice_mode). See `rhetoric.json` at the
project root for the actual lines.

Voice modes per GDD §10:
  * consecration — terse, present-tense, descriptive (70% weight).
  * doctrinal    — states a principle (20% weight).
  * ritual       — describes what the priests/citizens do (10% weight).

`pick()` rotates modes by weighted draw and avoids immediate repeats.
"""
from __future__ import annotations
import json
import random
from pathlib import Path
from typing import Callable


DEFAULT_RHETORIC_PATH = Path(__file__).resolve().parent.parent / "rhetoric.json"

_MODE_WEIGHTS = (
    ("consecration", 0.70),
    ("doctrinal",    0.20),
    ("ritual",       0.10),
)


class _SafeFormatDict(dict):
    """Format-map mapping that leaves unknown {tokens} literal instead
    of raising KeyError. Lets the JSON declare tokens the call site
    didn't supply without crashing the scripture log."""
    def __missing__(self, key):
        return "{" + key + "}"


class Rhetoric:
    """Holds the rhetoric pool and picks lines on demand.

    Stateful: tracks the most-recently-spoken line per (power, god) so
    we don't immediately repeat. If a pool has only one line, the
    no-repeat rule yields silently.
    """

    def __init__(self, pool: dict, seed: int = 0):
        self._pool = pool
        self._rng = random.Random(seed)
        self._last: dict[tuple[str, str], str] = {}

    @classmethod
    def from_file(cls, path: Path | str = DEFAULT_RHETORIC_PATH,
                   seed: int = 0) -> "Rhetoric":
        p = Path(path)
        with open(p, "r", encoding="utf-8") as f:
            data = json.load(f)
        return cls(data, seed=seed)

    def pick(self, power_key: str, god_key: str, sim_t: float = 0.0,
              tokens: dict | None = None) -> str:
        """Return a scripture line. Falls through gracefully if a key
        is missing — so a brand-new power that hasn't had lines written
        yet still gets a placeholder rather than a KeyError.

        If `tokens` is provided, `{name}` placeholders in the line are
        substituted via str.format_map; unknown tokens are left literal
        (see `_SafeFormatDict`). When `tokens` is None, the line is
        returned verbatim — preserves pre-PR3-step-12 behavior."""
        god_pool = self._pool.get(power_key, {}).get(god_key)
        if not god_pool:
            return f"<{power_key}>"

        mode = self._pick_mode(god_pool)
        lines = god_pool.get(mode) or god_pool.get("consecration") or []
        if not lines:
            return f"<{power_key}>"

        last_key = (power_key, god_key)
        last_line = self._last.get(last_key)
        # Try up to N times to avoid immediate repeat.
        for _ in range(8):
            line = self._rng.choice(lines)
            if line != last_line or len(lines) == 1:
                self._last[last_key] = line
                return self._interpolate(line, tokens)
        # All rolls matched the last (huge dupe in pool); accept it.
        self._last[last_key] = line
        return self._interpolate(line, tokens)

    @staticmethod
    def _interpolate(line: str, tokens: dict | None) -> str:
        if tokens is None:
            return line
        try:
            return line.format_map(_SafeFormatDict(tokens))
        except (ValueError, IndexError):
            # Malformed format spec — leave the line literal rather
            # than crash the scripture log mid-cast.
            return line

    def _pick_mode(self, god_pool: dict) -> str:
        """Weighted pick. Drop modes the pool doesn't have."""
        weights = [(m, w) for m, w in _MODE_WEIGHTS if god_pool.get(m)]
        if not weights:
            return "consecration"
        total = sum(w for _, w in weights)
        roll = self._rng.random() * total
        cur = 0.0
        for mode, w in weights:
            cur += w
            if roll <= cur:
                return mode
        return weights[-1][0]


def make_picker(rhet: Rhetoric) -> Callable[[str, str, float], str]:
    """Convenience: return a function suitable for `PowerSystem(rhetoric_pick=...)`."""
    return rhet.pick
