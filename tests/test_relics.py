"""Tests for the Relic data model + RelicManager state machine.

Covers tests 1-4 from `Densitas_relics.md` section 11 (the state-
machine / mutation-validation tests) plus the smoke tests in the
same section. Tests 5-12 cover belief contribution, citizen
attraction, and the shatter rule - those wait for PR3 steps 2-4.

This file complements the existing tests/test_food.py /
tests/test_citizen.py pattern: each test builds a minimal stub
World, constructs the manager, exercises one transition, and
asserts on the visible Relic state.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from densitas.config import RelicConfig
from densitas.relics import (
    Relic, RelicManager, RelicState, ShatterSummary, RELIC_NAMES,
)
from densitas.world import World, Tile


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_relic_cfg(initial_count: int = 3) -> RelicConfig:
    """Defaults match `config.toml` [powers.relic]. Tests that need
    different values pass overrides."""
    return RelicConfig(
        amplitude=20.0,
        place_cooldown=30.0,
        shatter_ratio=1.5,
        shatter_time=8.0,
        attract_radius=8,
        attract_probability=0.4,
        initial_count=initial_count,
    )


def _make_world(width: int = 32, height: int = 24,
                 tile: int = int(Tile.GRASS)) -> World:
    """Stub World filled with a single tile type. Matches the helper
    in tests/test_food.py."""
    tiles = np.full((height, width), tile, dtype=np.uint8)
    heightmap = np.zeros((height, width), dtype=np.float32)
    return World(width=width, height=height, seed=0,
                  tiles=tiles, heightmap=heightmap)


# ---------------------------------------------------------------------------
# Test 1: construction + initial state
# ---------------------------------------------------------------------------

def test_01_manager_initialises_with_n_factions_x_initial_count_available():
    """RelicManager allocates faction*initial_count relics, all AVAILABLE."""
    cfg = _make_relic_cfg(initial_count=3)
    mgr = RelicManager(cfg, n_factions=2)
    assert len(mgr.relics) == 6
    assert all(r.state == RelicState.AVAILABLE for r in mgr.relics)
    # All factions covered, in slot order.
    f0 = mgr.for_faction(0)
    f1 = mgr.for_faction(1)
    assert [r.slot for r in f0] == [0, 1, 2]
    assert [r.slot for r in f1] == [0, 1, 2]


def test_01b_ids_are_stable_and_unique():
    """id = faction * initial_count + slot. Stable across the round."""
    cfg = _make_relic_cfg(initial_count=3)
    mgr = RelicManager(cfg, n_factions=2)
    ids = [r.id for r in mgr.relics]
    assert ids == [0, 1, 2, 3, 4, 5]
    assert len(set(ids)) == len(ids)  # no duplicates


def test_01c_names_come_from_lore_table():
    """Open Eye = Witnesses, Maw = Bites, per Densitas_relics.md."""
    cfg = _make_relic_cfg(initial_count=3)
    mgr = RelicManager(cfg, n_factions=2)
    assert mgr.get(0, 0).name == "The First Witness"
    assert mgr.get(0, 1).name == "The Second Witness"
    assert mgr.get(1, 0).name == "The First Bite"
    assert mgr.get(1, 2).name == "The Third Bite"


def test_01d_unknown_faction_falls_back_to_generic_name():
    """Bumping n_factions past the lore table shouldn't crash."""
    cfg = _make_relic_cfg(initial_count=2)
    mgr = RelicManager(cfg, n_factions=3)  # faction 2 has no lore yet
    r = mgr.get(2, 0)
    assert "f2" in r.name and "s0" in r.name


def test_01e_invalid_construction_rejects():
    """Manager catches obvious misuse early."""
    with pytest.raises(ValueError):
        RelicManager(_make_relic_cfg(), n_factions=0)
    with pytest.raises(ValueError):
        RelicManager(_make_relic_cfg(initial_count=0), n_factions=2)


# ---------------------------------------------------------------------------
# Test 2: place() transitions AVAILABLE -> PLACED
# ---------------------------------------------------------------------------

def test_02_place_transitions_available_to_placed_and_stamps():
    """place() stamps tx/ty/placed_at and flips state."""
    cfg = _make_relic_cfg()
    mgr = RelicManager(cfg, n_factions=2)
    ok, why = mgr.place(0, 0, tx=10, ty=8, world=_make_world(), sim_t=4.25)
    assert ok, why
    r = mgr.get(0, 0)
    assert r.state == RelicState.PLACED
    assert (r.tx, r.ty) == (10, 8)
    assert r.placed_at == pytest.approx(4.25)
    assert r.times_moved == 0           # placement is not a move
    assert r.threat_timer == 0.0


def test_02b_place_rejects_when_already_placed():
    """A second place() on a PLACED slot returns the move-hint reason."""
    cfg = _make_relic_cfg()
    mgr = RelicManager(cfg, n_factions=2)
    w = _make_world()
    mgr.place(0, 0, 5, 5, w, sim_t=0.0)
    ok, why = mgr.place(0, 0, 6, 6, w, sim_t=1.0)
    assert not ok
    assert "already placed" in why


def test_02c_place_rejects_out_of_bounds():
    cfg = _make_relic_cfg()
    mgr = RelicManager(cfg, n_factions=2)
    w = _make_world(width=16, height=16)
    ok, why = mgr.place(0, 0, tx=-1, ty=5, world=w, sim_t=0.0)
    assert not ok
    assert "out of bounds" in why


def test_02d_place_rejects_water():
    """Water tiles fail with the explicit water message."""
    cfg = _make_relic_cfg()
    mgr = RelicManager(cfg, n_factions=2)
    w = _make_world(tile=int(Tile.WATER))
    ok, why = mgr.place(0, 0, 5, 5, w, sim_t=0.0)
    assert not ok
    assert "water" in why


def test_02e_place_rejects_non_walkable_non_water():
    """Mountain isn't water but still rejects."""
    cfg = _make_relic_cfg()
    mgr = RelicManager(cfg, n_factions=2)
    w = _make_world(tile=int(Tile.MOUNTAIN))
    ok, why = mgr.place(0, 0, 5, 5, w, sim_t=0.0)
    assert not ok
    assert "not walkable" in why


def test_02f_place_rejects_same_faction_tile_occupied():
    """Two same-faction relics on the same tile is forbidden."""
    cfg = _make_relic_cfg()
    mgr = RelicManager(cfg, n_factions=2)
    w = _make_world()
    assert mgr.place(0, 0, 5, 5, w, sim_t=0.0)[0]
    ok, why = mgr.place(0, 1, 5, 5, w, sim_t=1.0)
    assert not ok
    assert "same-faction relic" in why


