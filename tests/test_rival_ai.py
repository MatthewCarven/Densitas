"""PR4 steps 4-5 - rival AI tests (spec `Densitas_rival_ai.md` §12
groups D and E).

Group D - the skeleton. Eight tests, no display required:
  D1. cadence honours `period` - nothing early, exactly one on the beat
  D2. `difficulty` scales the cadence and nothing else
  D3. `period` floors at one logic tick however high difficulty goes
  D4. two identically-seeded runs produce identical decision logs
  D5. senses: own / enemy / seam argmax against hand-built grids
  D6. senses: centroids against hand-placed citizens, and the
      push-point anchor on an uncontested map
  D7. the decision ring caps at 64, dropping oldest first
  D8. the Maw never scores BLESS, even with `w_bless` forced to 1.0

Plus D0, a labelled guard rail over the presets and factory that the
eight above lean on.

Group E - the same-rules property, 500 decision ticks of a contested map
with a forced-aggressive brain and the casts live:
  E1. every cast the AI reached for passed `can_cast` first
  E2. the belief pool never goes negative, and was really spent
  E3. the Maw never blesses under load, with an Open Eye control

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
from densitas.relics import RelicManager, RelicState
from densitas.rival_ai import (
    GOD_FORBIDS, PERSONALITIES, SCORED_INTENTS, AIPersonality, DecisionRecord,
    Intent, RivalAI, argmax_cell, centroid, dist, make_rival_ai,
)
from densitas.world import Tile, World, is_walkable_tile


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

    def kwargs(self, *, food=True):
        """`food=False` drops the food field, for the callers that only
        want the scoring pass."""
        kw = dict(sim_t=self.sim_t, citizens=self.cm, belief=self.belief,
                  relic_mgr=self.relics, power_system=self.ps,
                  world=self.world)
        if food:
            kw["food"] = self.food
        return kw

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


# The 32x24 test world is an eighth of the real map, so the chain's
# world-scale distances (spec'd for 256x192) shrink with it. Any test that
# expects the rival to actually plant a flag here uses this.
_SMALL_MAP = dict(relic_step_tiles=10.0, relic_standoff_tiles=3.0,
                  relic_spread_tiles=4.0, move_deadband_tiles=2.0,
                  drift_ref_tiles=8.0)


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

    # With no flags planted, the chain anchors on our own centroid and
    # steps straight at theirs - never on the seam argmax's (0, 0)
    # tie-break, which is a map corner and not an anchor.
    assert s.seam_peak_value == 0.0
    small = RivalAI(1, ai.p, _rival_cfg(**_SMALL_MAP), _power_cfg(), seed=0)
    _sense_only(small, env)
    anchor, u, reach = small.push_reach(s)
    assert anchor == pytest.approx((4.0, 6.0))
    assert u == pytest.approx((11.0 / dist((4, 6), (15, 15)),
                               9.0 / dist((4, 6), (15, 15))))
    assert 0.0 < reach <= small.step_tiles * small.p.relic_forward_bias
    assert small.push_point_cell(s) != (0, 0)

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


# -- E: the same-rules property (spec §12 group E) ----------------------------

# All weights maxed, no reserve, no idle floor: whatever the board offers,
# this brain reaches for it. The point is that maximum aggression still
# cannot get around `can_cast`.
_RELIC_INTENTS = {Intent.RELIC_PLACE, Intent.RELIC_MOVE,
                  Intent.RELIC_RETRIEVE}

_AGGRESSIVE = dataclasses.replace(
    PERSONALITIES["zealot"], name="forced-aggressive",
    w_curse=1.0, w_hunger_pang=1.0, w_lower=1.0, w_bless=1.0,
    w_relic_place=1.0, w_relic_move=1.0, w_relic_retrieve=1.0,
    spend_floor=0.0, idle_floor=0.0,
)


class _CastSpy:
    """Wraps `cast_or_queue` and checks `can_cast` immediately before every
    call - i.e. that the AI only ever reaches for a legal cast."""

    def __init__(self, env, faction):
        self.env = env
        self.faction = faction
        self.calls = []          # (kind, tx, ty, can_cast_ok, reason)
        self._inner = env.ps.cast_or_queue
        env.ps.cast_or_queue = self

    def __call__(self, kind, faction, tx, ty, citizens, world, food, belief,
                 sim_t, suppress_scripture=False):
        ok, why = self.env.ps.can_cast(kind, faction, tx, ty, citizens, world)
        self.calls.append((kind, tx, ty, ok, why))
        return self._inner(kind, faction, tx, ty, citizens, world, food,
                           belief, sim_t, suppress_scripture)


def _property_run(personality=_AGGRESSIVE, faction=1, ticks=500, seed=11,
                  start_pool=100.0):
    """500 decision ticks of a contested map, casts live."""
    dt = 0.2
    env = _Env(initial_pop=12)
    # Put the rival beside the player cluster so the seam is real and the
    # chain has a direction to push, and give both sides tier 2 so the
    # costed powers are on the menu at all.
    env.stuff(12, faction=1, at=(24, 14))
    env.ps.pool[0] = start_pool
    env.ps.pool[1] = start_pool
    spy = _CastSpy(env, faction)
    ai = RivalAI(faction, personality,
                 _rival_cfg(difficulty=100.0, **_SMALL_MAP),
                 _power_cfg(), seed=seed)     # period floors to one tick

    pool_min = min(env.ps.pool)
    for _ in range(ticks):
        env.advance(dt)
        env.sim_t += dt
        ai.tick(dt, **env.kwargs())
        pool_min = min(pool_min, min(env.ps.pool))
    return ai, env, spy, pool_min


def test_e1_every_executed_cast_passed_can_cast():
    ai, env, spy, _ = _property_run()

    assert ai.decisions == 500
    assert spy.calls, "the property run must actually cast something"
    bad = [c for c in spy.calls if not c[3]]
    assert not bad, f"reached for {len(bad)} illegal cast(s): {bad[:3]}"
    assert ai.casts == len(spy.calls)
    assert ai.refused == 0, "a scored-feasible cast was refused at the verb"

    # Relic verbs went live in step 6, so the same-rules property has to
    # cover them too: each one that won a decision went through the real
    # RelicManager API and was accepted.
    relic_records = [r for r in ai.log if r.intent in _RELIC_INTENTS]
    assert ai.relic_acts > 0, "the property run must exercise relic verbs too"
    assert all(r.executed for r in relic_records),         "a relic verb was refused after scoring feasible"


def test_e2_pool_never_goes_negative():
    ai, env, spy, pool_min = _property_run()

    assert ai.casts > 0
    assert pool_min >= 0.0, f"pool dipped to {pool_min}"
    assert all(p >= 0.0 for p in env.ps.pool)

    # And the spending was real, not a no-op that trivially never debits:
    # the aggressive brain outspends its own regen at some point in the run.
    assert pool_min < 100.0, "nothing was ever actually paid for"


def test_e3_maw_never_blesses_under_load():
    """The property-run twin of D8, which tests the same rule as a unit."""
    ai, env, spy, _ = _property_run(faction=1)      # faction 1 == the Maw

    assert ai.god_key == "maw"
    assert ai.p.w_bless == 1.0, "the mask must be what stops it, not the weight"
    assert PowerKind.BLESS not in {c[0] for c in spy.calls}
    assert all(r.intent is not Intent.CAST_BLESS for r in ai.log)

    # The control: the same brain as the Open Eye does bless, so the run is
    # not simply one where BLESS was never affordable.
    eye, _env, eye_spy, _ = _property_run(faction=0)
    assert eye.god_key == "open_eye"
    assert PowerKind.BLESS in {c[0] for c in eye_spy.calls}


# -- F: relic intents (spec §12 group F) --------------------------------------

def _sense_only(ai, env):
    return ai.sense(sim_t=env.sim_t, citizens=env.cm, belief=env.belief,
                    relic_mgr=env.relics, power_system=env.ps)


def test_f1_chain_steps_from_the_front_flag_and_stops_at_the_standoff():
    """Step 8b replaced the lerp: `push_reach` is anchor + unit x reach."""
    env = _Env()
    ai = RivalAI(1, PERSONALITIES["zealot"], _rival_cfg(**_SMALL_MAP),
                 _power_cfg(), seed=0)
    env.cm.citizens.clear()
    for _ in range(4):
        env.cm.citizens.append(env.cm._make_citizen(faction=0, x=2.0, y=12.0,
                                                    age=10.0))
    for _ in range(4):
        env.cm.citizens.append(env.cm._make_citizen(faction=1, x=30.0, y=12.0,
                                                    age=10.0))
    s = _sense_only(ai, env)
    assert s.own_centroid == pytest.approx((30.0, 12.0))
    assert s.enemy_centroid == pytest.approx((2.0, 12.0))

    # No flags: anchor is our centroid, direction is straight at theirs,
    # reach is bias x step (6.5), nowhere near the 28-tile gap.
    anchor, u, reach = ai.push_reach(s)
    assert anchor == pytest.approx((30.0, 12.0))
    assert u == pytest.approx((-1.0, 0.0))
    assert reach == pytest.approx(10.0 * 0.65)
    assert ai.push_point_tile(s) is not None

    # Bias 0 never advances; bias 1 takes a full step.
    home = RivalAI(1, dataclasses.replace(ai.p, relic_forward_bias=0.0),
                   _rival_cfg(**_SMALL_MAP), _power_cfg(), seed=0)
    assert home.push_reach(_sense_only(home, env)) is None
    full = RivalAI(1, dataclasses.replace(ai.p, relic_forward_bias=1.0),
                   _rival_cfg(**_SMALL_MAP), _power_cfg(), seed=0)
    assert full.push_reach(_sense_only(full, env))[2] == pytest.approx(10.0)

    # A planted flag becomes the anchor - the chain steps from the FRONT
    # one, not from home.
    assert env.relics.place(1, 0, 20, 12, env.world, 0.0)[0]
    s = _sense_only(ai, env)
    assert ai.front_most(s).slot == 0
    anchor, u, reach = ai.push_reach(s)
    assert anchor == pytest.approx((20.0, 12.0))
    assert reach == pytest.approx(6.5)

    # The standoff caps the reach against the enemy centroid: a front flag
    # 5 tiles from them may advance only 2 more (standoff 3)...
    assert env.relics.place(1, 1, 7, 12, env.world, 0.0)[0]
    s = _sense_only(ai, env)
    assert ai.front_most(s).slot == 1
    assert ai.push_reach(s)[2] == pytest.approx(5.0 - 3.0)
    # ...and at the line, the chain holds: no push point at all.
    assert env.relics.move(1, 1, 5, 12, env.world, 1.0)[0]
    assert ai.push_reach(_sense_only(ai, env)) is None

    # An enemy relic on the ray shortens the reach to the edge of its
    # standoff circle; one off to the side does not.
    assert env.relics.retrieve(1, 1, 2.0)[0]               # front back to slot 0 at x=20
    assert env.relics.place(0, 0, 14, 12, env.world, 0.0)[0]   # dead ahead, 6 away
    s = _sense_only(ai, env)
    assert ai.push_reach(s)[2] == pytest.approx(6.0 - 3.0)
    assert env.relics.move(0, 0, 14, 20, env.world, 1.0)[0]    # 8 tiles off the ray
    s = _sense_only(ai, env)
    assert ai.push_reach(s)[2] == pytest.approx(6.5)


def test_f2_place_consumes_a_slot_through_the_real_api():
    ai, env, spy, _ = _property_run(ticks=120)

    placed = env.relics.placed_for_faction(1)
    assert placed, "the rival never planted a flag"
    assert ai.relic_acts >= len(placed)

    # Slots came out of the tray, and every placed relic sits on a tile
    # the real API accepted (walkable, in bounds, no same-faction stack).
    free = [r for r in env.relics.for_faction(1)
            if r.state == RelicState.AVAILABLE]
    assert len(placed) + len(free) == len(env.relics.for_faction(1))
    seen = set()
    for r in placed:
        assert env.world.in_bounds(r.tx, r.ty)
        assert is_walkable_tile(int(env.world.tiles[r.ty, r.tx]))
        assert (r.tx, r.ty) not in seen, "two relics stacked on one tile"
        seen.add((r.tx, r.ty))

    # And the citizen attractor list was re-synced, or the placement
    # would pull nobody and the whole point would be lost.
    assert any(a[3] == 1 for a in env.cm.attractors)


def test_f3_retrieve_only_fires_past_retrieve_panic():
    env = _Env()
    ai = _ai()                                  # zealot: retrieve_panic 0.75
    shatter_time = env.relics.cfg.shatter_time
    ok, _why = env.relics.place(1, 0, 16, 12, env.world, 0.0)
    assert ok

    def utility_at(threat_fraction):
        env.relics.get(1, 0).threat_timer = threat_fraction * shatter_time
        s = _sense_only(ai, env)
        assert s.max_threat_frac == pytest.approx(threat_fraction)
        return ai.utilities(s, env.ps, env.cm, env.world)[Intent.RELIC_RETRIEVE]

    assert utility_at(0.00) == 0.0
    assert utility_at(0.50) == 0.0
    assert utility_at(0.75) == 0.0              # at the panic point, not past
    # Past it the ramp is linear to 1.0 at a full shatter timer.
    assert utility_at(0.80) == pytest.approx((0.80 - 0.75) / 0.25)
    assert utility_at(1.00) == pytest.approx(1.0)


def test_f4_move_targets_the_rear_most_relic():
    env = _Env()
    ai = RivalAI(1, PERSONALITIES["zealot"], _rival_cfg(**_SMALL_MAP),
                 _power_cfg(), seed=0)
    env.cm.citizens.clear()
    for _ in range(4):
        env.cm.citizens.append(env.cm._make_citizen(faction=0, x=2.0, y=2.0,
                                                    age=10.0))
    for _ in range(4):
        env.cm.citizens.append(env.cm._make_citizen(faction=1, x=28.0, y=20.0,
                                                    age=10.0))

    # Slot 0 out front, slot 1 back home. The chain steps from slot 0; the
    # rear-most is slot 1, and moving it there is the leapfrog.
    assert env.relics.place(1, 0, 20, 14, env.world, 0.0)[0]
    assert env.relics.place(1, 1, 28, 20, env.world, 0.0)[0]

    s = _sense_only(ai, env)
    assert ai.front_most(s).slot == 0
    push = ai.push_point_tile(s)
    assert push is not None
    rear = ai.rear_most(s)
    assert rear is not None and rear.slot == 1
    assert dist((rear.tx, rear.ty), push) > dist((20, 14), push)
    # The leapfrog lands ahead of the old front, toward the enemy.
    assert dist(push, (2, 2)) < dist((20, 14), (2, 2))

    # And the verb moves that slot, not the forward one.
    before = (env.relics.get(1, 0).tx, env.relics.get(1, 0).ty)
    executed, why = ai._execute(
        Intent.RELIC_MOVE, push, s, sim_t=1.0, citizens=env.cm,
        world=env.world, food=env.food, belief=env.belief,
        relic_mgr=env.relics, power_system=env.ps)
    assert executed, why
    assert (env.relics.get(1, 1).tx, env.relics.get(1, 1).ty) == push
    assert (env.relics.get(1, 0).tx, env.relics.get(1, 0).ty) == before
    assert env.relics.get(1, 1).times_moved == 1


def test_f5_refinement_never_yields_an_unwalkable_tile():
    env = _Env()
    ai = _ai()
    tpc_x, tpc_y = env.belief.tiles_per_cell_x, env.belief.tiles_per_cell_y

    # Drown a whole cell block except one tile, then refine into it many
    # times - the seeded shuffle must never hand back the water.
    cell = (5, 5)
    block = [(cell[0] * tpc_x + i, cell[1] * tpc_y + j)
             for j in range(tpc_y) for i in range(tpc_x)]
    survivor = block[-1]
    for tx, ty in block:
        if (tx, ty) != survivor:
            env.world.tiles[ty, tx] = int(Tile.WATER)

    ai._tpc_x, ai._tpc_y = tpc_x, tpc_y
    ai._grid_w, ai._grid_h = env.belief.grid_w, env.belief.grid_h
    for _ in range(40):
        got = ai.refine(cell, env.world,
                        lambda tx, ty: env.relics.can_place(
                            1, 0, tx, ty, env.world)[0],
                        require_walkable=True)
        assert got == survivor
        assert is_walkable_tile(int(env.world.tiles[got[1], got[0]]))

    # Flood the survivor too and refinement reports failure rather than
    # returning something illegal - that None is what triggers a re-score.
    env.world.tiles[survivor[1], survivor[0]] = int(Tile.WATER)
    assert ai.refine(cell, env.world,
                     lambda tx, ty: env.relics.can_place(
                         1, 0, tx, ty, env.world)[0],
                     require_walkable=True) is None


def test_f6_two_rescore_bound_holds():
    env = _Env(initial_pop=12)
    env.stuff(12, faction=1, at=(24, 14))
    env.ps.pool[1] = 200.0
    env.advance(0.2)
    env.sim_t += 0.2

    ai = RivalAI(1, _AGGRESSIVE, _rival_cfg(**_SMALL_MAP), _power_cfg(),
                 seed=5)

    # Every target is unrefinable, so each pick is dropped and re-scored.
    tried = []

    def _never(intent, *a, **kw):
        tried.append(intent)
        return None

    ai.target_for = _never
    rec = ai._decide(sim_t=env.sim_t, citizens=env.cm, belief=env.belief,
                     relic_mgr=env.relics, power_system=env.ps,
                     world=env.world, food=env.food)

    assert rec.intent is Intent.IDLE
    assert rec.note == "re-score bound reached"
    assert rec.target is None and not rec.executed
    # One pick plus exactly two re-scores, then it stops. No scan loop.
    assert len(tried) == 3, f"tried {len(tried)} intents, expected 3"
    assert len(set(tried)) == 3, "a dropped intent was picked again"
    assert ai.casts == 0 and ai.relic_acts == 0


# -- F7/F8: regressions found by the step-6 smoke runs -------------------------

def test_f7_push_point_falls_back_when_its_block_is_unplaceable():
    """The primary push cell barely moves between decisions, so if it is
    unplaceable the AI stalls on it forever - RELIC_PLACE stays the top
    intent and fails refinement every tick. Observed live at 0.91."""
    env = _Env()
    ai = _ai()
    env.cm.citizens.clear()
    for _ in range(4):
        env.cm.citizens.append(env.cm._make_citizen(faction=0, x=4.0, y=12.0,
                                                    age=10.0))
    for _ in range(4):
        env.cm.citizens.append(env.cm._make_citizen(faction=1, x=28.0, y=12.0,
                                                    age=10.0))
    s = _sense_only(ai, env)

    cells = ai.push_point_cells(s)
    assert cells[0] == ai.push_point_cell(s), "primary must be tried first"
    assert 1 < len(cells) <= 25, "fallbacks must exist and stay bounded"

    # Drown the primary block outright; targeting must still find a tile.
    for tx, ty in ai.block_tiles(*cells[0]):
        if env.world.in_bounds(tx, ty):
            env.world.tiles[ty, tx] = int(Tile.WATER)

    got = ai.target_for(Intent.RELIC_PLACE, s, env.world, env.cm, env.ps,
                        env.relics)
    assert got is not None, "stalled on an unplaceable push point"
    assert is_walkable_tile(int(env.world.tiles[got[1], got[0]]))
    assert env.relics.can_place(1, ai.place_slot(s), got[0], got[1],
                                env.world)[0]

    # The reachability-aware push tile skips the drowned block too, so the
    # drift maths and the targeting agree on where "forward" is.
    reachable = ai.push_point_tile(s, env.world)
    assert reachable is not None
    assert reachable != ai.push_point_tile(s)


def test_f8_spread_gates_rather_than_merely_discounts():
    """`spread` began life as a plain ratio, which only lowered the score:
    the Zealot cleared its 0.05 idle floor on the way down and stacked all
    three relics within three tiles, starving itself. It must gate - on
    every flag except the one the chain is stepping from, which is
    `reach` away by construction (step 8b)."""
    env = _Env()
    ai = RivalAI(1, PERSONALITIES["zealot"], _rival_cfg(**_SMALL_MAP),
                 _power_cfg(), seed=0)
    env.cm.citizens.clear()
    for _ in range(4):
        env.cm.citizens.append(env.cm._make_citizen(faction=0, x=2.0, y=12.0,
                                                    age=10.0))
    for _ in range(4):
        env.cm.citizens.append(env.cm._make_citizen(faction=1, x=30.0, y=12.0,
                                                    age=10.0))
    # Front flag at x=16, rear flag at x=26 (enemy is at x=2).
    assert env.relics.place(1, 0, 16, 12, env.world, 0.0)[0]
    assert env.relics.place(1, 1, 26, 12, env.world, 0.0)[0]
    s = _sense_only(ai, env)
    assert ai.front_most(s).slot == 0

    assert ai.spread(s, (27, 13)) == 0.0        # on the rear flag: gated
    assert ai.spread(s, (17, 13)) == 1.0        # on the front flag: exempt
    assert ai.spread(s, (8, 12)) == 1.0         # clear of everything

    # With one flag down and the line too close for a step worth taking,
    # the chain itself refuses - there is no push point to stack on.
    assert env.relics.retrieve(1, 1, 1.0)[0]
    assert env.relics.move(1, 0, 6, 12, env.world, 1.0)[0]   # 4 from the enemy
    s = _sense_only(ai, env)
    assert ai.push_reach(s) is None
    u = ai.utilities(s, env.ps, env.cm, env.world)
    assert u[Intent.RELIC_PLACE] == 0.0
    assert ai.score(u)[Intent.RELIC_PLACE] == 0.0

    # An empty tray is still the unconditional 1.0 - nothing to stack on.
    assert env.relics.retrieve(1, 0, 2.0)[0]
    assert ai.spread(_sense_only(ai, env), (17, 13)) == 1.0
