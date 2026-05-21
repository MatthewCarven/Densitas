"""Powers — the player-verb layer.

See `Densitas_P3.md` for the spec. Summary:

  * `PowerKind`   — enum of all power kinds.
  * `PowerSpec`   — frozen dataclass holding tier/cost/cooldown/AoE.
  * `POWERS`      — registry mapping kind -> spec.
  * `ActiveEffect`— Bless/Curse instances, scanned each tick.
  * `ScriptureEntry` — one log line per cast.
  * `PowerSystem` — owns pool, cooldowns, effects, log. Validates
                    casts, dispatches effects, ticks per sim frame.

P3 PR1 ships:
  T0 — Inspire (real), Calm (stub), Hunger Pang (stub-against-rival).
  T1 — Bless, Curse.

PR2 will add Raise/Lower; PR3 adds Relics.

The dispatch table is a dict of callables so each new power kind in P5
adds exactly one registration line.
"""
from __future__ import annotations
import enum
import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable, Optional, Tuple

import numpy as np

from .config import PowerConfig
from .citizen import CitizenManager, Citizen, CitizenState, tier_for
from .world import World, Tile
from .belief import BeliefField, N_FACTIONS


N_TIERS = 5  # T0..T4 ; matches tier_for() ladder.


class PowerKind(enum.IntEnum):
    """All powers. Add new kinds at the bottom — values are stable."""
    INSPIRE     = 0    # T0
    CALM        = 1    # T0  (stub for P3; needs FLEE state)
    HUNGER_PANG = 2    # T0  (needs rival citizens to bite)
    RAISE       = 10   # T1  (terrain; PR2)
    LOWER       = 11   # T1  (terrain; PR2)
    BLESS       = 12   # T1
    CURSE       = 13   # T1
    # SPRING       = 14  # T1 — deferred to P3.5


@dataclass(frozen=True)
class PowerSpec:
    """Frozen description of a single power."""
    kind: PowerKind
    name: str                  # display name in HUD/scripture
    tier: int                  # min tier_idx required (0..4)
    belief_cost: float
    cooldown: float
    aoe_radius: int            # 0 = point target
    duration: float            # for persistent effects; 0 = instant
    rhetoric_key: str          # key in rhetoric.json


# Defaults — actual numbers come from PowerConfig at PowerSystem boot,
# but a frozen registry helps for tier-gate / lookup / iteration before
# the cfg is loaded (e.g. in tests).
POWERS: dict[PowerKind, PowerSpec] = {
    PowerKind.INSPIRE:     PowerSpec(PowerKind.INSPIRE,     "Inspire",      tier=1, belief_cost=0.0,  cooldown=1.5, aoe_radius=4,  duration=0.0,  rhetoric_key="inspire"),
    PowerKind.CALM:        PowerSpec(PowerKind.CALM,        "Calm",         tier=1, belief_cost=0.0,  cooldown=1.5, aoe_radius=2,  duration=5.0,  rhetoric_key="calm"),
    PowerKind.HUNGER_PANG: PowerSpec(PowerKind.HUNGER_PANG, "Hunger Pang",  tier=1, belief_cost=1.0,  cooldown=3.0, aoe_radius=0,  duration=0.0,  rhetoric_key="hunger_pang"),
    PowerKind.RAISE:       PowerSpec(PowerKind.RAISE,       "Raise",        tier=2, belief_cost=5.0,  cooldown=2.0, aoe_radius=0,  duration=0.0,  rhetoric_key="raise"),
    PowerKind.LOWER:       PowerSpec(PowerKind.LOWER,       "Lower",        tier=2, belief_cost=5.0,  cooldown=2.0, aoe_radius=0,  duration=0.0,  rhetoric_key="lower"),
    PowerKind.BLESS:       PowerSpec(PowerKind.BLESS,       "Bless",        tier=2, belief_cost=10.0, cooldown=4.0, aoe_radius=4,  duration=30.0, rhetoric_key="bless"),
    PowerKind.CURSE:       PowerSpec(PowerKind.CURSE,       "Curse",        tier=2, belief_cost=10.0, cooldown=4.0, aoe_radius=4,  duration=30.0, rhetoric_key="curse"),
}


@dataclass
class ActiveEffect:
    """A Bless or Curse currently modulating the food field."""
    kind: PowerKind
    tx: int
    ty: int
    radius: int
    multiplier: float
    timer: float                 # sim_s remaining
    caster_faction: int


@dataclass
class ScriptureEntry:
    """One scripture-log line."""
    sim_t: float                 # when emitted
    line: str
    power: PowerKind
    faction: int


