## 2026-05-21 (P1 polish ship) — Walk cycle, DYING fade, EATING munch

The "open from P1" polish bucket cleared. Three small visual improvements; each one shows up immediately during playtest without changing any game mechanic.

**What landed:**

- `densitas/citizen.py` — `Citizen.dying_fade: float = 1.0` field. Updated in the DYING tick branch: `c.dying_fade = max(0.0, c.state_timer / cfg.dying_duration)`. Frozen at 1.0 for all non-DYING citizens. No transition-site changes needed — the existing default carries through to the first DYING tick where it gets the proper ramp.
- `densitas/render.py` — three changes inside the PixelRenderer:
  - Walk-frame cycle is now **spatial**: `phase = (c.x + c.y) % 1.0` → `frame = 1 if phase < 0.5 else 2`. Each tile travelled = one step cycle, diagonals included. Replaces the prior `(int(sim_time / 0.25) + c.id) & 1` clock-driven toggle. Frame-rate independent and visually correct: when a citizen pauses, their feet stop.
  - DYING render path is new — alpha-modulates the IDLE sprite by `c.dying_fade`. Uses `sprite.copy() + set_alpha()` (one copy per DYING citizen per render frame; cheap at the expected count). The sprite ghosts out over the 2 s dying_duration in lockstep with the belief-field fade.
  - EATING render path is new — alternates between frame 0 (mouth closed, idle pose) and frame 3 (mouth open) every 0.4 sim sec keyed on `int(sim_time / 0.4) + c.id` so individual citizens chew out of phase.
- `densitas/render.py :: _paint_citizen` — accepts `frame=3` as the "mouth open" variant. The 4 mouth-outline pixels (SOUTH/EAST/WEST facings) are dropped; NORTH-facing isn't shown from the front so the accent stays. Frame 3 reuses the idle leg layout. Sprite catalog grew from 24 to 32 keys (2 factions × 4 facings × 4 frames).
- `tests/test_citizen.py` — `test_dying_fade_decays_over_dying_duration` (also wired into the `__main__` runner). After 5 ticks of 0.2s with dying_duration=2.0, fade should sit ~0.5; after 9 ticks, ~0.1.

**Test results:** 86/86 pass (8 P0 + 12 P1 + 15 P2 + 20 P1.5 + 31 P3 PR1+PR2+Queue). P1 grew by 1.

**Smoke test:** Headless. Built renderer with default config, confirmed all 32 sprite keys filled. Forced five citizens into IDLE / WANDER / EATING / DYING / FORAGE simultaneously and rendered at sim_time=1.0 and sim_time=1.4 to flex the EATING alternation — no crashes, alpha-fade with dying_fade=0.5 + skip-render with dying_fade=0.0 both clean.

**No key changes** — pure visual polish. Players will notice but the cheatsheet stays the same.

**Up next:** Either PR3 Religious Relics (finish P3) or back to the Menu PR. Both are gated on Matthew's call.

---

## 2026-05-21 (Cast Queue ship) — Click-chain Raise/Lower

Cast Queue shipped — the player can rapid-click Raise/Lower tiles and the engine drip-feeds them through the existing 2 s cooldown. Five-tile coastline that used to be five separate clicks separated by frustrating waits is now five clicks in a row + ten seconds of watching the surface repaint.

**What landed:**

- `densitas/powers.py` — `QueuedCast` dataclass; `PowerSystem.queues: dict[(faction, kind), list[QueuedCast]]`; `cast_or_queue()` entry point (immediate-fire if ready AND queue empty, else enqueue); `drain_queues()` called from main-loop after `tick()`; `cancel_queued_at(tx, ty, kind, faction)` for surgical RMB cancel; `clear_queue(kind, faction)` for `C`-key bulk clear; `_dispatch_queued()` that re-validates the tile (burns cooldown silently if invalid, with `queued_invalid` scripture line, no refund); `_is_queueable()` + `QUEUEABLE_KINDS` frozenset (Raise+Lower only — extending is one-line).
- `densitas/powers.py` — `can_cast(*, skip_cooldown=False)` keyword arg so enqueue can validate tier / pool / bounds / tile while knowing the cooldown is what triggered the queue path.
- `densitas/render.py` — `Renderer.blit_cast_queue()` abstract + `PixelRenderer` impl. Amber ▲ for queued Raise, brown ▼ for queued Lower, with a 1-9 position number in the corner of each chevron. Drawn over citizens, under the cast preview.
- `densitas/hud.py` — queue-count superscript on the R/L cooldown icons. Caps at 9 visually with a "+" suffix when the actual queue is longer.
- `densitas/main.py` — LMB on a queueable mode routes to `cast_or_queue` instead of `cast`. RMB tries `cancel_queued_at` first; only falls through to mode-cancel if there's no queued tile under the cursor. `C` clears the queue for the current mode (no-op outside Raise/Lower). `drain_queues` called from the sim step right after `tick`. Debug overlay grows a "Queue: R x N (Ns)  L x M (Ms)" line.
- `densitas/config.py` + `config.toml` — `queue_cap` field on `PowerConfig` (default 16).
- `rhetoric.json` — `queued_invalid` block for Open Eye with consecration / doctrinal / ritual lines. The line shows in the scripture log when a queued cast's tile changed before dispatch — "The rite was answered before it was spoken."
- `tests/test_powers.py` — 7 new tests (test_25-test_31): ready-fires-immediately, cooling-enqueues-and-debits, drain-pops-one-per-cleared-cooldown, cancel-refunds, clear-refunds-sum, queued-invalid-burns-and-logs, queue-cap-blocks-overflow. Uses the `_wire_mutate_tile` helper from PR2.

