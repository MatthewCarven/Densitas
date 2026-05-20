"""Configuration loader. Reads config.toml at the project root.

Uses stdlib `tomllib` (Python 3.11+) and falls back to the `tomli` backport
on older versions. Defines frozen dataclasses for type-checked access.
"""
from __future__ import annotations
import sys
from dataclasses import dataclass
from pathlib import Path

try:
    import tomllib  # Python 3.11+
except ImportError:  # pragma: no cover
    import tomli as tomllib  # type: ignore[no-redef]

DEFAULT_CONFIG_PATH = Path(__file__).resolve().parent.parent / "config.toml"


@dataclass(frozen=True)
class WorldConfig:
    width: int
    height: int
    seed: int
    sea_level: float
    beach_thresh: float
    forest_thresh: float
    hill_thresh: float
    mountain_thresh: float


@dataclass(frozen=True)
class RenderConfig:
    art_style: str  # "pixel" (active) or "vector" (not yet implemented)
    tile_size: int
    viewport_w: int
    viewport_h: int
    fps_target: int


@dataclass(frozen=True)
class CameraConfig:
    scroll_speed: float
    edge_scroll_px: int


@dataclass(frozen=True)
class CitizenConfig:
    # Population & lifecycle
    initial_population: int
    spawn_radius_tiles: int
    spawn_seed: int
    maturity_age: float
    lifespan_mean: float
    lifespan_jitter: float
    repro_radius: int
    repro_cooldown: float
    mate_duration: float
    dying_duration: float
    # Movement
    wander_period: float
    wander_radius: int
    wander_speed: float
    # Tick
    tick_hz: int


@dataclass(frozen=True)
class BeliefConfig:
    grid_w: int
    grid_h: int
    amplitude: float
    blur_passes: int
    blur_radius: int
    recompute_hz: int
    overlay_alpha_max: int


@dataclass(frozen=True)
class FoodBiomeConfig:
    forest_initial: float
    forest_regen: float
    grass_initial: float
    grass_regen: float
    beach_initial: float
    beach_regen: float
    hill_initial: float
    hill_regen: float
    holy_initial: float
    holy_regen: float


@dataclass(frozen=True)
class FoodConfig:
    hunger_rate: float
    forage_threshold: float
    repro_hunger_threshold: float
    starve_hunger: float
    eat_amount: float
    eat_duration: float
    bite_size: float
    calorie_per_food: float
    forage_radius_tiles: int
    min_forage_food: float
    overlay_alpha_max: int
    biome: FoodBiomeConfig


@dataclass(frozen=True)
class Config:
    world: WorldConfig
    render: RenderConfig
    camera: CameraConfig
    citizen: CitizenConfig
    belief: BeliefConfig
    food: FoodConfig


def load(path: Path | str = DEFAULT_CONFIG_PATH) -> Config:
    """Load and validate config.toml. Raises FileNotFoundError if missing."""
    p = Path(path)
    with open(p, "rb") as f:
        raw = tomllib.load(f)

    food_raw = dict(raw["food"])
    biome_raw = food_raw.pop("biome")

    return Config(
        world=WorldConfig(**raw["world"]),
        render=RenderConfig(**raw["render"]),
        camera=CameraConfig(**raw["camera"]),
        citizen=CitizenConfig(**raw["citizen"]),
        belief=BeliefConfig(**raw["belief"]),
        food=FoodConfig(biome=FoodBiomeConfig(**biome_raw), **food_raw),
    )
