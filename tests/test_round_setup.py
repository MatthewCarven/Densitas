"""PR4 step 3 — round-setup tests (spec `Densitas_rival_ai.md` §12 group C).

Five tests, no display required (importing `densitas.main` pulls pygame
in but never opens a window):
  C1. default rival spawn count + location
  C2. `--rival-stub-seed` warns and overrides `[rival] initial_population`
  C3. `--seed-relics` restores exactly the old six placements
  C4. a default round starts with six AVAILABLE slots and no PLACED relics
  C5. `[rival]` round-trips through config.toml, and a bad personality
      is rejected at load time

Run from the repo root:
    python -m pytest tests/test_round_setup.py
"""
from __future__ import annotations
import contextlib
import io as _io
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from densitas import config as config_mod
from densitas.config import load, RivalConfig, PERSONALITIES
from densitas.world import World
from densitas.citizen import CitizenManager
from densitas.relics import RelicManager, RelicState
from densitas.main import (
    parse_args, effective_rival_population,
    seed_relics, SEED_RELIC_PLACEMENTS,
)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_PATH = os.path.join(ROOT, "config.toml")


def _cfg():
    return load(CONFIG_PATH)


# ---------- C1: default rival spawn count + location -------------------------

def test_default_rival_spawn_count_and_location():
    cfg = _cfg()
    world = World.generate(cfg.world)
    cm = CitizenManager(cfg.citizen, world, world_seed=cfg.world.seed)
    before = len(cm.citizens)

    placed = cm.spawn_faction_at(
        world, n=cfg.rival.initial_population, faction=1,
        frac_x=cfg.rival.spawn_frac_x, frac_y=cfg.rival.spawn_frac_y,
        radius=cfg.rival.spawn_radius_tiles, seed=cfg.world.seed,
    )
    assert placed == cfg.rival.initial_population
    assert len(cm.citizens) == before + placed
    assert cm.population(1) == placed

    cx = int(world.width * cfg.rival.spawn_frac_x)
    cy = int(world.height * cfg.rival.spawn_frac_y)
    r = cfg.rival.spawn_radius_tiles
    for c in cm.citizens:
        if c.faction != 1:
            continue
        assert abs(int(c.x) - cx) <= r, (c.x, cx)
        assert abs(int(c.y) - cy) <= r, (c.y, cy)
        assert c.faith == 1.0          # rivals are devout at spawn too


# ---------- C2: deprecated flag warns + overrides -----------------------------

def test_rival_stub_seed_warns_and_overrides():
    err = _io.StringIO()
    with contextlib.redirect_stderr(err):
        args = parse_args(["densitas", "--rival-stub-seed", "12"])
    assert args["rival_stub_seed"] == 12
    assert args["seed_relics"] is False
    assert "deprecated" in err.getvalue().lower()

    # The flag beats config, including when the rival is switched off.
    on = RivalConfig(initial_population=8, enabled=True)
    off = RivalConfig(initial_population=8, enabled=False)
    assert effective_rival_population(on, args) == 12
    assert effective_rival_population(off, args) == 12

    # Without the flag: config decides.
    plain = parse_args(["densitas"])
    assert plain["rival_stub_seed"] == 0
    assert effective_rival_population(on, plain) == 8
    assert effective_rival_population(off, plain) == 0

    # A garbage value warns and leaves the default alone.
    err2 = _io.StringIO()
    with contextlib.redirect_stderr(err2):
        bad = parse_args(["densitas", "--rival-stub-seed", "banana"])
    assert bad["rival_stub_seed"] == 0
    assert "expects an integer" in err2.getvalue()


# ---------- C3: --seed-relics restores exactly the old six --------------------

def test_seed_relics_flag_restores_the_old_six():
    args = parse_args(["densitas", "--seed-relics"])
    assert args["seed_relics"] is True
    assert args["rival_stub_seed"] == 0

    cfg = _cfg()
    world = World.generate(cfg.world)
    mgr = RelicManager(cfg.powers.relic, n_factions=2)
    placed = seed_relics(mgr, world, verbose=False)
    assert len(SEED_RELIC_PLACEMENTS) == 6
    assert placed == 6

    cx, cy = world.width // 2, world.height // 2
    expected = {(f, s): (cx + dx, cy + dy)
                for f, s, dx, dy in SEED_RELIC_PLACEMENTS}
    got = {(r.faction, r.slot): (r.tx, r.ty)
           for r in mgr.relics if r.state == RelicState.PLACED}
    assert got == expected


# ---------- C4: a default round has six AVAILABLE slots -----------------------

def test_default_round_has_six_available_slots():
    cfg = _cfg()
    mgr = RelicManager(cfg.powers.relic, n_factions=2)
    assert len(mgr.relics) == 6
    assert all(r.state == RelicState.AVAILABLE for r in mgr.relics)
    for faction in (0, 1):
        assert sum(1 for r in mgr.relics if r.faction == faction) == 3
    # And a default round does not run the seeder.
    args = parse_args(["densitas"])
    assert args["seed_relics"] is False


# ---------- C5: config round-trip + validation --------------------------------

def test_rival_config_round_trips():
    cfg = _cfg()
    r = cfg.rival
    assert r.enabled is True
    assert r.personality == "zealot" and r.personality in PERSONALITIES
    assert r.difficulty == 1.0
    assert r.initial_population == 8
    assert (r.spawn_frac_x, r.spawn_frac_y) == (0.75, 0.50)
    assert r.spawn_radius_tiles == 5
    assert r.ai_base_period == 2.0
    assert r.ai_seed == 0
    # config.toml carries the spec's opening bids verbatim.
    assert r == RivalConfig()

    tmpdir = tempfile.mkdtemp()
    try:
        # A [rival]-less config still loads, with the defaults.
        text = open(CONFIG_PATH, encoding="utf-8").read()
        start = text.index("[rival]")
        end = text.index("[belief]")
        legacy = os.path.join(tmpdir, "legacy.toml")
        with open(legacy, "w", encoding="utf-8") as f:
            f.write(text[:start] + text[end:])
        assert load(legacy).rival == RivalConfig()

        # A typo'd personality is a load-time error, not a silent wrong brain.
        bad = os.path.join(tmpdir, "bad.toml")
        with open(bad, "w", encoding="utf-8") as f:
            f.write(text.replace('personality        = "zealot"',
                                 'personality        = "zelot"'))
        try:
            load(bad)
        except ValueError as e:
            assert "personality" in str(e)
        else:
            raise AssertionError("expected ValueError for a bad personality")
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            fn()
            print(f"ok {name}")
