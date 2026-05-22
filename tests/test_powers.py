"""P3 tests — PowerSystem dispatch + T0/T1 + Bless/Curse + rhetoric (PR1)
plus Raise/Lower terrain mutation + drown rule (PR2) plus the cast queue
for Raise/Lower (P3-Queue, Densitas_queue.md).

Spec §12 numbered tests:
  PR1: 1-11 (init / regen / cast validation / inspire / bless / curse / cooldown)
       + 7-9 (effects) + 16-18 (scripture / can_cast / hunger pang).
  PR2: 12-15 (raise/lower world+food update, mountain block, two-step lower,
       drown). Live in this file as test_21..test_24.
  Queue: enqueue / drain / cancel / clear / queued_invalid / cap.
         test_25..test_31.

Run from /tmp/dtest_p3/ to dodge the flaky-mount pytest-cleanup recursion.
"""
from __future__ import annotations
import math

import numpy as np
import pytest

from densitas.config import (
    PowerConfig, RelicConfig, CitizenConfig, WorldConfig, FoodConfig,
    FoodBiomeConfig, BeliefConfig,
)
from densitas.world import World, Tile
from densitas.citizen import CitizenManager, CitizenState, tier_for
from densitas.belief import BeliefField
from densitas.food import FoodField
from densitas.powers import (
    PowerSystem, PowerKind, POWERS, ActiveEffect, ScriptureEntry,
    effective_food_regen,
    _height_ladder_up, _height_ladder_down, _tile_valid_for,
)
from densitas.rhetoric import Rhetoric


# -- fixtures ---------------------------------------------------------------

def _world_cfg(seed=42):
    return WorldConfig(
        width=32, height=24, seed=seed,
        sea_level=0.30, beach_thresh=0.34, forest_thresh=0.55,
        hill_thresh=0.70, mountain_thresh=0.85,
    )


def _grass_world(seed=42):
    """A small all-grass world for stable test conditions."""
    w = World.generate(_world_cfg(seed))
    w.tiles[:] = int(Tile.GRASS)
    return w


def _citizen_cfg(initial=8):
    return CitizenConfig(
        initial_population=initial, spawn_radius_tiles=5, spawn_seed=0,
        maturity_age=8.0, lifespan_mean=180.0, lifespan_jitter=40.0,
        repro_radius=2, repro_cooldown=5.0, mate_duration=0.5,
        dying_duration=2.0, wander_period=2.0, wander_radius=6,
        wander_speed=1.0, tick_hz=5,
    )


def _food_cfg():
    return FoodConfig(
        hunger_rate=0.05, forage_threshold=0.40,
        repro_hunger_threshold=0.30, starve_hunger=1.00,
        eat_amount=0.20, eat_duration=1.00, bite_size=0.20,
        calorie_per_food=1.00, satiation_cap=0.50,
        forage_radius_tiles=8, min_forage_food=0.10,
        overlay_alpha_max=160,
        biome=FoodBiomeConfig(
            forest_initial=1.0, forest_regen=0.007,
            grass_initial=0.8, grass_regen=0.005,
            beach_initial=0.5, beach_regen=0.003,
            hill_initial=0.3, hill_regen=0.002,
            holy_initial=0.15, holy_regen=0.001,
        ),
    )


def _belief_cfg():
    return BeliefConfig(
        grid_w=16, grid_h=12, amplitude=1.0,
        blur_passes=2, blur_radius=1, recompute_hz=5, overlay_alpha_max=180,
    )


def _power_cfg():
    return PowerConfig(
        belief_regen_per_citizen=0.02,
        k_tier=(0.5, 1.0, 4.0, 20.0, 80.0),
        rhetoric_fade_seconds=6.0,
        scripture_log_max=32,
        inspire_cooldown=1.5, calm_cooldown=1.5, hunger_pang_cooldown=3.0,
        raise_cooldown=2.0, lower_cooldown=2.0,
        bless_cooldown=4.0, curse_cooldown=4.0,
        bless_multiplier=2.0, curse_multiplier=0.2,
        effect_duration_t1=30.0,
        inspire_radius=4, hunger_pang_radius=0,
        bless_radius=4, curse_radius=4,
        queue_cap=16,
        relic=RelicConfig(
            amplitude=20.0, place_cooldown=30.0,
            shatter_ratio=1.5, shatter_time=8.0,
            attract_radius=8, attract_probability=0.4,
            initial_count=3,
        ),
    )


