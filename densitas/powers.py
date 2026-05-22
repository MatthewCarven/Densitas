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

P3 PR2 ships:
  T1 — Raise / Lower, wired through `mutate_tile=` (passed in from main.py
  so powers.py stays renderer-agnostic). Drown rule runs in the caller's
  closure after a successful mutation.

P3-Queue ships (Densitas_queue.md):
  Click-chain queue for Raise / Lower. `cast_or_queue` enqueues when the
  power is on cooldown (or the queue is non-empty); `drain_queues` pops
  one entry per cleared cooldown and dispatches it. Belief debits on
  enqueue; cancel refunds; invalid-at-dispatch burns silently.

PR3 adds Relics.

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


@dataclass
class QueuedCast:
    """One pending cast in the per-(faction, kind) queue (Densitas_queue.md).

    `paid` records the belief actually debited at enqueue so cancel
    refunds the exact amount — protects us from a future where cost
    depends on local conditions.

    `suppress_scripture` is set by the caller (P3-Brush) so a single
    bulk-click motion emits exactly one scripture line — the brush's
    first tile carries the voice; tiles 2..N**2 dispatch silently.
    Default False keeps single-tile click-chains emitting per-tile,
    matching the pre-brush queue behaviour.
    """
    kind: PowerKind
    faction: int
    tx: int
    ty: int
    queued_at: float
    paid: float
    suppress_scripture: bool = False


# Powers the player can chain via LMB while a previous cast is cooling.
# Extending this set is a one-line change.
QUEUEABLE_KINDS: frozenset[int] = frozenset({
    int(PowerKind.RAISE), int(PowerKind.LOWER),
})


