"""Densitas - P3 PR2 entry point.

Tile map + camera + terrain (P0) + citizens + HUD (P1) + belief field (P2)
+ food/forage/hunger (P1.5) + Powers T0/T1 + Bless/Curse (P3 PR1)
+ Raise/Lower terrain mutation + drown rule (P3 PR2).

Run from the repo root with:
    python -m densitas.main
    python -m densitas.main --rival-stub-seed 12    # spawn 12 rival citizens for testing

Number keys 1-7 pick a power mode:
    1 Inspire   2 Calm        3 Hunger Pang
    4 Raise     5 Lower       6 Bless        7 Curse
Left-click to cast; right-click or Esc to cancel mode.
"""
from __future__ import annotations
import sys
import time
from typing import Optional

import pygame

from . import config
from .world import World, mutate_tile as world_mutate_tile, is_walkable_tile
from .camera import Camera
from .render import make_renderer
from .citizen import CitizenManager
from .belief import BeliefField
from .food import FoodField
from .hud import HUD
from .powers import PowerSystem, PowerKind, POWERS
from .rhetoric import Rhetoric, make_picker


# Keyboard bindings for power-mode selection. (Pygame keysym -> PowerKind)
POWER_KEYS: dict[int, PowerKind] = {
    pygame.K_1: PowerKind.INSPIRE,
    pygame.K_2: PowerKind.CALM,
    pygame.K_3: PowerKind.HUNGER_PANG,
    pygame.K_4: PowerKind.RAISE,
    pygame.K_5: PowerKind.LOWER,
    pygame.K_6: PowerKind.BLESS,
    pygame.K_7: PowerKind.CURSE,
}