@pytest.fixture
def make_env():
    """Return a builder that yields (cm, world, food, belief, ps, rhet)."""
    def _build(*, initial_pop=8, seed=42):
        w = _grass_world(seed=seed)
        cc = _citizen_cfg(initial=initial_pop)
        cm = CitizenManager(cc, w, world_seed=seed, food_cfg=_food_cfg())
        food = FoodField(_food_cfg(), w)
        belief = BeliefField(_belief_cfg(), w, dying_duration=cc.dying_duration)
        belief.recompute(cm.citizens)
        rhet = Rhetoric({
            "inspire": {"open_eye": {"consecration": ["test inspire line"]}},
            "calm":    {"open_eye": {"consecration": ["test calm line"]}},
            "bless":   {"open_eye": {"consecration": ["test bless line"]}},
            "curse":   {"open_eye": {"consecration": ["test curse line"]}},
            "hunger_pang": {"open_eye": {"consecration": ["test hunger pang line"]}},
            "raise":   {"open_eye": {"consecration": ["test raise line"]}},
            "lower":   {"open_eye": {"consecration": ["test lower line"]}},
        }, seed=seed)
        ps = PowerSystem(_power_cfg(), n_factions=2,
                         rhetoric_pick=rhet.pick)
        return cm, w, food, belief, ps, rhet
    return _build


def _stuff_population(cm, world, n, faction=0, around_xy=(5, 5)):
    """Inject N synthetic citizens around a tile so tier-gates change."""
    cx, cy = around_xy
    for _ in range(n):
        cm.citizens.append(cm._make_citizen(
            faction=faction, x=float(cx) + 0.5, y=float(cy) + 0.5, age=10.0,
        ))


# -- tests ------------------------------------------------------------------

def test_01_init_empty_state(make_env):
    cm, world, food, belief, ps, _ = make_env()
    assert ps.pool == [0.0, 0.0]
    assert ps.cooldowns == {}
    assert ps.effects == []
    assert ps.scripture_log == []


def test_02_pool_regen_scales_with_population(make_env):
    cm, world, food, belief, ps, _ = make_env(initial_pop=8)
    # 8 citizens × 0.02 × 1 sec = 0.16
    ps.tick(1.0, cm, sim_t=1.0)
    assert math.isclose(ps.pool[0], 8 * 0.02 * 1.0, rel_tol=1e-6)
    # Faction 1 has no citizens — pool stays zero.
    assert ps.pool[1] == 0.0


def test_03_cast_on_empty_pool_fails_and_doesnt_debit(make_env):
    cm, world, food, belief, ps, _ = make_env()
    _stuff_population(cm, world, 20, faction=0)   # tier T1
    tx, ty = 5, 5
    pool_before = ps.pool[0]
    r = ps.cast(PowerKind.BLESS, 0, tx, ty, cm, world, food, belief, sim_t=0.0)
    assert not r.ok
    assert "belief" in r.reason
    assert ps.pool[0] == pool_before
    # No cooldown on validation failure.
    assert (0, int(PowerKind.BLESS)) not in ps.cooldowns


def test_04_cast_below_tier_fails(make_env):
    cm, world, food, belief, ps, _ = make_env(initial_pop=5)  # tier T0 only
    tx, ty = 5, 5
    r = ps.cast(PowerKind.BLESS, 0, tx, ty, cm, world, food, belief, sim_t=0.0)
    assert not r.ok
    assert r.reason == "need T1"


def test_05_inspire_moves_nearest_citizen_target(make_env):
    cm, world, food, belief, ps, _ = make_env(initial_pop=8)
    # Pick an arbitrary citizen and capture old target.
    target_tx, target_ty = 5, 5
    # Place a citizen near (5,5) so it's the nearest.
    cm.citizens.clear()
    near = cm._make_citizen(faction=0, x=5.5, y=5.5, age=10.0)
    far  = cm._make_citizen(faction=0, x=20.5, y=15.5, age=10.0)
    cm.citizens.extend([near, far])
    # Manually pre-set target so we can detect mutation.
    near.target_x = 99.0; near.target_y = 99.0
    far.target_x  = 99.0; far.target_y  = 99.0
    r = ps.cast(PowerKind.INSPIRE, 0, target_tx, target_ty, cm, world, food, belief, sim_t=0.0)
    assert r.ok, r.reason
    assert near.target_x == 5.5 and near.target_y == 5.5
    assert near.state == CitizenState.WANDER
    # Far citizen untouched.
    assert far.target_x == 99.0 and far.target_y == 99.0


def test_06_inspire_no_citizen_in_range_charges_cost(make_env):
    cm, world, food, belief, ps, _ = make_env()
    cm.citizens.clear()
    # Place a single citizen far from the target so it falls outside radius.
    cm.citizens.append(cm._make_citizen(faction=0, x=2.5, y=2.5, age=10.0))
    # Tier — need T0. One citizen is enough.
    assert tier_for(cm.population(0))[1] >= 1
    ps.pool[0] = 5.0
    r = ps.cast(PowerKind.INSPIRE, 0, 25, 20, cm, world, food, belief, sim_t=0.0)
    # Cost is 0 so pool unchanged, but cooldown should still be set
    # (dispatch ran; no citizen was found, but that's a noop).
    assert r.ok  # validation passes; dispatch is a no-op
    assert (0, int(PowerKind.INSPIRE)) in ps.cooldowns


