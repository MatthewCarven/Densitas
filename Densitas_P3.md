# Densitas — P3: Powers T0–T1 + Relics

*v0.1 — 2026-05-21. Implementation spec for the player-verb layer.*

This is the milestone where the player *plays*. P0–P2 + P1.5 built the
simulation that exists without the god. P3 adds the god's hands: the
belief pool, the cast queue, two tiers of powers, and the religious relics
that are the game's central strategic verb.

The simulation primitives are all in place:

  * `belief.query(tx, ty, faction)` returns local density for strength scaling.
  * `belief.total(faction)`         drives the pool regen rate.
  * `belief.version`                lets the renderer cache.
  * `food.consume(tx, ty, amount)`  is what Bless/Curse will modulate.
  * `food.cap` / `food.regen`       are vectors we can mutate when terrain shifts.
  * `world.tiles` + `heightmap`     are the targets of Raise/Lower.
  * `Citizen.target_x / target_y`   is what Inspire pre-empts.

P3 is mechanically the bridge from "watch the curve" to "shape the curve."

---

## §1 Pillars

1. **Belief is the only currency.** All powers debit a single pool. The
   pool refills from population — no other source, no time decay, no gift
   from the heavens. Lose your citizens, lose your hands.
2. **Density is the multiplier, not the gate.** Tier (population threshold)
   gates *which* powers exist. Local belief at the target tile scales *how
   hard* each cast lands. A T1 Bless cast in a dead zone is a Bless in name
   only.
3. **Relics are the strategy; powers are the tactics.** Relics persist for
   minutes and pin intent to the map. Powers fire once and resolve. The
   choice of *where* a relic sits decides games; the choice of *when* to
   curse a rival field decides skirmishes.
4. **Citizens are never targeted.** Every power targets a tile or an AoE.
   Citizens get caught in effects; they are never picked.
5. **The propaganda is always present.** Every cast emits exactly one
   scripture-log line picked from `(power, god, voice_mode)`. The voice
   never apologises, never winks. See GDD §10 and the rhetoric block in
   `Densitas_Powers.md` §"Rhetoric pool".

---

## §2 Belief pool vs belief field

These are two different things and conflating them is the easiest mistake
to make. We keep them syntactically distinct from day one.

### §2.1 Belief field (P2, already shipped)

`densitas/belief.py :: BeliefField`. A `(n_factions, grid_h, grid_w)`
float32 grid. Recomputed every citizen tick from citizen positions
(scatter + 2-pass box blur, volume-preserving so `total ≈ population`
mod the DYING fade). **Read-only with respect to the player.** It's the
state of the world's faith, snapshot.

### §2.2 Belief pool (P3, new)

A single float per faction. Lives on `PowerSystem.pool[faction]`. Grows
each tick from the *field*; spent each cast. Cannot go negative; a cast
that asks for more than the pool holds fails validation.

Regen formula for P3 (kept simple):

```
pool[f] += population(f) * cfg.belief_regen_per_citizen * dt
```

With `belief_regen_per_citizen = 0.02 / sim_sec` (from the Powers Spec
hint: `belief_per_sec ≈ population × 0.02 × (1 + density_bonus)`). We
defer the density bonus — leave the hook obvious in the code as a
`# TODO(P3.5): density bonus from peak/avg ratio.`

The pool is **uncapped** for P3. If you sit on a high population without
spending you accrue indefinitely — that's a feature, not a bug, and gives
the player the option to bank a T2 strike. We can add a soft cap at
`5000 + 10 × population` if playtest shows it matters.

### §2.3 Why two things, not one

If powers debited the field, casting would *delete citizens visually* in
the heatmap, which makes no sense — the citizens didn't die, the god just
spent attention. The pool is the god's reservoir; the field is the
testimony that fills it.

---

## §3 Power system architecture

`densitas/powers.py` is the new home for everything except relics
(`densitas/relics.py`).

