"""PR4 step 7a - scripture machinery tests (spec `Densitas_rival_ai.md`
§4, §12 group G, machinery half).

Group G, the three that need no lines written:
  G1. the coalescer voices the first event at once and batches the rest
      of the window into one `{count}` line
  G2. singular vs plural: count 1 uses the base cell, count > 1 the
      `<key>_many` cell when the pool has one, the base cell when not
  G5. the no-repeat rule survives coalesced picks

Plus the channel and the routing the three above stand on:
  H1. a completed conversion emits a CitizenEvent with the right factions,
      and the cumulative counter follows it
  H2. despair emits its own event kind, and drain_events() empties
  H3. the rival's relic verbs reach the scripture log with the relic's
      name, and `[rival] relic_scripture = false` silences them
  H4. `PowerSystem.voice` is the one append site: it caps the log and
      leaves `power` None for a non-cast line

G3 and G4 (the cells themselves) are step 7b's.

Run from the repo root:
    python -m pytest tests/test_scripture.py
"""
from __future__ import annotations

import dataclasses
import math
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from densitas.citizen import CitizenEvent, CitizenManager, CitizenState
from densitas.config import CitizenConfig, FaithConfig, WorldConfig
from densitas.powers import PowerKind, PowerSystem, god_key_for
from densitas.rhetoric import Rhetoric, ScriptureCoalescer
from densitas.rival_ai import Intent
from densitas.world import World

# The rival-AI test file already builds a full small environment; reuse
# it rather than grow a second copy of every config block.
from tests.test_rival_ai import (
    PERSONALITIES, RivalAI, _Env, _power_cfg, _rival_cfg, _sense_only,
)

DT = 0.2


# -- a pool with singular + plural conversion cells --------------------------

def _pool():
    return Rhetoric({
        "citizen_converted": {
            "open_eye": {"consecration": ["One more opened an eye."]},
            "maw":      {"consecration": ["One was swallowed."]},
        },
        "citizen_converted_many": {
            "open_eye": {"consecration": ["{count} more opened their eyes.",
                                          "{count} lids lifted at once."]},
            # The Maw has no plural cell: G2 checks the fallback.
        },
        "citizen_despair": {
            "open_eye": {"consecration": ["The unworthy were called home."]},
        },
    }, seed=7)


class _Log:
    """Stand-in for PowerSystem.voice: records (key, faction, sim_t, tokens)
    and returns the picked line."""

    def __init__(self, rhet):
        self.rhet = rhet
        self.calls = []

    def voice(self, key, faction, sim_t, tokens):
        line = self.rhet.pick(key, god_key_for(faction), sim_t=sim_t,
                              tokens=tokens)
        self.calls.append((key, faction, sim_t, dict(tokens), line))
        return line

    def has(self, key, faction):
        return self.rhet.has(key, god_key_for(faction))


def _coalescer(window=5.0):
    log = _Log(_pool())
    return ScriptureCoalescer(window, voice=log.voice, has=log.has), log


# -- G1: leading edge, then one batch per window ------------------------------

def test_g1_coalescer_batches_the_window_into_one_count_line():
    co, log = _coalescer(window=5.0)

    # First event in a quiet window is voiced immediately, count 1.
    line = co.emit("citizen_converted", 0, 0.0)
    assert line == "One more opened an eye."
    assert len(log.calls) == 1 and log.calls[0][3]["count"] == 1

    # Six more inside the window join a batch; nothing is voiced.
    for t in (0.4, 0.8, 1.2, 2.0, 3.0, 4.6):
        assert co.emit("citizen_converted", 0, t) is None
        assert co.tick(t) == []
    assert len(log.calls) == 1

    # At the window's end the batch flushes as exactly one plural line.
    flushed = co.tick(5.0)
    assert len(flushed) == 1
    assert len(log.calls) == 2
    key, faction, t, toks, line = log.calls[1]
    assert key == "citizen_converted_many" and toks["count"] == 6
    assert line in ("6 more opened their eyes.", "6 lids lifted at once.")
    assert co.lines == 2 and co.batched == 6

    # A fresh event right after the flush is inside the new window, so it
    # batches again rather than voicing - one line per window, full stop.
    assert co.emit("citizen_converted", 0, 5.2) is None
    assert co.tick(9.9) == []
    assert len(co.tick(10.0)) == 1

    # Keys and factions rate-limit independently of each other.
    assert co.emit("citizen_despair", 0, 10.1) is not None
    assert co.emit("citizen_converted", 1, 10.1) is not None


