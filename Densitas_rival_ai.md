# Densitas — Conversion + Rival God AI (PR4 spec)

*v0.1 — drafted 2026-06-07. Scope decisions confirmed with Matthew:
conversion lands in this PR (steps 1-2, the AI fights over something
real); framework built for three personalities with **Zealot live**,
Steward/Trickster parameter blocks specced but inert until T2/T3
powers exist; personality is **config-selectable** (`[rival]
personality = "zealot"`), not bound to the god — the Maw keeps its
voice whichever brain drives it.*

---

## 0. Scope

This PR makes the Maw play the game. Two halves:

* **Conversion** (GDD §6) — the per-citizen `faith` stat, drain in
  rival-dominated territory, the CONVERTED faction flip, despair
  death. This is the thing the gods fight *over*.
* **Rival AI** (GDD §7) — a decision loop that senses the belief
  fields, scores a small intent menu through personality weights, and
  acts through **exactly the player's verbs**: `PowerSystem.cast_or_queue`
  and `RelicManager.place/move/retrieve`.

Out of scope: Pilgrimage and all T2+ powers, fog-of-war sense
clipping, win/lose conditions, AI-state serialization, starting-
position fairness. See §14.

---

## 1. Pillars (load-bearing)

1. **The AI plays by the same rules** (GDD §7). It owns faction 1's
   existing belief pool, pays the same costs, waits the same
   cooldowns, gates on the same tiers, and is subject to the same
   tile-validity checks. Enforced structurally: the AI may only call
   the public APIs the player's input handlers call. It never writes
   to citizens, belief grids, food, or world directly. A property
   test (§12, E3) asserts every AI action passed through
   `can_cast(...) == True` or a relic-API `(ok, why)` success.
2. **Difficulty scales the tick rate of power use, not the rule set**
   (GDD §7, verbatim). One knob: decision cadence. No discounts, no
   extra senses, no pool multipliers — ever.
3. **Legible, cheap, deterministic.** No behavior trees, no planners.
   One utility-scored intent pick per decision tick, all senses
   derived from numpy ops on grids that already exist. Seeded RNG,
   no wall-clock. Two runs with the same seeds produce the same
   decision log.
4. **Personality is data, not code.** The three archetypes are
   parameter blocks over one shared loop. Adding a personality must
   not require touching the loop.
5. **God ≠ personality.** The god constrains *which* powers are
   castable (the Maw never blesses — lore mask); the personality
   weighs *when and where* within that mask. Scripture voice follows
   the god, always.

---

## 2. Faith — the conversion stat

### 2.1 The stat

New `Citizen` field: `faith: float = 1.0`, range `[0, 1]`. Spawned
citizens and newborns start at `1.0`. Converts restart at
`convert_faith_reset` (default 0.6 — converts are shaky).

### 2.2 Dominance and drain

Each citizen logic tick (5 Hz, inside the existing
`CitizenManager.tick` loop — two O(1) `belief.query` lookups per
citizen):

```
B_own = belief.query(tile_x, tile_y, faction=c.faction)
B_riv = belief.query(tile_x, tile_y, faction=enemy(c.faction))
dominance = B_riv / (B_riv + B_own + 1e-6)        # 0..1, 0.5 = parity
```

* `dominance > 0.5` — **drain**:
  `faith -= drain_rate * (2*dominance - 1) * dt`
  Linear ramp: zero at parity, full `drain_rate` under total rival
  dominance.
* `dominance < 0.5` — **regen**, but only inside your god's actual
  field (GDD: faith is *supplied* by proximity to belief):
  `faith += regen_rate * (1 - 2*dominance) * min(1, B_own / regen_ref) * dt`
  capped at 1.0. In the empty wilderness (`B_own ≈ B_riv ≈ 0`) the
  eps guard puts dominance ≈ 0 but the `B_own / regen_ref` factor is
  ≈ 0 too: **no drain, no regen, no wilderness death spirals.**

One smooth expression each way, no division blow-ups, vectorizable
later if the per-citizen loop ever becomes the bottleneck.

### 2.3 Thresholds — convert vs despair (GDD's two outcomes)

Checked in this order, immediately after the faith update:

1. **Despair:** `faith <= despair_threshold` (default 0.05) → enter
   DYING via the existing death path (cause tag `"despair"` for the
   summary/log). Despair is what happens when faith collapses and
   *no god is strong enough to receive you*.
2. **Convert:** `faith <= convert_threshold` (default 0.30) **and**
   `B_riv >= min_convert_belief` (default 0.05) → enter CONVERTED
   (§3). The receiving-field gate is what makes despair reachable:
   in a contested-but-weak zone the drain can carry a citizen
   straight past 0.30 because there is nothing to convert *to*.

States exempt from conversion checks: DYING (already gone) and
MATE (mid-ceremony; mercy rule, also avoids a half-flipped pair).
Faith still drains in those states; the check just defers.

---

## 3. CONVERTED — the faction flip

`CitizenState.CONVERTED = 8` finally gets a dispatch row.

* **Entry:** `state = CONVERTED`, `state_timer = ceremony_duration`
  (default 1.5 sim_s). The citizen stands still — the moment of
  apostasy is visible on the map (renderer note below).
* **Abort:** if during the ceremony the receiving field drops below
  `min_convert_belief` at the citizen's tile (their new god lost the
  ground), revert to IDLE. Faith stays where it is — they will
  likely re-enter CONVERTED or slide to despair.
* **Completion:** on `state_timer` expiry:
  `faction = enemy(faction)`, `faith = convert_faith_reset`,
  `home_x/home_y = current tile` (their old life is over),
  `state = IDLE`. Wander targets/attractors re-derive naturally on
  the next tick; `sync_attractors_from_relics` already filters by
  faction so the convert starts drifting toward its *new* god's
  relics with no extra code.
* **Accounting:** no code needed — `population(faction)` counts by
  the `faction` field, so tier progression, belief scatter
  (`_scatter` reads `c.faction`), HUD population, and the AI's own
  senses all see the flip for free. This is the payoff of P2's
  faction plumbing.
* **Renderer:** none. Sprites are cached per `(faction, facing,
  frame)` via `CITIZEN_PALETTE` — the flip re-tints automatically.
  The only addition: during CONVERTED the citizen renders with the
  *receiving* faction's accent color as a 1-px outline pulse
  (PixelRenderer only; one new branch in the citizen blit, no new
  abstract method on `Renderer`).