def test_07_bless_creates_effect_and_doubles_regen(make_env):
    cm, world, food, belief, ps, _ = make_env()
    _stuff_population(cm, world, 20, faction=0)
    ps.pool[0] = 50.0
    tx, ty = 5, 5
    food.regen[ty, tx] = 1.0
    food.food[ty, tx] = 0.0
    food.cap[ty, tx] = 100.0
    r = ps.cast(PowerKind.BLESS, 0, tx, ty, cm, world, food, belief, sim_t=0.0)
    assert r.ok
    assert len(ps.effects) == 1
    assert ps.effects[0].kind == PowerKind.BLESS
    # Apply one tick.
    food.recompute(0.2, effects=ps.effects)
    # Base regen 1.0 * bless 2.0 * dt 0.2 = 0.4
    assert math.isclose(float(food.food[ty, tx]), 0.4, abs_tol=1e-5)


def test_08_bless_expires_and_regen_reverts(make_env):
    cm, world, food, belief, ps, _ = make_env()
    _stuff_population(cm, world, 20, faction=0)
    ps.pool[0] = 50.0
    tx, ty = 5, 5
    r = ps.cast(PowerKind.BLESS, 0, tx, ty, cm, world, food, belief, sim_t=0.0)
    assert r.ok
    # Tick past effect duration (30s).
    for _ in range(int(31.0 / 0.2)):
        ps.tick(0.2, cm, sim_t=0.0)
    assert ps.effects == []


def test_09_curse_purges_existing_bless_at_same_tile(make_env):
    cm, world, food, belief, ps, _ = make_env()
    _stuff_population(cm, world, 20, faction=0)
    ps.pool[0] = 100.0
    tx, ty = 5, 5
    ps.cast(PowerKind.BLESS, 0, tx, ty, cm, world, food, belief, sim_t=0.0)
    assert len(ps.effects) == 1
    # Curse on top of Bless on same tile — purges Bless first then appends Curse.
    ps.cooldowns.clear()
    ps.cast(PowerKind.CURSE, 0, tx, ty, cm, world, food, belief, sim_t=1.0)
    assert len(ps.effects) == 1
    assert ps.effects[0].kind == PowerKind.CURSE


def test_10_cooldown_blocks_repeat_cast(make_env):
    cm, world, food, belief, ps, _ = make_env()
    _stuff_population(cm, world, 20, faction=0)
    ps.pool[0] = 100.0
    tx, ty = 5, 5
    r1 = ps.cast(PowerKind.BLESS, 0, tx, ty, cm, world, food, belief, sim_t=0.0)
    assert r1.ok
    r2 = ps.cast(PowerKind.BLESS, 0, tx, ty, cm, world, food, belief, sim_t=0.0)
    assert not r2.ok and "cool" in r2.reason


def test_11_cooldown_bleeds_via_tick(make_env):
    cm, world, food, belief, ps, _ = make_env()
    _stuff_population(cm, world, 20, faction=0)
    ps.pool[0] = 100.0
    tx, ty = 5, 5
    ps.cast(PowerKind.BLESS, 0, tx, ty, cm, world, food, belief, sim_t=0.0)
    # Cooldown is 4s. Tick 5s.
    for _ in range(int(5.0 / 0.2)):
        ps.tick(0.2, cm, sim_t=0.0)
    assert (0, int(PowerKind.BLESS)) not in ps.cooldowns


def test_12_scripture_appends_one_per_successful_cast(make_env):
    cm, world, food, belief, ps, _ = make_env()
    _stuff_population(cm, world, 20, faction=0)
    ps.pool[0] = 200.0
    tx, ty = 5, 5
    ps.cast(PowerKind.INSPIRE, 0, tx, ty, cm, world, food, belief, sim_t=0.0)
    ps.cast(PowerKind.BLESS,   0, tx, ty, cm, world, food, belief, sim_t=1.0)
    assert len(ps.scripture_log) == 2
    assert ps.scripture_log[0].power == PowerKind.INSPIRE
    assert ps.scripture_log[1].power == PowerKind.BLESS


def test_13_scripture_fades_old_entries(make_env):
    cm, world, food, belief, ps, _ = make_env()
    _stuff_population(cm, world, 20, faction=0)
    ps.pool[0] = 100.0
    ps.cast(PowerKind.INSPIRE, 0, 5, 5, cm, world, food, belief, sim_t=0.0)
    assert len(ps.scripture_log) == 1
    # Tick beyond fade window (6s).
    ps.tick(0.1, cm, sim_t=10.0)
    assert ps.scripture_log == []


def test_14_can_cast_returns_concrete_reasons(make_env):
    cm, world, food, belief, ps, _ = make_env(initial_pop=5)
    # Below tier.
    ok, why = ps.can_cast(PowerKind.BLESS, 0, 5, 5, cm, world)
    assert not ok and why == "need T1"
    # Above tier but underfunded.
    _stuff_population(cm, world, 20, faction=0)
    ok, why = ps.can_cast(PowerKind.BLESS, 0, 5, 5, cm, world)
    assert not ok and "belief" in why
    # OOB tile.
    ps.pool[0] = 100.0
    ok, why = ps.can_cast(PowerKind.BLESS, 0, 9999, 9999, cm, world)
    assert not ok and why == "out of bounds"


