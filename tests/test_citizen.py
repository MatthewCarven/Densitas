"""Unit tests for citizen module — no display required.

Run from the repo root with:
    python -m pytest tests/
or directly:
    python tests/test_citizen.py
"""
from __future__ import annotations
import os
import sys
from dataclasses import replace

# Allow running this file directly (without pytest):
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from densitas.world import World, Tile
from densitas.config import WorldConfig, CitizenConfig
from densitas.citizen import (
    CitizenManager, CitizenState, Facing, tier_for, TIERS, WALKABLE_TILES,
)


def _world_cfg() -> WorldConfig:
    return WorldConfig(
        width=64, height=48, seed=42,
        sea_level=0.30, beach_thresh=0.34,
        forest_thresh=0.55, hill_thresh=0.70,
        mountain_thresh=0.85,
    )


def _citizen_cfg(**overrides) -> CitizenConfig:
    base = dict(
        initial_population=5,
        spawn_radius_tiles=20,
        spawn_seed=0,
        maturity_age=8.0,
        lifespan_mean=90.0,
        lifespan_jitter=30.0,
        repro_radius=2,
        repro_cooldown=6.0,
        mate_duration=0.5,
        dying_duration=0.5,
        wander_period=2.0,
        wander_radius=6,
        wander_speed=1.0,
        tick_hz=5,
    )
    base.update(overrides)
    return CitizenConfig(**base)


# ---------- spawn -----------------------------------------------------------

def test_spawn_initial_population_matches_config():
    world = World.generate(_world_cfg())
    cm = CitizenManager(_citizen_cfg(initial_population=10), world, world_seed=42)
    assert len(cm.citizens) == 10
    assert cm.population(faction=0) == 10


def test_spawn_is_deterministic_for_same_seed():
    world = World.generate(_world_cfg())
    a = CitizenManager(_citizen_cfg(), world, world_seed=42)
    b = CitizenManager(_citizen_cfg(), world, world_seed=42)
    a_pos = [(c.x, c.y) for c in a.citizens]
    b_pos = [(c.x, c.y) for c in b.citizens]
    assert a_pos == b_pos


def test_spawn_differs_for_different_seed():
    world = World.generate(_world_cfg())
    a = CitizenManager(_citizen_cfg(), world, world_seed=42)
    b = CitizenManager(_citizen_cfg(spawn_seed=99), world, world_seed=42)
    a_pos = [(c.x, c.y) for c in a.citizens]
    b_pos = [(c.x, c.y) for c in b.citizens]
    assert a_pos != b_pos


def test_initial_citizens_are_on_walkable_tiles():
    world = World.generate(_world_cfg())
    cm = CitizenManager(_citizen_cfg(initial_population=20), world, world_seed=42)
    for c in cm.citizens:
        ix, iy = int(c.x), int(c.y)
        assert 0 <= ix < world.width and 0 <= iy < world.height
        assert int(world.tiles[iy, ix]) in WALKABLE_TILES


# ---------- wander / movement ----------------------------------------------

def test_wander_stays_in_bounds_and_walkable():
    world = World.generate(_world_cfg())
    # Use a short wander period so many transitions happen, and a large
    # wander radius to stress edge cases.
    cfg = _citizen_cfg(initial_population=15, wander_period=0.4, wander_radius=10)
    cm = CitizenManager(cfg, world, world_seed=42)
    # Simulate ~10 sim seconds (50 ticks at 5 Hz).
    for _ in range(50):
        cm.tick(0.2, world)
    for c in cm.citizens:
        ix, iy = int(c.x), int(c.y)
        assert 0 <= ix < world.width and 0 <= iy < world.height
        assert int(world.tiles[iy, ix]) in WALKABLE_TILES, \
            f"citizen at non-walkable tile {(ix, iy)} value {world.tiles[iy, ix]}"


def test_wander_actually_moves():
    """Over enough ticks, at least some citizens should have moved from spawn."""
    world = World.generate(_world_cfg())
    cfg = _citizen_cfg(initial_population=10, wander_period=0.3)
    cm = CitizenManager(cfg, world, world_seed=42)
    start = [(c.x, c.y) for c in cm.citizens]
    for _ in range(60):
        cm.tick(0.2, world)
    end = [(c.x, c.y) for c in cm.citizens[:len(start)]]
    moved = sum(1 for s, e in zip(start, end) if s != e)
    assert moved >= 3, f"expected at least 3 of 10 citizens to move, got {moved}"


