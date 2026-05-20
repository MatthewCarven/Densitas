# Densitas — TODO

## Design
- [x] ~~Answer the open questions in §13~~ — resolved 2026-05-20 (see GDD §13).
- [x] ~~Resolve §14 still-open items~~ — resolved 2026-05-20 (art direction pixel-active/vector-deferred, citizens 16-tall pixel, rhetoric hand-written, relic-shatter as summary screen).
- [x] ~~Spec the citizen state machine~~ — done 2026-05-20 in `Densitas_citizens.md` (IDLE / WANDER / MATE / DYING for P1; FORAGE / EATING / SLEEP / FLEE / CONVERTED placeholders).
- [x] ~~Define the belief-field math precisely~~ — done 2026-05-21 in `Densitas_belief.md`. Kernel: 2 passes 3-wide box blur. Grid 64x48. Recompute at citizen tick.
- [ ] Spec the rival god AI for each personality (Zealot / Steward / Trickster): decision loop, target selection, when to spend belief vs hoard.
- [ ] Define terrain generation: ~~heightmap method~~ (done: multi-octave value noise + vignette), biome derivation rules (done in `world.py`), starting-position fairness (open).
- [ ] **Relic spec.** Placement UI (drag from tray? click on map?), visual representation, the shattering animation/sound, retrieval flow.
- [ ] **Relic-shatter summary screen.** When a relic shatters, show: god, relic name, tile, local-belief at shatter, # of player citizens within 8 tiles, # of rival citizens within 8 tiles, time-since-placed, # of times moved. Numbers go to the log too in parallel.
- [ ] **Rhetoric pool expansion.** Write 6-10 lines per power per voice mode. Hand-written; Matthew reserves the right to move the goalpost later. Pool format: small JSON/YAML keyed on (power, god, mode).
- [x] ~~**Config schema — citizen section**~~ — done 2026-05-20 (`[citizen]` block in `config.toml`, validated by `CitizenConfig`).
- [x] ~~**Config schema — belief section**~~ — done 2026-05-21 (`[belief]` block, validated by `BeliefConfig`). Food and tier-tunable knobs still pending.

## Art / UX
- [x] ~~Decide art direction~~ — pixel-art active, vector deferred behind the `Renderer` abstract base class.
- [ ] **VectorRenderer** — implement the alternative draw style using `pygame.draw` primitives. Same `build_world_surface` / `blit_viewport` / `blit_citizens` / `blit_belief_overlay` contract.
- [x] ~~Citizen icon resolution~~ — 16-tall pixel humanoid (8 wide).
- [x] ~~**Citizen sprite set**~~ — done 2026-05-20. Pixel-art 8x16 humanoid in 2 factions x 4 facings x 3 frames per faction. Death/converted/forage frames pending.
- [ ] **Relic sprite placement on map.** The pixel-art glyphs from `Densitas_relic_glyphs_v1.html` get blitted at 16-24 px on the tile they occupy.
- [ ] Final HUD pass: settings menu, pause menu, end-of-round screen.

## Prototype P0 — Pixel world (SHIPPED 2026-05-20)
- [x] Project skeleton: `densitas/`, `main.py`, `world.py`, `render.py`, `config.py`, `camera.py`, `tests/`.
- [x] Tile map data structure (heightmap-driven, uint8 tile types, 256x192 default).
- [x] Heightmap generation — multi-octave value noise + island vignette.
- [x] Camera with WASD/arrow scroll + edge-of-screen scroll. Clamped to world bounds.
- [x] Render base terrain to a pre-rendered Surface; blit viewport per frame.
- [x] FPS counter, debug overlay (F3 toggle).
- [x] Unit tests for world generation, determinism, tile classification, camera clamp.

## Prototype P1 — Citizens exist (SHIPPED 2026-05-20)
- [x] **Citizen state-machine spec** — `Densitas_citizens.md`. Lifecycle, reproduction, sprite contract, HUD wiring.
- [x] **Citizen entity** — `densitas/citizen.py`: `Citizen` dataclass with id, faction, position, state, age, lifespan, repro cooldown, facing, home/target. `CitizenManager` owns the population, ticks at 5 Hz.
- [x] **Wander behaviour** — random walk anchored to spawn point, slide-along-axis collision against non-walkable tiles. No pathfinding (intentional).
- [x] **Reproduction** — same-faction adjacency (Chebyshev <= `repro_radius`), maturity check, cooldown after MATE. Child spawned at nearby walkable tile.
- [x] **Death** — Gaussian-truncated lifespan, DYING state, removal after `dying_duration`.
- [x] **Population counter in HUD** — `densitas/hud.py`: bottom-left card with population, tier name, pip indicators T0..T4.
- [x] **16-tall pixel sprite set** — 8x16 humanoid, 4 facings x 3 frames per faction (Open Eye + Maw palettes). Blitted on top of world surface every frame.
- [x] **Config schema** — `[citizen]` section in `config.toml`. Tunables: initial_population, spawn_radius, maturity_age, lifespan, repro_radius, repro_cooldown, wander knobs, tick_hz.
- [x] **Tests** — `tests/test_citizen.py`: 11 tests, all passing.
- [ ] **Forage** — placeholder state in the FSM. Add when food entities exist (P1.5 or P2).
- [ ] **Walk-frame animation polish** — currently flips between walk-A/walk-B every 0.25 sim sec; consider tying to sub-tile movement progress instead.
- [ ] **Death frame** — DYING currently shows the idle frame. Add a fading sprite variant.

