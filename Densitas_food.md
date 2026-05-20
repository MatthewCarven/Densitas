# Densitas — Food, Forage & Hunger Spec (P1.5)

**Status:** v0.1, 2026-05-21. Closes the population blowup discovered at the end of P2 (uncapped exponential growth — a default seed hit 132,797 citizens at sim_t ~620s). P1.5 introduces resource pressure as the natural carrying-capacity mechanism, replacing what a band-aid would have papered over.

The proper way: food is a tile attribute that regenerates by biome. Citizens consume what's around them. Hungry citizens won't mate; starving citizens die. Equilibrium population emerges from the ratio of land's regen rate to per-citizen consumption.

---

## 1. Pillars

1. **Food is a property of the land, not an entity.** No food objects to manage, render, or pathfind to. Each tile holds a `food: float` value alongside its type, regenerating up to a per-biome cap.
2. **Hunger is the population control.** Reproduction is gated on hunger, not on a hard cap. When a region's regen can't keep up with its calorie load, mating slows and deaths catch up — a soft, self-balancing ceiling.
3. **Death from starvation looks like decline.** Belief drops gradually as the population cascades down. DYING citizens fade their belief contribution over their dying state, so the heatmap shrinks visibly.
4. **Eat in place, for now.** Citizens consume from the tile they're standing on. A future inventory tier (food 0–5, sword, shield) is anticipated — the dataclass carries `food_carried: int = 0` today as a placeholder so the migration is one feature, not a refactor.

---

## 2. World extension

### 2.1 New per-tile channel

```
world.food : np.ndarray[(height, width)], dtype=float32
```

Same shape as `world.tiles`. Indexed `[ty, tx]`.

### 2.2 Biome regen table

| Tile      | Initial / Cap | Regen / sim sec | Notes                              |
|-----------|---------------|-----------------|------------------------------------|
| FOREST    | 8.0           | 0.10            | berries + game; richest             |
| GRASS     | 5.0           | 0.08            | wild grain                          |
| BEACH     | 3.0           | 0.05            | shellfish + tide pools              |
| HILL      | 2.0           | 0.03            | sparse game                         |
| HOLY      | 1.0           | 0.02            | symbolic — manna                    |
| MOUNTAIN  | 0             | 0               | barren                              |
| WATER     | 0             | 0               | (fishing structures: P3)            |
| LAVA      | 0             | 0               | barren                              |
| BLIGHTED  | 0             | 0               | barren — Cataclysm-tier output      |

All values tunable via `config.toml`. Carried by a `[food.biome]` sub-table keyed by tile name.

### 2.3 Regen pass

Per citizen tick (5 Hz, same cadence as belief):

```python
food += regen_per_tile * tick_dt
np.minimum(food, food_cap_per_tile, out=food)
```

`regen_per_tile` and `food_cap_per_tile` are world-shape arrays precomputed from `world.tiles` at world load and held inside `World` (or a sibling `FoodField` — see §10).

Cost: 49,152 cells (default world) × one numpy add + clamp = sub-millisecond.

A `food_version: int` counter bumps on each regen so the food overlay can cache like belief does.

---

## 3. Citizen extension

### 3.1 New dataclass fields

```python
hunger: float          # 0.0 fed -> 1.0 starving
food_carried: int = 0  # P1.5 unused; reserved for future inventory tier
```

`hunger` initializes to a random value in `[0.0, 0.2]` at spawn so a new generation isn't synchronised.

### 3.2 New FSM transitions

Existing P1 states: IDLE / WANDER / MATE / DYING. P1.5 activates FORAGE and EATING (currently placeholders).

```
IDLE / WANDER
  ├── hunger > forage_threshold  -> FORAGE
  └── (otherwise: IDLE/WANDER as P1)

FORAGE
  ├── on a food-bearing tile     -> EATING
  ├── no food in forage_radius   -> WANDER outward (existing wander)
  └── hunger >= starve_hunger    -> DYING (starvation)

EATING
  ├── for eat_duration sim sec, consume: tile.food -= bite_size,
  │                                       hunger   -= bite_size * calorie_per_food
  │   clamped: hunger >= 0, tile.food >= 0
  ├── tile food exhausted        -> FORAGE (find a new tile)
  └── hunger <= 0                -> IDLE

MATE (existing)
  ├── partner.hunger >= repro_hunger_threshold  -> not eligible (gate)
```

### 3.3 Hunger accrual

Per tick:

```
c.hunger += hunger_rate * tick_dt          # always increases
np.clip(c.hunger, 0.0, 1.0)                 # cap at starving
```

