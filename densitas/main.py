"""Densitas - P3 PR2 + Cast Queue entry point.

Tile map + camera + terrain (P0) + citizens + HUD (P1) + belief field (P2)
+ food/forage/hunger (P1.5) + Powers T0/T1 + Bless/Curse (P3 PR1)
+ Raise/Lower terrain mutation + drown rule (P3 PR2)
+ Click-chain queue for Raise/Lower with cancel UX (P3-Queue).

Run from the repo root with:
    python -m densitas.main
    python -m densitas.main --seed-relics           # restore the six debug relics
    python -m densitas.main --rival-stub-seed 12    # DEPRECATED - overrides [rival] initial_population
    python -m densitas.main --ai-debug              # dump every rival AI decision to stdout

The rival god spawns by default (PR4 step 3): `[rival]` in config.toml
controls the count, location and personality. Set `enabled = false` for
a solo sandbox round. PR4 step 4 gives it a brain - it senses, scores and
logs one decision every `ai_base_period / difficulty` sim seconds, but
executes nothing until step 5. `--ai-debug` prints those decisions.

Number keys 1-7 pick a power mode:
    1 Inspire   2 Calm        3 Hunger Pang
    4 Raise     5 Lower       6 Bless        7 Curse
Left-click to cast; right-click or Esc to cancel mode.

While Raise (4) or Lower (5) is the active mode:
    +  / =      bump brush size up   (side length 1 -> 2 -> 3 -> 4; tiles 1 -> 4 -> 9 -> 16)
    -  / _      bump brush size down (cap at 1)
Brush is top-left anchored: the cursor tile is the upper-left corner of
the NxN square, extending right and down. Persists across mode switches
but only takes effect in Raise/Lower.
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
from .rhetoric import Rhetoric, ScriptureCoalescer, make_picker
from .rival_ai import make_rival_ai
from .relics import (
    RelicManager, RelicState,
    RelicMode, RelicInputState,
    cycle_r_key, cycle_shift_r_key,
    _name_for as _relic_name_for,
)


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
    """Tiny arg parser - argparse would be overkill for two flags."""
    out = {"rival_stub_seed": 0, "seed_relics": False, "ai_debug": False}
    i = 1
    while i < len(argv):
        a = argv[i]
        if a == "--seed-relics":
            # PR4 step 3: the six hardcoded placements are debug scenery
            # now, not round setup. Handy for renderer work.
            out["seed_relics"] = True
            i += 1
            continue
        if a == "--ai-debug":
            # PR4 step 4: dump every rival decision (intent, target,
            # score, top 3) to stdout as it happens.
            out["ai_debug"] = True
            i += 1
            continue
        if a == "--rival-stub-seed":
            i += 1
            try:
                out["rival_stub_seed"] = int(argv[i])
            except (IndexError, ValueError):
                print(f"warning: --rival-stub-seed expects an integer; ignoring", file=sys.stderr)
            else:
                print("warning: --rival-stub-seed is deprecated (PR4 step 3) - "
                      "the rival spawns by default; use [rival] initial_population "
                      "in config.toml. The flag still overrides it; it goes away in P5.",
                      file=sys.stderr)
            i += 1
            continue
        if a in ("--help", "-h"):
            print(__doc__)
            sys.exit(0)
        # Skip unknowns silently - pygame.main might inherit argv.
        i += 1
    return out


def effective_rival_population(rival_cfg, args: dict) -> int:
    """How many rival citizens this round starts with.

    PR4 step 3 (spec §5). `[rival] enabled = false` means none;
    otherwise `initial_population`. The deprecated `--rival-stub-seed N`
    overrides both - an explicit debug flag beats config, including the
    disabled case, so `--rival-stub-seed 12` always gets you 12 rivals.
    """
    override = int(args.get("rival_stub_seed", 0) or 0)
    if override > 0:
        return override
    if not rival_cfg.enabled:
        return 0
    return int(rival_cfg.initial_population)


# The six centre-relative relic placements that used to be round setup.
# They made sense when relics were watch-only scenery; from PR4 step 3 the
# player places their own (R-key, PR3 step 10) and the AI places its own
# (spec §8), so these live behind --seed-relics for renderer testing.
SEED_RELIC_PLACEMENTS: tuple[tuple[int, int, int, int], ...] = (
    # (faction, slot, dx, dy)
    (0, 0, -4, -1),   # Open Eye  - NW (walkable for seed=0; (-3,-2) lands on a hill)
    (0, 1,  3,  0),   # Open Eye  - E (in the cluster)
    (0, 2, -8, -6),   # Open Eye  - far NW (alone)
    (1, 0,  0,  4),   # Maw       - rival S
    (1, 1,  5,  3),   # Maw       - rival SE
    (1, 2,  1,  5),   # Maw       - rival cluster
)


def seed_relics(relic_mgr: RelicManager, world,
                 placements: tuple[tuple[int, int, int, int], ...] = SEED_RELIC_PLACEMENTS,
                 sim_t: float = 0.0, verbose: bool = True) -> int:
    """Place the debug relic set, centre-relative. Returns how many landed.

    A seed tile can fall on water for an unusual world seed; that is
    logged and skipped rather than fatal - the preview copes with fewer
    than six relics on screen.
    """
    cx, cy = world.width // 2, world.height // 2
    placed = 0
    for f, slot, dx, dy in placements:
        ok, why = relic_mgr.place(f, slot, cx + dx, cy + dy, world, sim_t=sim_t)
        if ok:
            placed += 1
        elif verbose:
            print(f"  relic seed skipped (f{f} s{slot}): {why}")
    return placed


def _relic_mode_label(state: RelicInputState) -> str:
    """Short human-readable string for the active relic mode.

    Used by the HUD chip and the cursor-preview label. Slot 0 of
    faction 0 prints as "The First Witness", per RELIC_NAMES.
    """
    if state.mode == RelicMode.PLACE:
        return f"PLACING: {_relic_name_for(state.faction, state.slot)}"
    if state.mode == RelicMode.MOVE:
        return f"MOVING: {_relic_name_for(state.faction, state.slot)}"
    if state.mode == RelicMode.RETRIEVE:
        return "RETRIEVING (click a placed relic)"
    return "RELIC: ?"


def _apply_relic_input(state: RelicInputState, mgr: RelicManager,
                       world, tx: int, ty: int,
                       sim_t: float) -> tuple[bool, str]:
    """Dispatch an LMB click to the correct RelicManager mutation
    based on `state.mode`. Returns (ok, reason).
    """
    if state.mode == RelicMode.PLACE:
        return mgr.place(state.faction, state.slot, tx, ty,
                          world, sim_t=sim_t)
    if state.mode == RelicMode.MOVE:
        return mgr.move(state.faction, state.slot, tx, ty,
                         world, sim_t=sim_t)
    if state.mode == RelicMode.RETRIEVE:
        for r in mgr.for_faction(state.faction):
            if (r.state == RelicState.PLACED
                    and r.tx == tx and r.ty == ty):
                return mgr.retrieve(state.faction, r.slot,
                                     sim_t=sim_t)
        return (False, "no placed relic on this tile")
    return (False, f"unknown relic mode: {state.mode!r}")


def _preview_valid(state: RelicInputState, mgr: RelicManager,
                    world, tx: int, ty: int) -> bool:
    """True if an LMB at (tx, ty) right now would succeed.

    Cheap check used by the cursor preview to pick the tint colour.
    For PLACE/MOVE: tile must be in-bounds and walkable. For
    RETRIEVE: a PLACED relic of the player's faction must sit on
    the tile.
    """
    if not world.in_bounds(tx, ty):
        return False
    if state.mode in (RelicMode.PLACE, RelicMode.MOVE):
        return is_walkable_tile(int(world.tiles[ty, tx]))
    if state.mode == RelicMode.RETRIEVE:
        for r in mgr.for_faction(state.faction):
            if (r.state == RelicState.PLACED
                    and r.tx == tx and r.ty == ty):
                return True
        return False
    return False


def _relic_god_key(faction: int) -> str:
    if faction == 0: return "open_eye"
    if faction == 1: return "maw"
    return f"faction_{faction}"


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv
    args = parse_args(argv)
    cfg = config.load()

    pygame.init()
    pygame.display.set_caption("Densitas - P3 PR2 + Queue")
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
                                  food_cfg=cfg.food,
                                  relic_cfg=cfg.powers.relic)
    print(f"  spawned {len(citizen_mgr.citizens)} citizens")

    # PR4 step 3 (spec §5) - the rival god is default-on. There is an
    # opponent on the map from tick zero; the AI brain arrives in step 4.
    n_rival = effective_rival_population(cfg.rival, args)
    if n_rival > 0:
        placed = citizen_mgr.spawn_faction_at(
            world, n=n_rival, faction=1,
            frac_x=cfg.rival.spawn_frac_x,
            frac_y=cfg.rival.spawn_frac_y,
            radius=cfg.rival.spawn_radius_tiles,
            seed=cfg.world.seed,
        )
        print(f"  +{placed} rival citizens ({cfg.rival.personality}) at "
              f"({cfg.rival.spawn_frac_x:.2f}, {cfg.rival.spawn_frac_y:.2f}) "
              f"of map")
    else:
        print("  no rival this round ([rival] enabled = false)")

    # PR3 step 1 (2026-05-22): real RelicManager owns the per-round relic
    # list. PR4 step 3: a default round now starts with all six slots
    # AVAILABLE - the player places theirs with R and the AI places its
    # own (spec §8). --seed-relics restores the old debug scenery.
    relic_mgr = RelicManager(cfg.powers.relic, n_factions=2)
    if args["seed_relics"]:
        n_seeded = seed_relics(relic_mgr, world)
        print(f"  seeded {n_seeded}/{len(SEED_RELIC_PLACEMENTS)} debug "
              f"relics (--seed-relics)")
    else:
        print(f"  {len(relic_mgr.relics)} relic slots AVAILABLE "
              f"(--seed-relics to place the debug six)")
    # PR3 step 3: push any PLACED relics into the citizen manager so
    # wander picks can be drawn toward them. Re-synced after every
    # R-key placement / move / retrieve (PR3 step 10) and shatter
    # (PR3 step 4).
    citizen_mgr.sync_attractors_from_relics(
        relic_mgr.relics, cfg.powers.relic.attract_radius,
    )

    print(f"Allocating belief field ({cfg.belief.grid_w}x{cfg.belief.grid_h})...")
    belief = BeliefField(cfg.belief, world,
                          dying_duration=cfg.citizen.dying_duration,
                          relic_cfg=cfg.powers.relic)
    # PR3 step 2: pass the seeded relics into the initial recompute so
    # the startup belief readout reflects them too. sim_t=0.0 means the
    # six fresh placements contribute exactly 0 - fade-in starts on the
    # NEXT recompute. That's intentional per `Densitas_relics.md` section 7.
    belief.recompute(citizen_mgr.citizens, relics=relic_mgr.relics, sim_t=0.0)
    print(f"  initial belief total: f0={belief.total(0):.2f}, f1={belief.total(1):.2f}")

    print("Loading rhetoric pool...")
    try:
        rhet = Rhetoric.from_file(seed=cfg.world.seed)
        print(f"  rhetoric pool ready ({len(rhet._pool)} power keys)")
    except FileNotFoundError:
        print("  WARNING: rhetoric.json missing; scripture log will show placeholders")
        rhet = Rhetoric({}, seed=cfg.world.seed)

    print("Wiring power system...")

    # P3 PR2 - terrain mutation callback. Closes over world / food / renderer
    # / world_surface / citizen_mgr so PowerSystem doesn't have to know about
    # any of them. The drown rule (spec section 5.3) runs here, *after* the
    # world / food / surface have been updated - so the belief field on the
    # next tick sees both the new tile and the now-DYING citizens.
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

    # PR4 step 4 (spec §6) - the rival gets a brain. Built whenever the
    # round actually has rival citizens, so `--rival-stub-seed N` against
    # `enabled = false` still gets the opponent it asked for. Step 5 made
    # its four cast intents live; the relic verbs land in step 6.
    rival_ai = None
    if n_rival > 0:
        rival_ai = make_rival_ai(
            cfg.rival, cfg.powers, faction=1,
            seed=cfg.rival.ai_seed, debug=args["ai_debug"],
        )
        print(f"Rival AI online: {rival_ai.p.name} as {rival_ai.god_key}, "
              f"decision every {rival_ai.period:.2f} sim_s "
              f"(difficulty {cfg.rival.difficulty:g})"
              + ("  [--ai-debug]" if rival_ai.debug else ""))

    # PR4 step 7a (spec §4): conversion and despair events come out of the
    # citizen manager and are voiced through a coalescer - the first in a
    # quiet window at once, the rest of the window as one `{count}` line.
    # `has` lets it pick the `_many` plural cell only when the pool has
    # one; until step 7b fills the cells, every line is a visible `<key>`
    # placeholder, deliberately.
    coalescer = ScriptureCoalescer(
        cfg.citizen.faith.scripture_coalesce_window,
        voice=lambda key, faction, t, tokens: power_system.voice(
            key, faction, t, tokens=tokens),
        has=lambda key, faction: rhet.has(key, _relic_god_key(faction)),
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
    show_relics = True   # toggle with `K` - render-only hide for screenshots / eyeballing.

    active_mode: Optional[PowerKind] = None
    # PR3 step 10: R-key input modes (place/move/retrieve).
    # Mutually exclusive with active_mode - entering one clears the other.
    relic_input: Optional[RelicInputState] = None
    last_relic_fail_at: float = -1.0
    last_relic_fail_reason: str = ""
    # PR3 step 9: shatter summary panel state.
    # pending_shatters: shatter events waiting their PANEL_OPEN_DELAY before
    # the auto-panel appears. Each entry is (sim_t_of_shatter, summary).
    # panel_state: tuple (summary, opened_at, manual) or None when no panel
    # is open. tray_slot_rects_last: cache the rects returned by the most
    # recent blit_relic_tray call so the LMB handler can route clicks to
    # SHATTERED slots without re-deriving the geometry.
    pending_shatters: list = []
    panel_state: Optional[tuple] = None
    tray_slot_rects_last: list = []
    panel_rect_last = None
    # Brush size for bulk Raise/Lower (side length, so tile count = brush_size**2).
    # 1..4 -> 1, 4, 9, 16 tiles. Persists across mode switches; only effective
    # while active_mode is RAISE or LOWER. Modulated by +/- (top row or keypad).
    brush_size: int = 1
    BRUSH_MIN, BRUSH_MAX = 1, 4
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
                    if relic_input is not None:
                        relic_input = None
                    elif active_mode is not None:
                        active_mode = None
                    else:
                        running = False
                elif event.key == pygame.K_F3:
                    show_debug = not show_debug
                elif event.key == pygame.K_b:
                    show_belief_overlay = not show_belief_overlay
                elif event.key == pygame.K_f:
                    show_food_overlay = not show_food_overlay
                elif event.key == pygame.K_k:
                    # Render-only toggle - does not mutate RelicManager state.
                    show_relics = not show_relics
                elif event.key == pygame.K_c:
                    # P3-Queue: clear the queue for the current mode.
                    if active_mode in (PowerKind.RAISE, PowerKind.LOWER):
                        n = power_system.clear_queue(active_mode, faction=0)
                        if n:
                            last_cast_failed_at = sim_time
                            last_cast_reason = f"cleared {n} queued"
                elif event.key in (pygame.K_PLUS, pygame.K_EQUALS,
                                    pygame.K_KP_PLUS):
                    # P3-Brush: bump brush size up. Only effective while
                    # active_mode is Raise/Lower; key still consumed (i.e.
                    # the brush variable persists) so switching back to
                    # Raise restores the prior brush.
                    if brush_size < BRUSH_MAX:
                        brush_size += 1
                        if active_mode in (PowerKind.RAISE, PowerKind.LOWER):
                            last_cast_failed_at = sim_time
                            last_cast_reason = (
                                f"brush {brush_size}x{brush_size} "
                                f"({brush_size * brush_size} tiles)"
                            )
                elif event.key in (pygame.K_MINUS, pygame.K_UNDERSCORE,
                                    pygame.K_KP_MINUS):
                    if brush_size > BRUSH_MIN:
                        brush_size -= 1
                        if active_mode in (PowerKind.RAISE, PowerKind.LOWER):
                            last_cast_failed_at = sim_time
                            last_cast_reason = (
                                f"brush {brush_size}x{brush_size} "
                                f"({brush_size * brush_size} tiles)"
                            )
                elif event.key == pygame.K_r:
                    # PR3 step 10: R cycles place/move; Shift+R toggles retrieve.
                    if event.mod & pygame.KMOD_SHIFT:
                        relic_input = cycle_shift_r_key(
                            relic_input, relic_mgr, faction=0,
                        )
                    else:
                        relic_input = cycle_r_key(
                            relic_input, relic_mgr, faction=0,
                        )
                    if relic_input is not None:
                        # Mutual exclusion with power modes.
                        active_mode = None
                elif event.key in POWER_KEYS:
                    active_mode = POWER_KEYS[event.key]
            elif event.type == pygame.MOUSEBUTTONDOWN:
                # PR3 step 9: panel + SHATTERED-tray click handling. Both
                # are gated AHEAD of relic_input / active_mode so a click
                # on the panel or on a SHATTERED tray slot doesn't fall
                # through to a power cast.
                _panel_consumed = False
                if event.button == 1 and panel_state is not None \
                        and panel_rect_last is not None \
                        and panel_rect_last.collidepoint(event.pos):
                    _summary, _opened_at, _manual = panel_state
                    if _manual:
                        # Manual re-opens dismiss immediately on click.
                        panel_state = None
                    else:
                        # Auto-panels jump to slide-out: rewind opened_at so
                        # the next frame sees PANEL_PHASE_SLIDE_OUT phase
                        # progress = 0. opened_at = sim_time - hold -
                        # slide_in puts us at the very start of slide-out.
                        from densitas.hud import (
                            PANEL_SLIDE_DURATION, PANEL_HOLD_DURATION,
                        )
                        panel_state = (
                            _summary,
                            sim_time - PANEL_SLIDE_DURATION - PANEL_HOLD_DURATION,
                            False,
                        )
                    _panel_consumed = True
                elif event.button == 1 and tray_slot_rects_last:
                    # Click-to-reopen on a SHATTERED tray slot.
                    for _trect, _relic in tray_slot_rects_last:
                        if _trect.collidepoint(event.pos) \
                                and _relic.state == RelicState.SHATTERED \
                                and _relic.shatter_summary is not None:
                            panel_state = (
                                _relic.shatter_summary,
                                sim_time,
                                True,    # manual
                            )
                            _panel_consumed = True
                            break
                if _panel_consumed:
                    continue
                if event.button == 1 and relic_input is not None:
                    # PR3 step 10: relic-mode LMB.
                    mx, my = event.pos
                    rtx, rty = _screen_to_tile(mx, my, cam, cfg)
                    _mode = relic_input.mode
                    _slot = relic_input.slot
                    _faction = relic_input.faction
                    ok, reason = _apply_relic_input(
                        relic_input, relic_mgr, world,
                        rtx, rty, sim_t=sim_time,
                    )
                    if ok:
                        # Re-sync attractors so a fresh PLACED relic
                        # immediately starts pulling, and retrieved /
                        # moved relics update their pull tile.
                        citizen_mgr.sync_attractors_from_relics(
                            relic_mgr.relics,
                            cfg.powers.relic.attract_radius,
                        )
                        # PR3 step 12: scripture log emission wired with
                        # rhetoric.json relic_placed / relic_moved /
                        # relic_retrieved keys + {relic_name} token.
                        _key = ("relic_placed" if _mode == RelicMode.PLACE
                                else "relic_moved" if _mode == RelicMode.MOVE
                                else "relic_retrieved")
                        try:
                            _relic = relic_mgr.get(_faction, _slot)
                            _line = rhet.pick(
                                _key, _relic_god_key(_faction),
                                sim_t=sim_time,
                                tokens={"relic_name": _relic.name},
                            )
                            print(f"  [scripture {_key}] f{_faction}: {_line}")
                        except Exception:
                            # Pool key missing or relic lookup failed -
                            # log loudly so we notice in dev but don't
                            # crash the game.
                            pass
                        # Auto-advance through AVAILABLE on PLACE; stay
                        # in mode on MOVE / RETRIEVE so the player can
                        # chain more without re-pressing R.
                        if _mode == RelicMode.PLACE:
                            relic_input = cycle_r_key(
                                relic_input, relic_mgr, faction=0,
                            )
                            # Suppress mode-flip to MOVE - the user
                            # expected another place, not a move.
                            if (relic_input is not None
                                    and relic_input.mode == RelicMode.MOVE):
                                relic_input = None
                    else:
                        last_relic_fail_at = sim_time
                        last_relic_fail_reason = reason
                elif event.button == 1 and active_mode is not None:
                    mx, my = event.pos
                    tx, ty = _screen_to_tile(mx, my, cam, cfg)
                    # P3-Queue: queueable kinds go through cast_or_queue
                    # so chained clicks during cooldown enqueue rather
                    # than fail.
                    # P3-Brush: bulk Raise/Lower expands one click into an
                    # NxN top-left-anchored square; other powers stay
                    # single-tile regardless of brush_size.
                    if active_mode in (PowerKind.RAISE, PowerKind.LOWER):
                        bn = brush_size
                    else:
                        bn = 1
                    first_fail: Optional[str] = None
                    is_first_tile = True
                    for dx in range(bn):
                        for dy in range(bn):
                            receipt = power_system.cast_or_queue(
                                kind=active_mode, faction=0,
                                tx=tx + dx, ty=ty + dy,
                                citizens=citizen_mgr, world=world, food=food,
                                belief=belief, sim_t=sim_time,
                                # P3-Brush: first tile carries the
                                # scripture voice; tiles 2..N**2 are
                                # silent so one click reads as one
                                # casting motion in the log.
                                suppress_scripture=not is_first_tile,
                            )
                            if not receipt.ok and first_fail is None:
                                first_fail = receipt.reason
                            # Only flip after a tile that actually had a
                            # shot at emitting scripture (i.e. the call
                            # got past validation enough to debit/queue).
                            # Validation failures don't emit scripture
                            # either way, so they shouldn't burn the
                            # "first" slot.
                            if receipt.ok:
                                is_first_tile = False
                    if first_fail is not None:
                        last_cast_failed_at = sim_time
                        last_cast_reason = first_fail
                elif event.button == 3 and relic_input is not None:
                    # PR3 step 10: RMB cancels relic mode.
                    relic_input = None
                elif event.button == 3:
                    # P3-Queue: RMB on a queued tile cancels that tile
                    # first; falls through to mode-cancel only if no
                    # queued tile under cursor.
                    cancelled = False
                    if active_mode in (PowerKind.RAISE, PowerKind.LOWER) \
                            and pygame.mouse.get_focused():
                        mx, my = event.pos
                        tx, ty = _screen_to_tile(mx, my, cam, cfg)
                        cancelled = power_system.cancel_queued_at(
                            tx, ty, active_mode, faction=0,
                        )
                    if not cancelled:
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
            # P3-Queue: drain right after tick so a just-cleared cooldown
            # can dispatch in the same step. Belief was debited at enqueue.
            power_system.drain_queues(
                citizen_mgr, world, food, belief, sim_time,
            )
            food.recompute(tick_dt, effects=power_system.effects)
            # PR4 step 1: belief passed in for the faith update. Citizens
            # read the PREVIOUS tick's field (recompute runs just below) -
            # a one-tick lag the 5 Hz cadence absorbs invisibly.
            citizen_mgr.tick(tick_dt, world, food, belief=belief)
            # PR4 step 7a: voice the faith outcomes. `citizen_converted`
            # belongs to the GAINING god, `citizen_despair` to the god they
            # were abandoning - the loser's silence on a conversion is
            # on-brand (spec §4).
            for _ev in citizen_mgr.drain_events():
                if _ev.kind == "converted":
                    coalescer.emit("citizen_converted", _ev.to_faction, sim_time)
                elif _ev.kind == "despair":
                    coalescer.emit("citizen_despair", _ev.from_faction, sim_time)
            coalescer.tick(sim_time)
            # PR3 step 2: pass the live relic list + current sim_t so
            # each PLACED relic contributes amplitude * min(1.0,
            # (sim_t - placed_at) / place_cooldown) to its belief cell.
            belief.recompute(
                citizen_mgr.citizens,
                relics=relic_mgr.relics,
                sim_t=sim_time,
            )
            # PR3 step 4: drive threat_timer from rival belief,
            # transition PLACED -> SHATTERED when the threshold
            # sustains for shatter_time. Runs AFTER belief.recompute
            # so query() sees the just-computed field.
            _shattered = relic_mgr.tick(
                tick_dt, belief, citizen_mgr, sim_t=sim_time,
            )
            if _shattered:
                # Re-sync attractors so SHATTERED relics stop pulling.
                citizen_mgr.sync_attractors_from_relics(
                    relic_mgr.relics, cfg.powers.relic.attract_radius,
                )
                # PR3 step 9: queue each shatter for the summary panel.
                # The actual open is delayed by PANEL_OPEN_DELAY (1.0 sim_sec
                # by default) so the on-map shatter animation (step 7) plays
                # out before the panel slides in.
                for _s in _shattered:
                    pending_shatters.append((sim_time, _s))
                for _s in _shattered:
                    print(
                        f"  [shatter @ sim_t={sim_time:.1f}] "
                        f"f{_s.faction} {_s.name} at "
                        f"({_s.tx},{_s.ty}) | belief p={_s.local_belief_player:.2f} "
                        f"r={_s.local_belief_rival:.2f} | "
                        f"citizens p={_s.player_citizens_within_8} "
                        f"r={_s.rival_citizens_within_8} | "
                        f"placed_total={_s.time_placed_total:.1f}s "
                        f"moves={_s.times_moved}"
                    )
                    # PR3 step 12: shatter scripture. Each loss gets a
                    # voiced line from the LOSING god's pool (the
                    # propaganda is theirs to mourn). The numbers above
                    # are the truth; the line below is the doctrine.
                    try:
                        _line = rhet.pick(
                            "relic_shattered",
                            _relic_god_key(_s.faction),
                            sim_t=sim_time,
                            tokens={"relic_name": _s.name},
                        )
                        print(
                            f"  [scripture relic_shattered] "
                            f"f{_s.faction}: {_line}"
                        )
                    except Exception:
                        pass
            # PR4 step 4 (spec §6): the AI senses this tick's fully
            # settled state - belief recomputed, relics ticked, attractors
            # re-synced - and its eventual casts (step 5) will dispatch
            # through the same path as a player click.
            if rival_ai is not None:
                rival_ai.tick(
                    tick_dt, sim_t=sim_time, citizens=citizen_mgr,
                    belief=belief, relic_mgr=relic_mgr,
                    power_system=power_system, world=world, food=food,
                )
            sim_accumulator -= tick_dt
            sim_time += tick_dt

        screen.fill((0, 0, 0))
        renderer.blit_viewport(screen, world_surface, cam.x, cam.y)
        if show_food_overlay:
            renderer.blit_food_overlay(screen, food, cam.x, cam.y)
        if show_belief_overlay:
            renderer.blit_belief_overlay(screen, belief, cam.x, cam.y)
        # Relics blit between the world surface (+ overlays) and
        # citizens, so a citizen on the same tile walks visibly over
        # the relic's base. PR3 step 1: source is the live
        # `RelicManager`, filtered to currently-PLACED relics across
        # all factions. Iteration order follows `relics` list order
        # (faction-major, slot-minor) which gives consistent z-order.
        if show_relics:
            _placed = [r for r in relic_mgr.relics
                       if r.state == RelicState.PLACED]
            renderer.blit_relics(screen, _placed, cam.x, cam.y, sim_time)
        # PR3 step 7: shatter animation. Passes the FULL relic list so
        # the renderer can pick the SHATTERED ones within the
        # SHATTER_ANIM_DURATION window itself; no-op past it.
        renderer.blit_shatter_animations(
            screen, relic_mgr.relics, cam.x, cam.y, sim_time,
        )
        renderer.blit_citizens(screen, citizen_mgr.iter_for_render(), cam.x, cam.y, sim_time)

        # P3-Queue: queued-cast chevrons sit above citizens, below preview.
        renderer.blit_cast_queue(screen, power_system.queues,
                                  cam.x, cam.y, cast_chip_font)

        # PR3 step 10: relic-mode cursor preview - draws above citizens.
        if relic_input is not None and pygame.mouse.get_focused():
            mx, my = pygame.mouse.get_pos()
            rtx, rty = _screen_to_tile(mx, my, cam, cfg)
            renderer.blit_relic_preview(
                screen,
                faction=relic_input.faction,
                tx=rtx, ty=rty,
                valid=_preview_valid(
                    relic_input, relic_mgr, world, rtx, rty,
                ),
                attract_radius=cfg.powers.relic.attract_radius,
                cam_x=cam.x, cam_y=cam.y,
                font=cast_chip_font,
                label=_relic_mode_label(relic_input),
            )

        # Cast preview (P3) - draw above citizens, below HUD.
        if active_mode is not None and pygame.mouse.get_focused():
            mx, my = pygame.mouse.get_pos()
            tx, ty = _screen_to_tile(mx, my, cam, cfg)
            if world.in_bounds(tx, ty):
                spec = POWERS[active_mode]
                ok, reason = power_system.can_cast(
                    active_mode, faction=0, tx=tx, ty=ty,
                    citizens=citizen_mgr, world=world,
                )
                preview_brush = (
                    brush_size
                    if active_mode in (PowerKind.RAISE, PowerKind.LOWER)
                    else 1
                )
                renderer.blit_cast_preview(
                    screen, spec, tx, ty, ok, reason,
                    cam.x, cam.y, cast_chip_font,
                    brush_size=preview_brush,
                )

        if show_debug:
            _draw_debug(screen, font, clock, cam, cfg, citizen_mgr, belief, food,
                         power_system, active_mode, sim_time,
                         show_belief_overlay, show_food_overlay,
                         last_cast_failed_at, last_cast_reason,
                         brush_size)
        hud.draw(screen, citizen_mgr, belief,
                  powers=power_system, sim_t=sim_time,
                  active_mode=(int(active_mode) if active_mode is not None else None))
        # PR3 step 8: relic tray, bottom-right corner. Display-only.
        # The returned (Rect, Relic) pairs feed step 9's click-to-reopen.
        _tray_mouse = pygame.mouse.get_pos() if pygame.mouse.get_focused() else None
        tray_slot_rects_last = hud.blit_relic_tray(
            screen,
            relic_mgr.for_faction(0),
            sim_t=sim_time,
            shatter_time=cfg.powers.relic.shatter_time,
            mouse_pos=_tray_mouse,
        )
        # PR3 step 9: advance the pending-shatter queue. If no panel is
        # open and the oldest pending shatter is older than the
        # PANEL_OPEN_DELAY (1.0 sim_sec by default - matches the on-map
        # animation's 1.0 sec duration so the panel opens as the relic
        # finishes fading), pop and open the auto panel.
        from densitas.hud import PANEL_OPEN_DELAY as _PANEL_OPEN_DELAY
        if panel_state is None and pending_shatters:
            if sim_time - pending_shatters[0][0] >= _PANEL_OPEN_DELAY:
                _, _next_summary = pending_shatters.pop(0)
                panel_state = (_next_summary, sim_time, False)
        # Render the panel and capture its rect for click-to-dismiss.
        panel_rect_last = None
        if panel_state is not None:
            _summary, _opened_at, _manual = panel_state
            panel_rect_last = hud.blit_shatter_summary_panel(
                screen, _summary, _opened_at, sim_time, manual=_manual,
            )
            if panel_rect_last is None:
                # phase 'done' -> auto-panel has finished slide-out.
                panel_state = None
        # PR3 step 10: relic-mode chip above the HUD box.
        if relic_input is not None:
            _accent = (
                (90, 200, 220) if relic_input.mode == RelicMode.PLACE
                else (220, 170, 60) if relic_input.mode == RelicMode.MOVE
                else (210, 70, 60)
            )
            hud.draw_relic_mode_chip(
                screen,
                label=_relic_mode_label(relic_input),
                accent=_accent,
            )
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
                 last_cast_failed_at: float, last_cast_reason: str,
                 brush_size: int = 1) -> None:
    ts = cfg.render.tile_size
    tile_x = int((cam.x + cfg.render.viewport_w / 2) // ts)
    tile_y = int((cam.y + cfg.render.viewport_h / 2) // ts)
    bf_here = belief.query(tile_x, tile_y, 0)
    food_here = food.query(tile_x, tile_y)
    fed, hungry, starving, avg = cm.hunger_stats(0)
    mode_name = POWERS[active_mode].name if active_mode is not None else "-"
    if active_mode in (PowerKind.RAISE, PowerKind.LOWER) and brush_size > 1:
        mode_name = f"{mode_name} brush {brush_size}x{brush_size} ({brush_size * brush_size}t)"
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
        f"Queue:  R x {len(ps.queues.get((0, 10), [])):d} ({len(ps.queues.get((0, 10), [])) * 2.0:.1f}s)  "
        f"L x {len(ps.queues.get((0, 11), [])):d} ({len(ps.queues.get((0, 11), [])) * 2.0:.1f}s)",
        err_line if err_line else "1-7 power - +/- brush (R/L) - LMB cast/queue - RMB cancel - C clear queue - F3 - B/F/K - ESC",
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