@dataclass
class CastReceipt:
    """Returned by `cast()`. For T0/T1 in P3, `resolve_at == sim_t` so
    casts apply instantly. P5+ T3+ powers will widen the window so the
    counter-cast rule can interpose."""
    kind: PowerKind
    faction: int
    tx: int
    ty: int
    sim_t: float
    resolve_at: float
    ok: bool
    reason: str = ""


class PowerSystem:
    """Owns belief pool, cooldowns, active effects, scripture log.

    Wiring (called by main.py):

      ps.tick(dt, citizens, sim_t)           # every sim tick
      ps.cast(kind, faction, tx, ty, ...)    # on user input

    Callbacks:
      `mutate_tile(tx, ty, new_tile) -> bool`  invoked by Raise/Lower (PR2).
      `rhetoric_pick(power_key, god_key, sim_t) -> str`  invoked on cast.

    Both are passed in to keep `powers.py` from importing renderer/IO.
    """

    def __init__(
        self,
        cfg: PowerConfig,
        n_factions: int = N_FACTIONS,
        rhetoric_pick: Optional[Callable[[str, str, float], str]] = None,
        mutate_tile: Optional[Callable[[int, int, int], bool]] = None,
    ):
        self.cfg = cfg
        self.n_factions = n_factions
        # Belief pool per faction. Uncapped in P3.
        # TODO(P5): soft cap = 5000 + 10 * population once T2+ exists.
        self.pool: list[float] = [0.0] * n_factions
        # Per-faction per-kind cooldowns. {(faction, kind): seconds_remaining}
        self.cooldowns: dict[tuple[int, int], float] = {}
        # Live effects (Bless/Curse). Scanned each tick.
        self.effects: list[ActiveEffect] = []
        # Scripture log. List of ScriptureEntry, FIFO. Old entries pruned by sim_t.
        self.scripture_log: list[ScriptureEntry] = []
        # Hooks (None = stub; tests pass mocks).
        self._rhetoric = rhetoric_pick or (lambda p, g, t: f"<{p}>")
        self._mutate_tile = mutate_tile  # used by Raise/Lower in PR2

        # Per-kind dispatch table. Populated below.
        self._dispatch: dict[PowerKind, Callable] = {
            PowerKind.INSPIRE:     self._dispatch_inspire,
            PowerKind.CALM:        self._dispatch_calm,
            PowerKind.HUNGER_PANG: self._dispatch_hunger_pang,
            PowerKind.RAISE:       self._dispatch_raise,        # PR2
            PowerKind.LOWER:       self._dispatch_lower,        # PR2
            PowerKind.BLESS:       self._dispatch_bless,
            PowerKind.CURSE:       self._dispatch_curse,
        }

    # -- tick ---------------------------------------------------------------

    def tick(self, dt: float, citizens: CitizenManager, sim_t: float) -> None:
        """Advance pool regen, cooldowns, effect timers, scripture log fade."""
        # 1. Pool regen.
        rate = self.cfg.belief_regen_per_citizen
        for f in range(self.n_factions):
            pop = citizens.population(f)
            self.pool[f] += pop * rate * dt

        # 2. Cooldowns bleed.
        for key in list(self.cooldowns.keys()):
            self.cooldowns[key] -= dt
            if self.cooldowns[key] <= 0.0:
                del self.cooldowns[key]

        # 3. Active effect timers.
        for e in self.effects:
            e.timer -= dt
        self.effects = [e for e in self.effects if e.timer > 0.0]

        # 4. Scripture log fade — drop entries older than fade_seconds.
        cutoff = sim_t - self.cfg.rhetoric_fade_seconds
        if self.scripture_log and self.scripture_log[0].sim_t < cutoff:
            self.scripture_log = [s for s in self.scripture_log if s.sim_t >= cutoff]

    # -- validation ---------------------------------------------------------

    def can_cast(
        self, kind: PowerKind, faction: int, tx: int, ty: int,
        citizens: CitizenManager, world: World,
    ) -> tuple[bool, str]:
        """Return (ok, reason). Reason is a short HUD string."""
        spec = POWERS.get(kind)
        if spec is None:
            return False, f"unknown power"

        # Tier gate.
        _, tier_idx = tier_for(citizens.population(faction))
        if tier_idx < spec.tier:
            return False, f"need T{spec.tier - 1}"

        # Cooldown.
        cd = self.cooldowns.get((faction, int(kind)), 0.0)
        if cd > 0.0:
            return False, f"cooling {cd:.1f}s"

        # Belief cost.
        if self.pool[faction] < spec.belief_cost - 1e-6:
            return False, f"need {spec.belief_cost:.0f} belief"

        # Tile bounds.
        if not world.in_bounds(int(tx), int(ty)):
            return False, "out of bounds"

        # Per-kind tile checks.
        tile_id = int(world.tiles[int(ty), int(tx)])
        ok, reason = _tile_valid_for(kind, tile_id)
        if not ok:
            return False, reason

        return True, ""

    # -- cast ---------------------------------------------------------------

    def cast(
        self,
        kind: PowerKind,
        faction: int,
        tx: int,
        ty: int,
        citizens: CitizenManager,
        world: World,
        food,
        belief: BeliefField,
        sim_t: float,
    ) -> CastReceipt:
        """Validate, debit, dispatch, log. Returns a CastReceipt."""
        ok, reason = self.can_cast(kind, faction, tx, ty, citizens, world)
        if not ok:
            return CastReceipt(kind, faction, int(tx), int(ty), sim_t, sim_t,
                                ok=False, reason=reason)

        spec = POWERS[kind]

        # Debit pool, set cooldown. (P3 simplification: full charge even
        # on dispatch failure; refunds kick in at T2+ per spec.)
        self.pool[faction] -= spec.belief_cost
        if self.pool[faction] < 0.0:
            self.pool[faction] = 0.0
        self.cooldowns[(faction, int(kind))] = spec.cooldown

        # Strength scaling: local belief / k_tier
        local_b = belief.query(int(tx), int(ty), faction)
        kt_idx = max(0, min(len(self.cfg.k_tier) - 1, spec.tier - 1))
        k = self.cfg.k_tier[kt_idx]
        strength = max(0.0, local_b) / max(1e-3, k)

        # Dispatch.
        self._dispatch[kind](
            faction=faction, tx=int(tx), ty=int(ty), strength=strength,
            citizens=citizens, world=world, food=food, belief=belief,
            sim_t=sim_t,
        )

        # Scripture.
        god_key = _god_key_for(faction)
        line = self._rhetoric(spec.rhetoric_key, god_key, sim_t)
        self.scripture_log.append(ScriptureEntry(sim_t, line, kind, faction))
        if len(self.scripture_log) > self.cfg.scripture_log_max:
            self.scripture_log = self.scripture_log[-self.cfg.scripture_log_max:]

        return CastReceipt(kind, faction, int(tx), int(ty), sim_t, sim_t,
                            ok=True, reason="")

    # -- dispatch (per power) ----------------------------------------------

    def _dispatch_inspire(self, faction, tx, ty, strength, citizens,
                           world, food, belief, sim_t):
        spec = POWERS[PowerKind.INSPIRE]
        bias_duration = 10.0  # sim seconds the citizen pursues the bias before re-randomising
        citizens.inspire_citizen(
            target_tx=tx, target_ty=ty,
            faction=faction, max_radius=spec.aoe_radius,
            bias_duration=bias_duration,
        )

    def _dispatch_calm(self, faction, tx, ty, strength, citizens, world,
                        food, belief, sim_t):
        # Stub: FLEE state doesn't exist yet (P4). No-op + scripture line.
        pass

    def _dispatch_hunger_pang(self, faction, tx, ty, strength, citizens,
                               world, food, belief, sim_t):
        # Stub: pick nearest other-faction citizen and force them to FORAGE.
        # If no rivals exist (P3 default), this is effectively a no-op.
        target = citizens.find_nearest_other_faction(
            tx=tx, ty=ty, my_faction=faction, radius=12,
        )
        if target is None:
            return
        target.state = CitizenState.FORAGE
        # Point at their current location so they search-from-here.
        target.target_x = float(target.x)
        target.target_y = float(target.y)

    def _dispatch_bless(self, faction, tx, ty, strength, citizens,
                         world, food, belief, sim_t):
        spec = POWERS[PowerKind.BLESS]
        # Most-recent-wins: drop any prior Bless/Curse covering this exact tile by same caster.
        self._purge_effect_at(tx, ty, faction)
        self.effects.append(ActiveEffect(
            kind=PowerKind.BLESS, tx=tx, ty=ty,
            radius=spec.aoe_radius, multiplier=self.cfg.bless_multiplier,
            timer=self.cfg.effect_duration_t1, caster_faction=faction,
        ))

    def _dispatch_curse(self, faction, tx, ty, strength, citizens,
                         world, food, belief, sim_t):
        spec = POWERS[PowerKind.CURSE]
        self._purge_effect_at(tx, ty, faction)
        self.effects.append(ActiveEffect(
            kind=PowerKind.CURSE, tx=tx, ty=ty,
            radius=spec.aoe_radius, multiplier=self.cfg.curse_multiplier,
            timer=self.cfg.effect_duration_t1, caster_faction=faction,
        ))

    def _dispatch_raise(self, faction, tx, ty, strength, citizens,
                         world, food, belief, sim_t):
        # PR2 — terrain mutation. Stubbed for PR1 so the dispatch table is complete.
        if self._mutate_tile is None:
            return
        old = int(world.tiles[ty, tx])
        new = _height_ladder_up(old)
        if new == old:
            return
        self._mutate_tile(tx, ty, new)

    def _dispatch_lower(self, faction, tx, ty, strength, citizens,
                         world, food, belief, sim_t):
        if self._mutate_tile is None:
            return
        old = int(world.tiles[ty, tx])
        new = _height_ladder_down(old)
        if new == old:
            return
        self._mutate_tile(tx, ty, new)

    # -- internals ----------------------------------------------------------

    def _purge_effect_at(self, tx: int, ty: int, faction: int) -> None:
        """Drop any active effect of the same caster centered on (tx, ty)."""
        self.effects = [
            e for e in self.effects
            if not (e.tx == tx and e.ty == ty and e.caster_faction == faction)
        ]


