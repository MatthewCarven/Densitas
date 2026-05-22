# Densitas — Religious Relics

*v0.1 — 2026-05-22. Companion spec for P3 PR3. Refines `Densitas_P3.md` §6 with the renderer, HUD, and UX detail the implementation needs.*

Relics are the strategic verb of Densitas. Powers fire once and resolve; relics persist for minutes, pin intent to the map, and decide where civilizations grow. P3 PR1 and PR2 gave the player tactical hands. PR3 gives them a strategic anchor.

This doc layers on top of `Densitas_P3.md` §6. Where the two disagree, this doc wins for the implementation; P3.md remains the milestone-level summary.

---

## §1 Pillars

1. **Cost is opportunity, not belief.** A relic costs 0 belief to place. The cost is the slot — you only have three, and a shattered relic is gone forever. The player who places carelessly loses the game without the rival spending a single power.
2. **Relics radiate, they don't compel.** Citizens are *attracted* to relics, not *commanded* by them. Hunger overrides devotion. A relic in a barren spot still pulls, but the bodies it draws starve.
3. **Visibility is the whole point.** A placed relic glows on the heatmap, on the map itself, and in the tray. The player should always know where each of their relics is at a glance — never hunt for one.
4. **Shatter is permanent and ceremonial.** A relic going down is the biggest event in the game short of a citizen-zero. The visual and the summary screen mark it; the slot stays empty for the rest of the round.
5. **No second modality.** Placement and retrieval are keyboard-modes + click, identical in shape to power-casting. The tray displays state; it doesn't accept input.

---

## §2 Data model

`densitas/relics.py`. Refines P3.md §6 with the fields needed for the summary screen and for save/load.

```python
class RelicState(IntEnum):
    AVAILABLE = 0
    PLACED    = 1
    SHATTERED = 2


@dataclass
class Relic:
    id: int                  # stable per game, 0..N-1 across all factions
    faction: int             # 0 = Open Eye, 1 = Maw, ...
    slot: int                # 0..initial_count-1 within its faction
    name: str                # "The First Witness", "Second Bite", ...
    state: RelicState        # AVAILABLE / PLACED / SHATTERED
    tx: int                  # placed tile (meaningless when AVAILABLE)
    ty: int
    placed_at: float         # sim_t of last place/move; 0.0 when AVAILABLE
    times_moved: int         # increments on every move() (not on first place)
    threat_timer: float      # 0..shatter_time; bleeds at 2x recovery rate
    shatter_at: float        # sim_t when SHATTERED; 0.0 otherwise
    shatter_summary: Optional["ShatterSummary"] = None


@dataclass(frozen=True)
class ShatterSummary:
    relic_id: int
    faction: int
    name: str
    tx: int
    ty: int
    sim_t: float             # when it shattered
    local_belief_player: float
    local_belief_rival: float
    player_citizens_within_8: int
    rival_citizens_within_8: int
    time_placed_total: float # sum of all placement intervals (sim_s)
    times_moved: int
```

`RelicManager`:

```python
class RelicManager:
    def __init__(self, cfg: RelicConfig, n_factions: int): ...
    relics: list[Relic]                                    # flat, length n_factions * initial_count

    # Mutations — return (ok, reason).
    def place(self, faction: int, slot: int, tx: int, ty: int,
              world: World, sim_t: float) -> tuple[bool, str]: ...
    def move (self, faction: int, slot: int, tx: int, ty: int,
              world: World, sim_t: float) -> tuple[bool, str]: ...
    def retrieve(self, faction: int, slot: int,
                 sim_t: float) -> tuple[bool, str]: ...

    # Per-tick.
    def tick(self, dt: float, belief: BeliefField, citizens: CitizenManager,
             sim_t: float) -> list[ShatterSummary]: ...
        # Returns any newly-shattered summaries this tick (0 or 1 in practice).

    # Queries.
    def get(self, faction: int, slot: int) -> Relic: ...
    def for_faction(self, faction: int) -> list[Relic]: ...
    def placed_for_faction(self, faction: int) -> list[Relic]: ...
    def shatter_at(self, tx: int, ty: int, radius: int,
                   sim_t: float) -> list[ShatterSummary]: ...   # hook for P5 disasters
```

