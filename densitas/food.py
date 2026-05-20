"""Food field — tile-attribute food layer + per-biome regeneration.

See `Densitas_food.md` for the spec. Summary:

  * Per-tile `food: float32` array, same shape as `world.tiles`.
  * Biome dictates initial value (== cap) and regen rate per sim second.
  * Each citizen tick: `food = min(food + regen * dt, cap)`.
  * Consumed by citizens in EATING state via `consume(tx, ty, amount)`.

Mirrors `BeliefField` syntactically (recompute / query / grid / version)
so the renderer can treat them with the same shape.

The food field is the carrying-capacity mechanism: by limiting calorie
flow into the population, reproduction self-throttles long before the
exponential blowup we saw in P2 (132k citizens at sim_t 620s on default
seed; cured by gating mating on hunger and starving citizens that can't eat).
"""
from __future__ import annotations
from typing import Optional

import numpy as np

from .config import FoodConfig
from .world import World, Tile


# Biome -> (initial, regen) lookup, materialised at FoodField construction
# from cfg.biome. Tiles not listed implicitly carry (0.0, 0.0).
def _biome_table(cfg: FoodConfig) -> dict[int, tuple[float, float]]:
    b = cfg.biome
    return {
        int(Tile.FOREST):    (b.forest_initial,    b.forest_regen),
        int(Tile.GRASS):     (b.grass_initial,     b.grass_regen),
        int(Tile.BEACH):     (b.beach_initial,     b.beach_regen),
        int(Tile.HILL):      (b.hill_initial,      b.hill_regen),
        int(Tile.HOLY):      (b.holy_initial,      b.holy_regen),
        # WATER, MOUNTAIN, LAVA, BLIGHTED implicitly (0.0, 0.0).
    }


class FoodField:
    """Per-tile food layer. Vectorised regen + numpy-based forage search.

    Coordinates throughout are (tx, ty) integer world tiles. Indexing
    follows the rest of the codebase: arrays are (height, width) = (ty, tx).
    """

    def __init__(self, cfg: FoodConfig, world: World):
        self.cfg = cfg
        self.world_w = world.width
        self.world_h = world.height

        table = _biome_table(cfg)

        # Per-tile cap and regen-rate arrays, derived from the tile map.
        cap = np.zeros((world.height, world.width), dtype=np.float32)
        regen = np.zeros_like(cap)
        for tile_id, (init, rg) in table.items():
            mask = (world.tiles == tile_id)
            cap[mask] = init
            regen[mask] = rg

        self.cap = cap
        self.regen = regen
        # Start at cap. The first sim seconds happen on a full larder.
        self.food = cap.copy()
        # Bumps every recompute so the renderer can cache by version.
        self.version: int = 0

    # -- recompute ----------------------------------------------------------

    def recompute(self, dt: float) -> None:
        """Advance the field by `dt` sim seconds. Vectorised."""
        if dt <= 0.0:
            return
        # food = min(food + regen * dt, cap)
        np.add(self.food, self.regen * dt, out=self.food)
        np.minimum(self.food, self.cap, out=self.food)
        self.version += 1

    # -- queries ------------------------------------------------------------

    def query(self, tx: int, ty: int) -> float:
        """Food at the given world tile. Clamped at edges."""
        ix = max(0, min(self.world_w - 1, int(tx)))
        iy = max(0, min(self.world_h - 1, int(ty)))
        return float(self.food[iy, ix])

    def total(self) -> float:
        return float(self.food.sum())

    def peak(self) -> float:
        return float(self.food.max())

    def grid(self) -> np.ndarray:
        """Read-only view of the food grid."""
        return self.food

    # -- mutators -----------------------------------------------------------

    def consume(self, tx: int, ty: int, amount: float) -> float:
        """Consume up to `amount` units from the given tile.

        Returns the amount actually consumed (clamped if the tile didn't
        have enough). Tile food can never go negative.
        """
        ix = max(0, min(self.world_w - 1, int(tx)))
        iy = max(0, min(self.world_h - 1, int(ty)))
        available = float(self.food[iy, ix])
        taken = min(amount, available)
        if taken > 0.0:
            self.food[iy, ix] = available - taken
            # Mutation invalidates renderer cache.
            self.version += 1
        return taken

    # -- search -------------------------------------------------------------

    def find_nearest(self, tx: int, ty: int, radius: int,
                     min_food: float) -> Optional[tuple[int, int]]:
        """Find the nearest tile within `radius` with food >= `min_food`.

        Ties on distance are broken in favour of higher food. Returns
        (tx, ty) or None if no eligible tile in range.
        """
        x0 = max(0, int(tx) - radius)
        x1 = min(self.world_w, int(tx) + radius + 1)
        y0 = max(0, int(ty) - radius)
        y1 = min(self.world_h, int(ty) + radius + 1)
        if x0 >= x1 or y0 >= y1:
            return None
        window = self.food[y0:y1, x0:x1]
        eligible = window >= float(min_food)
        if not bool(eligible.any()):
            return None
        # Build a Chebyshev distance grid relative to (tx, ty).
        yy, xx = np.mgrid[y0:y1, x0:x1]
        dist = np.maximum(np.abs(xx - int(tx)), np.abs(yy - int(ty)))
        # Score: lower distance preferred, ties broken by higher food.
        # 1 / (1 + food) keeps the secondary key in (0, 1] so it doesn't
        # overwhelm the integer distance.
        scores = np.where(
            eligible,
            dist.astype(np.float32) + 1.0 / (1.0 + window),
            np.float32(np.inf),
        )
        flat = int(np.argmin(scores))
        iy, ix = np.unravel_index(flat, scores.shape)
        return (int(ix + x0), int(iy + y0))
