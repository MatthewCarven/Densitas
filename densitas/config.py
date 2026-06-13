"""Configuration loader. Reads config.toml at the project root.

Uses stdlib `tomllib` (Python 3.11+) and falls back to the `tomli` backport
on older versions. Defines frozen dataclasses for type-checked access.
"""
from __future__ import annotations
import sys
from dataclasses import dataclass, field
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
class FaithConfig:
    """PR4 step 1: the conversion stat (`Densitas_rival_ai.md` §2, §11).

    Defaults are the spec's opening bids; every value is a playtest
    knob. `ceremony_duration`, the thresholds, `convert_faith_reset`
    and `scripture_coalesce_window` are consumed by later PR4 steps -
    they land here so the `[citizen.faith]` block is complete from
    step 1.
    """
    drain_rate:          float = 0.08  # faith/sim_s under total rival dominance
    regen_rate:          float = 0.04  # faith/sim_s deep in your own field
    regen_ref:           float = 0.50  # belief level giving full-rate regen
    convert_threshold:   float = 0.30
    despair_threshold:   float = 0.05
    min_convert_belief:  float = 0.05  # receiving field must be at least this
    ceremony_duration:   float = 1.5   # sim_s standing in CONVERTED
    convert_faith_reset: float = 0.60
    scripture_coalesce_window: float = 5.0


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
    # PR4 step 1: faith / conversion knobs. Optional for P1-P3
    # backward-compat (same pattern as CitizenManager's food_cfg):
    # when None, the faith update is disabled entirely.
    faith: "FaithConfig | None" = None


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
    satiation_cap: float
    forage_radius_tiles: int
    min_forage_food: float
    overlay_alpha_max: int
    biome: FoodBiomeConfig


@dataclass(frozen=True)
class RelicConfig:
    amplitude: float
    place_cooldown: float
    shatter_ratio: float
    shatter_time: float
    attract_radius: int
    attract_probability: float
    initial_count: int


@dataclass(frozen=True)
class PowerConfig:
    """P3: PowerSystem tunables.

    `k_tier` is a list of length N_TIERS+1 indexed 0..4 mapping tier
    index to the divisor used in strength scaling. Sensible defaults:
    higher tiers have larger divisors so the scaling stays in roughly
    1.0-ish range across tiers when local belief is "decent for that tier".
    """
    belief_regen_per_citizen: float
    k_tier: tuple[float, ...]
    rhetoric_fade_seconds: float
    scripture_log_max: int
    # Cooldown overrides (None = use POWERS spec default)
    inspire_cooldown: float
    calm_cooldown: float
    hunger_pang_cooldown: float
    raise_cooldown: float
    lower_cooldown: float
    bless_cooldown: float
    curse_cooldown: float
    # Effect multipliers
    bless_multiplier: float
    curse_multiplier: float
    effect_duration_t1: float
    # AoE radii (some are 0 for point targets)
    inspire_radius: int
    hunger_pang_radius: int
    bless_radius: int
    curse_radius: int
    # P3-Queue — cast queue (Raise / Lower).
    queue_cap: int    # max pending QueuedCasts per (faction, queueable kind)
    relic: RelicConfig


@dataclass(frozen=True)
class Config:
    world: WorldConfig
    render: RenderConfig
    camera: CameraConfig
    citizen: CitizenConfig
    belief: BeliefConfig
    food: FoodConfig
    powers: PowerConfig


def load(path: Path | str = DEFAULT_CONFIG_PATH) -> Config:
    """Load and validate config.toml. Raises FileNotFoundError if missing."""
    p = Path(path)
    with open(p, "rb") as f:
        raw = tomllib.load(f)

    food_raw = dict(raw["food"])
    biome_raw = food_raw.pop("biome")

    powers_raw = dict(raw["powers"])
    relic_raw = powers_raw.pop("relic")
    # Normalise list -> tuple for k_tier.
    powers_raw["k_tier"] = tuple(float(x) for x in powers_raw["k_tier"])

    citizen_raw = dict(raw["citizen"])
    faith_raw = citizen_raw.pop("faith")

    return Config(
        world=WorldConfig(**raw["world"]),
        render=RenderConfig(**raw["render"]),
        camera=CameraConfig(**raw["camera"]),
        citizen=CitizenConfig(faith=FaithConfig(**faith_raw), **citizen_raw),
        belief=BeliefConfig(**raw["belief"]),
        food=FoodConfig(biome=FoodBiomeConfig(**biome_raw), **food_raw),
        powers=PowerConfig(relic=RelicConfig(**relic_raw), **powers_raw),
    )
