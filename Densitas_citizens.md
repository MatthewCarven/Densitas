# Densitas — Citizen Specification

*v0.1 — P1 design pass, 2026-05-20*

Citizens are the carriers of belief. They are not units; the player never
selects, orders, or directly addresses one. They are the **field** out of
which divine power is computed. This spec defines what a citizen *is*,
what states it can occupy, and what makes it transition between them.

The scope of this document is **P1 only**. Belief field, fog of war, food
entities, religious relics, and rival-god conversion are deliberately
out-of-scope here; each gets its own spec when its milestone lands.

---

## 1. Pillars (load-bearing)

1. **Citizens are never directly selected.** No click-to-order verb.
2. **Citizens are autonomous.** They wander, age, pair off, and die on
   their own clocks. The player influences them through Whispers (T0)
   and Religious Relics — *never* by puppeting one.
3. **Citizens are cheap.** A late-game world holds thousands. Each
   citizen costs a handful of bytes plus one sprite blit. No per-citizen
   pathfinding, no per-citizen behavior tree — just a small state
   machine driven by need + nearest-neighbour math.
4. **5 Hz logic / 60 Hz render.** Citizens think 5× per second; sprites
   interpolate. P1 may render-on-tick (no interpolation) if simpler;
   interpolation is a polish task.

---

## 2. Data model

```python
@dataclass
class Citizen:
    id:        int        # stable across ticks; never reused after death
    faction:   int        # 0 = player (Open Eye), 1 = rival (Maw), …
    x:         float      # tile coordinates; sub-tile for smooth motion
    y:         float
    state:     CitizenState
    age:       float      # in sim seconds (1 sim sec = 1 wall sec at 5 Hz)
    lifespan:  float      # sim seconds at which DEAD transition fires
    repro_cd:  float      # sim seconds remaining before next MATE eligible
    facing:    Facing     # N/S/E/W — sprite direction
    home_x:    float      # wander anchor (set at spawn, may drift later)
    home_y:    float
    target_x:  float      # current wander target
    target_y:  float
```

All fields fit comfortably; a 10k-citizen world is ~640 KB. We may move
to a structure-of-arrays layout later if profiling demands it — keep
it simple now.

---

## 3. States and transitions

```
              ┌─────────┐
              │  IDLE   │◄────────────┐
              └────┬────┘             │
            pick wander target        │ arrive at target
                  │                   │
              ┌───▼─────┐             │
              │ WANDER  │─────────────┘
              └────┬────┘
                   │  age ≥ maturity AND
                   │  another mature adult of same faction within repro_radius AND
                   │  both have repro_cd == 0
              ┌────▼─────┐
              │  MATE    │   (0.5 sim sec — spawns child, sets cooldowns)
              └────┬─────┘
                   │ done
                   ▼
                 IDLE

        any state ── age ≥ lifespan ──► DYING (0.5s) ─► (removed)
```

**P1 states (implemented):** IDLE, WANDER, MATE, DYING.
**P1.5+ states (placeholders only):** FORAGE, EATING, SLEEP, FLEE,
CONVERTED. Add to the enum so save-files don't break later; the
dispatch table is empty for them in P1.

**Transition rules:**

| From    | To      | Trigger |
|---------|---------|---------|
| IDLE    | WANDER  | every tick, with prob `1 - exp(-tick_dt / wander_period)` |
| WANDER  | IDLE    | reached `(target_x, target_y)` within 0.5 tile |
| IDLE    | MATE    | mate eligibility (see §5) |
| any     | DYING   | `age >= lifespan` |
| DYING   | removed | after `dying_duration` sim seconds |

---

## 4. Spawning

* **Initial spawn (world load):** `cfg.citizen.initial_population`
  citizens (default 5) placed at uniformly-random walkable tiles within
  a `cfg.citizen.spawn_radius_tiles` of map center (default 20).
