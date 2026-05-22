"""Tests for the food field + hunger / forage / starvation."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from densitas.config import FoodConfig, FoodBiomeConfig, CitizenConfig
from densitas.food import FoodField
from densitas.citizen import (
    Citizen, CitizenState, CitizenManager, Facing, WALKABLE_TILES,
)
from densitas.world import World, Tile


def _make_food_cfg(**overrides) -> FoodConfig:
    defaults = dict(
        hunger_rate=0.005,
        forage_threshold=0.4,
        repro_hunger_threshold=0.3,
        starve_hunger=1.0,
        eat_amount=0.2,
        eat_duration=1.0,
        bite_size=0.2,
        calorie_per_food=1.0,
        satiation_cap=0.5,
        forage_radius_tiles=8,
        min_forage_food=0.5,
        overlay_alpha_max=160,
    )
    defaults.update(overrides)
    biome = FoodBiomeConfig(
        forest_initial=8.0, forest_regen=0.10,
        grass_initial=5.0,  grass_regen=0.08,
        beach_initial=3.0,  beach_regen=0.05,
        hill_initial=2.0,   hill_regen=0.03,
        holy_initial=1.0,   holy_regen=0.02,
    )
    return FoodConfig(biome=biome, **defaults)


def _make_citizen_cfg(**overrides) -> CitizenConfig:
    defaults = dict(
        initial_population=4, spawn_radius_tiles=3, spawn_seed=0,
        maturity_age=8.0, lifespan_mean=180.0, lifespan_jitter=40.0,
        repro_radius=2, repro_cooldown=5.0,
        mate_duration=0.5, dying_duration=2.0,
        wander_period=2.0, wander_radius=6, wander_speed=1.0,
        tick_hz=5,
    )
    defaults.update(overrides)
    return CitizenConfig(**defaults)


def _make_world(width: int = 32, height: int = 24,
                 tile: int = int(Tile.GRASS)) -> World:
    """Build a stub World filled with a single tile type."""
    tiles = np.full((height, width), tile, dtype=np.uint8)
    heightmap = np.zeros((height, width), dtype=np.float32)
    return World(width=width, height=height, seed=0,
                  tiles=tiles, heightmap=heightmap)


# ---------------------------------------------------------------------------
# FoodField
# ---------------------------------------------------------------------------

def test_food_initialises_at_biome_cap():
    w = _make_world(tile=int(Tile.GRASS))
    f = FoodField(_make_food_cfg(), w)
    # Whole world is grass -> all cells at grass_initial.
    assert np.allclose(f.food, 5.0)
    assert f.cap.max() == pytest.approx(5.0)


def test_food_barren_biomes_stay_zero():
    w = _make_world(tile=int(Tile.MOUNTAIN))
    f = FoodField(_make_food_cfg(), w)
    assert f.food.max() == 0.0
    assert f.regen.max() == 0.0


def test_food_mixed_biomes():
    w = _make_world(tile=int(Tile.GRASS), width=4, height=4)
    # Patch a forest stripe
    w.tiles[1, :] = int(Tile.FOREST)
    f = FoodField(_make_food_cfg(), w)
    assert f.food[1, 0] == pytest.approx(8.0)
    assert f.food[0, 0] == pytest.approx(5.0)


def test_food_regen_caps_at_initial():
    w = _make_world(tile=int(Tile.GRASS))
    f = FoodField(_make_food_cfg(), w)
    f.food *= 0.0       # depleted
    f.recompute(10000.0) # regen for "a very long time"
    # All cells should clamp at grass_initial (5.0), not exceed it.
    assert f.food.max() == pytest.approx(5.0)
    assert (f.food == f.cap).all()


def test_food_regen_partial():
    w = _make_world(tile=int(Tile.GRASS))
    f = FoodField(_make_food_cfg(), w)
    f.food *= 0.0
    f.recompute(1.0)    # 1 sim sec at grass_regen 0.08
    assert f.food[0, 0] == pytest.approx(0.08, abs=1e-5)


def test_food_consume_returns_taken_amount():
    w = _make_world(tile=int(Tile.GRASS))
    f = FoodField(_make_food_cfg(), w)
    taken = f.consume(2, 2, 0.5)
    assert taken == pytest.approx(0.5)
    assert f.food[2, 2] == pytest.approx(4.5)


def test_food_consume_clamps_to_available():
    w = _make_world(tile=int(Tile.GRASS))
    f = FoodField(_make_food_cfg(), w)
    taken = f.consume(2, 2, 10.0)    # cap is 5.0
    assert taken == pytest.approx(5.0)
    assert f.food[2, 2] == 0.0


def test_food_consume_on_barren_returns_zero():
    w = _make_world(tile=int(Tile.MOUNTAIN))
    f = FoodField(_make_food_cfg(), w)
    taken = f.consume(2, 2, 1.0)
    assert taken == 0.0


def test_food_version_bumps():
    w = _make_world()
    f = FoodField(_make_food_cfg(), w)
    v = f.version
    f.recompute(0.1)
    assert f.version == v + 1
    f.consume(0, 0, 0.1)
    assert f.version == v + 2


def test_find_nearest_picks_closest():
    w = _make_world(width=16, height=16, tile=int(Tile.MOUNTAIN))  # barren by default
    f = FoodField(_make_food_cfg(), w)
    # Plant two food tiles: one close, one far.
    f.food[2, 5] = 4.0
    f.food[10, 12] = 4.0
    spot = f.find_nearest(2, 4, radius=8, min_food=0.5)
    assert spot == (5, 2)   # closest


def test_find_nearest_respects_min_food():
    w = _make_world(width=16, height=16, tile=int(Tile.MOUNTAIN))
    f = FoodField(_make_food_cfg(), w)
    f.food[3, 3] = 0.1   # below min
    f.food[7, 7] = 1.0   # eligible but farther
    spot = f.find_nearest(3, 3, radius=8, min_food=0.5)
    assert spot == (7, 7)


def test_find_nearest_none_in_range():
    w = _make_world(width=16, height=16, tile=int(Tile.MOUNTAIN))
    f = FoodField(_make_food_cfg(), w)
    f.food[15, 15] = 5.0  # outside radius from origin
    assert f.find_nearest(0, 0, radius=4, min_food=0.5) is None


# ---------------------------------------------------------------------------
# Citizen hunger / forage / starvation / repro gate
# ---------------------------------------------------------------------------

def test_hunger_accrues_during_tick():
    w = _make_world(tile=int(Tile.GRASS))
    f = FoodField(_make_food_cfg(), w)
    cm = CitizenManager(_make_citizen_cfg(), w, world_seed=1, food_cfg=_make_food_cfg())
    cm.citizens[0].hunger = 0.0
    cm.citizens[0].state = CitizenState.IDLE
    cm.tick(1.0, w, f)
    # hunger_rate is 0.005/s, so after 1s we expect ~0.005 added.
    assert cm.citizens[0].hunger > 0.001
    assert cm.citizens[0].hunger < 0.05


def test_citizen_starves_when_food_runs_out():
    """Walkable but foodless: citizen runs out of food and starves to DYING."""
    w = _make_world(width=16, height=16, tile=int(Tile.GRASS))
    food_cfg = _make_food_cfg(hunger_rate=0.5)  # 2 sim sec to fully starve
    f = FoodField(food_cfg, w)
    f.food *= 0.0   # immediately drain the world; regen during the test is below min_forage_food
    cfg = _make_citizen_cfg(initial_population=0)
    cm = CitizenManager(cfg, w, world_seed=1, food_cfg=food_cfg)
    cm.citizens = [
        Citizen(id=1, faction=0, x=5.5, y=5.5,
                state=CitizenState.IDLE, age=20.0, lifespan=180.0, repro_cd=0.0,
                facing=Facing.SOUTH, home_x=5.5, home_y=5.5,
                target_x=5.5, target_y=5.5,
                hunger=0.2, food_carried=0),
    ]
    states_seen = set()
    for _ in range(80):  # 16 sim sec
        cm.tick(0.2, w, f)
        if cm.citizens:
            states_seen.add(cm.citizens[0].state)
        else:
            states_seen.add("removed")
            break
    # Citizen must have passed through DYING (starvation) and then been removed.
    assert CitizenState.DYING in states_seen or "removed" in states_seen
    # Final state: pop should be 0 (citizen died and was removed).
    assert cm.population(0) == 0


def test_reproduction_gated_on_hunger():
    """Two mature, hungry adults adjacent should NOT mate (gate active)."""
    w = _make_world(tile=int(Tile.GRASS))
    food_cfg = _make_food_cfg()
    f = FoodField(food_cfg, w)
    cfg = _make_citizen_cfg(initial_population=0, maturity_age=0.0,
                             repro_radius=2, mate_duration=0.5,
                             repro_cooldown=1.0)
    cm = CitizenManager(cfg, w, world_seed=1, food_cfg=food_cfg)
    # Drain the world's food so the gate actually bites — otherwise they
    # forage->eat->become fed->mate normally.
    f.food *= 0.0
    # Manually plant two mature hungry adults.
    cm.citizens = [
        Citizen(id=1, faction=0, x=10.5, y=10.5,
                state=CitizenState.IDLE, age=100.0, lifespan=180.0, repro_cd=0.0,
                facing=Facing.SOUTH, home_x=10.5, home_y=10.5,
                target_x=10.5, target_y=10.5,
                hunger=0.8, food_carried=0),
        Citizen(id=2, faction=0, x=11.5, y=10.5,
                state=CitizenState.IDLE, age=100.0, lifespan=180.0, repro_cd=0.0,
                facing=Facing.SOUTH, home_x=11.5, home_y=10.5,
                target_x=11.5, target_y=10.5,
                hunger=0.8, food_carried=0),
    ]
    starting = len(cm.citizens)
    for _ in range(10):
        cm.tick(0.2, w, f)
    # No reproduction should have occurred (both starving above gate).
    assert len(cm.citizens) == starting


def test_reproduction_allowed_when_fed():
    """Two mature, fed adults adjacent SHOULD mate."""
    w = _make_world(tile=int(Tile.GRASS))
    food_cfg = _make_food_cfg()
    f = FoodField(food_cfg, w)
    cfg = _make_citizen_cfg(initial_population=0, maturity_age=0.0,
                             repro_radius=2, mate_duration=0.2,
                             repro_cooldown=1.0)
    cm = CitizenManager(cfg, w, world_seed=1, food_cfg=food_cfg)
    cm.citizens = [
        Citizen(id=1, faction=0, x=10.5, y=10.5,
                state=CitizenState.IDLE, age=100.0, lifespan=180.0, repro_cd=0.0,
                facing=Facing.SOUTH, home_x=10.5, home_y=10.5,
                target_x=10.5, target_y=10.5,
                hunger=0.1, food_carried=0),
        Citizen(id=2, faction=0, x=11.5, y=10.5,
                state=CitizenState.IDLE, age=100.0, lifespan=180.0, repro_cd=0.0,
                facing=Facing.SOUTH, home_x=11.5, home_y=10.5,
                target_x=11.5, target_y=10.5,
                hunger=0.1, food_carried=0),
    ]
    starting = len(cm.citizens)
    for _ in range(20):
        cm.tick(0.2, w, f)
    assert len(cm.citizens) > starting


def test_forage_transitions_when_hungry():
    """A hungry citizen with food in range should enter FORAGE."""
    w = _make_world(tile=int(Tile.GRASS))
    food_cfg = _make_food_cfg()
    f = FoodField(food_cfg, w)
    cfg = _make_citizen_cfg(initial_population=0)
    cm = CitizenManager(cfg, w, world_seed=1, food_cfg=food_cfg)
    cm.citizens = [
        Citizen(id=1, faction=0, x=10.5, y=10.5,
                state=CitizenState.IDLE, age=50.0, lifespan=180.0, repro_cd=0.0,
                facing=Facing.SOUTH, home_x=10.5, home_y=10.5,
                target_x=10.5, target_y=10.5,
                hunger=0.6, food_carried=0),
    ]
    # Just one tick: the FORAGE/EATING dispatch should fire.
    cm.tick(0.2, w, f)
    # Either we found a tile and went to FORAGE/EATING, or we're on a food
    # tile (grass world) and went directly to EATING.
    assert cm.citizens[0].state in (
        CitizenState.FORAGE, CitizenState.EATING,
    )


def test_eating_reduces_hunger_and_tile_food():
    """An EATING citizen on a food tile drops hunger and decrements tile food."""
    w = _make_world(tile=int(Tile.GRASS))
    food_cfg = _make_food_cfg(eat_duration=10.0, bite_size=0.5, calorie_per_food=1.0,
                                hunger_rate=0.0)
    f = FoodField(food_cfg, w)
    cfg = _make_citizen_cfg(initial_population=0, dying_duration=2.0)
    cm = CitizenManager(cfg, w, world_seed=1, food_cfg=food_cfg)
    cm.citizens = [
        Citizen(id=1, faction=0, x=5.5, y=5.5,
                state=CitizenState.EATING, age=50.0, lifespan=180.0, repro_cd=0.0,
                facing=Facing.SOUTH, home_x=5.5, home_y=5.5,
                target_x=5.5, target_y=5.5, state_timer=5.0,
                hunger=0.8, food_carried=0),
    ]
    tile_before = float(f.food[5, 5])
    hunger_before = cm.citizens[0].hunger
    cm.tick(0.2, w, f)
    assert cm.citizens[0].hunger < hunger_before
    assert f.food[5, 5] < tile_before


def test_satiation_buffer_lets_hunger_go_negative():
    """A well-fed citizen on an abundant tile gorges past hunger=0 down to
    -satiation_cap, then exits EATING when state_timer expires (not on hunger<=0).

    With satiation_cap=0.5, bite_size=0.2, calorie_per_food=1.0, the citizen
    starting at hunger=0.0 should hit -0.5 within ~3 bites = 3 ticks of 0.2s.
    """
    w = _make_world(tile=int(Tile.GRASS))
    food_cfg = _make_food_cfg(eat_duration=10.0, bite_size=0.2, calorie_per_food=1.0,
                                hunger_rate=0.0, satiation_cap=0.5)
    f = FoodField(food_cfg, w)
    cfg = _make_citizen_cfg(initial_population=0, dying_duration=2.0)
    cm = CitizenManager(cfg, w, world_seed=1, food_cfg=food_cfg)
    cm.citizens = [
        Citizen(id=1, faction=0, x=5.5, y=5.5,
                state=CitizenState.EATING, age=50.0, lifespan=180.0, repro_cd=0.0,
                facing=Facing.SOUTH, home_x=5.5, home_y=5.5,
                target_x=5.5, target_y=5.5, state_timer=5.0,
                hunger=0.0, food_carried=0),
    ]
    # Five ticks of 0.2s — enough to eat past zero into the reserve.
    for _ in range(5):
        cm.tick(0.2, w, f)
    c = cm.citizens[0]
    # Should be at the clamp floor, still in EATING (timer hasn't expired).
    assert c.hunger == -0.5, f"expected hunger==-0.5, got {c.hunger}"
    assert c.state == CitizenState.EATING, f"expected EATING, got {c.state}"


def test_food_carried_field_defaults_zero():
    """P1.5 inventory hook lives in dataclass but is never set."""
    w = _make_world()
    food_cfg = _make_food_cfg()
    cm = CitizenManager(_make_citizen_cfg(), w, world_seed=1, food_cfg=food_cfg)
    for c in cm.citizens:
        assert c.food_carried == 0


def test_p1_backward_compat_no_food_cfg():
    """When food_cfg is None, manager runs in P1 mode (no hunger gate)."""
    w = _make_world(tile=int(Tile.GRASS))
    cm = CitizenManager(_make_citizen_cfg(), w, world_seed=1, food_cfg=None)
    # Should not crash; should report zero hunger stats.
    fed, hungry, starving, avg = cm.hunger_stats(0)
    assert (fed, hungry, starving, avg) == (0, 0, 0, 0.0)
    cm.tick(0.2, w, food=None)
