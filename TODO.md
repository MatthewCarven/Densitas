# Densitas — TODO

## Design
- [x] ~~Answer the open questions in §13~~ — resolved 2026-05-20.
- [x] ~~Resolve §14 still-open items~~ — resolved 2026-05-20.
- [x] ~~Spec the citizen state machine~~ — done 2026-05-20 in `Densitas_citizens.md`.
- [x] ~~Define the belief-field math precisely~~ — done 2026-05-21 in `Densitas_belief.md`.
- [x] ~~Spec food/forage/hunger~~ — done 2026-05-21 in `Densitas_food.md`. Tile-attribute food, hunger gate, FORAGE/EATING transitions, starvation, DYING-fades-belief.
- [ ] Spec the rival god AI for each personality (Zealot / Steward / Trickster): decision loop, target selection, when to spend belief vs hoard.
- [ ] Define terrain generation: ~~heightmap method~~ (done), biome derivation rules (done), starting-position fairness (open). (Raise/Lower mutation pipeline shipped P3 PR2.)
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
- [x] ~~**Death-frame sprite.**~~ — done 2026-05-21. Alpha-fade rather than a new sprite; cheaper and pairs with the existing belief-fade smoothly.
- [x] ~~**EATING frame.**~~ — done 2026-05-21. 4th frame per (faction, facing) with the mouth-outline pixels suppressed; renderer cycles 0 ↔ 3 every 0.4 sim sec.
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
- [x] ~~**Walk-frame animation polish**~~ — done 2026-05-21. Frame cycles on spatial phase `(c.x + c.y) % 1.0` so animation steps with motion, not the clock.
- [x] ~~**Death frame**~~ — done 2026-05-21. `dying_fade` field on Citizen updated each DYING tick; renderer alpha-modulates the IDLE sprite. Pairs with the P1.5 belief fade.

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

## Prototype P3 PR1 — Powers T0 + Bless/Curse (SHIPPED 2026-05-21)
- [x] P3 spec doc (`Densitas_P3.md`). Spec §14 decisions resolved.
- [x] `PowerSystem` — pool, cooldowns, effects, scripture log, dispatch table.
- [x] T0 Inspire (real), Calm (stub), Hunger Pang (rival-faction stub).
- [x] T1 Bless / Curse — active-effect machinery; food.recompute folds multipliers.
- [x] Rhetoric module + `rhetoric.json` (Open Eye lines for 7 powers + 2 relic events).
- [x] Cast preview render (AoE circle + status chip with green/amber/red tint).
- [x] HUD pool bar replaces static total; cooldown row with 7 power icons; scripture log overlay.
- [x] Input bindings (1-7 mode select, LMB cast, RMB/ESC cancel).
- [x] `--rival-stub-seed N` debug flag for live multi-faction testing.
- [x] Config schema (`[powers]` and `[powers.relic]` blocks).
- [x] 20 P3 tests (74 total in suite, all pass).
- [x] `CastReceipt` seam left open for P5 counter-cast partial-cancel.

## Prototype Cast Queue — Click-chain Raise/Lower (SHIPPED 2026-05-21)
- [x] `Densitas_queue.md` spec doc.
- [x] `QueuedCast` dataclass + `PowerSystem.queues` dict + `_is_queueable`.
- [x] `cast_or_queue` entry point; `drain_queues` in main-loop sim step.
- [x] `cancel_queued_at` (RMB on queued tile, refunds) + `clear_queue` (`C` key).
- [x] `can_cast(..., skip_cooldown=True)` for the enqueue validation path.
- [x] `_dispatch_queued` — re-validates tile; on invalid emits `queued_invalid` scripture line, burns cooldown, no refund.
- [x] `Renderer.blit_cast_queue` (abstract + pixel) — amber ▲ / brown ▼ chevrons with 1-9 position numbers.
- [x] HUD: queue-count superscript on R/L cooldown icons (caps at 9+).
- [x] main.py: LMB routed to `cast_or_queue`; RMB tries cancel-first; `C` clears.
- [x] Debug overlay shows `Queue: R x N (Ns)  L x M (Ms)`.
- [x] `queue_cap` config field (default 16).
- [x] `queued_invalid` rhetoric pool entries for Open Eye.
- [x] 7 new tests (test_25-test_31), 85 total in suite.

## Prototype P3 PR2 — Raise / Lower terrain (SHIPPED 2026-05-21)
- [x] `densitas/world.py :: mutate_tile(world, food, repaint_cb, tx, ty, new_tile)`.
- [x] `Renderer.repaint_tile(world_surface, world, tx, ty)` — abstract + pixel impl.
- [x] PowerSystem `_dispatch_raise` / `_dispatch_lower` call into mutate_tile (PR1 stub replaced; main.py injects the callback).
- [x] Heightmap update — canonical band midpoint per tile via `heightmap_for()`.
- [x] Food field cap+regen recomputed from biome for the new tile.
- [x] Drown rule — citizens on a newly-unwalkable tile transition to DYING via `CitizenManager.drown_at()`.
- [x] Tests 12-15 from spec §12 (live as test_21-test_24, 24 P3 tests total).

## Prototype P3 PR3 — Religious Relics
- [ ] `densitas/relics.py` — `Relic`, `RelicManager`, `RelicState` (AVAILABLE/PLACED/SHATTERED).
- [ ] `BeliefField.recompute(citizens, relics=None, sim_t=0.0)` + `_scatter_relics` with linear fade-in over place_cooldown.
- [ ] Citizen attractor list + `_pick_wander_target` integration (~40% probability, hunger trumps).
- [ ] Shatter rule: rival belief > 1.5x player belief sustained for 8 sec at the tile.
- [ ] Tray UI in HUD (3 slots; AVAILABLE/PLACED/SHATTERED states).
- [ ] `R` / `Shift+R` mode select; click to place/move/retrieve.
- [ ] `blit_relics(screen, relics, cam_x, cam_y)` using the existing `Densitas_relic_glyphs_v1.html` glyphs.
- [ ] 10 P3 PR3 tests (spec §12 #19-28).

## Prototype P3.5 — Spring + Curse-flight
- [ ] Spring (T1) — fresh-water tile sub-type increasing adjacent carrying capacity.
- [ ] Curse-citizen-flight — citizens in cursed land flee outward (overlaps with future FLEE state).
- [ ] Pool soft cap (`5000 + 10 * pop`) if banking has become trivial by then.
- [ ] Density-bonus regen factor for the belief pool (peak/avg ratio).

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
