"""HUD - heads-up display layer painted last (always on top).

P1+P2+P1.5+P3 elements:
  * Population counter (faction 0)
  * Current divine tier banner
  * Belief pool bar (P3 - replaces the old static total)
  * Hunger summary (fed / hungry / starving) + a slim three-segment bar
  * Cooldown row (P3 - one icon per power, lit/dim/cooling)
  * Scripture log (P3 - top-right corner, last 4 lines, fading)
  * Relic tray (PR3 step 8 - bottom-right corner, 3 slots, display-only)
"""
from __future__ import annotations
import pygame
from typing import Optional

from .citizen import CitizenManager, tier_for, TIERS
from .relics import Relic, RelicState
from .relic_glyphs import (
    GLYPH_SIZE_PX as RELIC_GLYPH_NATIVE_PX,
    GLYPHS_BY_FACTION as RELIC_GLYPHS_BY_FACTION,
)

HUD_BG       = (10, 10, 16, 200)
HUD_PARCH    = (216, 201, 168)
HUD_ACCENT   = (90, 200, 220)
HUD_DIM      = (140, 130, 110)
HUD_GREEN    = (110, 200, 80)
HUD_AMBER    = (220, 170, 60)
HUD_RED      = (210, 70, 60)

# ---- relic tray (PR3 step 8) ----------------------------------------------
# Layout constants live as module-level tuples so the pure helpers below can
# be exercised in unit tests without instantiating pygame surfaces.

TRAY_SLOT_W: int       = 108
TRAY_SLOT_H: int       = 56
TRAY_SLOT_GAP: int     = 3
TRAY_MARGIN: int       = 8
TRAY_GLYPH_PX: int     = 24
TRAY_AVAIL_COLOR       = HUD_GREEN
TRAY_PLACED_COLOR      = HUD_ACCENT
TRAY_THREAT_COLOR      = HUD_AMBER
TRAY_SHATTERED_COLOR   = HUD_RED
TRAY_NAME_COLOR        = HUD_PARCH
TRAY_NAME_STRUCK_COLOR = (130, 90, 90)
TRAY_BG_COLOR          = (12, 12, 20, 210)
SKULL_X_COLOR          = (160, 50, 50)

# Threshold at which the threat bar tips amber -> red (last 30% of the timer).
TRAY_THREAT_RED_FRAC: float = 0.7

# Cooldown row - first letter of each power for the icon labels.
# Kind values mirror PowerKind in powers.py to avoid an import cycle.
COOLDOWN_ICONS: tuple[tuple[int, int, str, tuple[int, int, int]], ...] = (
    # (PowerKind value, tier_required, label, accent_color)
    (0,  1, "I", HUD_ACCENT),                         # INSPIRE
    (1,  1, "C", (160, 160, 200)),                    # CALM
    (2,  1, "H", (200, 100, 100)),                    # HUNGER_PANG
    (10, 2, "R", (200, 170, 80)),                     # RAISE
    (11, 2, "L", (140, 100, 70)),                     # LOWER
    (12, 2, "B", HUD_GREEN),                          # BLESS
    (13, 2, "U", (200, 110, 90)),                     # CURSE
)


# ---------------------------------------------------------------------------
# Pure helpers for the relic tray (no pygame required).
# These are imported by tests/test_relics.py to verify tray geometry and the
# state-to-color / threat-fraction mappings without spinning up SDL.
# ---------------------------------------------------------------------------

def tray_slot_rects(screen_w: int, screen_h: int,
                    n_slots: int = 3) -> list[tuple[int, int, int, int]]:
    """Return (x, y, w, h) tuples for each tray slot.

    Anchored to the bottom-right corner with `TRAY_MARGIN` padding from the
    right and bottom edges. Slots stack horizontally left-to-right in slot
    order so the lowest-slot relic is on the left of the tray.
    """
    total_w = n_slots * TRAY_SLOT_W + max(0, n_slots - 1) * TRAY_SLOT_GAP
    tray_x = screen_w - total_w - TRAY_MARGIN
    tray_y = screen_h - TRAY_SLOT_H - TRAY_MARGIN
    rects = []
    for i in range(n_slots):
        sx = tray_x + i * (TRAY_SLOT_W + TRAY_SLOT_GAP)
        rects.append((sx, tray_y, TRAY_SLOT_W, TRAY_SLOT_H))
    return rects