def test_15_tile_validation_per_kind():
    # Direct unit test of _tile_valid_for.
    ok, _ = _tile_valid_for(PowerKind.RAISE, int(Tile.MOUNTAIN))
    assert not ok
    ok, _ = _tile_valid_for(PowerKind.LOWER, int(Tile.WATER))
    assert not ok
    ok, _ = _tile_valid_for(PowerKind.BLESS, int(Tile.WATER))
    assert not ok
    ok, _ = _tile_valid_for(PowerKind.BLESS, int(Tile.GRASS))
    assert ok
    ok, _ = _tile_valid_for(PowerKind.INSPIRE, int(Tile.WATER))
    assert ok  # Inspire is tile-agnostic


def test_16_height_ladder_round_trip():
    # GRASS up -> FOREST, down -> BEACH.
    assert _height_ladder_up(int(Tile.GRASS)) == int(Tile.FOREST)
    assert _height_ladder_down(int(Tile.GRASS)) == int(Tile.BEACH)
    # WATER cannot go lower; MOUNTAIN cannot go higher.
    assert _height_ladder_up(int(Tile.MOUNTAIN)) == int(Tile.MOUNTAIN)
    assert _height_ladder_down(int(Tile.WATER)) == int(Tile.WATER)
    # BEACH lowers to WATER (drown rule applies in PR2).
    assert _height_ladder_down(int(Tile.BEACH)) == int(Tile.WATER)


def test_17_effective_food_regen_applies_multipliers():
    base = np.ones((10, 10), dtype=np.float32)
    eff = [
        ActiveEffect(kind=PowerKind.BLESS, tx=5, ty=5, radius=2,
                     multiplier=2.0, timer=10.0, caster_faction=0),
    ]
    out = effective_food_regen(base, eff)
    # Inside the radius: doubled.
    assert math.isclose(float(out[5, 5]), 2.0)
    assert math.isclose(float(out[5, 3]), 2.0)  # edge of square footprint
    assert math.isclose(float(out[5, 7]), 2.0)
    # Outside radius: untouched.
    assert math.isclose(float(out[0, 0]), 1.0)


def test_18_hunger_pang_stub_targets_other_faction(make_env):
    cm, world, food, belief, ps, _ = make_env()
    _stuff_population(cm, world, 20, faction=0)   # T1
    # Drop one rival into the bullseye.
    cm.citizens.append(cm._make_citizen(faction=1, x=5.5, y=5.5, age=10.0))
    rival_idx = len(cm.citizens) - 1
    rival = cm.citizens[rival_idx]
    rival.state = CitizenState.IDLE
    ps.pool[0] = 10.0
    r = ps.cast(PowerKind.HUNGER_PANG, 0, 5, 5, cm, world, food, belief, sim_t=0.0)
    assert r.ok, r.reason
    assert rival.state == CitizenState.FORAGE


def test_19_underfunded_cast_does_not_debit(make_env):
    cm, world, food, belief, ps, _ = make_env()
    _stuff_population(cm, world, 20, faction=0)
    ps.pool[0] = 5.0  # below Bless cost of 10
    r = ps.cast(PowerKind.BLESS, 0, 5, 5, cm, world, food, belief, sim_t=0.0)
    assert not r.ok
    assert ps.pool[0] == 5.0
    # No cooldown either — validation failed before debit/dispatch.
    assert (0, int(PowerKind.BLESS)) not in ps.cooldowns


def test_20_rhetoric_picks_line():
    rhet = Rhetoric({
        "bless": {"open_eye": {"consecration": ["A", "B", "C"]}},
    }, seed=42)
    s = rhet.pick("bless", "open_eye", 0.0)
    assert s in ("A", "B", "C")
    # Missing key falls through to placeholder rather than KeyError.
    s2 = rhet.pick("doesnotexist", "open_eye", 0.0)
    assert s2 == "<doesnotexist>"


# -- PR2 — Raise / Lower terrain mutation -----------------------------------
#
# Spec §12 #12-15. We wire a mutate_tile callback the same way main.py does:
# `world.mutate_tile` for the world/food/repaint update + `cm.drown_at` for
# any citizen left on a newly-unwalkable tile. The repaint_cb is a no-op so
# the tests can run headlessly (no pygame surface required).

def _no_repaint(world, tx, ty):
    """Headless renderer stand-in for tests — does nothing."""
    return None


def _wire_mutate_tile(ps, world, food, citizen_mgr=None, dying_duration=2.0):
    """Inject a mutate_tile callback into the PowerSystem (same shape main.py uses)."""
    from densitas.world import mutate_tile, is_walkable_tile

    def cb(tx, ty, new_tile):
        changed = mutate_tile(world, food, _no_repaint, tx, ty, new_tile)
        if changed and citizen_mgr is not None:
            if not is_walkable_tile(int(world.tiles[ty, tx])):
                citizen_mgr.drown_at(tx, ty, dying_duration)
        return changed

    ps._mutate_tile = cb