# -- G2: singular vs plural cell selection -----------------------------------

def test_g2_singular_and_plural_cells():
    co, log = _coalescer(window=5.0)

    # Count 1 -> singular cell, for a god that HAS a plural cell.
    co.emit("citizen_converted", 0, 0.0)
    assert log.calls[-1][0] == "citizen_converted"

    # Count > 1 -> `_many` cell when it exists ...
    for t in (1.0, 2.0):
        co.emit("citizen_converted", 0, t)
    co.tick(5.0)
    assert log.calls[-1][0] == "citizen_converted_many"
    assert log.calls[-1][3]["count"] == 2

    # ... and the base cell, `{count}` still substituted, when it does not
    # (the Maw has no plural cell in this pool).
    co.emit("citizen_converted", 1, 0.0)
    for t in (1.0, 2.0, 3.0):
        co.emit("citizen_converted", 1, t)
    co.tick(5.0)
    key, faction, _t, toks, line = log.calls[-1]
    assert (key, faction) == ("citizen_converted", 1)
    assert toks["count"] == 3
    assert line == "One was swallowed."   # no {count} in the line; still fine

    # Without a `has`, the coalescer commits to `_many` and lets the
    # placeholder show - a missing cell is a thing to notice, not hide.
    blind_log = _Log(_pool())
    blind = ScriptureCoalescer(5.0, voice=blind_log.voice)
    blind.emit("citizen_converted", 1, 0.0)      # voiced: singular
    blind.emit("citizen_converted", 1, 1.0)      # batched ...
    blind.emit("citizen_converted", 1, 2.0)      # ... count 2
    blind.tick(5.0)
    assert blind_log.calls[-1][3]["count"] == 2
    assert blind_log.calls[-1][4] == "<citizen_converted_many>"


# -- G5: no-repeat survives coalesced picks ----------------------------------

def test_g5_no_repeat_survives_coalesced_picks():
    co, log = _coalescer(window=1.0)
    # Two-line plural pool: consecutive batch flushes must alternate,
    # exactly as consecutive direct picks would.
    picked = []
    t = 0.0
    co.emit("citizen_converted", 0, t)            # leading edge, singular
    for _ in range(12):
        co.emit("citizen_converted", 0, t + 0.1)
        co.emit("citizen_converted", 0, t + 0.2)
        t += 1.0
        co.tick(t)
        picked.append(log.calls[-1][4])
    assert all(p.startswith("2 ") for p in picked)
    assert all(a != b for a, b in zip(picked, picked[1:])), picked


# -- H1/H2: the event channel out of CitizenManager --------------------------

class _StubBelief:
    def __init__(self, own, riv):
        self.own, self.riv = own, riv

    def query(self, tx, ty, faction=0):
        return self.own if faction == 0 else self.riv


def _lone_citizen_manager():
    world = World.generate(WorldConfig(
        width=64, height=48, seed=42, sea_level=0.30, beach_thresh=0.34,
        forest_thresh=0.55, hill_thresh=0.70, mountain_thresh=0.85))
    cm = CitizenManager(CitizenConfig(
        initial_population=1, spawn_radius_tiles=20, spawn_seed=0,
        maturity_age=8.0, lifespan_mean=900.0, lifespan_jitter=0.0,
        repro_radius=2, repro_cooldown=6.0, mate_duration=0.5,
        dying_duration=0.5, wander_period=1e9, wander_radius=6,
        wander_speed=1.0, tick_hz=5, faith=FaithConfig()), world,
        world_seed=42)
    assert len(cm.citizens) == 1
    return cm, world


