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
class RivalConfig:
    """PR4 step 3: the rival god (`Densitas_rival_ai.md` §5, §11).

    Defaults are the spec's opening bids, so `RivalConfig()` is a valid
    stand-in for tests and for a config.toml written before the block
    existed. `personality` picks the brain, not the god - the Maw is the
    skin either way. `difficulty` scales decision *cadence* only (GDD
    §7); it is consumed by step 4's `RivalAI`, as are `ai_base_period`
    and `ai_seed` - they land here so the `[rival]` block is complete
    from the step that introduces it.
    """
    enabled:            bool  = True
    personality:        str   = "zealot"   # zealot | steward | trickster
    difficulty:         float = 1.0        # scales decision cadence ONLY
    initial_population: int   = 8
    spawn_frac_x:       float = 0.75
    spawn_frac_y:       float = 0.50
    spawn_radius_tiles: int   = 5
    ai_base_period:     float = 2.0        # sim_s between decisions at difficulty 1.0
    ai_seed:            int   = 0
    # PR4 step 7a: voice the rival's relic verbs into the scripture log.
    # The player's own relic lines stay on stdout - a line confirming
    # your own click tells you nothing; the Maw's tells you where to
    # look. Decided 2026-09-11.
    relic_scripture:    bool  = True
    # PR4 step 8: the step-6 relic-targeting distances, in world tiles.
    # They started as module constants in rival_ai.py; they are balance
    # dials, so they live here. rival_ai.py documents what each gates.
    relic_spread_tiles:  float = 16.0  # a new flag must be this clear of the planted ones
    move_deadband_tiles: float = 8.0   # a flag drifts this far before RELIC_MOVE touches it
    drift_ref_tiles:     float = 32.0  # drift at which RELIC_MOVE's utility saturates
    # PR4 step 8b: the relic chain. A new flag goes `relic_forward_bias x
    # relic_step_tiles` ahead of the front-most one already planted, and
    # never closer than `relic_standoff_tiles` to the enemy centroid or
    # to any enemy relic. Replaces step 6's lerp toward the enemy
    # centroid, which marched the flags into the enemy's temple.
    relic_step_tiles:    float = 32.0  # full step at forward_bias 1.0
    relic_standoff_tiles: float = 12.0 # the line the chain stops at


PERSONALITIES: tuple[str, ...] = ("zealot", "steward", "trickster")


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
    # PR4 step 8c (2026-09-11): the pull scales with the faction's alive
    # population - `attract_probability x clamp01(pop / attract_pop_ref)`.
    # A village of ten doesn't send pilgrims. Below this, two attractor
    # discs twenty tiles apart left nobody within mating range and the
    # Maw died of age with no births. 1 disables the scaling.
    attract_pop_ref: int = 40


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
    # PR4 step 3: default_factory keeps `Config(...)` constructible
    # without a [rival] block (older config.toml, hand-built test cfgs).
    rival: RivalConfig = field(default_factory=RivalConfig)


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

    # PR4 step 3: [rival] is optional - a config.toml written before the
    # block still loads, with the spec defaults.
    rival = RivalConfig(**dict(raw.get("rival", {})))
    if rival.personality not in PERSONALITIES:
        raise ValueError(
            f"[rival] personality must be one of {PERSONALITIES}, "
            f"got {rival.personality!r}"
        )
    if rival.difficulty <= 0.0:
        raise ValueError(
            f"[rival] difficulty must be > 0, got {rival.difficulty}"
        )

    return Config(
        world=WorldConfig(**raw["world"]),
        render=RenderConfig(**raw["render"]),
        camera=CameraConfig(**raw["camera"]),
        citizen=CitizenConfig(faith=FaithConfig(**faith_raw), **citizen_raw),
        belief=BeliefConfig(**raw["belief"]),
        food=FoodConfig(biome=FoodBiomeConfig(**biome_raw), **food_raw),
        powers=PowerConfig(relic=RelicConfig(**relic_raw), **powers_raw),
        rival=rival,
    )
