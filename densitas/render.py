"""Render — abstract Renderer + PixelRenderer implementation.

The Renderer interface is intentionally narrow so a future VectorRenderer
can be dropped in without touching world/camera/main code. Implementations
share the same `build_world_surface`, `blit_viewport`, `blit_citizens`,
and `blit_belief_overlay` contract.
"""
from __future__ import annotations
import abc
import pygame
import numpy as np
from typing import Iterable
from .world import World, Tile
from .config import RenderConfig
from .citizen import Citizen, CitizenState, Facing


# Pixel-art tile palette. Each tile has (base, detail, accent) colors.
# Procedural tile sprites are painted at startup from these triples.
PIXEL_PALETTE: dict[Tile, tuple[tuple[int, int, int],
                                tuple[int, int, int],
                                tuple[int, int, int]]] = {
    Tile.WATER:    ((28, 60, 100),   (44, 80, 130),   (60, 100, 160)),
    Tile.BEACH:    ((220, 200, 150), (200, 180, 130), (240, 220, 170)),
    Tile.GRASS:    ((70, 110, 50),   (90, 140, 60),   (110, 160, 70)),
    Tile.FOREST:   ((30, 70, 30),    (50, 100, 40),   (80, 130, 50)),
    Tile.HILL:     ((100, 90, 60),   (140, 130, 90),  (170, 160, 110)),
    Tile.MOUNTAIN: ((110, 110, 120), (150, 150, 160), (200, 200, 210)),
    Tile.LAVA:     ((180, 50, 20),   (220, 100, 30),  (250, 200, 40)),
    Tile.BLIGHTED: ((60, 50, 50),    (80, 60, 60),    (100, 80, 80)),
    Tile.HOLY:     ((240, 230, 180), (255, 250, 210), (255, 255, 230)),
}

# Citizen sprite palette per faction.
# (skin, robe, accent, outline) - outline doubles as foot shadow.
CITIZEN_PALETTE: dict[int, tuple[tuple[int, int, int], tuple[int, int, int],
                                  tuple[int, int, int], tuple[int, int, int]]] = {
    # Faction 0 = Open Eye (player). Parchment robe + cyan accent.
    0: ((230, 200, 170), (220, 210, 180), (90, 200, 220), (30, 28, 30)),
    # Faction 1 = Maw (rival). Bone robe + blood accent.
    1: ((210, 190, 170), (190, 180, 170), (160, 30, 30), (30, 28, 30)),
}

CITIZEN_W = 8    # sprite width in pixels
CITIZEN_H = 16   # sprite height in pixels

# Belief overlay tints per faction (R,G,B). Alpha is computed per cell from
# field magnitude.
BELIEF_TINT: dict[int, tuple[int, int, int]] = {
    0: (90, 200, 220),   # Open Eye - cyan
    1: (220, 60, 60),    # Maw - red
}


class Renderer(abc.ABC):
    """Abstract renderer.

    Implementations:
      PixelRenderer  - active.
      VectorRenderer - todo. Subclass and add a branch to make_renderer().
    """

    def __init__(self, cfg: RenderConfig):
        self.cfg = cfg

    @property
    def tile_size(self) -> int:
        return self.cfg.tile_size

    @abc.abstractmethod
    def build_world_surface(self, world: World) -> pygame.Surface:
        """Pre-render the entire world to a Surface. Called once at world load."""
        ...

    def blit_viewport(self, screen: pygame.Surface, world_surface: pygame.Surface,
                       cam_x: float, cam_y: float) -> None:
        """Blit the visible portion of the world surface to the screen."""
        screen.blit(
            world_surface,
            (0, 0),
            area=pygame.Rect(int(cam_x), int(cam_y),
                              self.cfg.viewport_w, self.cfg.viewport_h),
        )

    @abc.abstractmethod
    def blit_citizens(self, screen: pygame.Surface, citizens: Iterable[Citizen],
                       cam_x: float, cam_y: float, sim_time: float = 0.0) -> None:
        """Blit citizens on top of the already-drawn viewport.
        `sim_time` (sim seconds) drives walk-frame selection.
        """
        ...

    @abc.abstractmethod
    def blit_belief_overlay(self, screen: pygame.Surface, belief,
                             cam_x: float, cam_y: float) -> None:
        """Blit a heatmap of the belief field over the viewport.
        `belief` is a BeliefField. Implementations cache by belief.version.
        """
        ...