## Prototype P2 — Belief field (SHIPPED 2026-05-21)
- [x] **Belief spec** — `Densitas_belief.md`. Grid, kernel, cadence, query API, overlay, contract.
- [x] **Belief grid** — 64x48 (4-tile sampling of 256x192 world) per faction. `densitas/belief.py`, scatter-then-blur with 2 passes of 3-wide separable box blur. Volume-preserving so `total == population`.
- [x] **`BeliefField.query(tx, ty, faction)`** — per-tile lookup primitive. Hooks for P3 power-cast strength scaling.
- [x] **`BeliefField.dominant_faction(tx, ty)`** — stubbed for P3 relic-shatter trigger and P4 CONVERTED state.
- [x] **Heatmap overlay** — `PixelRenderer.blit_belief_overlay`. Per-faction tint, alpha by magnitude. Cached by `belief.version`. Toggle key `B`. Off by default.
- [x] **HUD belief readout** — bottom-left card shows BELIEF total in cyan next to POPULATION.
- [x] **Belief regen accounting** — `total(faction)` exposed; no spend ledger yet (P3 introduces it).
- [x] **Config schema** — `[belief]` block in `config.toml`. Tunables: grid_w, grid_h, amplitude, blur_passes, blur_radius, recompute_hz, overlay_alpha_max.
- [x] **Tests** — `tests/test_belief.py`: 13 tests, all passing.
- [ ] **Overlay rebuild perf.** First-build cache miss is ~22 ms (64x48 -> 4096x3072 nearest-scale). At 5 Hz that's ~11% CPU when overlay is on. Optimize by either: smaller scaled intermediate, or per-frame visible-region scale only.

## Prototype P2.5 — Fog of war
- [ ] Per-god visibility grid; recompute on relic move and citizen move.
- [ ] Render unseen tiles dimmed; render last-known rival positions as ghost dots.
- [ ] Relic placement constrained to visible tiles from this point on.

## Prototype P3 — Powers T0–T1 + Relics
- [ ] Power dispatch system: cast queue, validation (tier check, belief check, cooldown), effect application. Uses `belief.query(...)` for per-cast strength.
- [ ] Whisper (inspire).
- [ ] Raise / Lower terrain (need to re-render affected tiles into the world surface).
- [ ] Bless field.
- [ ] **Religious Relics:** placement, retrieval, attractor behavior, belief contribution, shatter when rival belief sustainably dominates (uses `belief.dominant_faction`).
- [ ] Scripture log: rhetoric pool wired up; per-cast line picked from (power, god, mode) JSON.

## Prototype P4 — Rival god AI
- [ ] Rival faction citizens spawn from rival starting point.
- [ ] Three personality decision loops (Zealot / Steward / Trickster).
- [ ] Belief field per faction; conflict where they overlap (already plumbed in P2).
- [ ] CONVERTED state wired up: when citizen sits long enough in opposing dominant field.

## Prototype P5 — Tiers T2–T4
- [ ] Tempest tier powers (T2): Storm, Earthquake.
- [ ] Cataclysm tier powers (T3): Flood, Volcano, Plague.
- [ ] Apocalypse tier powers (T4): The Last Witness, The Final Bite.
- [ ] Holy-site mechanic (T4 requirement).

## Prototype P6 — Win/lose + polish
- [ ] Win condition: rival civilization extinguished OR holy-site apotheosis.
- [ ] Lose condition: player citizens reach 0 AND no relics survive.
- [ ] End-of-round summary with the full propaganda log.
- [ ] Save / load (the `*.densitas-save` file format).

## Stretch / never
- [ ] Multiplayer — hot-seat first, then lockstep-deterministic. Parked.
- [ ] Additional gods from the pantheon (Open Hand, Numbering, Empty Throne).
- [ ] Mod support: rhetoric pool, palettes, god kits all externally swappable.
