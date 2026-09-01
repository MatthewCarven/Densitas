"""PR4 step 4 - the rival god's brain (spec `Densitas_rival_ai.md` §6-§10).

One decision every `ai_base_period / difficulty` sim seconds: sense the
board, score every intent, act on the argmax if it beats `idle_floor`.
Cadence is the *only* thing difficulty touches (pillar 2).

**Steps 5-6: every intent is live.** The four cast intents go out
through `PowerSystem.cast_or_queue` and the three relic intents through
`RelicManager.place / move / retrieve` - the same entry points a player
click uses, so the rival pays the same belief, burns the same cooldowns,
obeys the same `can_cast` / `can_place`, and voices the same scripture
path keyed by its own god.

Dependency direction: only `main.py` imports this module, and this module
imports only public APIs of the others (§6). Note `god_key_for` was
promoted out of `powers.py`'s private namespace for exactly that reason.

Deviation from §6's prose, noted rather than designed around: it says
"one class, one dataclass, one preset table" but then names
`DecisionRecord` too. There are three dataclasses here - `AIPersonality`,
`Senses` and `DecisionRecord`. Folding senses into the class body would
have made the determinism tests reach into private state.
"""
from __future__ import annotations

import enum
from collections import deque
from dataclasses import dataclass
from typing import Callable, Optional

import numpy as np

from .belief import BeliefField
from .citizen import CitizenManager, tier_for
from .powers import POWERS, PowerKind, PowerSystem, god_key_for
from .relics import Relic, RelicManager, RelicState
from .world import World, is_walkable_tile


_EPS = 1e-9

# Float slack for the cadence comparison. Ten additions of 0.2 land on
# 1.9999999999999998, not 2.0, so a naive `accum < period` would push
# every decision one logic tick late and make the cadence tests fragile.
_CADENCE_EPS = 1e-9

# How many of the hottest seam cells CAST_LOWER inspects for ridge tiles.
# Bounded work: K cells x 16 tiles per cell, at the decision cadence.
_LOWER_SCAN_CELLS = 8

# Distance (world tiles) at which a placed relic counts as fully out of
# position for RELIC_MOVE's utility. 32 tiles = 8 belief cells. Opening
# bid; step 8's balance pass owns it.
_DRIFT_REF_TILES = 32.0

# Drift (world tiles) a placed relic must be out of position before
# RELIC_MOVE will touch it. Without a deadband the rear-most relic is
# always *some* distance from the push point, so the AI spends half its
# decisions shuffling flags it has already planted (measured: 157 relic
# acts in 300 decisions before this existed). Below the deadband the
# intent scores zero; above it the ramp runs to `_DRIFT_REF_TILES`.
_MOVE_DEADBAND_TILES = 8.0

# Fractions of `relic_forward_bias` sampled when the push point itself is
# unplaceable, most-forward first. Bounded and small on purpose: §8 wants
# no scanning loops, and this is "plant as far forward as the ground
# allows", not a search.
_PUSH_FALLBACK_FRACTIONS = (1.0, 0.8, 0.6, 0.4, 0.2)

# Distance (world tiles) at which a new relic counts as fully clear of the
# ones already planted. Below it, RELIC_PLACE's utility falls off, so the
# three flags spread along the advance instead of stacking on one tile.
# 16 tiles = 4 belief cells.
_RELIC_SPREAD_TILES = 16.0


class Intent(enum.IntEnum):
    """The PR4 intent menu (§8). Values are stable; new intents append."""
    IDLE             = 0
    CAST_CURSE       = 1
    CAST_HUNGER_PANG = 2
    CAST_LOWER       = 3
    CAST_BLESS       = 4
    RELIC_PLACE      = 5
    RELIC_MOVE       = 6
    RELIC_RETRIEVE   = 7


# Intents that resolve to a power cast, and the power they cast.
INTENT_POWER: dict[Intent, PowerKind] = {
    Intent.CAST_CURSE:       PowerKind.CURSE,
    Intent.CAST_HUNGER_PANG: PowerKind.HUNGER_PANG,
    Intent.CAST_LOWER:       PowerKind.LOWER,
    Intent.CAST_BLESS:       PowerKind.BLESS,
}

# Every scoreable intent, in stable order. IDLE is the floor, not a
# candidate, so it is absent. Order is load-bearing: the jitter vector is
# drawn against it, so changing it changes every seeded decision stream.
SCORED_INTENTS: tuple[Intent, ...] = (
    Intent.CAST_CURSE, Intent.CAST_HUNGER_PANG,
    Intent.CAST_LOWER, Intent.CAST_BLESS,
    Intent.RELIC_PLACE, Intent.RELIC_MOVE, Intent.RELIC_RETRIEVE,
)

# Intent -> the AIPersonality field holding its weight.
WEIGHT_ATTR: dict[Intent, str] = {
    Intent.CAST_CURSE:       "w_curse",
    Intent.CAST_HUNGER_PANG: "w_hunger_pang",
    Intent.CAST_LOWER:       "w_lower",
    Intent.CAST_BLESS:       "w_bless",
    Intent.RELIC_PLACE:      "w_relic_place",
    Intent.RELIC_MOVE:       "w_relic_move",
    Intent.RELIC_RETRIEVE:   "w_relic_retrieve",
}