def parse_args(argv: list[str]) -> dict:
    """Tiny arg parser — argparse would be overkill for one flag."""
    out = {"rival_stub_seed": 0}
    i = 1
    while i < len(argv):
        a = argv[i]
        if a == "--rival-stub-seed":
            i += 1
            try:
                out["rival_stub_seed"] = int(argv[i])
            except (IndexError, ValueError):
                print(f"warning: --rival-stub-seed expects an integer; ignoring", file=sys.stderr)
            i += 1
            continue
        if a in ("--help", "-h"):
            print(__doc__)
            sys.exit(0)
        # Skip unknowns silently — pygame.main might inherit argv.
        i += 1
    return out


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv
    args = parse_args(argv)
    cfg = config.load()

    pygame.init()
    pygame.display.set_caption("Densitas - P3 PR2")
    screen = pygame.display.set_mode((cfg.render.viewport_w, cfg.render.viewport_h))
    clock = pygame.time.Clock()
    font = pygame.font.SysFont("consolas,menlo,monaco,monospace", 14)
    cast_chip_font = pygame.font.SysFont("consolas,menlo,monaco,monospace", 13, bold=True)

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

    print("Allocating food field...")
    food = FoodField(cfg.food, world)
    print(f"  food cap total: {food.cap.sum():.0f}, "
          f"peak: {food.cap.max():.1f}")

    print(f"Spawning initial population ({cfg.citizen.initial_population})...")
    citizen_mgr = CitizenManager(cfg.citizen, world, world_seed=cfg.world.seed,
                                  food_cfg=cfg.food)
    print(f"  spawned {len(citizen_mgr.citizens)} citizens")

    # P3 — optional rival stub for live testing of multi-faction codepaths.
    if args["rival_stub_seed"] > 0:
        placed = citizen_mgr.spawn_rival_stub(
            world, n=args["rival_stub_seed"],
            faction=1, seed=cfg.world.seed,
        )
        print(f"  +{placed} rival-faction citizens (--rival-stub-seed)")

    print(f"Allocating belief field ({cfg.belief.grid_w}x{cfg.belief.grid_h})...")
    belief = BeliefField(cfg.belief, world,
                          dying_duration=cfg.citizen.dying_duration)
    belief.recompute(citizen_mgr.citizens)
    print(f"  initial belief total: f0={belief.total(0):.2f}, f1={belief.total(1):.2f}")

    print("Loading rhetoric pool...")
    try:
        rhet = Rhetoric.from_file(seed=cfg.world.seed)
        print(f"  rhetoric pool ready ({len(rhet._pool)} power keys)")
    except FileNotFoundError:
        print("  WARNING: rhetoric.json missing; scripture log will show placeholders")
        rhet = Rhetoric({}, seed=cfg.world.seed)

    print("Wiring power system...")

    # P3 PR2 — terrain mutation callback. Closes over world / food / renderer
    # / world_surface / citizen_mgr so PowerSystem doesn't have to know about
    # any of them. The drown rule (spec §5.3) runs here, *after* the world /
    # food / surface have been updated — so the belief field on the next
    # tick sees both the new tile and the now-DYING citizens.
    def _mutate_tile_cb(tx: int, ty: int, new_tile: int) -> bool:
        def _repaint(w, tx_, ty_):
            renderer.repaint_tile(world_surface, w, tx_, ty_)
        changed = world_mutate_tile(world, food, _repaint, tx, ty, new_tile)
        if changed and not is_walkable_tile(int(world.tiles[ty, tx])):
            citizen_mgr.drown_at(tx, ty, cfg.citizen.dying_duration)
        return changed

    power_system = PowerSystem(
        cfg.powers,
        n_factions=2,
        rhetoric_pick=make_picker(rhet),
        mutate_tile=_mutate_tile_cb,
    )

    hud = HUD()

    cam = Camera(
        x=(world.width * cfg.render.tile_size - cfg.render.viewport_w) / 2.0,
        y=(world.height * cfg.render.tile_size - cfg.render.viewport_h) / 2.0,
        cfg=cfg.camera,
        render_cfg=cfg.render,
        world_cfg=cfg.world,
    )
    cam.clamp()

    show_debug = True
    show_belief_overlay = False
    show_food_overlay = False
    active_mode: Optional[PowerKind] = None
    last_cast_failed_at: float = -1.0  # for HUD flash (used in debug overlay)
    last_cast_reason: str = ""

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
                    if active_mode is not None:
                        active_mode = None
                    else:
                        running = False
                elif event.key == pygame.K_F3:
                    show_debug = not show_debug
                elif event.key == pygame.K_b:
                    show_belief_overlay = not show_belief_overlay
                elif event.key == pygame.K_f:
                    show_food_overlay = not show_food_overlay
                elif event.key in POWER_KEYS:
                    active_mode = POWER_KEYS[event.key]
            elif event.type == pygame.MOUSEBUTTONDOWN:
                if event.button == 1 and active_mode is not None:
                    mx, my = event.pos
                    tx, ty = _screen_to_tile(mx, my, cam, cfg)
                    receipt = power_system.cast(
                        kind=active_mode, faction=0,
                        tx=tx, ty=ty,
                        citizens=citizen_mgr, world=world, food=food,
                        belief=belief, sim_t=sim_time,
                    )
                    if not receipt.ok:
                        last_cast_failed_at = sim_time
                        last_cast_reason = receipt.reason
                elif event.button == 3:
                    active_mode = None

        keys = pygame.key.get_pressed()
        if pygame.mouse.get_focused():
            mouse_pos = pygame.mouse.get_pos()
        else:
            mouse_pos = (None, None)
        cam.update_from_input(keys, mouse_pos, dt)

        sim_accumulator += dt
        if sim_accumulator > 1.0:
            sim_accumulator = 1.0
        while sim_accumulator >= tick_dt:
            # Order matters: tick effects first so food.recompute sees them.
            power_system.tick(tick_dt, citizen_mgr, sim_time)
            food.recompute(tick_dt, effects=power_system.effects)
            citizen_mgr.tick(tick_dt, world, food)
            belief.recompute(citizen_mgr.citizens)
            sim_accumulator -= tick_dt
            sim_time += tick_dt

        screen.fill((0, 0, 0))
        renderer.blit_viewport(screen, world_surface, cam.x, cam.y)
        if show_food_overlay:
            renderer.blit_food_overlay(screen, food, cam.x, cam.y)
        if show_belief_overlay:
            renderer.blit_belief_overlay(screen, belief, cam.x, cam.y)
        renderer.blit_citizens(screen, citizen_mgr.iter_for_render(), cam.x, cam.y, sim_time)

        # Cast preview (P3) — draw above citizens, below HUD.
        if active_mode is not None and pygame.mouse.get_focused():
            mx, my = pygame.mouse.get_pos()
            tx, ty = _screen_to_tile(mx, my, cam, cfg)
            if world.in_bounds(tx, ty):
                spec = POWERS[active_mode]
                ok, reason = power_system.can_cast(
                    active_mode, faction=0, tx=tx, ty=ty,
                    citizens=citizen_mgr, world=world,
                )
                renderer.blit_cast_preview(
                    screen, spec, tx, ty, ok, reason,
                    cam.x, cam.y, cast_chip_font,
                )

        if show_debug:
            _draw_debug(screen, font, clock, cam, cfg, citizen_mgr, belief, food,
                         power_system, active_mode, sim_time,
                         show_belief_overlay, show_food_overlay,
                         last_cast_failed_at, last_cast_reason)
        hud.draw(screen, citizen_mgr, belief,
                  powers=power_system, sim_t=sim_time,
                  active_mode=(int(active_mode) if active_mode is not None else None))
        pygame.display.flip()

    pygame.quit()
    return 0