**Known follow-up exposed by this PR (flag, don't fix):** GDD §5
says tiers persist once unlocked, but `can_cast` recomputes
`tier_for(population(faction))` live. Conversion makes population
*drops* routine for the first time, so tier regression becomes
observable. The fix (a high-water-mark per faction) belongs in a
later slice; noting it here so nobody mistakes it for a PR4 bug.

---

## 4. Conversion scripture

The propaganda layer is the point of the game, and conversion is its
best material. Two new rhetoric keys, plus gap-fill:

* `citizen_converted.<god>` — voiced by the **gaining** god. The
  loser's silence is on-brand.
* `citizen_despair.<god>` — voiced by the **abandoning** god (dark;
  *"The unworthy among us were called home"* energy).
* **Gap-fill:** the Zealot's live cast set hits Maw cells that don't
  exist yet — `hunger_pang.maw` and `lower.maw` currently fall back
  to `<placeholder>`. (Audit of rhetoric.json 2026-06-07: Maw has
  only `curse` + the four relic events.) These get filled in the
  same step. Line-writing per the established voice rules
  (ridiculous-and-true double filter); Matthew co-writes like the
  step-12 pass.

**Coalescing.** Conversion cascades along a seam can fire dozens of
events per second; the log must not spam. Rate limit: max one line
per (key, god) per `scripture_coalesce_window` (default 5 sim_s);
batched events interpolate a `{count}` token (the step-12
`_SafeFormatDict` machinery handles unknown tokens already), e.g.
*"Seven more opened their eyes."* Lines must read correctly for
`{count} = 1`-style singulars — provide singular/plural variants in
the pool and pick by count.

---

## 5. Round setup — the rival becomes real

New `[rival]` config block (§11). Changes to `main.py` startup:

* **Default-on rival spawn.** `initial_population` (default 8)
  rival citizens at `(spawn_frac_x, spawn_frac_y)` of map size
  (default `0.75, 0.5` — the canonical stub location), radius
  `spawn_radius_tiles`. Implementation reuses `spawn_rival_stub`'s
  walkable-rejection loop, renamed `spawn_faction_at` (general
  signature; the stub name retires).
* **`--rival-stub-seed N` deprecated** → alias that overrides
  `rival.initial_population` and prints a deprecation warning.
  Remove in P5.
* **Hardcoded seed relics removed.** The six center-relative
  placements (three per god) made sense when relics were
  watch-only; now the player places theirs (R-key, PR3 step 10) and
  the AI places its own (§8). A `--seed-relics` debug flag restores
  the old six for renderer testing. Default rounds start with all
  six slots AVAILABLE.
* **Player spawn unchanged** (map center). Starting-position
  fairness stays an open terrain-gen TODO; not this PR.

---

## 6. AI architecture

New module `densitas/rival_ai.py`. One class, one dataclass, one
preset table. No other module imports it except `main.py`
(one-way dependency; rival_ai imports only public APIs).

```python
@dataclass(frozen=True)
class AIPersonality:
    name: str
    # intent weights (0 disables an intent for this personality)
    w_curse: float
    w_hunger_pang: float
    w_lower: float
    w_bless: float
    w_relic_place: float
    w_relic_move: float
    w_relic_retrieve: float
    # behavioral scalars
    spend_floor: float        # don't cast costed powers below this pool level
    idle_floor: float         # if best score <= this, do nothing this tick
    retrieve_panic: float     # threat_fraction above which retrieve utility ramps
    relic_forward_bias: float # 0 = place defensively, 1 = at the enemy's throat
    jitter: float             # uniform tie-break noise on scores

PERSONALITIES: dict[str, AIPersonality] = {"zealot": ..., "steward": ..., "trickster": ...}
```

```python
class RivalAI:
    def __init__(self, faction: int, personality: AIPersonality,
                 rival_cfg, powers_cfg, seed: int): ...
    def tick(self, dt: float, *, sim_t, citizens, belief, relic_mgr,
             power_system, world) -> None:
        # accumulate; every `period` sim_s run one sense->score->act pass
```

* **Cadence:** `period = ai_base_period / difficulty` (default
  2.0 / 1.0 → a decision every 2 sim_s = every 10th logic tick),
  floored at one logic tick. This is the *only* thing difficulty
  touches (pillar 2).
* **Call site:** in `main.py`'s 5 Hz block, after `relic_mgr.tick`
  and the attractor re-sync — the AI senses this tick's fully
  settled state; its casts dispatch immediately through the same
  code path as a player click and take effect like any cast would.
* **Determinism:** `self.rng = np.random.default_rng(ai_seed ^ (faction << 8))`.
  All randomness (jitter, tile refinement) flows from it.
* **Decision log:** ring buffer (64) of
  `DecisionRecord(sim_t, intent, target, score, top3)` — feeds the
  `--ai-debug` stdout dump now, a debug overlay later, and the
  determinism tests (§12).
* **One action per decision tick.** Zealots feel relentless at a
  2-second cadence; nobody needs a combo system.

---

## 7. Senses

All cheap, all derived per decision tick (not per logic tick), all
read-only. Belief grids are 64×48 numpy arrays over the 256×192
world — every argmax below is grid-resolution, refined to a walkable
world tile afterward (§8).

| Sense | Source | Cost |
|---|---|---|
| `pop_own`, `pop_enemy` | `citizens.population(f)` | O(n) existing |
| `pool_own` | `power_system.pool[f]` | O(1) |
| `tier_own` | `tier_for(pop_own)` | O(1) |
| `B_own`, `B_enemy` | `belief.grid(f)` | view, free |
| `seam_product` | `B_own * B_enemy` | one 64×48 multiply |
| `enemy_peak_cell` | `argmax(B_enemy)` | one pass |
| `seam_peak_cell` | `argmax(seam_product)` | one pass |
| `own_centroid`, `enemy_centroid` | mean of citizen positions by faction | O(n) |
| own relics + threat | `relic_mgr.for_faction(f)`, `.threat_timer / shatter_time` | O(relics) |
| enemy placed relic cells | `relic_mgr.placed_for_faction(enemy)` | O(relics) |

No sense reads anything the player can't see on screen today (the
heatmap overlay shows both fields; fog-of-war symmetry arrives with
P2.5 for both sides at once — §14).

