"""Unit tests for world generation and camera math.

Run from the repo root with:
    python -m pytest tests/
or directly:
    python tests/test_world.py
"""
from __future__ import annotations
import os
import sys
import numpy as np

# Allow running this file directly (without pytest):
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from densitas.world import World, Tile
from densitas.config import WorldConfig, RenderConfig, CameraConfig
from densitas.camera import Camera


def _world_cfg() -> WorldConfig:
    return WorldConfig(
        width=64, height=48, seed=42,
        sea_level=0.30, beach_thresh=0.34,
        forest_thresh=0.55, hill_thresh=0.70,
        mountain_thresh=0.85,
    )


def _render_cfg() -> RenderConfig:
    return RenderConfig(
        art_style="pixel", tile_size=16,
        viewport_w=320, viewport_h=240, fps_target=60,
    )


def _camera_cfg() -> CameraConfig:
    return CameraConfig(scroll_speed=12.0, edge_scroll_px=24)


def test_world_dimensions():
    world = World.generate(_world_cfg())
    assert world.tiles.shape == (48, 64)
    assert world.heightmap.shape == (48, 64)
    assert world.width == 64 and world.height == 48


def test_world_has_variety():
    world = World.generate(_world_cfg())
    counts = {t: int(np.sum(world.tiles == int(t))) for t in Tile}
    # We expect water (from vignette/edges) and at least some land.
    assert counts[Tile.WATER] > 0, f"expected water; got {counts}"
    assert counts[Tile.GRASS] + counts[Tile.FOREST] > 0, f"expected land; got {counts}"
    # Total accounted for
    assert sum(counts.values()) == 48 * 64


def test_world_is_deterministic():
    a = World.generate(_world_cfg())
    b = World.generate(_world_cfg())
    assert np.array_equal(a.tiles, b.tiles)
    assert np.array_equal(a.heightmap, b.heightmap)


def test_world_changes_with_seed():
    cfg_a = _world_cfg()
    cfg_b = WorldConfig(**{**cfg_a.__dict__, "seed": 1337})
    a = World.generate(cfg_a)
    b = World.generate(cfg_b)
    assert not np.array_equal(a.tiles, b.tiles), "different seeds should produce different worlds"


def test_in_bounds():
    world = World.generate(_world_cfg())
    assert world.in_bounds(0, 0)
    assert world.in_bounds(63, 47)
    assert not world.in_bounds(64, 0)
    assert not world.in_bounds(-1, 0)
    assert not world.in_bounds(0, 48)


def test_camera_clamps_to_world_bounds():
    cam = Camera(x=-100.0, y=99999.0,
                  cfg=_camera_cfg(),
                  render_cfg=_render_cfg(),
                  world_cfg=_world_cfg())
    cam.clamp()
    assert cam.x >= 0
    assert cam.y <= cam.max_y


def test_camera_max_bounds():
    cam = Camera(x=0, y=0, cfg=_camera_cfg(),
                  render_cfg=_render_cfg(), world_cfg=_world_cfg())
    # World is 64x48 tiles * 16px = 1024x768.  Viewport is 320x240.
    # max_x = 1024 - 320 = 704, max_y = 768 - 240 = 528.
    assert cam.max_x == 704
    assert cam.max_y == 528


def test_tile_from_height_partitions_unit_interval():
    cfg = _world_cfg()
    assert Tile.from_height(0.0,  cfg) == Tile.WATER
    assert Tile.from_height(0.29, cfg) == Tile.WATER
    assert Tile.from_height(0.32, cfg) == Tile.BEACH
    assert Tile.from_height(0.40, cfg) == Tile.GRASS
    assert Tile.from_height(0.60, cfg) == Tile.FOREST
    assert Tile.from_height(0.75, cfg) == Tile.HILL
    assert Tile.from_height(0.90, cfg) == Tile.MOUNTAIN
    assert Tile.from_height(1.0,  cfg) == Tile.MOUNTAIN


if __name__ == "__main__":
    tests = [
        test_world_dimensions,
        test_world_has_variety,
        test_world_is_deterministic,
        test_world_changes_with_seed,
        test_in_bounds,
        test_camera_clamps_to_world_bounds,
        test_camera_max_bounds,
        test_tile_from_height_partitions_unit_interval,
    ]
    for t in tests:
        t()
        print(f"  OK  {t.__name__}")
    print(f"\n{len(tests)} tests passed.")