* **Walkable** in P1 = `Tile.GRASS | FOREST | BEACH`. Not HILL (slope),
  not WATER, not MOUNTAIN.
* All initial citizens are faction 0 (player) for now. Rival faction
  spawn is P4 (rival-god AI). The data model supports it.
* `home_x/y` is set to the spawn tile; this is the wander anchor.

**Determinism:** spawn is RNG-seeded from `cfg.world.seed XOR
cfg.citizen.spawn_seed` (default 0). Same seed → same positions.

---

## 5. Reproduction (§5 — load-bearing)

Reproduction is the only way the population grows. P1 has no food
constraint and no migration; growth is purely demographic.

**Eligibility test for citizen A:**

1. `A.age >= cfg.citizen.maturity_age` (default 8 sim sec)
2. `A.repro_cd == 0`
3. There exists another citizen B with:
   - `B.faction == A.faction`
   - `B.id != A.id`
   - `B.age >= maturity_age`
   - `B.repro_cd == 0`
   - `chebyshev_distance(A, B) <= cfg.citizen.repro_radius` (default 2)

If both A and B are eligible, both enter MATE. After `mate_duration`
(default 0.5 sim sec):

* A new citizen C spawns at a random walkable tile within
  `repro_radius` of A.
* C inherits A.faction, age 0, fresh lifespan rolled from
  `lifespan_mean ± lifespan_jitter`.
* A.repro_cd = B.repro_cd = `cfg.citizen.repro_cooldown` (default 6 sim sec)

**Why these defaults.** At 5 Hz, maturity 8s means new citizens become
breeders after ~40 ticks. With cooldown 6s, a stable pair produces ~1
child per ~6.5 sim seconds. Two paired citizens with no death produce
6 children in their first minute of joint adult life. With lifespan
~60 sim sec, this gives a modest exponential ramp — enough to feel
alive in playtest without saturating the heatmap before P2 is done.

These are starting numbers. All tunable in `config.toml`.

---

## 6. Death

* When `age >= lifespan`, transition to DYING.
* After `dying_duration` (default 0.5 sim sec), remove from the
  population. Sprite shows a "fading" frame during DYING (P1.5
  polish; P1 may just hold the idle frame).
* No body, no resource drop. Death is silent in P1; the rhetoric
  log is P3.

**Lifespan distribution:** Gaussian-truncated, `lifespan_mean`
(default 90 sim sec) ± `lifespan_jitter` (default 30, truncated at
mean ± 2·jitter so nothing is negative).

---

## 7. Movement

* In WANDER, move toward `(target_x, target_y)` at
  `cfg.citizen.wander_speed` tiles/sim-sec (default 1.0). At 5 Hz, that
  is 0.2 tiles per tick.
* Targets are picked within `cfg.citizen.wander_radius` (default 6
  tiles) of `home_x/home_y`. If the picked target lands on a
  non-walkable tile, repick (up to 8 attempts; if no luck, stay home).
* Movement is 8-connected free movement on the tile grid — no
  pathfinding. If the straight-line step crosses a non-walkable tile,
  *project* it: move only on the walkable axis, or stay put for that
  tick. Good enough for P1; revisit if behaviour looks dumb in playtest.

---

## 8. Sprite

* **16 tall, 8 wide** pixel humanoid. Need not be square; the render
  blits citizen sprites *on top of* the world surface every frame,
  centred horizontally on the tile and aligned to the bottom of the
  tile (`tile_y * 16 + 16 - 16` for the top of the sprite ⇒ flush
  bottom).
* **4 facings** × **2 walk frames** + **1 idle frame** = 9 frames per
  faction. P1 may ship with just 1 idle + 1 walk per facing (5 frames)
  and add the second walk frame as polish.
* **Faction tint:** player (Open Eye) — parchment + cyan; rival (Maw)
  — bone + blood. Tints come from the lore pantheon palette.
