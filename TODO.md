# Densitas — TODO

## Design
- [x] ~~Answer the open questions in §13~~ — resolved 2026-05-20.
- [x] ~~Resolve §14 still-open items~~ — resolved 2026-05-20.
- [x] ~~Spec the citizen state machine~~ — done 2026-05-20 in `Densitas_citizens.md`.
- [x] ~~Define the belief-field math precisely~~ — done 2026-05-21 in `Densitas_belief.md`.
- [x] ~~Spec food/forage/hunger~~ — done 2026-05-21 in `Densitas_food.md`. Tile-attribute food, hunger gate, FORAGE/EATING transitions, starvation, DYING-fades-belief.
- [ ] Spec the rival god AI for each personality (Zealot / Steward / Trickster): decision loop, target selection, when to spend belief vs hoard.
- [ ] Define terrain generation: ~~heightmap method~~ (done), biome derivation rules (done), starting-position fairness (open).
- [ ] **Relic spec.** Placement UI (drag from tray? click on map?), visual representation, the shattering animation/sound, retrieval flow.
- [ ] **Relic-shatter summary screen.** When a relic shatters, show: god, relic name, tile, local-belief at shatter, # of player citizens within 8 tiles, # of rival citizens within 8 tiles, time-since-placed, # of times moved.
- [ ] **Rhetoric pool expansion.** Write 6-10 lines per power per voice mode.
- [x] ~~Config schema — citizen / belief / food~~ — done 2026-05-20 / 2026-05-21.
- [ ] **Food tuning iteration.** Default tuning lands equilibrium at ~700-1000 citizens. T3 (1000 threshold) sits *at* the edge — sustained survival reaches it but the curve is slow. If playtest feels T3 too hard, bump biome regens 1.5x OR drop hunger_rate 0.05 -> 0.04. The P3 holy-site / relic boost is the intended path to T3+ via richer local food.

## Art / UX
- [x] ~~Decide art direction~~ — pixel-art active, vector deferred.
- [ ] **VectorRenderer** — implement the alternative draw style. Same `build_world_surface` / `blit_viewport` / `blit_citizens` / `blit_belief_overlay` / `blit_food_overlay` contract.
- [x] ~~Citizen icon resolution~~ — 16-tall pixel humanoid (8 wide).
- [x] ~~**Citizen sprite set**~~ — done 2026-05-20. 8x16 humanoid x 2 factions x 4 facings x 3 frames.
- [ ] **Relic sprite placement on map.** The pixel-art glyphs from `Densitas_relic_glyphs_v1.html` get blitted at 16-24 px on the tile they occupy.
- [ ] **Death-frame sprite.** DYING currently shows IDLE. Add a pale-fade variant; pair the animation with the belief fade introduced in P1.5.
- [ ] **EATING frame.** Currently idle. Small "munch" detail (jaw pixel toggle) would communicate state without a full new sprite.
- [ ] Final HUD pass: settings menu, pause menu, end-of-round screen.

## Prototype P0 — Pixel world (SHIPPED 2026-05-20)
- [x] Project skeleton.
- [x] Tile map data structure.
- [x] Heightmap generation.
- [x] Camera + edge scroll.
- [x] World surface pre-render.
- [x] FPS counter + debug overlay (F3).
- [x] Tests.

## Prototype P1 — Citizens exist (SHIPPED 2026-05-20)
- [x] Citizen state-machine spec.
- [x] Citizen entity + manager + 5 Hz tick.
- [x] Wander behaviour.
- [x] Reproduction (with cooldown).
- [x] Death by lifespan.
- [x] Population HUD.
- [x] 16-tall pixel sprite set.
- [x] Config schema.
- [x] 11 tests.
- [ ] **Walk-frame animation polish** — tie to sub-tile movement progress.
- [ ] **Death frame** — see Art/UX section.

