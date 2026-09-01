"""PR4 step 4 - rival AI skeleton tests (spec `Densitas_rival_ai.md` §12
group D).

Eight tests, no display required:
  D1. cadence honours `period` - nothing early, exactly one on the beat
  D2. `difficulty` scales the cadence and nothing else
  D3. `period` floors at one logic tick however high difficulty goes
  D4. two identically-seeded runs produce identical decision logs
  D5. senses: own / enemy / seam argmax against hand-built grids
  D6. senses: centroids against hand-placed citizens, and the
      push-point anchor on an uncontested map
  D7. the decision ring caps at 64, dropping oldest first
  D8. the Maw never scores BLESS, even with `w_bless` forced to 1.0

Run from the repo root:
    python -m pytest tests/test_rival_ai.py
"""
from __future__ import annotations

import dataclasses
import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from densitas.belief import BeliefField
from densitas.citizen import CitizenManager
from densitas.config import (
    BeliefConfig, CitizenConfig, FoodBiomeConfig, FoodConfig, PowerConfig,
    RelicConfig, RivalConfig, WorldConfig,
)
from densitas.food import FoodField
from densitas.powers import PowerKind, PowerSystem, god_key_for
from densitas.relics import RelicManager
from densitas.rival_ai import (
    GOD_FORBIDS, PERSONALITIES, SCORED_INTENTS, AIPersonality, DecisionRecord,
    Intent, RivalAI, argmax_cell, centroid, make_rival_ai,
)
from densitas.world import Tile, World


# -- fixtures ----------------------------------------------------------------

def _world_cfg(seed=42):
    return WorldConfig(
        width=32, height=24, seed=seed,
        sea_level=0.30, beach_thresh=0.34, forest_thresh=0.55,
        hill_thresh=0.70, mountain_thresh=0.85,
    )


def _grass_world(seed=42):
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


def _relic_cfg():
    return RelicConfig(
        amplitude=20.0, place_cooldown=30.0,
        shatter_ratio=1.5, shatter_time=8.0,
        attract_radius=8, attract_probability=0.4,
        initial_count=3,
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
        relic=_relic_cfg(),
    )


class _Env:
    """Everything `RivalAI.tick` needs, built small and deterministic."""

    def __init__(self, seed=42, initial_pop=8):
        self.world = _grass_world(seed=seed)
        cc = _citizen_cfg(initial=initial_pop)
        self.cm = CitizenManager(cc, self.world, world_seed=seed,
                                 food_cfg=_food_cfg(),
                                 relic_cfg=_relic_cfg())
        self.food = FoodField(_food_cfg(), self.world)
        self.belief = BeliefField(_belief_cfg(), self.world,
                                  dying_duration=cc.dying_duration,
                                  relic_cfg=_relic_cfg())
        self.belief.recompute(self.cm.citizens)
        self.relics = RelicManager(_relic_cfg(), n_factions=2)
        self.ps = PowerSystem(_power_cfg(), n_factions=2)
        self.sim_t = 0.0

    def kwargs(self):
        return dict(sim_t=self.sim_t, citizens=self.cm, belief=self.belief,
                    relic_mgr=self.relics, power_system=self.ps,
                    world=self.world)

    def advance(self, dt):
        """One logic tick of the parts the AI senses."""
        self.ps.tick(dt, self.cm, self.sim_t)
        self.food.recompute(dt, effects=self.ps.effects)
        self.cm.tick(dt, self.world, self.food, belief=self.belief)
        self.belief.recompute(self.cm.citizens, relics=self.relics.relics,
                              sim_t=self.sim_t)
        self.relics.tick(dt, self.belief, self.cm, sim_t=self.sim_t)

    def stuff(self, n, faction, at=(5, 5)):
        """Inject N synthetic citizens so tier gates move."""
        cx, cy = at
        for _ in range(n):
            self.cm.citizens.append(self.cm._make_citizen(
                faction=faction, x=float(cx) + 0.5, y=float(cy) + 0.5,
                age=10.0,
            ))


def _rival_cfg(**kw):
    return dataclasses.replace(RivalConfig(), **kw)