---

## 8. Intent menu (PR4 set)

Each decision tick: score every intent, `score = weight × utility ×
feasible + jitter`, take the argmax, act if it beats `idle_floor`.
Feasibility uses `can_cast` (full checks, *not* `skip_cooldown`) or
the relic APIs' validity, so an infeasible intent scores 0 rather
than erroring — and the same-rules pillar holds by construction.

**God power mask.** `GOD_FORBIDS: dict[god_key, frozenset[PowerKind]]`
— `maw: {BLESS}`, `open_eye: {}` (Sundering is T4's problem).
Applied before scoring; a personality's `w_bless` simply never fires
for the Maw. Mask lives in rival_ai.py next to the personalities;
lore enforcement in one greppable place.

| Intent | Target | Utility (0..1) | Verb |
|---|---|---|---|
| CAST_CURSE | `seam_peak_cell` | normalized `B_enemy` at cell | `cast_or_queue(CURSE, ...)` |
| CAST_HUNGER_PANG | `enemy_peak_cell` | normalized enemy density at cell | `cast_or_queue(HUNGER_PANG, ...)` |
| CAST_LOWER | highest walk-blocking ridge cell adjacent to seam | terrain advantage estimate | `cast_or_queue(LOWER, ...)` |
| CAST_BLESS | own densest cell | own-density shortfall vs enemy | `cast_or_queue(BLESS, ...)` (masked for Maw) |
| RELIC_PLACE | seam push point (below) | free slots × seam opportunity | `relic_mgr.place` |
| RELIC_MOVE | rear-most placed relic → push point | seam drift distance behind relic | `relic_mgr.move` |
| RELIC_RETRIEVE | most-threatened placed relic | `threat_fraction`, ramping past `retrieve_panic` | `relic_mgr.retrieve` |
| IDLE | — | `idle_floor` | none |

**Costed casts** additionally gate on `pool_own >= spend_floor +
spec.belief_cost` — the Steward hoards by raising `spend_floor`, the
Zealot's floor is 0. (`spend_floor` is a *reserve*, not a discount;
pillar 1 is untouched.)

**Relic push point.** `lerp(seam_peak_cell, enemy_centroid,
relic_forward_bias)`, snapped to grid. Zealot bias 0.65 plants
relics past the seam — greedy, shatter-prone, exactly right.
Steward bias 0.15 keeps them home.

**Tile refinement.** Chosen grid cell → its 4×4 world-tile block →
seeded-shuffle, first tile passing walkability + the verb's own
validity check (`can_cast` / relic `(ok, why)`); if none pass, the
intent was infeasible this tick, re-score without it. Bounded two
re-scores per tick, then IDLE — no scanning loops.