# -- module helpers --------------------------------------------------------

def _god_key_for(faction: int) -> str:
    """JSON key for the faction's rhetoric block."""
    if faction == 0: return "open_eye"
    if faction == 1: return "maw"
    return f"faction_{faction}"


def _tile_valid_for(kind: PowerKind, tile_id: int) -> tuple[bool, str]:
    """Per-kind tile-validation. Returns (ok, reason)."""
    if kind == PowerKind.RAISE:
        if tile_id == int(Tile.MOUNTAIN): return False, "can't raise mountain"
        if tile_id == int(Tile.LAVA):     return False, "can't raise lava"
        if tile_id == int(Tile.HOLY):     return False, "can't raise holy"
        return True, ""
    if kind == PowerKind.LOWER:
        if tile_id == int(Tile.WATER):    return False, "can't lower water"
        if tile_id == int(Tile.LAVA):     return False, "can't lower lava"
        if tile_id == int(Tile.HOLY):     return False, "can't lower holy"
        return True, ""
    if kind in (PowerKind.BLESS, PowerKind.CURSE):
        # Must land on a food-bearing tile (i.e. one whose biome has nonzero regen).
        if tile_id in (int(Tile.WATER), int(Tile.MOUNTAIN),
                       int(Tile.LAVA), int(Tile.BLIGHTED)):
            return False, "no food here"
        return True, ""
    if kind in (PowerKind.INSPIRE, PowerKind.CALM, PowerKind.HUNGER_PANG):
        return True, ""
    return True, ""


