"""Render - abstract Renderer + PixelRenderer implementation.

The Renderer interface is intentionally narrow so a future VectorRenderer
can be dropped in without touching world/camera/main code. Implementations
share the same `build_world_surface`, `blit_viewport`, `blit_citizens`,
`blit_belief_overlay`, `blit_food_overlay`, and (P3) `blit_cast_preview`
contract.
"""
from __future__ import annotations
import abc
import pygame
import numpy as np
from typing import Iterable, Optional, TYPE_CHECKING
from .world import World, Tile
from .config import RenderConfig
from .citizen import Citizen, CitizenState, Facing

if TYPE_CHECKING:
    from .powers import PowerSpec


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

CITIZEN_PALETTE: dict[int, tuple[tuple[int, int, int], tuple[int, int, int],
                                  tuple[int, int, int], tuple[int, int, int]]] = {
    0: ((230, 200, 170), (220, 210, 180), (90, 200, 220), (30, 28, 30)),
    1: ((210, 190, 170), (190, 180, 170), (160, 30, 30), (30, 28, 30)),
}

CITIZEN_W = 8
CITIZEN_H = 16

BELIEF_TINT: dict[int, tuple[int, int, int]] = {
    0: (90, 200, 220),
    1: (220, 60, 60),
}

# Food overlay: a single yellow-green tint scaled by food/global_max.
FOOD_TINT: tuple[int, int, int] = (110, 200, 80)

# Per-power AoE tint for the cast preview.
PREVIEW_TINT_BY_KIND: dict[int, tuple[int, int, int]] = {
    0:  (200, 200, 240),    # INSPIRE   - pale blue
    1:  (200, 220, 220),    # CALM      - off-white
    2:  (200, 120, 120),    # HUNGER_PANG - dim red
    10: (200, 170, 80),     # RAISE     - amber
    11: (130, 90, 60),      # LOWER     - brown
    12: (110, 200, 80),     # BLESS     - green
    13: (200, 100, 80),     # CURSE     - red
}


class Renderer(abc.ABC):
    def __init__(self, cfg: RenderConfig):
        self.cfg = cfg

    @property
    def tile_size(self) -> int:
        return self.cfg.tile_size

    @abc.abstractmethod
    def build_world_surface(self, world: World) -> pygame.Surface: ...

    def blit_viewport(self, screen: pygame.Surface, world_surface: pygame.Surface,
                       cam_x: float, cam_y: float) -> None:
        screen.blit(
            world_surface,
            (0, 0),
            area=pygame.Rect(int(cam_x), int(cam_y),
                              self.cfg.viewport_w, self.cfg.viewport_h),
        )

    @abc.abstractmethod
    def blit_citizens(self, screen: pygame.Surface, citizens: Iterable[Citizen],
                       cam_x: float, cam_y: float, sim_time: float = 0.0) -> None: ...

    @abc.abstractmethod
    def blit_belief_overlay(self, screen: pygame.Surface, belief,
                             cam_x: float, cam_y: float) -> None: ...

    @abc.abstractmethod
    def blit_food_overlay(self, screen: pygame.Surface, food,
                           cam_x: float, cam_y: float) -> None: ...

    @abc.abstractmethod
    def blit_cast_preview(self, screen: pygame.Surface, spec: "PowerSpec",
                           tx: int, ty: int, ok: bool, reason: str,
                           cam_x: float, cam_y: float, font) -> None: ...

    @abc.abstractmethod
    def repaint_tile(self, world_surface: pygame.Surface, world: World,
                      tx: int, ty: int) -> None:
        """Re-blit a single tile's sprite onto the cached world surface.

        Called by `world.mutate_tile` after a Raise/Lower mutation so the
        world surface stays current without a full rebuild.
        """
        ...

    @abc.abstractmethod
    def blit_cast_queue(self, screen: pygame.Surface, queues: dict,
                         cam_x: float, cam_y: float, font) -> None:
        """Paint chevrons for every queued cast (Densitas_queue.md §6.1).

        `queues` is `PowerSystem.queues`; the renderer iterates and paints
        amber ▲ on RAISE entries, brown ▼ on LOWER entries, with a small
        position number in the corner.
        """
        ...


