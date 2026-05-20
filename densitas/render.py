"""Render — abstract Renderer + PixelRenderer implementation.

The Renderer interface is intentionally narrow so a future VectorRenderer
can be dropped in without touching world/camera/main code. Implementations
share the same `build_world_surface` and `blit_viewport` contract.
"""
from __future__ import annotations
import abc
import pygame
import numpy as np
from .world import World, Tile
from .config import RenderConfig


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


class Renderer(abc.ABC):
    """Abstract renderer. Implementations: PixelRenderer (active), VectorRenderer (todo)."""

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


class PixelRenderer(Renderer):
    """Pixel-art renderer. Each tile type has N procedurally-textured variants."""

    def __init__(self, cfg: RenderConfig, rng_seed: int = 0,
                 variants_per_tile: int = 4):
        super().__init__(cfg)
        self._rng = np.random.default_rng(rng_seed)
        self._tile_sprites: dict[Tile, list[pygame.Surface]] = {}
        self._build_tile_sprites(variants_per_tile)

    def _build_tile_sprites(self, variants_per_tile: int) -> None:
        ts = self.cfg.tile_size
        for tile, (base, detail, accent) in PIXEL_PALETTE.items():
            sprites: list[pygame.Surface] = []
            for _ in range(variants_per_tile):
                surf = pygame.Surface((ts, ts))
                surf.fill(base)
                noise = self._rng.random((ts, ts))
                # Vectorized pixel art: paint detail + accent layers in batch
                surf_arr = pygame.surfarray.pixels3d(surf)
                # pygame.surfarray returns (width, height, 3); transpose for ours
                detail_mask = noise.T > 0.65
                accent_mask = noise.T > 0.92
                surf_arr[detail_mask] = detail
                surf_arr[accent_mask] = accent
                del surf_arr  # release the surface lock
                sprites.append(surf)
            self._tile_sprites[tile] = sprites

    def build_world_surface(self, world: World) -> pygame.Surface:
        ts = self.cfg.tile_size
        surf = pygame.Surface((world.width * ts, world.height * ts))
        for y in range(world.height):
            for x in range(world.width):
                tile = Tile(world.tiles[y, x])
                variants = self._tile_sprites[tile]
                # Deterministic variant selection from coords
                idx = (x * 73856093 ^ y * 19349663 ^ int(tile) * 83492791) % len(variants)
                surf.blit(variants[idx], (x * ts, y * ts))
        return surf


def make_renderer(cfg: RenderConfig) -> Renderer:
    """Factory dispatching on cfg.art_style."""
    if cfg.art_style == "pixel":
        return PixelRenderer(cfg)
    if cfg.art_style == "vector":
        raise NotImplementedError(
            "VectorRenderer is on the TODO list. Use art_style = \"pixel\" for now."
        )
    raise ValueError(f"Unknown art_style: {cfg.art_style!r}")
