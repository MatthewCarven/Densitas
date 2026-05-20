"""HUD - heads-up display layer painted last (always on top).

P1+P2+P1.5 elements:
  * Population counter (faction 0)
  * Current divine tier banner
  * Belief total
  * Hunger summary (fed / hungry / starving) + a slim health bar
"""
from __future__ import annotations
import pygame
from .citizen import CitizenManager, tier_for, TIERS

HUD_BG       = (10, 10, 16, 200)
HUD_PARCH    = (216, 201, 168)
HUD_ACCENT   = (90, 200, 220)
HUD_DIM      = (140, 130, 110)
HUD_GREEN    = (110, 200, 80)
HUD_AMBER    = (220, 170, 60)
HUD_RED      = (210, 70, 60)


class HUD:
    def __init__(self):
        self.font_pop    = pygame.font.SysFont("consolas,menlo,monaco,monospace", 22, bold=True)
        self.font_label  = pygame.font.SysFont("consolas,menlo,monaco,monospace", 12)
        self.font_tier   = pygame.font.SysFont("consolas,menlo,monaco,monospace", 14, bold=True)
        self.font_belief = pygame.font.SysFont("consolas,menlo,monaco,monospace", 16, bold=True)
        self.font_small  = pygame.font.SysFont("consolas,menlo,monaco,monospace", 11)

    def draw(self, screen: pygame.Surface, manager: CitizenManager,
              belief=None) -> None:
        pop = manager.population(faction=0)
        tier_name, tier_idx = tier_for(pop)
        next_threshold = self._next_threshold(tier_idx)

        # Box: bottom-left corner. Taller now to hold the hunger bar.
        box_x, box_y = 8, screen.get_height() - 124
        box_w, box_h = 320, 116

        overlay = pygame.Surface((box_w, box_h), pygame.SRCALPHA)
        overlay.fill(HUD_BG)
        screen.blit(overlay, (box_x, box_y))

        # POPULATION
        label = self.font_label.render("POPULATION", True, HUD_DIM)
        screen.blit(label, (box_x + 12, box_y + 6))
        pop_text = self.font_pop.render(f"{pop:,}", True, HUD_PARCH)
        screen.blit(pop_text, (box_x + 12, box_y + 18))

        # BELIEF
        bf_label = self.font_label.render("BELIEF", True, HUD_DIM)
        screen.blit(bf_label, (box_x + 130, box_y + 6))
        if belief is not None:
            bf_text = self.font_belief.render(f"{belief.total(0):.0f}", True, HUD_ACCENT)
            screen.blit(bf_text, (box_x + 130, box_y + 22))

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

        # Three labels
        hy = box_y + 78
        hl_fed     = self.font_small.render(f"FED {fed_pct:.0f}%",          True, HUD_GREEN)
        hl_hungry  = self.font_small.render(f"HUNGRY {hungry_pct:.0f}%",     True, HUD_AMBER)
        hl_starve  = self.font_small.render(f"STARVING {starve_pct:.0f}%",   True, HUD_RED)
        screen.blit(hl_fed,    (box_x + 12, hy))
        screen.blit(hl_hungry, (box_x + 12 + hl_fed.get_width() + 10, hy))
        screen.blit(hl_starve, (box_x + 12 + hl_fed.get_width() + 12 + hl_hungry.get_width(), hy))

        # Stacked bar — 3 segments proportional to fed / hungry / starving.
        bar_x, bar_y = box_x + 12, box_y + 96
        bar_w, bar_h = box_w - 24, 8
        # background
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