`place`/`move` validate: tile in-bounds, tile walkable, not already occupied by another relic of the same faction. Shattered relics are no-ops on every mutation. Validation reasons surface as strings like `"slot already placed — use move"`, `"tile not walkable"`, `"can't place — water"`.

**ID assignment.** `id = faction * initial_count + slot`. Stable across the round so the save file can refer to relics by id.

---

## §3 Lifecycle & input

### §3.1 Placement (R-mode)

Per `Densitas_P3.md` §10.1 and the decision sketched 2026-05-22:

* `R` cycles the player's tray: enters `RELIC_PLACE` mode targeting the lowest-slot AVAILABLE relic. Press `R` again: cycles to the next AVAILABLE slot. Press `R` with no AVAILABLE relics: enters `RELIC_MOVE` mode targeting the lowest-slot PLACED relic (the player wanted to relocate). Press `R` a third time after all slots are exhausted: cancels mode.
* In `RELIC_PLACE` mode: cursor shows the relic glyph at 50% alpha at the hovered tile, with a soft cyan attract-circle (R=8) and a green/red tint to indicate validity.
* `LMB` on a valid tile: relic transitions AVAILABLE → PLACED, `placed_at = sim_t`, `times_moved` unchanged (placement isn't a move). Scripture line emitted from `relic_placed.<god>` pool.
* `LMB` on an invalid tile: rejection chip near cursor (`"can't place on water"`); mode stays active.
* `RMB` or `ESC`: cancel mode.

In `RELIC_MOVE` mode (same `R` key, just the next state): same cursor preview, but `LMB` on a valid tile triggers `move`, which updates `tx`/`ty`/`placed_at`, increments `times_moved`, and resets `threat_timer` to 0. The belief contribution restarts its fade-in from zero — moving a relic costs it 30 sim_sec of full-amplitude time. That's the cost of relocation.

### §3.2 Retrieval (Shift+R)

* `Shift+R` enters `RELIC_RETRIEVE` mode. Cursor shows a small "↶" icon. PLACED relic tiles glow.
* `LMB` on a PLACED relic's tile (within the player's faction): relic transitions PLACED → AVAILABLE, `placed_at` zeroed, position cleared. Scripture line from `relic_retrieved.<god>`.
* `LMB` on any other tile: no-op, mode stays active.
* `RMB` or `ESC`: cancel mode.

A retrieved relic is immediately available to re-place. The same slot, the same name. The strategy is: pull it back before it shatters, eat the cost of the fade-in, hope to redeploy on better ground.

### §3.3 Why no drag-from-tray

Considered and rejected. It adds a second input modality, breaks the keyboard-first feel of power casting, and isn't more discoverable once the tooltip on the tray slot reads "Press R to place." Park if playtest disagrees.

---

## §4 On-map rendering

`Renderer.blit_relics(screen, relics, cam_x, cam_y, sim_t)` — new abstract method, pixel impl in `PixelRenderer`.

* **Sprite source.** The 7 glyph designs in `Densitas_relic_glyphs_v1.html` are pre-rasterized at game start into a sprite atlas keyed by relic id. (Glyphs 1-3 = Open Eye, 4-6 = Maw, 7 reserved for the future T3 unlock.)
* **Target size.** 20 px square (mid-band of the 16-24 px range from the TODO). Renders at 1:1 on the default zoom; `pygame.transform.scale` nearest-neighbour at other zooms (per the camera-zoom backlog item; relics inherit the same scale path as citizens).
* **Anchor.** Bottom-centred on the tile, matching citizen sprite anchor. The 20×20 sprite sits on tile `(tx, ty)` with its base aligned to the tile's bottom edge in screen space.
* **Depth.** Drawn *after* the world surface and *before* citizens, so citizens walk visibly over a relic's base but never disappear behind it. The relic's top-half overlaps citizens in the same tile only when the citizen is north of the relic — minor, acceptable.
* **Fade-in pulse.** During the `place_cooldown` window (default 30 sim_sec after place/move), the sprite's alpha pulses gently: `alpha = 160 + 64 * sin(2π * sim_t / 1.5)`, clamped. This visually signals "not yet at full belief amplitude." After cooldown, alpha is solid 255.
* **Threat overlay.** When `threat_timer > 0`, a thin red ring is drawn around the sprite. Ring opacity = `threat_timer / shatter_time`. Full ring = imminent shatter.

