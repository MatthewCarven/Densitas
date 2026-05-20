"""Densitas P0 — tile map + camera + terrain render.

Run from the repo root with:
    python -m densitas.main
"""
from __future__ import annotations
import sys
import time
import pygame
from . import config
from .world import World
from .camera import Camera
from .render import make_renderer


def main(argv: list[str] | None = None) -> int:
    cfg = config.load()

    pygame.init()
    pygame.display.set_caption("Densitas — P0")
    screen = pygame.display.set_mode((cfg.render.viewport_w, cfg.render.viewport_h))
    clock = pygame.time.Clock()
    font = pygame.font.SysFont("consolas,menlo,monaco,monospace", 14)

    print(f"Generating world ({cfg.world.width}x{cfg.world.height}, seed={cfg.world.seed})...")
    t0 = time.perf_counter()
    world = World.generate(cfg.world)
    print(f"  world generated in {time.perf_counter() - t0:.2f}s")

    print(f"Building renderer ({cfg.render.art_style})...")
    t0 = time.perf_counter()
    renderer = make_renderer(cfg.render)
    print(f"  renderer built in {time.perf_counter() - t0:.2f}s")

    print("Pre-rendering world surface...")
    t0 = time.perf_counter()
    world_surface = renderer.build_world_surface(world)
    print(f"  world surface built in {time.perf_counter() - t0:.2f}s "
          f"({world_surface.get_width()}x{world_surface.get_height()} px)")

    # Center the camera initially
    cam = Camera(
        x=(world.width * cfg.render.tile_size - cfg.render.viewport_w) / 2.0,
        y=(world.height * cfg.render.tile_size - cfg.render.viewport_h) / 2.0,
        cfg=cfg.camera,
        render_cfg=cfg.render,
        world_cfg=cfg.world,
    )
    cam.clamp()

    show_debug = True
    running = True
    while running:
        dt = clock.tick(cfg.render.fps_target) / 1000.0

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    running = False
                elif event.key == pygame.K_F3:
                    show_debug = not show_debug

        keys = pygame.key.get_pressed()
        if pygame.mouse.get_focused():
            mouse_pos = pygame.mouse.get_pos()
        else:
            mouse_pos = (None, None)
        cam.update_from_input(keys, mouse_pos, dt)

        screen.fill((0, 0, 0))
        renderer.blit_viewport(screen, world_surface, cam.x, cam.y)
        if show_debug:
            _draw_debug(screen, font, clock, cam, cfg)
        pygame.display.flip()

    pygame.quit()
    return 0


def _draw_debug(screen: pygame.Surface, font: pygame.font.Font,
                 clock: pygame.time.Clock, cam: Camera, cfg) -> None:
    ts = cfg.render.tile_size
    tile_x = int((cam.x + cfg.render.viewport_w / 2) // ts)
    tile_y = int((cam.y + cfg.render.viewport_h / 2) // ts)
    lines = [
        f"FPS:    {clock.get_fps():5.1f}",
        f"Cam:    ({cam.x:6.0f}, {cam.y:6.0f})  max ({cam.max_x:.0f}, {cam.max_y:.0f})",
        f"Center: tile ({tile_x}, {tile_y})",
        f"Tile:   {ts}px   Style: {cfg.render.art_style}",
        f"World:  {cfg.world.width} x {cfg.world.height} tiles (seed {cfg.world.seed})",
        "WASD/arrows scroll · mouse edge scrolls · F3 debug · ESC quit",
    ]
    pad = 8
    line_h = font.get_linesize()
    box_w, box_h = 380, len(lines) * line_h + pad * 2
    overlay = pygame.Surface((box_w, box_h), pygame.SRCALPHA)
    overlay.fill((10, 10, 16, 200))
    screen.blit(overlay, (8, 8))
    for i, line in enumerate(lines):
        screen.blit(font.render(line, True, (216, 201, 168)),
                     (8 + pad, 8 + pad + i * line_h))


if __name__ == "__main__":
    sys.exit(main(sys.argv))
