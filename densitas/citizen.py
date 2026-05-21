"""Citizen - autonomous inhabitants of the world.

Implements the state machine described in `Densitas_citizens.md` (P1) and
extended for food in `Densitas_food.md` (P1.5) and powers in
`Densitas_P3.md` (P3).

Design notes:
- Citizens are NEVER directly selected by the player.
- All behaviour is local: wander, age, eat, pair off, die.
- 5 Hz simulation tick (logic). Rendering runs at fps_target (60 Hz).
- No pathfinding. Movement projects onto walkable tiles; if a step
  crosses an unwalkable tile, slide along the walkable axis or stay.

P1.5 brings carrying capacity into the simulation. Citizens get hungry,
forage from food-bearing tiles, eat in place, and starve when food runs
out. Reproduction is gated on hunger so a famine self-throttles the
population long before exponential growth swamps the map.

P3 PR1 adds two CitizenManager hooks the PowerSystem calls:
  * `inspire_citizen` — pre-empt one citizen's wander target.
  * `find_nearest_other_faction` — Hunger-Pang dispatch helper.
  * `spawn_rival_stub(seed, n)` — debug-flag entry point for live-play
    testing of multi-faction codepaths before P4.

P3 PR2 adds the drown rule:
  * `drown_at(tx, ty, dying_duration)` — Raise/Lower invokes this when
    the mutated tile becomes unwalkable; every live citizen on that
    tile transitions to DYING (the existing 2.0s fade applies).
"""
from __future__ import annotations
import enum
import math
from dataclasses import dataclass
from typing import Iterable, Optional, TYPE_CHECKING
import numpy as np

from .world import World, Tile
from .config import CitizenConfig, FoodConfig

if TYPE_CHECKING:
    from .food import FoodField


# Tiles a citizen can stand on / walk through.
WALKABLE_TILES: frozenset[int] = frozenset({
    int(Tile.GRASS), int(Tile.BEACH), int(Tile.FOREST), int(Tile.HOLY),
})

# Tier thresholds, by population. Single source of truth.
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
    """States in the citizen FSM. P1.5 activates FORAGE and EATING.
    SLEEP/FLEE/CONVERTED remain placeholders for later milestones.
    """
    IDLE      = 0
    WANDER    = 1
    MATE      = 2
    DYING     = 3
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
    state_timer: float = 0.0  # time remaining in transient states
    # --- P1.5 additions ---
    hunger:    float = 0.0    # 0.0 fed -> 1.0 starving
    food_carried: int = 0     # P1.5 unused; reserved for future inventory tier
    # --- P3 PR1 additions ---
    inspire_bias_until: float = -1.0  # sim_t below which the citizen pursues an Inspire target