**Test results:** 85/85 pass (8 P0 + 11 P1 + 15 P2 + 20 P1.5 + 24 P3 PR1+PR2 + 7 Queue). All 31 P3 tests run in ~0.4 s.

**Smoke test:** Headless. Four rapid `cast_or_queue` clicks on adjacent GRASS tiles → 1 immediate fire (pool 200 → 195) + 3 queued (pool 195 → 180). Tick+drain loop for 10 sim sec → drains at t=2.2 / 4.4 / 6.6 sec exactly as the 2 s cooldown predicts. All four tiles end as FOREST. Cancel a specific queued tile → pool refunds +5 precisely. Clear-queue on remaining 2 → pool refunds +10 precisely.

**Diversion from the menu PR.** `Densitas_menu.md` was written and signed off before Matthew playtested PR2 and felt the rapid-Raise/Lower ergonomic pain. The menu PR is paused — the spec stays in the repo, implementation will pick back up after Queue ships. Tracked in tasks.

**Edit-tool lessons holding.** Re-used the patcher-script pattern from the PR2 recovery — no Edit calls on existing files, only Write to outputs + Python substring patcher in bash + atomic-rename + SHA verify. All eight code-file deploys hit OK on first try. One test assertion needed a fix (test_30 didn't account for pool regen during the 12-step cooldown tick); fixed with a second patcher pass and re-deploy.

**Up next:** Either back to the Menu PR (the spec is sitting there ready to implement), or PR3 (Religious Relics) if Matthew wants to push P3 to feature-complete first. Both are gated on Matthew's call.

---

## 2026-05-21 (P3 PR2 ship) — Raise / Lower terrain + drown rule

P3 PR2 shipped — the player can now sculpt land.

**What landed:**

- `densitas/world.py` — `mutate_tile(world, food, repaint_cb, tx, ty, new_tile)`. Single seam where tile + heightmap + food cap/regen/food update together; the renderer repaint runs inside as a callback. Returns `True` only on a real change so the caller can skip drown / log side effects. Added `is_walkable_tile()` + `WALKABLE_TILE_IDS` (mirrors `citizen.py`'s `WALKABLE_TILES` so world.py can answer the drown question without importing citizen) and `heightmap_for()` (canonical 0..1 band midpoint per tile).
- `densitas/citizen.py` — `CitizenManager.drown_at(tx, ty, dying_duration)`. Idempotent: skips citizens already in DYING. The existing 2s DYING-fade-belief refinement (P1.5) handles the visual + belief decay for free.
- `densitas/render.py` — `Renderer.repaint_tile()` abstract method + `PixelRenderer` impl. Uses the same deterministic hash as `build_world_surface` so the variant choice for `(tx, ty, tile_id)` stays stable across mutations.
- `densitas/powers.py` — dropped the "stubbed for PR1" comments on `_dispatch_raise` / `_dispatch_lower`; both now call the injected `_mutate_tile` callback. No-callback case stays a quiet no-op (still charges the cast per the "dispatch failure charges" rule).
- `densitas/main.py` — wires the `_mutate_tile_cb` closure into `PowerSystem(mutate_tile=...)`. The closure captures world / food / renderer / world_surface / citizen_mgr, calls `world.mutate_tile`, then runs the drown rule if the new tile is unwalkable. Caption bumped to "Densitas - P3 PR2".
- `tests/test_powers.py` — 4 new tests (test_21..test_24) covering spec §12 #12–15: raise GRASS→FOREST updates everything; raise on MOUNTAIN fails with reason; two Lowers walk GRASS→BEACH→WATER and zero the food cap/regen; lower-into-water drowns a citizen and is idempotent.

**Test results:** 78/78 pass (8 P0 + 11 P1 + 15 P2 + 20 P1.5 + 24 P3 PR1+PR2). All 24 P3 tests run in ~0.22 s.

**Smoke test:** Headless `World.generate` + `mutate_tile(GRASS → FOREST)` + `repaint_tile` round-trip works end-to-end. Food cap moves 0.8 → 1.0 (FOREST biome), `is_walkable_tile` returns True for the new tile, drown_at on an empty tile returns 0.

**Edit-tool truncation incident — recovered.** First pass tried to land the PR2 edits via the Edit tool. Every file ended up at its *original* byte count with the additions inserted but the tail content silently lost — same shape of failure the [[feedback-densitas-mount]] note warned about, except it manifested in `/outputs` not the project mount. Recovered by extracting originals from `git show HEAD:` into `/tmp/restore/`, running a deterministic Python substring-patcher (`outputs/patch_pr2.py`), then atomic-renaming the patched files into the project. **Conclusion:** for files >10 KB in this session's mount stack, prefer Write (full file) over Edit (substring). The patcher script is kept under `/outputs` for replay if PR3 hits the same pothole.

**Up next (PR3):** Religious Relics. `densitas/relics.py` new module; `BeliefField.recompute(..., relics=None, sim_t=0.0)` + `_scatter_relics` with linear fade-in over place_cooldown; citizen attractor list + `_pick_wander_target` integration; shatter rule; tray UI; `R` / `Shift+R` mode select; 10 P3 PR3 tests (spec §12 #19–28). With PR1 + PR2 + PR3 done, P3 is feature-complete.

---

## 2026-05-21 (P3 PR1 ship) — Powers T0–T1 + Bless/Curse

P3 PR1 shipped — the player-verb layer is live.

**Spec resolved (with Matthew):** §14 decisions stamped. Spring deferred to P3.5, rival-stub flag included, pool soft-cap parked as `# TODO(P5)`, counter-cast `CastReceipt` seam kept open, Curse-flight also deferred to P3.5.

**What landed:**

- `densitas/powers.py` (new, 17.3 KB) — `PowerKind`, frozen `PowerSpec` registry, `ActiveEffect`, `ScriptureEntry`, `CastReceipt`, `PowerSystem` (pool / cooldowns / effects / scripture log). Dict-of-callables dispatch table — each new power kind is one registration line. `effective_food_regen()` folds Bless/Curse multipliers on top of base regen.
- `densitas/rhetoric.py` (new) + `rhetoric.json` (4.3 KB) — JSON pool keyed on `(power, god, voice_mode)`. Weighted mode rotation (70/20/10) + no-immediate-repeat. Open Eye lines for Inspire/Calm/HungerPang/Bless/Curse/Raise/Lower/relic_placed/relic_shattered; Maw lines deferred to P4.
- `densitas/food.py` — `recompute(dt, effects=None)` folds active Bless/Curse on top of base regen each tick (lazy import to break the cycle with powers.py).
- `densitas/citizen.py` — `inspire_citizen()`, `find_nearest_other_faction()`, `spawn_rival_stub()`, `inspire_bias_until` field on Citizen so `_pick_wander_target` respects the bias until arrival or 10 sim sec.
- `densitas/config.py` + `config.toml` — `PowerConfig` + `RelicConfig`, `[powers]` and `[powers.relic]` blocks. `k_tier` parsed list→tuple.
- `densitas/render.py` — `blit_cast_preview()` (abstract + pixel impl). AoE circle + colour-tinted status chip (green ready / amber cooling / red blocked).
- `densitas/hud.py` — pool bar replaces the old static total readout; cooldown row with 7 power icons (greyed if tier-locked, amber numeric countdown if cooling, accent-coloured if ready, parchment ring if active mode); scripture log overlay top-right with 6-sec alpha fade.
- `densitas/main.py` — number keys 1-7 select mode, LMB casts, RMB/ESC cancels. Mouse→tile via `cam + ts // ts`. Boot now wires PowerSystem and Rhetoric. `--rival-stub-seed N` spawns N faction-1 citizens at `(world.w * 3/4, world.h/2)` for live multi-faction testing before P4.
- `tests/test_powers.py` (new, 20 tests).
- `Densitas_P3.md` §14 — decisions stamped to "Resolved".

**Bugs caught in smoke that didn't reach the tests:**

- Off-by-one in `f"need T{spec.tier}"` reason string — display tier is `spec.tier - 1` because tier_for indexes 1=T0.
- Same off-by-one in `k_tier[spec.tier]` indexing — `k_tier` is 0..4 over T0..T4, so `kt_idx = max(0, min(len-1, spec.tier - 1))`.

Both caught and fixed before staging. test_14 (concrete-reason strings) and test_04 (need-T1 display) would have caught these on first run; the smoke test caught them first.

**Test results:** 74/74 pass (8 P0 + 11 P1 + 15 P2 + 20 P1.5 + 20 P3). Headless main.main() boots, allocates everything, exits clean.

**Files staged via atomic-rename through /tmp:** all 10 (powers.py, rhetoric.py, rhetoric.json, food.py, citizen.py, config.py, config.toml, render.py, hud.py, main.py) + test_powers.py + Densitas_P3.md §14 patch. Each SHA-verified after sync.

**Up next (PR2):** Raise/Lower terrain. World tile + heightmap mutation, FoodField cap/regen recomputed from new biome, world-surface tile repaint, drown rule for newly-water tiles. Tests 12-15 from spec §12.

---

# Densitas — Worklog

## 2026-05-20 — initial design session

First substantive design pass. Folder was empty going in; no prior session documents existed despite the project instructions hinting at a previous discussion. Started from the brief.

**Directional choices (with Matthew):**

- Top-down god view (classic Populous shape).
- Belief economy: population thresholds unlock power *tiers*; per-cast strength scales with current local density.
- Rival god as the opposing force (one to start).
- Python + pygame for the eventual prototype.

**Design pivot taken without explicit ask:** leaned into the name *Densitas* (Latin: density) to make local population density mechanically meaningful, not just total population. Belief is a 2D scalar field, not a global mana bar. This is the central twist that separates Densitas from Populous and ties straight back to the brief's "belief determined by amount of citizens" — citizens *are* the field.

**Produced:**

- `Densitas_GDD.md` — full game design document, v0.1.
- `Densitas_Powers.md` — per-power spec sheet across all five tiers (Whisper / Blessing / Tempest / Cataclysm / Apocalypse), with cost, AoE, scaling, cooldowns, counters.
- `Densitas_HUD_mockup.html` — annotated SVG mockup of the proposed HUD.
- `TODO.md` — prioritized backlog.

**Open questions captured in GDD §13** — belief decay, reproduction pacing, heatmap default state, rival field visibility, citizen control granularity, multiplayer scope. Don't need to answer these to start the P0 prototype.

## 2026-05-20 (later) — second design pass

Matthew walked through the §13 open questions. All folded into the GDD and powers spec (now §13 *Resolved decisions* with the smaller §14 *Still open* set).

**Decisions:** belief = no time-decay; reproduction speed config-tunable; heatmap overlay off by default toggleable; fog of war at P2.5; nudge-only citizen control via Whispers + Religious Relics; 5 Hz logic / 60 Hz render; multiplayer parked.

**New mechanic: Religious Relic.** Each god gets 3 to start (4 at T3, 5 at T4). Placed anywhere visible. Radiate belief like a ~20x citizen and passively attract player citizens. Shatter when rival belief dominates the tile. *This is the central control verb of the game.*

**Tone expansion.** Added a propaganda/rhetoric section to GDD §10. Every divine act gets a reverent over-confident scripture-log line. *"The unworthy among us were called home."*

## 2026-05-20 (audit) — discovered mount truncation; remediated

Matthew shared the flaky-mount rules: stage in sandbox, atomic-rename, verify size + SHA. Audit found GDD/Powers/TODO/WORKLOG all truncated mid-write from earlier `Edit`-tool calls. Rebuilt full v0.2 content in `/sessions/<id>/mnt/outputs/`, atomic-renamed into the project folder with `cp -> sync -> mv -f .tmp -> verify`. All four files recovered on first attempt under the new pattern.

**Rule of thumb going forward:** treat this mount like a flaky network share. No incremental edits via the Edit tool against this folder. Whole-file writes only, through the staging pattern.

## 2026-05-20 (lore + relic art) — pantheon and glyphs

- `Densitas_relic_glyphs_v1.html` — programmatically-generated pixel-art glyphs for the two starting gods. **The Open Eye** (player; celestial; parchment+cyan; almond eye + rays) and **The Maw** (rival; chthonic; bone+blood; downward arc + fangs). 32x32 native, rendered at 32/96/192/384 px.
- `Densitas_lore_pantheon.md` — Office-Pantheon format (credit: Gemini, via Matthew). Full theology for the Open Eye and the Maw, plus three sketched stretch gods (The Open Hand, The Numbering, The Empty Throne) and heresies/cults. Each god has a tenet, a voice mode for the scripture log, and a *failure mode the rhetoric protects against* — the propaganda's actual job.
- `Densitas_Powers.md` v0.3 — Rhetoric pool expanded with three voice modes (consecration / doctrinal / ritual-procedural) and per-god variant lines for the same power. Implementation note: small JSON/YAML data file keyed on `(power, god, mode)` for easy hand-editing.

## 2026-05-20 (P0 ship) — Pixel world

P0 milestone shipped. Tile map, terrain generation, scrollable camera, debug overlay, headless smoke-test verified.

**Decisions folded in before coding:**

- **Art direction** — pixel-art active, vector deferred behind a `Renderer` abstract base class with `build_world_surface(world)` and `blit_viewport(...)` as the contract. Swap is one line in `config.toml` once `VectorRenderer` exists.
- **Citizen icon resolution** — 16-tall pixel humanoid (need not be square). Slated for P1.
- **Rhetoric pool** — hand-written. Matthew reserves the right to move the goalpost later (planning to get AI input on the funny side).
- **Relic shatter feedback** — simple summary screen with the actual numbers, for the player who wants to keep score. The propaganda is for the log; the numbers are for the screen. Two registers in the same game.

**Code shipped:**

- `densitas/__init__.py`, `densitas/main.py`, `densitas/config.py` (tomllib + tomli fallback), `densitas/world.py` (multi-octave value noise + island vignette + vectorized tile classification), `densitas/camera.py` (WASD + arrow + edge-scroll, normalized diagonals), `densitas/render.py` (`Renderer` ABC + `PixelRenderer` with 4 procedural variants per tile).
- `config.toml` (all tunable parameters; default world 256x192, viewport 1280x720, tile_size 16).
- `tests/test_world.py` — 8 tests covering generation, determinism, tile-from-height partition, camera clamp, max bounds.
- `README.md`, `requirements.txt`.

**Sandbox verification:**

- All 8 unit tests pass.
- Headless smoke test (SDL `dummy` driver): world generates in ~20 ms (256x192); pixel renderer builds in <1 ms; pre-rendered world surface (4096x3072 px) builds in ~70 ms.

## 2026-05-20 (pygame-ce + git init + README polish)

Switched dependency from upstream `pygame` to the community fork `pygame-ce`. Both ship as `import pygame`, so no code changes were needed beyond `requirements.txt` and a README note explaining `pygame.IS_CE` and the can't-coexist constraint.

Matthew initialised the git repository himself (out-of-session, to avoid sandbox git-lock issues). Root commit `600343c` shipped clean. README rewritten with embedded `docs/` PNG assets (world thumbnail, both god glyphs at 32 px and 256 px), Status table tracking P0-P6, Project layout tree, Tone section.

## 2026-05-20 (P1 ship) — Citizens exist

P1 milestone shipped. The world is no longer empty.

**Decisions folded in before coding:**

- **Citizens are never directly selected.** No click-to-order verb. All influence flows through Whispers and Religious Relics (P3). Load-bearing — see `Densitas_citizens.md` §1.
- **No food in P1.** Reproduction is pure demographics (adjacency + maturity + cooldown). Resource pressure is P1.5 at earliest; let playtest tell us whether unconstrained growth is actually a problem.
- **No pathfinding, ever.** Wander uses straight-line + project-onto-walkable-axis. Good enough for a wandering simulation; revisit only if P3 relic-pull behaviour reveals a real problem.
- **`Renderer` ABC extended, not replaced.** `blit_citizens` is now part of the contract. VectorRenderer (TODO) inherits this surface area; PixelRenderer paints 8x16 humanoids with 4 facings x 3 frames per faction.

**Code shipped:**

- `Densitas_citizens.md` (v0.1, 11429 bytes) — full spec: states, transitions, data model, reproduction math, sprite/HUD contracts, what's deliberately omitted, contract with the rest of the codebase.
- `densitas/citizen.py` (12810 bytes) — `Citizen` dataclass, `CitizenManager` with 5 Hz tick, `tier_for()` helper, `Facing` and `CitizenState` enums, `WALKABLE_TILES` constant.
- `densitas/hud.py` (3133 bytes) — bottom-left card: population, tier name, T0-T4 pip indicators, "+N for next tier" hint.
- `densitas/render.py` (rev, 11564 bytes) — adds `blit_citizens` abstract + PixelRenderer implementation. 8x16 procedural pixel humanoid per (faction, facing, frame).
- `densitas/main.py` (rev, 4952 bytes) — wires citizen sim into the game loop with a fixed-timestep accumulator (5 Hz logic regardless of render framerate). Debug HUD includes population. Window title bumped to "Densitas — P1".
- `densitas/config.py` (rev, 2045 bytes) — adds `CitizenConfig` frozen dataclass; `Config` carries `citizen`.
- `config.toml` (rev, 2190 bytes) — adds `[citizen]` block. 14 tunables.
- `tests/test_citizen.py` (7783 bytes) — 11 tests: spawn determinism, walkable enforcement, wander stays in bounds, wander actually moves, population grows under normal conditions, no reproduction before maturity, lifespan death, tier table partition, tier list shape.

**Sandbox verification (against the live project folder):**

- All 19 unit tests pass (8 P0 + 11 P1).
- Population curve from default seed (8 initial citizens, lifespan 180 ± 40, repro_cooldown 5): T0 -> T1 at sim_t ~30s -> T2 at ~300s -> T3 at ~400s -> T4 at ~500s. Stable exponential ramp; ~5 sim minutes to apocalypse tier without intervention. Tunable.
- Headless renderer run with hundreds of citizens: no crashes, sprite blit stays well under frame budget.

**Tuning notes for the next session.** Default `initial_population=8` with `spawn_radius_tiles=5` (down from the original 20) was needed to ensure mates can find each other. Default lifespan bumped from 90 -> 180 sim sec so founder generations don't die before their grandchildren mature. These numbers are first-pass; expect to revisit during balancing.

**Encountered & noted.** Outputs scratchpad files were silently truncated and padded with NUL bytes by the editor tool on two of the larger writes. Worked around by stripping NULs before SHA verification, then later by writing via bash heredoc to /tmp and atomic-renaming from there. The flaky-mount staging pattern continues to be load-bearing — every project-folder write was first-try after the pattern was applied. WORKLOG and TODO themselves had to be rebuilt whole in this session because earlier sessions had left them truncated.

**Next session candidates.** P2 (belief field): the central distinguishing mechanic. The citizen positions are already there; we need the 2D density grid + heatmap overlay + the per-cast strength lookup. Alternative: P1.5 (food/forage) if growth feels weird in playtest, or the citizen sprite polish (death frame, sub-tile walk animation).

## 2026-05-20 (P2 ship) — Belief field

P2 milestone shipped. The central distinguishing mechanic of *Densitas* now exists in code: belief is a per-faction 2D scalar field arising from citizen positions, queryable at any world tile, with a toggleable heatmap overlay.

**Decisions folded in before coding:**

- **Grid resolution 64x48** mirrors the default 256x192 world at 4-tile sampling. Each belief cell aggregates a 4x4 patch of world tiles. Tunable via `config.toml`.
- **Kernel: scatter-then-blur.** Each living citizen splats `amplitude=1.0` into their cell, then the per-faction grid is convolved with 2 passes of a separable 3-wide box filter (~ Gaussian σ ≈ 1.4 cells = 5.6 world tiles). Box blur is volume-preserving, so `total(faction) == population(faction)` exactly (mod float drift). This makes the integral interpretable; tests assert it.
- **No SciPy.** Box blur via numpy cumulative-sum trick keeps the dependency footprint at numpy alone.
- **Cadence: tied to citizen tick (5 Hz).** Belief is a pure function of current positions; no time-decay (locked in GDD §13).
- **DYING citizens excluded from belief.** Consistent with `CitizenManager.population()`.
- **`Renderer` ABC extended again.** `blit_belief_overlay` is now part of the contract. Implementations cache by `belief.version` to skip rebuild work between recomputes.
- **Overlay color model:** per-faction tint (cyan for Open Eye, red for Maw), per-cell alpha scaled by max magnitude, blend by faction-weight where they overlap. Off by default; toggle key `B`.
- **HUD shows belief total** next to population. With amplitude=1 this lands at ~population; the small DYING gap is the signal.

**Code shipped:**

- `Densitas_belief.md` (6453 bytes) — full P2 spec: pillars, grid, kernel, recompute cadence, query API, regen accounting, overlay, faction isolation, deliberately omitted, contract with rest of codebase, tunables.
- `densitas/belief.py` (7663 bytes) — `BeliefField` class, scatter-then-blur math, query/total/peak/dominant_faction/grid API, `version` counter for renderer caching, `N_FACTIONS = 2` constant.
- `densitas/render.py` (rev, 14030 bytes) — `Renderer.blit_belief_overlay` abstract added; `PixelRenderer` implementation builds the (gh, gw, 4) RGBA cell array, faction-weighted blend, alpha from magnitude, nearest-neighbor scale to world pixel dims, cached by belief.version.
- `densitas/main.py` (rev, 5860 bytes) — instantiates `BeliefField`, recomputes after each `citizen_mgr.tick`, wires the `B` keydown to `show_belief_overlay`, paints overlay after world surface but before citizens, debug HUD shows `belief here` at the center tile plus total / peak.
- `densitas/hud.py` (rev, 3490 bytes) — adds BELIEF readout (cyan, 16pt bold) inside the same bottom-left card. Box grew from 72px to 88px tall.
- `densitas/config.py` (rev, 2306 bytes) — `BeliefConfig` frozen dataclass; `Config` carries `belief`.
- `config.toml` (rev, 2846 bytes) — adds `[belief]` block. 7 tunables (grid_w, grid_h, amplitude, blur_passes, blur_radius, recompute_hz, overlay_alpha_max).
- `tests/test_belief.py` (6005 bytes) — 13 tests: empty world, single-citizen volume preservation, total==population, DYING exclusion, faction isolation, peak under citizen position, query matches grid, query edge clamping, dominant_faction, version counter, recompute idempotence, zero-blur-passes path, N_FACTIONS constant.

**Sandbox verification:**

- All 32 unit tests pass (8 P0 + 11 P1 + 13 P2).
- Headless smoke (SDL dummy): 60 s of sim (300 ticks at 5 Hz) runs in 80 ms wall (≈ 3750x realtime). Belief recompute average <1 ms at the early populations. Overlay first-build (64x48 → 4096x3072 nearest-neighbor scale) is ~22 ms; cached blits are ~0.4 ms/frame. The 22 ms hit lands at 5 Hz which is a ~11% CPU slice when the overlay is on — acceptable for a P2 prototype, noted as a future optimization (downscale-target intermediate, or per-frame-visible-region scale).
- 90 s of sim with overlay-each-frame rendering: ran clean, pop 19, belief total 19.00 (matches population to the cent), peak ~1.0.

**Encountered & noted.** Pytest's tempdir cleanup recurses infinitely on the project mount (likely a permissions/lstat quirk). Worked around by copying `densitas/`, `tests/`, and `config.toml` to `/tmp/densitas_test_run/` and running pytest there. All staging into the project folder continues via the bash-heredoc → /tmp → atomic-rename pattern; every P2 file landed first-try with SHA verification.

**Next session candidates.** P2.5 (fog of war) is a natural next step — the belief field is the input the visibility computation needs. Alternatively jump to P3 (Powers T0–T1 + Relics): the `belief.query` primitive is already in place for per-cast strength scaling, and relic placement only needs a click handler + a sprite on the map. P1.5 (food) remains parked unless playtest reveals growth weirdness.

## 2026-05-21 (P1.5 ship) — Food, forage, and carrying capacity

P1.5 milestone shipped. The 132k-citizen population blowup observed at the end of P2 is replaced by a real carrying-capacity mechanic. Tile food is now the constraint on reproduction; hungry citizens forage, starving citizens die.

**Diagnosed at the start of session 2026-05-21:**

Matthew's screenshot showed pop 132,797 / T4 Apocalypse / FPS 0.6 at sim_t ~617s. Belief total matched population to the cent (P2 math correct) but reproduction was unbounded. Matthew picked the proper fix over a band-aid: implement P1.5 food/forage now rather than papering over with parameter tweaks that we'd just undo at P3 relic-tier.

**Decisions folded in before coding:**

- **Food is a tile attribute, not an entity.** `world.food` float32 array sibling to `world.tiles`. Biome dictates initial value (= cap) and regen rate. No new entity type to render or pathfind to.
- **Eat in place** for P1.5. `Citizen.food_carried: int = 0` placeholder field exists for a future inventory tier (food 0-5, sword bool, shield bool) but is unused today.
- **Reproduction gate on hunger.** Both partners must have `hunger < repro_hunger_threshold` (0.3 default). This is the real population cap — the famine-throttles-births feedback loop.
- **Starvation -> DYING.** Distinct trigger from old-age (`hunger >= starve_hunger`), shared FSM exit through DYING.
- **DYING citizens contribute fractional belief** scaled by `state_timer / dying_duration`. With `dying_duration` bumped 0.5s → 2.0s, the belief overlay visibly shrinks during mass mortality — *"the god slowly loses belief"*, per Matthew.
- **Food field as a separate module** (`densitas/food.py`), parallel to `BeliefField`. World terrain stays read-only after generation; FoodField owns the dynamic state. Same shape: `recompute / query / grid / version`.
- **Heatmap overlay** mirrors belief: built at world-tile native resolution (256×192), nearest-scaled to world pixels, cached by `food.version`. Toggle key `F`.
- **HUD adds three-segment hunger bar** + percentage readout (FED / HUNGRY / STARVING) inside the same bottom-left card.

**Code shipped:**

- `Densitas_food.md` (13,675 bytes) — full P1.5 spec: pillars, world extension with biome regen table, citizen extension (hunger field + FSM additions), belief refinement, render extension, HUD extension, config schema, equilibrium math, playtest acceptance, FoodField location decision, contract with rest of codebase.
- `densitas/food.py` (5,775 bytes) — `FoodField`: per-tile cap + regen arrays derived from `world.tiles`. `recompute(dt)` vectorised numpy. `consume(tx, ty, amount) -> taken`. `find_nearest(tx, ty, radius, min_food) -> (tx,ty) | None` using numpy window + Chebyshev distance + secondary food-magnitude tiebreaker. `query`, `grid`, `peak`, `total`, `version`.
- `densitas/belief.py` (rev, 6,282 bytes) — DYING-fade in `_scatter`: weight = `amp * (state_timer / dying_duration)` when DYING. Takes `dying_duration` at construction time.
- `densitas/citizen.py` (rev, 18,995 bytes) — `hunger: float` and `food_carried: int = 0` on Citizen. `food_cfg` arg to `CitizenManager`; passing None falls back to P1 mode. New FSM dispatch for FORAGE (walks to nearest food tile via existing `_step_toward`) and EATING (consumes bite_size per tick, decrements hunger). Hunger accrues every tick except in DYING. Starvation transitions to DYING when `hunger >= starve_hunger`. `_is_repro_fed` gate added to `_find_mate`. Mating now costs additional hunger on both partners. `hunger_stats(faction) -> (fed, hungry, starving, avg_hunger)`.
- `densitas/render.py` (rev, 13,295 bytes) — adds `blit_food_overlay` abstract + PixelRenderer implementation. World-tile-native source resolution. Walks the same cache pattern as belief. FORAGE state added to walk-frame state set so foragers animate.
- `densitas/hud.py` (rev, 5,059 bytes) — three-segment hunger bar (green / amber / red) + percentage labels. Box grew from 88px to 116px tall.
- `densitas/main.py` (rev, 6,457 bytes) — instantiates `FoodField`, recomputes after each citizen tick (food first, then citizens, then belief). `K_f` toggles `show_food_overlay`. Draw order: world → food (if on) → belief (if on) → citizens → debug → HUD. Debug overlay shows food-here, total food, peak food.
- `densitas/config.py` (rev, 3,119 bytes) — `FoodConfig` + `FoodBiomeConfig` frozen dataclasses; `Config` carries `food`.
- `config.toml` (rev, 2,423 bytes) — `[food]` and `[food.biome]` blocks. **Tuned 2026-05-21** (see below). `citizen.dying_duration` bumped 0.5 → 2.0.
- `tests/test_food.py` (12,740 bytes) — 20 tests: biome init, barren biomes, mixed-biome maps, regen cap clamp, partial regen, `consume` returns/clamps/no-op on barren, version bumping, `find_nearest` closest/respects-min/none-in-range, hunger accrues, starvation→DYING, repro gate blocks hungry, repro allowed when fed, FORAGE transition, EATING reduces hunger+food, `food_carried` defaults to zero, P1 backward-compat with `food_cfg=None`.
- `tests/test_belief.py` (rev, 5,317 bytes) — 15 tests, three new: DYING with full timer contributes full amplitude, DYING at midpoint contributes ~half, DYING at zero timer contributes nothing.

**Sandbox verification:**

- All 54 unit tests pass (8 P0 + 11 P1 + 15 P2 + 20 P1.5).
- Headless tuning playtest, default seed, 30 sim minutes (1800s, 9000 ticks):
  - 8 founders → max 736 → settling around 685
  - T1 by sim_t ~100s, T2 by ~200s, T3 not reached in 30 sim min
  - fed/hungry/starving stable at ~30/68/2% — the hunger gate is biting continuously
  - Total food: 27,358 → 23,174 (~15% drawdown; system in flow, not collapse)
  - Wall clock: 20 sec for 1800 sim sec (90x realtime)

**Tuning numbers landed:**

```
[food]
hunger_rate = 0.05            # 20s full→starving
forage_threshold = 0.40
repro_hunger_threshold = 0.30
starve_hunger = 1.00
bite_size = 0.20
calorie_per_food = 1.00
forage_radius_tiles = 8
min_forage_food = 0.10

[food.biome]
forest_initial = 1.00 / regen 0.007
grass_initial  = 0.80 / regen 0.005
beach_initial  = 0.50 / regen 0.003
hill_initial   = 0.30 / regen 0.002
holy_initial   = 0.15 / regen 0.001
```

Carrying-capacity math: `N_eq = total_regen_per_sec / hunger_rate ≈ 178 / 0.05 ≈ 3,560`. Actual equilibrium settles lower (~700–1000) because not every tile has a citizen sitting on it at once and the spatial spread limits eat-throughput.

**Tuning iteration open in TODO.** T3 (1000 threshold) currently sits *at* the edge of equilibrium — reaching it requires sustained survival rather than a brief growth spike. If playtest reveals T3 feels unreachable, bump regens 1.5x or drop `hunger_rate` to 0.04. P3 holy-site / relic mechanics will also boost local food/belief which is the *intended* path to T3+.

**Encountered & noted.** Two test failures on the first pytest run revealed fixture bugs, not implementation bugs: `test_citizen_starves` used MOUNTAIN world (not walkable, so `_spawn_initial` placed zero citizens), and `test_reproduction_gated_on_hunger` used GRASS world (citizens just ate themselves out of the gate). Both fixed by manually planting citizens + zeroing the food field. Every project-folder write was first-try under the existing flaky-mount staging pattern.

**Next session candidates.** P2.5 (fog of war) — the belief + food fields are exactly what visibility computation needs as input. Or P3 (Powers + Relics): `belief.query` and `food.consume / find_nearest` are the primitives, plus relics need to interact with the food field (Holy tiles get richer regen than current). Or sprite polish (death-fade frame matching the belief fade, EATING munch animation).
