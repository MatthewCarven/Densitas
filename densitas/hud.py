"""HUD - heads-up display layer painted last (always on top).

P1+P2 elements:
  * Population counter (faction 0)
  * Current divine tier banner
  * Belief total (= integral of player faction belief field)

Future:
  * Belief-strength dial (P3)
  * Relic state pips (P3)
  * Rival pop indicator (P4)
"""
from __future__ import annotations
import pygame
from .citizen import CitizenManager, tier_for, TIERS

# Palette - kept thematic with the Open Eye's parchment + cyan accent.
HUD_BG       = (10, 10, 16, 200)
HUD_PARCH    = (216, 201, 168)
HUD_ACCENT   = (90, 200, 220)
HUD_DIM      = (140, 130, 110)


class HUD:
    """Stateless drawer; constructed once, called every frame."""

    def __init__(self):
        self.font_pop   = pygame.font.SysFont("consolas,menlo,monaco,monospace", 22, bold=True)
        self.font_label = pygame.font.SysFont("consolas,menlo,monaco,monospace", 12)
        self.font_tier  = pygame.font.SysFont("consolas,menlo,monaco,monospace", 14, bold=True)
        self.font_belief = pygame.font.SysFont("consolas,menlo,monaco,monospace", 16, bold=True)

    def draw(self, screen: pygame.Surface, manager: CitizenManager,
              belief=None) -> None:
        pop = manager.population(faction=0)
        tier_name, tier_idx = tier_for(pop)
        next_threshold = self._next_threshold(tier_idx)

        # Box: bottom-left corner.
        box_x, box_y = 8, screen.get_height() - 96
        box_w, box_h = 280, 88

        overlay = pygame.Surface((box_w, box_h), pygame.SRCALPHA)
        overlay.fill(HUD_BG)
        screen.blit(overlay, (box_x, box_y))

        # POPULATION label + number
        label = self.font_label.render("POPULATION", True, HUD_DIM)
        screen.blit(label, (box_x + 12, box_y + 6))
        pop_text = self.font_pop.render(f"{pop:,}", True, HUD_PARCH)
        screen.blit(pop_text, (box_x + 12, box_y + 18))

        # BELIEF label + number (just under population)
        bf_label = self.font_label.render("BELIEF", True, HUD_DIM)
        screen.blit(bf_label, (box_x + 110, box_y + 6))
        if belief is not None:
            bf_total = belief.total(0)
            bf_text = self.font_belief.render(f"{bf_total:.0f}", True, HUD_ACCENT)
            screen.blit(bf_text, (box_x + 110, box_y + 22))

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

        # Tier pips (T0..T4 dots, brighter for reached)
        pip_x = box_x + box_w - 12 - (5 * 12)
        pip_y = box_y + 72
        for i in range(5):
            color = HUD_ACCENT if i < tier_idx else HUD_DIM
            pygame.draw.circle(screen, color, (pip_x + i * 12, pip_y), 3)
            label = self.font_label.render(f"T{i}", True, color)
            screen.blit(label, (pip_x + i * 12 - 7, pip_y + 6))

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