def tray_status_label(r: "Relic") -> str:
    """Human-readable status string for the second line of a tray slot."""
    if r.state == RelicState.AVAILABLE:
        return "AVAILABLE"
    if r.state == RelicState.PLACED:
        return f"PLACED ({r.tx},{r.ty})"
    if r.state == RelicState.SHATTERED:
        return "SHATTERED"
    return "?"


def tray_status_color(r: "Relic", threat_frac: float = 0.0
                      ) -> tuple[int, int, int]:
    """RGB tint to use for the slot border + status text.

    `threat_frac` is in [0, 1] and only consulted when state == PLACED:
    above `TRAY_THREAT_RED_FRAC` we tip into red, otherwise amber when
    threat > 0, cyan when not threatened.
    """
    if r.state == RelicState.AVAILABLE:
        return TRAY_AVAIL_COLOR
    if r.state == RelicState.SHATTERED:
        return TRAY_SHATTERED_COLOR
    if r.state == RelicState.PLACED:
        if threat_frac <= 0.0:
            return TRAY_PLACED_COLOR
        if threat_frac >= TRAY_THREAT_RED_FRAC:
            return TRAY_SHATTERED_COLOR
        return TRAY_THREAT_COLOR
    return HUD_DIM


def threat_fraction(r: "Relic", shatter_time: float) -> float:
    """Clamp threat_timer / shatter_time to [0, 1]. AVAILABLE and
    SHATTERED relics are always at 0 - their threat timer is meaningless
    (AVAILABLE has never been threatened; SHATTERED is already gone)."""
    if r.state != RelicState.PLACED:
        return 0.0
    if shatter_time <= 0.0:
        return 0.0
    return max(0.0, min(1.0, r.threat_timer / shatter_time))


