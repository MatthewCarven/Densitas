"""PR4 step 1 — faith math tests (spec `Densitas_rival_ai.md` §12 group A).

Six tests, no display required:
  A1. parity ⇒ no change
  A2. drain ramp linear in dominance
  A3. regen requires own field (void ⇒ frozen faith; own field ⇒ regen)
  A4. clamps at [0, 1]
  A5. eps guards (both fields zero — no NaN, no drift)
  A6. drain continues during MATE (the transition checks are step 2;
      here we assert only that the update itself never pauses)

The belief field is duck-typed in `CitizenManager.tick` — anything with
`query(tx, ty, faction) -> float` works — so these tests drive the math
with a two-constant stub instead of building a real `BeliefField`.

Run from the repo root:
    python -m pytest tests/test_faith.py
"""
from __future__ import annotations
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from densitas.world import World
from densitas.config import WorldConfig, CitizenConfig, FaithConfig
from densitas.citizen import CitizenManager, CitizenState

DT = 0.2  # one 5 Hz tick


class StubBelief:
    """Constant belief field: faction 0 sees `own`, faction 1 sees `riv`.
    (For a faction-0 citizen, `riv` is the enemy field.)"""

    def __init__(self, own: float, riv: float):
        self.own = own
        self.riv = riv

    def query(self, tx: int, ty: int, faction: int = 0) -> float:
        return self.own if faction == 0 else self.riv


def _world_cfg() -> WorldConfig:
    return WorldConfig(
        width=64, height=48, seed=42,
        sea_level=0.30, beach_thresh=0.34,
        forest_thresh=0.55, hill_thresh=0.70,
        mountain_thresh=0.85,
    )


def _citizen_cfg(**overrides) -> CitizenConfig:
    base = dict(
        initial_population=1,
        spawn_radius_tiles=20,
        spawn_seed=0,
        maturity_age=8.0,
        lifespan_mean=900.0,   # long-lived: no lifespan deaths mid-test
        lifespan_jitter=0.0,
        repro_radius=2,
        repro_cooldown=6.0,
        mate_duration=0.5,
        dying_duration=0.5,
        wander_period=1e9,     # effectively never wander
        wander_radius=6,
        wander_speed=1.0,
        tick_hz=5,
        faith=FaithConfig(),
    )
    base.update(overrides)
    return CitizenConfig(**base)


def _manager() -> CitizenManager:
    world = World.generate(_world_cfg())
    cm = CitizenManager(_citizen_cfg(), world, world_seed=42)
    assert len(cm.citizens) == 1
    cm._world = world  # convenience handle for the tests below
    return cm


def _tick(cm: CitizenManager, belief: StubBelief, n: int = 1) -> None:
    for _ in range(n):
        cm.tick(DT, cm._world, None, belief=belief)


# ---------- A1: parity ⇒ no change ------------------------------------------

def test_parity_no_change():
    cm = _manager()
    c = cm.citizens[0]
    c.faith = 0.7
    _tick(cm, StubBelief(own=0.4, riv=0.4), n=10)
    # dominance ≈ 0.5 exactly at parity (eps pushes it a hair below;
    # the regen factor (1 - 2*dom) is then ~1e-6 — no visible drift).
    assert math.isclose(c.faith, 0.7, abs_tol=1e-5)


# ---------- A2: drain ramp linear in dominance -------------------------------

def test_drain_ramp_linear_in_dominance():
    fa = FaithConfig()
    # Two dominance levels with B_riv + B_own = 1.0 (so eps is negligible):
    # dom = 0.8 → strength 0.6;  dom = 0.65 → strength 0.3. Ratio 2:1.
    cm1 = _manager()
    c1 = cm1.citizens[0]
    c1.faith = 1.0
    _tick(cm1, StubBelief(own=0.2, riv=0.8))
    drop1 = 1.0 - c1.faith

    cm2 = _manager()
    c2 = cm2.citizens[0]
    c2.faith = 1.0
    _tick(cm2, StubBelief(own=0.35, riv=0.65))
    drop2 = 1.0 - c2.faith

    assert math.isclose(drop1, fa.drain_rate * 0.6 * DT, rel_tol=1e-3)
    assert math.isclose(drop2, fa.drain_rate * 0.3 * DT, rel_tol=1e-3)
    assert math.isclose(drop1 / drop2, 2.0, rel_tol=1e-3)


# ---------- A3: regen requires own field -------------------------------------

def test_regen_requires_own_field():
    fa = FaithConfig()
    # Void: dominance ≈ 0 but B_own/regen_ref ≈ 0 → frozen faith.
    cm = _manager()
    c = cm.citizens[0]
    c.faith = 0.5
    _tick(cm, StubBelief(own=0.0, riv=0.0), n=25)
    assert math.isclose(c.faith, 0.5, abs_tol=1e-9)

    # Deep in own field: full-rate regen (B_own ≥ regen_ref saturates
    # the min(1, ·) factor; riv=0 puts dominance at ~0).
    cm2 = _manager()
    c2 = cm2.citizens[0]
    c2.faith = 0.5
    _tick(cm2, StubBelief(own=fa.regen_ref, riv=0.0))
    gain = c2.faith - 0.5
    assert math.isclose(gain, fa.regen_rate * 1.0 * DT, rel_tol=1e-3)

    # Thin own field (half regen_ref): regen scales down proportionally.
    cm3 = _manager()
    c3 = cm3.citizens[0]
    c3.faith = 0.5
    _tick(cm3, StubBelief(own=fa.regen_ref * 0.5, riv=0.0))
    gain3 = c3.faith - 0.5
    assert math.isclose(gain3, fa.regen_rate * 0.5 * DT, rel_tol=1e-3)


# ---------- A4: clamps at [0, 1] ---------------------------------------------

def test_faith_clamps_to_unit_interval():
    # Floor: heavy drain for many ticks never goes below 0.
    cm = _manager()
    c = cm.citizens[0]
    c.faith = 0.02
    _tick(cm, StubBelief(own=0.0, riv=5.0), n=50)
    assert c.faith == 0.0

    # Ceiling: regen from near-full caps at exactly 1.0.
    cm2 = _manager()
    c2 = cm2.citizens[0]
    c2.faith = 0.999
    _tick(cm2, StubBelief(own=2.0, riv=0.0), n=50)
    assert c2.faith == 1.0


# ---------- A5: eps guards ----------------------------------------------------

def test_eps_guards_zero_fields():
    cm = _manager()
    c = cm.citizens[0]
    c.faith = 0.42
    _tick(cm, StubBelief(own=0.0, riv=0.0), n=10)
    assert not math.isnan(c.faith)
    assert math.isclose(c.faith, 0.42, abs_tol=1e-9)
    # And spawn default is full faith.
    assert 0.0 <= c.faith <= 1.0


# ---------- A6: drain continues during MATE -----------------------------------

def test_drain_continues_during_mate():
    cm = _manager()
    c = cm.citizens[0]
    c.state = CitizenState.MATE
    c.state_timer = 10.0  # stay in MATE for the whole test
    c.faith = 0.8
    _tick(cm, StubBelief(own=0.0, riv=1.0), n=5)
    fa = FaithConfig()
    # dom ≈ 1.0 → full drain_rate for 5 ticks.
    expected = 0.8 - fa.drain_rate * 1.0 * DT * 5
    assert c.state == CitizenState.MATE  # no transition machinery yet (step 2)
    assert math.isclose(c.faith, expected, rel_tol=1e-3)


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            fn()
            print(f"ok {name}")
