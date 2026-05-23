"""Religious Relics - data model + manager skeleton.

PR3 step 1 of the slicing in `Densitas_relics.md` section 13.

This file lands the state machine and the mutation operations (place /
move / retrieve / get / for_faction / placed_for_faction). It does NOT
yet wire belief contribution (`_scatter_relics` lives on `BeliefField`,
arrives in PR3 step 2), citizen attraction (PR3 step 3), or the shatter
rule (PR3 step 4). `tick()` and `shatter_at()` are present as no-op
stubs so callers can be written against the final signature now.

See `Densitas_relics.md` sections 1-3 for the design rationale and
section 2 for the contract this module implements.

Naming policy: hardcoded per-faction lists keyed by `slot`. The spec
gives "The First Witness" / "Second Bite" as examples; we extend to
three of each since `initial_count = 3` at T0. Names are stable for
the life of a `Relic` object - they're set at construction.
"""
from __future__ import annotations

import enum
import math
from dataclasses import dataclass, field
from typing import Optional, TYPE_CHECKING

from .config import RelicConfig
from .world import World, is_walkable_tile

if TYPE_CHECKING:
    from .belief import BeliefField
    from .citizen import CitizenManager


class RelicState(enum.IntEnum):
    """Three-state lifecycle. See `Densitas_relics.md` section 2.

    AVAILABLE -> PLACED via `place(...)`.
    PLACED    -> AVAILABLE via `retrieve(...)`; PLACED -> PLACED via `move(...)`.
    PLACED    -> SHATTERED via `tick(...)` when the shatter rule triggers.
    SHATTERED is terminal - no mutation transitions out of it.
    """
    AVAILABLE = 0
    PLACED    = 1
    SHATTERED = 2


# Per-faction relic name table. Indexed by `slot` (0..initial_count-1).
# The spec gives "The First Witness" / "Second Bite" as the shape; we
# extend to three of each for T0's initial_count. Faction 0 is the Open
# Eye, faction 1 is the Maw, matching `relic_glyphs.py :: GLYPHS_BY_FACTION`.
RELIC_NAMES: dict[int, tuple[str, ...]] = {
    0: ("The First Witness", "The Second Witness", "The Third Witness"),
    1: ("The First Bite",    "The Second Bite",    "The Third Bite"),
}


def _name_for(faction: int, slot: int) -> str:
    """Lookup with a graceful fallback so adding a faction or bumping
    `initial_count` past 3 doesn't crash - it just produces a generic
    name we can refine later when those features land.
    """
    table = RELIC_NAMES.get(faction)
    if table is not None and slot < len(table):
        return table[slot]
    return f"Relic f{faction} s{slot}"


@dataclass
class ShatterSummary:
    """Snapshot built at the moment of SHATTERED transition. See
    `Densitas_relics.md` section 6 (summary panel) and section 2 for
    the field contract.

    Frozen by convention (dataclass-frozen would require us to drop the
    field-by-field constructor convenience the manager will use later).
    Treat as immutable once returned from `RelicManager.tick`.
    """
    relic_id: int
    faction: int
    name: str
    tx: int
    ty: int
    sim_t: float                      # when the shatter fired
    local_belief_player: float
    local_belief_rival: float
    player_citizens_within_8: int
    rival_citizens_within_8: int
    time_placed_total: float          # cumulative sim_s spent in PLACED state
    times_moved: int


@dataclass
class Relic:
    """One relic slot. `id` is stable for the life of the game; the
    slot can cycle AVAILABLE / PLACED / AVAILABLE many times before a
    final SHATTERED. See `Densitas_relics.md` section 2.

    `tx` / `ty` are meaningful only when `state == PLACED`. When
    AVAILABLE or SHATTERED they retain their last value but should not
    be queried. `placed_at` and `threat_timer` follow the same rule:
    only meaningful while PLACED. The shatter summary keeps a frozen
    copy of `tx` / `ty` so we don't lose the location post-shatter.
    """
    id: int
    faction: int
    slot: int
    name: str
    state: RelicState = RelicState.AVAILABLE
    tx: int = 0
    ty: int = 0
    placed_at: float = 0.0
    times_moved: int = 0
    threat_timer: float = 0.0
    shatter_at: float = 0.0
    shatter_summary: Optional[ShatterSummary] = None
    # Cumulative time spent in PLACED state, summed across all placements.
    # Useful for `ShatterSummary.time_placed_total`. Incremented in `tick`
    # (PR3 step 4) and reset on `retrieve` / new `place`.
    _placed_time_accum: float = field(default=0.0, repr=False)