def test_h1_conversion_emits_an_event_and_counts():
    cm, world = _lone_citizen_manager()
    c = cm.citizens[0]
    c.faith = 0.20
    belief = _StubBelief(own=0.40, riv=0.50)
    assert cm.events == [] and not cm.conversions

    for _ in range(20):
        cm.tick(DT, world, None, belief=belief)
        if c.faction == 1:
            break
    assert c.faction == 1

    evs = cm.drain_events()
    assert len(evs) == 1
    ev = evs[0]
    assert isinstance(ev, CitizenEvent)
    assert ev.kind == "converted"
    assert (ev.from_faction, ev.to_faction) == (0, 1)
    assert ev.citizen_id == c.id
    assert (ev.tx, ev.ty) == (int(c.x), int(c.y))
    assert math.isclose(ev.sim_t, cm._sim_t)
    # Drained, but counted for good.
    assert cm.events == []
    assert cm.conversions[(0, 1)] == 1
    assert cm.drain_events() == []


def test_h2_despair_emits_its_own_kind():
    cm, world = _lone_citizen_manager()
    c = cm.citizens[0]
    c.faith = 0.04                               # under despair_threshold
    belief = _StubBelief(own=0.0, riv=0.0)       # nowhere to convert to
    cm.tick(DT, world, None, belief=belief)

    assert c.state == CitizenState.DYING and c.death_cause == "despair"
    evs = cm.drain_events()
    assert [e.kind for e in evs] == ["despair"]
    assert (evs[0].from_faction, evs[0].to_faction) == (0, 0)
    assert cm.despairs[0] == 1 and not cm.conversions


# -- H3: the rival's relic verbs are voiced ----------------------------------

def _rival_relic_place(relic_scripture):
    env = _Env()
    ai = RivalAI(1, PERSONALITIES["zealot"],
                 _rival_cfg(relic_scripture=relic_scripture), _power_cfg(),
                 seed=0)
    env.cm.citizens.clear()
    for _ in range(4):
        env.cm.citizens.append(env.cm._make_citizen(faction=0, x=6.0, y=6.0,
                                                    age=10.0))
    for _ in range(4):
        env.cm.citizens.append(env.cm._make_citizen(faction=1, x=26.0, y=18.0,
                                                    age=10.0))
    # A real pool behind the power system, so the line is a real line.
    env.ps._rhetoric = Rhetoric({
        "relic_placed": {"maw": {"consecration": ["{relic_name} is set."]}},
    }, seed=0).pick
    s = _sense_only(ai, env)
    target = ai.target_for(Intent.RELIC_PLACE, s, env.world, env.cm, env.ps,
                           env.relics)
    assert target is not None
    executed, why = ai._execute(
        Intent.RELIC_PLACE, target, s, sim_t=3.0, citizens=env.cm,
        world=env.world, food=env.food, belief=env.belief,
        relic_mgr=env.relics, power_system=env.ps)
    assert executed, why
    return env


def test_h3_rival_relic_verbs_reach_the_log_behind_the_toggle():
    env = _rival_relic_place(relic_scripture=True)
    placed = env.relics.placed_for_faction(1)
    assert len(placed) == 1
    assert len(env.ps.scripture_log) == 1
    entry = env.ps.scripture_log[0]
    assert entry.line == f"{placed[0].name} is set."
    assert entry.faction == 1 and entry.power is None
    assert entry.sim_t == 3.0

    # Off: the verb still happens, the log stays silent.
    env = _rival_relic_place(relic_scripture=False)
    assert len(env.relics.placed_for_faction(1)) == 1
    assert env.ps.scripture_log == []


# -- H4: voice() is the one append site --------------------------------------

def test_h4_voice_caps_the_log_and_marks_non_casts():
    ps = PowerSystem(dataclasses.replace(_power_cfg(), scripture_log_max=3),
                     n_factions=2)
    for i in range(5):
        ps.voice("citizen_converted", 1, float(i))
    assert len(ps.scripture_log) == 3
    assert [e.sim_t for e in ps.scripture_log] == [2.0, 3.0, 4.0]
    assert all(e.power is None and e.faction == 1 for e in ps.scripture_log)
    # The stub picker yields a visible placeholder for a missing cell.
    assert ps.scripture_log[-1].line == "<citizen_converted>"

    # A cast still tags its entry with the power, through the same site.
    env = _Env()
    env.stuff(12, faction=0)
    env.ps.pool[0] = 50.0
    receipt = env.ps.cast(PowerKind.INSPIRE, 0, 6, 6, env.cm, env.world,
                          env.food, env.belief, 1.0)
    assert receipt.ok
    assert env.ps.scripture_log[-1].power == PowerKind.INSPIRE