`hunger_rate` is a config knob (sim sec to reach 1.0 from 0.0). Default first pass: 0.005/s ≈ 200s to fully starve from full.

### 3.4 Reproduction gate

`CitizenManager._find_mate` already checks faction, age, cooldown. Add: both partners must have `hunger < repro_hunger_threshold` (default 0.3). Mating consumes a small amount of additional hunger on both (handwaved as "the energy cost of carrying the next generation").

### 3.5 Starvation -> DYING

When `c.hunger >= 1.0`, transition to DYING with the existing `dying_duration`. The starvation path is distinguishable from old-age death by `c.age < c.lifespan` (caller of post-mortem stats can flag this).

### 3.6 Forage targeting

When entering FORAGE:

1. Scan tiles in `forage_radius_tiles` Chebyshev around current position.
2. Pick the tile with `food >= min_forage_food` minimizing Chebyshev distance (ties broken by `food` descending).
3. Walk toward it via existing slide-along-walkable wander step. No pathfinding (per the no-pathfinding decision in `Densitas_citizens.md`).
4. On arrival, transition to EATING.

If no eligible tile exists within radius, citizens fall back to wide-radius WANDER (effectively migration). They'll keep starving until they luck into food or die. **This is intentional**: regional famines feel real because the local citizens visibly drift outward seeking food.

---

## 4. Belief field refinement (DYING fade)

The current `BeliefField._scatter` excludes DYING citizens entirely, which makes deaths visible as instant 1.0 drops in the heatmap. For P1.5's "the god slowly loses belief" feel, DYING citizens contribute *fractional* belief:

```python
if c.state == CitizenState.DYING:
    frac = c.state_timer / max(cfg_dying_duration, 1e-6)
    field[c.faction, cy, cx] += amp * frac
else:
    field[c.faction, cy, cx] += amp
```

This is a tiny edit (5 lines), but visually it means the belief overlay smoothly contracts as a population dies off — load-bearing for the feel of decline. Bump `citizen.dying_duration` from 0.5s to 2.0s so the fade reads at human timescales.

Tests assert: a DYING citizen at half its dying_duration contributes ~0.5 amplitude.

---

## 5. Render extension

### 5.1 Food overlay (toggle key `F`)

Mirrors the belief overlay (P2):

- Build a `(world_h, world_w, 4)` RGBA grid at recompute time, cell colour = green tint scaled by `food / max_cap`, alpha by magnitude.
- Cache by `world.food_version`.
- Scale to world pixel resolution, blit viewport-style.
- Order: world surface → food overlay (if on) → belief overlay (if on) → citizens.

The food overlay is at world-tile resolution (256×192) not 4-tile sampling — food is per-tile native, so we get a richer image. Memory: 256·192·4 = 200 KB; world-scaled copy is the same ~50 MB as belief.

### 5.2 No new sprites

Citizens in FORAGE state use the WANDER walk animation. EATING uses the IDLE frame. We can add a "munching" detail at P2 polish; for P1.5 the only feedback needed is the state itself + the moving population.

---

## 6. HUD extension

Add to the bottom-left card, below BELIEF:

```
FED   85%       HUNGRY 12%      STARVING 3%
[============================  ]   <- bar visualization
```

Where:
- FED     = % of pop with `hunger < repro_hunger_threshold`
- HUNGRY  = % between repro_hunger_threshold and starve_hunger
- STARVING= % above starve_hunger

The bar visualises population health and is at a glance the most informative new readout — when it turns red, the player knows the next die-off is coming.

---

## 7. Config schema `[food]`

```toml
[food]
hunger_rate             = 0.005   # 1/sim_sec — 200s from full to starving
forage_threshold        = 0.40    # hunger above this -> FORAGE
repro_hunger_threshold  = 0.30    # both partners must be below this to mate
starve_hunger           = 1.00    # hunger >= this -> DYING (starvation)
eat_amount              = 0.20    # hunger reduction per EATING tick
eat_duration            = 1.00    # sim sec spent in EATING per visit
bite_size               = 0.20    # tile food consumed per EATING tick
calorie_per_food        = 1.00    # multiplier: 1 unit of food reduces hunger by this
forage_radius_tiles     = 8       # Chebyshev search radius for nearest food
min_forage_food         = 0.5     # ignore tiles with less food than this
overlay_alpha_max       = 160     # 0..255 — peak alpha on the heatmap

[food.biome]
# initial = cap; regen is per sim sec
forest_initial    = 8.0
forest_regen      = 0.10
grass_initial     = 5.0
grass_regen       = 0.08
beach_initial     = 3.0
beach_regen       = 0.05
hill_initial      = 2.0
hill_regen        = 0.03
holy_initial      = 1.0
holy_regen        = 0.02
# unused tiles (mountain, water, lava, blighted) implicitly 0 / 0
```

