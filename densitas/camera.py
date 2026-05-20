"""Camera — viewport position in world-pixel coordinates."""
from __future__ import annotations
from dataclasses import dataclass
from .config import CameraConfig, RenderConfig, WorldConfig


@dataclass
class Camera:
    """Top-left of the viewport, in world-pixel coordinates."""
    x: float
    y: float
    cfg: CameraConfig
    render_cfg: RenderConfig
    world_cfg: WorldConfig

    @property
    def world_w_px(self) -> int:
        return self.world_cfg.width * self.render_cfg.tile_size

    @property
    def world_h_px(self) -> int:
        return self.world_cfg.height * self.render_cfg.tile_size

    @property
    def max_x(self) -> float:
        return max(0.0, self.world_w_px - self.render_cfg.viewport_w)

    @property
    def max_y(self) -> float:
        return max(0.0, self.world_h_px - self.render_cfg.viewport_h)

    def clamp(self) -> None:
        self.x = max(0.0, min(self.x, self.max_x))
        self.y = max(0.0, min(self.y, self.max_y))

    def move(self, dx: float, dy: float, dt: float) -> None:
        speed_px = self.cfg.scroll_speed * self.render_cfg.tile_size
        self.x += dx * speed_px * dt
        self.y += dy * speed_px * dt
        self.clamp()

    def update_from_input(self, keys, mouse_pos, dt: float) -> None:
        """Apply WASD/arrow keys plus mouse-edge scrolling."""
        import pygame
        dx = dy = 0.0
        if keys[pygame.K_a] or keys[pygame.K_LEFT]:  dx -= 1
        if keys[pygame.K_d] or keys[pygame.K_RIGHT]: dx += 1
        if keys[pygame.K_w] or keys[pygame.K_UP]:    dy -= 1
        if keys[pygame.K_s] or keys[pygame.K_DOWN]:  dy += 1
        # Edge scroll (only when mouse is over the window)
        mx, my = mouse_pos
        if mx is not None and my is not None:
            edge = self.cfg.edge_scroll_px
            if mx < edge:                                          dx -= 1
            elif mx > self.render_cfg.viewport_w - edge:           dx += 1
            if my < edge:                                          dy -= 1
            elif my > self.render_cfg.viewport_h - edge:           dy += 1
        # Normalize diagonal so diagonal movement isn't sqrt(2) faster
        if dx and dy:
            INV_SQRT2 = 0.7071067811865476
            dx *= INV_SQRT2
            dy *= INV_SQRT2
        self.move(dx, dy, dt)