def test_21_raise_grass_to_forest_updates_world_and_food(make_env):
    """Spec §12 #12 — Raise on GRASS should bump tile, heightmap, and food
    cap/regen from the new tile's biome row."""
    cm, world, food, belief, ps, _ = make_env()
    _stuff_population(cm, world, 20, faction=0)
    _wire_mutate_tile(ps, world, food, cm)
    tx, ty = 5, 5
    # Force-set the starting state so the test doesn't depend on the fixture.
    world.tiles[ty, tx] = int(Tile.GRASS)
    food.cap[ty, tx] = 0.8
    food.regen[ty, tx] = 0.005
    food.food[ty, tx] = 0.8
    h_before = float(world.heightmap[ty, tx])
    food_ver_before = food.version

    ps.pool[0] = 100.0
    r = ps.cast(PowerKind.RAISE, 0, tx, ty, cm, world, food, belief, sim_t=0.0)
    assert r.ok, r.reason
    # Tile climbed one rank on the height ladder.
    assert int(world.tiles[ty, tx]) == int(Tile.FOREST)
    # Food field follows the new biome (FOREST: 1.0 cap, 0.007 regen — see _food_cfg).
    assert math.isclose(float(food.cap[ty, tx]),   1.0,   abs_tol=1e-5)
    assert math.isclose(float(food.regen[ty, tx]), 0.007, abs_tol=1e-6)
    # Heightmap moved (canonical band for the new tile).
    assert float(world.heightmap[ty, tx]) != h_before
    # Food version bumped so any cached overlay invalidates.
    assert food.version > food_ver_before


def test_22_raise_on_mountain_fails_with_reason(make_env):
    """Spec §12 #13 — MOUNTAIN cannot be raised; can_cast surfaces the reason."""
    cm, world, food, belief, ps, _ = make_env()
    _stuff_population(cm, world, 20, faction=0)
    _wire_mutate_tile(ps, world, food, cm)
    tx, ty = 5, 5
    world.tiles[ty, tx] = int(Tile.MOUNTAIN)
    ps.pool[0] = 100.0
    r = ps.cast(PowerKind.RAISE, 0, tx, ty, cm, world, food, belief, sim_t=0.0)
    assert not r.ok
    assert r.reason == "can't raise mountain"
    # Validation failure: pool untouched, no cooldown set.
    assert ps.pool[0] == 100.0
    assert (0, int(PowerKind.RAISE)) not in ps.cooldowns


def test_23_two_lowers_take_grass_to_beach_to_water(make_env):
    """Spec §12 #14 — sequential Lower casts walk down the height ladder.
    Confirms WATER tiles have zero food cap/regen after the second step."""
    cm, world, food, belief, ps, _ = make_env()
    _stuff_population(cm, world, 20, faction=0)
    _wire_mutate_tile(ps, world, food, cm)
    tx, ty = 5, 5
    world.tiles[ty, tx] = int(Tile.GRASS)
    food.cap[ty, tx] = 0.8
    food.regen[ty, tx] = 0.005
    ps.pool[0] = 100.0

    r1 = ps.cast(PowerKind.LOWER, 0, tx, ty, cm, world, food, belief, sim_t=0.0)
    assert r1.ok, r1.reason
    assert int(world.tiles[ty, tx]) == int(Tile.BEACH)
    # Beach biome row from _food_cfg.
    assert math.isclose(float(food.cap[ty, tx]),   0.5,   abs_tol=1e-5)
    assert math.isclose(float(food.regen[ty, tx]), 0.003, abs_tol=1e-6)

    # Clear cooldown for the second cast.
    ps.cooldowns.clear()
    r2 = ps.cast(PowerKind.LOWER, 0, tx, ty, cm, world, food, belief, sim_t=2.5)
    assert r2.ok, r2.reason
    assert int(world.tiles[ty, tx]) == int(Tile.WATER)
    # WATER is barren (not in the biome table) — cap/regen drop to 0.
    assert float(food.cap[ty, tx])   == 0.0
    assert float(food.regen[ty, tx]) == 0.0
    # Standing food clamped down with the cap.
    assert float(food.food[ty, tx])  == 0.0


def test_24_lower_into_water_drowns_citizen(make_env):
    """Spec §12 #15 — a citizen left on a tile that becomes WATER (or any
    other unwalkable type) transitions to DYING."""
    # Park the population well away from the test tile so the only citizen
    # at (5, 5) is the victim we drop in here.
    cm, world, food, belief, ps, _ = make_env()
    _stuff_population(cm, world, 20, faction=0, around_xy=(20, 18))
    tx, ty = 5, 5
    # Set up BEACH so one Lower takes it to WATER.
    world.tiles[ty, tx] = int(Tile.BEACH)
    food.cap[ty, tx]   = 0.5
    food.regen[ty, tx] = 0.003

    victim = cm._make_citizen(faction=0, x=float(tx) + 0.5, y=float(ty) + 0.5, age=10.0)
    cm.citizens.append(victim)
    assert victim.state != CitizenState.DYING

    _wire_mutate_tile(ps, world, food, cm, dying_duration=2.0)
    ps.pool[0] = 100.0
    r = ps.cast(PowerKind.LOWER, 0, tx, ty, cm, world, food, belief, sim_t=0.0)
    assert r.ok, r.reason
    assert int(world.tiles[ty, tx]) == int(Tile.WATER)
    # The drown rule fired in the closure after mutate_tile returned True.
    assert victim.state == CitizenState.DYING
    assert victim.state_timer > 0.0
    # Calling drown_at again on the same tile is idempotent (already-DYING skipped).
    cm.drown_at(tx, ty, dying_duration=2.0)
    assert victim.state == CitizenState.DYING



