"""Belief field — the 2D scalar density field that *is* divine power in Densitas.

See `Densitas_belief.md` for the spec. Summary:

  * Grid resolution `cfg.grid_w x cfg.grid_h` (default 64x48 over 256x192 world).
  * One float32 plane per faction.
  * Each citizen tick: zero the grid, splat amplitude=1 per citizen at their
    belief cell, apply N passes of a 3-wide separable box blur.
  * Two passes ~ Gaussian sigma 1.4 cells. Box blur is volume-preserving so
    `total(faction) == population(faction)`.

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
      * `(world_tx, world_ty)` — integer world-tile coords.
      * `(cx, cy)`             — belief-cell coords.

      cx = world_tx // tiles_per_cell_x
      cy = world_ty // tiles_per_cell_y

    The grid dims are read from `BeliefConfig` and need not match the world
    dims exactly; cells past the world's extent stay zero.
    """

    def __init__(self, cfg: BeliefConfig, world: World, n_factions: int = N_FACTIONS):
        self.cfg = cfg
        self.world_w = world.width
        self.world_h = world.height
        self.n_factions = n_factions
        self.grid_w = cfg.grid_w
        self.grid_h = cfg.grid_h
        # Tiles per belief cell on each axis. World dims should divide cleanly
        # for the default 256x192 / 64x48 case; otherwise we round up which
        # leaves trailing cells partially empty.
        self.tiles_per_cell_x = max(1, world.width // cfg.grid_w)
        self.tiles_per_cell_y = max(1, world.height // cfg.grid_h)

        # (faction, y, x) layout — matches numpy row-major convention used
        # everywhere else in the codebase (world.tiles is also [y, x]).
        self.field = np.zeros(
            (n_factions, cfg.grid_h, cfg.grid_w), dtype=np.float32,
        )
        # Scratch buffer for blur to avoid per-tick allocation.
        self._scratch = np.zeros_like(self.field)
        # Bumps every recompute so the renderer can cache by version.
        self.version: int = 0

    # -- recompute ----------------------------------------------------------

    def recompute(self, citizens: Iterable[Citizen]) -> None:
        """Rebuild the field from current citizen positions.

        Order:
          1. zero the field
          2. scatter (amplitude per citizen into their cell, skipping DYING)
          3. blur N passes
        """
        self.field.fill(0.0)
        self._scatter(citizens)
        for _ in range(self.cfg.blur_passes):
            self._box_blur(self.cfg.blur_radius)
        self.version += 1

    def _scatter(self, citizens: Iterable[Citizen]) -> None:
        amp = float(self.cfg.amplitude)
        tpcx = self.tiles_per_cell_x
        tpcy = self.tiles_per_cell_y
        gw = self.grid_w
        gh = self.grid_h
        field = self.field
        for c in citizens:
            if c.state == CitizenState.DYING:
                continue
            # Citizen position is float tile-space. Convert to cell idx.
            cx = int(c.x) // tpcx
            cy = int(c.y) // tpcy
            if 0 <= cx < gw and 0 <= cy < gh and 0 <= c.faction < self.n_factions:
                field[c.faction, cy, cx] += amp

    def _box_blur(self, radius: int) -> None:
        """In-place separable box blur with `radius=1` => 3-cell window.

        Volume-preserving: dividing by kernel size keeps the integral.
        Edges use reflection (replicate the edge sample) which is fine for
        this scale; the bias near boundaries is negligible at radius 1-2.
        """
        if radius < 1:
            return
        k = 2 * radius + 1
        scratch = self._scratch
        # Horizontal pass: field -> scratch
        # cumulative-sum trick: window sum at i = csum[i+r+1] - csum[i-r]
        # We pad with edge values for reflection.
        field = self.field
        # numpy can blur all factions at once thanks to leading axis.
        # Pad on the x-axis.
        padded = np.pad(
            field, ((0, 0), (0, 0), (radius, radius)),
            mode="edge",
        )
        # Cumulative sum along x.
        csum = np.cumsum(padded, axis=2, dtype=np.float32)
        # csum has shape (F, H, W + 2r). Window sum at output column i:
        #   csum[..., i + 2r] - csum[..., i - 1]  with csum[..., -1] = 0.
        # Use a zero-prepend to handle the i=0 case without branching.
        zero = np.zeros((field.shape[0], field.shape[1], 1), dtype=np.float32)
        csum_p = np.concatenate([zero, csum], axis=2)
        # Now window-sum at output col i = csum_p[..., i + 2r + 1] - csum_p[..., i]
        end = csum_p[..., 2 * radius + 1: 2 * radius + 1 + field.shape[2]]
        start = csum_p[..., 0:field.shape[2]]
        scratch[...] = (end - start) / float(k)

        # Vertical pass: scratch -> field
        padded = np.pad(
            scratch, ((0, 0), (radius, radius), (0, 0)),
            mode="edge",
        )
        csum = np.cumsum(padded, axis=1, dtype=np.float32)
        zero = np.zeros((scratch.shape[0], 1, scratch.shape[2]), dtype=np.float32)
        csum_p = np.concatenate([zero, csum], axis=1)
        end = csum_p[:, 2 * radius + 1: 2 * radius + 1 + scratch.shape[1], :]
        start = csum_p[:, 0:scratch.shape[1], :]
        field[...] = (end - start) / float(k)

    # -- queries ------------------------------------------------------------

    def query(self, world_tx: int, world_ty: int, faction: int = 0) -> float:
        """Belief at the given world tile for `faction`. Clamped at edges."""
        cx = max(0, min(self.grid_w - 1, int(world_tx) // self.tiles_per_cell_x))
        cy = max(0, min(self.grid_h - 1, int(world_ty) // self.tiles_per_cell_y))
        if not (0 <= faction < self.n_factions):
            return 0.0
        return float(self.field[faction, cy, cx])

    def total(self, faction: int = 0) -> float:
        """Sum over the field for `faction`. Equals population (within float drift)."""
        if not (0 <= faction < self.n_factions):
            return 0.0
        return float(self.field[faction].sum())

    def dominant_faction(self, world_tx: int, world_ty: int) -> int | None:
        """Which faction has greater belief here, or None if tied or both zero.

        Stubbed for P2 — wired up in P3 (relic shatter) and P4 (CONVERTED state).
        """
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
        """Read-only view of the per-faction grid.

        The caller (renderer) must not mutate. Returning the live array lets
        the overlay surface be built without copying.
        """
        return self.field[faction]

    def peak(self, faction: int = 0) -> float:
        """Max value across the per-faction grid (for alpha scaling in overlay)."""
        if not (0 <= faction < self.n_factions):
            return 0.0
        return float(self.field[faction].max())