```
PowerKind        (IntEnum: INSPIRE, CALM, HUNGER_PANG, RAISE, LOWER,
                  BLESS, CURSE)
PowerSpec        (frozen dataclass: tier, belief_cost, cooldown, aoe_radius,
                  duration, requires_target_kind)
POWERS           (dict[PowerKind, PowerSpec])
ActiveEffect     (dataclass: kind, tx, ty, radius, multiplier, timer,
                  caster_faction)
ScriptureEntry   (dataclass: sim_t, line, power, faction)
PowerSystem      (the manager — one per game, holds pool, cooldowns,
                  effects, scripture log)
```

### §3.1 Lifecycle per tick

```python
def tick(self, dt, citizens, food, belief, sim_t):
    # 1. Regen pool from population.
    for f in range(N_FACTIONS):
        pop = citizens.population(f)
        self.pool[f] += pop * self.cfg.belief_regen_per_citizen * dt
    # 2. Bleed cooldowns.
    for k in list(self.cooldowns):
        self.cooldowns[k] -= dt
        if self.cooldowns[k] <= 0.0: del self.cooldowns[k]
    # 3. Tick active effects; expire when timer hits 0.
    for e in self.effects:
        e.timer -= dt
    self.effects = [e for e in self.effects if e.timer > 0.0]
    # 4. Fade scripture log entries older than rhetoric_fade_seconds.
    cutoff = sim_t - self.cfg.rhetoric_fade_seconds
    self.scripture_log = [s for s in self.scripture_log if s.sim_t >= cutoff]
```

### §3.2 Validation — `can_cast(kind, faction, tx, ty)`

Returns `(ok: bool, reason: str)`. Reasons surface in the HUD when the
player tries to cast and fails.

```
ok = (
    tier_for(citizens.population(faction))[1] >= spec.tier
    and self.pool[faction] >= spec.belief_cost
    and self.cooldowns.get(kind, 0.0) <= 0.0
    and world.in_bounds(tx, ty)
    and _tile_valid_for(kind, world.tiles[ty, tx])
)
```

`_tile_valid_for` knows that RAISE can't lift a MOUNTAIN further, LOWER
can't drop WATER, BLESS only lands on tiles with non-zero food capacity,
etc. Reasons for failure are returned as plain strings: `"need T1"`,
`"cooling 2.3s"`, `"need 5 belief"`, `"can't raise mountain"`.

### §3.3 Cast — `cast(kind, faction, tx, ty, world, citizens, food, belief, sim_t)`

```python
ok, reason = self.can_cast(...)
if not ok:
    self._log_failure(kind, reason, sim_t)   # short red flash in HUD
    return False
spec = POWERS[kind]
self.pool[faction] -= spec.belief_cost
self.cooldowns[kind] = spec.cooldown

# Strength scaling: local_belief / k_tier
local_b = belief.query(tx, ty, faction)
strength = max(0.0, local_b) / max(1e-3, self.cfg.k_tier[spec.tier])

# Dispatch on kind.
self._dispatch[kind](self, tx, ty, strength, faction,
                     world, citizens, food, belief, sim_t)

# Always log scripture.
self._scripture(kind, faction, tx, ty, sim_t)
return True
```

The `_dispatch` dict-of-callables shape (rather than a giant if/elif
ladder) keeps adding a power to a single registration line — important
for P5 when there are 16 of them.

### §3.4 Failed casts