def _is_queueable(kind: PowerKind) -> bool:
    return int(kind) in QUEUEABLE_KINDS


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
        # P3-Queue — pending click-chain casts per (faction, kind). FIFO.
        # See Densitas_queue.md. Drained by `drain_queues()`.
        self.queues: dict[tuple[int, int], list[QueuedCast]] = {}
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
        *, skip_cooldown: bool = False,
    ) -> tuple[bool, str]:
        """Return (ok, reason). Reason is a short HUD string.

        `skip_cooldown=True` is for the queue-enqueue validation path
        (Densitas_queue.md) — the caller already knows the power is
        cooling and wants to add to the queue; tier / pool / bounds /
        tile checks still apply.
        """
        spec = POWERS.get(kind)
        if spec is None:
            return False, f"unknown power"

        # Tier gate.
        _, tier_idx = tier_for(citizens.population(faction))
        if tier_idx < spec.tier:
            return False, f"need T{spec.tier - 1}"

        # Cooldown.
        if not skip_cooldown:
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
        suppress_scripture: bool = False,
    ) -> CastReceipt:
        """Validate, debit, dispatch, log. Returns a CastReceipt.

        `suppress_scripture` lets the brush caller (P3-Brush) silence
        the scripture line for tiles 2..N**2 of a bulk Raise/Lower so
        one click yields one voice. Validation failures never emit
        scripture either way.
        """
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

        # Scripture (suppressed by P3-Brush on tiles 2..N**2 of a bulk
        # cast — the first tile of the brush carries the voice).
        if not suppress_scripture:
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
        # PR2: terrain step up via the injected callback. main.py wires it.
        # If no callback (unit tests, headless smokes), this is a no-op —
        # the cast still charges per the "dispatch failure charges" rule.
        if self._mutate_tile is None:
            return
        old = int(world.tiles[ty, tx])
        new = _height_ladder_up(old)
        if new == old:
            return
        self._mutate_tile(tx, ty, new)

    def _dispatch_lower(self, faction, tx, ty, strength, citizens,
                         world, food, belief, sim_t):
        # PR2: terrain step down. The drown rule for newly-water tiles
        # runs inside the callback (see main.py's closure).
        if self._mutate_tile is None:
            return
        old = int(world.tiles[ty, tx])
        new = _height_ladder_down(old)
        if new == old:
            return
        self._mutate_tile(tx, ty, new)

    # -- queue --------------------------------------------------------------

    def cast_or_queue(
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
        suppress_scripture: bool = False,
    ) -> CastReceipt:
        """Fire immediately if ready, else enqueue (Densitas_queue.md).

        Non-queueable kinds always go through `cast()` unchanged. For
        queueable kinds, the ready path is *both* cooldown clear AND queue
        empty — so a new click never jumps ahead of already-queued tiles.

        `suppress_scripture` (P3-Brush) silences this cast's scripture
        line so a bulk Raise/Lower click emits exactly one voice for the
        whole NxN brush. The flag is forwarded to `cast()` on the
        immediate path and stored on the `QueuedCast` on the queue path
        so the suppression survives the dispatch delay.
        """
        if not _is_queueable(kind):
            return self.cast(kind, faction, tx, ty, citizens, world,
                             food, belief, sim_t,
                             suppress_scripture=suppress_scripture)
        key = (faction, int(kind))
        cd = self.cooldowns.get(key, 0.0)
        q = self.queues.get(key, [])
        if cd <= 0.0 and not q:
            return self.cast(kind, faction, tx, ty, citizens, world,
                             food, belief, sim_t,
                             suppress_scripture=suppress_scripture)
        # Queue path: validate (skipping the cooldown check we know about),
        # debit belief, push to back.
        ok, reason = self.can_cast(kind, faction, tx, ty, citizens, world,
                                    skip_cooldown=True)
        if not ok:
            return CastReceipt(kind, faction, int(tx), int(ty), sim_t, sim_t,
                                ok=False, reason=reason)
        spec = POWERS[kind]
        q = self.queues.setdefault(key, [])
        if len(q) >= self.cfg.queue_cap:
            return CastReceipt(kind, faction, int(tx), int(ty), sim_t, sim_t,
                                ok=False, reason="queue full")
        self.pool[faction] -= spec.belief_cost
        if self.pool[faction] < 0.0:
            self.pool[faction] = 0.0
        q.append(QueuedCast(
            kind=kind, faction=faction, tx=int(tx), ty=int(ty),
            queued_at=sim_t, paid=spec.belief_cost,
            suppress_scripture=suppress_scripture,
        ))
        return CastReceipt(kind, faction, int(tx), int(ty), sim_t, sim_t,
                            ok=True, reason="queued")

    def drain_queues(
        self,
        citizens: CitizenManager,
        world: World,
        food,
        belief: BeliefField,
        sim_t: float,
    ) -> int:
        """Pop and dispatch one queued cast per (faction, kind) whose
        cooldown has cleared. Returns the count drained this call.

        Called from the main loop *after* `tick()` so a just-cleared
        cooldown can dispatch in the same sim step.
        """
        drained = 0
        for key, q in list(self.queues.items()):
            if not q:
                del self.queues[key]
                continue
            if self.cooldowns.get(key, 0.0) > 0.0:
                continue
            qc = q.pop(0)
            self._dispatch_queued(qc, citizens, world, food, belief, sim_t)
            drained += 1
            if not q:
                del self.queues[key]
        return drained

    def cancel_queued_at(self, tx: int, ty: int, kind: PowerKind,
                          faction: int) -> bool:
        """Remove the first QueuedCast matching (tx, ty, kind, faction)
        and refund its `paid` cost. Returns True if something was cancelled.
        """
        key = (faction, int(kind))
        q = self.queues.get(key)
        if not q:
            return False
        for i, qc in enumerate(q):
            if qc.tx == int(tx) and qc.ty == int(ty):
                self.pool[faction] += qc.paid
                del q[i]
                if not q:
                    del self.queues[key]
                return True
        return False

    def clear_queue(self, kind: PowerKind, faction: int) -> int:
        """Refund every queued cast for (kind, faction). Returns count
        cleared."""
        key = (faction, int(kind))
        q = self.queues.pop(key, [])
        if q:
            self.pool[faction] += sum(qc.paid for qc in q)
        return len(q)

    def _dispatch_queued(self, qc: "QueuedCast",
                         citizens: CitizenManager, world: World,
                         food, belief: BeliefField, sim_t: float) -> None:
        """Run a queued cast. Re-validate the tile; on invalid, burn the
        cooldown silently with a `queued_invalid` scripture line (no refund
        — the gesture happened, the world moved on).

        P3-Brush: when `qc.suppress_scripture` is set (tiles 2..N**2 of
        a bulk Raise/Lower), no scripture line is appended on either the
        valid or invalid path. The brush's first tile carries the voice
        for the whole motion.
        """
        spec = POWERS[qc.kind]
        tile_id = int(world.tiles[qc.ty, qc.tx])
        ok, _reason = _tile_valid_for(qc.kind, tile_id)
        god_key = _god_key_for(qc.faction)
        if not ok:
            self.cooldowns[(qc.faction, int(qc.kind))] = spec.cooldown
            if not qc.suppress_scripture:
                line = self._rhetoric("queued_invalid", god_key, sim_t)
                self.scripture_log.append(
                    ScriptureEntry(sim_t, line, qc.kind, qc.faction))
            return
        # Set cooldown, then dispatch (belief was debited at enqueue).
        self.cooldowns[(qc.faction, int(qc.kind))] = spec.cooldown
        local_b = belief.query(qc.tx, qc.ty, qc.faction)
        kt_idx = max(0, min(len(self.cfg.k_tier) - 1, spec.tier - 1))
        k = self.cfg.k_tier[kt_idx]
        strength = max(0.0, local_b) / max(1e-3, k)
        self._dispatch[qc.kind](
            faction=qc.faction, tx=qc.tx, ty=qc.ty, strength=strength,
            citizens=citizens, world=world, food=food, belief=belief,
            sim_t=sim_t,
        )
        if not qc.suppress_scripture:
            line = self._rhetoric(spec.rhetoric_key, god_key, sim_t)
            self.scripture_log.append(
                ScriptureEntry(sim_t, line, qc.kind, qc.faction))

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