class RelicManager:
    """Owns the per-game flat list of relics and the mutation API.

    Construction allocates `n_factions * cfg.initial_count` Relic
    objects, all AVAILABLE, with stable `id = faction * initial_count
    + slot` per `Densitas_relics.md` section 2. The flat layout makes
    save/load (PR3 step 13) trivial - just serialise the list.

    `tick()` is a no-op stub until PR3 step 4 lands the shatter rule.
    `shatter_at()` is a no-op stub until PR3 step 4 (P5 disaster hook).
    """

    def __init__(self, cfg: RelicConfig, n_factions: int = 2) -> None:
        if n_factions < 1:
            raise ValueError(f"n_factions must be >= 1, got {n_factions}")
        if cfg.initial_count < 1:
            raise ValueError(
                f"cfg.initial_count must be >= 1, got {cfg.initial_count}"
            )
        self.cfg = cfg
        self.n_factions = n_factions
        self.relics: list[Relic] = [
            Relic(
                id=faction * cfg.initial_count + slot,
                faction=faction,
                slot=slot,
                name=_name_for(faction, slot),
            )
            for faction in range(n_factions)
            for slot in range(cfg.initial_count)
        ]

    # -- Lookup ------------------------------------------------------------

    def get(self, faction: int, slot: int) -> Relic:
        """Return the relic at `(faction, slot)`. Raises IndexError if
        out of range - the manager owns the slot space, so callers
        passing bad indices is a bug, not a runtime condition.
        """
        if not (0 <= faction < self.n_factions):
            raise IndexError(
                f"faction {faction} out of range [0, {self.n_factions})"
            )
        if not (0 <= slot < self.cfg.initial_count):
            raise IndexError(
                f"slot {slot} out of range [0, {self.cfg.initial_count})"
            )
        return self.relics[faction * self.cfg.initial_count + slot]

    def for_faction(self, faction: int) -> list[Relic]:
        """All relics belonging to `faction`, in slot order."""
        return [r for r in self.relics if r.faction == faction]

    def placed_for_faction(self, faction: int) -> list[Relic]:
        """All relics belonging to `faction` whose current state is
        PLACED. This is the iterator that `PixelRenderer.blit_relics`
        consumes - it walks once per frame and so should stay cheap.
        For small `initial_count` (3 at T0, 4-5 at T3/T4) the linear
        scan is fine.
        """
        return [
            r for r in self.relics
            if r.faction == faction and r.state == RelicState.PLACED
        ]

    # -- Mutations ---------------------------------------------------------

    def place(self, faction: int, slot: int, tx: int, ty: int,
              world: World, sim_t: float) -> tuple[bool, str]:
        """AVAILABLE -> PLACED. Returns (ok, reason).

        Validation order (so reasons are predictable in tests):
          1. Slot identity (faction/slot in range).
          2. State must be AVAILABLE.
          3. Tile in bounds.
          4. Tile walkable (water / mountain / lava / blighted reject).
          5. No same-faction relic already on this exact tile.

        On success: state -> PLACED, position stamped, `placed_at = sim_t`.
        `times_moved` is NOT incremented - placement isn't a move.
        `threat_timer` is reset to 0 (was already 0 from AVAILABLE).
        """
        try:
            r = self.get(faction, slot)
        except IndexError as e:
            return (False, str(e))

        if r.state == RelicState.SHATTERED:
            return (False, "relic shattered - slot exhausted for the round")
        if r.state == RelicState.PLACED:
            return (False, "slot already placed - use move")

        ok, reason = self._validate_tile(faction, tx, ty, world,
                                          ignore_relic_id=r.id)
        if not ok:
            return (False, reason)

        r.state = RelicState.PLACED
        r.tx = tx
        r.ty = ty
        r.placed_at = sim_t
        r.threat_timer = 0.0
        r._placed_time_accum = 0.0
        return (True, "placed")

    def move(self, faction: int, slot: int, tx: int, ty: int,
             world: World, sim_t: float) -> tuple[bool, str]:
        """PLACED -> PLACED (new tile). Returns (ok, reason).

        Per `Densitas_relics.md` section 3.1: moving costs 30 sim_sec
        of full-amplitude time because `placed_at` resets and the
        belief fade-in restarts from zero. `times_moved` increments;
        `threat_timer` resets to 0 (a moved relic isn't threatened in
        its new location yet).

        Validation order matches `place`, except state must be PLACED
        (not AVAILABLE) and we allow the relic to stay on its current
        tile (no-op move) - validators only reject *other* relics'
        tiles.
        """
        try:
            r = self.get(faction, slot)
        except IndexError as e:
            return (False, str(e))

        if r.state == RelicState.SHATTERED:
            return (False, "relic shattered - slot exhausted for the round")
        if r.state == RelicState.AVAILABLE:
            return (False, "slot not placed - use place")

        ok, reason = self._validate_tile(faction, tx, ty, world,
                                          ignore_relic_id=r.id)
        if not ok:
            return (False, reason)

        r.tx = tx
        r.ty = ty
        r.placed_at = sim_t
        r.times_moved += 1
        r.threat_timer = 0.0
        # Moving counts as a fresh placement for fade-in purposes; we
        # do NOT reset _placed_time_accum because cumulative time in
        # PLACED state continues across moves (see ShatterSummary spec).
        return (True, "moved")

    def retrieve(self, faction: int, slot: int,
                 sim_t: float) -> tuple[bool, str]:
        """PLACED -> AVAILABLE. Returns (ok, reason).

        The relic returns to the tray with the same `name` and `slot`.
        `placed_at` and `threat_timer` reset to 0; `times_moved`
        accumulates across retrieve cycles (so a slot that was moved
        twice, retrieved, re-placed, and moved once more reports
        `times_moved = 3` in any future shatter summary).

        `_placed_time_accum` also persists across retrieve / re-place
        so total time-in-PLACED is honest in the final summary.
        """
        try:
            r = self.get(faction, slot)
        except IndexError as e:
            return (False, str(e))

        if r.state == RelicState.SHATTERED:
            return (False, "relic shattered - slot exhausted for the round")
        if r.state == RelicState.AVAILABLE:
            return (False, "slot not placed - nothing to retrieve")

        r.state = RelicState.AVAILABLE
        r.placed_at = 0.0
        r.threat_timer = 0.0
        # tx / ty intentionally left at their last value so a UI
        # debugger can show "last seen at" if needed; queries should
        # gate on state == PLACED before reading them.
        return (True, "retrieved")

    # -- Per-tick (stubs until PR3 step 4) --------------------------------

    def tick(self, dt: float, belief: Optional["BeliefField"],
             citizens: Optional["CitizenManager"],
             sim_t: float) -> list[ShatterSummary]:
        """Advance time for each PLACED relic. Returns any
        ShatterSummary instances produced this tick.

        Per `Densitas_relics.md` section 9:
          - If rival belief at this relic's tile exceeds
            `shatter_ratio * max(player_belief, 1e-3)`, the
            relic's `threat_timer` accumulates `dt`.
          - Otherwise `threat_timer` decays at 2x dt (a 1-sec
            rival incursion erases ~2 sec of threat - sustained
            pressure is required to shatter).
          - When `threat_timer` reaches `shatter_time` (8 sec
            default), the relic transitions PLACED -> SHATTERED
            and `_build_shatter_summary` snapshots the
            tile / belief / citizen-count state for the panel.

        Defensive: `belief=None` or `citizens=None` skip the
        shatter math but still advance `_placed_time_accum`. This
        preserves the step-1 stub-test contract
        (test_tick_accumulates_placed_time_for_placed_relics).
        """
        shattered: list[ShatterSummary] = []
        skip_shatter = (belief is None) or (citizens is None)
        for r in self.relics:
            if r.state != RelicState.PLACED:
                continue
            r._placed_time_accum += dt
            if skip_shatter:
                continue

            p_b = belief.query(r.tx, r.ty, faction=r.faction)
            rival_bs = [
                belief.query(r.tx, r.ty, f)
                for f in range(belief.n_factions)
                if f != r.faction
            ]
            r_b = max(rival_bs) if rival_bs else 0.0

            if r_b > self.cfg.shatter_ratio * max(p_b, 1e-3):
                r.threat_timer += dt
            else:
                r.threat_timer = max(0.0, r.threat_timer - 2.0 * dt)

            if r.threat_timer >= self.cfg.shatter_time:
                summary = self._build_shatter_summary(
                    r, p_b, r_b, citizens, sim_t,
                )
                r.state = RelicState.SHATTERED
                r.shatter_at = sim_t
                r.shatter_summary = summary
                # Position kept so the on-map crack/flash (PR3 step 7)
                # can render at the shatter site.
                shattered.append(summary)
        return shattered

    def _build_shatter_summary(self, r: Relic,
                                 p_b: float, r_b: float,
                                 citizens: "CitizenManager",
                                 sim_t: float) -> ShatterSummary:
        """Snapshot the eight fields the shatter panel reads from.

        Citizen counts use Euclidean distance within radius 8 from
        the relic's tile, consistent with the attractor disc shape
        (spec section 8). DYING citizens are still counted - they
        were near the relic at the moment of shatter, which is
        what the panel reports.

        `citizens` is duck-typed - we only need an iterable of
        objects with `.x`, `.y`, `.faction`. CitizenManager exposes
        `.citizens` as that list; future N-faction work can pass
        any compatible iterable.
        """
        radius = 8.0
        radius_sq = radius * radius
        p_count = 0
        r_count = 0
        cx, cy = float(r.tx), float(r.ty)
        for c in citizens.citizens:
            dx = c.x - cx
            dy = c.y - cy
            if dx * dx + dy * dy > radius_sq:
                continue
            if c.faction == r.faction:
                p_count += 1
            else:
                r_count += 1
        return ShatterSummary(
            relic_id=r.id,
            faction=r.faction,
            name=r.name,
            tx=r.tx,
            ty=r.ty,
            sim_t=sim_t,
            local_belief_player=float(p_b),
            local_belief_rival=float(r_b),
            player_citizens_within_8=p_count,
            rival_citizens_within_8=r_count,
            time_placed_total=r._placed_time_accum,
            times_moved=r.times_moved,
        )

    def shatter_at(self, tx: int, ty: int, radius: int,
                   sim_t: float) -> list[ShatterSummary]:
        """No-op stub. Hook reserved for P5 disasters (Volcano,
        Earthquake) - shattering any relic within `radius` of the
        epicentre. Lands with the disaster powers, not in PR3.
        """
        return []

    # -- Internal helpers --------------------------------------------------

    def _validate_tile(self, faction: int, tx: int, ty: int,
                        world: World,
                        ignore_relic_id: int = -1) -> tuple[bool, str]:
        """Shared validation for place / move. `ignore_relic_id` lets
        a move() to the same tile pass the same-faction-occupancy
        check (we shouldn't refuse to move-to-self).
        """
        if not world.in_bounds(tx, ty):
            return (False, f"tile ({tx}, {ty}) out of bounds")
        tile_id = int(world.tiles[ty, tx])
        if not is_walkable_tile(tile_id):
            from .world import Tile
            if tile_id == int(Tile.WATER):
                return (False, "can't place on water")
            return (False, f"tile not walkable (tile_id={tile_id})")
        # Same-faction occupancy. PLACED relics from the same faction
        # block; other-faction relics don't (per the spec, two factions
        # may place on adjacent tiles - the conflict is in the belief
        # field, not the tile slot).
        for other in self.relics:
            if other.id == ignore_relic_id:
                continue
            if other.faction != faction:
                continue
            if other.state != RelicState.PLACED:
                continue
            if other.tx == tx and other.ty == ty:
                return (False, "tile already has a same-faction relic")
        return (True, "valid")

