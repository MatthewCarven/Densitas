"""PR3 step 12 — Rhetoric token interpolation + full relic-event coverage.

The pre-step-12 happy-path / missing-key tests live in test_powers.py
(`test_20_rhetoric_picks_line`). This file covers what step 12 adds:

* Token interpolation via the `tokens=` kwarg + missing-token safety.
* All 4 relic events (placed / moved / retrieved / shattered) ×
  both gods (open_eye / maw) × all 3 modes (consecration / doctrinal /
  ritual) return a non-placeholder line.
* The 3 banked doctrinal lines from `densitas-scripture-voice` memory
  are present in their assigned cells.
* No-immediate-repeat rule survives the token interpolation pass.
"""
from __future__ import annotations
import json
import random
from collections import Counter
from pathlib import Path

import pytest

from densitas.rhetoric import Rhetoric, _SafeFormatDict, DEFAULT_RHETORIC_PATH


# -- helpers -----------------------------------------------------------------

RELIC_EVENTS = ("relic_placed", "relic_moved", "relic_retrieved",
                "relic_shattered")
GODS = ("open_eye", "maw")
MODES = ("consecration", "doctrinal", "ritual")


@pytest.fixture(scope="module")
def real_pool() -> dict:
    """Load the actual rhetoric.json from the project root."""
    with open(DEFAULT_RHETORIC_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


# -- A. Token interpolation --------------------------------------------------

def test_a1_tokens_substituted_when_provided():
    rhet = Rhetoric({
        "x": {"open_eye": {"consecration": ["Behold {relic_name}."]}}
    }, seed=0)
    out = rhet.pick("x", "open_eye", tokens={"relic_name": "The Lantern"})
    assert out == "Behold The Lantern."


def test_a2_tokens_none_leaves_braces_literal():
    """Backward compat — pre-step-12 callers omit `tokens` and the line
    is returned verbatim, even if it has {placeholders}."""
    rhet = Rhetoric({
        "x": {"open_eye": {"consecration": ["Behold {relic_name}."]}}
    }, seed=0)
    out = rhet.pick("x", "open_eye")
    assert out == "Behold {relic_name}."


def test_a3_unknown_token_left_literal():
    """SafeFormatDict: unknown tokens stay as `{name}` rather than raising."""
    rhet = Rhetoric({
        "x": {"open_eye": {"consecration": ["See {a} and {b}."]}}
    }, seed=0)
    out = rhet.pick("x", "open_eye", tokens={"a": "one"})
    assert out == "See one and {b}."


def test_a4_no_tokens_in_line_with_tokens_dict():
    """A line without {placeholders} passes through format_map unchanged
    when a tokens dict is supplied."""
    rhet = Rhetoric({
        "x": {"open_eye": {"consecration": ["Plain text."]}}
    }, seed=0)
    out = rhet.pick("x", "open_eye", tokens={"relic_name": "Ignored"})
    assert out == "Plain text."


def test_a5_safe_format_dict_missing_returns_brace_form():
    d = _SafeFormatDict({"a": "X"})
    assert d["a"] == "X"
    assert d["missing"] == "{missing}"


def test_a6_malformed_format_returns_line_verbatim():
    """Pathological format spec must not crash pick()."""
    rhet = Rhetoric({
        "x": {"open_eye": {"consecration": ["Bad {0!r:>{width}} spec"]}}
    }, seed=0)
    # No tokens supplied to satisfy the {0} / {width} — _interpolate
    # should swallow the ValueError and return the line literal.
    out = rhet.pick("x", "open_eye", tokens={})
    assert "Bad " in out


# -- B. Full relic-event coverage (every cell × every mode populated) -------

def test_b1_all_relic_events_present(real_pool):
    for event in RELIC_EVENTS:
        assert event in real_pool, f"missing top-level key {event}"
        for god in GODS:
            assert god in real_pool[event], f"missing {event}.{god}"


def test_b2_every_cell_has_all_three_modes(real_pool):
    """Each event × god cell must have at least 1 line per mode so the
    weighted mode-pick can't land on an empty list."""
    for event in RELIC_EVENTS:
        for god in GODS:
            cell = real_pool[event][god]
            for mode in MODES:
                assert mode in cell, f"{event}.{god} missing mode '{mode}'"
                assert len(cell[mode]) >= 1, \
                    f"{event}.{god}.{mode} empty"


def test_b3_pick_returns_real_line_for_every_cell_x_mode(real_pool):
    """Force-pick each mode by stubbing _pick_mode and assert a real
    line comes back (not the `<placeholder>` fallback)."""
    rhet = Rhetoric(real_pool, seed=0)
    for event in RELIC_EVENTS:
        for god in GODS:
            for mode in MODES:
                rhet._pick_mode = lambda gp, _m=mode: _m
                line = rhet.pick(event, god,
                                  tokens={"relic_name": "TEST_NAME"})
                assert not line.startswith("<"), \
                    f"placeholder returned for {event}.{god}.{mode}"
                assert line != "", f"empty line for {event}.{god}.{mode}"


# -- C. Banked doctrinal lines from the design memory ------------------------

def test_c1_open_eye_normalization_line_in_relic_placed(real_pool):
    """`densitas-scripture-voice` banks this line for placed.open_eye.doctrinal."""
    doct = real_pool["relic_placed"]["open_eye"]["doctrinal"]
    assert any("speed the new became normal" in line for line in doct), \
        "Open Eye 'speed the new became normal' line missing from " \
        "relic_placed.open_eye.doctrinal"


def test_c2_maw_eaten_line_in_relic_placed(real_pool):
    doct = real_pool["relic_placed"]["maw"]["doctrinal"]
    assert any("The new is eaten" in line for line in doct), \
        "Maw 'The new is eaten' line missing from relic_placed.maw.doctrinal"


def test_c3_maw_torture_tree_line_in_relic_shattered(real_pool):
    doct = real_pool["relic_shattered"]["maw"]["doctrinal"]
    assert any("torture-tree" in line for line in doct), \
        "Maw 'torture-tree' line missing from relic_shattered.maw.doctrinal"


# -- D. No-immediate-repeat survives interpolation ---------------------------

def test_d1_no_immediate_repeat_with_tokens():
    """When the same (event, god) is picked many times in a row with a
    multi-line pool, consecutive picks should differ (the no-repeat rule)."""
    rhet = Rhetoric({
        "x": {"open_eye": {"consecration": [
            "Line A about {relic_name}.",
            "Line B about {relic_name}.",
        ]}}
    }, seed=7)
    prev = None
    for _ in range(20):
        line = rhet.pick("x", "open_eye", tokens={"relic_name": "Z"})
        if prev is not None:
            assert line != prev, "no-repeat rule violated"
        prev = line


def test_d2_single_line_pool_repeats_silently():
    """If a pool has only one line, the rule yields and the line is
    returned every time (per the docstring in pick())."""
    rhet = Rhetoric({
        "x": {"open_eye": {"consecration": ["Only line {relic_name}."]}}
    }, seed=0)
    for _ in range(5):
        out = rhet.pick("x", "open_eye", tokens={"relic_name": "Z"})
        assert out == "Only line Z."


# -- E. Weighted-mode pick still respects 70/20/10 over a large sample ------

def test_e1_mode_weights_roughly_70_20_10(real_pool):
    """Over many picks against a cell that has all three modes populated,
    mode frequencies should sit within 7 percentage points of spec."""
    # Use relic_placed.open_eye which has 3/2/1 lines across modes.
    cell = real_pool["relic_placed"]["open_eye"]
    rhet = Rhetoric(real_pool, seed=12345)
    # Tap _pick_mode directly to isolate the weighting from the pool.
    n = 20_000
    counts = Counter()
    for _ in range(n):
        counts[rhet._pick_mode(cell)] += 1
    for mode, expected in (("consecration", 0.70), ("doctrinal", 0.20),
                            ("ritual", 0.10)):
        observed = counts[mode] / n
        assert abs(observed - expected) < 0.03, \
            f"{mode}: observed {observed:.3f}, expected {expected:.3f}"


# -- F. Deterministic with seed ---------------------------------------------

def test_f1_same_seed_same_sequence(real_pool):
    """Two managers with the same seed produce the same pick sequence."""
    r1 = Rhetoric(real_pool, seed=999)
    r2 = Rhetoric(real_pool, seed=999)
    seq1 = [r1.pick("relic_placed", "maw",
                     tokens={"relic_name": "X"}) for _ in range(10)]
    seq2 = [r2.pick("relic_placed", "maw",
                     tokens={"relic_name": "X"}) for _ in range(10)]
    assert seq1 == seq2