* **Animation rate:** alternate walk frames every 0.25 sim sec (~50 ms
  at 5 Hz = 2 ticks; tighter on render). Citizens in IDLE/MATE/DYING
  show the idle frame.

**Implementation hook:** the renderer exposes a
`blit_citizens(screen, world_surface, citizens, cam_x, cam_y)` method;
PixelRenderer paints the 9 frames at construction time and looks them
up by `(faction, facing, frame)`.

---

## 9. HUD wiring

The HUD lives in `densitas/hud.py`. It is rendered *after* the world
viewport and *after* the F3 debug overlay, so it is always on top.

**P1 HUD elements (top of screen, left aligned):**

* **Population**: total count of faction-0 citizens currently alive.
* **Tier banner**: current divine tier based on population, computed
  by:

  ```
  T0 Whisper     pop ≥ 1
  T1 Blessing    pop ≥ 10
  T2 Tempest     pop ≥ 100
  T3 Cataclysm   pop ≥ 1000
  T4 Apocalypse  pop ≥ 5000     # +holy-site requirement in P5
  ```

  Tier crosses are silent in P1; the "scripture log line on tier-up"
  is P3 work.

The HUD does **not** show rival population, individual citizen state,
or any tile-level data. Those belong to the debug overlay (F3) or
later milestones.

---

## 10. Config schema additions

```toml
[citizen]
initial_population   = 5      # number spawned at world load
spawn_radius_tiles   = 20     # spawn within this Chebyshev distance of map center
spawn_seed           = 0      # XOR'd with world.seed; bump to reshuffle initial positions
maturity_age         = 8.0    # sim seconds before able to reproduce
lifespan_mean        = 90.0   # sim seconds
lifespan_jitter      = 30.0   # ± this around the mean, truncated
repro_radius         = 2      # Chebyshev distance to find a mate
repro_cooldown       = 6.0    # sim seconds after MATE before eligible again
mate_duration        = 0.5    # MATE state duration
wander_period        = 2.0    # mean sim seconds between picking new wander target
wander_radius        = 6      # tiles around home_x/y for picking targets
wander_speed         = 1.0    # tiles per sim second
dying_duration       = 0.5    # DYING state duration before removal
tick_hz              = 5      # simulation ticks per second
```

---

## 11. What this spec deliberately omits

* **Belief field.** P2. Citizens emit faith aura, that aura is
  accumulated into a 2D density grid. *Until P2 lands, total
  population is the only belief signal, and only at tier-unlock
  granularity.*
* **Food / hunger / forage.** P1.5 at earliest. Without food, growth
  is unconstrained by environment; we'll see whether that's actually a
  problem in playtest before we add resource pressure.
* **Religious Relics.** P3. Relics will modify wander anchors
  (citizens drift toward them) and contribute to the belief field.
* **Rival faction.** P4. The data model supports it; the AI doesn't
  yet.
* **Conversion.** P4. CONVERTED is a placeholder state in the enum.
* **Pathfinding.** Never, hopefully. Project-onto-walkable should
  suffice for a wandering simulation. If P3 relic-pull behaviour
  reveals problems, revisit then.

---

## 12. Contract with the rest of the codebase

* `densitas/citizen.py` exports `Citizen`, `CitizenManager`,
  `CitizenConfig`, `Facing`, `CitizenState`.
* `CitizenManager.tick(dt_sim: float, world: World) -> None` advances
  the simulation by `dt_sim` sim seconds. Called once per 5 Hz tick
  from `main.py`.
* `CitizenManager.population(faction: int = 0) -> int` for HUD.
* `Renderer.blit_citizens(screen, citizens, cam_x, cam_y) -> None`
  paints citizens (P1: PixelRenderer only; VectorRenderer remains TODO).
* `HUD.draw(screen, manager, cfg) -> None` paints the population +
  tier banner.

Nothing in `world.py` or `camera.py` changes. The world is still a
read-only substrate; citizens are layered above it.