class CitizenManager:
    """Owns the population and advances the simulation by sim-seconds.

    `tick(dt, world, food)` now takes the food field too. Passing `None`
    is permitted for backward-compat tests (skips hunger/forage/eating
    bookkeeping; the FSM falls back to P1 behaviour).
    """

    def __init__(self, cfg: CitizenConfig, world: World, world_seed: int,
                 food_cfg: Optional[FoodConfig] = None):
        self.cfg = cfg
        self.food_cfg = food_cfg
        self._rng = np.random.default_rng(world_seed ^ cfg.spawn_seed)
        self._next_id: int = 0
        self.citizens: list[Citizen] = []
        self._spawn_initial(world)
        # Sim clock — written by tick() and read by inspire_bias logic.
        self._sim_t: float = 0.0

    # -- public API ---------------------------------------------------------

    def population(self, faction: int = 0) -> int:
        """Count of alive citizens (not in DYING) belonging to `faction`."""
        return sum(
            1 for c in self.citizens
            if c.faction == faction and c.state != CitizenState.DYING
        )

    def hunger_stats(self, faction: int = 0) -> tuple[int, int, int, float]:
        """Return (fed, hungry, starving, avg_hunger) counts for `faction`.

          * fed      = hunger <  repro_hunger_threshold (default 0.3)
          * hungry   = repro_hunger_threshold <= hunger < starve_hunger * 0.8
          * starving = hunger >= starve_hunger * 0.8

        If no food_cfg is set, returns zeros (P1 backward-compat).
        """
        if self.food_cfg is None:
            return (0, 0, 0, 0.0)
        fc = self.food_cfg
        fed = hungry = starving = 0
        total = 0
        sum_h = 0.0
        starve_warn = fc.starve_hunger * 0.8
        for c in self.citizens:
            if c.faction != faction or c.state == CitizenState.DYING:
                continue
            total += 1
            sum_h += c.hunger
            if c.hunger < fc.repro_hunger_threshold:
                fed += 1
            elif c.hunger >= starve_warn:
                starving += 1
            else:
                hungry += 1
        avg = sum_h / total if total else 0.0
        return (fed, hungry, starving, avg)

    def tick(self, dt: float, world: World,
              food: "FoodField | None" = None) -> None:
        """Advance the sim by `dt` sim-seconds. Single tick at 5 Hz = 0.2s.

        `food` is optional (P1 backward-compat): when None, hunger and
        forage/eating are disabled and the manager behaves as in P1.
        """
        self._sim_t += dt
        new_citizens: list[Citizen] = []
        dead_idx: list[int] = []
        cfg = self.cfg
        fc = self.food_cfg

        # Pre-build a coarse spatial index for mate-finding.
        spatial: dict[tuple[int, int], list[int]] = {}
        for i, c in enumerate(self.citizens):
            spatial.setdefault((int(c.x), int(c.y)), []).append(i)

        for i, c in enumerate(self.citizens):
            # Aging applies in every state.
            c.age += dt
            if c.repro_cd > 0.0:
                c.repro_cd = max(0.0, c.repro_cd - dt)

            # Hunger accrual (everywhere except DYING, where the body shuts down).
            if fc is not None and food is not None and c.state != CitizenState.DYING:
                c.hunger += fc.hunger_rate * dt
                if c.hunger > 1.0:
                    c.hunger = 1.0

            # Starvation: hunger maxed -> DYING.
            if fc is not None and food is not None:
                if c.state != CitizenState.DYING and c.hunger >= fc.starve_hunger:
                    c.state = CitizenState.DYING
                    c.state_timer = cfg.dying_duration
                    continue

            # Lifespan check - preempts everything except already-dying.
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

            if c.state == CitizenState.EATING:
                # Consume one bite from the tile we're on. If empty, hunt for another.
                if fc is not None and food is not None:
                    take = food.consume(int(c.x), int(c.y), fc.bite_size)
                    if take > 0.0:
                        c.hunger -= take * fc.calorie_per_food
                        if c.hunger < 0.0:
                            c.hunger = 0.0
                        c.state_timer -= dt
                        if c.state_timer <= 0.0 or c.hunger <= 0.0:
                            c.state = CitizenState.IDLE
                    else:
                        # Tile exhausted under us — go forage somewhere else.
                        c.state = CitizenState.FORAGE
                        c.state_timer = 0.0
                else:
                    c.state = CitizenState.IDLE
                continue

            if c.state == CitizenState.FORAGE:
                # Are we already on a food tile? Eat.
                if fc is not None and food is not None:
                    if food.query(int(c.x), int(c.y)) >= fc.min_forage_food:
                        c.state = CitizenState.EATING
                        c.state_timer = fc.eat_duration
                        continue
                    # Otherwise step toward our forage target.
                    self._step_toward(c, c.target_x, c.target_y, dt, world)
                    dx = c.target_x - c.x
                    dy = c.target_y - c.y
                    if dx * dx + dy * dy < 0.25:
                        # Arrived; re-evaluate the tile.
                        if food.query(int(c.x), int(c.y)) >= fc.min_forage_food:
                            c.state = CitizenState.EATING
                            c.state_timer = fc.eat_duration
                        else:
                            # Target tile got eaten while we walked; look again.
                            spot = food.find_nearest(
                                int(c.x), int(c.y),
                                fc.forage_radius_tiles, fc.min_forage_food,
                            )
                            if spot is not None:
                                c.target_x = float(spot[0]) + 0.5
                                c.target_y = float(spot[1]) + 0.5
                            else:
                                # Nothing nearby - fall back to a regular wander
                                # outward. We keep the hunger and starve if we
                                # can't find food in time.
                                c.state = CitizenState.WANDER
                                tx, ty = self._pick_wander_target(c, world)
                                c.target_x = tx
                                c.target_y = ty
                else:
                    c.state = CitizenState.IDLE
                continue

            # IDLE / WANDER are the only remaining states.
            # First: should we be foraging instead?
            if fc is not None and food is not None and c.hunger >= fc.forage_threshold:
                spot = food.find_nearest(
                    int(c.x), int(c.y),
                    fc.forage_radius_tiles, fc.min_forage_food,
                )
                if spot is not None:
                    c.target_x = float(spot[0]) + 0.5
                    c.target_y = float(spot[1]) + 0.5
                    c.state = CitizenState.FORAGE
                    continue
                # else: no food in range, fall through to wander (migration)

            if c.state == CitizenState.IDLE:
                # Mating eligibility: now also gated on hunger.
                if (c.age >= cfg.maturity_age and c.repro_cd == 0.0
                        and self._is_repro_fed(c)):
                    mate_idx = self._find_mate(i, c, spatial)
                    if mate_idx is not None:
                        mate = self.citizens[mate_idx]
                        c.state = CitizenState.MATE
                        c.state_timer = cfg.mate_duration
                        c.repro_cd = cfg.repro_cooldown
                        mate.state = CitizenState.MATE
                        mate.state_timer = cfg.mate_duration
                        mate.repro_cd = cfg.repro_cooldown
                        # Carrying the next generation costs a bit of hunger.
                        if fc is not None and food is not None:
                            c.hunger    = min(1.0, c.hunger    + fc.repro_hunger_threshold * 0.5)
                            mate.hunger = min(1.0, mate.hunger + fc.repro_hunger_threshold * 0.5)
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
                    # End-of-bias: once the citizen reaches the inspired
                    # target, the bias is consumed regardless of timer.
                    if c.inspire_bias_until > 0.0:
                        c.inspire_bias_until = -1.0
                continue

        # Apply births and deaths.
        if dead_idx:
            for idx in sorted(dead_idx, reverse=True):
                self.citizens.pop(idx)
        if new_citizens:
            self.citizens.extend(new_citizens)

    def iter_for_render(self) -> Iterable[Citizen]:
        return self.citizens

    # -- P3 PR1 hooks -------------------------------------------------------

    def inspire_citizen(
        self,
        target_tx: int,
        target_ty: int,
        faction: int,
        max_radius: int,
        bias_duration: float,
    ) -> Optional[Citizen]:
        """Find the nearest IDLE/WANDER citizen of `faction` within
        `max_radius` tiles of (target_tx, target_ty) and pre-empt their
        wander target. Returns the citizen affected, or None if none in
        range (which is a dispatch failure for the caller).

        Bias persists until `self._sim_t + bias_duration` or arrival.
        """
        best_idx: Optional[int] = None
        best_d2: float = float("inf")
        eligible = (CitizenState.IDLE, CitizenState.WANDER)
        for i, c in enumerate(self.citizens):
            if c.faction != faction or c.state not in eligible:
                continue
            dx = c.x - target_tx
            dy = c.y - target_ty
            d2 = dx * dx + dy * dy
            if d2 > max_radius * max_radius:
                continue
            if d2 < best_d2:
                best_d2 = d2
                best_idx = i
        if best_idx is None:
            return None
        c = self.citizens[best_idx]
        c.target_x = float(target_tx) + 0.5
        c.target_y = float(target_ty) + 0.5
        c.state = CitizenState.WANDER
        c.inspire_bias_until = self._sim_t + bias_duration
        return c

    def find_nearest_other_faction(
        self, tx: int, ty: int, my_faction: int, radius: int,
    ) -> Optional[Citizen]:
        """Used by Hunger-Pang. Returns nearest non-`my_faction`,
        non-DYING citizen within radius, or None."""
        best: Optional[Citizen] = None
        best_d2 = float("inf")
        r2 = radius * radius
        for c in self.citizens:
            if c.faction == my_faction or c.state == CitizenState.DYING:
                continue
            dx = c.x - tx
            dy = c.y - ty
            d2 = dx * dx + dy * dy
            if d2 > r2 or d2 >= best_d2:
                continue
            best = c
            best_d2 = d2
        return best

    def drown_at(self, tx: int, ty: int, dying_duration: float) -> int:
        """Transition every live citizen currently standing on tile
        (tx, ty) to DYING with `dying_duration` seconds left on the timer.

        Used by the Raise/Lower drown rule (P3 PR2 spec §5.3) — invoked
        after `world.mutate_tile` from the main loop when the new tile
        is unwalkable. Idempotent: citizens already DYING are skipped,
        so calling twice on the same tile is a no-op on the second pass.

        Returns the number of citizens newly DYING. The 2s fade in the
        belief field falls out for free (existing DYING-fades-belief
        behaviour, P1.5).
        """
        tx_i = int(tx); ty_i = int(ty)
        drowned = 0
        for c in self.citizens:
            if c.state == CitizenState.DYING:
                continue
            if int(c.x) == tx_i and int(c.y) == ty_i:
                c.state = CitizenState.DYING
                c.state_timer = float(dying_duration)
                drowned += 1
        return drowned

    def spawn_rival_stub(self, world: World, n: int, faction: int = 1,
                          seed: int = 0) -> int:
        """Debug-flag entry point. Spawn `n` rival-faction citizens at the
        canonical stub location: 3/4 across, mid-height. Returns the
        number actually placed (some attempts land on unwalkable tiles).

        Used by `python -m densitas.main --rival-stub-seed N`.
        """
        rng = np.random.default_rng(seed ^ 0xABCDEF)
        cx = (world.width * 3) // 4
        cy = world.height // 2
        r = self.cfg.spawn_radius_tiles
        placed = 0
        attempts = 0
        max_attempts = n * 50
        while placed < n and attempts < max_attempts:
            attempts += 1
            x = int(rng.integers(max(0, cx - r), min(world.width, cx + r)))
            y = int(rng.integers(max(0, cy - r), min(world.height, cy + r)))
            if not _walkable(world, x, y):
                continue
            self.citizens.append(self._make_citizen(
                faction=faction, x=x + 0.5, y=y + 0.5,
                age=self._initial_age(),
            ))
            placed += 1
        return placed

    # -- internals ----------------------------------------------------------

    def _is_repro_fed(self, c: Citizen) -> bool:
        """Is this citizen well-fed enough to consider mating?
        Returns True when food_cfg is unset (P1 mode)."""
        if self.food_cfg is None:
            return True
        return c.hunger < self.food_cfg.repro_hunger_threshold

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

    def _initial_hunger(self) -> float:
        """Spread initial hunger so a founding generation doesn't synchronise."""
        return float(self._rng.uniform(0.0, 0.2))

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
            hunger=self._initial_hunger(),
            food_carried=0,
            inspire_bias_until=-1.0,
        )

    def _pick_wander_target(self, c: Citizen, world: World) -> tuple[float, float]:
        # P3 PR1: respect Inspire bias. If the citizen has been inspired and the
        # bias hasn't timed out, keep the existing target.
        if c.inspire_bias_until > self._sim_t:
            return c.target_x, c.target_y
        if c.inspire_bias_until > 0.0 and c.inspire_bias_until <= self._sim_t:
            # Bias expired — clear and continue with normal wander.
            c.inspire_bias_until = -1.0

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
        if abs(step_x) > abs(step_y):
            c.facing = Facing.EAST if step_x > 0 else Facing.WEST
        elif abs(step_y) > 0:
            c.facing = Facing.SOUTH if step_y > 0 else Facing.NORTH

    def _find_mate(self, my_idx: int, me: Citizen,
                    spatial: dict[tuple[int, int], list[int]]) -> int | None:
        """Find a nearby same-faction mature mate. Chebyshev distance.
        P1.5: partner must also be `_is_repro_fed`."""
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
                    if not self._is_repro_fed(other):
                        continue
                    return j
        return None

    def _spawn_child(self, parent: Citizen, world: World) -> Citizen | None:
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
    if x < 0 or y < 0 or x >= world.width or y >= world.height:
        return False
    return int(world.tiles[y, x]) in WALKABLE_TILES