### §4.1 Shatter animation (subtle ceremony)

When `RelicManager.tick` flips a relic to SHATTERED:

1. The glyph cracks visibly: over 0.4 sim_sec, two procedural cracks (computed from `hash(relic.id)`) are drawn across the sprite. Implementation: render the sprite into an offscreen surface, draw two `pygame.draw.line` strokes in #1a0000 across it, blit.
2. At t=0.4 sec, a single-frame white flash at the tile (3×3 tile rect, alpha 200, blit once).
3. From t=0.4 to t=1.0, the sprite alpha-fades from 255 to 0.
4. At t=1.0, the sprite is removed from the draw list. The tile is unmarked.
5. A scripture line emits from `relic_shattered.<god>` (existing pool in `rhetoric.json`).
6. The summary panel slides in (see §6).

The game keeps running throughout. No pause, no dilation. The drama is enough by being silent.

### §4.2 Sound (deferred)

P3 has no audio system. The shatter is silent in PR3. Wire a `RelicManager.on_shatter` callback list so a future audio module can subscribe without touching the relic code. Default empty.

---

## §5 Tray HUD

`densitas/hud.py` — `blit_relic_tray(screen, relics, sim_t)`. Bottom-right corner, 3 slots stacked vertically (or horizontally — pick one, document below).

Layout (horizontal, fits beside the cooldown row):

```
┌────────────────┬────────────────┬────────────────┐
│  [glyph 20px]  │  [glyph 20px]  │  [glyph 20px]  │
│  First Witness │  Second Witns. │  Third Witness │
│  AVAILABLE     │  PLACED (12,34)│  SHATTERED     │
│                │  ▓▓▓░░░░░ 12s  │                │
└────────────────┴────────────────┴────────────────┘
```

Per slot:

