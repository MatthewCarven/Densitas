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