def test_02g_place_allows_other_faction_on_same_tile():
    """Different factions sharing a tile is legal - belief field
    decides the conflict, not the tile slot."""
    cfg = _make_relic_cfg()
    mgr = RelicManager(cfg, n_factions=2)
    w = _make_world()
    assert mgr.place(0, 0, 5, 5, w, sim_t=0.0)[0]
    ok, why = mgr.place(1, 0, 5, 5, w, sim_t=1.0)
    assert ok, why


# ---------------------------------------------------------------------------
# Test 3: move() resets placed_at, increments times_moved, zeroes threat
# ---------------------------------------------------------------------------

def test_03_move_resets_placed_at_increments_times_moved_zeroes_threat():
    """The fade-in clock restarts; times_moved climbs; threat resets."""
    cfg = _make_relic_cfg()
    mgr = RelicManager(cfg, n_factions=2)
    w = _make_world()
    mgr.place(0, 0, 5, 5, w, sim_t=10.0)
    # Simulate a build-up of threat (PR3 step 4 would do this in tick).
    mgr.get(0, 0).threat_timer = 3.5

    ok, why = mgr.move(0, 0, 7, 7, w, sim_t=20.0)
    assert ok, why
    r = mgr.get(0, 0)
    assert (r.tx, r.ty) == (7, 7)
    assert r.placed_at == pytest.approx(20.0)
    assert r.times_moved == 1
    assert r.threat_timer == 0.0


def test_03b_move_rejects_when_not_placed():
    cfg = _make_relic_cfg()
    mgr = RelicManager(cfg, n_factions=2)
    ok, why = mgr.move(0, 0, 5, 5, _make_world(), sim_t=0.0)
    assert not ok
    assert "not placed" in why


def test_03c_multiple_moves_accumulate_times_moved():
    cfg = _make_relic_cfg()
    mgr = RelicManager(cfg, n_factions=2)
    w = _make_world()
    mgr.place(0, 0, 5, 5, w, sim_t=0.0)
    mgr.move(0, 0, 6, 6, w, sim_t=1.0)
    mgr.move(0, 0, 7, 7, w, sim_t=2.0)
    mgr.move(0, 0, 8, 8, w, sim_t=3.0)
    assert mgr.get(0, 0).times_moved == 3


def test_03d_move_to_same_tile_is_valid():
    """A no-op move is legal (the relic stays put but the fade-in
    clock restarts). The same-faction-occupancy check must let the
    moving relic ignore its own tile."""
    cfg = _make_relic_cfg()
    mgr = RelicManager(cfg, n_factions=2)
    w = _make_world()
    mgr.place(0, 0, 5, 5, w, sim_t=0.0)
    ok, why = mgr.move(0, 0, 5, 5, w, sim_t=10.0)
    assert ok, why
    assert mgr.get(0, 0).times_moved == 1
    assert mgr.get(0, 0).placed_at == pytest.approx(10.0)


# ---------------------------------------------------------------------------
# Test 4: retrieve() PLACED -> AVAILABLE
# ---------------------------------------------------------------------------

def test_04_retrieve_transitions_placed_to_available():
    cfg = _make_relic_cfg()
    mgr = RelicManager(cfg, n_factions=2)
    w = _make_world()
    mgr.place(0, 0, 5, 5, w, sim_t=10.0)
    ok, why = mgr.retrieve(0, 0, sim_t=15.0)
    assert ok, why
    r = mgr.get(0, 0)
    assert r.state == RelicState.AVAILABLE
    assert r.placed_at == 0.0
    assert r.threat_timer == 0.0


def test_04b_retrieve_rejects_when_not_placed():
    cfg = _make_relic_cfg()
    mgr = RelicManager(cfg, n_factions=2)
    ok, why = mgr.retrieve(0, 0, sim_t=0.0)
    assert not ok
    assert "nothing to retrieve" in why or "not placed" in why


def test_04c_retrieve_then_replace_preserves_times_moved():
    """Slot identity persists across retrieve / re-place cycles."""
    cfg = _make_relic_cfg()
    mgr = RelicManager(cfg, n_factions=2)
    w = _make_world()
    mgr.place(0, 0, 5, 5, w, sim_t=0.0)
    mgr.move(0, 0, 6, 6, w, sim_t=1.0)
    assert mgr.get(0, 0).times_moved == 1
    mgr.retrieve(0, 0, sim_t=2.0)
    mgr.place(0, 0, 7, 7, w, sim_t=3.0)
    # times_moved persists; place() doesn't reset it.
    assert mgr.get(0, 0).times_moved == 1
    # Subsequent move increments from there.
    mgr.move(0, 0, 8, 8, w, sim_t=4.0)
    assert mgr.get(0, 0).times_moved == 2


# ---------------------------------------------------------------------------
# Shattered-state contract (SHATTERED is set by PR3 step 4; we
# simulate it here by direct field write to verify the no-op rules
# all three mutation methods enforce).
# ---------------------------------------------------------------------------

def test_shattered_relic_rejects_all_mutations():
    cfg = _make_relic_cfg()
    mgr = RelicManager(cfg, n_factions=2)
    r = mgr.get(0, 0)
    r.state = RelicState.SHATTERED   # simulating a post-step-4 outcome

    for method, args in [
        ("place",    (0, 0, 5, 5, _make_world(), 0.0)),
        ("move",     (0, 0, 6, 6, _make_world(), 0.0)),
        ("retrieve", (0, 0, 0.0)),
    ]:
        ok, why = getattr(mgr, method)(*args)
        assert not ok
        assert "shattered" in why


# ---------------------------------------------------------------------------
# Queries
# ---------------------------------------------------------------------------

def test_placed_for_faction_filters_by_state_and_faction():
    cfg = _make_relic_cfg()
    mgr = RelicManager(cfg, n_factions=2)
    w = _make_world()
    mgr.place(0, 0, 1, 1, w, sim_t=0.0)
    mgr.place(0, 2, 3, 3, w, sim_t=0.0)
    mgr.place(1, 1, 5, 5, w, sim_t=0.0)
    f0_placed = mgr.placed_for_faction(0)
    f1_placed = mgr.placed_for_faction(1)
    assert {r.slot for r in f0_placed} == {0, 2}
    assert {r.slot for r in f1_placed} == {1}
    # Other factions' relics never leak into the filter.
    assert all(r.faction == 0 for r in f0_placed)
    assert all(r.faction == 1 for r in f1_placed)