class PixelRenderer(Renderer):
    def __init__(self, cfg: RenderConfig, rng_seed: int = 0,
                 variants_per_tile: int = 4):
        super().__init__(cfg)
        self._rng = np.random.default_rng(rng_seed)
        self._tile_sprites: dict[Tile, list[pygame.Surface]] = {}
        self._build_tile_sprites(variants_per_tile)
        self._citizen_sprites: dict[tuple[int, int, int], pygame.Surface] = {}
        self._build_citizen_sprites()
        self._belief_cache_version: int = -1
        self._belief_overlay_world: pygame.Surface | None = None
        self._food_cache_version: int = -1
        self._food_overlay_world: pygame.Surface | None = None

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

    def repaint_tile(self, world_surface: pygame.Surface, world: World,
                      tx: int, ty: int) -> None:
        """Blit a single tile onto the cached world surface (P3 PR2).

        Uses the same deterministic hash as `build_world_surface` so the
        variant choice for a given (tx, ty, tile_id) is stable across
        rebuilds. Avoids a full re-render after every Raise/Lower cast.
        """
        ts = self.cfg.tile_size
        tile = Tile(int(world.tiles[ty, tx]))
        variants = self._tile_sprites[tile]
        idx = (tx * 73856093 ^ ty * 19349663 ^ int(tile) * 83492791) % len(variants)
        world_surface.blit(variants[idx], (tx * ts, ty * ts))

    # -- citizen sprites ----------------------------------------------------

    def _build_citizen_sprites(self) -> None:
        # Frames: 0 idle, 1+2 walk cycle, 3 EATING munch (mouth-open variant).
        for faction, (skin, robe, accent, outline) in CITIZEN_PALETTE.items():
            for facing in Facing:
                for frame in range(4):
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

        for hy in range(0, 4):
            for hx in range(2, 6):
                px(hx, hy, skin)
        for hy in range(0, 4):
            px(1, hy, outline)
            px(6, hy, outline)
        px(2, 0, outline); px(5, 0, outline)

        # Frame 3 = EATING munch — drop the mouth outline pixels so the
        # mouth looks open. Cycles with frame 0 to give a chewing motion.
        mouth_open = (frame == 3)
        if facing == Facing.SOUTH and not mouth_open:
            px(3, 2, outline); px(4, 2, outline)
        elif facing == Facing.NORTH:
            for hx in range(2, 6):
                px(hx, 1, accent)
        elif facing == Facing.EAST and not mouth_open:
            px(4, 2, outline); px(5, 2, outline)
        elif facing == Facing.WEST and not mouth_open:
            px(2, 2, outline); px(3, 2, outline)

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

        # Frame 3 (EATING munch) reuses the idle leg layout.
        if frame == 0 or frame == 3:
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

    def blit_citizens(self, screen: pygame.Surface, citizens: Iterable[Citizen],
                       cam_x: float, cam_y: float, sim_time: float = 0.0) -> None:
        """Paint each citizen. P1-polish:
          * Walk frames cycle by *spatial* phase (position), not the clock.
          * DYING citizens are alpha-faded by `c.dying_fade` (paired with
            the P1.5 belief-field fade).
          * EATING citizens chew — alternate frame 0 / frame 3 (mouth open).
        """
        ts = self.cfg.tile_size
        vw, vh = self.cfg.viewport_w, self.cfg.viewport_h
        cx_int = int(cam_x)
        cy_int = int(cam_y)
        sprites = self._citizen_sprites
        blit = screen.blit
        walk_states = (CitizenState.WANDER, CitizenState.FORAGE)
        for c in citizens:
            wx = int(c.x * ts) - cx_int + (ts - CITIZEN_W) // 2
            wy = int(c.y * ts) - cy_int + (ts - CITIZEN_H)
            if wx + CITIZEN_W < 0 or wy + CITIZEN_H < 0 or wx >= vw or wy >= vh:
                continue
            # DYING — alpha-fade the idle sprite by remaining dying_fade.
            if c.state == CitizenState.DYING:
                sprite = sprites.get((c.faction, int(c.facing), 0))
                if sprite is None:
                    sprite = sprites[(0, int(Facing.SOUTH), 0)]
                fade = max(0.0, min(1.0, getattr(c, "dying_fade", 1.0)))
                if fade <= 0.0:
                    continue
                if fade < 0.999:
                    tmp = sprite.copy()
                    tmp.set_alpha(int(255 * fade))
                    blit(tmp, (wx, wy))
                else:
                    blit(sprite, (wx, wy))
                continue
            # EATING — alternate mouth-closed (0) and mouth-open (3) ~2.5x/sec.
            if c.state == CitizenState.EATING:
                frame = 3 if (int(sim_time / 0.4) + c.id) & 1 else 0
            elif c.state in walk_states:
                # Spatial phase — animation steps with the citizen's actual
                # motion. Sum x+y so diagonal travel still cycles cleanly.
                phase = (c.x + c.y) % 1.0
                frame = 1 if phase < 0.5 else 2
            else:
                frame = 0
            sprite = sprites.get((c.faction, int(c.facing), frame))
            if sprite is None:
                sprite = sprites[(0, int(Facing.SOUTH), 0)]
            blit(sprite, (wx, wy))

    # -- belief overlay ----------------------------------------------------

    def blit_belief_overlay(self, screen: pygame.Surface, belief,
                             cam_x: float, cam_y: float) -> None:
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
        gw = belief.grid_w
        gh = belief.grid_h
        peaks = [max(belief.peak(f), 1e-3) for f in range(belief.n_factions)]
        rgba = np.zeros((gh, gw, 4), dtype=np.float32)
        max_mass = np.zeros((gh, gw), dtype=np.float32)
        total_weight = np.zeros((gh, gw), dtype=np.float32)
        for f in range(belief.n_factions):
            grid = belief.grid(f)
            tint = BELIEF_TINT.get(f, (200, 200, 200))
            w = grid / peaks[f]
            np.clip(w, 0.0, 1.0, out=w)
            rgba[..., 0] += w * tint[0]
            rgba[..., 1] += w * tint[1]
            rgba[..., 2] += w * tint[2]
            total_weight += w
            np.maximum(max_mass, w, out=max_mass)
        nz = total_weight > 0.0
        rgba[nz, 0] /= total_weight[nz]
        rgba[nz, 1] /= total_weight[nz]
        rgba[nz, 2] /= total_weight[nz]
        alpha_max = float(belief.cfg.overlay_alpha_max)
        rgba[..., 3] = max_mass * alpha_max
        rgba_u8 = rgba.clip(0, 255).astype(np.uint8)
        small = pygame.image.frombuffer(
            rgba_u8.tobytes(), (gw, gh), "RGBA",
        ).convert_alpha()
        ts = self.cfg.tile_size
        return pygame.transform.scale(small,
                                       (belief.world_w * ts, belief.world_h * ts))

    # -- food overlay ------------------------------------------------------

    def blit_food_overlay(self, screen: pygame.Surface, food,
                           cam_x: float, cam_y: float) -> None:
        """Greenish heatmap of `food.grid()`, cached by `food.version`.

        Source resolution is world-tile native (e.g. 256x192). One per-tile
        cell -> tile_size pixels in the upscaled overlay.
        """
        if food.version != self._food_cache_version or self._food_overlay_world is None:
            self._food_overlay_world = self._build_food_overlay_world(food)
            self._food_cache_version = food.version
        screen.blit(
            self._food_overlay_world,
            (0, 0),
            area=pygame.Rect(int(cam_x), int(cam_y),
                              self.cfg.viewport_w, self.cfg.viewport_h),
        )

    def _build_food_overlay_world(self, food) -> pygame.Surface:
        grid = food.grid()  # (h, w) float32
        # Normalize by the global cap maximum so tiles at full carry max alpha.
        cap_max = float(max(food.cap.max(), 1e-3))
        w = (grid / cap_max).clip(0.0, 1.0).astype(np.float32)
        h, gw = grid.shape
        rgba = np.zeros((h, gw, 4), dtype=np.float32)
        tint = FOOD_TINT
        rgba[..., 0] = w * tint[0]
        rgba[..., 1] = w * tint[1]
        rgba[..., 2] = w * tint[2]
        rgba[..., 3] = w * float(food.cfg.overlay_alpha_max)
        rgba_u8 = rgba.clip(0, 255).astype(np.uint8)
        small = pygame.image.frombuffer(
            rgba_u8.tobytes(), (gw, h), "RGBA",
        ).convert_alpha()
        ts = self.cfg.tile_size
        return pygame.transform.scale(small,
                                       (food.world_w * ts, food.world_h * ts))

    # -- cast preview (P3) -------------------------------------------------

    def blit_cast_preview(self, screen: pygame.Surface, spec,
                           tx: int, ty: int, ok: bool, reason: str,
                           cam_x: float, cam_y: float, font) -> None:
        """Paint the AoE circle + status chip for the active power mode.

        Coordinates are world tiles. Caller passes the mouse-to-tile
        result. Renderer composes a transparent overlay so it doesn't
        require the world surface.
        """
        ts = self.cfg.tile_size
        vw, vh = self.cfg.viewport_w, self.cfg.viewport_h

        # Tile -> screen pixel (centre of tile).
        sx = int(tx * ts - cam_x + ts // 2)
        sy = int(ty * ts - cam_y + ts // 2)

        # AoE radius in screen pixels (point targets get a single-tile pip).
        rpx = max(ts // 2, spec.aoe_radius * ts)

        # Tint by kind. Status colour: green ok, amber cooling, red blocked.
        tint = PREVIEW_TINT_BY_KIND.get(int(spec.kind), (200, 200, 200))
        if ok:
            border = (110, 230, 110)
        elif reason.startswith("cooling"):
            border = (220, 170, 60)
        else:
            border = (220, 90, 80)

        # Overlay surface for the alpha circle.
        ov = pygame.Surface((rpx * 2 + 6, rpx * 2 + 6), pygame.SRCALPHA)
        pygame.draw.circle(ov, (*tint, 70), (rpx + 3, rpx + 3), rpx)
        pygame.draw.circle(ov, (*border, 220), (rpx + 3, rpx + 3), rpx, width=2)
        # Crosshair pip at the centre tile.
        pygame.draw.rect(
            ov, (*border, 200),
            pygame.Rect(rpx + 3 - ts // 2, rpx + 3 - ts // 2, ts, ts),
            width=1,
        )
        screen.blit(ov, (sx - rpx - 3, sy - rpx - 3))

        # Status chip: "BLESS  10b  4.0s   need T2" near the cursor.
        chip_lines = []
        chip_lines.append(f"{spec.name.upper()}  {spec.belief_cost:.0f}b  {spec.cooldown:.1f}s")
        if reason:
            chip_lines.append(reason)

        # Render chip with parchment text on a dark pad.
        pad_x = 6; pad_y = 4
        line_h = font.get_linesize()
        text_surfs = [font.render(s, True, (216, 201, 168)) for s in chip_lines]
        chip_w = max((s.get_width() for s in text_surfs), default=0) + pad_x * 2
        chip_h = sum(s.get_height() for s in text_surfs) + pad_y * 2

        chip_x = min(max(sx + 14, 0), vw - chip_w)
        chip_y = min(max(sy + 14, 0), vh - chip_h)
        chip_bg = pygame.Surface((chip_w, chip_h), pygame.SRCALPHA)
        chip_bg.fill((10, 10, 16, 220))
        pygame.draw.rect(chip_bg, (*border, 220), chip_bg.get_rect(), width=1)
        screen.blit(chip_bg, (chip_x, chip_y))
        oy = chip_y + pad_y
        for s in text_surfs:
            screen.blit(s, (chip_x + pad_x, oy))
            oy += s.get_height()

    # -- cast queue (P3-Queue) ---------------------------------------------

    def blit_cast_queue(self, screen: pygame.Surface, queues: dict,
                         cam_x: float, cam_y: float, font) -> None:
        """Paint amber ▲ for queued Raise, brown ▼ for queued Lower
        (Densitas_queue.md §6.1). Position number in the upper-right of
        each chevron; we draw 1-9 and stop (the chevron carries the
        load-bearing signal past 9)."""
        if not queues:
            return
        ts = self.cfg.tile_size
        vw, vh = self.cfg.viewport_w, self.cfg.viewport_h
        # Tints — match the cast-preview palette.
        AMBER = (220, 180, 80)   # RAISE
        BROWN = (160, 110, 70)   # LOWER
        DARK  = (10, 10, 16)
        for (_faction, kind_val), q in queues.items():
            if not q:
                continue
            is_raise = kind_val == 10    # PowerKind.RAISE.value
            is_lower = kind_val == 11    # PowerKind.LOWER.value
            if not (is_raise or is_lower):
                continue
            tint = AMBER if is_raise else BROWN
            for i, qc in enumerate(q, start=1):
                sx = int(qc.tx * ts - cam_x)
                sy = int(qc.ty * ts - cam_y)
                if sx + ts < 0 or sy + ts < 0 or sx >= vw or sy >= vh:
                    continue
                cx = sx + ts // 2
                cy = sy + ts // 2
                r = max(5, ts // 2 - 2)
                # Triangle (▲ up for raise, ▼ down for lower).
                if is_raise:
                    pts = [(cx, cy - r), (cx - r, cy + r), (cx + r, cy + r)]
                else:
                    pts = [(cx, cy + r), (cx - r, cy - r), (cx + r, cy - r)]
                ov = pygame.Surface((ts + 4, ts + 4), pygame.SRCALPHA)
                ov_pts = [(p[0] - sx + 2, p[1] - sy + 2) for p in pts]
                pygame.draw.polygon(ov, (*tint, 180), ov_pts)
                pygame.draw.polygon(ov, (*DARK,  220), ov_pts, width=1)
                screen.blit(ov, (sx - 2, sy - 2))
                # Position number (1-9 only; beyond that the chevron is enough).
                if i <= 9 and font is not None:
                    txt = font.render(str(i), True, DARK)
                    screen.blit(txt, (cx + r - txt.get_width() - 1,
                                       cy - r + 1 if is_raise else cy + 1))


def make_renderer(cfg: RenderConfig) -> Renderer:
    if cfg.art_style == "pixel":
        return PixelRenderer(cfg)
    if cfg.art_style == "vector":
        raise NotImplementedError(
            "VectorRenderer is on the TODO list. Use art_style = \"pixel\" for now."
        )
    raise ValueError(f"Unknown art_style: {cfg.art_style!r}")