@dataclass(frozen=True)
class AIPersonality:
    """One brain's parameter block (§6, §9). Frozen: presets are shared."""
    name: str
    # Intent weights. 0 disables an intent for this personality.
    w_curse:            float
    w_hunger_pang:      float
    w_lower:            float
    w_bless:            float
    w_relic_place:      float
    w_relic_move:       float
    w_relic_retrieve:   float
    # Behavioural scalars.
    spend_floor:        float  # pool reserve held back from costed casts
    idle_floor:         float  # best score must beat this to act
    retrieve_panic:     float  # threat_fraction where retrieve starts ramping
    relic_forward_bias: float  # 0 = place at home, 1 = at the enemy's throat
    jitter:             float  # uniform tie-break noise on scores

    def weight(self, intent: Intent) -> float:
        """Weight for `intent`, or 0.0 for one this table does not cover
        (IDLE, and any future intent a preset predates)."""
        attr = WEIGHT_ATTR.get(intent)
        return float(getattr(self, attr)) if attr else 0.0


# §9. The Zealot's numbers are the spec's verbatim opening bids. Steward
# and Trickster fill the gaps the spec left in prose with values that
# match its description; all three are step 8's to tune.
PERSONALITIES: dict[str, AIPersonality] = {
    # §9.1 - aggressive, pushes seams, casts powers cheaply, neglects
    # density.
    "zealot": AIPersonality(
        name="zealot",
        w_curse=1.0, w_hunger_pang=0.8, w_lower=0.3, w_bless=0.1,
        w_relic_place=0.9, w_relic_move=0.5, w_relic_retrieve=0.3,
        spend_floor=0.0, idle_floor=0.05, retrieve_panic=0.75,
        relic_forward_bias=0.65, jitter=0.05,
    ),
    # §9.2 - defensive density. Hoards toward big casts that do not exist
    # until T3, so a PR4 Steward banks belief it will never spend. That is
    # honest inertness, not a bug. A Steward Maw is bless-masked into
    # near-total passivity, which is the joke the spec intends.
    "steward": AIPersonality(
        name="steward",
        w_curse=0.2, w_hunger_pang=0.2, w_lower=0.2, w_bless=1.0,
        w_relic_place=0.5, w_relic_move=0.2, w_relic_retrieve=0.9,
        spend_floor=60.0, idle_floor=0.25, retrieve_panic=0.35,
        relic_forward_bias=0.15, jitter=0.05,
    ),
    # §9.3 - the signature verb (Pilgrimage) is a T2 power that does not
    # exist yet, so this preset zeroes everything distinctive and plays
    # like a timid Zealot. `w_pilgrimage` joins the dataclass with T2.
    "trickster": AIPersonality(
        name="trickster",
        w_curse=0.7, w_hunger_pang=0.6, w_lower=0.2, w_bless=0.1,
        w_relic_place=0.6, w_relic_move=0.4, w_relic_retrieve=0.5,
        spend_floor=0.0, idle_floor=0.15, retrieve_panic=0.50,
        relic_forward_bias=0.40, jitter=0.08,
    ),
}


# §8 god power mask. Lore enforcement in one greppable place: the Maw does
# not bless, whatever a personality's `w_bless` says. Applied before
# scoring, so a masked intent never reaches feasibility, let alone a tile.
GOD_FORBIDS: dict[str, frozenset[PowerKind]] = {
    "maw":      frozenset({PowerKind.BLESS}),
    "open_eye": frozenset(),
}


@dataclass(frozen=True)
class Senses:
    """One decision tick's read-only view of the board (§7).

    Everything here is derivable from what the belief heatmap already
    shows the player - no hidden information (§14). The belief arrays are
    live views, not copies; nothing in this module writes to them.
    """
    sim_t:           float
    pop_own:         int
    pop_enemy:       int
    pool_own:        float
    tier_own:        int
    b_own:           np.ndarray
    b_enemy:         np.ndarray
    seam:            np.ndarray
    peak_own:        float
    peak_enemy:      float
    own_peak_cell:   tuple[int, int]                  # (cx, cy)
    enemy_peak_cell: tuple[int, int]
    seam_peak_cell:  tuple[int, int]
    seam_peak_value: float
    own_centroid:    Optional[tuple[float, float]]    # world tiles
    enemy_centroid:  Optional[tuple[float, float]]
    own_placed:      tuple[Relic, ...]
    own_free_slots:  tuple[int, ...]
    n_slots:         int
    max_threat_frac: float

    @property
    def seam_overlap(self) -> float:
        """How much the two fields actually share, in [0, 1].

        `seam = b_own * b_enemy` reaches `peak_own * peak_enemy` only when
        both fields peak on the same cell, so this ratio is a real contact
        measure rather than a degenerate 1.0-at-the-argmax.
        """
        denom = self.peak_own * self.peak_enemy
        if denom <= _EPS:
            return 0.0
        return float(min(1.0, self.seam_peak_value / denom))