# =============================================================================
# PR3 step 10 - R-key input modes.
#
# Pure state machine, no pygame, no rendering. The main event loop owns
# construction (`relic_input: Optional[RelicInputState]`) and calls
# `cycle_r_key` / `cycle_shift_r_key` on each R press; `None` return
# means "cancel mode".
#
# See `Densitas_relics.md` section 3 for the cycle behaviour these
# helpers implement.
# =============================================================================


class RelicMode(enum.IntEnum):
    """Three input modes from `Densitas_relics.md` section 3.

    PLACE     - cursor targets an AVAILABLE slot; LMB transitions
                AVAILABLE -> PLACED.
    MOVE      - cursor targets a PLACED slot; LMB transitions
                PLACED -> PLACED (new tile).
    RETRIEVE  - cursor seeks any PLACED relic of the player's
                faction; LMB transitions PLACED -> AVAILABLE.
    """
    PLACE    = 1
    MOVE     = 2
    RETRIEVE = 3


@dataclass
class RelicInputState:
    """One tick of the R-key cycle. The event loop holds an
    `Optional[RelicInputState]`; None means "no relic mode active".

    `slot` is the slot the cursor is currently targeting. For
    RETRIEVE it's -1 (any PLACED relic of the faction).
    """
    mode: RelicMode
    slot: int
    faction: int


