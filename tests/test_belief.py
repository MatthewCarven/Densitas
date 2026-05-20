"""Tests for the belief field module."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from densitas.config import BeliefConfig
from densitas.belief import BeliefField, N_FACTIONS
from densitas.citizen import Citizen, CitizenState, Facing


def _make_cfg(grid_w: int = 64, grid_h: int = 48,
              amplitude: float = 1.0, blur_passes: int = 2,
              blur_radius: int = 1) -> BeliefConfig:
    return BeliefConfig(
        grid_w=grid_w, grid_h=grid_h,
        amplitude=amplitude, blur_passes=blur_passes, blur_radius=blur_radius,
        recompute_hz=5, overlay_alpha_max=180,
    )


class _FakeWorld:
    width: int = 256
    height: int = 192


def _citizen(id_: int, faction: int, x: float, y: float,
             state: CitizenState = CitizenState.IDLE,
             state_timer: float = 0.0) -> Citizen:
    return Citizen(
        id=id_, faction=faction, x=x, y=y,
        state=state, age=10.0, lifespan=180.0, repro_cd=0.0,
        facing=Facing.SOUTH, home_x=x, home_y=y,
        target_x=x, target_y=y, state_timer=state_timer,
        hunger=0.0, food_carried=0,
    )


def test_empty_world_total_is_zero():
    bf = BeliefField(_make_cfg(), _FakeWorld())
    bf.recompute([])
    assert bf.total(0) == 0.0
    assert bf.total(1) == 0.0


def test_single_citizen_volume_preserved():
    bf = BeliefField(_make_cfg(), _FakeWorld())
    bf.recompute([_citizen(1, 0, 100.0, 80.0)])
    assert bf.total(0) == pytest.approx(1.0, abs=1e-4)


def test_total_equals_population():
    bf = BeliefField(_make_cfg(), _FakeWorld())
    cs = [_citizen(i, 0, 100.0 + (i % 5), 80.0 + (i // 5)) for i in range(50)]
    bf.recompute(cs)
    assert bf.total(0) == pytest.approx(50.0, abs=1e-2)


def test_dying_at_full_timer_contributes_full_amplitude():
    """P1.5: DYING citizen with full state_timer == amplitude (no fade yet)."""
    dd = 2.0
    bf = BeliefField(_make_cfg(), _FakeWorld(), dying_duration=dd)
    bf.recompute([_citizen(1, 0, 100.0, 80.0,
                            state=CitizenState.DYING, state_timer=dd)])
    assert bf.total(0) == pytest.approx(1.0, abs=1e-4)


def test_dying_fades_to_half_at_midpoint():
    """P1.5: at state_timer == dying_duration/2, weight is 0.5 amplitude."""
    dd = 2.0
    bf = BeliefField(_make_cfg(), _FakeWorld(), dying_duration=dd)
    bf.recompute([_citizen(1, 0, 100.0, 80.0,
                            state=CitizenState.DYING, state_timer=dd / 2)])
    assert bf.total(0) == pytest.approx(0.5, abs=1e-3)


def test_dying_at_zero_timer_contributes_nothing():
    dd = 2.0
    bf = BeliefField(_make_cfg(), _FakeWorld(), dying_duration=dd)
    bf.recompute([_citizen(1, 0, 100.0, 80.0,
                            state=CitizenState.DYING, state_timer=0.0)])
    assert bf.total(0) == 0.0


def test_faction_isolation():
    bf = BeliefField(_make_cfg(), _FakeWorld())
    cs = [
        _citizen(1, 0, 100.0, 80.0),
        _citizen(2, 0, 100.0, 80.0),
        _citizen(3, 1, 200.0, 120.0),
    ]
    bf.recompute(cs)
    assert bf.total(0) == pytest.approx(2.0, abs=1e-4)
    assert bf.total(1) == pytest.approx(1.0, abs=1e-4)


def test_peak_under_citizen_position():
    bf = BeliefField(_make_cfg(), _FakeWorld())
    cs = []
    cid = 0
    for dx in range(3):
        for dy in range(3):
            cid += 1
            cs.append(_citizen(cid, 0, 100.0 + dx * 0.3, 80.0 + dy * 0.3))
    bf.recompute(cs)
    grid = bf.grid(0)
    cx, cy = 100 // 4, 80 // 4
    assert grid[cy, cx] > 0.0
    assert grid[cy, cx] == bf.peak(0)


def test_query_matches_grid():
    bf = BeliefField(_make_cfg(), _FakeWorld())
    bf.recompute([_citizen(1, 0, 100.0, 80.0)])
    cx, cy = 100 // 4, 80 // 4
    assert bf.query(100, 80, 0) == pytest.approx(bf.grid(0)[cy, cx])


def test_query_clamps_at_edges():
    bf = BeliefField(_make_cfg(), _FakeWorld())
    bf.recompute([_citizen(1, 0, 0.0, 0.0)])
    assert bf.query(-100, -100, 0) == pytest.approx(bf.grid(0)[0, 0])
    assert bf.query(99999, 99999, 0) == pytest.approx(bf.grid(0)[-1, -1])


def test_dominant_faction():
    bf = BeliefField(_make_cfg(), _FakeWorld())
    cs = [
        _citizen(1, 0, 100.0, 80.0),
        _citizen(2, 0, 100.0, 80.0),
        _citizen(3, 1, 200.0, 120.0),
    ]
    bf.recompute(cs)
    assert bf.dominant_faction(100, 80) == 0
    assert bf.dominant_faction(200, 120) == 1
    assert bf.dominant_faction(0, 0) is None


def test_version_bumps_on_recompute():
    bf = BeliefField(_make_cfg(), _FakeWorld())
    v0 = bf.version
    bf.recompute([])
    assert bf.version == v0 + 1


def test_recompute_is_idempotent_for_same_input():
    bf = BeliefField(_make_cfg(), _FakeWorld())
    cs = [_citizen(i, 0, 100.0 + (i % 4), 80.0 + (i // 4)) for i in range(20)]
    bf.recompute(cs)
    grid_a = bf.grid(0).copy()
    bf.recompute(cs)
    np.testing.assert_array_almost_equal(grid_a, bf.grid(0))


def test_zero_blur_passes_skips_blur():
    bf = BeliefField(_make_cfg(blur_passes=0), _FakeWorld())
    bf.recompute([_citizen(1, 0, 100.0, 80.0)])
    cx, cy = 100 // 4, 80 // 4
    assert bf.grid(0)[cy, cx] == pytest.approx(1.0)


def test_n_factions_constant():
    assert N_FACTIONS == 2