@dataclass(frozen=True)
class DecisionRecord:
    """One entry in the decision ring (§6).

    The spec names `(sim_t, intent, target, score, top3)`; `executed` and
    `note` are additions - step 4 needs to say "scored but no-op", and
    steps 5/6 need somewhere to record a verb refused at the last moment.
    """
    sim_t:    float
    intent:   Intent
    target:   Optional[tuple[int, int]]      # world tile
    score:    float
    top3:     tuple[tuple[Intent, float], ...]
    executed: bool = False
    note:     str = ""

    def format(self) -> str:
        tgt = f"({self.target[0]},{self.target[1]})" if self.target else "-"
        top = ", ".join(f"{i.name} {s:.2f}" for i, s in self.top3)
        tail = f" | {self.note}" if self.note else ""
        return (f"[ai t={self.sim_t:6.1f}] {self.intent.name:<16} @ {tgt:>11} "
                f"score={self.score:.3f} | top3: {top}{tail}")


class RivalAI:
    """The rival god's decision loop. One action per decision tick (§6)."""

    RING = 64

    def __init__(self, faction: int, personality: AIPersonality,
                 rival_cfg, powers_cfg, seed: int,
                 n_factions: int = 2, debug: bool = False) -> None:
        self.faction = int(faction)
        # Two-faction game; generalise when a third god lands.
        self.enemy = 0 if self.faction != 0 else 1
        self.p = personality
        self.rival_cfg = rival_cfg
        self.powers_cfg = powers_cfg
        self.n_factions = n_factions
        self.debug = bool(debug)

        self.god_key = god_key_for(self.faction)
        self.forbidden: frozenset[PowerKind] = GOD_FORBIDS.get(
            self.god_key, frozenset())

        # §6 cadence. `difficulty` scales it and nothing else. The
        # one-logic-tick floor is applied per call, in `tick`, because the
        # tick length is the caller's to know.
        difficulty = max(_EPS, float(getattr(rival_cfg, "difficulty", 1.0)))
        self.base_period = float(getattr(rival_cfg, "ai_base_period", 2.0))
        self.period = self.base_period / difficulty

        # §6 determinism. Every random draw in this module comes from here.
        self.rng = np.random.default_rng(int(seed) ^ (self.faction << 8))

        self._accum = 0.0
        self.decisions = 0
        self.casts = 0        # cast verbs that went out (step 5)
        self.relic_acts = 0   # relic verbs that went out (step 6)
        self.refused = 0      # scored feasible, then refused at the verb
        self.log: deque[DecisionRecord] = deque(maxlen=self.RING)

        # Belief-grid geometry, refreshed on each decision from the live
        # field so a resized grid cannot leave stale block maths behind.
        self._grid_w = 0
        self._grid_h = 0
        self._tpc_x = 1
        self._tpc_y = 1

    # -- cadence -------------------------------------------------------------

    def tick(self, dt: float, *, sim_t: float, citizens: CitizenManager,
             belief: BeliefField, relic_mgr: RelicManager,
             power_system: PowerSystem, world: World,
             food=None) -> Optional[DecisionRecord]:
        """Accumulate; run one sense -> score -> act pass every `period`.

        Returns the DecisionRecord if a decision ran this call, else None.

        `food` is not in §6's signature but `PowerSystem.cast_or_queue`
        requires it, so step 5 threads it through. It defaults to None so
        a caller that only wants the scoring pass (the step-4 tests) still
        works; a cast attempted without it is refused, not crashed.
        """
        self._accum += float(dt)
        period = max(self.period, float(dt))     # floor at one logic tick
        if self._accum + _CADENCE_EPS < period:
            return None
        # Subtract rather than zero so the cadence does not drift slow;
        # clamp if a long stall banked more than one period, because §6
        # allows exactly one action per decision tick.
        self._accum -= period
        if self._accum >= period:
            self._accum = 0.0

        rec = self._decide(sim_t=sim_t, citizens=citizens, belief=belief,
                           relic_mgr=relic_mgr, power_system=power_system,
                           world=world, food=food)
        self.log.append(rec)
        self.decisions += 1
        if self.debug:
            print(rec.format())
        return rec

    # -- senses (§7) ---------------------------------------------------------

    def sense(self, *, sim_t: float, citizens: CitizenManager,
              belief: BeliefField, relic_mgr: RelicManager,
              power_system: PowerSystem) -> Senses:
        """Derive this decision tick's board state. Cheap, read-only.

        Also refreshes the cached belief-grid geometry, so any caller that
        senses before scoring (the tests do) gets correct block maths
        without reaching into private state first.
        """
        self._grid_w = belief.grid_w
        self._grid_h = belief.grid_h
        self._tpc_x = max(1, belief.tiles_per_cell_x)
        self._tpc_y = max(1, belief.tiles_per_cell_y)

        b_own = belief.grid(self.faction)
        b_enemy = belief.grid(self.enemy)
        seam = b_own * b_enemy

        placed = tuple(relic_mgr.placed_for_faction(self.faction))
        own_slots = relic_mgr.for_faction(self.faction)
        free = tuple(r.slot for r in own_slots
                     if r.state == RelicState.AVAILABLE)
        shatter_time = max(_EPS, float(relic_mgr.cfg.shatter_time))
        threats = [min(1.0, r.threat_timer / shatter_time) for r in placed]

        pop_own = citizens.population(self.faction)
        return Senses(
            sim_t=float(sim_t),
            pop_own=pop_own,
            pop_enemy=citizens.population(self.enemy),
            pool_own=float(power_system.pool[self.faction]),
            tier_own=tier_for(pop_own)[1],
            b_own=b_own, b_enemy=b_enemy, seam=seam,
            peak_own=float(b_own.max()) if b_own.size else 0.0,
            peak_enemy=float(b_enemy.max()) if b_enemy.size else 0.0,
            own_peak_cell=argmax_cell(b_own),
            enemy_peak_cell=argmax_cell(b_enemy),
            seam_peak_cell=argmax_cell(seam),
            seam_peak_value=float(seam.max()) if seam.size else 0.0,
            own_centroid=centroid(citizens, self.faction),
            enemy_centroid=centroid(citizens, self.enemy),
            own_placed=placed,
            own_free_slots=free,
            n_slots=len(own_slots),
            max_threat_frac=max(threats) if threats else 0.0,
        )

    # -- scoring (§8) --------------------------------------------------------

    def _cast_gate(self, kind: PowerKind, s: Senses,
                   power_system: PowerSystem) -> bool:
        """The cell-independent half of `can_cast`, plus the god mask.

        Cheap enough to run before choosing a tile. The authoritative
        per-tile half runs during refinement, via `can_cast` itself, so
        nothing here can let an illegal cast through - it only avoids
        scanning 16 tiles for a power we already cannot afford.
        """
        if kind in self.forbidden:
            return False
        spec = POWERS.get(kind)
        if spec is None:
            return False
        if s.tier_own < spec.tier:
            return False
        if power_system.cooldowns.get((self.faction, int(kind)), 0.0) > 0.0:
            return False
        # `spend_floor` is a reserve, not a discount (§8): the cost is
        # still paid in full, it just may not dip into the reserve.
        if s.pool_own < self.p.spend_floor + spec.belief_cost - 1e-6:
            return False
        return True

    def utilities(self, s: Senses, power_system: PowerSystem,
                  citizens: CitizenManager,
                  world: World) -> dict[Intent, float]:
        """Utility in [0, 1] per intent. 0 means infeasible or worthless."""
        u: dict[Intent, float] = {i: 0.0 for i in SCORED_INTENTS}
        enemy_ref = max(s.peak_enemy, _EPS)

        # CURSE - hit the seam where the enemy is thickest.
        if self._cast_gate(PowerKind.CURSE, s, power_system):
            cx, cy = s.seam_peak_cell
            u[Intent.CAST_CURSE] = clamp01(
                float(s.b_enemy[cy, cx]) / enemy_ref)

        # HUNGER_PANG - hit the enemy's densest cell. Normalising the
        # enemy field by its own peak makes this exactly 1.0 while we aim
        # at the argmax; the formula stays general if the target rule ever
        # moves off it.
        if self._cast_gate(PowerKind.HUNGER_PANG, s, power_system):
            cx, cy = s.enemy_peak_cell
            u[Intent.CAST_HUNGER_PANG] = clamp01(
                float(s.b_enemy[cy, cx]) / enemy_ref)

        # BLESS - own-density shortfall against the enemy. Masked off for
        # the Maw long before we get here.
        if self._cast_gate(PowerKind.BLESS, s, power_system):
            u[Intent.CAST_BLESS] = clamp01(
                (s.peak_enemy - s.peak_own) / enemy_ref)

        # LOWER - open a route through the ridge holding the seam shut.
        # Utility is settled alongside the target, since finding one means
        # scanning the block anyway.
        if self._cast_gate(PowerKind.LOWER, s, power_system):
            ridge = self.ridge_target(s, power_system, citizens, world)
            if ridge is not None:
                u[Intent.CAST_LOWER] = ridge[1]

        # RELIC_PLACE - free slots x how much new ground the push point
        # claims.
        #
        # Section 8 scores this on `seam_overlap`, but steps 4 and 5
        # measured a default round and found the two fields never touch at
        # all: zero belief cells carry both. That formula therefore leaves
        # the rival's relics in the tray for the whole game, and puts step
        # 8's acceptance bar out of reach. Keyed off the push point
        # instead, so relics *make* the contact rather than wait for it -
        # a placed relic pulls our own citizens toward it through the
        # same-faction attractor list, which drags the belief field
        # forward with them. Deviation agreed 2026-09-02; see the worklog.
        if s.own_free_slots and s.n_slots > 0:
            push = self.push_point_tile(s, world)
            if push is not None:
                u[Intent.RELIC_PLACE] = clamp01(
                    (len(s.own_free_slots) / s.n_slots)
                    * self.spread(s, push))

        # RELIC_MOVE - how far the rear-most relic has fallen behind the
        # push point the seam has drifted to, past a deadband so a flag
        # that is roughly where it should be gets left alone.
        rear = self.rear_most(s, world)
        if rear is not None:
            push = self.push_point_tile(s, world)
            if push is not None:
                drift = dist((rear.tx, rear.ty), push)
                span = max(_EPS, _DRIFT_REF_TILES - _MOVE_DEADBAND_TILES)
                if drift > _MOVE_DEADBAND_TILES:
                    u[Intent.RELIC_MOVE] = clamp01(
                        (drift - _MOVE_DEADBAND_TILES) / span)

        # RELIC_RETRIEVE - dead flat until `retrieve_panic`, then ramps.
        if s.own_placed:
            panic = clamp01(self.p.retrieve_panic)
            tf = s.max_threat_frac
            if panic >= 1.0 - _EPS:
                u[Intent.RELIC_RETRIEVE] = 1.0 if tf >= 1.0 else 0.0
            elif tf > panic:
                u[Intent.RELIC_RETRIEVE] = clamp01((tf - panic) / (1.0 - panic))

        return u

    def score(self, u: dict[Intent, float]) -> dict[Intent, float]:
        """`score = weight x utility + jitter`, jitter on feasible only.

        §8 writes `weight x utility x feasible + jitter`, which lets an
        infeasible intent score up to `jitter` - and the Zealot's jitter
        (0.05) exactly ties its `idle_floor` (0.05). Keeping jitter off
        the zero-utility branch makes "an infeasible intent scores 0"
        literally true, and the same-rules pillar structural rather than
        lucky.

        The jitter vector is drawn at full width every tick regardless of
        how many intents are live, so the RNG stream stays aligned across
        runs - that is what makes the determinism test meaningful.
        """
        noise = self.rng.random(len(SCORED_INTENTS)) * self.p.jitter
        out: dict[Intent, float] = {}
        for k, intent in enumerate(SCORED_INTENTS):
            util = u.get(intent, 0.0)
            w = self.p.weight(intent)
            if util <= 0.0 or w <= 0.0:
                out[intent] = 0.0
            else:
                out[intent] = w * util + float(noise[k])
        return out

    # -- targeting (§8) ------------------------------------------------------

    def push_point_cell(self, s: Senses) -> Optional[tuple[int, int]]:
        """The push point at this personality's full forward bias."""
        return self.push_cell_at(s, clamp01(self.p.relic_forward_bias))

    def push_point_cells(self, s: Senses) -> list[tuple[int, int]]:
        """The push point plus fallbacks walking back toward home.

        §8 refines inside one cell and re-scores if nothing in it is
        legal, which stalls hard when the push point lands on water: the
        anchor barely moves between decisions, so RELIC_PLACE stays the
        top-scoring intent and fails refinement every single tick.
        Observed live at 0.91 and unplaceable for a solid minute of play.

        Sampling the same lerp at decreasing bias reads as "plant as far
        forward as the ground allows" and stays bounded at five tries -
        a fallback list, not a scan.
        """
        t0 = clamp01(self.p.relic_forward_bias)
        out: list[tuple[int, int]] = []
        for frac in _PUSH_FALLBACK_FRACTIONS:
            cell = self.push_cell_at(s, t0 * frac)
            if cell is not None and cell not in out:
                out.append(cell)
        return out

    def push_cell_at(self, s: Senses,
                     t: float) -> Optional[tuple[int, int]]:
        """`lerp(seam_peak_cell, enemy_centroid, t)`, snapped.

        Degenerate board: before the two fields touch, `seam` is zero
        everywhere and its argmax is cell (0, 0) by tie-break - a map
        corner, not an anchor. Fall back to our own centroid then, which
        reads the lerp as "push from where we are toward them" and keeps
        RELIC_MOVE's utility honest on an uncontested map. Once any seam
        exists this branch never runs.
        """
        if s.seam_peak_value > _EPS or s.own_centroid is None:
            cx, cy = s.seam_peak_cell
        else:
            ox, oy = s.own_centroid
            cx = int(ox / max(1, self._tpc_x))
            cy = int(oy / max(1, self._tpc_y))
        if s.enemy_centroid is None:
            return (max(0, min(max(0, self._grid_w - 1), cx)),
                    max(0, min(max(0, self._grid_h - 1), cy)))
        ex, ey = s.enemy_centroid
        # The centroid arrives in world tiles; the lerp happens in cells.
        ecx = ex / max(1, self._tpc_x)
        ecy = ey / max(1, self._tpc_y)
        t = clamp01(t)
        gx = int(round(cx + (ecx - cx) * t))
        gy = int(round(cy + (ecy - cy) * t))
        gx = max(0, min(max(0, self._grid_w - 1), gx))
        gy = max(0, min(max(0, self._grid_h - 1), gy))
        return (gx, gy)

    def push_point_tile(self, s: Senses,
                        world: Optional[World] = None
                        ) -> Optional[tuple[int, int]]:
        """The push point as a world tile (block centre, unrefined).

        Given `world`, walks the same fallback list `target_for` uses and
        answers with the first block that holds any walkable tile - so
        the drift maths measures against a push point we can actually
        reach. Without that, RELIC_MOVE compares its relics to an
        unreachable anchor, never closes the gap, and re-moves the same
        flag every other decision (observed: relic acts back up to 35 a
        round after the fallback landed). Cheap: a walkability scan of at
        most five blocks, no dry runs and no RNG.
        """
        if world is not None:
            for cx, cy in self.push_point_cells(s):
                for tx, ty in self.block_tiles(cx, cy):
                    if world.in_bounds(tx, ty) and is_walkable_tile(
                            int(world.tiles[ty, tx])):
                        return (cx * self._tpc_x + self._tpc_x // 2,
                                cy * self._tpc_y + self._tpc_y // 2)
            return None
        cell = self.push_point_cell(s)
        if cell is None:
            return None
        cx, cy = cell
        return (cx * self._tpc_x + self._tpc_x // 2,
                cy * self._tpc_y + self._tpc_y // 2)

    def spread(self, s: Senses, push: tuple[int, int]) -> float:
        """How clear the push point is of the relics we already planted.

        1.0 with nothing placed yet, then a hard zero until the push
        point is `_RELIC_SPREAD_TILES` clear of every flag already
        planted, ramping to 1.0 at twice that.

        It started life as a plain ratio, which only *lowered* the score
        instead of gating it: the Zealot still cleared its 0.05 idle
        floor on the way down and stacked all three relics within three
        tiles of each other, concentrating every citizen it had into one
        attractor disc until the local food gave out. A gate, like
        RELIC_MOVE's deadband, is what the term was always meant to be.
        """
        if not s.own_placed:
            return 1.0
        nearest = min(dist((r.tx, r.ty), push) for r in s.own_placed)
        if nearest < _RELIC_SPREAD_TILES:
            return 0.0
        return clamp01((nearest - _RELIC_SPREAD_TILES) / _RELIC_SPREAD_TILES)

    def place_slot(self, s: Senses) -> Optional[int]:
        """The slot RELIC_PLACE would consume: the lowest free one.

        Deterministic on `s`, so `target_for` and `_execute` can each
        derive it without threading a choice between them.
        """
        return s.own_free_slots[0] if s.own_free_slots else None

    def rear_most(self, s: Senses,
                  world: Optional[World] = None) -> Optional[Relic]:
        """The placed relic furthest from the push point - the one most
        out of position, hence the one worth moving forward."""
        if not s.own_placed:
            return None
        push = self.push_point_tile(s, world)
        if push is None:
            return None
        return max(s.own_placed, key=lambda r: dist((r.tx, r.ty), push))

    def most_threatened(self, s: Senses) -> Optional[Relic]:
        if not s.own_placed:
            return None
        return max(s.own_placed, key=lambda r: r.threat_timer)

    def ridge_target(self, s: Senses, power_system: PowerSystem,
                     citizens: CitizenManager,
                     world: World) -> Optional[tuple[tuple[int, int], float]]:
        """Best `(tile, utility)` for CAST_LOWER, or None.

        Walks the hottest `_LOWER_SCAN_CELLS` seam cells and scores each
        block by how much of it is walk-blocking-but-lowerable - i.e. how
        much of a wall the seam is pressed against. `can_cast` is the
        authority on lowerable, so this can never nominate a tile the cast
        itself would refuse.
        """
        if s.seam.size == 0 or s.seam_peak_value <= _EPS:
            return None
        flat = s.seam.ravel()
        k = min(_LOWER_SCAN_CELLS, flat.size)
        # argpartition for the top k, then sort just those, hottest first.
        idx = np.argpartition(flat, -k)[-k:]
        idx = idx[np.argsort(flat[idx])[::-1]]

        best: Optional[tuple[tuple[int, int], float]] = None
        span = float(max(1, self._tpc_x * self._tpc_y))
        for lin in idx:
            seam_v = float(flat[int(lin)])
            if seam_v <= _EPS:
                break
            cy, cx = divmod(int(lin), max(1, self._grid_w))
            blocked: list[tuple[int, int]] = []
            for tx, ty in self.block_tiles(cx, cy):
                if not world.in_bounds(tx, ty):
                    continue
                if is_walkable_tile(int(world.tiles[ty, tx])):
                    continue
                ok, _ = power_system.can_cast(
                    PowerKind.LOWER, self.faction, tx, ty, citizens, world)
                if ok:
                    blocked.append((tx, ty))
            if not blocked:
                continue
            util = clamp01((len(blocked) / span)
                           * (seam_v / max(s.seam_peak_value, _EPS)))
            if best is None or util > best[1]:
                best = (blocked[0], util)
        return best

    def block_tiles(self, cx: int, cy: int) -> list[tuple[int, int]]:
        """The world tiles inside belief cell `(cx, cy)`."""
        x0 = cx * self._tpc_x
        y0 = cy * self._tpc_y
        return [(x0 + i, y0 + j)
                for j in range(self._tpc_y) for i in range(self._tpc_x)]

    def refine(self, cell: tuple[int, int], world: World,
               validator: Callable[[int, int], bool], *,
               require_walkable: bool) -> Optional[tuple[int, int]]:
        """Grid cell -> a world tile inside it that passes `validator`.

        Seeded shuffle over the cell's block; first tile that passes wins
        (§8). `require_walkable` is True for relic verbs and False for
        casts: §8 asks for "walkability + the verb's own validity check",
        but for casts the verb's own check *is* the authority (CAST_LOWER
        deliberately targets unwalkable ridge), and for relics
        `RelicManager` already rejects unwalkable tiles. Splitting the two
        keeps both readings honest.
        """
        cx, cy = cell
        tiles = self.block_tiles(cx, cy)
        if not tiles:
            return None
        for k in self.rng.permutation(len(tiles)):
            tx, ty = tiles[int(k)]
            if not world.in_bounds(tx, ty):
                continue
            if require_walkable and not is_walkable_tile(
                    int(world.tiles[ty, tx])):
                continue
            if validator(tx, ty):
                return (tx, ty)
        return None

    def target_for(self, intent: Intent, s: Senses, world: World,
                   citizens: CitizenManager, power_system: PowerSystem,
                   relic_mgr: RelicManager) -> Optional[tuple[int, int]]:
        """Resolve an intent to a concrete world tile, or None when the
        refinement found nothing legal (the caller re-scores without it)."""
        if intent in INTENT_POWER:
            kind = INTENT_POWER[intent]
            if intent == Intent.CAST_LOWER:
                ridge = self.ridge_target(s, power_system, citizens, world)
                return ridge[0] if ridge else None
            cell = {
                Intent.CAST_CURSE:       s.seam_peak_cell,
                Intent.CAST_HUNGER_PANG: s.enemy_peak_cell,
                Intent.CAST_BLESS:       s.own_peak_cell,
            }[intent]
            return self.refine(
                cell, world,
                lambda tx, ty: power_system.can_cast(
                    kind, self.faction, tx, ty, citizens, world)[0],
                require_walkable=False,
            )

        if intent == Intent.RELIC_RETRIEVE:
            r = self.most_threatened(s)
            return (r.tx, r.ty) if r is not None else None

        # PLACE and MOVE both aim at the push point, and both refine
        # against the real relic API's dry run (added in step 6), so a
        # refined tile is one the verb will actually accept. If the push
        # point itself is unplaceable we walk back toward home rather
        # than give up on the tick - see `push_point_cells`.
        if intent == Intent.RELIC_PLACE:
            slot = self.place_slot(s)
            if slot is None:
                return None
            ok = lambda tx, ty: relic_mgr.can_place(
                self.faction, slot, tx, ty, world)[0]
        elif intent == Intent.RELIC_MOVE:
            rear = self.rear_most(s, world)
            if rear is None:
                return None
            ok = lambda tx, ty: relic_mgr.can_move(
                self.faction, rear.slot, tx, ty, world)[0]
        else:
            return None

        for cell in self.push_point_cells(s):
            got = self.refine(cell, world, ok, require_walkable=True)
            if got is not None:
                return got
        return None

    # -- the decision --------------------------------------------------------

    def _decide(self, *, sim_t: float, citizens: CitizenManager,
                belief: BeliefField, relic_mgr: RelicManager,
                power_system: PowerSystem, world: World,
                food=None) -> DecisionRecord:
        s = self.sense(sim_t=sim_t, citizens=citizens, belief=belief,
                       relic_mgr=relic_mgr, power_system=power_system)
        u = self.utilities(s, power_system, citizens, world)
        scores = self.score(u)
        top3 = tuple(sorted(scores.items(), key=lambda kv: -kv[1])[:3])

        # §8: argmax, refine, and on a refinement miss drop that intent and
        # re-score. Bounded at two re-scores, then IDLE - no scan loops.
        remaining = dict(scores)
        note = ""
        for _attempt in range(3):
            if not remaining:
                note = note or "nothing feasible"
                break
            intent = max(remaining, key=lambda i: remaining[i])
            best = remaining[intent]
            if best <= self.p.idle_floor:
                note = "below idle_floor"
                break
            target = self.target_for(intent, s, world, citizens,
                                     power_system, relic_mgr)
            if target is None:
                del remaining[intent]
                note = "re-scored past unrefinable target"
                continue
            executed, why = self._execute(
                intent, target, s, sim_t=sim_t, citizens=citizens,
                world=world, food=food, belief=belief,
                relic_mgr=relic_mgr, power_system=power_system)
            return DecisionRecord(
                sim_t=sim_t, intent=intent, target=target, score=best,
                top3=top3, executed=executed, note=why,
            )
        else:
            note = "re-score bound reached"

        return DecisionRecord(sim_t=sim_t, intent=Intent.IDLE, target=None,
                              score=0.0, top3=top3, executed=False,
                              note=note or "nothing feasible")

    def _execute(self, intent: Intent, target: tuple[int, int], s: Senses, *,
                 sim_t: float, citizens: CitizenManager, world: World,
                 belief: BeliefField, relic_mgr: RelicManager,
                 power_system: PowerSystem,
                 food=None) -> tuple[bool, str]:
        """Perform the chosen intent. Returns `(executed, note)`.

        Step 5: the four cast intents go out through `cast_or_queue` -
        the player's own entry point. It re-validates with `can_cast`,
        debits the pool, burns the cooldown and emits the scripture line
        for our god, so the same-rules pillar holds by construction
        rather than by our promising to behave. Step 6 fills in the three
        relic verbs below the same way.
        """
        if intent in INTENT_POWER:
            kind = INTENT_POWER[intent]
            if food is None:
                # No food field to hand the dispatch - refuse rather than
                # crash. Only reachable from a caller that omitted it.
                return False, "no food field; cast skipped"
            tx, ty = target
            receipt = power_system.cast_or_queue(
                kind, self.faction, int(tx), int(ty),
                citizens, world, food, belief, sim_t,
            )
            if receipt.ok:
                self.casts += 1
                return True, ("queued" if receipt.reason == "queued" else "")
            # Scored feasible, then refused at the verb. Should not happen
            # - surface it in the log instead of swallowing it.
            self.refused += 1
            return False, f"refused: {receipt.reason}"

        # Relic verbs (step 6). The slot is re-derived from the same
        # `Senses` the target was chosen against, so it cannot disagree
        # with what `target_for` refined for.
        tx, ty = int(target[0]), int(target[1])
        if intent == Intent.RELIC_PLACE:
            slot = self.place_slot(s)
            if slot is None:
                return False, "no free slot"
            ok, why = relic_mgr.place(self.faction, slot, tx, ty,
                                      world, sim_t)
        elif intent == Intent.RELIC_MOVE:
            rear = self.rear_most(s, world)
            if rear is None:
                return False, "nothing placed to move"
            # A move resets `placed_at`, so the relic pays a full
            # belief fade-in for the privilege (`Densitas_relics.md`
            # §3.1). Shuffling it a couple of tiles is strictly a loss.
            if dist((rear.tx, rear.ty), (tx, ty)) <= _MOVE_DEADBAND_TILES:
                return False, "move too short to pay for its fade-in"
            ok, why = relic_mgr.move(self.faction, rear.slot, tx, ty,
                                     world, sim_t)
        elif intent == Intent.RELIC_RETRIEVE:
            worst = self.most_threatened(s)
            if worst is None:
                return False, "nothing placed to retrieve"
            ok, why = relic_mgr.retrieve(self.faction, worst.slot, sim_t)
        else:
            return False, f"no verb for {intent.name}"

        if not ok:
            self.refused += 1
            return False, f"refused: {why}"
        self.relic_acts += 1
        # Citizen attractors are rebuilt from PLACED relics, so any relic
        # mutation invalidates them. main.py re-syncs after a player
        # placement and after a shatter; the AI owes the same for its own.
        citizens.sync_attractors_from_relics(
            relic_mgr.relics, self.powers_cfg.relic.attract_radius)
        return True, why


# -- helpers -----------------------------------------------------------------

def clamp01(v: float) -> float:
    """Clamp to [0, 1]. NaN (an empty field dividing out) reads as 0."""
    if v != v:
        return 0.0
    return 0.0 if v < 0.0 else (1.0 if v > 1.0 else float(v))


def argmax_cell(grid: np.ndarray) -> tuple[int, int]:
    """`(cx, cy)` of the grid's maximum. Ties take the first in C order."""
    if grid.size == 0:
        return (0, 0)
    cy, cx = np.unravel_index(int(np.argmax(grid)), grid.shape)
    return (int(cx), int(cy))


def centroid(citizens: CitizenManager,
             faction: int) -> Optional[tuple[float, float]]:
    """Mean world-tile position of a faction's citizens, or None if the
    faction is extinct. DYING citizens count - they are still bodies on
    the map, and they still scatter belief."""
    xs = 0.0
    ys = 0.0
    n = 0
    for c in citizens.citizens:
        if c.faction == faction:
            xs += c.x
            ys += c.y
            n += 1
    if n == 0:
        return None
    return (xs / n, ys / n)


def dist(a: tuple[float, float], b: tuple[float, float]) -> float:
    return float(np.hypot(float(a[0]) - float(b[0]),
                          float(a[1]) - float(b[1])))


def make_rival_ai(rival_cfg, powers_cfg, *, faction: int = 1,
                  seed: int = 0, debug: bool = False) -> RivalAI:
    """Build the AI named by `[rival] personality`.

    Raises on an unknown name - `config.load` validates it too, but a
    hand-built RivalConfig in a test deserves the same error.
    """
    key = str(getattr(rival_cfg, "personality", "zealot")).lower()
    if key not in PERSONALITIES:
        raise ValueError(
            f"unknown rival personality {key!r}; "
            f"expected one of {sorted(PERSONALITIES)}")
    return RivalAI(faction, PERSONALITIES[key], rival_cfg, powers_cfg,
                   seed=seed, debug=debug)
