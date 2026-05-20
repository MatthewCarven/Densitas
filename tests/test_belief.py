"""Tests for the belief field module."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

# Allow running from repo root.
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from densitas.config import BeliefConfig, CitizenConfig
from densitas.belief import BeliefField, N_FACTIONS
from densitas.citizen import Citizen, CitizenState, Facing
from densitas.world import World


def _make_cfg(grid_w: int = 64, grid_h: int = 48,
              amplitude: float = 1.0, blur_passes: int = 2,
              blur_radius: int = 1) -> BeliefConfig:
    return BeliefConfig(
        grid_w=grid_w,
        grid_h=grid_h,
        amplitude=amplitude,
        blur_passes=blur_passes,
        blur_radius=blur_radius,
        recompute_hz=5,
        overlay_alpha_max=180,
    )


class _FakeWorld:
    """Minimal world stub for belief tests (we never query tiles)."""
    width: int = 256
    height: int = 192


def _citizen(id_: int, faction: int, x: float, y: float,
             state: CitizenState = CitizenState.IDLE) -> Citizen:
    return Citizen(
        id=id_, faction=faction, x=x, y=y,
        state=state, age=10.0, lifespan=180.0, repro_cd=0.0,
        facing=Facing.SOUTH, home_x=x, home_y=y,
        target_x=x, target_y=y, state_timer=0.0,
    )


# ---------------------------------------------------------------------------

def test_empty_world_total_is_zero():
    bf = BeliefField(_make_cfg(), _FakeWorld())
    bf.recompute([])
    assert bf.total(0) == 0.0
    assert bf.total(1) == 0.0
    assert bf.peak(0) == 0.0


def test_single_citizen_volume_preserved():
    bf = BeliefField(_make_cfg(), _FakeWorld())
    bf.recompute([_citizen(1, 0, 100.0, 80.0)])
    # Box blur is volume-preserving: total == amplitude * 1 citizen.
    assert bf.total(0) == pytest.approx(1.0, abs=1e-4)
    assert bf.total(1) == 0.0


def test_total_equals_population():
    bf = BeliefField(_make_cfg(), _FakeWorld())
    cs = [_citizen(i, 0, 100.0 + (i % 5), 80.0 + (i // 5))
          for i in range(50)]
    bf.recompute(cs)
    assert bf.total(0) == pytest.approx(50.0, abs=1e-2)


def test_dying_citizens_excluded():
    bf = BeliefField(_make_cfg(), _FakeWorld())
    cs = [
        _citizen(1, 0, 100.0, 80.0, state=CitizenState.IDLE),
        _citizen(2, 0, 100.0, 80.0, state=CitizenState.DYING),
        _citizen(3, 0, 100.0, 80.0, state=CitizenState.DYING),
    ]
    bf.recompute(cs)
    assert bf.total(0) == pytest.approx(1.0, abs=1e-4)


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
    # Faction grids are independent — splatting f0 must not touch f1 grid.
    assert bf.grid(0)[(80 // 4), (100 // 4)] > 0.0
    assert bf.grid(1)[(80 // 4), (100 // 4)] == 0.0


def test_peak_under_citizen_position():
    bf = BeliefField(_make_cfg(), _FakeWorld())
    # Cluster of 9 in a 3x3 block within a single belief cell.
    cs = []
    cid = 0
    for dx in range(3):
        for dy in range(3):
            cid += 1
            cs.append(_citizen(cid, 0, 100.0 + dx * 0.3, 80.0 + dy * 0.3))
    bf.recompute(cs)
    grid = bf.grid(0)
    cx, cy = 100 // 4, 80 // 4
    # Peak should be at or near the cluster cell, definitely not at a far cell.
    assert grid[cy, cx] > 0.0
    assert grid[cy, cx] > grid[0, 0]
    assert grid[cy, cx] == bf.peak(0)


def test_query_matches_grid():
    bf = BeliefField(_make_cfg(), _FakeWorld())
    cs = [_citizen(1, 0, 100.0, 80.0)]
    bf.recompute(cs)
    # query at the citizen tile must equal grid[cy, cx]
    cx, cy = 100 // 4, 80 // 4
    assert bf.query(100, 80, 0) == pytest.approx(bf.grid(0)[cy, cx])


def test_query_clamps_at_edges():
    bf = BeliefField(_make_cfg(), _FakeWorld())
    bf.recompute([_citizen(1, 0, 0.0, 0.0)])
    # Negative coords clamp to cell 0.
    assert bf.query(-100, -100, 0) == pytest.approx(bf.grid(0)[0, 0])
    # Far past world edge clamps to grid_w-1, grid_h-1.
    assert bf.query(99999, 99999, 0) == pytest.approx(bf.grid(0)[-1, -1])


def test_dominant_faction():
    bf = BeliefField(_make_cfg(), _FakeWorld())
    cs = [
        _citizen(1, 0, 100.0, 80.0),
        _citizen(2, 0, 100.0, 80.0),
        _citizen(3, 1, 200.0, 120.0),
    ]
    bf.recompute(cs)
    # Player faction dominates near its cluster.
    assert bf.dominant_faction(100, 80) == 0
    # Rival faction dominates near its cluster.
    assert bf.dominant_faction(200, 120) == 1
    # Tile with no belief: None.
    assert bf.dominant_faction(0, 0) is None


def test_version_bumps_on_recompute():
    bf = BeliefField(_make_cfg(), _FakeWorld())
    v0 = bf.version
    bf.recompute([])
    assert bf.version == v0 + 1
    bf.recompute([_citizen(1, 0, 100.0, 80.0)])
    assert bf.version == v0 + 2


def test_recompute_is_idempotent_for_same_input():
    bf = BeliefField(_make_cfg(), _FakeWorld())
    cs = [_citizen(i, 0, 100.0 + (i % 4), 80.0 + (i // 4)) for i in range(20)]
    bf.recompute(cs)
    grid_a = bf.grid(0).copy()
    bf.recompute(cs)
    grid_b = bf.grid(0).copy()
    np.testing.assert_array_almost_equal(grid_a, grid_b)


def test_zero_blur_passes_skips_blur():
    bf = BeliefField(_make_cfg(blur_passes=0), _FakeWorld())
    bf.recompute([_citizen(1, 0, 100.0, 80.0)])
    # With no blur, the splat stays a single-cell spike of amplitude=1.
    cx, cy = 100 // 4, 80 // 4
    assert bf.grid(0)[cy, cx] == pytest.approx(1.0)
    # No neighbors should have leaked.
    if cx + 1 < bf.grid_w:
        assert bf.grid(0)[cy, cx + 1] == 0.0
    if cy + 1 < bf.grid_h:
        assert bf.grid(0)[cy + 1, cx] == 0.0


def test_n_factions_constant():
    # Document the contract: 2 factions in P2.
    assert N_FACTIONS == 2