def _screen_to_tile(mx: int, my: int, cam, cfg) -> tuple[int, int]:
    ts = cfg.render.tile_size
    tx = int((cam.x + mx) // ts)
    ty = int((cam.y + my) // ts)
    return tx, ty


def _draw_debug(screen, font, clock, cam, cfg, cm, belief, food,
                 ps, active_mode, sim_time, show_belief, show_food,
                 last_cast_failed_at: float, last_cast_reason: str) -> None:
    ts = cfg.render.tile_size
    tile_x = int((cam.x + cfg.render.viewport_w / 2) // ts)
    tile_y = int((cam.y + cfg.render.viewport_h / 2) // ts)
    bf_here = belief.query(tile_x, tile_y, 0)
    food_here = food.query(tile_x, tile_y)
    fed, hungry, starving, avg = cm.hunger_stats(0)
    mode_name = POWERS[active_mode].name if active_mode is not None else "—"
    pool0 = ps.pool[0]
    pool1 = ps.pool[1] if len(ps.pool) > 1 else 0.0
    err_line = ""
    if last_cast_reason and last_cast_failed_at >= 0.0 and sim_time - last_cast_failed_at < 2.0:
        err_line = f"last fail: {last_cast_reason}"
    lines = [
        f"FPS:    {clock.get_fps():5.1f}    Sim t: {sim_time:7.1f}s",
        f"Cam:    ({cam.x:6.0f}, {cam.y:6.0f})  max ({cam.max_x:.0f}, {cam.max_y:.0f})",
        f"Center: tile ({tile_x}, {tile_y})   belief: {bf_here:.3f}  food: {food_here:.2f}",
        f"World:  {cfg.world.width} x {cfg.world.height}  seed {cfg.world.seed}  style: {cfg.render.art_style}",
        f"Citiz:  f0 {cm.population(0):d}  f1 {cm.population(1):d}  list {len(cm.citizens):d}   avg hunger {avg*100:.0f}%",
        f"Hunger: fed {fed:d}  hungry {hungry:d}  starving {starving:d}",
        f"Blief:  total f0={belief.total(0):.1f}  peak={belief.peak(0):.3f}  "
        f"overlay {'ON' if show_belief else 'off'} (B)",
        f"Food:   total {food.total():.0f}  peak={food.peak():.2f}  "
        f"overlay {'ON' if show_food else 'off'} (F)",
        f"Power:  mode {mode_name}   pool f0={pool0:.1f}  f1={pool1:.1f}  effects={len(ps.effects)}",
        err_line if err_line else "1-7 power - LMB cast - RMB cancel - F3 debug - B/F overlays - ESC",
    ]
    pad = 8
    line_h = font.get_linesize()
    box_w, box_h = 580, len(lines) * line_h + pad * 2
    overlay = pygame.Surface((box_w, box_h), pygame.SRCALPHA)
    overlay.fill((10, 10, 16, 200))
    screen.blit(overlay, (8, 8))
    for i, line in enumerate(lines):
        screen.blit(font.render(line, True, (216, 201, 168)),
                     (8 + pad, 8 + pad + i * line_h))


if __name__ == "__main__":
    sys.exit(main(sys.argv))