def _available_slots(mgr: "RelicManager", faction: int) -> list[int]:
    return sorted(
        r.slot for r in mgr.for_faction(faction)
        if r.state == RelicState.AVAILABLE
    )


def _placed_slots(mgr: "RelicManager", faction: int) -> list[int]:
    return sorted(
        r.slot for r in mgr.for_faction(faction)
        if r.state == RelicState.PLACED
    )


def cycle_r_key(state: Optional[RelicInputState],
                mgr: "RelicManager",
                faction: int) -> Optional[RelicInputState]:
    """Compute the next state when R is pressed (no Shift).

    Cycle order per spec section 3.1:
      1. None / RETRIEVE -> first AVAILABLE slot in PLACE mode
      2. PLACE on slot N -> next AVAILABLE slot > N in PLACE mode
      3. PLACE exhausted -> first PLACED slot in MOVE mode
      4. MOVE on slot N -> next PLACED slot > N in MOVE mode
      5. MOVE exhausted -> None (cancel)

    A RETRIEVE state is treated like None - pressing R while in
    retrieve switches to placement.
    """
    avail = _available_slots(mgr, faction)
    placed = _placed_slots(mgr, faction)

    if state is None or state.mode == RelicMode.RETRIEVE:
        if avail:
            return RelicInputState(RelicMode.PLACE, avail[0], faction)
        if placed:
            return RelicInputState(RelicMode.MOVE, placed[0], faction)
        return None

    if state.mode == RelicMode.PLACE:
        nxt = [s for s in avail if s > state.slot]
        if nxt:
            return RelicInputState(RelicMode.PLACE, nxt[0], faction)
        if placed:
            return RelicInputState(RelicMode.MOVE, placed[0], faction)
        return None

    if state.mode == RelicMode.MOVE:
        nxt = [s for s in placed if s > state.slot]
        if nxt:
            return RelicInputState(RelicMode.MOVE, nxt[0], faction)
        return None

    return None


def cycle_shift_r_key(state: Optional[RelicInputState],
                      mgr: "RelicManager",
                      faction: int) -> Optional[RelicInputState]:
    """Compute the next state when Shift+R is pressed.

    Per spec section 3.2 RETRIEVE is a single state (no cycle). If
    Shift+R is pressed while RETRIEVE is already active, it cancels.
    If pressed in any other state, switches to RETRIEVE. No PLACED
    relics -> no-op (returns None).
    """
    if state is not None and state.mode == RelicMode.RETRIEVE:
        return None
    if not _placed_slots(mgr, faction):
        return None
    return RelicInputState(RelicMode.RETRIEVE, -1, faction)

