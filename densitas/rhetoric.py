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
from dataclasses import dataclass
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

    def has(self, power_key: str, god_key: str) -> bool:
        """True if the pool has at least one line for this (key, god).
        PR4 step 7a: lets the coalescer decide whether a `<key>_many`
        plural cell exists before it commits to it."""
        return bool(self._pool.get(power_key, {}).get(god_key))

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


@dataclass
class _Batch:
    count: int
    first_sim_t: float
    tokens: dict


class ScriptureCoalescer:
    """PR4 step 7a - rate limiter for event-driven scripture (spec §4).

    Conversion cascades along a seam fire dozens of events a second, and
    the log must not spam. Rule: at most one line per (key, faction) per
    `window` sim seconds. *Leading edge*: the first event in a quiet
    window is voiced at once with `{count} = 1`, so a lone conversion
    shows up the moment it happens. Everything after it inside the window
    is batched and flushed as one line at the window's end with
    `{count} = N`, from the `<key>_many` cell when the pool has one and
    the singular cell (with `{count}` still substituted) when it does not.

    `voice(key, faction, sim_t, tokens) -> str` does the picking and the
    logging; `has(key, faction) -> bool` says whether a cell exists. Both
    are injected so this class knows nothing about gods or the log.
    """

    def __init__(self, window: float,
                 voice: Callable[[str, int, float, dict], str],
                 has: Callable[[str, int], bool] | None = None) -> None:
        self.window = max(0.0, float(window))
        self._voice = voice
        self._has = has or (lambda key, faction: True)
        self._last_emit: dict[tuple[str, int], float] = {}
        self._pending: dict[tuple[str, int], _Batch] = {}
        self.lines = 0        # lines actually voiced
        self.batched = 0      # events folded into a {count} line

    def emit(self, key: str, faction: int, sim_t: float,
             tokens: dict | None = None) -> str | None:
        """Report one event. Returns the line if it was voiced now, else
        None (it joined a batch)."""
        k = (key, faction)
        last = self._last_emit.get(k)
        quiet = last is None or (sim_t - last) >= self.window
        if k not in self._pending and quiet:
            return self._fire(key, faction, sim_t, 1, tokens)
        b = self._pending.get(k)
        if b is None:
            self._pending[k] = _Batch(1, sim_t, dict(tokens or {}))
        else:
            b.count += 1
        return None

    def tick(self, sim_t: float) -> list[str]:
        """Flush every batch whose window has elapsed. Returns the lines."""
        out: list[str] = []
        for k in list(self._pending):
            last = self._last_emit.get(k, float("-inf"))
            if (sim_t - last) >= self.window:
                b = self._pending.pop(k)
                out.append(self._fire(k[0], k[1], sim_t, b.count, b.tokens))
        return out

    def flush(self, sim_t: float) -> list[str]:
        """Voice every pending batch regardless of window - end of round."""
        out: list[str] = []
        for k in list(self._pending):
            b = self._pending.pop(k)
            out.append(self._fire(k[0], k[1], sim_t, b.count, b.tokens))
        return out

    def _fire(self, key: str, faction: int, sim_t: float, count: int,
              tokens: dict | None) -> str:
        toks = dict(tokens or {})
        toks["count"] = count
        use_key = key
        if count > 1 and self._has(f"{key}_many", faction):
            use_key = f"{key}_many"
        self._last_emit[(key, faction)] = sim_t
        self.lines += 1
        if count > 1:
            self.batched += count
        return self._voice(use_key, faction, sim_t, toks)


def make_picker(rhet: Rhetoric) -> Callable[[str, str, float], str]:
    """Convenience: return a function suitable for `PowerSystem(rhetoric_pick=...)`."""
    return rhet.pick