## Prototype P2 — Belief field (SHIPPED 2026-05-21)
- [x] Belief spec (`Densitas_belief.md`).
- [x] `BeliefField` — 64x48 grid per faction, scatter-then-blur, volume-preserving box blur.
- [x] `query`, `dominant_faction`, `total`, `peak`, `grid`.
- [x] Heatmap overlay (`PixelRenderer.blit_belief_overlay`, toggle key `B`).
- [x] HUD belief readout.
- [x] Belief regen accounting (`total(faction)` exposed; no spend yet).
- [x] Config schema (`[belief]` block).
- [x] 15 tests (including 3 new DYING-fade tests from P1.5).
- [ ] **Overlay rebuild perf.** First-build is ~22 ms at 5 Hz on default world (~11% CPU when overlay is on). Optimize via smaller intermediate or per-frame visible-region scale.

## Prototype P1.5 — Food, forage & hunger (SHIPPED 2026-05-21)
- [x] Food spec (`Densitas_food.md`).
- [x] `FoodField` — per-tile food + regen, vectorised. `consume`, `find_nearest`, `query`, `version`.
- [x] Biome regen table (forest / grass / beach / hill / holy; mountain/water/lava/blighted barren).
- [x] Citizen hunger field, hunger accrual, FORAGE/EATING dispatch, starvation→DYING.
- [x] Reproduction gate on `hunger < repro_hunger_threshold` for both partners.
- [x] DYING-fades-belief refinement (fractional amplitude scaled by remaining state_timer; dying_duration 0.5s → 2.0s).
- [x] Food overlay (`PixelRenderer.blit_food_overlay`, toggle key `F`).
- [x] HUD three-segment hunger bar (FED / HUNGRY / STARVING) + percentages.
- [x] Config schema (`[food]` and `[food.biome]` blocks).
- [x] 20 tests.
- [x] Tuning playtest at 30 sim min. Equilibrium ~700-1000 on default seed.
- [x] `food_carried: int = 0` inventory hook on Citizen (unused in P1.5; reserved for future).

## Prototype P2.5 — Fog of war
- [ ] Per-god visibility grid; recompute on relic move and citizen move.
- [ ] Render unseen tiles dimmed; render last-known rival positions as ghost dots.
- [ ] Relic placement constrained to visible tiles from this point on.
- [ ] Rival belief field clipped to visible tiles in the heatmap overlay.

## Prototype P3 — Powers T0–T1 + Relics
- [ ] Power dispatch system: cast queue, validation (tier check, belief check, cooldown), effect application. Uses `belief.query(...)` for per-cast strength.
- [ ] Whisper (inspire).
- [ ] Raise / Lower terrain (need to re-render affected tiles into the world surface AND update FoodField cap+regen).
- [ ] Bless field.
- [ ] **Religious Relics:** placement, retrieval, attractor behavior, belief contribution, shatter when rival belief sustainably dominates.
- [ ] **Holy site food boost.** Tiles within N of a relic get richer food regen (this is the path to T3+).
- [ ] Granary (T3 building) — citizen inventory tier hooked in here. Activate `food_carried`.
- [ ] Scripture log: rhetoric pool wired up; per-cast line picked from `(power, god, mode)` JSON.

## Prototype P4 — Rival god AI
- [ ] Rival faction citizens spawn from rival starting point.
- [ ] Three personality decision loops (Zealot / Steward / Trickster).
- [ ] Belief field per faction; conflict where they overlap (already plumbed in P2).
- [ ] CONVERTED state wired up.

## Prototype P5 — Tiers T2–T4
- [ ] Tempest tier powers (T2): Storm, Earthquake.
- [ ] Cataclysm tier powers (T3): Flood, Volcano, Plague. (Volcano and Plague mutate food field — Plague sets a malus, Volcano blights tiles.)
- [ ] Apocalypse tier powers (T4): The Last Witness, The Final Bite.
- [ ] Holy-site mechanic (T4 requirement).

## Prototype P6 — Win/lose + polish
- [ ] Win condition: rival civilization extinguished OR holy-site apotheosis.
- [ ] Lose condition: player citizens reach 0 AND no relics survive (`belief.total(0) <= eps`).
- [ ] End-of-round summary with the full propaganda log.
- [ ] Save / load (the `*.densitas-save` file format). `FoodField` is a numpy array — trivially serialisable.

## Stretch / never
- [ ] Multiplayer — hot-seat first, then lockstep-deterministic. Parked.
- [ ] Additional gods from the pantheon (Open Hand, Numbering, Empty Throne).
- [ ] Mod support: rhetoric pool, palettes, god kits, food biome table all externally swappable.