# ---------- reproduction ----------------------------------------------------

def test_population_grows_under_normal_conditions():
    """A small mature population packed together should reproduce."""
    world = World.generate(_world_cfg())
    # Tight config: low maturity, tight repro window, no death.
    cfg = _citizen_cfg(
        initial_population=6,
        maturity_age=0.0,           # everyone is mature immediately
        lifespan_mean=99999.0,
        lifespan_jitter=0.0,
        repro_radius=3,
        repro_cooldown=2.0,
        wander_radius=2,            # keep them clustered
        wander_period=5.0,
    )
    cm = CitizenManager(cfg, world, world_seed=42)
    start = len(cm.citizens)
    # 60 sim sec at 5 Hz.
    for _ in range(300):
        cm.tick(0.2, world)
    assert len(cm.citizens) > start, \
        f"expected population to grow from {start}; ended at {len(cm.citizens)}"


def test_no_reproduction_before_maturity():
    """If no citizen reaches maturity, no births happen."""
    world = World.generate(_world_cfg())
    cfg = _citizen_cfg(
        initial_population=6,
        maturity_age=99999.0,       # nobody ever matures
        lifespan_mean=99999.0,
        lifespan_jitter=0.0,
    )
    cm = CitizenManager(cfg, world, world_seed=42)
    start = len(cm.citizens)
    for _ in range(100):
        cm.tick(0.2, world)
    assert len(cm.citizens) == start


# ---------- death -----------------------------------------------------------

def test_citizens_die_at_lifespan():
    """With a tiny lifespan, all citizens should die within a short window."""
    world = World.generate(_world_cfg())
    cfg = _citizen_cfg(
        initial_population=8,
        maturity_age=999.0,         # no reproduction during the test
        lifespan_mean=2.0,
        lifespan_jitter=0.5,
        dying_duration=0.5,
    )
    cm = CitizenManager(cfg, world, world_seed=42)
    start = len(cm.citizens)
    assert start == 8
    # Simulate 6 sim seconds — exceeds lifespan + dying_duration even at max jitter.
    for _ in range(30):
        cm.tick(0.2, world)
    assert len(cm.citizens) == 0, f"expected 0 alive, got {len(cm.citizens)}"


# ---------- tier table ------------------------------------------------------

def test_tier_thresholds_partition():
    assert tier_for(0)    == ("—",             0)
    assert tier_for(1)    == ("T0 Whisper",    1)
    assert tier_for(9)    == ("T0 Whisper",    1)
    assert tier_for(10)   == ("T1 Blessing",   2)
    assert tier_for(99)   == ("T1 Blessing",   2)
    assert tier_for(100)  == ("T2 Tempest",    3)
    assert tier_for(999)  == ("T2 Tempest",    3)
    assert tier_for(1000) == ("T3 Cataclysm",  4)
    assert tier_for(4999) == ("T3 Cataclysm",  4)
    assert tier_for(5000) == ("T4 Apocalypse", 5)
    assert tier_for(50000)== ("T4 Apocalypse", 5)


def test_tier_list_has_5_tiers():
    assert len(TIERS) == 5
    # Thresholds strictly increasing
    thresholds = [t for _, t in TIERS]
    assert thresholds == sorted(thresholds)
    assert len(set(thresholds)) == 5


if __name__ == "__main__":
    tests = [
        test_spawn_initial_population_matches_config,
        test_spawn_is_deterministic_for_same_seed,
        test_spawn_differs_for_different_seed,
        test_initial_citizens_are_on_walkable_tiles,
        test_wander_stays_in_bounds_and_walkable,
        test_wander_actually_moves,
        test_population_grows_under_normal_conditions,
        test_no_reproduction_before_maturity,
        test_citizens_die_at_lifespan,
        test_tier_thresholds_partition,
        test_tier_list_has_5_tiers,
    ]
    for t in tests:
        t()
        print(f"  OK  {t.__name__}")
    print(f"\n{len(tests)} tests passed.")