def _ai(*, personality="zealot", faction=1, seed=0, **cfg_kw):
    return make_rival_ai(_rival_cfg(personality=personality, **cfg_kw),
                         _power_cfg(), faction=faction, seed=seed)


# -- D1: cadence honours period ----------------------------------------------

def test_d1_cadence_honours_period():
    env = _Env()
    ai = _ai()
    assert ai.period == pytest.approx(2.0)     # base 2.0 / difficulty 1.0

    dt = 0.2                                   # one logic tick at 5 Hz
    fired = [ai.tick(dt, **env.kwargs()) for _ in range(9)]
    assert all(r is None for r in fired), "decided before the period elapsed"
    assert ai.decisions == 0

    rec = ai.tick(dt, **env.kwargs())
    assert isinstance(rec, DecisionRecord), "missed the beat at t=2.0"
    assert ai.decisions == 1

    # Second period: nine quiet ticks, then exactly one more decision.
    for _ in range(9):
        assert ai.tick(dt, **env.kwargs()) is None
    assert ai.tick(dt, **env.kwargs()) is not None
    assert ai.decisions == 2


# -- D2: difficulty scales cadence -------------------------------------------

def test_d2_difficulty_scales_cadence():
    dt = 0.2

    fast = _ai(difficulty=2.0)
    assert fast.period == pytest.approx(1.0)
    env = _Env()
    for _ in range(20):
        fast.tick(dt, **env.kwargs())
    assert fast.decisions == 20 * dt / 1.0

    slow = _ai(difficulty=0.5)
    assert slow.period == pytest.approx(4.0)
    env2 = _Env()
    for _ in range(20):
        slow.tick(dt, **env2.kwargs())
    assert slow.decisions == 1                 # 4.0 sim_s of a 4.0 s period

    # Cadence is the ONLY thing difficulty touches (pillar 2): the two
    # brains are otherwise the same parameter block.
    assert fast.p == slow.p


# -- D3: period floors at one logic tick -------------------------------------

def test_d3_period_floors_at_one_logic_tick():
    dt = 0.2
    frantic = _ai(difficulty=100.0)
    assert frantic.period < dt                 # 2.0 / 100 = 0.02

    env = _Env()
    for _ in range(5):
        assert frantic.tick(dt, **env.kwargs()) is not None
    assert frantic.decisions == 5, "a decision tick cannot subdivide a logic tick"


# -- D4: determinism ----------------------------------------------------------

def _log_signature(ai):
    return [(round(r.sim_t, 6), r.intent, r.target, round(r.score, 9),
             tuple((i, round(s, 9)) for i, s in r.top3))
            for r in ai.log]


def test_d4_identical_seeds_give_identical_logs():
    dt = 0.2
    runs = []
    for _ in range(2):
        env = _Env(seed=42)
        env.stuff(20, faction=1, at=(20, 12))
        env.ps.pool[1] = 200.0
        ai = _ai(seed=7, difficulty=5.0)       # period 0.4 -> plenty of decisions
        for _ in range(60):
            env.advance(dt)
            env.sim_t += dt
            ai.tick(dt, **env.kwargs())
        runs.append((_log_signature(ai), ai.decisions))

    assert runs[0][1] == runs[1][1] > 0
    assert runs[0][0] == runs[1][0], "same seed + same state must decide alike"

    # A different ai_seed must actually change the stream, or the test above
    # would pass on a broken RNG that always returns the same draw.
    env = _Env(seed=42)
    env.stuff(20, faction=1, at=(20, 12))
    env.ps.pool[1] = 200.0
    other = _ai(seed=99, difficulty=5.0)
    for _ in range(60):
        env.advance(dt)
        env.sim_t += dt
        other.tick(dt, **env.kwargs())
    assert _log_signature(other) != runs[0][0]


# -- D5: senses, argmax over hand-built grids --------------------------------

