"""Headless round runner (PR4 step 8, spec §13 as amended 2026-09-11).

`run_round()` is `main.py`'s 5 Hz loop without pygame: the same order of
operations, the same entry points, the same scripture path. It can put an
Open Eye brain in the player's seat (`mode="versus"`), so the Maw is
measured against an opponent that fights back rather than a faction that
stands there and takes it - the passive numbers from steps 4-6 overstate
the rival for exactly that reason.

It exists because every balance question so far was answered with a
scratch script that re-typed this loop. Now there is one copy, the
acceptance run reads from it, and a future "does the Steward hold?" is a
one-liner.

    python -m densitas.harness                      # acceptance matrix
    python -m densitas.harness --mode versus --ai-seeds 0 1 --sim-s 300
    python -m densitas.harness --player-brain zealot   # mirror match

Acceptance (spec §13): the rival places >= 2 relics, casts >= 10 times,
converts >= 5 player citizens; no exceptions; pool never negative; player
relics come under genuine shatter threat in at least one run. Evaluated
per run by `acceptance()`; the "at least one run" clause is the caller's.
"""
from __future__ import annotations

import argparse
import sys
import time
from collections import Counter
from dataclasses import dataclass, field
from typing import Optional

from . import config
from .belief import BeliefField
from .citizen import CitizenManager
from .food import FoodField
from .powers import PowerSystem, god_key_for
from .relics import RelicManager, RelicState
from .rhetoric import Rhetoric, ScriptureCoalescer, make_picker
from .rival_ai import PERSONALITIES, Intent, RivalAI
from .world import World

# The three faction-0 debug placements from main.SEED_RELIC_PLACEMENTS,
# centre-relative. A passive player never places relics, and the
# acceptance clause about player relics under threat needs some to exist.
_PLAYER_SEED_RELICS: tuple[tuple[int, int, int], ...] = (
    (0, -4, -1), (1, 3, 0), (2, -8, -6),      # (slot, dx, dy)
)

MODES = ("passive", "versus")


@dataclass
class BrainStats:
    personality: str
    decisions: int = 0
    casts: int = 0
    relic_acts: int = 0
    refused: int = 0
    executed: Counter = field(default_factory=Counter)   # Intent.name -> n
    chosen: Counter = field(default_factory=Counter)     # Intent.name -> n

    @property
    def placements(self) -> int:
        return self.executed.get(Intent.RELIC_PLACE.name, 0)


@dataclass
class RoundResult:
    mode: str
    world_seed: int
    ai_seed: int
    sim_s: float
    wall_s: float
    pop_final: dict[int, int]
    pop_peak: dict[int, int]
    extinct_at: dict[int, Optional[float]]
    pool_min: dict[int, float]
    pool_final: dict[int, float]
    conversions: Counter                   # (from, to) -> n
    despairs: Counter                      # faction -> n
    relics_placed_end: dict[int, int]
    relics_shattered: dict[int, int]
    max_threat_frac: dict[int, float]      # per relic owner
    scripture_lines: int
    coalesced_lines: int
    rival: BrainStats
    player: Optional[BrainStats]

    # -- acceptance ------------------------------------------------------------

    def acceptance(self) -> dict[str, tuple[bool, str]]:
        """Spec §13's per-run criteria. Pool-never-negative and
        no-exceptions are structural: an exception propagates out of
        `run_round`, and the pool floor is measured every tick."""
        conv = self.conversions.get((0, 1), 0)
        threat = self.max_threat_frac.get(0, 0.0)
        return {
            "places >= 2 relics":   (self.rival.placements >= 2,
                                     f"{self.rival.placements} placed"),
            "casts >= 10":          (self.rival.casts >= 10,
                                     f"{self.rival.casts} casts"),
            "converts >= 5":        (conv >= 5, f"{conv} converted 0->1"),
            "pool never negative":  (min(self.pool_min.values()) >= 0.0,
                                     f"min {min(self.pool_min.values()):.2f}"),
            "player relic threat":  (threat >= 0.25,
                                     f"max threat {threat:.2f} of shatter"),
        }

    def passed(self) -> bool:
        return all(ok for ok, _ in self.acceptance().values())

    # -- display -----------------------------------------------------------

    def summary(self) -> str:
        p0, p1 = self.pop_final.get(0, 0), self.pop_final.get(1, 0)
        ext = ", ".join(f"f{f} out @ {t:.0f}s"
                        for f, t in self.extinct_at.items() if t is not None)
        conv = self.conversions.get((0, 1), 0)
        back = self.conversions.get((1, 0), 0)
        player = (f" | eye: {self.player.casts}c/{self.player.relic_acts}r"
                  if self.player else "")
        return (f"[{self.mode:7s} ai_seed={self.ai_seed}] "
                f"pop {p0:3d} v {p1:3d} (peak {self.pop_peak.get(0, 0)}/"
                f"{self.pop_peak.get(1, 0)}){' [' + ext + ']' if ext else ''} "
                f"| conv 0->1 {conv:2d}, 1->0 {back:2d} "
                f"| maw: {self.rival.casts}c/{self.rival.relic_acts}r "
                f"({self.rival.placements} placed, "
                f"{self.relics_shattered.get(1, 0)} shattered)"
                f"{player} | threat f0 {self.max_threat_frac.get(0, 0.0):.2f}")


