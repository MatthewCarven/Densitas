"""Belief field — the 2D scalar density field that *is* divine power in Densitas.

See `Densitas_belief.md` for the spec. Summary:

  * Grid resolution `cfg.grid_w x cfg.grid_h` (default 64x48 over 256x192 world).
  * One float32 plane per faction.
  * Each citizen tick: zero the grid, splat amplitude per citizen at their
    belief cell, apply N passes of a 3-wide separable box blur.
  * Two passes ~ Gaussian sigma 1.4 cells. Box blur is volume-preserving so
    `total(faction) == population(faction)` (mod the dying-citizen fade).

P1.5 refinement: DYING citizens contribute *fractional* amplitude
`(state_timer / dying_duration)` so deaths fade out of the field smoothly
rather than dropping instantly. With `citizen.dying_duration = 2.0s`, this
makes mass-starvation visibly shrink the heatmap — the god slowly losing
belief, as Matthew put it.

Render path is in render.py; this module is render-agnostic.
"""
from __future__ import annotations
from typing import Iterable

import numpy as np

from .config import BeliefConfig
from .citizen import Citizen, CitizenState
from .world import World


# Faction count is fixed at 2 for P2 (Open Eye + Maw). When more gods exist,
# this becomes a config knob.
N_FACTIONS = 2


class BeliefField:
    """Per-faction 2D scalar field, recomputed from citizen positions.

    Coordinates:
      * `(world_tx, world_ty)` - integer world-tile coords.
      * `(cx, cy)`             - belief-cell coords.
    """

    def __init__(self, cfg: BeliefConfig, world: World, n_factions: int = N_FACTIONS,
                 dying_duration: float = 2.0):
        """`dying_duration` matches citizen.cfg so the DYING fade reads correctly.
        Defaulted to 2.0 (P1.5 value) for tests that don't pass a citizen cfg.
        """
        self.cfg = cfg
        self.world_w = world.width
        self.world_h = world.height
        self.n_factions = n_factions
        self.grid_w = cfg.grid_w
        self.grid_h = cfg.grid_h
        self.tiles_per_cell_x = max(1, world.width // cfg.grid_w)
        self.tiles_per_cell_y = max(1, world.height // cfg.grid_h)
        self.dying_duration = float(max(dying_duration, 1e-6))

        self.field = np.zeros(
            (n_factions, cfg.grid_h, cfg.grid_w), dtype=np.float32,
        )
        self._scratch = np.zeros_like(self.field)
        # Bumps every recompute so the renderer can cache by version.
        self.version: int = 0

    # -- recompute ----------------------------------------------------------

    def recompute(self, citizens: Iterable[Citizen]) -> None:
        self.field.fill(0.0)
        self._scatter(citizens)
        for _ in range(self.cfg.blur_passes):
            self._box_blur(self.cfg.blur_radius)
        self.version += 1

    def _scatter(self, citizens: Iterable[Citizen]) -> None:
        """Scatter per-citizen amplitude into the per-faction grid.

        DYING citizens contribute a fractional amplitude that decays linearly
        from full at moment-of-death to zero at removal. This produces the
        gradual belief shrinkage during mass mortality.
        """
        amp = float(self.cfg.amplitude)
        dying_d = self.dying_duration
        tpcx = self.tiles_per_cell_x
        tpcy = self.tiles_per_cell_y
        gw = self.grid_w
        gh = self.grid_h
        field = self.field
        for c in citizens:
            if c.state == CitizenState.DYING:
                # state_timer counts DOWN from dying_duration to 0.
                frac = c.state_timer / dying_d
                if frac < 0.0:
                    continue
                weight = amp * frac
            else:
                weight = amp
            cx = int(c.x) // tpcx
            cy = int(c.y) // tpcy
            if 0 <= cx < gw and 0 <= cy < gh and 0 <= c.faction < self.n_factions:
                field[c.faction, cy, cx] += weight

    def _box_blur(self, radius: int) -> None:
        if radius < 1:
            return
        k = 2 * radius + 1
        scratch = self._scratch
        field = self.field

        padded = np.pad(field, ((0, 0), (0, 0), (radius, radius)), mode="edge")
        csum = np.cumsum(padded, axis=2, dtype=np.float32)
        zero = np.zeros((field.shape[0], field.shape[1], 1), dtype=np.float32)
        csum_p = np.concatenate([zero, csum], axis=2)
        end = csum_p[..., 2 * radius + 1: 2 * radius + 1 + field.shape[2]]
        start = csum_p[..., 0:field.shape[2]]
        scratch[...] = (end - start) / float(k)

        padded = np.pad(scratch, ((0, 0), (radius, radius), (0, 0)), mode="edge")
        csum = np.cumsum(padded, axis=1, dtype=np.float32)
        zero = np.zeros((scratch.shape[0], 1, scratch.shape[2]), dtype=np.float32)
        csum_p = np.concatenate([zero, csum], axis=1)
        end = csum_p[:, 2 * radius + 1: 2 * radius + 1 + scratch.shape[1], :]
        start = csum_p[:, 0:scratch.shape[1], :]
        field[...] = (end - start) / float(k)

    # -- queries ------------------------------------------------------------

    def query(self, world_tx: int, world_ty: int, faction: int = 0) -> float:
        cx = max(0, min(self.grid_w - 1, int(world_tx) // self.tiles_per_cell_x))
        cy = max(0, min(self.grid_h - 1, int(world_ty) // self.tiles_per_cell_y))
        if not (0 <= faction < self.n_factions):
            return 0.0
        return float(self.field[faction, cy, cx])

    def total(self, faction: int = 0) -> float:
        if not (0 <= faction < self.n_factions):
            return 0.0
        return float(self.field[faction].sum())

    def dominant_faction(self, world_tx: int, world_ty: int) -> int | None:
        cx = max(0, min(self.grid_w - 1, int(world_tx) // self.tiles_per_cell_x))
        cy = max(0, min(self.grid_h - 1, int(world_ty) // self.tiles_per_cell_y))
        col = self.field[:, cy, cx]
        peak = col.max()
        if peak <= 0.0:
            return None
        winners = np.flatnonzero(col == peak)
        if winners.size != 1:
            return None
        return int(winners[0])

    def grid(self, faction: int = 0) -> np.ndarray:
        return self.field[faction]

    def peak(self, faction: int = 0) -> float:
        if not (0 <= faction < self.n_factions):
            return 0.0
        return float(self.field[faction].max())