def test_d5_senses_argmax_on_hand_built_grids():
    env = _Env()
    ai = _ai()                                 # faction 1, enemy 0

    env.belief.field[:] = 0.0
    # Own (faction 1) peaks at (cx=12, cy=3); enemy (faction 0) at (2, 8).
    # Both are non-zero at (7, 5), which is where their product peaks.
    env.belief.field[1, 3, 12] = 9.0
    env.belief.field[0, 8, 2] = 8.0
    env.belief.field[1, 5, 7] = 4.0
    env.belief.field[0, 5, 7] = 5.0            # product 20 > any other cell

    s = ai.sense(sim_t=0.0, citizens=env.cm, belief=env.belief,
                 relic_mgr=env.relics, power_system=env.ps)

    assert s.own_peak_cell == (12, 3)
    assert s.enemy_peak_cell == (2, 8)
    assert s.seam_peak_cell == (7, 5)
    assert s.seam_peak_value == pytest.approx(20.0)
    assert s.peak_own == pytest.approx(9.0)
    assert s.peak_enemy == pytest.approx(8.0)
    # Overlap is the shared mass against the best possible overlap.
    assert s.seam_overlap == pytest.approx(20.0 / (9.0 * 8.0))

    # The bare helper agrees, and reports (cx, cy) not numpy's (row, col).
    assert argmax_cell(env.belief.grid(1)) == (12, 3)
    assert argmax_cell(np.zeros((0, 0))) == (0, 0)


# -- D6: senses, centroids ----------------------------------------------------

def test_d6_senses_centroids():
    env = _Env()
    ai = _ai()                                 # faction 1, enemy 0

    env.cm.citizens.clear()
    for x, y in ((10.0, 10.0), (20.0, 10.0), (10.0, 20.0), (20.0, 20.0)):
        env.cm.citizens.append(env.cm._make_citizen(faction=0, x=x, y=y,
                                                    age=10.0))
    for x, y in ((3.0, 4.0), (5.0, 8.0)):
        env.cm.citizens.append(env.cm._make_citizen(faction=1, x=x, y=y,
                                                    age=10.0))

    s = ai.sense(sim_t=0.0, citizens=env.cm, belief=env.belief,
                 relic_mgr=env.relics, power_system=env.ps)

    assert s.enemy_centroid == pytest.approx((15.0, 15.0))
    assert s.own_centroid == pytest.approx((4.0, 6.0))
    assert s.pop_own == 2 and s.pop_enemy == 4

    # With no seam (these two clusters do not overlap at all), the relic
    # push point must anchor on our own centroid rather than on the seam
    # argmax's (0, 0) tie-break, which is a map corner and not an anchor.
    assert s.seam_peak_value == 0.0
    push = ai.push_point_cell(s)
    own_cell = (int(4.0 / env.belief.tiles_per_cell_x),
                int(6.0 / env.belief.tiles_per_cell_y))
    enemy_cell = (15.0 / env.belief.tiles_per_cell_x,
                  15.0 / env.belief.tiles_per_cell_y)
    t = ai.p.relic_forward_bias
    assert push == (round(own_cell[0] + (enemy_cell[0] - own_cell[0]) * t),
                    round(own_cell[1] + (enemy_cell[1] - own_cell[1]) * t))
    assert push != (0, 0)

    # An extinct faction has no centroid at all - callers must not get a
    # (0, 0) that reads as "the top-left corner".
    env.cm.citizens = [c for c in env.cm.citizens if c.faction == 0]
    assert centroid(env.cm, 1) is None
    assert centroid(env.cm, 0) == pytest.approx((15.0, 15.0))


# -- D7: decision ring caps ---------------------------------------------------

def test_d7_decision_ring_caps_at_64():
    dt = 0.2
    env = _Env()
    ai = _ai(difficulty=100.0)                 # one decision per logic tick
    assert ai.RING == 64

    for _ in range(70):
        env.sim_t += dt
        ai.tick(dt, **env.kwargs())

    assert ai.decisions == 70
    assert len(ai.log) == 64, "ring buffer must bound its own memory"
    # Oldest-first eviction: the surviving window is the last 64 decisions,
    # so entry 0 is decision 7 (1-indexed), at sim_t = 7 * dt.
    assert ai.log[0].sim_t == pytest.approx(7 * dt)
    assert ai.log[-1].sim_t == pytest.approx(70 * dt)