---

## 8. Equilibrium target

The carrying capacity of a default map is roughly:

```
carrying_capacity ≈ Σ (regen[tile] for tile in world) / consumption_per_citizen
```

With first-pass numbers, ~60% of the default 256×192 = 49,152 tiles are food-bearing. Average regen ≈ 0.07/s × 29,500 tiles ≈ 2,065 food units/s globally. Consumption per citizen ≈ `hunger_rate / calorie_per_food` × continuous-eating-equivalent ≈ ~1.0 food/s.

So the equilibrium target is **≈ 2,000 citizens** on a default world — *two orders of magnitude lower than the 130k blowup*. The 8 founders should grow exponentially through T0–T3 in roughly the same timing as today (~5–10 sim minutes to T4), then plateau as food becomes the bottleneck.

The §9 playtest pass tunes to hit this curve cleanly.

---

## 9. Tuning playtest

Headless sim run, 1200 sim sec (20 sim minutes), default seed. Capture:

- Population vs sim_t (every 10s)
- % fed / hungry / starving (every 10s)
- Tier reached at each 100s mark
- Final population

Acceptance:
- Population stays under 4,000 at all times (twice the target as safety margin)
- Population stays above 200 after the first 600s (no extinction)
- T1 reached before sim_t 60s; T3 reached before sim_t 600s
- Average hunger stays under 0.6 at equilibrium

If the run fails any criterion, retune and re-run. Numbers go in the WORKLOG.

---

## 10. Where the food field lives

Two reasonable locations:

- **(a)** Inside `World`. `world.food` is a sibling of `world.tiles`. Regen happens via a `world.tick_food(dt)` method.
- **(b)** Separate `FoodField` class in `densitas/food.py`, parallel to `BeliefField`. Constructor takes a world; owns its own arrays and version counter.

I'm going with **(b)** because:
1. The food *field* is genuinely separate concern from the *world* terrain — terrain is static, food is dynamic state.
2. `FoodField` parallels `BeliefField` syntactically: `recompute(dt)`, `query(tx, ty)`, `peak()`, `grid()`, `version`. The renderer can treat them with the same shape.
3. Tests for food don't need to drag a `World` around — they can spin up a `FoodField` over a stub.

`World` stays read-only after generation. `FoodField` owns the live food state.

---

## 11. Contract with the rest of the codebase

| Caller         | Method                                  | When                          |
|----------------|------------------------------------------|-------------------------------|
| `main.py`      | `FoodField(cfg.food, world)`             | once at world load            |
| `main.py`      | `food.recompute(tick_dt)`                | every citizen tick (5 Hz)     |
| `citizen.py`   | `food.consume(tx, ty, amount) -> float`  | when in EATING, per tick      |
| `citizen.py`   | `food.find_nearest(tx, ty, radius, min)` | entering FORAGE               |
| `render.py`    | `food.grid()`, `food.version`             | overlay rebuild               |
| `hud.py`       | `manager.hunger_stats() -> (fed, hungry, starving)` | per render frame |

`food.consume` returns the amount actually consumed (clamped if the tile was nearly empty). `food.find_nearest` returns `(tx, ty)` or `None`.

---

## 12. Deliberately omitted (P1.5)

- **Inventory.** `food_carried: int` exists on the dataclass but is never set. P3+.
- **Granaries / food storage structures.** P3 (relic-tier feature).
- **Fishing on WATER tiles.** Requires a structure entity. P3.
- **Predator/prey, wolves, raids.** Out of scope for this game.
- **Famine events as scripture-log lines.** Tone work; defer until P3 wires the log up.
- **Save/load.** P6 — but `FoodField` is a numpy array, trivially serializable.

---

## 13. Open questions to retire during implementation

- Should EATING be interruptible by other hungry citizens stacking on the tile (food gets split)? *First pass:* no — citizens eat in turn, each takes their bite_size; the tile depletes naturally.
- Should FORAGE target selection use line-of-sight or just radius? *First pass:* radius only. LOS is fog-of-war's problem (P2.5).
- Should the food overlay show in `dominant_faction`-style coloured tints to indicate "this is my faction's larder"? *No* — food is universal, not faction-claimed. Cyan-vs-red is for belief; green is for food. (Cult mechanics could change this in P4.)