# -- P3-Queue — click-chain Raise/Lower (Densitas_queue.md) ----------------

def test_25_cast_or_queue_ready_fires_immediately(make_env):
    """cast_or_queue on a ready Raise behaves like cast()."""
    cm, world, food, belief, ps, _ = make_env()
    _stuff_population(cm, world, 20, faction=0)
    _wire_mutate_tile(ps, world, food, cm)
    tx, ty = 5, 5
    world.tiles[ty, tx] = int(Tile.GRASS)
    ps.pool[0] = 100.0
    r = ps.cast_or_queue(PowerKind.RAISE, 0, tx, ty, cm, world, food, belief, sim_t=0.0)
    assert r.ok
    assert int(world.tiles[ty, tx]) == int(Tile.FOREST)
    # Queue should still be empty (immediate fire path).
    assert (0, int(PowerKind.RAISE)) not in ps.queues
    # Cooldown set.
    assert ps.cooldowns.get((0, int(PowerKind.RAISE)), 0.0) > 0.0


def test_26_cast_or_queue_on_cooldown_enqueues_and_debits(make_env):
    """cast_or_queue while cooling enqueues and debits belief immediately."""
    cm, world, food, belief, ps, _ = make_env()
    _stuff_population(cm, world, 20, faction=0)
    _wire_mutate_tile(ps, world, food, cm)
    world.tiles[5, 5] = int(Tile.GRASS)
    world.tiles[5, 6] = int(Tile.GRASS)
    ps.pool[0] = 100.0
    # First fires immediately (pool 100 -> 95).
    ps.cast_or_queue(PowerKind.RAISE, 0, 5, 5, cm, world, food, belief, sim_t=0.0)
    pool_after_first = ps.pool[0]
    # Second enqueues (pool 95 -> 90).
    r2 = ps.cast_or_queue(PowerKind.RAISE, 0, 6, 5, cm, world, food, belief, sim_t=0.1)
    assert r2.ok and r2.reason == "queued"
    assert ps.pool[0] == pool_after_first - 5.0
    q = ps.queues[(0, int(PowerKind.RAISE))]
    assert len(q) == 1
    assert (q[0].tx, q[0].ty) == (6, 5)


def test_27_drain_queues_pops_one_per_cleared_cooldown(make_env):
    """Two enqueued + cooldown tick -> first drains, world updated, queue shrinks."""
    cm, world, food, belief, ps, _ = make_env()
    _stuff_population(cm, world, 20, faction=0)
    _wire_mutate_tile(ps, world, food, cm)
    world.tiles[5, 5] = int(Tile.GRASS)
    world.tiles[5, 6] = int(Tile.GRASS)
    world.tiles[5, 7] = int(Tile.GRASS)
    ps.pool[0] = 100.0
    # Fire one + queue two. After this: 1 cooling, 2 queued.
    ps.cast_or_queue(PowerKind.RAISE, 0, 5, 5, cm, world, food, belief, sim_t=0.0)
    ps.cast_or_queue(PowerKind.RAISE, 0, 6, 5, cm, world, food, belief, sim_t=0.0)
    ps.cast_or_queue(PowerKind.RAISE, 0, 7, 5, cm, world, food, belief, sim_t=0.0)
    assert len(ps.queues[(0, int(PowerKind.RAISE))]) == 2
    # Tick past 2.0s cooldown, then drain.
    for _ in range(int(2.5 / 0.2)):
        ps.tick(0.2, cm, sim_t=0.0)
    drained = ps.drain_queues(cm, world, food, belief, sim_t=2.5)
    assert drained == 1
    # First queued tile (6, 5) should have been raised.
    assert int(world.tiles[5, 6]) == int(Tile.FOREST)
    # One left in queue.
    assert len(ps.queues[(0, int(PowerKind.RAISE))]) == 1