def test_get_raises_on_out_of_range():
    cfg = _make_relic_cfg(initial_count=3)
    mgr = RelicManager(cfg, n_factions=2)
    with pytest.raises(IndexError):
        mgr.get(2, 0)   # only factions 0 and 1
    with pytest.raises(IndexError):
        mgr.get(0, 3)   # only slots 0, 1, 2


# ---------------------------------------------------------------------------
# tick() stub contract: PR3 step 4 will populate _placed_time_accum.
# Verify the stub already does that piece so the eventual shatter
# summary's time_placed_total is honest.
# ---------------------------------------------------------------------------

def test_tick_accumulates_placed_time_for_placed_relics():
    cfg = _make_relic_cfg()
    mgr = RelicManager(cfg, n_factions=2)
    w = _make_world()
    mgr.place(0, 0, 5, 5, w, sim_t=0.0)
    # 50 ticks of 0.2s = 10s in PLACED state.
    for _ in range(50):
        result = mgr.tick(0.2, belief=None, citizens=None, sim_t=0.0)
        assert result == []
    assert mgr.get(0, 0)._placed_time_accum == pytest.approx(10.0)
    # AVAILABLE relics don't accumulate.
    assert mgr.get(0, 1)._placed_time_accum == 0.0


def test_shatter_at_stub_returns_empty():
    """Hook for P5 disasters; lands later. Until then: no-op."""
    cfg = _make_relic_cfg()
    mgr = RelicManager(cfg, n_factions=2)
    w = _make_world()
    mgr.place(0, 0, 5, 5, w, sim_t=0.0)
    out = mgr.shatter_at(tx=5, ty=5, radius=10, sim_t=1.0)
    assert out == []
    # The relic itself is unaffected by the stub.
    assert mgr.get(0, 0).state == RelicState.PLACED

# ===========================================================================
# PR3 step 2: belief contribution via BeliefField._scatter_relics.
# Tests #5, #6, #10 from `Densitas_relics.md` section 11, plus smoke.
# ===========================================================================

from densitas.config import BeliefConfig
from densitas.belief import BeliefField


def _make_belief_cfg(blur_passes: int = 0, blur_radius: int = 1,
                     grid_w: int = 32, grid_h: int = 24,
                     amplitude: float = 1.0) -> BeliefConfig:
    """BeliefConfig with blur disabled so tests can assert exact per-cell
    contributions. The default `amplitude` here is for the *citizen*
    splat (irrelevant for these tests since we pass no citizens); the
    relic amplitude lives on RelicConfig and arrives via relic_cfg.

    Mirrors tests/test_belief.py::_make_cfg but defaults blur_passes=0.
    """
    return BeliefConfig(
        grid_w=grid_w,
        grid_h=grid_h,
        amplitude=amplitude,
        blur_passes=blur_passes,
        blur_radius=blur_radius,
        recompute_hz=5,
        overlay_alpha_max=180,
    )


def _make_belief_field(world: World, relic_cfg=None,
                        blur_passes: int = 0) -> BeliefField:
    """BeliefField wired for relic contribution. blur_passes=0 is the
    default so tests assert raw scatter values; pass blur_passes>0 if
    you want to exercise the bleed."""
    return BeliefField(
        _make_belief_cfg(blur_passes=blur_passes),
        world,
        relic_cfg=relic_cfg,
    )


# ---------------------------------------------------------------------------
# Spec test #5: full amplitude after place_cooldown elapses.
# ---------------------------------------------------------------------------

def test_05_relic_contributes_full_amplitude_after_cooldown():
    """After place_cooldown sim-seconds, the field at the relic's cell
    equals exactly `amplitude`. No blur, no citizens, no other relics
    - so the contribution lands cleanly in one cell."""
    cfg = _make_relic_cfg()       # amplitude=20, place_cooldown=30
    mgr = RelicManager(cfg, n_factions=2)
    w = _make_world(width=64, height=48)
    mgr.place(0, 0, tx=10, ty=8, world=w, sim_t=0.0)

    bf = _make_belief_field(w, relic_cfg=cfg)
    # sim_t exactly one cooldown after placement -> weight = amplitude.
    bf.recompute(citizens=[], relics=mgr.relics, sim_t=30.0)

    # Map the relic's world tile to its belief cell. With width=64,
    # grid_w=32: tiles_per_cell_x = 2 -> tx=10 maps to cx=5. Same for y.
    tpcx = bf.tiles_per_cell_x
    tpcy = bf.tiles_per_cell_y
    cx, cy = 10 // tpcx, 8 // tpcy
    assert bf.field[0, cy, cx] == pytest.approx(cfg.amplitude)
    # Other faction should not have any contribution at this cell.
    assert bf.field[1, cy, cx] == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# Spec test #6: linear fade-in - half cooldown gives half amplitude.
# ---------------------------------------------------------------------------

def test_06_relic_fade_in_is_linear_during_cooldown():
    """At sim_t = 0.5 * cooldown after place, weight = 0.5 * amplitude."""
    cfg = _make_relic_cfg()
    mgr = RelicManager(cfg, n_factions=2)
    w = _make_world(width=64, height=48)
    mgr.place(0, 0, tx=10, ty=8, world=w, sim_t=0.0)

    bf = _make_belief_field(w, relic_cfg=cfg)
    bf.recompute(citizens=[], relics=mgr.relics,
                  sim_t=cfg.place_cooldown * 0.5)

    tpcx = bf.tiles_per_cell_x
    tpcy = bf.tiles_per_cell_y
    cx, cy = 10 // tpcx, 8 // tpcy
    assert bf.field[0, cy, cx] == pytest.approx(cfg.amplitude * 0.5)


def test_06b_relic_fade_in_clamps_at_one():
    """After the cooldown, contribution stays at amplitude - the
    `min(1.0, elapsed/cd)` clamp means longer elapsed times don't keep
    growing the weight."""
    cfg = _make_relic_cfg()
    mgr = RelicManager(cfg, n_factions=2)
    w = _make_world(width=64, height=48)
    mgr.place(0, 0, tx=10, ty=8, world=w, sim_t=0.0)

    bf = _make_belief_field(w, relic_cfg=cfg)
    # 5x the cooldown.
    bf.recompute(citizens=[], relics=mgr.relics,
                  sim_t=cfg.place_cooldown * 5.0)

    tpcx = bf.tiles_per_cell_x
    tpcy = bf.tiles_per_cell_y
    cx, cy = 10 // tpcx, 8 // tpcy
    assert bf.field[0, cy, cx] == pytest.approx(cfg.amplitude)


