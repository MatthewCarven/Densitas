"""Citizen — autonomous inhabitants of the world.

Implements the state machine described in `Densitas_citizens.md` (P1).

Design notes:
- Citizens are NEVER directly selected by the player.
- All behaviour is local: wander, age, pair off, die.
- 5 Hz simulation tick (logic). Rendering runs at fps_target (60 Hz)
  but reads citizen positions directly — interpolation is a polish task.
- No pathfinding. Movement projects onto walkable tiles; if a step
  crosses an unwalkable tile, slide along the walkable axis or stay.

The belief field (P2) will read citizen positions; this module does
not depend on belief.
"""
from __future__ import annotations
import enum
import math
from dataclasses import dataclass
from typing import Iterable
import numpy as np

from .world import World, Tile
from .config import CitizenConfig

# Tiles a citizen can stand on / walk through.
WALKABLE_TILES: frozenset[int] = frozenset({
    int(Tile.GRASS), int(Tile.BEACH), int(Tile.FOREST), int(Tile.HOLY),
})

# Tier thresholds, by population. Single source of truth.
# (name, min_population)
TIERS: tuple[tuple[str, int], ...] = (
    ("T0 Whisper",    1),
    ("T1 Blessing",   10),
    ("T2 Tempest",    100),
    ("T3 Cataclysm",  1000),
    ("T4 Apocalypse", 5000),
)


def tier_for(population: int) -> tuple[str, int]:
    """Return (tier_name, tier_index) for the given population.
    Index 0 = pre-T0 (no citizens). Index 1..5 = T0..T4.
    """
    if population < 1:
        return ("—", 0)
    idx = 0
    for i, (_, threshold) in enumerate(TIERS, start=1):
        if population >= threshold:
            idx = i
        else:
            break
    return (TIERS[idx - 1][0], idx)


class CitizenState(enum.IntEnum):
    """States in the citizen FSM. P1 uses IDLE/WANDER/MATE/DYING.
    The rest are placeholders so save-files stay forward-compatible.
    """
    IDLE      = 0
    WANDER    = 1
    MATE      = 2
    DYING     = 3
    # Placeholders (not dispatched in P1):
    FORAGE    = 4
    EATING    = 5
    SLEEP     = 6
    FLEE      = 7
    CONVERTED = 8


class Facing(enum.IntEnum):
    SOUTH = 0
    NORTH = 1
    EAST  = 2
    WEST  = 3


@dataclass
class Citizen:
    """A single citizen. Coordinates are in tile units (sub-tile float)."""
    id:        int
    faction:   int
    x:         float
    y:         float
    state:     CitizenState
    age:       float
    lifespan:  float
    repro_cd:  float
    facing:    Facing
    home_x:    float
    home_y:    float
    target_x:  float
    target_y:  float
    state_timer: float = 0.0  # time remaining in transient states (MATE, DYING)