**Scripture for free:** every cast and relic verb already emits
through the rhetoric path keyed by `_god_key_for(faction)`. The Maw
narrates its own aggression with zero new wiring (the missing Maw
*cells* are §4's gap-fill).

---

## 9. Personality parameter blocks

### 9.1 Zealot — live in PR4

> aggressive, pushes seams, casts powers cheaply, neglects density (GDD §7)

| Param | Value | Reading |
|---|---|---|
| w_curse / w_hunger_pang / w_lower | 1.0 / 0.8 / 0.3 | offense first |
| w_bless | 0.1 | "neglects density" (and masked off for the Maw anyway) |
| w_relic_place / move / retrieve | 0.9 / 0.5 / 0.3 | plants flags, rarely retreats |
| spend_floor | 0.0 | casts the moment it can afford to |
| idle_floor | 0.05 | almost never idles |
| retrieve_panic | 0.75 | lets relics burn until the last moment |
| relic_forward_bias | 0.65 | places past the seam |
| jitter | 0.05 | |

Starting numbers, tuned in step 8's balance pass against the
acceptance run (§13).

### 9.2 Steward — specced, partially inert until T3

Defensive density: high `w_bless` (1.0), low offense (0.2s),
`spend_floor` ≈ 60 (hoards toward big casts **that don't exist yet**
— with only T0/T1 implemented a Steward banks belief it will never
spend; that's honest inertness, not a bug), `retrieve_panic` 0.35,
`relic_forward_bias` 0.15, `idle_floor` 0.25 (comfortable doing
nothing). Note: a Steward *Maw* is bless-masked into near-total
passivity — funny, lore-coherent, and exactly why personality is
config-selectable.

### 9.3 Trickster — specced, blocked on Pilgrimage (T2)

Signature verb doesn't exist. Block reserves `w_pilgrimage` (the
dataclass grows the field when T2 lands; until then the preset
zeroes everything distinctive and plays like a timid Zealot).
Targeting note for the future: Trickster aims at the *thinnest*
positive enemy belief (argmin over masked field), placing relics to
overlap enemy fringes — conversion pressure, not disasters.

---

## 10. Difficulty

`[rival] difficulty = 1.0` → `period = ai_base_period / difficulty`.
0.5 = a ponderous god, 2.0 = a frantic one. Nothing else changes
(pillar 2). Not surfaced in any menu this PR; config knob only.

---

## 11. Config schema (new blocks)

```toml
[citizen.faith]
drain_rate         = 0.08   # faith/sim_s under total rival dominance
regen_rate         = 0.04   # faith/sim_s deep in your own field
regen_ref          = 0.50   # belief level giving full-rate regen
convert_threshold  = 0.30
despair_threshold  = 0.05
min_convert_belief = 0.05   # receiving field must be at least this
ceremony_duration  = 1.5    # sim_s standing in CONVERTED
convert_faith_reset = 0.60
scripture_coalesce_window = 5.0

[rival]
enabled            = true
personality        = "zealot"    # zealot | steward | trickster
difficulty         = 1.0         # scales decision cadence ONLY
initial_population = 8
spawn_frac_x       = 0.75
spawn_frac_y       = 0.50
spawn_radius_tiles = 5
ai_base_period     = 2.0         # sim_s between decisions at difficulty 1.0
ai_seed            = 0
```

Worked into `config.py` dataclasses with the same tomllib/tomli
fallback; every value above is a playtest knob, defaults are
opening bids.

---

## 12. Tests (≈ +50, suite 209 → ~260)

* **A. Faith math (6):** parity ⇒ no change; drain ramp linear in
  dominance; regen requires own field (void ⇒ frozen faith); clamps
  at [0, 1]; eps guards (both fields zero); drain continues during
  MATE but transition defers.
* **B. Conversion transitions (8):** despair checked before convert;
  convert gated on `min_convert_belief`; ceremony abort path;
  completion flips faction + resets faith/home; population/tier
  accounting follows the flip; newborn faith = 1.0; DYING exempt;
  despair reuses the existing death path with cause tag.
* **C. Round setup (5):** default rival spawn count/location;
  `--rival-stub-seed` alias warns + overrides; `--seed-relics`
  restores exactly the old six; default round has six AVAILABLE
  slots; config round-trips.
* **D. AI skeleton (8):** cadence honors period and difficulty
  scaling; decision sequence deterministic under fixed seeds (two
  fresh runs, identical logs); senses math (seam_product argmax,
  centroids) against hand-built grids; ring buffer caps at 64.
* **E. Same-rules property (3):** run 500 decision ticks with a
  forced-aggressive personality on a contested map — every executed
  action passed `can_cast == True` / relic `(ok=True)`; pool never
  negative; Maw never blessed even with `w_bless = 1.0` forced.
* **F. Relic intents (6):** push-point lerp + snap; place consumes a
  slot through the real API; retrieve fires only past
  `retrieve_panic`; move targets the rear-most relic; refinement
  never yields an unwalkable tile; two-rescore bound holds.
* **G. Scripture (5):** coalescing window batches with `{count}`;
  singular/plural cell selection; `citizen_converted`/`citizen_despair`
  cells exist for both gods; `hunger_pang.maw` / `lower.maw` no
  longer fall through to `<placeholder>`; no-repeat rule survives
  coalesced picks.

Plus the headless acceptance run in step 8.

---

## 13. Step plan (commit-sized; one .cmd each, /outputs staging per the bundling rule)

| Step | Lands | Tests |
|---|---|---|
| 1 | `faith` field + drain/regen integration + `[citizen.faith]` config | A |
| 2 | CONVERTED dispatch row + despair + flip + outline pulse | B |
| 3 | `[rival]` block, default-on spawn, seed-relic removal + `--seed-relics`, stub-flag deprecation | C |
| 4 | `rival_ai.py` skeleton: personality dataclass + presets, cadence, senses, scoring, decision log, `--ai-debug`; all intents no-op | D |
| 5 | Cast intents live (CURSE / HUNGER_PANG / LOWER / BLESS) + god mask | E |
| 6 | Relic intents live (place / move / retrieve, push-point targeting) | F |
| 7 | Scripture: conversion keys + coalescing + Maw gap-fill *(line co-write with Matthew)* | G |
| 8 | Difficulty wiring + Zealot balance pass + WORKLOG/TODO/README sync | acceptance |

**Acceptance (step 8, headless, 600 sim_s, default config, seed 42 ×3
runs):** the rival places ≥ 2 relics, casts ≥ 10 times, converts ≥ 5
player citizens; no exceptions; pool never negative; player relics
near the seam come under genuine shatter threat in at least one run.
The bar is "the Maw is *present*", not "the Maw is balanced" —
balance is playtest's job.

Commit hygiene per the standing rule: each step staged in /outputs
until HEAD matches the previous step's commit; explicit `git add` of
only that step's files (build.cmd/start.cmd CRLF noise and scratch
.cmd/.txt artifacts stay out); pre-flight HEAD check in every .cmd.
PR4 step 1's pre-flight expects HEAD = the spec commit (the commit
that lands this doc). The spec commit itself expects HEAD = `b922d7d`
(origin is current there as of 2026-06-07).

