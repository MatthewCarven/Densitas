# Densitas — TODO

## Design
- [x] ~~Answer the open questions in §13~~ — resolved 2026-05-20 (see GDD §13).
- [x] ~~Resolve §14 still-open items~~ — resolved 2026-05-20 (art direction pixel-active/vector-deferred, citizens 16-tall pixel, rhetoric hand-written, relic-shatter as summary screen).
- [x] ~~Spec the citizen state machine~~ — done 2026-05-20 in `Densitas_citizens.md` (IDLE / WANDER / MATE / DYING for P1; FORAGE / EATING / SLEEP / FLEE / CONVERTED placeholders).
- [ ] Spec the rival god AI for each personality (Zealot / Steward / Trickster): decision loop, target selection, when to spend belief vs hoard.
- [ ] Define the belief-field math precisely: kernel radius, amplitude, grid resolution, recompute cadence. First-pass numbers in GDD, but they need a parameters file before implementation.
- [ ] Define terrain generation: ~~heightmap method~~ (done: multi-octave value noise + vignette), biome derivation rules (done in `world.py`), starting-position fairness (open).
- [ ] **Relic spec.** Placement UI (drag from tray? click on map?), visual representation, the shattering animation/sound, retrieval flow.
- [ ] **Relic-shatter summary screen.** When a relic shatters, show: god, relic name, tile, local-belief at shatter, # of player citizens within 8 tiles, # of rival citizens within 8 tiles, time-since-placed, # of times moved. Numbers go to the log too in parallel.
- [ ] **Rhetoric pool expansion.** Write 6-10 lines per power per voice mode. Hand-written; Matthew reserves the right to move the goalpost later. Pool format: small JSON/YAML keyed on (power, god, mode).
- [x] ~~**Config schema — citizen section**~~ — done 2026-05-20 (`[citizen]` block in `config.toml`, validated by `CitizenConfig`). Belief-field, food, and tier-tunable knobs still pending.

## Art / UX
- [x] ~~Decide art direction~~ — pixel-art active, vector deferred behind the `Renderer` abstract base class.
- [ ] **VectorRenderer** — implement the alternative draw style using `pygame.draw` primitives. Same `build_world_surface` / `blit_viewport` / `blit_citizens` contract.
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

## Prototype P2 — Belief field
- [ ] Belief grid (64x48 to mirror the world's 256x192 at 4-tile sampling) accumulating from citizen positions.
- [ ] Heatmap render as semi-transparent overlay (off by default; toggle key `B`).
- [ ] Belief regen + spend accounting (no powers yet — just track the number).

## Prototype P2.5 — Fog of war
- [ ] Per-god visibility grid; recompute on relic move and citizen move.
- [ ] Render unseen tiles dimmed; render last-known rival positions as ghost dots.
- [ ] Relic placement constrained to visible tiles from this point on.

## Prototype P3 — Powers T0–T1 + Relics
- [ ] Power dispatch system: cast queue, validation (tier check, belief check, cooldown), effect application.
- [ ] Whisper (inspire).
- [ ] Raise / Lower terrain (need to re-render affected tiles into the world surface).
- [ ] Bless field.
- [ ] **Religious Relics:** placement, retrieval, attractor behavior, belief contribution, shatter when rival belief sustainably dominates.
- [ ] Scripture log: rhetoric pool wired up; per-cast line picked from (power, god, mode) JSON.

## Prototype P4 — Rival god AI
- [ ] Rival faction citizens spawn from rival starting point.
- [ ] Three personality decision loops (Zealot / Steward / Trickster).
- [ ] Belief field per faction; conflict where they overlap.
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