# -- D8: the god mask ---------------------------------------------------------

def _bless_utility(faction, w_bless, *, own_peak, enemy_peak):
    """Score BLESS for one god with the fields stacked in its favour."""
    env = _Env()
    ai = RivalAI(faction, dataclasses.replace(PERSONALITIES["zealot"],
                                              w_bless=w_bless),
                 _rival_cfg(), _power_cfg(), seed=0)
    enemy = ai.enemy
    env.stuff(30, faction=faction, at=(5, 5))      # T2: BLESS needs tier 2
    env.ps.pool[faction] = 500.0                   # and 10 belief

    env.belief.field[:] = 0.0
    env.belief.field[faction, 4, 4] = own_peak
    env.belief.field[enemy, 6, 9] = enemy_peak

    s = ai.sense(sim_t=0.0, citizens=env.cm, belief=env.belief,
                 relic_mgr=env.relics, power_system=env.ps)
    u = ai.utilities(s, env.ps, env.cm, env.world)
    return ai, s, u


def test_d8_maw_never_blesses():
    # Control: the Open Eye, facing the denser god, wants to bless.
    eye, s_eye, u_eye = _bless_utility(0, w_bless=1.0,
                                       own_peak=1.0, enemy_peak=5.0)
    assert eye.god_key == "open_eye"
    assert PowerKind.BLESS not in eye.forbidden
    assert s_eye.tier_own >= 2 and s_eye.pool_own >= 10.0
    assert u_eye[Intent.CAST_BLESS] > 0.0, "control case must be feasible"

    # The Maw, in the identical shortfall, scores exactly zero - and the
    # only difference is the mask.
    maw, s_maw, u_maw = _bless_utility(1, w_bless=1.0,
                                       own_peak=1.0, enemy_peak=5.0)
    assert maw.god_key == "maw"
    assert PowerKind.BLESS in maw.forbidden
    assert s_maw.tier_own >= 2 and s_maw.pool_own >= 10.0
    assert u_maw[Intent.CAST_BLESS] == 0.0
    assert maw.score(u_maw)[Intent.CAST_BLESS] == 0.0

    # And it never surfaces as a decision, however long it runs.
    dt = 0.2
    env = _Env()
    env.stuff(30, faction=1, at=(5, 5))
    env.ps.pool[1] = 500.0
    env.belief.field[:] = 0.0
    env.belief.field[1, 4, 4] = 1.0
    env.belief.field[0, 6, 9] = 5.0
    ai = RivalAI(1, dataclasses.replace(PERSONALITIES["zealot"], w_bless=1.0),
                 _rival_cfg(difficulty=100.0), _power_cfg(), seed=3)
    for _ in range(40):
        env.sim_t += dt
        ai.tick(dt, **env.kwargs())
    assert ai.decisions == 40
    assert all(r.intent is not Intent.CAST_BLESS for r in ai.log)

    # The mask is keyed by god, not by faction number, so it survives any
    # future re-numbering of the factions.
    assert set(GOD_FORBIDS) == {"maw", "open_eye"}
    assert god_key_for(1) == "maw"


# -- housekeeping the above leans on -----------------------------------------

def test_d0_presets_and_factory_are_well_formed():
    """Not one of the spec's eight - a guard rail for the other seven,
    which all assume the presets and the factory hold their shape."""
    assert set(PERSONALITIES) == {"zealot", "steward", "trickster"}
    for name, p in PERSONALITIES.items():
        assert isinstance(p, AIPersonality) and p.name == name
        for intent in SCORED_INTENTS:
            assert p.weight(intent) >= 0.0
        assert p.weight(Intent.IDLE) == 0.0
        assert 0.0 <= p.relic_forward_bias <= 1.0
        assert 0.0 <= p.retrieve_panic <= 1.0

    z = make_rival_ai(_rival_cfg(personality="zealot"), _power_cfg(),
                      faction=1, seed=0)
    assert z.p is PERSONALITIES["zealot"] and z.faction == 1 and z.enemy == 0

    with pytest.raises(ValueError):
        make_rival_ai(_rival_cfg(personality="zelot"), _power_cfg())
