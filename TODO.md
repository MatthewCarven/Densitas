# Densitas — TODO

## Design
- [x] ~~Answer the open questions in §13~~ — resolved 2026-05-20 (see GDD §13).
- [x] ~~Resolve §14 still-open items~~ — resolved 2026-05-20 (art direction pixel-active/vector-deferred, citizens 16-tall pixel, rhetoric hand-written, relic-shatter as summary screen).
- [ ] Spec the citizen state machine: idle / forage / build / flee / convert / die — with the trigger conditions for each transition.
- [ ] Spec the rival god AI for each personality (Zealot / Steward / Trickster): decision loop, target selection, when to spend belief vs hoard.
- [ ] Define the belief-field math precisely: kernel radius, amplitude, grid resolution, recompute cadence. First-pass numbers in GDD, but they need a parameters file before implementation.
- [ ] Define terrain generation: ~~heightmap method~~ (done: multi-octave value noise + vignette), biome derivation rules (done in `world.py`), starting-position fairness (open).
- [ ] **Relic spec.** Placement UI (drag from tray? click on map?), visual representation, the shattering animation/sound, retrieval flow.
- [ ] **Relic-shatter summary screen.** When a relic shatters, show: god, relic name, tile, local-belief at shatter, # of player citizens within 8 tiles, # of rival citizens within 8 tiles, time-since-placed, # of times moved. Numbers go to the log too in parallel — the screen is for the player who wants to keep score.
- [ ] **Rhetoric pool expansion.** Write 6–10 lines per power per voice mode. Hand-written; Matthew reserves the right to move the goalpost later (planning to ask AIs for input on the funny side). Pool format: small JSON/YAML keyed on `(power, god, mode)`.
- [ ] **Config schema** — extend `config.toml` for sim tunables (`reproduction_rate`, `lifecycle_length_days`, `infant_mortality`, `food_to_birth_ratio`, belief-field knobs, tier thresholds). Engine reads and honors.

## Art / UX
- [x] ~~Decide art direction~~ — pixel-art active, vector deferred behind the `Renderer` abstract base class.
- [ ] **VectorRenderer** — implement the alternative draw style using `pygame.draw` primitives. Same `build_world_surface` contract. Switchable via `render.art_style = "vector"` in `config.toml`.
- [x] ~~Citizen icon resolution~~ — 16-tall pixel humanoid (need not be square; 8–12 wide likely).
- [ ] **Citizen sprite set.** Pixel-art 16-tall humanoid in 2 factions × 4 directional facings × 2 idle/walk frames = 16 sprites total. Plus a death/converted state.
- [ ] **Relic sprite placement on map.** The pixel-art glyphs from `Densitas_relic_glyphs_v1.html` get blitted at 16–24 px on the tile they occupy. Possibly with a small "stand" pixel base.
- [ ] Final HUD pass: settings menu, pause menu, end-of-round screen.

## Prototype P0 — Pixel world (SHIPPED 2026-05-20)
- [x] Project skeleton: `densitas/`, `main.py`, `world.py`, `render.py`, `config.py`, `camera.py`, `tests/`.
- [x] Tile map data structure (heightmap-driven, uint8 tile types, 256×192 default).
- [x] Heightmap generation — multi-octave value noise + island vignette.
- [x] Camera with WASD/arrow scroll + edge-of-screen scroll. Clamped to world bounds.
- [x] Render base terrain to a pre-rendered Surface; blit viewport per frame.
- [x] FPS counter, debug overlay (F3 toggle).
- [x] Unit tests for world generation, determinism, tile classification, camera clamp.

## Prototype P1 — Citizens exist
- [ ] Citizen entity (position, needs `(food, shelter, faith)`, faction, faith level, faction id).
- [ ] Wander + forage behavior on the existing tile map (terrain affects move cost).
- [ ] Reproduction at simple thresholds (config-tunable).
- [ ] Population counter in HUD.
- [ ] 16-tall pixel sprite set wired through `PixelRenderer`.

## Prototype P2 — Belief field
- [ ] Belief grid (64×48 to mirror the world's 256×192 at 4-tile sampling) accumulating from citizen positions.
- [ ] Heatmap render as semi-transparent overlay (**off by default; toggle key `B`**).
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
- [ ] **Religious Relics:** placement, retrieval, attractor behavior, belief contribution, shat