def test_28_cancel_queued_at_refunds(make_env):
    """RMB cancel on a specific queued tile removes it and refunds."""
    cm, world, food, belief, ps, _ = make_env()
    _stuff_population(cm, world, 20, faction=0)
    _wire_mutate_tile(ps, world, food, cm)
    ps.pool[0] = 100.0
    # Fire one (cools), queue two.
    ps.cast_or_queue(PowerKind.RAISE, 0, 5, 5, cm, world, food, belief, sim_t=0.0)
    ps.cast_or_queue(PowerKind.RAISE, 0, 6, 5, cm, world, food, belief, sim_t=0.0)
    ps.cast_or_queue(PowerKind.RAISE, 0, 7, 5, cm, world, food, belief, sim_t=0.0)
    pool_before = ps.pool[0]
    # Cancel the (6, 5) tile.
    ok = ps.cancel_queued_at(6, 5, PowerKind.RAISE, 0)
    assert ok
    assert ps.pool[0] == pool_before + 5.0
    q = ps.queues[(0, int(PowerKind.RAISE))]
    assert len(q) == 1
    assert (q[0].tx, q[0].ty) == (7, 5)
    # Cancel on a non-queued tile returns False without changing pool.
    pool_now = ps.pool[0]
    assert not ps.cancel_queued_at(99, 99, PowerKind.RAISE, 0)
    assert ps.pool[0] == pool_now


def test_29_clear_queue_refunds_sum(make_env):
    """'C' key -> clear_queue refunds every queued cost in one go."""
    cm, world, food, belief, ps, _ = make_env()
    _stuff_population(cm, world, 20, faction=0)
    _wire_mutate_tile(ps, world, food, cm)
    ps.pool[0] = 100.0
    ps.cast_or_queue(PowerKind.RAISE, 0, 5, 5, cm, world, food, belief, sim_t=0.0)
    ps.cast_or_queue(PowerKind.RAISE, 0, 6, 5, cm, world, food, belief, sim_t=0.0)
    ps.cast_or_queue(PowerKind.RAISE, 0, 7, 5, cm, world, food, belief, sim_t=0.0)
    ps.cast_or_queue(PowerKind.RAISE, 0, 8, 5, cm, world, food, belief, sim_t=0.0)
    pool_before = ps.pool[0]
    n_queued_before = len(ps.queues[(0, int(PowerKind.RAISE))])
    n = ps.clear_queue(PowerKind.RAISE, 0)
    assert n == n_queued_before
    assert ps.pool[0] == pool_before + 5.0 * n
    assert (0, int(PowerKind.RAISE)) not in ps.queues
    # Clear on an empty queue is a no-op.
    assert ps.clear_queue(PowerKind.RAISE, 0) == 0


def test_30_queued_invalid_burns_and_logs(make_env):
    """A queued cast whose tile is no longer valid at dispatch burns
    silently — cooldown set, no refund, queued_invalid scripture line."""
    cm, world, food, belief, ps, _ = make_env()
    _stuff_population(cm, world, 20, faction=0)
    _wire_mutate_tile(ps, world, food, cm)
    world.tiles[5, 5] = int(Tile.GRASS)
    ps.pool[0] = 100.0
    # Fire one (cools), queue one targeting GRASS at (6, 5).
    ps.cast_or_queue(PowerKind.RAISE, 0, 5, 5, cm, world, food, belief, sim_t=0.0)
    ps.cast_or_queue(PowerKind.RAISE, 0, 6, 5, cm, world, food, belief, sim_t=0.0)
    pool_after_enqueue = ps.pool[0]
    log_len_before = len(ps.scripture_log)
    # Simulate the world moving on: someone else takes (6, 5) to MOUNTAIN.
    world.tiles[5, 6] = int(Tile.MOUNTAIN)
    # Tick past cooldown (pool regens during tick — capture state right
    # before drain so we can prove drain itself debited/refunded nothing).
    for _ in range(int(2.5 / 0.2)):
        ps.tick(0.2, cm, sim_t=0.0)
    pool_pre_drain = ps.pool[0]
    drained = ps.drain_queues(cm, world, food, belief, sim_t=2.5)
    assert drained == 1
    # World still MOUNTAIN — burn did NOT raise it.
    assert int(world.tiles[5, 6]) == int(Tile.MOUNTAIN)
    # Drain itself neither refunded nor debited — pool unchanged across drain.
    assert ps.pool[0] == pool_pre_drain
    # Pool still below pool_after_enqueue + 5 — no refund happened.
    assert ps.pool[0] < pool_after_enqueue + 5.0
    # Cooldown set anyway.
    assert ps.cooldowns.get((0, int(PowerKind.RAISE)), 0.0) > 0.0
    # Scripture line emitted with queued_invalid pattern (test fixture has
    # no queued_invalid lines so picker returns the placeholder).
    assert len(ps.scripture_log) > log_len_before
    assert ps.scripture_log[-1].line == "<queued_invalid>"


