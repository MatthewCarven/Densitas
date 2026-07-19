"""PR4 step 2 — conversion transition tests (spec `Densitas_rival_ai.md`
§12 group B).

Eight tests, no display required:
  B1. despair is checked before convert (both conditions met ⇒ despair)
  B2. convert is gated on `min_convert_belief` — and that gate is what
      makes despair reachable in a contested-but-weak zone
  B3. ceremony abort path (receiving field collapses mid-rite)
  B4. completion flips faction and resets faith / home
  B5. population + tier accounting follow the flip for free
  B6. newborns start at faith 1.0 with no death cause
  B7. DYING is exempt from the transition checks
  B8. despair reuses the existing death path, with a cause tag

Same duck-typed belief stub as `test_faith.py`, plus a mutable variant
so a test can pull the receiving field out from under a ceremony.

Run from the repo root:
    python -m pytest tests/test_conversion.py
"""
from __future__ import annotations
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from densitas.world import World
from densitas.config import WorldConfig, CitizenConfig, FaithConfig
from densitas.citizen import CitizenManager, CitizenState, tier_for

DT = 0.2  # one 5 Hz tick


class StubBelief:
    """Constant belief field: faction 0 sees `own`, faction 1 sees `riv`.
    Mutable — tests reassign `.own` / `.riv` between ticks."""

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


# ---------- B1: despair is checked before convert ----------------------------

def test_despair_wins_over_convert():
    fa = FaithConfig()
    cm = _manager()
    c = cm.citizens[0]
    # One tick of full-dominance drain (0.016) carries 0.06 past the
    # despair threshold. The rival field is strong, so the convert
    # branch would fire too — order is what we are asserting.
    c.faith = fa.despair_threshold + 0.01
    _tick(cm, StubBelief(own=0.0, riv=1.0))
    assert c.faith <= fa.despair_threshold
    assert c.state == CitizenState.DYING
    assert c.death_cause == "despair"


# ---------- B2: convert gated on min_convert_belief ---------------------------

def test_convert_gated_on_receiving_field():
    fa = FaithConfig()
    cm = _manager()
    c = cm.citizens[0]
    c.faith = 0.20  # already under convert_threshold (0.30)
    thin = StubBelief(own=0.0, riv=fa.min_convert_belief * 0.4)
    _tick(cm, thin)
    # Nothing to convert *to*: no ceremony, and the drain continues.
    assert c.state == CitizenState.IDLE
    assert c.faith < 0.20

    # Keep draining in that contested-but-weak zone and the citizen
    # goes past convert_threshold all the way to despair — which is
    # exactly what the gate is for.
    _tick(cm, thin, n=40)
    assert c.state == CitizenState.DYING
    assert c.death_cause == "despair"


# ---------- B3: ceremony abort path -------------------------------------------

def test_ceremony_aborts_when_receiving_field_collapses():
    fa = FaithConfig()
    cm = _manager()
    c = cm.citizens[0]
    c.faith = 0.20
    belief = StubBelief(own=0.40, riv=0.50)
    _tick(cm, belief)
    assert c.state == CitizenState.CONVERTED
    assert math.isclose(c.state_timer, fa.ceremony_duration - DT, rel_tol=1e-6)

    # Their new god loses the ground mid-rite.
    belief.riv = fa.min_convert_belief * 0.5
    _tick(cm, belief)
    assert c.state == CitizenState.IDLE
    assert c.state_timer == 0.0
    assert c.faction == 0                      # no flip
    assert c.faith < fa.convert_threshold      # faith was not reset
    assert c.faith != fa.convert_faith_reset


# ---------- B4: completion flips faction, resets faith + home -----------------

def test_ceremony_completion_flips_faction():
    fa = FaithConfig()
    cm = _manager()
    c = cm.citizens[0]
    c.faith = 0.20
    c.home_x, c.home_y = 3.5, 3.5              # somewhere else entirely
    tile_x, tile_y = int(c.x), int(c.y)
    belief = StubBelief(own=0.40, riv=0.50)    # gentle drain, safe from despair

    for _ in range(20):
        _tick(cm, belief)
        if c.faction == 1:
            break
    assert c.faction == 1
    assert c.state == CitizenState.IDLE
    assert math.isclose(c.faith, fa.convert_faith_reset, rel_tol=1e-9)
    # Their old life is over: home is the tile they knelt on.
    assert math.isclose(c.home_x, tile_x + 0.5, rel_tol=1e-9)
    assert math.isclose(c.home_y, tile_y + 0.5, rel_tol=1e-9)
    assert c.inspire_bias_until == -1.0


# ---------- B5: population + tier accounting follow the flip ------------------

def test_population_and_tier_follow_the_flip():
    cm = _manager()
    c = cm.citizens[0]
    assert cm.population(0) == 1 and cm.population(1) == 0
    assert tier_for(cm.population(0))[1] == 1   # T0 Whisper
    assert tier_for(cm.population(1))[1] == 0   # pre-T0

    c.faith = 0.20
    belief = StubBelief(own=0.40, riv=0.50)
    for _ in range(20):
        _tick(cm, belief)
        if c.faction == 1:
            break

    assert cm.population(0) == 0 and cm.population(1) == 1
    assert tier_for(cm.population(0))[1] == 0   # the loss is immediate
    assert tier_for(cm.population(1))[1] == 1


# ---------- B6: newborns start at full faith ----------------------------------

def test_newborn_faith_is_full():
    cm = _manager()
    parent = cm.citizens[0]
    parent.faith = 0.11          # a shaky parent makes no difference
    child = cm._spawn_child(parent, cm._world)
    assert child is not None
    assert child.faith == 1.0
    assert child.death_cause == ""
    assert child.faction == parent.faction


# ---------- B7: DYING is exempt from the transition checks --------------------

def test_dying_is_exempt_from_conversion():
    cm = _manager()
    c = cm.citizens[0]
    c.state = CitizenState.DYING
    c.state_timer = 10.0         # outlives the test
    c.faith = 0.0                # rock bottom: both branches would fire
    _tick(cm, StubBelief(own=0.0, riv=1.0), n=5)
    assert c.state == CitizenState.DYING
    assert c.death_cause == ""   # not re-tagged as despair
    assert c.faction == 0


# ---------- B8: despair reuses the existing death path ------------------------

def test_despair_uses_the_existing_death_path():
    cfg_dying = _citizen_cfg().dying_duration
    cm = _manager()
    c = cm.citizens[0]
    c.faith = 0.01
    belief = StubBelief(own=0.0, riv=1.0)
    _tick(cm, belief)
    assert c.state == CitizenState.DYING
    assert math.isclose(c.state_timer, cfg_dying, rel_tol=1e-9)
    assert cm.population(0) == 0          # DYING no longer counts

    _tick(cm, belief)                     # fade begins
    assert 0.0 < c.dying_fade < 1.0

    _tick(cm, belief, n=4)                # 0.5s duration exhausted
    assert cm.citizens == []


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            fn()
            print(f"ok {name}")