class CitizenManager:
    """Owns the population and advances the simulation by sim-seconds.

    Use:
        cm = CitizenManager(cfg.citizen, world, world_seed=cfg.world.seed)
        # ... in main loop, accumulator-style:
        while accumulator >= tick_dt:
            cm.tick(tick_dt, world)
            accumulator -= tick_dt
    """

    def __init__(self, cfg: CitizenConfig, world: World, world_seed: int):
        self.cfg = cfg
        self._rng = np.random.default_rng(world_seed ^ cfg.spawn_seed)
        self._next_id: int = 0
        self.citizens: list[Citizen] = []
        self._spawn_initial(world)

    # -- public API ---------------------------------------------------------

    def population(self, faction: int = 0) -> int:
        """Count of alive citizens (not in DYING) belonging to `faction`."""
        return sum(
            1 for c in self.citizens
            if c.faction == faction and c.state != CitizenState.DYING
        )

    def tick(self, dt: float, world: World) -> None:
        """Advance the sim by `dt` sim-seconds. Single tick at 5 Hz = 0.2s."""
        new_citizens: list[Citizen] = []
        dead_idx: list[int] = []
        cfg = self.cfg

        # Pre-build a coarse spatial index for mate-finding.
        spatial: dict[tuple[int, int], list[int]] = {}
        for i, c in enumerate(self.citizens):
            spatial.setdefault((int(c.x), int(c.y)), []).append(i)

        for i, c in enumerate(self.citizens):
            # Aging applies in every state.
            c.age += dt
            if c.repro_cd > 0.0:
                c.repro_cd = max(0.0, c.repro_cd - dt)

            # Lifespan check — preempts everything except already-dying.
            if c.state != CitizenState.DYING and c.age >= c.lifespan:
                c.state = CitizenState.DYING
                c.state_timer = cfg.dying_duration
                continue

            if c.state == CitizenState.DYING:
                c.state_timer -= dt
                if c.state_timer <= 0.0:
                    dead_idx.append(i)
                continue

            if c.state == CitizenState.MATE:
                c.state_timer -= dt
                if c.state_timer <= 0.0:
                    c.state = CitizenState.IDLE
                continue

            if c.state == CitizenState.IDLE:
                if (c.age >= cfg.maturity_age and c.repro_cd == 0.0):
                    mate_idx = self._find_mate(i, c, spatial)
                    if mate_idx is not None:
                        mate = self.citizens[mate_idx]
                        c.state = CitizenState.MATE
                        c.state_timer = cfg.mate_duration
                        c.repro_cd = cfg.repro_cooldown
                        mate.state = CitizenState.MATE
                        mate.state_timer = cfg.mate_duration
                        mate.repro_cd = cfg.repro_cooldown
                        # Only the lower-id partner spawns the child
                        # so we don't double-up.
                        if c.id < mate.id:
                            child = self._spawn_child(c, world)
                            if child is not None:
                                new_citizens.append(child)
                        continue
                p_wander = 1.0 - math.exp(-dt / max(0.01, cfg.wander_period))
                if self._rng.random() < p_wander:
                    tx, ty = self._pick_wander_target(c, world)
                    c.target_x = tx
                    c.target_y = ty
                    c.state = CitizenState.WANDER
                continue

            if c.state == CitizenState.WANDER:
                self._step_toward(c, c.target_x, c.target_y, dt, world)
                dx = c.target_x - c.x
                dy = c.target_y - c.y
                if dx * dx + dy * dy < 0.25:
                    c.state = CitizenState.IDLE
                continue

        # Apply births and deaths.
        if dead_idx:
            for idx in sorted(dead_idx, reverse=True):
                self.citizens.pop(idx)
        if new_citizens:
            self.citizens.extend(new_citizens)

    def iter_for_render(self) -> Iterable[Citizen]:
        return self.citizens

    # -- internals ----------------------------------------------------------

    def _spawn_initial(self, world: World) -> None:
        cfg = self.cfg
        cx = world.width // 2
        cy = world.height // 2
        r = cfg.spawn_radius_tiles
        attempts = 0
        spawned = 0
        max_attempts = cfg.initial_population * 50
        while spawned < cfg.initial_population and attempts < max_attempts:
            attempts += 1
            x = int(self._rng.integers(max(0, cx - r), min(world.width, cx + r)))
            y = int(self._rng.integers(max(0, cy - r), min(world.height, cy + r)))
            if not _walkable(world, x, y):
                continue
            self.citizens.append(self._make_citizen(faction=0, x=x + 0.5, y=y + 0.5,
                                                    age=self._initial_age()))
            spawned += 1

    def _initial_age(self) -> float:
        """Initial age — spread but strictly pre-mature.

        Initial citizens all start under maturity_age so reproduction is
        not instant on world load (gives the player a moment to look
        around). They mature into reproduction over the first
        ``maturity_age`` sim seconds.

        Bounded by half of ``lifespan_mean`` as well, so config combinations
        with absurdly large maturity don't accidentally spawn already-
        dying citizens.
        """
        cfg = self.cfg
        upper = min(cfg.maturity_age * 0.95, cfg.lifespan_mean * 0.5)
        upper = max(0.0, upper)
        if upper <= 0.0:
            return 0.0
        return float(self._rng.uniform(0.0, upper))

    def _roll_lifespan(self) -> float:
        cfg = self.cfg
        lo = max(1.0, cfg.lifespan_mean - 2.0 * cfg.lifespan_jitter)
        hi = cfg.lifespan_mean + 2.0 * cfg.lifespan_jitter
        for _ in range(10):
            v = float(self._rng.normal(cfg.lifespan_mean, cfg.lifespan_jitter))
            if lo <= v <= hi:
                return v
        return cfg.lifespan_mean

    def _make_citizen(self, faction: int, x: float, y: float, age: float = 0.0) -> Citizen:
        cid = self._next_id
        self._next_id += 1
        return Citizen(
            id=cid,
            faction=faction,
            x=x, y=y,
            state=CitizenState.IDLE,
            age=age,
            lifespan=self._roll_lifespan(),
            repro_cd=0.0,
            facing=Facing.SOUTH,
            home_x=x, home_y=y,
            target_x=x, target_y=y,
            state_timer=0.0,
        )

    def _pick_wander_target(self, c: Citizen, world: World) -> tuple[float, float]:
        r = self.cfg.wander_radius
        for _ in range(8):
            dx = float(self._rng.integers(-r, r + 1))
            dy = float(self._rng.integers(-r, r + 1))
            tx = c.home_x + dx
            ty = c.home_y + dy
            ix, iy = int(tx), int(ty)
            if 0 <= ix < world.width and 0 <= iy < world.height and _walkable(world, ix, iy):
                return tx, ty
        return c.home_x, c.home_y

    def _step_toward(self, c: Citizen, tx: float, ty: float, dt: float, world: World) -> None:
        speed = self.cfg.wander_speed * dt
        dx = tx - c.x
        dy = ty - c.y
        d = math.hypot(dx, dy)
        if d < 1e-6:
            return
        step_x = dx / d * speed
        step_y = dy / d * speed
        nx, ny = c.x + step_x, c.y + step_y
        if _walkable(world, int(nx), int(ny)):
            c.x, c.y = nx, ny
        else:
            nx2 = c.x + step_x
            if _walkable(world, int(nx2), int(c.y)):
                c.x = nx2
            else:
                ny2 = c.y + step_y
                if _walkable(world, int(c.x), int(ny2)):
                    c.y = ny2
                # else: blocked — stay put
        # Facing follows step direction.
        if abs(step_x) > abs(step_y):
            c.facing = Facing.EAST if step_x > 0 else Facing.WEST
        elif abs(step_y) > 0:
            c.facing = Facing.SOUTH if step_y > 0 else Facing.NORTH

    def _find_mate(self, my_idx: int, me: Citizen,
                    spatial: dict[tuple[int, int], list[int]]) -> int | None:
        """Find a nearby same-faction mature mate. Chebyshev distance."""
        cfg = self.cfg
        r = cfg.repro_radius
        my_tx, my_ty = int(me.x), int(me.y)
        for ty in range(my_ty - r, my_ty + r + 1):
            for tx in range(my_tx - r, my_tx + r + 1):
                bucket = spatial.get((tx, ty))
                if not bucket:
                    continue
                for j in bucket:
                    if j == my_idx:
                        continue
                    other = self.citizens[j]
                    if other.faction != me.faction:
                        continue
                    if other.state != CitizenState.IDLE:
                        continue
                    if other.age < cfg.maturity_age:
                        continue
                    if other.repro_cd > 0.0:
                        continue
                    return j
        return None

    def _spawn_child(self, parent: Citizen, world: World) -> Citizen | None:
        """Spawn a child near `parent`. Returns None if no walkable tile found."""
        cfg = self.cfg
        r = cfg.repro_radius
        for _ in range(8):
            dx = float(self._rng.integers(-r, r + 1))
            dy = float(self._rng.integers(-r, r + 1))
            cx = parent.x + dx
            cy = parent.y + dy
            ix, iy = int(cx), int(cy)
            if 0 <= ix < world.width and 0 <= iy < world.height and _walkable(world, ix, iy):
                return self._make_citizen(faction=parent.faction, x=cx, y=cy, age=0.0)
        return None


def _walkable(world: World, x: int, y: int) -> bool:
    """True if (x, y) is in-bounds and the tile is walkable."""
    if x < 0 or y < 0 or x >= world.width or y >= world.height:
        return False
    return int(world.tiles[y, x]) in WALKABLE_TILES