# ---------------------------------------------------------------------------
# Spec test #10: SHATTERED contributes nothing.
# ---------------------------------------------------------------------------

def test_10_shattered_relic_does_not_contribute():
    """The shatter ceremony's punch comes from the belief vanishing.
    Simulate by direct state mutation (PR3 step 4 will fire shatter
    through the tick loop)."""
    cfg = _make_relic_cfg()
    mgr = RelicManager(cfg, n_factions=2)
    w = _make_world(width=64, height=48)
    mgr.place(0, 0, tx=10, ty=8, world=w, sim_t=0.0)
    bf = _make_belief_field(w, relic_cfg=cfg)

    # First: full amplitude after cooldown.
    bf.recompute(citizens=[], relics=mgr.relics, sim_t=30.0)
    tpcx, tpcy = bf.tiles_per_cell_x, bf.tiles_per_cell_y
    cx, cy = 10 // tpcx, 8 // tpcy
    assert bf.field[0, cy, cx] == pytest.approx(cfg.amplitude)

    # Now shatter.
    mgr.get(0, 0).state = RelicState.SHATTERED
    bf.recompute(citizens=[], relics=mgr.relics, sim_t=31.0)
    assert bf.field[0, cy, cx] == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# Smoke tests
# ---------------------------------------------------------------------------

def test_relic_just_placed_contributes_zero_one_tick():
    """elapsed == 0 -> weight 0. Fade-in starts the next tick."""
    cfg = _make_relic_cfg()
    mgr = RelicManager(cfg, n_factions=2)
    w = _make_world(width=64, height=48)
    mgr.place(0, 0, tx=10, ty=8, world=w, sim_t=7.5)

    bf = _make_belief_field(w, relic_cfg=cfg)
    bf.recompute(citizens=[], relics=mgr.relics, sim_t=7.5)  # same instant

    tpcx, tpcy = bf.tiles_per_cell_x, bf.tiles_per_cell_y
    cx, cy = 10 // tpcx, 8 // tpcy
    assert bf.field[0, cy, cx] == pytest.approx(0.0)


def test_available_relic_does_not_contribute():
    """AVAILABLE = no on-map presence -> no belief contribution."""
    cfg = _make_relic_cfg()
    mgr = RelicManager(cfg, n_factions=2)
    w = _make_world(width=64, height=48)
    bf = _make_belief_field(w, relic_cfg=cfg)

    bf.recompute(citizens=[], relics=mgr.relics, sim_t=100.0)
    assert bf.field.sum() == pytest.approx(0.0)


def test_relics_recompute_signature_back_compatible():
    """The old recompute(citizens) signature still works. Critical
    for tests/test_belief.py and any caller that doesn't yet pass
    relics through."""
    cfg = _make_relic_cfg()
    w = _make_world(width=64, height=48)
    bf = _make_belief_field(w, relic_cfg=cfg)
    # No relics, no sim_t - should not raise and field stays zero.
    bf.recompute(citizens=[])
    assert bf.field.sum() == pytest.approx(0.0)