class PixelRenderer(Renderer):
    """Pixel-art renderer.

    Each tile type has N procedurally-textured variants.
    Each citizen faction has (Facing x 2 walk frames + 1 idle) sprites.
    """

    def __init__(self, cfg: RenderConfig, rng_seed: int = 0,
                 variants_per_tile: int = 4):
        super().__init__(cfg)
        self._rng = np.random.default_rng(rng_seed)
        self._tile_sprites: dict[Tile, list[pygame.Surface]] = {}
        self._build_tile_sprites(variants_per_tile)
        # citizen_sprites[(faction, facing, frame)] = Surface
        # frame: 0 = idle, 1 = walk-A, 2 = walk-B
        self._citizen_sprites: dict[tuple[int, int, int], pygame.Surface] = {}
        self._build_citizen_sprites()
        # Belief overlay cache: rebuilt on belief.version change.
        self._belief_cache_version: int = -1
        self._belief_overlay_world: pygame.Surface | None = None

    # -- tile sprites -------------------------------------------------------

    def _build_tile_sprites(self, variants_per_tile: int) -> None:
        ts = self.cfg.tile_size
        for tile, (base, detail, accent) in PIXEL_PALETTE.items():
            sprites: list[pygame.Surface] = []
            for _ in range(variants_per_tile):
                surf = pygame.Surface((ts, ts))
                surf.fill(base)
                noise = self._rng.random((ts, ts))
                surf_arr = pygame.surfarray.pixels3d(surf)
                detail_mask = noise.T > 0.65
                accent_mask = noise.T > 0.92
                surf_arr[detail_mask] = detail
                surf_arr[accent_mask] = accent
                del surf_arr
                sprites.append(surf)
            self._tile_sprites[tile] = sprites

    def build_world_surface(self, world: World) -> pygame.Surface:
        ts = self.cfg.tile_size
        surf = pygame.Surface((world.width * ts, world.height * ts))
        for y in range(world.height):
            for x in range(world.width):
                tile = Tile(world.tiles[y, x])
                variants = self._tile_sprites[tile]
                idx = (x * 73856093 ^ y * 19349663 ^ int(tile) * 83492791) % len(variants)
                surf.blit(variants[idx], (x * ts, y * ts))
        return surf

    # -- citizen sprites ----------------------------------------------------

    def _build_citizen_sprites(self) -> None:
        for faction, (skin, robe, accent, outline) in CITIZEN_PALETTE.items():
            for facing in Facing:
                for frame in range(3):
                    surf = self._paint_citizen(faction, facing, frame,
                                                skin, robe, accent, outline)
                    self._citizen_sprites[(faction, int(facing), frame)] = surf

    @staticmethod
    def _paint_citizen(faction: int, facing: Facing, frame: int,
                        skin, robe, accent, outline) -> pygame.Surface:
        surf = pygame.Surface((CITIZEN_W, CITIZEN_H), pygame.SRCALPHA)
        surf.fill((0, 0, 0, 0))

        def px(x: int, y: int, c) -> None:
            if 0 <= x < CITIZEN_W and 0 <= y < CITIZEN_H:
                surf.set_at((x, y), c)

        # --- Head (rows 0-3) ---
        for hy in range(0, 4):
            for hx in range(2, 6):
                px(hx, hy, skin)
        for hy in range(0, 4):
            px(1, hy, outline)
            px(6, hy, outline)
        px(2, 0, outline); px(5, 0, outline)

        if facing == Facing.SOUTH:
            px(3, 2, outline); px(4, 2, outline)
        elif facing == Facing.NORTH:
            for hx in range(2, 6):
                px(hx, 1, accent)
        elif facing == Facing.EAST:
            px(4, 2, outline); px(5, 2, outline)
        elif facing == Facing.WEST:
            px(2, 2, outline); px(3, 2, outline)

        # --- Torso (rows 4-9) ---
        for ty in range(4, 10):
            for tx in range(1, 7):
                px(tx, ty, robe)
        for ty in range(4, 10):
            px(1, ty, outline)
            px(6, ty, outline)
        px(3, 5, accent); px(4, 5, accent)
        px(3, 7, accent); px(4, 7, accent)

        if facing in (Facing.SOUTH, Facing.NORTH):
            for ay in range(5, 9):
                px(0, ay, robe); px(7, ay, robe)
            px(0, 9, skin); px(7, 9, skin)
        elif facing == Facing.EAST:
            for ay in range(5, 9):
                px(7, ay, robe)
            px(7, 9, skin)
        elif facing == Facing.WEST:
            for ay in range(5, 9):
                px(0, ay, robe)
            px(0, 9, skin)

        # --- Legs (rows 10-13) ---
        if frame == 0:
            for ly in range(10, 14):
                for lx in range(2, 4):
                    px(lx, ly, robe)
                for lx in range(4, 6):
                    px(lx, ly, robe)
        elif frame == 1:
            for ly in range(10, 13):
                for lx in range(2, 4):
                    px(lx, ly, robe)
            for ly in range(11, 14):
                for lx in range(4, 6):
                    px(lx, ly, robe)
        else:
            for ly in range(11, 14):
                for lx in range(2, 4):
                    px(lx, ly, robe)
            for ly in range(10, 13):
                for lx in range(4, 6):
                    px(lx, ly, robe)

        for fy in (14, 15):
            for fx in range(2, 6):
                px(fx, fy, outline)

        return surf

    # -- citizen blit -------------------------------------------------------

    def blit_citizens(self, screen: pygame.Surface, citizens: Iterable[Citizen],
                       cam_x: float, cam_y: float, sim_time: float = 0.0) -> None:
        ts = self.cfg.tile_size
        vw, vh = self.cfg.viewport_w, self.cfg.viewport_h
        cx_int = int(cam_x)
        cy_int = int(cam_y)
        sprites = self._citizen_sprites
        blit = screen.blit
        for c in citizens:
            wx = int(c.x * ts) - cx_int + (ts - CITIZEN_W) // 2
            wy = int(c.y * ts) - cy_int + (ts - CITIZEN_H)
            if wx + CITIZEN_W < 0 or wy + CITIZEN_H < 0 or wx >= vw or wy >= vh:
                continue
            if c.state == CitizenState.WANDER:
                frame = 1 if (int(sim_time / 0.25) + c.id) & 1 else 2
            else:
                frame = 0
            sprite = sprites.get((c.faction, int(c.facing), frame))
            if sprite is None:
                sprite = sprites[(0, int(Facing.SOUTH), 0)]
            blit(sprite, (wx, wy))

    # -- belief overlay ----------------------------------------------------

    def blit_belief_overlay(self, screen: pygame.Surface, belief,
                             cam_x: float, cam_y: float) -> None:
        """Build (cached) a world-pixel-sized RGBA overlay, blit visible region.

        Cache invalidates on belief.version change. Rebuild path:
          1. compute per-cell RGB by faction-weighted blend
          2. compute per-cell alpha from max field across factions
          3. construct 64x48 RGBA surface
          4. nearest-neighbor scale up to world pixel dims
        """
        if belief.version != self._belief_cache_version or self._belief_overlay_world is None:
            self._belief_overlay_world = self._build_belief_overlay_world(belief)
            self._belief_cache_version = belief.version
        screen.blit(
            self._belief_overlay_world,
            (0, 0),
            area=pygame.Rect(int(cam_x), int(cam_y),
                              self.cfg.viewport_w, self.cfg.viewport_h),
        )

    def _build_belief_overlay_world(self, belief) -> pygame.Surface:
        """Construct the cell-resolution overlay then nearest-scale to world px."""
        gw = belief.grid_w
        gh = belief.grid_h
        # Per-faction peaks for alpha normalization. Use a small epsilon floor
        # so a single citizen still produces a visible blob.
        peaks = [max(belief.peak(f), 1e-3) for f in range(belief.n_factions)]
        # Build (gh, gw, 4) uint8 array.
        rgba = np.zeros((gh, gw, 4), dtype=np.float32)
        max_mass = np.zeros((gh, gw), dtype=np.float32)
        total_weight = np.zeros((gh, gw), dtype=np.float32)
        for f in range(belief.n_factions):
            grid = belief.grid(f)  # (gh, gw) float32
            tint = BELIEF_TINT.get(f, (200, 200, 200))
            # Normalize per faction: 0..1 by peak
            w = grid / peaks[f]
            np.clip(w, 0.0, 1.0, out=w)
            rgba[..., 0] += w * tint[0]
            rgba[..., 1] += w * tint[1]
            rgba[..., 2] += w * tint[2]
            total_weight += w
            np.maximum(max_mass, w, out=max_mass)
        # Average the RGB by total weight so a single faction at peak doesn't
        # double-saturate when factions overlap.
        nz = total_weight > 0.0
        rgba[nz, 0] /= total_weight[nz]
        rgba[nz, 1] /= total_weight[nz]
        rgba[nz, 2] /= total_weight[nz]
        # Alpha from the dominant faction's normalized magnitude.
        # overlay_alpha_max is read off belief.cfg.
        alpha_max = float(belief.cfg.overlay_alpha_max)
        rgba[..., 3] = max_mass * alpha_max
        rgba_u8 = rgba.clip(0, 255).astype(np.uint8)
        # Build a (gw, gh) Surface from the (gh, gw, 4) array. pygame uses
        # (width, height) for surfaces but numpy is (rows=h, cols=w).
        small = pygame.image.frombuffer(
            rgba_u8.tobytes(), (gw, gh), "RGBA",
        ).convert_alpha()
        # Scale up to world pixel resolution.
        ts = self.cfg.tile_size
        world_w_px = belief.world_w * ts
        world_h_px = belief.world_h * ts
        return pygame.transform.scale(small, (world_w_px, world_h_px))


def make_renderer(cfg: RenderConfig) -> Renderer:
    """Factory dispatching on cfg.art_style."""
    if cfg.art_style == "pixel":
        return PixelRenderer(cfg)
    if cfg.art_style == "vector":
        raise NotImplementedError(
            "VectorRenderer is on the TODO list. Use art_style = \"pixel\" for now."
        )
    raise ValueError(f"Unknown art_style: {cfg.art_style!r}")