---

## 14. Deliberately omitted (and why)

* **Pilgrimage / T2+ powers.** Trickster's signature and Steward's
  payoff. Separate power-PR; the personality blocks already leave
  their seams.
* **Fog-of-war sense clipping.** P2.5. Today the AI is omniscient
  and so is the player (full-map view + heatmap overlay) — symmetric,
  pillar-clean. When fog lands, §7's senses get masked the same way
  the player's overlay does.
* **Win/lose conditions.** P5. After this PR the Maw can genuinely
  extinguish you, which will make P5 urgent rather than theoretical.
* **AI state serialization.** The AI is nearly stateless (cadence
  accumulator + decision ring); a loaded round re-seeds and the Maw
  simply thinks fresh. Noted for the save-file PR alongside the
  bigger gap: *citizen* serialization (which must now include
  `faith` + `faction`).
* **Tier high-water-mark.** The GDD §5 persistence rule vs live
  `tier_for` recompute (§3). Small follow-up slice, post-PR4.
* **AI Whispers.** Same-rules says it *could*; zero strategic value
  at AI scale. Skipped.
* **Starting-position fairness.** Open terrain-gen TODO; rival
  spawns at the canonical 0.75 / 0.5 stub point for now.

---

## 15. Contract with the rest of the codebase

* `densitas/rival_ai.py` exports `RivalAI`, `AIPersonality`,
  `PERSONALITIES`, `GOD_FORBIDS`.
* `main.py`: constructs `RivalAI` after `relic_mgr` (respecting the
  hotfix ordering lesson — AI construction needs the manager to
  exist); calls `rival_ai.tick(...)` in the 5 Hz block **after**
  `relic_mgr.tick` + attractor re-sync.
* `citizen.py`: `Citizen.faith` field; faith update + threshold
  checks inside `CitizenManager.tick`; `spawn_rival_stub` →
  `spawn_faction_at`. Exports unchanged otherwise.
* `powers.py`, `relics.py`, `belief.py`, `render.py`: **no public
  API changes.** One PixelRenderer-internal branch for the
  CONVERTED outline pulse.
* `config.py`: `FaithConfig`, `RivalConfig` dataclasses + parsing.
* `rhetoric.json`: +4 key families (§4). `rhetoric.py`: coalescing
  helper (pure, testable without pygame).

Nothing in `world.py`, `camera.py`, `food.py`, `hud.py` changes.