class HUD:
    def __init__(self):
        self.font_pop    = pygame.font.SysFont("consolas,menlo,monaco,monospace", 22, bold=True)
        self.font_label  = pygame.font.SysFont("consolas,menlo,monaco,monospace", 12)
        self.font_tier   = pygame.font.SysFont("consolas,menlo,monaco,monospace", 14, bold=True)
        self.font_belief = pygame.font.SysFont("consolas,menlo,monaco,monospace", 16, bold=True)
        self.font_small  = pygame.font.SysFont("consolas,menlo,monaco,monospace", 11)
        self.font_chip   = pygame.font.SysFont("consolas,menlo,monaco,monospace", 13, bold=True)
        self.font_log    = pygame.font.SysFont("consolas,menlo,monaco,monospace", 13, italic=True)
        # Tray glyph + skull-X caches are built lazily on first draw so the
        # HUD can be constructed before pygame.display is fully ready.
        self._tray_glyph_cache: dict[int, pygame.Surface] = {}
        self._tray_skull_x: Optional[pygame.Surface] = None

    def draw(self, screen: pygame.Surface, manager: CitizenManager,
              belief=None, powers=None, sim_t: float = 0.0,
              active_mode: Optional[int] = None) -> None:
        pop = manager.population(faction=0)
        tier_name, tier_idx = tier_for(pop)
        next_threshold = self._next_threshold(tier_idx)

        # Box: bottom-left corner. Now taller to hold pool bar + cooldown row.
        box_x, box_y = 8, screen.get_height() - 168
        box_w, box_h = 360, 160

        overlay = pygame.Surface((box_w, box_h), pygame.SRCALPHA)
        overlay.fill(HUD_BG)
        screen.blit(overlay, (box_x, box_y))

        # POPULATION
        label = self.font_label.render("POPULATION", True, HUD_DIM)
        screen.blit(label, (box_x + 12, box_y + 6))
        pop_text = self.font_pop.render(f"{pop:,}", True, HUD_PARCH)
        screen.blit(pop_text, (box_x + 12, box_y + 18))

        # BELIEF (pool)
        pool_value = 0.0
        if powers is not None:
            pool_value = powers.pool[0] if len(powers.pool) > 0 else 0.0
        bf_label = self.font_label.render("BELIEF POOL", True, HUD_DIM)
        screen.blit(bf_label, (box_x + 130, box_y + 6))
        bf_text = self.font_belief.render(f"{pool_value:.0f}", True, HUD_ACCENT)
        screen.blit(bf_text, (box_x + 130, box_y + 22))

        # Field total in dim text for context.
        if belief is not None:
            field_total = belief.total(0)
            ft_label = self.font_small.render(
                f"field: {field_total:.0f}", True, HUD_DIM,
            )
            screen.blit(ft_label, (box_x + 130 + bf_text.get_width() + 8, box_y + 28))

        # Tier name + progress
        tier_text = self.font_tier.render(tier_name, True, HUD_ACCENT)
        screen.blit(tier_text, (box_x + 12, box_y + 50))
        if next_threshold is not None:
            need = max(0, next_threshold - pop)
            sub = self.font_label.render(
                f"+{need} for {self._next_tier_name(tier_idx)}",
                True, HUD_DIM,
            )
            screen.blit(sub, (box_x + 12 + tier_text.get_width() + 8, box_y + 52))

        # Tier pips
        pip_x = box_x + box_w - 12 - (5 * 12)
        pip_y = box_y + 50
        for i in range(5):
            color = HUD_ACCENT if i < tier_idx else HUD_DIM
            pygame.draw.circle(screen, color, (pip_x + i * 12, pip_y), 3)
            label_t = self.font_label.render(f"T{i}", True, color)
            screen.blit(label_t, (pip_x + i * 12 - 7, pip_y + 6))

        # Hunger row -------------------------------------------------------
        fed, hungry, starving, avg = manager.hunger_stats(faction=0)
        total_alive = max(1, fed + hungry + starving)
        fed_pct      = 100 * fed      / total_alive
        hungry_pct   = 100 * hungry   / total_alive
        starve_pct   = 100 * starving / total_alive

        hy = box_y + 76
        hl_fed     = self.font_small.render(f"FED {fed_pct:.0f}%",          True, HUD_GREEN)
        hl_hungry  = self.font_small.render(f"HUNGRY {hungry_pct:.0f}%",     True, HUD_AMBER)
        hl_starve  = self.font_small.render(f"STARVING {starve_pct:.0f}%",   True, HUD_RED)
        screen.blit(hl_fed,    (box_x + 12, hy))
        screen.blit(hl_hungry, (box_x + 12 + hl_fed.get_width() + 10, hy))
        screen.blit(hl_starve, (box_x + 12 + hl_fed.get_width() + 12 + hl_hungry.get_width(), hy))

        # Three-segment stacked hunger bar
        bar_x, bar_y = box_x + 12, box_y + 92
        bar_w, bar_h = box_w - 24, 6
        pygame.draw.rect(screen, (40, 40, 50), (bar_x, bar_y, bar_w, bar_h))
        seg_fed = int(bar_w * fed / total_alive)
        seg_hun = int(bar_w * hungry / total_alive)
        seg_str = bar_w - seg_fed - seg_hun
        cur = bar_x
        if seg_fed:
            pygame.draw.rect(screen, HUD_GREEN, (cur, bar_y, seg_fed, bar_h))
            cur += seg_fed
        if seg_hun:
            pygame.draw.rect(screen, HUD_AMBER, (cur, bar_y, seg_hun, bar_h))
            cur += seg_hun
        if seg_str:
            pygame.draw.rect(screen, HUD_RED, (cur, bar_y, seg_str, bar_h))

        # Pool fill bar ---------------------------------------------------
        # Soft cap reference: hint at the 5000 + 10*pop heuristic without enforcing.
        cap_hint = max(50.0, 5000.0 + 10.0 * pop)
        pool_frac = min(1.0, pool_value / cap_hint)
        pbar_x, pbar_y = box_x + 12, box_y + 104
        pbar_w, pbar_h = box_w - 24, 4
        pygame.draw.rect(screen, (40, 40, 60), (pbar_x, pbar_y, pbar_w, pbar_h))
        if pool_frac > 0.0:
            pygame.draw.rect(screen, HUD_ACCENT,
                              (pbar_x, pbar_y, int(pbar_w * pool_frac), pbar_h))

        # Cooldown row ----------------------------------------------------
        if powers is not None:
            self._draw_cooldown_row(
                screen,
                origin=(box_x + 12, box_y + 116),
                tier_idx=tier_idx,
                powers=powers,
                active_mode=active_mode,
            )

        # Scripture log ---------------------------------------------------
        if powers is not None and powers.scripture_log:
            self._draw_scripture_log(screen, powers, sim_t)

    # -- PR3 step 10: relic mode indicator ---------------------------------

    def draw_relic_mode_chip(self, screen: pygame.Surface,
                              label: str,
                              accent: tuple[int, int, int] = None) -> None:
        """Floating chip naming the active relic mode + slot.

        Sits just above the existing bottom-left HUD box. Called from
        main.py only when `relic_input` is not None. The accent colour
        defaults to the global HUD_ACCENT (cyan) but can be overridden
        per-mode (e.g. amber for MOVE, red-ish for RETRIEVE).
        """
        if accent is None:
            accent = HUD_ACCENT
        pad_x, pad_y = 10, 5
        text_surf = self.font_chip.render(label, True, accent)
        chip_w = text_surf.get_width() + pad_x * 2
        chip_h = text_surf.get_height() + pad_y * 2
        # Coords: bottom-left, just above the HUD box (which sits at
        # screen_h - 168).
        cx = 8
        cy = screen.get_height() - 168 - chip_h - 6
        bg = pygame.Surface((chip_w, chip_h), pygame.SRCALPHA)
        bg.fill((10, 10, 16, 220))
        screen.blit(bg, (cx, cy))
        pygame.draw.rect(screen, accent, (cx, cy, chip_w, chip_h), width=1)
        screen.blit(text_surf, (cx + pad_x, cy + pad_y))

    # -- PR3 step 8: relic tray ---------------------------------------------

    def blit_relic_tray(self, screen: pygame.Surface,
                         relics, sim_t: float,
                         shatter_time: float,
                         mouse_pos: Optional[tuple[int, int]] = None):
        """Display-only tray (`Densitas_relics.md` section 5).

        Bottom-right corner, 3 horizontal slots showing the player's
        relics. Each slot renders glyph + name + status + (when PLACED)
        an age/threat bar; SHATTERED slots show a skull-X icon and
        struck-through name. Tooltips appear when `mouse_pos` is inside
        a slot.

        Returns a list of `(rect, relic)` pairs so callers (`main.py`
        eventually, PR3 step 9 specifically) can route click-to-reopen
        on SHATTERED slots without re-deriving the geometry.

        `relics` may be longer than 3; the tray renders all of them
        in order, which for T0 == initial_count == 3.
        """
        if not relics:
            return []
        self._ensure_tray_assets()
        sw, sh = screen.get_width(), screen.get_height()
        rects = tray_slot_rects(sw, sh, n_slots=len(relics))
        result = []
        for r, (sx, sy, sw_slot, sh_slot) in zip(relics, rects):
            frac = threat_fraction(r, shatter_time)
            border = tray_status_color(r, frac)
            slot_rect = pygame.Rect(sx, sy, sw_slot, sh_slot)

            # Background panel
            bg = pygame.Surface((sw_slot, sh_slot), pygame.SRCALPHA)
            bg.fill(TRAY_BG_COLOR)
            screen.blit(bg, (sx, sy))
            pygame.draw.rect(screen, border, slot_rect, width=1)

            # Glyph
            self._blit_tray_glyph(screen, r, sx + 6, sy + 6)

            # Name (struck-through when SHATTERED)
            name_color = (
                TRAY_NAME_STRUCK_COLOR
                if r.state == RelicState.SHATTERED
                else TRAY_NAME_COLOR
            )
            name_surf = self.font_label.render(r.name, True, name_color)
            screen.blit(name_surf, (sx + 34, sy + 8))
            if r.state == RelicState.SHATTERED:
                # Strike-through line through the middle of the name surf.
                line_y = sy + 8 + name_surf.get_height() // 2
                pygame.draw.line(
                    screen, TRAY_NAME_STRUCK_COLOR,
                    (sx + 34, line_y),
                    (sx + 34 + name_surf.get_width(), line_y),
                    1,
                )

            # Status line
            status = tray_status_label(r)
            status_surf = self.font_small.render(status, True, border)
            screen.blit(status_surf, (sx + 34, sy + 24))

            # Threat / age bar (PLACED only)
            if r.state == RelicState.PLACED:
                bar_x = sx + 34
                bar_y = sy + 42
                bar_w = 68
                bar_h = 4
                pygame.draw.rect(screen, (40, 40, 50),
                                  (bar_x, bar_y, bar_w, bar_h))
                fill_color = (
                    TRAY_SHATTERED_COLOR
                    if frac >= TRAY_THREAT_RED_FRAC
                    else (TRAY_THREAT_COLOR if frac > 0.0 else TRAY_PLACED_COLOR)
                )
                # When not threatened we show a thin age tick (last 30 s of
                # placement). When threatened we show the threat fraction.
                if frac > 0.0:
                    fill_w = max(1, int(bar_w * frac))
                else:
                    age = max(0.0, sim_t - r.placed_at)
                    # Saturate at 30 sim_sec (the place_cooldown / fade-in
                    # window). After that the tick stays full and dim.
                    age_frac = max(0.0, min(1.0, age / 30.0))
                    fill_w = max(0, int(bar_w * age_frac))
                if fill_w > 0:
                    pygame.draw.rect(screen, fill_color,
                                      (bar_x, bar_y, fill_w, bar_h))
                # Threat seconds numeric overlay (right-aligned of bar)
                if frac > 0.0:
                    remain = max(0.0, shatter_time - r.threat_timer)
                    num = self.font_small.render(
                        f"{remain:.1f}s", True, fill_color,
                    )
                    screen.blit(num, (sx + sw_slot - num.get_width() - 6,
                                       sy + 38))

            result.append((slot_rect, r))

            # Hover tooltip
            if mouse_pos is not None and slot_rect.collidepoint(mouse_pos):
                self._draw_tray_tooltip(screen, r, mouse_pos)

        return result

    def _blit_tray_glyph(self, screen: pygame.Surface, r,
                          gx: int, gy: int) -> None:
        """Pick the right cached icon for `r` and blit it at (gx, gy)."""
        if r.state == RelicState.SHATTERED:
            if self._tray_skull_x is not None:
                screen.blit(self._tray_skull_x, (gx, gy))
            return
        sprite = self._tray_glyph_cache.get(int(r.faction))
        if sprite is None:
            return
        if r.state == RelicState.PLACED:
            # Desaturate by alpha drop - the cheap way to say "in use".
            ghost = sprite.copy()
            ghost.set_alpha(180)
            screen.blit(ghost, (gx, gy))
        else:
            screen.blit(sprite, (gx, gy))

    def _draw_tray_tooltip(self, screen: pygame.Surface, r,
                            mouse_pos: tuple[int, int]) -> None:
        """One-line tooltip beneath the cursor. Hint matches the spec:
        AVAILABLE -> 'Press R to place.'; SHATTERED -> 'Lost at (tx,ty)
        - click to view.' (panel hookup lands with step 9).
        PLACED gets a quieter tooltip with the tile coords.
        """
        if r.state == RelicState.AVAILABLE:
            txt = "Press R to place."
        elif r.state == RelicState.SHATTERED:
            txt = f"Lost at ({r.tx},{r.ty}) - click to view."
        else:
            txt = f"Placed at ({r.tx},{r.ty})."
        surf = self.font_small.render(txt, True, HUD_PARCH)
        pad = 4
        tw = surf.get_width() + pad * 2
        th = surf.get_height() + pad * 2
        # Anchor above the cursor so it never clips the tray itself.
        mx, my = mouse_pos
        tx = max(4, min(screen.get_width() - tw - 4, mx + 12))
        ty = max(4, my - th - 8)
        bg = pygame.Surface((tw, th), pygame.SRCALPHA)
        bg.fill((10, 10, 16, 230))
        screen.blit(bg, (tx, ty))
        pygame.draw.rect(screen, HUD_DIM, (tx, ty, tw, th), width=1)
        screen.blit(surf, (tx + pad, ty + pad))

    def _ensure_tray_assets(self) -> None:
        """Build the tray glyph + skull-X cache on first use."""
        if not self._tray_glyph_cache:
            native = RELIC_GLYPH_NATIVE_PX
            target = TRAY_GLYPH_PX
            for faction, (palette, pixels) in RELIC_GLYPHS_BY_FACTION.items():
                surf = pygame.Surface((native, native), pygame.SRCALPHA)
                surf.fill((0, 0, 0, 0))
                for x, y, pal_idx in pixels:
                    rc, gc, bc = palette[pal_idx]
                    surf.set_at((x, y), (rc, gc, bc, 255))
                if target != native:
                    surf = pygame.transform.scale(surf, (target, target))
                self._tray_glyph_cache[faction] = surf
        if self._tray_skull_x is None:
            self._tray_skull_x = self._build_skull_x(TRAY_GLYPH_PX)

    @staticmethod
    def _build_skull_x(size: int) -> pygame.Surface:
        """Constant 'gone' icon: a stylised X with two thicker strokes.

        Drawn once into a cached surface. Same icon for all factions/slots
        when state is SHATTERED, per `Densitas_relics.md` section 5.
        """
        surf = pygame.Surface((size, size), pygame.SRCALPHA)
        surf.fill((0, 0, 0, 0))
        # Dimmer border ring so the icon reads as "framed" against the panel.
        pygame.draw.rect(surf, (50, 20, 20), (0, 0, size, size), width=1)
        # X strokes
        pad = 4
        pygame.draw.line(surf, SKULL_X_COLOR,
                          (pad, pad), (size - 1 - pad, size - 1 - pad),
                          width=3)
        pygame.draw.line(surf, SKULL_X_COLOR,
                          (size - 1 - pad, pad), (pad, size - 1 - pad),
                          width=3)
        # Single darker overstroke down each diagonal for the etched look.
        pygame.draw.line(surf, (90, 20, 20),
                          (pad, pad), (size - 1 - pad, size - 1 - pad),
                          width=1)
        pygame.draw.line(surf, (90, 20, 20),
                          (size - 1 - pad, pad), (pad, size - 1 - pad),
                          width=1)
        return surf

    def _draw_cooldown_row(self, screen, origin, tier_idx, powers,
                            active_mode: Optional[int]) -> None:
        """7 small icons, one per power kind. Tier-locked = dim grey.
        Cooling = darkened with a small numeric overlay. Active = brightened ring."""
        ix, iy = origin
        size = 30
        gap = 5
        for kind_val, tier_req, label, accent in COOLDOWN_ICONS:
            unlocked = tier_idx >= tier_req
            cd = 0.0
            if (0, kind_val) in powers.cooldowns:
                cd = powers.cooldowns[(0, kind_val)]
            rect = pygame.Rect(ix, iy, size, size)
            if not unlocked:
                pygame.draw.rect(screen, (30, 30, 36), rect)
                pygame.draw.rect(screen, HUD_DIM, rect, width=1)
                txt = self.font_chip.render(label, True, HUD_DIM)
            elif cd > 0.0:
                pygame.draw.rect(screen, (30, 30, 36), rect)
                pygame.draw.rect(screen, HUD_AMBER, rect, width=1)
                # Numeric cooldown.
                txt = self.font_chip.render(f"{cd:.1f}", True, HUD_AMBER)
            else:
                pygame.draw.rect(screen, (40, 40, 48), rect)
                pygame.draw.rect(screen, accent, rect, width=1)
                txt = self.font_chip.render(label, True, accent)
            tx = ix + (size - txt.get_width()) // 2
            ty = iy + (size - txt.get_height()) // 2
            screen.blit(txt, (tx, ty))
            # Active-mode highlight ring.
            if active_mode is not None and int(active_mode) == kind_val:
                pygame.draw.rect(screen, HUD_PARCH, rect.inflate(4, 4), width=2)
            # Queue count badge (P3-Queue): tiny superscript in upper-right.
            q = getattr(powers, "queues", {})
            n_q = len(q.get((0, kind_val), []))
            if n_q:
                # Cap visible badge at 9; queue holds more.
                txt = self.font_small.render(
                    str(min(n_q, 9)) + ("+" if n_q > 9 else ""),
                    True, HUD_AMBER,
                )
                bx = ix + size - txt.get_width() - 2
                by = iy + 2
                bg = pygame.Surface(
                    (txt.get_width() + 2, txt.get_height()),
                    pygame.SRCALPHA,
                )
                bg.fill((10, 10, 16, 200))
                screen.blit(bg, (bx - 1, by))
                screen.blit(txt, (bx, by))
            ix += size + gap

    def _draw_scripture_log(self, screen, powers, sim_t: float) -> None:
        """Render the last few scripture entries top-right, fading by age."""
        log = powers.scripture_log
        if not log:
            return
        # Show the most-recent 4 entries.
        tail = log[-4:]
        sw = screen.get_width()
        # Compute layout: right-aligned, top margin 8.
        margin = 12
        max_w = 420
        line_h = self.font_log.get_linesize()
        # Render bottom-up so newest stays at top of stack.
        entries = []
        for e in tail:
            age = max(0.0, sim_t - e.sim_t)
            life = max(0.01, powers.cfg.rhetoric_fade_seconds)
            alpha = int(max(0.0, min(1.0, 1.0 - age / life)) * 230)
            if alpha <= 4:
                continue
            surf = self.font_log.render(e.line, True, HUD_PARCH)
            surf.set_alpha(alpha)
            entries.append(surf)
        if not entries:
            return
        # Stack top-down with newest at top.
        oy = margin
        for surf in reversed(entries):  # newest last in tail -> draw last so it overlays old
            w = min(surf.get_width(), max_w)
            x = sw - w - margin
            bg = pygame.Surface((w + 12, line_h + 4), pygame.SRCALPHA)
            bg.fill((10, 10, 16, 140))
            screen.blit(bg, (x - 6, oy - 2))
            screen.blit(surf, (x, oy))
            oy += line_h + 2

    @staticmethod
    def _next_threshold(tier_idx: int):
        if tier_idx >= len(TIERS):
            return None
        return TIERS[tier_idx][1]

    @staticmethod
    def _next_tier_name(tier_idx: int) -> str:
        if tier_idx >= len(TIERS):
            return "-"
        return TIERS[tier_idx][0]