def run_round(cfg: config.Config, *, mode: str = "passive", sim_s: float = 600.0,
              ai_seed: int = 0, player_brain: str = "steward",
              rival_brain: Optional[str] = None,
              seed_player_relics: Optional[bool] = None,
              world_seed: Optional[int] = None) -> RoundResult:
    """One headless round. Raises on any exception - the harness does not
    swallow; "no exceptions" is an acceptance criterion."""
    if mode not in MODES:
        raise ValueError(f"mode must be one of {MODES}, got {mode!r}")
    t_wall = time.perf_counter()

    wcfg = cfg.world
    if world_seed is not None:
        import dataclasses
        wcfg = dataclasses.replace(wcfg, seed=int(world_seed))
    world = World.generate(wcfg)

    cm = CitizenManager(cfg.citizen, world, world_seed=wcfg.seed,
                        food_cfg=cfg.food, relic_cfg=cfg.powers.relic)
    cm.spawn_faction_at(
        world, n=cfg.rival.initial_population, faction=1,
        frac_x=cfg.rival.spawn_frac_x, frac_y=cfg.rival.spawn_frac_y,
        radius=cfg.rival.spawn_radius_tiles, seed=wcfg.seed,
    )
    food = FoodField(cfg.food, world)
    belief = BeliefField(cfg.belief, world,
                         dying_duration=cfg.citizen.dying_duration,
                         relic_cfg=cfg.powers.relic)
    relics = RelicManager(cfg.powers.relic, n_factions=2)

    # A passive player gets the debug relic set so the shatter-threat
    # clause has something to measure; a brained player places its own.
    if seed_player_relics is None:
        seed_player_relics = (mode == "passive")
    if seed_player_relics:
        cx, cy = world.width // 2, world.height // 2
        for slot, dx, dy in _PLAYER_SEED_RELICS:
            relics.place(0, slot, cx + dx, cy + dy, world, 0.0)
    cm.sync_attractors_from_relics(relics.relics, cfg.powers.relic.attract_radius)
    belief.recompute(cm.citizens, relics=relics.relics, sim_t=0.0)

    try:
        rhet = Rhetoric.from_file(seed=wcfg.seed)
    except FileNotFoundError:
        rhet = Rhetoric({}, seed=wcfg.seed)
    ps = PowerSystem(cfg.powers, n_factions=2, rhetoric_pick=make_picker(rhet))
    coalescer = ScriptureCoalescer(
        cfg.citizen.faith.scripture_coalesce_window,
        voice=lambda key, faction, t, tokens: ps.voice(key, faction, t,
                                                       tokens=tokens),
        has=lambda key, faction: rhet.has(key, god_key_for(faction)),
    )

    rival_name = rival_brain or cfg.rival.personality
    rival = RivalAI(1, PERSONALITIES[rival_name], cfg.rival, cfg.powers,
                    seed=ai_seed)
    player = None
    if mode == "versus":
        player = RivalAI(0, PERSONALITIES[player_brain], cfg.rival,
                         cfg.powers, seed=ai_seed)

    stats = {1: BrainStats(rival_name)}
    if player is not None:
        stats[0] = BrainStats(player_brain)

    dt = 1.0 / cfg.citizen.tick_hz
    sim_t = 0.0
    pop_peak = {0: cm.population(0), 1: cm.population(1)}
    extinct_at: dict[int, Optional[float]] = {0: None, 1: None}
    pool_min = {0: ps.pool[0], 1: ps.pool[1]}
    max_threat = {0: 0.0, 1: 0.0}
    shattered = Counter()
    shatter_time = max(1e-9, cfg.powers.relic.shatter_time)

    def _tick_brain(ai: RivalAI, st: BrainStats) -> None:
        rec = ai.tick(dt, sim_t=sim_t, citizens=cm, belief=belief,
                      relic_mgr=relics, power_system=ps, world=world,
                      food=food)
        if rec is not None:
            st.decisions += 1
            st.chosen[rec.intent.name] += 1
            if rec.executed:
                st.executed[rec.intent.name] += 1

    n_ticks = int(round(sim_s / dt))
    for _ in range(n_ticks):
        # main.py's order, verbatim.
        ps.tick(dt, cm, sim_t)
        ps.drain_queues(cm, world, food, belief, sim_t)
        food.recompute(dt, effects=ps.effects)
        cm.tick(dt, world, food, belief=belief)
        for ev in cm.drain_events():
            if ev.kind == "converted":
                coalescer.emit("citizen_converted", ev.to_faction, sim_t)
            elif ev.kind == "despair":
                coalescer.emit("citizen_despair", ev.from_faction, sim_t)
        coalescer.tick(sim_t)
        belief.recompute(cm.citizens, relics=relics.relics, sim_t=sim_t)
        for s in relics.tick(dt, belief, cm, sim_t=sim_t):
            shattered[s.faction] += 1
            cm.sync_attractors_from_relics(relics.relics,
                                           cfg.powers.relic.attract_radius)
        # The player brain moves first, then the rival, so a versus round
        # is one deterministic interleaving rather than two.
        if player is not None:
            _tick_brain(player, stats[0])
        _tick_brain(rival, stats[1])

        for f in (0, 1):
            n = cm.population(f)
            pop_peak[f] = max(pop_peak[f], n)
            if n == 0 and extinct_at[f] is None:
                extinct_at[f] = sim_t
            pool_min[f] = min(pool_min[f], ps.pool[f])
        for r in relics.relics:
            if r.state == RelicState.PLACED:
                max_threat[r.faction] = max(
                    max_threat[r.faction], r.threat_timer / shatter_time)
        sim_t += dt

    for f, ai in ((1, rival), (0, player)):
        if ai is None:
            continue
        stats[f].casts = ai.casts
        stats[f].relic_acts = ai.relic_acts
        stats[f].refused = ai.refused

    return RoundResult(
        mode=mode, world_seed=wcfg.seed, ai_seed=ai_seed, sim_s=sim_s,
        wall_s=time.perf_counter() - t_wall,
        pop_final={0: cm.population(0), 1: cm.population(1)},
        pop_peak=pop_peak, extinct_at=extinct_at,
        pool_min=pool_min, pool_final={0: ps.pool[0], 1: ps.pool[1]},
        conversions=Counter(cm.conversions), despairs=Counter(cm.despairs),
        relics_placed_end={f: len(relics.placed_for_faction(f)) for f in (0, 1)},
        relics_shattered={f: shattered.get(f, 0) for f in (0, 1)},
        max_threat_frac=max_threat,
        scripture_lines=len(ps.scripture_log),
        coalesced_lines=coalescer.lines,
        rival=stats[1], player=stats.get(0),
    )


