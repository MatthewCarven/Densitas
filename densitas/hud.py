"""HUD - heads-up display layer painted last (always on top).

P1+P2+P1.5+P3 elements:
  * Population counter (faction 0)
  * Current divine tier banner
  * Belief pool bar (P3 — replaces the old static total)
  * Hunger summary (fed / hungry / starving) + a slim three-segment bar
  * Cooldown row (P3 — one icon per power, lit/dim/cooling)
  * Scripture log (P3 — top-right corner, last 4 lines, fading)
"""
from __future__ import annotations
import pygame
from typing import Optional

from .citizen import CitizenManager, tier_for, TIERS

HUD_BG       = (10, 10, 16, 200)
HUD_PARCH    = (216, 201, 168)
HUD_ACCENT   = (90, 200, 220)
HUD_DIM      = (140, 130, 110)
HUD_GREEN    = (110, 200, 80)
HUD_AMBER    = (220, 170, 60)
HUD_RED      = (210, 70, 60)

# Cooldown row — first letter of each power for the icon labels.
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


class HUD:
    def __init__(self):
        self.font_pop    = pygame.font.SysFont("consolas,menlo,monaco,monospace", 22, bold=True)
        self.font_label  = pygame.font.SysFont("consolas,menlo,monaco,monospace", 12)
        self.font_tier   = pygame.font.SysFont("consolas,menlo,monaco,monospace", 14, bold=True)
        self.font_belief = pygame.font.SysFont("consolas,menlo,monaco,monospace", 16, bold=True)
        self.font_small  = pygame.font.SysFont("consolas,menlo,monaco,monospace", 11)
        self.font_chip   = pygame.font.SysFont("consolas,menlo,monaco,monospace", 13, bold=True)
        self.font_log    = pygame.font.SysFont("consolas,menlo,monaco,monospace", 13, italic=True)

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
    def _next_threshold(tier_idx: int) -> int | None:
        if tier_idx >= len(TIERS):
            return None
        return TIERS[tier_idx][1]

    @staticmethod
    def _next_tier_name(tier_idx: int) -> str:
        if tier_idx >= len(TIERS):
            return "-"
        return TIERS[tier_idx][0]