def _height_ladder_up(tile_id: int) -> int:
    """Tile after one Raise. See P3 spec §5.1."""
    ladder = {
        int(Tile.WATER):    int(Tile.BEACH),
        int(Tile.BEACH):    int(Tile.GRASS),
        int(Tile.GRASS):    int(Tile.FOREST),
        int(Tile.FOREST):   int(Tile.HILL),
        int(Tile.HILL):     int(Tile.MOUNTAIN),
        int(Tile.BLIGHTED): int(Tile.GRASS),  # slow reclamation
    }
    return ladder.get(tile_id, tile_id)


def _height_ladder_down(tile_id: int) -> int:
    """Tile after one Lower. Mirrors `_up`."""
    ladder = {
        int(Tile.MOUNTAIN): int(Tile.HILL),
        int(Tile.HILL):     int(Tile.FOREST),
        int(Tile.FOREST):   int(Tile.GRASS),
        int(Tile.GRASS):    int(Tile.BEACH),
        int(Tile.BEACH):    int(Tile.WATER),
        int(Tile.BLIGHTED): int(Tile.WATER),
    }
    return ladder.get(tile_id, tile_id)


def effective_food_regen(
    base_regen: np.ndarray, effects: Iterable[ActiveEffect],
) -> np.ndarray:
    """Build an effective regen field by applying all active Bless/Curse
    effects on top of `base_regen`. Returns a new array, leaves base unchanged.

    The simpler O(N * tiles) loop is fine while concurrent effect count is
    small (<10).
    """
    out = base_regen.copy()
    if not effects:
        return out
    h, w = base_regen.shape
    for e in effects:
        r = int(e.radius)
        x0 = max(0, e.tx - r)
        x1 = min(w, e.tx + r + 1)
        y0 = max(0, e.ty - r)
        y1 = min(h, e.ty + r + 1)
        if x0 >= x1 or y0 >= y1:
            continue
        # Round AoE: keep tiles within Chebyshev distance r (square footprint).
        out[y0:y1, x0:x1] *= e.multiplier
    return out