Per Powers Spec: "Failed cast → 50% refund, full cooldown applied." For
P3 (T0/T1 only), all costs are small enough that the refund math is
noise. We implement: **no charge on validation failure, full charge +
cooldown on dispatch failure** (e.g. Inspire finds no citizen in range —
that's a dispatch failure, charges as a missed cast). The Powers Spec
50%-refund rule kicks in at T2+ casts.

---

## §4 T0 — Whisper (≥1 citizen)

| Power      | Cost | Cooldown | AoE | Tile kind     | Notes                                  |
|------------|------|----------|-----|---------------|----------------------------------------|
| INSPIRE    | 0    | 1.5 s    | 0   | any walkable  | Picks nearest IDLE/WANDER same-faction citizen within R=4. Overrides `target_x/y` toward (tx, ty). State → WANDER. Bias lasts until citizen arrives or 10 sim sec, whichever first. |
| CALM       | 0    | 1.5 s    | 2   | any           | Suppresses FLEE in radius. **Stub for P3:** FLEE state doesn't exist yet, so this is a registered no-op that still emits a scripture line. Wired so it lights up the day P4 introduces panic. |
| HUNGER_PANG| 1    | 3.0 s    | 0   | any walkable  | Sets nearest rival-faction citizen to FORAGE state. **Stub:** no rivals until P4; cast on faction 0 only re-targets a single citizen of any non-caster faction if one exists, else fails dispatch (charges). |

Inspire is the only T0 with real teeth in P3. It's also the cheapest way
to test the dispatch pipeline end-to-end.

---

## §5 T1 — Blessing (≥10 citizens)

| Power | Cost | Cooldown | AoE | Tile kind          | Effect                                                                                                                  |
|-------|------|----------|-----|--------------------|-------------------------------------------------------------------------------------------------------------------------|
| RAISE | 5    | 2.0 s    | 0   | not MOUNTAIN/LAVA  | Tile climbs one rank in the height ladder. Heightmap += ladder_step. `FoodField.cap/regen` recomputed from new tile.    |
| LOWER | 5    | 2.0 s    | 0   | not WATER          | Tile drops one rank. If the new tile is WATER, any citizen at that tile transitions to DYING (drown rule).              |
| BLESS | 10   | 4.0 s    | 4   | any food-bearing   | `ActiveEffect(kind=BLESS, multiplier=2.0, timer=30.0)`. While alive, `food.regen` in radius is doubled.                 |
| CURSE | 10   | 4.0 s    | 4   | any food-bearing   | `ActiveEffect(kind=CURSE, multiplier=0.2, timer=30.0)`. 80% reduction. Optional citizen flight is a P3.5 follow-up.    |

**Spring is deferred.** It introduces a new mechanic (a fresh-water tile
type that increases adjacent carrying capacity) that's a worthwhile
mini-spec on its own. Park to P3.5 alongside the density bonus.

### §5.1 Height ladder

```
WATER (0) -> BEACH (1) -> GRASS (2) -> FOREST (3) -> HILL (4) -> MOUNTAIN (5)
```

LAVA, BLIGHTED, HOLY are off-ladder. Lava cannot be raised or lowered.
Blighted upgrades to GRASS on raise (slow reclamation). Holy is sacred —
cannot be moved by terrain powers; only T4 disasters touch it.

Heightmap step per rank: 0.18 (so a single Raise visibly nudges the
shading; six raises moves a tile across the full elevation band).

### §5.2 World surface re-render

`Renderer` gains:

```python
@abstractmethod
def repaint_tile(self, world_surface: pygame.Surface, world: World,
                 tx: int, ty: int) -> None: ...
```

`PixelRenderer.repaint_tile` picks the same variant the original
`build_world_surface` would have (deterministic hash on `(tx, ty, tile)`)
and blits over the affected pixel rect. This avoids rebuilding the
whole world surface on every cast.

### §5.3 Drown rule

When a tile mutates and the new tile is not walkable:

```python
for c in citizens.citizens:
    if int(c.x) == tx and int(c.y) == ty and c.state != CitizenState.DYING:
        c.state = CitizenState.DYING
        c.state_timer = cfg.citizen.dying_duration
```

The 2.0s DYING fade-out keeps the visual smooth — same fade the belief
field uses.

### §5.4 Bless/Curse food regen folding

`FoodField.recompute(dt, effects=None)` gets an optional `effects` param:

```python
def recompute(self, dt, effects=None):
    if dt <= 0.0: return
    regen = self.regen
    if effects:
        regen = self._build_effective_regen(effects)
    np.add(self.food, regen * dt, out=self.food)
    np.minimum(self.food, self.cap, out=self.food)
    self.version += 1
```

`_build_effective_regen` allocates a temp array (cached, reused) and
applies the multiplier inside each effect's tile circle. The radius is
small (4 tiles), so this is cheap. The temp survives across calls and
is recomputed only when the active-effect set changes.

---

## §6 Religious Relics

The strategic verb. `densitas/relics.py`.

```
RelicState     (IntEnum: AVAILABLE, PLACED, SHATTERED)
Relic          (dataclass: id, faction, tx, ty, placed_at, state,
                threat_timer, name)
RelicManager   (owns the per-faction relic list; provides place/move/
                retrieve/tick/scatter_into_belief)
```

### §6.1 Per-faction inventory

3 relics per god at game start. T3 unlocks a 4th, T4 a 5th. (T3/T4
unlocks come with P5.)

Names from `Densitas_Powers.md`:
* Faction 0 (Open Eye): *The First Witness*, *The Second Witness*, *The Third Witness*.
* Faction 1 (Maw):      *First Bite*,        *Second Bite*,        *Third Bite*.

### §6.2 State machine

```
AVAILABLE  --place(tx, ty)-->  PLACED  --move(tx', ty')-->  PLACED (cooldown resets)
                                  |
                                  +--retrieve()-->  AVAILABLE
                                  |
                                  +--shatter()-->   SHATTERED  (terminal)
```

* Placement cost: 0 belief, 0 cooldown. The cost is opportunity.
* Move within 30 sec of last placement: allowed (no special rule for self-move). Just resets the move-cooldown timer.
* Retrieve: instant, no belief refund (the relic stays in your tray; nothing wasted).
* Shatter: permanent. Slot is gone for the rest of the game. (Brutal by design.)

### §6.3 Belief contribution

Each tick, after `BeliefField._scatter(citizens)`:

```python
def _scatter_relics(self, relics, sim_t):
    amp = self.cfg.relic_amplitude    # e.g. 20.0 — "as if 20 citizens"
    cd = self.cfg.relic_place_cooldown  # 30 s
    for r in relics:
        if r.state != RelicState.PLACED: continue
        elapsed = sim_t - r.placed_at
        if elapsed < cd:
            # Fade in: linear from 0 -> amp over the cooldown window.
            weight = amp * (elapsed / cd)
        else:
            weight = amp
        cx, cy = r.tx // tpcx, r.ty // tpcy
        if 0 <= cx < gw and 0 <= cy < gh:
            self.field[r.faction, cy, cx] += weight
```

`BeliefField.recompute(citizens, relics=None, sim_t=0.0)` grows the
signature. Relics-as-citizens means powers' strength scaling Just Works
near a relic — Bless on top of a relic is a stronger Bless.

### §6.4 Citizen attraction

Soft pull. `CitizenManager` gains an attractor list:

```python
def add_attractor(self, tx, ty, radius, faction): ...
def remove_attractor(self, tx, ty): ...   # by tile, idempotent
```

In `_pick_wander_target`, before the random pick, with probability
`p_attract = 0.4`, if any attractor of the citizen's faction is within
`R + radius` (where R is the relic radius), return a tile uniformly
sampled within `radius` of the attractor.

Hunger trumps devotion: a hungry citizen in FORAGE state ignores
attractors — they go after food. Relics make the steady-state
*equilibrium* more clustered; they don't override survival.

### §6.5 Shatter rule

```python
shatter_ratio = 1.5         # rival belief must exceed this fraction of player's
shatter_time  = 8.0  # sim_s — sustained margin required

for r in relics:
    if r.state != RelicState.PLACED: continue
    p = belief.query(r.tx, r.ty, faction=r.faction)
    rivals = max(belief.query(r.tx, r.ty, f) for f in range(N) if f != r.faction)
    if rivals > shatter_ratio * max(p, 1e-3):
        r.threat_timer += dt
    else:
        r.threat_timer = max(0.0, r.threat_timer - 2.0 * dt)
    if r.threat_timer >= shatter_time:
        r.state = RelicState.SHATTERED
        emit_scripture("relic_shattered", r.faction, r.tx, r.ty)
        # Future: emit a relic-shatter summary screen (TODO in main spec).
```

The 2.0× recovery rate means a brief incursion doesn't doom a relic — it
needs sustained pressure. The ratio and time are tunable; values above
are the P3 starting point.

**Until P4 lands rival citizens, no relic shatters in normal play.** The
test suite exercises the shatter codepath by direct field manipulation
(write to `belief.field[1, cy, cx]`); the live game won't trigger it
without rival input.

### §6.6 Disaster destruction (deferred)

Powers Spec: "A Comet on a relic is a real possibility." Implement at
P5 when Comet lands. The hook is: `RelicManager.shatter_at(tx, ty,
radius)` — call from any disaster effect.

---

## §7 Active effects (Bless / Curse)

Lightweight per-effect dataclass; small list scanned each tick. P3 only
introduces two effect kinds; P5 will add more.

```python
@dataclass
class ActiveEffect:
    kind: int             # PowerKind value
    tx: int
    ty: int
    radius: int
    multiplier: float
    timer: float          # sim_s remaining
    caster_faction: int
```

Lookup is O(N * tiles_in_radius) per tick — fine while we have <10
concurrent effects. If it grows, build a spatial index.

---

## §8 Terrain mutation pipeline

When RAISE/LOWER fires:

```python
def mutate_tile(world, food, renderer, world_surface, tx, ty, new_tile):
    old = int(world.tiles[ty, tx])
    if old == new_tile: return False
    world.tiles[ty, tx] = new_tile
    world.heightmap[ty, tx] = _heightmap_for(new_tile)
    food.cap[ty, tx]   = _biome_cap_for(new_tile)
    food.regen[ty, tx] = _biome_regen_for(new_tile)
    food.food[ty, tx]  = min(food.food[ty, tx], food.cap[ty, tx])
    food.version += 1
    renderer.repaint_tile(world_surface, world, tx, ty)
    return True
```

Drown rule (§5.3) runs *after* mutation.

This function lives in `densitas/world.py` (since it's "world mutation")
or `densitas/powers.py` (since powers are the callers). Putting it in
`world.py` keeps `powers.py` from importing `Renderer` directly — better
separation. `powers.py` takes a callable `mutate: Callable[[int, int, int], bool]`
in its constructor; `main.py` wires the real one up.

---

## §9 Rhetoric module

`densitas/rhetoric.py` + `rhetoric.json`.

```json
{
  "inspire": {
    "open_eye": {
      "consecration": [
        "A hand turns the wanderer toward the dawn.",
        "The eye looked upon them; they walked.",
        "The path is named. The faithful step."
      ],
      "doctrinal": [
        "No step is unobserved. No step is unled."
      ],
      "ritual": [
        "The priests light the lantern at the threshold."
      ]
    }
  },
  "bless": { "open_eye": { ... } },
  "raise": { "open_eye": { ... } },
  ...
}
```

`pick(power, god, sim_t) -> str` rotates voice modes weighted 70% /
20% / 10% (consecration / doctrinal / ritual). Selection inside a mode
is random with no-immediate-repeat.

P3 ships 3–5 lines per (power, god, mode) for the Open Eye only.
Faction-1 (Maw) lines come with P4 rival AI.

---

## §10 Input + HUD

### §10.1 Input bindings

| Key            | Mode                      |
|----------------|---------------------------|
| `1`            | Inspire (T0)              |
| `2`            | Calm (T0)                 |
| `3`            | Hunger Pang (T0)          |
| `4`            | Raise (T1)                |
| `5`            | Lower (T1)                |
| `6`            | Bless (T1)                |
| `7`            | Curse (T1)                |
| `R`            | Relic place (cycles available slots) |
| `Shift+R`      | Relic retrieve            |
| `Left-click`   | Execute current mode at mouse tile   |
| `Right-click`  | Cancel mode               |
| `ESC`          | Cancel mode (then quit)   |
| `B`            | Belief overlay (kept)     |
| `F`            | Food overlay (kept)       |
| `F3`           | Debug overlay (kept)      |

### §10.2 Cast preview

When a power mode is selected and the cursor is over a world tile:

* AoE radius drawn as a soft circle on the world surface (alpha 80,
  tinted by power: green=bless, red=curse, gold=raise, brown=lower).
* Cost + cooldown chip near the cursor: `5b · 2.0s` (cost · cooldown).
* Tint based on `can_cast` status: white = ready, yellow = cooling,
  red = under-funded or tile-invalid. The string from `can_cast` shows
  in red below the chip.

`PixelRenderer.blit_cast_preview(screen, cast_mode, tx, ty, ok, reason,
cam_x, cam_y)` is the new render method.

### §10.3 HUD additions

In `densitas/hud.py`:

* **Belief pool bar** — replaces the current `BELIEF total` text. Shows
  pool / a soft-cap estimate (e.g. `pool / (5000 + 10×pop)`). Bar fills
  from left, parchment background, accent fill. Numeric tooltip on
  hover.
* **Cooldown row** — a horizontal strip of 7 small icons (one per power,
  greyed if tier-locked). Each shows a sweep ring while on cooldown.
* **Scripture log** — top-right corner, last 4 entries. Each entry fades
  from alpha 220 to 0 over 6 sim sec. Lines are short, italic.
* **Relic tray** — bottom-right corner, 3 slots:
  * Tray slot: relic glyph at 24×24, "AVAILABLE" label.
  * Placed slot: greyed glyph, "PLACED (12,34)" label.
  * Shattered slot: skull-X glyph, "SHATTERED" label.

PR1 ships the pool bar + cooldown row + scripture log. PR3 ships the
relic tray.

---

## §11 Config schema

```toml
[powers]
belief_regen_per_citizen = 0.02   # pool/sim_sec/citizen
k_tier                    = [0.5, 1.0, 4.0, 20.0, 80.0]   # strength scale by tier 0..4
rhetoric_fade_seconds     = 6.0
inspire_cooldown          = 1.5
calm_cooldown             = 1.5
hunger_pang_cooldown      = 3.0
raise_cooldown            = 2.0
lower_cooldown            = 2.0
bless_cooldown            = 4.0
curse_cooldown            = 4.0
bless_multiplier          = 2.0
curse_multiplier          = 0.2
effect_duration_t1        = 30.0
inspire_radius            = 4
hunger_pang_radius        = 0     # point target
bless_radius              = 4
curse_radius              = 4

[powers.relic]
amplitude          = 20.0
place_cooldown     = 30.0   # belief contribution fades in over this window
shatter_ratio      = 1.5
shatter_time       = 8.0
attract_radius     = 8
attract_probability = 0.4
initial_count      = 3
```

`PowerConfig` (frozen dataclass with `relic: RelicConfig`) parallels
`FoodConfig(biome=FoodBiomeConfig(...))`.

---

## §12 Tests (target: 25)

`tests/test_powers.py`:

1. PowerSystem initialises with empty pool, no cooldowns, no effects.
2. Pool regen scales with population: 100 citizens × 0.02 × 1.0 = 2.0 / sim_sec.
3. Cast on empty pool fails with `"need N belief"` and doesn't debit.
4. Cast below tier fails; population 5 cannot cast T1.
5. Successful Inspire moves nearest citizen's `target_x/y`.
6. Inspire dispatch failure when no citizen in radius — charges full cost.
7. Bless creates an `ActiveEffect` and food regen in radius is multiplied 2.0×.
8. Bless expires after 30 sim sec and regen reverts.
9. Bless + Curse on same tile: most-recent wins (overwrite rule, P3 simplification).
10. Cooldown blocks repeat cast within window.
11. Cooldown ticks down on `PowerSystem.tick`.
12. Raise on GRASS → FOREST: world.tiles, heightmap, food.cap, food.regen all update.
13. Raise on MOUNTAIN fails with `"can't raise mountain"`.
14. Lower on GRASS → BEACH → WATER over two casts.
15. Lower-into-water on tile with a citizen sets citizen to DYING.
16. Scripture log appends one entry per successful cast.
17. Scripture log expires entries past `rhetoric_fade_seconds`.
18. `can_cast` returns concrete reason strings.

`tests/test_relics.py`:

19. RelicManager initialises with 3 AVAILABLE relics per faction.
20. Place transitions AVAILABLE → PLACED and stamps `placed_at`.
21. Move resets `placed_at` to the new sim_t.
22. Retrieve transitions PLACED → AVAILABLE.
23. Belief scatter adds `amplitude` at the relic tile (post-cooldown).
24. Belief scatter fades in linearly during the place-cooldown window.
25. Shatter trigger: write rival belief above ratio for `shatter_time`
    seconds; relic enters SHATTERED state and stays there.
26. Shatter doesn't fire when ratio is met briefly then drops (recovery test).
27. Citizen attractor probability is honoured (statistical: 1000 trials,
    ~40% land near the attractor).
28. SHATTERED relic doesn't contribute to belief field.

---

## §13 PR slicing

### PR1 — PowerSystem foundation + T0 + Bless/Curse

* `densitas/powers.py` (new)
* `densitas/rhetoric.py` + `rhetoric.json` (new)
* `densitas/food.py` modified: `recompute(dt, effects=None)`
* `densitas/citizen.py` modified: `inspire_citizen(tx, ty, max_radius)` helper
* `densitas/hud.py` modified: belief pool bar, cooldown row, scripture log
* `densitas/render.py` modified: `blit_cast_preview` (new abstract + pixel impl)
* `densitas/main.py` modified: number-key bindings, mouse-to-tile mapping, PowerSystem instantiate + tick
* `densitas/config.py` + `config.toml`: `[powers]` block
* `tests/test_powers.py` (18 tests above)

Ships: Inspire, Calm-stub, Hunger-Pang-stub, Bless, Curse. The player can
herd citizens and modulate food regen. No terrain mutation yet, no relics.

### PR2 — Terrain mutation (Raise / Lower)

* `densitas/world.py`: `mutate_tile(...)` function
* `densitas/render.py`: `repaint_tile(world_surface, world, tx, ty)`
* `densitas/powers.py`: Raise/Lower dispatch + height-ladder tables
* `densitas/citizen.py`: drown rule on mutate
* `tests/test_powers.py`: tests 12–15 above
* HUD cooldown icons for the two new powers

Ships: the player can sculpt land. Food field follows terrain. Citizens
drown on lowered tiles.

### PR3 — Relics

* `densitas/relics.py` (new)
* `densitas/belief.py`: `recompute(citizens, relics=None, sim_t=0.0)` + `_scatter_relics`
* `densitas/citizen.py`: attractor list + `_pick_wander_target` integration
* `densitas/hud.py`: relic tray
* `densitas/render.py`: `blit_relics(screen, relics, cam_x, cam_y)` using the existing pixel glyphs from `Densitas_relic_glyphs_v1.html`
* `densitas/main.py`: `R` / `Shift+R` modes, click-to-place
* `tests/test_relics.py` (tests 19–28)

Ships: the central strategic verb is in the player's hands. With Bless
and Inspire from PR1 and Raise/Lower from PR2, P3 is feature-complete.

---

## §14 Resolved decisions (Matthew, 2026-05-21)

1. **Spring (T1) — deferred to P3.5.** Spring + Curse-citizen-flight ship
   together in a small follow-up after P3 lands; both depend on
   sub-mechanics (fresh-water tile semantics; FLEE behaviour vector) that
   are outside the P3 critical path.
2. **Counter-cast receipt seam — kept.** `PowerSystem.cast()` returns a
   `CastReceipt(kind, sim_t, resolve_at)` whose `resolve_at == sim_t` for
   T0/T1 in P3. P5 will widen `resolve_at` for T3+ to allow the 2-sec
   partial-cancel window without restructuring.
3. **Rival stub flag — included.** `python -m densitas.main
   --rival-stub-seed N` spawns N faction-1 citizens at `(world.w*3/4,
   world.h/2)` so the relic-shatter codepath is exercisable in live play
   before P4 ships rival AI. Off by default.
4. **Pool soft cap — deferred to P5 with `# TODO(P5)` marker.** Uncapped
   pool stays for P3. If banking gets trivial when T2 lands, we add
   `cap = 5000 + 10 × population` at that point.
5. **Curse-citizen-flight — deferred to P3.5** (paired with Spring). For
   P3, Curse only modulates food regen. Citizen flight overlaps with the
   future FLEE state machine.

(All ungated. PR1 starts.)

---

## §15 Acceptance criteria

After P3 ships:

* Press `4` then click on a GRASS tile → the tile becomes FOREST, the
  world surface repaints, the food field's local regen rises, the
  belief pool drops by 5, scripture line appears: *"The ground itself
  takes the shape of our will."*
* Press `R` over the central altar → first Witness drops onto the tile.
  Over the next 5 sim sec, the belief heatmap brightens at that point.
  Citizens drift toward it slightly more often than away.
* Press `6` near a hungry group → food regen doubles for 30 sec, hunger
  bar's amber/red segments shrink, reproduction quietly resumes.
* Cast Inspire while pool is at 0 → red "need 0 belief" chip, no
  cooldown, no cast.

If all four work without a crash and the scripture log feels alive after
five minutes of play, P3 is done.

---

## §16 Contract / file impact

| Surface                | Owner       | Change                                                                 |
|------------------------|-------------|------------------------------------------------------------------------|
| `densitas/powers.py`   | new         | `PowerKind`, `PowerSpec`, `POWERS`, `ActiveEffect`, `ScriptureEntry`, `PowerSystem` |
| `densitas/relics.py`   | new         | `Relic`, `RelicManager`, `RelicState`                                  |
| `densitas/rhetoric.py` | new         | `load_rhetoric()`, `pick(power, god, sim_t)`                           |
| `rhetoric.json`        | new         | Line pool (Open Eye only in P3)                                        |
| `densitas/belief.py`   | extended    | `recompute(citizens, relics=None, sim_t=0.0)`; `_scatter_relics`       |
| `densitas/food.py`     | extended    | `recompute(dt, effects=None)`                                          |
| `densitas/citizen.py`  | extended    | `add_attractor`, `remove_attractor`, `inspire_citizen` helper          |
| `densitas/world.py`    | extended    | `mutate_tile(world, food, repaint_cb, tx, ty, new_tile)`               |
| `densitas/render.py`   | extended    | `repaint_tile`, `blit_cast_preview`, `blit_relics`, `blit_scripture_log` (abstract + pixel) |
| `densitas/hud.py`      | extended    | pool bar, cooldown row, scripture log, relic tray                      |
| `densitas/main.py`     | extended    | number keys, mouse-to-tile, PowerSystem + RelicManager tick            |
| `densitas/config.py`   | extended    | `PowerConfig`, `RelicConfig`                                           |
| `config.toml`          | extended    | `[powers]`, `[powers.relic]`                                           |
| `tests/`               | extended    | `test_powers.py` (18), `test_relics.py` (10)                           |
| `WORKLOG.md` / `TODO.md` / `README.md` | extended | P3 status + new keybindings                                |

Total: 3 new modules + 1 new JSON + 9 modified modules + 2 new test
files. The Renderer ABC contract grows by 4 methods (`repaint_tile`,
`blit_cast_preview`, `blit_relics`, `blit_scripture_log`); these all
stay abstract in the base class so a future VectorRenderer fails fast
if they're missing.

---

*Spec ends.*
