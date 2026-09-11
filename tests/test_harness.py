"""PR4 step 8 - the headless harness (`densitas/harness.py`).

Two fast structural tests keep the harness itself honest; the full
acceptance matrix (3 ai_seeds x 2 modes x 600 sim_s, ~20 s) is opt-in via
`DENSITAS_ACCEPTANCE=1`, because its numbers are balance and balance is
playtest's to move. Run it on demand:

    DENSITAS_ACCEPTANCE=1 python -m pytest tests/test_harness.py -q
    python -m densitas.harness                      # the same, as a report
"""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from densitas import config
from densitas.harness import MODES, RoundResult, report, run_matrix, run_round

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_PATH = os.path.join(ROOT, "config.toml")


def _cfg():
    return config.load(CONFIG_PATH)


def test_passive_round_reports_the_shape_the_acceptance_reads():
    r = run_round(_cfg(), mode="passive", sim_s=60.0, ai_seed=0)
    assert isinstance(r, RoundResult)
    assert r.mode == "passive" and r.player is None
    assert r.rival.decisions == 30                 # 60 s at a 2 s cadence
    assert r.rival.casts + r.rival.relic_acts > 0
    assert r.rival.refused == 0
    assert set(r.pop_final) == {0, 1} and min(r.pop_final.values()) > 0
    assert min(r.pool_min.values()) >= 0.0
    # The passive player gets the three debug relics so the shatter-threat
    # clause has something to measure.
    assert r.relics_placed_end[0] + r.relics_shattered[0] == 3
    crit = r.acceptance()
    assert set(crit) == {"places >= 2 relics", "casts >= 10",
                         "converts >= 5", "pool never negative",
                         "player relic threat"}
    assert all(isinstance(ok, bool) and isinstance(d, str)
               for ok, d in crit.values())
    assert r.summary().startswith("[passive ai_seed=0]")


def test_versus_round_puts_a_brain_in_the_players_seat():
    r = run_round(_cfg(), mode="versus", sim_s=60.0, ai_seed=1,
                  player_brain="steward")
    assert r.player is not None and r.player.personality == "steward"
    assert r.player.decisions == 30 and r.rival.decisions == 30
    # A brained player places its own relics rather than the debug set.
    assert r.relics_placed_end[0] + r.relics_shattered[0] <= 3
    # Determinism: the same seeds give the same round.
    again = run_round(_cfg(), mode="versus", sim_s=60.0, ai_seed=1,
                      player_brain="steward")
    assert again.pop_final == r.pop_final
    assert again.rival.chosen == r.rival.chosen
    assert again.player.chosen == r.player.chosen
    with pytest.raises(ValueError):
        run_round(_cfg(), mode="spectator")


@pytest.mark.skipif(not os.environ.get("DENSITAS_ACCEPTANCE"),
                    reason="600 sim_s x 6 rounds; set DENSITAS_ACCEPTANCE=1")
def test_pr4_acceptance_matrix():
    """Spec §13's acceptance run. Prints the report either way so a
    failure shows *which* criterion moved, not just that one did."""
    results = run_matrix(_cfg(), modes=MODES, ai_seeds=(0, 1, 2),
                         sim_s=600.0, verbose=True)
    text = report(results)
    print(text)
    for mode in MODES:
        runs = [r for r in results if r.mode == mode]
        for c in ("places >= 2 relics", "casts >= 10", "converts >= 5",
                  "pool never negative"):
            assert all(r.acceptance()[c][0] for r in runs), f"{mode}: {c}"
    assert any(r.acceptance()["player relic threat"][0] for r in results)