def run_matrix(cfg: config.Config, *, modes=MODES, ai_seeds=(0, 1, 2),
               sim_s: float = 600.0, player_brain: str = "steward",
               verbose: bool = True) -> list[RoundResult]:
    """The acceptance matrix: every mode x every ai_seed."""
    out: list[RoundResult] = []
    for mode in modes:
        for seed in ai_seeds:
            r = run_round(cfg, mode=mode, sim_s=sim_s, ai_seed=seed,
                          player_brain=player_brain)
            out.append(r)
            if verbose:
                print(r.summary())
    return out


def report(results: list[RoundResult]) -> str:
    """Per-criterion PASS/FAIL across the matrix. The spec's "at least
    one run" clause applies to the shatter-threat criterion only."""
    lines = []
    crits = list(results[0].acceptance()) if results else []
    for mode in dict.fromkeys(r.mode for r in results):
        runs = [r for r in results if r.mode == mode]
        lines.append(f"\n{mode} ({len(runs)} runs, {runs[0].sim_s:.0f} sim_s each):")
        for c in crits:
            oks = [r.acceptance()[c] for r in runs]
            if c == "player relic threat":
                ok = any(o for o, _ in oks)
                rule = "any run"
            else:
                ok = all(o for o, _ in oks)
                rule = "every run"
            detail = "; ".join(d for _, d in oks)
            lines.append(f"  {'PASS' if ok else 'FAIL'}  {c:<22} ({rule}): {detail}")
    return "\n".join(lines)


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--mode", choices=list(MODES) + ["both"], default="both")
    ap.add_argument("--ai-seeds", type=int, nargs="+", default=[0, 1, 2])
    ap.add_argument("--sim-s", type=float, default=600.0)
    ap.add_argument("--player-brain", choices=sorted(PERSONALITIES),
                    default="steward")
    ap.add_argument("--config", default=None, help="path to a config.toml")
    args = ap.parse_args(argv)

    cfg = config.load(args.config) if args.config else config.load()
    modes = MODES if args.mode == "both" else (args.mode,)
    t0 = time.perf_counter()
    results = run_matrix(cfg, modes=modes, ai_seeds=tuple(args.ai_seeds),
                         sim_s=args.sim_s, player_brain=args.player_brain)
    print(report(results))
    print(f"\n{len(results)} rounds in {time.perf_counter() - t0:.1f}s wall")
    return 0


if __name__ == "__main__":
    sys.exit(main())
