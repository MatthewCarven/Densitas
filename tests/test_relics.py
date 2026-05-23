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