def test_two_placed_relics_scatter_to_distinct_cells():
    """Multiple PLACED relics each contribute independently."""
    cfg = _make_relic_cfg()
    mgr = RelicManager(cfg, n_factions=2)
    w = _make_world(width=64, height=48)
    # Place two same-faction relics far apart so they land in different cells.
    mgr.place(0, 0, tx=5, ty=5, world=w, sim_t=0.0)
    mgr.place(0, 1, tx=50, ty=40, world=w, sim_t=0.0)
    bf = _make_belief_field(w, relic_cfg=cfg)
    bf.recompute(citizens=[], relics=mgr.relics, sim_t=30.0)

    tpcx, tpcy = bf.tiles_per_cell_x, bf.tiles_per_cell_y
    assert bf.field[0, 5 // tpcy, 5 // tpcx] == pytest.approx(cfg.amplitude)
    assert bf.field[0, 40 // tpcy, 50 // tpcx] == pytest.approx(cfg.amplitude)


def test_recompute_without_relic_cfg_skips_scatter():
    """If BeliefField was built without a relic_cfg, passing relics=
    into recompute is a no-op (no AttributeError)."""
    cfg = _make_relic_cfg()
    mgr = RelicManager(cfg, n_factions=2)
    w = _make_world(width=64, height=48)
    mgr.place(0, 0, tx=10, ty=8, world=w, sim_t=0.0)

    bf = _make_belief_field(w, relic_cfg=None)
    bf.recompute(citizens=[], relics=mgr.relics, sim_t=30.0)
    # No crash. Field stays zero because the scatter was skipped.
    assert bf.field.sum() == pytest.approx(0.0)

# ===========================================================================
# PR3 step 3: citizen attractors via CitizenManager.sync_attractors_from_relics
# + _pick_wander_target attractor branch. Tests #9 and #11 from spec section
# 11 plus smoke.
# ===========================================================================

import math

from densitas.config import CitizenConfig, FoodConfig, FoodBiomeConfig
from densitas.citizen import (
    CitizenManager, CitizenState, Citizen, Facing,
)


def _make_citizen_cfg_for_attractors(**overrides) -> CitizenConfig:
    """CitizenConfig sized for attractor tests. wander_radius=5 keeps the
    random-wander region tightly around home so we can place a relic far
    from home and isolate the attractor contribution to the hit count."""
    defaults = dict(
        initial_population=1, spawn_radius_tiles=2, spawn_seed=0,
        maturity_age=8.0, lifespan_mean=180.0, lifespan_jitter=40.0,
        repro_radius=2, repro_cooldown=5.0,
        mate_duration=0.5, dying_duration=2.0,
        wander_period=2.0, wander_radius=5, wander_speed=1.0,
        tick_hz=5,
    )
    defaults.update(overrides)
    return CitizenConfig(**defaults)


def _make_food_cfg_minimal() -> FoodConfig:
    """A FoodConfig that exists but does nothing interesting - we only
    pass it so the CitizenManager doesn't take its P1-backward-compat
    path that disables hunger / forage."""
    biome = FoodBiomeConfig(
        forest_initial=1.0, forest_regen=0.01,
        grass_initial=1.0,  grass_regen=0.01,
        beach_initial=1.0,  beach_regen=0.01,
        hill_initial=1.0,   hill_regen=0.01,
        holy_initial=1.0,   holy_regen=0.01,
    )
    return FoodConfig(
        hunger_rate=0.005, forage_threshold=0.4,
        repro_hunger_threshold=0.3, starve_hunger=1.0,
        eat_amount=0.2, eat_duration=1.0,
        bite_size=0.2, calorie_per_food=1.0, satiation_cap=0.5,
        forage_radius_tiles=8, min_forage_food=0.5,
        overlay_alpha_max=160, biome=biome,
    )


def _make_lone_citizen_mgr(world: World, relic_cfg: RelicConfig,
                            home: tuple[int, int] = (20, 20)
                            ) -> CitizenManager:
    """Build a CitizenManager with exactly one citizen at the given
    home tile. We override the initial spawn (random) by overwriting
    the citizens list after construction.
    """
    cm = CitizenManager(
        _make_citizen_cfg_for_attractors(),
        world,
        world_seed=1,
        food_cfg=_make_food_cfg_minimal(),
        relic_cfg=relic_cfg,
    )
    # Replace the auto-spawned citizens with one we control. Use
    # only the required fields plus inspire_bias_until (so the
    # P3 PR1 branch doesn't pick up stale bias).
    cm.citizens = [Citizen(
        id=0, faction=0,
        x=float(home[0]), y=float(home[1]),
        state=CitizenState.IDLE,
        age=10.0, lifespan=200.0, repro_cd=0.0,
        facing=Facing.SOUTH,
        home_x=float(home[0]), home_y=float(home[1]),
        target_x=float(home[0]), target_y=float(home[1]),
        inspire_bias_until=-1.0,
    )]
    return cm


# ---------------------------------------------------------------------------
# Spec test #9: ~40% of wander picks land in the relic disc.
# ---------------------------------------------------------------------------

def test_09_attractor_pulls_about_forty_percent_of_wander_picks():
    """With a single PLACED relic far from the citizen's wander region,
    the fraction of `_pick_wander_target` results that land within the
    relic's `attract_radius` should be approximately the configured
    attract_probability (0.4). Tolerance +/-5% per the spec.

    The relic is placed 30 tiles away from home with wander_radius=5,
    so random-wander picks never accidentally land in the relic disc.
    Any hit-in-disc is therefore an attractor pull.
    """
    cfg = _make_relic_cfg()  # attract_radius=8, attract_probability=0.4
    w = _make_world(width=80, height=60)

    mgr = RelicManager(cfg, n_factions=2)
    relic_tx, relic_ty = 50, 30
    mgr.place(0, 0, tx=relic_tx, ty=relic_ty, world=w, sim_t=0.0)

    cm = _make_lone_citizen_mgr(w, relic_cfg=cfg, home=(20, 20))
    cm.sync_attractors_from_relics(mgr.relics, cfg.attract_radius)
    assert len(cm.attractors) == 1

    c = cm.citizens[0]
    n = 1000
    hits = 0
    for _ in range(n):
        tx, ty = cm._pick_wander_target(c, w)
        # True (Euclidean) disc per spec - polar sampling implies it.
        if math.hypot(tx - relic_tx, ty - relic_ty) <= cfg.attract_radius:
            hits += 1

    ratio = hits / n
    # Spec tolerance: +/-5%. attract_probability=0.4 -> expect 0.35..0.45.
    assert 0.35 <= ratio <= 0.45, (
        f"attractor hit ratio {ratio:.3f} outside expected 0.35..0.45"
    )


# ---------------------------------------------------------------------------
# Spec test #11: FORAGE citizens ignore attractors (hunger trumps devotion).
# ---------------------------------------------------------------------------

def test_11_forage_state_ignores_attractors():
    """A citizen in the FORAGE state must skip the attractor branch.
    Hits in the relic disc should be near zero (only via wander-region
    overlap, which we engineer to be empty)."""
    cfg = _make_relic_cfg()
    w = _make_world(width=80, height=60)

    mgr = RelicManager(cfg, n_factions=2)
    relic_tx, relic_ty = 50, 30
    mgr.place(0, 0, tx=relic_tx, ty=relic_ty, world=w, sim_t=0.0)

    cm = _make_lone_citizen_mgr(w, relic_cfg=cfg, home=(20, 20))
    cm.sync_attractors_from_relics(mgr.relics, cfg.attract_radius)

    c = cm.citizens[0]
    c.state = CitizenState.FORAGE   # hunger trumps devotion

    n = 1000
    hits = 0
    for _ in range(n):
        tx, ty = cm._pick_wander_target(c, w)
        if math.hypot(tx - relic_tx, ty - relic_ty) <= cfg.attract_radius:
            hits += 1

    # With home 30 tiles from relic and wander_radius=5, random wander
    # picks should NEVER land within 8 of the relic. Allow at most 1
    # hit for any RNG weirdness on the edge of the search loop.
    assert hits <= 1, (
        f"FORAGE citizen pulled toward attractor: {hits}/1000 hits"
    )


# ---------------------------------------------------------------------------
# Smoke tests
# ---------------------------------------------------------------------------

def test_no_attractors_falls_back_to_random_wander():
    """Empty `attractors` list -> behaves exactly like P1 random wander."""
    cfg = _make_relic_cfg()
    w = _make_world(width=80, height=60)
    cm = _make_lone_citizen_mgr(w, relic_cfg=cfg, home=(40, 30))
    assert cm.attractors == []  # untouched by sync (no PLACED relics)

    c = cm.citizens[0]
    n = 200
    for _ in range(n):
        tx, ty = cm._pick_wander_target(c, w)
        # Every pick stays within wander_radius (5) of home Chebyshev.
        assert abs(tx - c.home_x) <= cm.cfg.wander_radius
        assert abs(ty - c.home_y) <= cm.cfg.wander_radius


def test_other_faction_relic_does_not_attract():
    """A faction-1 relic must not pull a faction-0 citizen."""
    cfg = _make_relic_cfg()
    w = _make_world(width=80, height=60)

    mgr = RelicManager(cfg, n_factions=2)
    relic_tx, relic_ty = 50, 30
    # faction 1 PLACED relic.
    mgr.place(1, 0, tx=relic_tx, ty=relic_ty, world=w, sim_t=0.0)

    cm = _make_lone_citizen_mgr(w, relic_cfg=cfg, home=(20, 20))
    cm.sync_attractors_from_relics(mgr.relics, cfg.attract_radius)
    assert len(cm.attractors) == 1   # synced, but for the wrong faction

    c = cm.citizens[0]  # faction 0
    n = 500
    hits = 0
    for _ in range(n):
        tx, ty = cm._pick_wander_target(c, w)
        if math.hypot(tx - relic_tx, ty - relic_ty) <= cfg.attract_radius:
            hits += 1
    # Same engineering as test #11: far home + small wander_radius => 0.
    assert hits <= 1, (
        f"other-faction relic pulled citizen: {hits}/500 hits"
    )


def test_sync_filters_to_placed_only():
    """AVAILABLE and SHATTERED relics must not appear in attractors."""
    cfg = _make_relic_cfg()
    w = _make_world(width=80, height=60)

    mgr = RelicManager(cfg, n_factions=2)
    # 3 relics: one PLACED, one AVAILABLE, one we'll SHATTER.
    mgr.place(0, 0, tx=10, ty=10, world=w, sim_t=0.0)
    # slot 1 stays AVAILABLE
    mgr.place(0, 2, tx=50, ty=30, world=w, sim_t=0.0)
    mgr.get(0, 2).state = RelicState.SHATTERED

    cm = _make_lone_citizen_mgr(w, relic_cfg=cfg, home=(20, 20))
    cm.sync_attractors_from_relics(mgr.relics, cfg.attract_radius)
    assert len(cm.attractors) == 1
    assert cm.attractors[0][:2] == (10, 10)  # only the PLACED one


def test_sync_idempotent_with_re_call():
    """Re-syncing after a state change reflects the new state."""
    cfg = _make_relic_cfg()
    w = _make_world(width=80, height=60)
    mgr = RelicManager(cfg, n_factions=2)
    mgr.place(0, 0, tx=10, ty=10, world=w, sim_t=0.0)

    cm = _make_lone_citizen_mgr(w, relic_cfg=cfg, home=(20, 20))
    cm.sync_attractors_from_relics(mgr.relics, cfg.attract_radius)
    assert len(cm.attractors) == 1

    # Retrieve and re-sync - should drop to zero attractors.
    mgr.retrieve(0, 0, sim_t=5.0)
    cm.sync_attractors_from_relics(mgr.relics, cfg.attract_radius)
    assert cm.attractors == []


def test_no_relic_cfg_disables_attractors_even_with_synced_list():
    """If CitizenManager was built without relic_cfg, attractors are
    ignored in _pick_wander_target even after sync populates the list.
    Defensive: no AttributeError when relic_cfg is None."""
    cfg = _make_relic_cfg()
    w = _make_world(width=80, height=60)

    mgr = RelicManager(cfg, n_factions=2)
    mgr.place(0, 0, tx=50, ty=30, world=w, sim_t=0.0)

    cm = CitizenManager(
        _make_citizen_cfg_for_attractors(), w, world_seed=1,
        food_cfg=_make_food_cfg_minimal(),
        relic_cfg=None,                          # the key bit
    )
    cm.citizens = [Citizen(
        id=0, faction=0, x=20.0, y=20.0,
        state=CitizenState.IDLE,
        age=10.0, lifespan=200.0, repro_cd=0.0,
        facing=Facing.SOUTH,
        home_x=20.0, home_y=20.0,
        target_x=20.0, target_y=20.0,
        inspire_bias_until=-1.0,
    )]
    cm.sync_attractors_from_relics(mgr.relics, cfg.attract_radius)
    assert len(cm.attractors) == 1  # sync still populates the list

    c = cm.citizens[0]
    n = 200
    hits = 0
    for _ in range(n):
        tx, ty = cm._pick_wander_target(c, w)
        if math.hypot(tx - 50, ty - 30) <= cfg.attract_radius:
            hits += 1
    # With relic_cfg=None the attractor branch is skipped entirely.
    assert hits <= 1, (
        f"None relic_cfg should disable attractor branch; got {hits}/200"
    )


def test_attractors_pick_uniformly_with_multiple_relics():
    """Two relics, both close enough to the citizen's home that the
    random-wander region can hit neither - each should get roughly half
    the attractor pulls."""
    cfg = _make_relic_cfg()
    w = _make_world(width=120, height=80)

    mgr = RelicManager(cfg, n_factions=2)
    # Two relics 40 tiles either side of home.
    mgr.place(0, 0, tx=20, ty=40, world=w, sim_t=0.0)
    mgr.place(0, 1, tx=100, ty=40, world=w, sim_t=0.0)

    cm = _make_lone_citizen_mgr(w, relic_cfg=cfg, home=(60, 40))
    cm.sync_attractors_from_relics(mgr.relics, cfg.attract_radius)

    c = cm.citizens[0]
    n = 2000
    hits_a = hits_b = 0
    for _ in range(n):
        tx, ty = cm._pick_wander_target(c, w)
        if math.hypot(tx - 20, ty - 40) <= cfg.attract_radius:
            hits_a += 1
        elif math.hypot(tx - 100, ty - 40) <= cfg.attract_radius:
            hits_b += 1
    total_hits = hits_a + hits_b
    # Expect each to be ~0.2 of all picks (0.4 attractor prob / 2 relics).
    # Allow a wide tolerance since the test runs few samples.
    assert total_hits >= int(n * 0.30), (
        f"total attractor hits {total_hits} suspiciously low"
    )
    # And the two should be within ~30% of each other.
    if hits_a > 0 and hits_b > 0:
        ratio = min(hits_a, hits_b) / max(hits_a, hits_b)
        assert ratio >= 0.65, (
            f"attractor split too uneven: {hits_a} vs {hits_b} (ratio {ratio:.2f})"
        )

# ===========================================================================
# PR3 step 4: shatter rule + ShatterSummary population.
# Tests #7, #8, #12 from `Densitas_relics.md` section 11, plus smoke.
# ===========================================================================

import types

from densitas.relics import ShatterSummary


class _FakeBelief:
    """Stub belief field for shatter tests.

    Implements just the API surface `RelicManager.tick` reaches for:
      - `.n_factions` attribute
      - `.query(tx, ty, faction=0) -> float`

    Real `BeliefField` rebuilds its grid from citizens + relics on each
    recompute, which is overkill for testing the shatter math. Keying a
    dict on (tx, ty, faction) lets each test express exactly the belief
    pressure that matters.
    """
    def __init__(self, n_factions: int = 2,
                 query_map: dict | None = None) -> None:
        self.n_factions = n_factions
        self._q = dict(query_map or {})

    def query(self, tx: int, ty: int, faction: int = 0) -> float:
        return float(self._q.get((int(tx), int(ty), int(faction)), 0.0))

    def set(self, tx: int, ty: int, faction: int, value: float) -> None:
        self._q[(int(tx), int(ty), int(faction))] = float(value)


def _fake_citizens(n_player_near: int = 0, n_rival_near: int = 0,
                    relic_tx: int = 0, relic_ty: int = 0):
    """Build a SimpleNamespace with a `.citizens` list - that's the only
    thing `_build_shatter_summary` reads on the CitizenManager.
    Citizens are placed exactly on the relic tile so they all count
    within the radius-8 disc."""
    cits = []
    for i in range(n_player_near):
        cits.append(types.SimpleNamespace(
            x=float(relic_tx), y=float(relic_ty), faction=0,
        ))
    for i in range(n_rival_near):
        cits.append(types.SimpleNamespace(
            x=float(relic_tx), y=float(relic_ty), faction=1,
        ))
    return types.SimpleNamespace(citizens=cits)


# ---------------------------------------------------------------------------
# Spec test #7: sustained rival belief above ratio fires SHATTERED.
# ---------------------------------------------------------------------------

def test_07_sustained_rival_belief_triggers_shatter():
    """Hold rival belief at >shatter_ratio * player for shatter_time sec;
    the relic must transition PLACED -> SHATTERED with a populated
    ShatterSummary on the tick that crosses the threshold."""
    cfg = _make_relic_cfg()      # shatter_ratio=1.5, shatter_time=8.0
    mgr = RelicManager(cfg, n_factions=2)
    w = _make_world(width=64, height=48)
    mgr.place(0, 0, tx=20, ty=15, world=w, sim_t=0.0)

    # Rival belief 10x player at the relic tile - well above 1.5x.
    bf = _FakeBelief(n_factions=2, query_map={
        (20, 15, 0): 1.0,
        (20, 15, 1): 10.0,
    })
    citizens = _fake_citizens(n_player_near=3, n_rival_near=7,
                                relic_tx=20, relic_ty=15)

    summaries: list[ShatterSummary] = []
    sim_t = 0.0
    # 5 Hz tick -> 0.2 dt. 8.0 / 0.2 = 40 ticks to reach shatter_time.
    for tick in range(60):
        sim_t += 0.2
        out = mgr.tick(0.2, bf, citizens, sim_t=sim_t)
        if out:
            summaries.extend(out)
            break

    r = mgr.get(0, 0)
    assert r.state == RelicState.SHATTERED
    assert len(summaries) == 1
    s = summaries[0]
    # All 12 fields populated and sane.
    assert s.relic_id == r.id
    assert s.faction == 0
    assert s.name == "The First Witness"
    assert (s.tx, s.ty) == (20, 15)
    assert s.sim_t > 0.0
    assert s.local_belief_player == pytest.approx(1.0)
    assert s.local_belief_rival == pytest.approx(10.0)
    assert s.player_citizens_within_8 == 3
    assert s.rival_citizens_within_8 == 7
    assert s.time_placed_total > 0.0   # accumulator running
    assert s.times_moved == 0


# ---------------------------------------------------------------------------
# Spec test #8: rival incursion shorter than shatter_time -> threat decays.
# ---------------------------------------------------------------------------

def test_08_short_incursion_decays_no_shatter():
    """Rival belief above ratio for 4 sec, then drops to 0. The threat
    accumulator (4.0) recovers at 2x rate (-0.4/0.2-dt) and would zero
    out in ~2 sim_sec of safety. Run 6 more sim_sec safe (well past
    recovery) and assert: still PLACED, threat_timer == 0."""
    cfg = _make_relic_cfg()
    mgr = RelicManager(cfg, n_factions=2)
    w = _make_world(width=64, height=48)
    mgr.place(0, 0, tx=20, ty=15, world=w, sim_t=0.0)

    bf = _FakeBelief(n_factions=2)
    citizens = _fake_citizens(relic_tx=20, relic_ty=15)

    # Phase 1: 4 sim_sec of incursion (20 ticks at 0.2s).
    bf.set(20, 15, 0, 1.0)
    bf.set(20, 15, 1, 10.0)
    sim_t = 0.0
    for _ in range(20):
        sim_t += 0.2
        out = mgr.tick(0.2, bf, citizens, sim_t=sim_t)
        assert out == []   # not enough to shatter yet
    assert mgr.get(0, 0).threat_timer == pytest.approx(4.0)

    # Phase 2: rival pulls back. 30 ticks (6 sim_sec) of safety - way
    # more than the 2 sim_sec recovery needs.
    bf.set(20, 15, 1, 0.0)
    for _ in range(30):
        sim_t += 0.2
        out = mgr.tick(0.2, bf, citizens, sim_t=sim_t)
        assert out == []
    r = mgr.get(0, 0)
    assert r.state == RelicState.PLACED
    assert r.threat_timer == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# Spec test #12: move during fade-in resets the belief-weight clock.
# ---------------------------------------------------------------------------

def test_12_move_during_fade_in_restarts_belief_weight_clock():
    """Per spec section 11 / 7: at sim_t=15 (half cooldown=30) the
    belief weight is 0.5 * amplitude. Move the relic, and at sim_t=20
    the weight is (20-15)/30 * amplitude = (1/6) * amplitude - NOT
    (20-0)/30 = 2/3 * amplitude. The fade-in restarts."""
    cfg = _make_relic_cfg()
    mgr = RelicManager(cfg, n_factions=2)
    w = _make_world(width=64, height=48)
    mgr.place(0, 0, tx=10, ty=8, world=w, sim_t=0.0)

    bf = _make_belief_field(w, relic_cfg=cfg)

    # t=15: half cooldown, weight = 0.5 * amplitude.
    bf.recompute(citizens=[], relics=mgr.relics, sim_t=15.0)
    tpcx, tpcy = bf.tiles_per_cell_x, bf.tiles_per_cell_y
    cx, cy = 10 // tpcx, 8 // tpcy
    assert bf.field[0, cy, cx] == pytest.approx(cfg.amplitude * 0.5)

    # Move at t=15. tx/ty change, placed_at resets to 15.0.
    ok, _ = mgr.move(0, 0, tx=12, ty=10, world=w, sim_t=15.0)
    assert ok

    # t=20: 5 sec into the new placement, weight = 5/30 * amplitude.
    bf.recompute(citizens=[], relics=mgr.relics, sim_t=20.0)
    new_cx, new_cy = 12 // tpcx, 10 // tpcy
    expected = cfg.amplitude * (5.0 / cfg.place_cooldown)
    assert bf.field[0, new_cy, new_cx] == pytest.approx(expected)
    # Old tile is empty.
    assert bf.field[0, cy, cx] == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# Smoke tests
# ---------------------------------------------------------------------------

def test_shattered_relic_does_not_double_shatter_next_tick():
    """Once SHATTERED, the relic stops being considered by tick().
    Subsequent ticks return [] - no duplicate ShatterSummary."""
    cfg = _make_relic_cfg()
    mgr = RelicManager(cfg, n_factions=2)
    w = _make_world(width=64, height=48)
    mgr.place(0, 0, tx=20, ty=15, world=w, sim_t=0.0)

    bf = _FakeBelief(n_factions=2, query_map={
        (20, 15, 0): 1.0,
        (20, 15, 1): 10.0,
    })
    citizens = _fake_citizens(relic_tx=20, relic_ty=15)

    # Force shatter.
    sim_t = 0.0
    fired = []
    for _ in range(60):
        sim_t += 0.2
        out = mgr.tick(0.2, bf, citizens, sim_t=sim_t)
        fired.extend(out)
    assert len(fired) == 1   # exactly one shatter, ever

    # 20 more ticks: still no new shatter even though belief pressure
    # is still set on the (now SHATTERED) tile.
    for _ in range(20):
        sim_t += 0.2
        out = mgr.tick(0.2, bf, citizens, sim_t=sim_t)
        assert out == []


def test_tick_with_none_belief_preserves_stub_contract():
    """The step-1 stub-test expects tick(None, None, sim_t) to advance
    `_placed_time_accum` without crashing. That contract must continue
    to hold after the shatter wiring lands - other tests (and any
    P3-PR1 powers tests that don't have a belief field handy) rely
    on it."""
    cfg = _make_relic_cfg()
    mgr = RelicManager(cfg, n_factions=2)
    w = _make_world(width=64, height=48)
    mgr.place(0, 0, tx=10, ty=8, world=w, sim_t=0.0)
    for _ in range(50):
        out = mgr.tick(0.2, belief=None, citizens=None, sim_t=0.0)
        assert out == []
    assert mgr.get(0, 0)._placed_time_accum == pytest.approx(10.0)
    assert mgr.get(0, 0).state == RelicState.PLACED


def test_balanced_pressure_does_not_shatter():
    """Rival belief exactly at the shatter_ratio threshold should NOT
    trigger - the rule is strict greater-than. Edge case."""
    cfg = _make_relic_cfg()   # shatter_ratio=1.5
    mgr = RelicManager(cfg, n_factions=2)
    w = _make_world(width=64, height=48)
    mgr.place(0, 0, tx=20, ty=15, world=w, sim_t=0.0)

    # Rival at exactly 1.5x player.
    bf = _FakeBelief(n_factions=2, query_map={
        (20, 15, 0): 2.0,
        (20, 15, 1): 3.0,
    })
    citizens = _fake_citizens(relic_tx=20, relic_ty=15)

    sim_t = 0.0
    for _ in range(60):   # 12 sim_sec, well past shatter_time
        sim_t += 0.2
        out = mgr.tick(0.2, bf, citizens, sim_t=sim_t)
        assert out == []
    assert mgr.get(0, 0).state == RelicState.PLACED


def test_shatter_summary_counts_only_within_radius_8():
    """Citizens beyond radius 8 of the relic are not counted in the
    summary. Citizens AT the radius edge are counted (<= 8.0)."""
    cfg = _make_relic_cfg()
    mgr = RelicManager(cfg, n_factions=2)
    w = _make_world(width=64, height=48)
    mgr.place(0, 0, tx=20, ty=15, world=w, sim_t=0.0)

    bf = _FakeBelief(n_factions=2, query_map={
        (20, 15, 0): 1.0,
        (20, 15, 1): 10.0,
    })

    # Mix of in-radius and out-of-radius citizens.
    cits = [
        types.SimpleNamespace(x=20.0, y=15.0,  faction=0),  # on relic, IN
        types.SimpleNamespace(x=23.0, y=18.0,  faction=0),  # ~4.24 dist, IN
        types.SimpleNamespace(x=28.0, y=23.0,  faction=0),  # ~11.3 dist, OUT
        types.SimpleNamespace(x=20.0, y=23.0,  faction=1),  # 8.0 dist, IN
        types.SimpleNamespace(x=20.0, y=25.0,  faction=1),  # 10.0 dist, OUT
        types.SimpleNamespace(x=50.0, y=40.0,  faction=1),  # far, OUT
    ]
    citizens = types.SimpleNamespace(citizens=cits)

    sim_t = 0.0
    summary = None
    for _ in range(60):
        sim_t += 0.2
        out = mgr.tick(0.2, bf, citizens, sim_t=sim_t)
        if out:
            summary = out[0]
            break

    assert summary is not None
    assert summary.player_citizens_within_8 == 2  # two faction-0 inside
    assert summary.rival_citizens_within_8 == 1   # one faction-1 inside


def test_shatter_persists_position_and_summary_post_shatter():
    """After SHATTERED, tx/ty/shatter_at/shatter_summary are all kept
    so PR3 step 7's crack animation and the summary panel can read
    them. State stays SHATTERED forever (no resurrection)."""
    cfg = _make_relic_cfg()
    mgr = RelicManager(cfg, n_factions=2)
    w = _make_world(width=64, height=48)
    mgr.place(0, 0, tx=20, ty=15, world=w, sim_t=0.0)

    bf = _FakeBelief(n_factions=2, query_map={
        (20, 15, 0): 1.0,
        (20, 15, 1): 10.0,
    })
    citizens = _fake_citizens(relic_tx=20, relic_ty=15)

    sim_t = 0.0
    for _ in range(60):
        sim_t += 0.2
        if mgr.tick(0.2, bf, citizens, sim_t=sim_t):
            break

    r = mgr.get(0, 0)
    assert r.state == RelicState.SHATTERED
    assert (r.tx, r.ty) == (20, 15)        # position retained
    assert r.shatter_at > 0.0              # populated
    assert r.shatter_summary is not None
    # No mutation method can resurrect a SHATTERED relic - already
    # covered by test_shattered_relic_rejects_all_mutations, but
    # sanity-check one more time post-real-shatter.
    ok, why = mgr.place(0, 0, 5, 5, w, sim_t=999.0)
    assert not ok
    assert "shattered" in why
