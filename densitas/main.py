"""Densitas - P2 entry point.

Tile map + camera + terrain render (P0) + citizens + HUD (P1) + belief field (P2).

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
from .citizen import CitizenManager
from .belief import BeliefField
from .hud import HUD


def main(argv: list[str] | None = None) -> int:
    cfg = config.load()

    pygame.init()
    pygame.display.set_caption("Densitas - P2")
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

    print(f"Spawning initial population ({cfg.citizen.initial_population})...")
    citizen_mgr = CitizenManager(cfg.citizen, world, world_seed=cfg.world.seed)
    print(f"  spawned {len(citizen_mgr.citizens)} citizens")

    print(f"Allocating belief field ({cfg.belief.grid_w}x{cfg.belief.grid_h})...")
    belief = BeliefField(cfg.belief, world)
    belief.recompute(citizen_mgr.citizens)
    print(f"  initial belief total: f0={belief.total(0):.2f}, f1={belief.total(1):.2f}")

    hud = HUD()

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
    show_belief_overlay = False  # toggle with B

    # Fixed-timestep accumulator for sim ticks at cfg.citizen.tick_hz
    tick_dt = 1.0 / max(1, cfg.citizen.tick_hz)
    sim_accumulator = 0.0
    sim_time = 0.0

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
                elif event.key == pygame.K_b:
                    show_belief_overlay = not show_belief_overlay

        keys = pygame.key.get_pressed()
        if pygame.mouse.get_focused():
            mouse_pos = pygame.mouse.get_pos()
        else:
            mouse_pos = (None, None)
        cam.update_from_input(keys, mouse_pos, dt)

        # Advance simulation at fixed 5 Hz, regardless of render rate.
        sim_accumulator += dt
        if sim_accumulator > 1.0:
            sim_accumulator = 1.0
        while sim_accumulator >= tick_dt:
            citizen_mgr.tick(tick_dt, world)
            belief.recompute(citizen_mgr.citizens)
            sim_accumulator -= tick_dt
            sim_time += tick_dt

        # Render
        screen.fill((0, 0, 0))
        renderer.blit_viewport(screen, world_surface, cam.x, cam.y)
        if show_belief_overlay:
            renderer.blit_belief_overlay(screen, belief, cam.x, cam.y)
        renderer.blit_citizens(screen, citizen_mgr.iter_for_render(), cam.x, cam.y, sim_time)
        if show_debug:
            _draw_debug(screen, font, clock, cam, cfg, citizen_mgr, belief,
                         sim_time, show_belief_overlay)
        hud.draw(screen, citizen_mgr, belief)
        pygame.display.flip()

    pygame.quit()
    return 0


def _draw_debug(screen: pygame.Surface, font: pygame.font.Font,
                 clock: pygame.time.Clock, cam: Camera, cfg,
                 cm: CitizenManager, belief: BeliefField,
                 sim_time: float, show_belief_overlay: bool) -> None:
    ts = cfg.render.tile_size
    tile_x = int((cam.x + cfg.render.viewport_w / 2) // ts)
    tile_y = int((cam.y + cfg.render.viewport_h / 2) // ts)
    bf_here = belief.query(tile_x, tile_y, 0)
    lines = [
        f"FPS:    {clock.get_fps():5.1f}    Sim t: {sim_time:7.1f}s",
        f"Cam:    ({cam.x:6.0f}, {cam.y:6.0f})  max ({cam.max_x:.0f}, {cam.max_y:.0f})",
        f"Center: tile ({tile_x}, {tile_y})   belief here: {bf_here:.3f}",
        f"Tile:   {ts}px   Style: {cfg.render.art_style}",
        f"World:  {cfg.world.width} x {cfg.world.height} tiles (seed {cfg.world.seed})",
        f"Citiz:  {cm.population(0):d} alive   list {len(cm.citizens):d}",
        f"Blief:  total f0={belief.total(0):.1f}  peak={belief.peak(0):.3f}  "
        f"overlay {'ON' if show_belief_overlay else 'off'} (B)",
        "WASD/arrows scroll - mouse edge scrolls - F3 debug - B belief - ESC quit",
    ]
    pad = 8
    line_h = font.get_linesize()
    box_w, box_h = 460, len(lines) * line_h + pad * 2
    overlay = pygame.Surface((box_w, box_h), pygame.SRCALPHA)
    overlay.fill((10, 10, 16, 200))
    screen.blit(overlay, (8, 8))
    for i, line in enumerate(lines):
        screen.blit(font.render(line, True, (216, 201, 168)),
                     (8 + pad, 8 + pad + i * line_h))


if __name__ == "__main__":
    sys.exit(main(sys.argv))