def test_31_queue_cap_blocks_overflow(make_env):
    """Beyond queue_cap, enqueue fails with 'queue full' and pool stays."""
    cm, world, food, belief, ps, _ = make_env()
    _stuff_population(cm, world, 20, faction=0)
    _wire_mutate_tile(ps, world, food, cm)
    # Shrink cap for the test. PowerConfig is frozen so we swap the cfg field.
    import dataclasses as _dc
    ps.cfg = _dc.replace(ps.cfg, queue_cap=3)
    ps.pool[0] = 100.0
    # Fire one (cools), queue three (hits cap).
    ps.cast_or_queue(PowerKind.RAISE, 0, 5, 5, cm, world, food, belief, sim_t=0.0)
    for x in (6, 7, 8):
        r = ps.cast_or_queue(PowerKind.RAISE, 0, x, 5, cm, world, food, belief, sim_t=0.0)
        assert r.ok, r.reason
    pool_at_cap = ps.pool[0]
    # 4th enqueue should fail with 'queue full' and not debit.
    r = ps.cast_or_queue(PowerKind.RAISE, 0, 9, 5, cm, world, food, belief, sim_t=0.0)
    assert not r.ok
    assert r.reason == "queue full"
    assert ps.pool[0] == pool_at_cap
    assert len(ps.queues[(0, int(PowerKind.RAISE))]) == 3


def test_32_brush_scripture_suppression(make_env):
    """P3-Brush: bulk Raise/Lower emits one scripture line per click.

    Mirrors the main.py brush loop: tile #1 goes through with
    `suppress_scripture=False`, tiles 2..N**2 go through with True.
    The first tile fires immediately and emits; the rest queue silently
    and stay silent on dispatch (both valid and invalid paths)."""
    cm, world, food, belief, ps, _ = make_env()
    _stuff_population(cm, world, 20, faction=0)
    _wire_mutate_tile(ps, world, food, cm)
    ps.pool[0] = 200.0
    # All-grass world from the fixture; pick a 4x4 brush footprint.
    bx, by = 4, 4
    n = 4
    sim_t = 0.0
    log_before = len(ps.scripture_log)
    pool_before = ps.pool[0]
    is_first = True
    for dx in range(n):
        for dy in range(n):
            r = ps.cast_or_queue(
                PowerKind.RAISE, 0, bx + dx, by + dy,
                cm, world, food, belief, sim_t=sim_t,
                suppress_scripture=not is_first,
            )
            assert r.ok, r.reason
            if r.ok:
                is_first = False
    # 16 calls => 1 immediate cast + 15 queued.
    assert len(ps.queues[(0, int(PowerKind.RAISE))]) == 15
    # Only the first tile emitted scripture.
    assert len(ps.scripture_log) == log_before + 1
    # Belief debited per tile (16 * 5.0 = 80.0).
    assert math.isclose(pool_before - ps.pool[0], 16 * 5.0, abs_tol=1e-6)

    # Drain all 15 queued. Each drain call should dispatch silently —
    # the log length never grows across a single drain_queues call.
    # (We can't simply check the final log length because the rhetoric
    # fade-prune in tick() will evict the initial entry past
    # `rhetoric_fade_seconds`; what matters is that drain itself never
    # appends.)
    for _ in range(20):  # ~48 sim_sec total — plenty for 15 queued @ 2s/each
        for _step in range(int(2.5 / 0.2)):
            ps.tick(0.2, cm, sim_t=sim_t)
            sim_t += 0.2
        before_drain = len(ps.scripture_log)
        ps.drain_queues(cm, world, food, belief, sim_t=sim_t)
        after_drain = len(ps.scripture_log)
        assert after_drain == before_drain, (
            f"queued drain emitted scripture (was {before_drain}, "
            f"now {after_drain}, sim_t={sim_t:.1f})"
        )
        if not ps.queues.get((0, int(PowerKind.RAISE))):
            break
    assert not ps.queues.get((0, int(PowerKind.RAISE))), "queue did not drain"


def test_33_brush_suppression_invalid_path_also_silent(make_env):
    """If a suppressed queued tile is invalid at dispatch, the
    queued_invalid scripture line is also suppressed — otherwise a 4x4
    brush over a mountain ridge would still spam the log."""
    cm, world, food, belief, ps, _ = make_env()
    _stuff_population(cm, world, 20, faction=0)
    _wire_mutate_tile(ps, world, food, cm)
    # Two tiles for a controlled 2-cast sequence: first fires, second
    # queues with suppress=True and becomes invalid before dispatch.
    world.tiles[5, 5] = int(Tile.GRASS)
    world.tiles[5, 6] = int(Tile.GRASS)
    ps.pool[0] = 100.0
    ps.cast_or_queue(PowerKind.RAISE, 0, 5, 5, cm, world, food, belief,
                     sim_t=0.0, suppress_scripture=False)
    ps.cast_or_queue(PowerKind.RAISE, 0, 6, 5, cm, world, food, belief,
                     sim_t=0.0, suppress_scripture=True)
    log_len_before = len(ps.scripture_log)   # 1 (the immediate)
    # World moves on — (6, 5) becomes MOUNTAIN; queued dispatch will
    # take the invalid path.
    world.tiles[5, 6] = int(Tile.MOUNTAIN)
    for _ in range(int(2.5 / 0.2)):
        ps.tick(0.2, cm, sim_t=0.0)
    ps.drain_queues(cm, world, food, belief, sim_t=2.5)
    # No new scripture line — the suppression covers the invalid path too.
    assert len(ps.scripture_log) == log_len_before