* **AVAILABLE.** Full-colour glyph at 24×24, name in black, status "AVAILABLE" in green. Tooltip on hover: "Press R to place."
* **PLACED.** Greyed glyph at 24×24 (70% saturation), name, "PLACED (tx,ty)", and a thin bar showing `placed_at` age. If `threat_timer > 0`, the bar tints red and shows the threat ratio (`threat_timer / shatter_time` as percentage).
* **SHATTERED.** Skull-X glyph (a constant icon, not the relic's original glyph) at 24×24 in dark red, name struck-through, status "SHATTERED" in red. Tooltip on hover: "Lost at (tx,ty) — click to view." Clicking re-opens the summary panel for that relic.

Slot size: 110 × 56 px. Tray total: 330 × 56 px. Sits to the left of the existing scripture log.

The tray is **display-only** — it does not accept clicks (except the SHATTERED summary re-open, which is the exception). All input is via `R` / `Shift+R`. This is deliberate per §1 pillar 5.

---

## §6 Shatter summary panel

When a relic shatters, after the on-map animation completes (~1.0 sim_sec after the trigger), a panel slides in from the right edge.

* **Dimensions.** 320 px wide, 280 px tall. Parchment background (`#f4e9ce`), 2 px gold border.
* **Slide.** Tweens in over 0.4 wall-seconds (cubic ease-out), holds for 10 sim_sec, slides out over 0.4 wall-seconds.
* **Dismiss.** Click anywhere on the panel = dismiss early. Click outside = no-op (the player might be mid-cast).
* **No pause.** The game continues. The player can cast through the panel — it does not capture input outside its own rect.

Content (the 7 fields from the TODO, plus 1 derived):

```
─── A RELIC HAS BROKEN ───────────────────
   The Second Witness
   Tile (47, 23)            sim_t 412.6 s

   Local belief at shatter
     yours:    4.2
     rival:    11.7        (ratio 2.78×)

   Citizens within 8 tiles
     yours:    23
     rival:    91

   Time placed:             198.4 s
   Times moved:             2

   (click to dismiss)
```

The line "ratio 2.78×" is derived (`rival / max(player, 1e-3)`). Everything else is verbatim from `ShatterSummary`.

A scripture-log entry is also emitted: *"The Second Witness has broken at (47, 23). The rival sang louder."* — picked from a new `relic_shattered_loud` pool to differentiate from the existing per-tick relic-shattered line.

### §6.1 Re-opening from the tray

Clicking the SHATTERED tray slot re-opens the panel for that relic, with the original `ShatterSummary` data. Same dimensions, same dismiss rules. No re-animation — it just appears. Useful for post-mortem.

---

## §7 Belief contribution

(Refines `Densitas_P3.md` §6.3.)

In `BeliefField.recompute(citizens, relics=None, sim_t=0.0)`:

```python
def recompute(self, citizens, relics=None, sim_t=0.0):
    self.field.fill(0.0)
    self._scatter(citizens)
    if relics is not None:
        self._scatter_relics(relics, sim_t)
    self._blur()
    self.version += 1
```

`_scatter_relics`:

```python
def _scatter_relics(self, relics, sim_t):
    amp = self.cfg.relic_amplitude       # 20.0
    cd  = self.cfg.relic_place_cooldown  # 30.0
    for r in relics:
        if r.state != RelicState.PLACED:
            continue                      # SHATTERED contributes nothing
        elapsed = sim_t - r.placed_at
        weight  = amp * min(1.0, elapsed / cd)   # linear fade-in
        cx, cy  = r.tx // tpcx, r.ty // tpcy
        if 0 <= cx < gw and 0 <= cy < gh:
            self.field[r.faction, cy, cx] += weight
```

Consequences worth noting in tests:
* **SHATTERED relics do not contribute.** This is what makes a shatter hurt — both the belief amplitude and the bias toward that tile evaporate.
* **A just-placed relic contributes 0** for one tick — the fade-in starts on the *next* recompute after `placed_at`.
* **Belief scales the power strength.** A Bless cast on top of a 30-sec-old relic gets `local_b ≈ 20 + nearby_population`, which means much higher `strength`. This is intended — relics are the strategic anchor; powers cast near them are stronger.

---

## §8 Citizen attraction

(Refines `Densitas_P3.md` §6.4 with concrete numbers and code shape.)

`CitizenManager` gains:

```python
self.attractors: list[tuple[int,int,int,int]] = []
# (tx, ty, radius, faction)

def sync_attractors_from_relics(self, relics: list[Relic],
                                 attract_radius: int) -> None:
    """Called by main.py after every RelicManager mutation."""
    self.attractors = [
        (r.tx, r.ty, attract_radius, r.faction)
        for r in relics if r.state == RelicState.PLACED
    ]
```

In `_pick_wander_target(c: Citizen)`:

```python
# Hunger trumps devotion — FORAGE-bound citizens skip attractors entirely.
if c.state == CitizenState.FORAGE:
    return self._random_wander_target(c)

# Per-faction attractors only.
mine = [a for a in self.attractors if a[3] == c.faction]
if mine and self.rng.random() < self.cfg.attract_probability:
    tx, ty, R, _ = self.rng.choice(mine)
    # Uniform within disc of radius R.
    return self._random_in_disc(tx, ty, R)

return self._random_wander_target(c)
```

Defaults: `attract_radius = 8`, `attract_probability = 0.4` (per the P3.md `[powers.relic]` config). Both are tunable.

Worth noting:
* A citizen with multiple same-faction attractors picks one **uniformly** at every wander pick. We don't weight by distance or current relic age. Simpler, and citizens drift between multiple relics naturally.
* The 40% probability is per-wander-pick, not per-tick. With wander picks every ~5 sim_sec on average, a citizen near 2 relics within their range will accumulate roughly 40% of their wandering time toward them.

---

## §9 Shatter rule

(Refines `Densitas_P3.md` §6.5 — same algorithm, but here we spell out the tick integration and what gets emitted.)

Inside `RelicManager.tick(dt, belief, citizens, sim_t)`:

```python
shattered_this_tick: list[ShatterSummary] = []
for r in self.relics:
    if r.state != RelicState.PLACED:
        continue
    p_b = belief.query(r.tx, r.ty, faction=r.faction)
    r_b = max((belief.query(r.tx, r.ty, f)
               for f in range(belief.n_factions) if f != r.faction),
              default=0.0)
    if r_b > self.cfg.shatter_ratio * max(p_b, 1e-3):
        r.threat_timer += dt
    else:
        r.threat_timer = max(0.0, r.threat_timer - 2.0 * dt)

    if r.threat_timer >= self.cfg.shatter_time:
        summary = self._build_shatter_summary(r, p_b, r_b,
                                              citizens, sim_t)
        r.state = RelicState.SHATTERED
        r.shatter_at = sim_t
        r.shatter_summary = summary
        # Position is retained so the on-map crack/flash can render at it.
        shattered_this_tick.append(summary)
return shattered_this_tick
```

`_build_shatter_summary` snapshots all eight fields, including counting citizens within 8 tiles of `(r.tx, r.ty)` for both factions (linear scan; small N).

The recovery rate of `2.0 * dt` means a 1-sec rival incursion erases ~2 sec of threat. Sustained pressure is required. Tunable via config if it feels too forgiving.

### §9.1 Drown-while-placed edge case

If a relic's tile gets Lowered into WATER (player or rival cast), the relic stays placed — water doesn't shatter a relic, only sustained rival belief does. The relic continues to attract citizens (who can't walk to it, since the tile is no longer walkable, but they'll try). This is a deliberate strategic wrinkle: lowering enemy land under their relic doesn't kill the relic, but it does isolate it.

If we change our minds and want water tiles to shatter relics, the hook is one line in `world.mutate_tile`: `relics.shatter_at(tx, ty, radius=0, sim_t)`. Park.

---

## §10 Edge cases

| Case                                          | Behaviour                                                        |
|-----------------------------------------------|------------------------------------------------------------------|
| Place on tile occupied by another relic       | Reject with `"tile occupied by another relic"`.                  |
| Place on a citizen's tile                     | Allowed. Citizens walk over relics.                              |
| Move during fade-in (placed_at < 30 sec ago)  | Allowed. Fade-in restarts from 0 at new tile.                    |
| Retrieve during shatter ceremony (~1 sec)     | Rejected — the relic is already SHATTERED; the tray shows it.    |
| Bless on top of own relic                     | Stronger Bless (higher local belief → higher strength). Working as intended. |
| Curse on top of own relic                     | Curse takes effect normally; the relic still pulls citizens *into* the cursed food regen. Player's mistake. |
| Curse on rival relic                          | Doesn't shatter it, but the food malus slows rival reproduction in the area, which over time shifts the belief ratio in your favour. The intended counter-strategy. |
| Raise on tile under own relic                 | Allowed. Relic stays in place; the tile mutation runs normally.   |
| Lower on tile under own relic, into water     | See §9.1.                                                         |
| Pool at 0 belief                              | No effect on relics — placement/retrieval are 0 belief.           |
| All 3 relics shattered                        | Player can still cast powers; they just have no relic anchor. Likely losing position. |
| Save / load                                   | Serialise the full `Relic` list (including `shatter_summary`) verbatim. `RelicManager.from_dict` rehydrates. |

---

## §11 Tests

Lives in `tests/test_relics.py`. Targets 12 (the 10 from `Densitas_P3.md` §12 #19-28, plus 2 new edge-case tests).

1. RelicManager initialises with `initial_count` AVAILABLE relics per faction.
2. `place(faction, slot, tx, ty, ...)` transitions AVAILABLE → PLACED and stamps `placed_at`.
3. `move(...)` resets `placed_at`, increments `times_moved`, and zeroes `threat_timer`.
4. `retrieve(...)` transitions PLACED → AVAILABLE, clears position.
5. `_scatter_relics` adds exactly `amplitude` at the relic tile after `place_cooldown` elapses.
6. `_scatter_relics` fades in linearly during the cooldown window: at `0.5 * cooldown`, contributed weight is `0.5 * amplitude`.
7. Shatter trigger: write rival belief above ratio for `shatter_time` seconds; relic enters SHATTERED, `shatter_summary` populated with all 8 fields.
8. Shatter recovery: ratio met for 4 sec then drops; `threat_timer` decays back toward 0 at 2× rate; no shatter.
9. Citizen attractor: in 1000 wander-picks with one relic at known location, ~40% land within the relic radius (allow ±5% tolerance).
10. SHATTERED relic doesn't contribute to belief field (post-shatter, `_scatter_relics` skips it).
11. **(New)** Hunger overrides attraction: a FORAGE-state citizen's `_pick_wander_target` ignores attractors and uses normal random wander.
12. **(New)** Move during fade-in: a relic moved at sim_t=15 (cooldown=30) has its weight at sim_t=20 equal to `(20-15)/30 * amplitude`, not `(20-0)/30 * amplitude` — i.e., the fade-in clock restarts.

Smoke tests beyond the 12:
* Place on water → rejected.
* Place on a tile that already has a same-faction relic → rejected.
* Save/load round-trip preserves all relic state including `shatter_summary`.

These smoke tests don't count toward the 12 but should live in the file.

---

## §12 Config

The `[powers.relic]` block already exists in `Densitas_P3.md` §11. PR3 adds two render-config fields, in a new `[render.relic]` block to keep render concerns separate from gameplay tuning:

```toml
[powers.relic]
amplitude           = 20.0
place_cooldown      = 30.0
shatter_ratio       = 1.5
shatter_time        = 8.0
attract_radius      = 8
attract_probability = 0.4
initial_count       = 3

[render.relic]
sprite_size_px      = 20     # 16-24 range; 20 is the chosen mid-band
tray_position       = "bottom-right"
tray_layout         = "horizontal"
summary_panel_seconds = 10.0  # auto-dismiss timer
fade_pulse_period   = 1.5    # sec, during place_cooldown
```

`RelicConfig` extends with `sprite_size_px`, `tray_position`, `tray_layout`, `summary_panel_seconds`, `fade_pulse_period`. Defaults match the values above.

---

## §13 PR slicing

PR3 ships as a single PR — it's already the third slice of P3. No further sub-slicing planned.

Order of work inside the PR:

1. **Module + data model.** `densitas/relics.py` with `RelicState`, `Relic`, `ShatterSummary`, `RelicManager` skeleton. No belief wiring yet.
2. **Belief wiring.** `BeliefField.recompute` signature widening + `_scatter_relics`. Tests #5, #6, #10.
3. **Attractor wiring.** `CitizenManager.sync_attractors_from_relics` + `_pick_wander_target` integration. Tests #9, #11.
4. **Shatter rule.** `RelicManager.tick` + `_build_shatter_summary`. Tests #7, #8, #12.
5. **Mutation ops.** `place`/`move`/`retrieve` + validation. Tests #1-#4, smoke tests.
6. **Renderer.** `Renderer.blit_relics` abstract + `PixelRenderer.blit_relics` impl + glyph atlas pre-rasterization at game start.
7. **Shatter animation.** Crack lines + flash + alpha fade, driven by a small per-relic animation state struct.
8. **HUD tray.** `blit_relic_tray` with the 3-slot layout + threat ring.
9. **Summary panel.** Slide-in tween + content render + dismiss handling + tray re-open.
10. **Input.** `R` / `Shift+R` mode state in `main.py`, click handling, mode preview.
11. **Config schema.** `[render.relic]` block + dataclass extension.
12. **Scripture pool additions.** `rhetoric.json` additions for `relic_placed`, `relic_retrieved`, `relic_shattered_loud` per god.
13. **Save/load.** `RelicManager.to_dict` / `from_dict`. Smoke test for round-trip.

Each step lands as one or two commits so the tree stays bisectable. The PR cuts at the end of step 13 with all 12 tests + smoke tests green.

---

## §14 Acceptance criteria

PR3 is done when, in live play:

* Press `R` over a forest tile near a citizen cluster → the First Witness appears, pulses gently, and over the next 30 sim_sec the belief heatmap brightens at that tile.
* Citizens drift toward the relic ~40% of their wander picks. Hungry citizens still go after food first.
* Press `R` again → cycles to the Second Witness slot (the First's slot now shows PLACED). Place that one too.
* Press `Shift+R` then click on the First Witness's tile → it returns to AVAILABLE. Press `R` to redeploy.
* Launch with `--rival-stub-seed 80`; observe rival citizens cluster near the player's relics; if their belief sustains 1.5× the player's at the relic for 8 sec, the relic visibly cracks, flashes, fades out, and a summary panel slides in from the right with all 8 fields populated.
* The tray's SHATTERED slot stays SHATTERED for the rest of the round; clicking it re-opens the summary.

If all six work without a crash and the shatter ceremony reads as "the most important thing that happened this round," PR3 is done.

---

## §15 Open decisions

None at v0.1. All UX questions were resolved 2026-05-22 by Matthew:

* Placement: R-mode + click on map.
* Retrieval: Shift+R then click on placed tile.
* Shatter ceremony: subtle (crack + flash + scripture + summary panel; no time-dilation, no modal).
* Summary screen: slide-in panel, 10-sec auto-dismiss.

If playtest of the slide-in panel feels too brief or too easy to miss, bump `summary_panel_seconds` in config — that's the tuning knob.

---

## §16 Contract / file impact

| Surface                | Owner       | Change                                                                  |
|------------------------|-------------|-------------------------------------------------------------------------|
| `densitas/relics.py`   | new         | `RelicState`, `Relic`, `ShatterSummary`, `RelicManager`                 |
| `densitas/belief.py`   | extended    | `recompute(citizens, relics=None, sim_t=0.0)` + `_scatter_relics`       |
| `densitas/citizen.py`  | extended    | `attractors`, `sync_attractors_from_relics`, `_pick_wander_target` hook |
| `densitas/render.py`   | extended    | `blit_relics` (abstract + pixel) + glyph atlas                          |
| `densitas/hud.py`      | extended    | `blit_relic_tray`, `blit_shatter_panel`                                 |
| `densitas/main.py`     | extended    | `R` / `Shift+R` modes, click routing, summary-panel state machine       |
| `densitas/config.py`   | extended    | `[render.relic]` fields on `RelicConfig`                                |
| `config.toml`          | extended    | `[render.relic]` block                                                  |
| `rhetoric.json`        | extended    | `relic_placed`, `relic_retrieved`, `relic_shattered_loud` per god       |
| `tests/test_relics.py` | new         | 12 tests + smoke tests                                                  |
| `WORKLOG.md` / `TODO.md` / `README.md` | extended | PR3 status, new keybindings, sprite atlas note            |

Total: 1 new module + 1 new test file + 9 modified modules + 3 doc updates.

The Renderer ABC contract grows by 3 methods (`blit_relics`, `blit_relic_tray`, `blit_shatter_panel`) — all stay abstract so the future VectorRenderer fails fast if missing.

---

*Spec ends.*
