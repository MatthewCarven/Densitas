# Densitas — Game Design Document

*Working draft, v0.2 — May 20, 2026*

---

## 1. Concept

**Densitas** is a top-down god game in the spirit of *Populous*, in which the player is a deity whose power is bounded entirely by the belief of mortal citizens. Belief is not an abstract resource — it is a **density field**. Every citizen radiates a small aura of faith around themselves; where citizens cluster, belief intensifies. Where belief intensifies, the god can act. Where belief is thin, the god is nearly powerless.

The name *Densitas* (Latin: density) is the central mechanic. Total population determines which **tiers of godly power** are unlocked. Local population density determines **how potent any given act of power can be at a specific place**. A god with a million scattered nomads is weaker, in any given valley, than a god with ten thousand citizens packed into a glorious city.

The player wins by becoming the dominant belief field on the map — either by extinguishing the rival god's faithful, by converting their cities, or by sustaining sufficient density to achieve **Apotheosis**.

## 2. How Densitas differs from Populous

- **Belief is geographic.** Populous treats faith as a single global mana bar. Densitas treats it as a 2D scalar field. The same spell cast in the heart of your capital and at the edge of the wilderness produces very different results.
- **Tier unlocks, not linear costs.** Powers are gated by population thresholds, not by accumulated mana. Reach 100 citizens and you unlock storms forever; you don't lose access if your population dips below 100 the next day, but the *strength* of what you cast scales with current local density.
- **Conversion at the seams.** There is no explicit "attack" power. War is fought by pushing your density field across the boundary of the rival's field. Citizens on the contested edge gradually lose faith in whichever god is locally weaker and convert — or starve and die — in proportion to how dominated they are.
- **The density field is visible.** A heatmap overlay is a first-class UI element, not a debug toggle. Reading the field is a core skill.

## 3. Core gameplay loop

1. **Gather** — guide citizens to fertile, defensible land and let them reproduce.
2. **Concentrate** — channel them into denser settlements; density compounds belief.
3. **Unlock** — pass population thresholds to unlock new tiers of divine power.
4. **Project** — cast powers to reshape terrain, smite enemies, or seduce the rival's citizens.
5. **Defend** — protect your density. A single well-placed disaster from the rival can collapse a city and crash you down a tier.

A round is won when the rival's belief field falls below an extinction threshold across the whole map, OR when the player sustains the highest tier for a continuous period (Apotheosis).

## 4. The belief field

Every citizen contributes a 2D Gaussian-shaped belief field centered on themselves, with radius `r_citizen` (small) and amplitude `a_citizen` (small). The total belief field for a god is the sum of all their citizens' contributions across the map.

Useful derived quantities:

- **Total belief** ≈ ∫ field dA ≈ proportional to citizen count → determines **tier unlocks**.
- **Local belief at point p** = field value at p → determines **per-cast strength**.
- **Peak density** = max field value → determines whether a megacity bonus is active (the "Holy Site" buff, unlocking T4 powers).

The field decays over distance and at "edges" overlapping a rival field, the two fields oppose: each citizen weighs the local difference (mine − rival's) to decide whether to keep the faith.

**No time-decay of belief.** Belief is strictly populace-driven — if your citizens are alive and present, your field exists. If they die or convert, it shrinks. No idle drain to manage, no "use it or lose it" pressure. This keeps the central mechanic legible: more citizens, more dense, more power. Less, less, less. End of rule.

## 5. Tiers of divine power

Powers are organized into five tiers. The tier is unlocked once your total population crosses the threshold; the **effect strength** of a cast power scales with local belief density at the cast location.

| Tier | Threshold | Theme | Sample powers |
|------|-----------|-------|---------------|
| T0 — **Whisper** | 1 citizen | Personal nudges | Inspire (one citizen wanders toward target), Calm, Hunger pang |
| T1 — **Blessing** | 10 citizens | Land + small miracles | Raise/Lower terrain, Bless field (food yield ↑), Curse field, Spring (create water source) |
| T2 — **Tempest** | 100 citizens | Weather + small disasters | Rainstorm, Lightning strike, Plague (small radius), Pilgrimage (citizens migrate to target) |
| T3 — **Cataclysm** | 1,000 citizens | Reshape the world | Earthquake, Volcano, Hurricane, Holy War (summons zealot bands) |
| T4 — **Apocalypse** | 5,000 citizens | Civilization-ending | The Flood, Comet, Sundering (cleave continent), Divine Manifest (god briefly walks the world) |

Tiers persist once unlocked. Strength does not. A T3 earthquake cast from a 10-citizen hamlet does roughly nothing.

## 6. Citizens

Citizens have three needs: **food, shelter, faith**. They wander toward food and shelter on their own; faith is supplied by the god through proximity to belief field and through interventions (blessings, miracles, granted prosperity).

- **Reproduction:** citizens with all three needs met above threshold produce new citizens at a configurable rate. Reproduction is faster in dense, faithful settlements — densitas compounds. **Tuning is exposed via config:** `reproduction_rate`, `lifecycle_length_days`, `infant_mortality`, `food_to_birth_ratio`. Defaults to be set by playtest; the engine just has to honor whatever values are in the config file. Build the game so we can spin the knobs.
- **Conversion:** a citizen standing where rival belief > own belief loses faith. Below a threshold they convert; below a second threshold they die of despair. The "seam" between two density fields is therefore the battlefield, and the player can push it by densifying near the boundary or by casting powers that locally amplify their field (e.g. erecting a shrine, miracle, etc.).
- **Buildings:** dwellings (passive, increase carrying capacity), shrines (radiate small extra belief), wonders (T3+, large persistent belief amplifier).

### 6.1 Player control of citizens — nudge-only

The god does not give orders. The god has exactly two ways to direct citizens:

- **Whispers (T0).** Pick a nearby citizen, push their wander vector. Tiny, individual, free. Mostly atmospheric.
- **Religious Relics.** Each side may place a small number of relics anywhere they can see (line-of-sight matters when fog-of-war exists; until then, anywhere on the map). A relic is a *focal point of faith*: it radiates extra belief around itself AND it acts as a passive attractor — citizens with surplus capacity drift toward the nearest visible relic over time. Relics persist until destroyed (rival can shatter them with disasters, or convert the surrounding land such that local rival-belief exceeds player-belief at the relic's location, which causes it to crack).

This is the central control verb. Want to settle that fertile valley? Drop a relic there. Want to thicken your seam? Drop a relic on it. Want to bait the rival into wasting a Comet on something you can rebuild? Drop a relic out in the wastes.

Starting allocation: 3 relics per god. T3 unlocks a 4th, T4 unlocks a 5th. Placing one is free; you only have so many at a time. You can pick up and move a relic, but it goes on cooldown (~30 sec) before it's effective again at the new spot — moves cost momentum, not belief.

## 7. Rival god AI

A single rival god to start. The AI plays by the same rules. Personalities (designed later, after core systems are in):

- **Zealot** — aggressive, pushes seams, casts powers cheaply, neglects density.
- **Steward** — defensive, densifies into one or two megacities, hoards belief for big T3+ casts.
- **Trickster** — uses pilgrimage and conversion rather than disasters; tries to thin your edges.

Difficulty scales the AI's tick rate of power use, not its rule set.

## 8. World and terrain

Heightmap-based, with biomes derived from elevation and moisture. Citizens prefer flat fertile land near fresh water. Raised land is defensible (and slows conversion across it). Water is impassable for citizens. Volcanic peaks emit sporadic eruptions even without a god casting one.

- **Tile types:** water, beach, grass, forest, hill, mountain, lava, blighted (post-disaster), holy (post-miracle).
- **Map size (prototype):** 256×256 tiles, scrolling camera, ~5 minute round.

## 9. Win conditions

A round ends when one of:

1. **Extinction** — rival's total population drops below 5 for 10 seconds.
2. **Conversion** — rival's last city flips to player faith.
3. **Apotheosis** — player sustains T4 (≥ 5,000 citizens AND peak density ≥ threshold) for 60 seconds while rival is at or below T2.

## 10. Tone

Reverent but with cosmic detachment. Citizens are tiny, named only by number, but mourned in aggregate on the post-round screen ("you lost 4,128 souls to the comet; 311 still pray your name"). UI text reads like scripture fragments. No grimdark; no cheerful chiming either.

**The questionable propaganda layer.** Every divine act gets translated by the citizens into reverent rhetoric in the scripture log — and the rhetoric is deliberately over-confident in a way that should slowly land as funny / unsettling once the player notices. A bless on a field becomes *"The Gods, in their wisdom, granted us the perfect harvest."* A plague that kills 30 citizens becomes *"The unworthy among us were called home."* A volcano that wipes out a city becomes *"The Other has shown us our smallness."* The player's casts are described in language that confidently asserts the god's benevolence, even when the action was cruel or arbitrary. The longer the player plays, the more they should notice the pattern: every event is consecrated, every loss is justified, every fortune is providential. Densitas is a game about *belief*, not just about belief as a resource — the rhetoric is the texture of that belief.

A few practical lines to seed the writer's voice:
- *"Rain came as foretold. None foretold it, but it came."*
- *"They reproduced and reproduced, as is the way."*
- *"A relic was placed where no one had thought to look. Now we see."*
- *"The river drowned its banks. The gods are with the river."*

## 11. Platform & tech

- **Engine:** Python + pygame.
- **Rendering:** software 2D, double-buffered. Terrain rendered to a base surface, belief field overlaid as a semi-transparent heatmap, citizens as 1–2 px dots, settlements as small icons.
- **Belief field representation:** coarse grid (e.g. 64×64), recomputed every N ticks by accumulating citizen contributions. Avoids per-citizen radius math on the hot path.
- **Simulation tick:** **5 Hz logic, 60 Hz render.** Nobody is auditing a god game at 20 Hz; 5 Hz gives the AI and the player time to think and is generous compute headroom for the belief-field recompute. Rendering interpolates between two logic ticks so motion still looks smooth.

## 12. Prototype milestones

| Milestone | Scope |
|-----------|-------|
| **P0 — Pixel world** | Tile map, camera, terrain render, no citizens yet |
| **P1 — Citizens exist** | Citizens spawn, wander, eat, reproduce. No god yet |
| **P2 — Belief field** | Density field accumulates, heatmap overlay |
| **P2.5 — Fog of war** | Per-god visibility; relic placement constrained to visible tiles |
| **P3 — Powers T0–T1** | Whisper + raise/lower terrain + bless. Relics. Player can click |
| **P4 — Rival god** | A second civilization with simple AI |
| **P5 — Tiers T2–T4** | Full power catalog, all tier transitions |
| **P6 — Win/lose & polish** | End conditions, end screen, sound, balance |

## 13. Resolved decisions

Settled with Matthew on 2026-05-20 during the second design pass:

- **Belief decay** — none. Strictly populace-driven. (See §4.)
- **Reproduction speed** — exposed as config. The engine honors the values; defaults to be set by playtest. Knobs: `reproduction_rate`, `lifecycle_length_days`, `infant_mortality`, `food_to_birth_ratio`. (§6.)
- **Heatmap overlay** — off by default, toggleable. Key bind to be assigned (proposal: `B` for belief).
- **Fog of war / rival field visibility** — full map and full rival field in P0–P2. Fog of war becomes a real mechanic at **P2.5**, and at that point it gates relic placement ("place anywhere you can see").
- **Citizen control** — nudge-only. Whispers (T0) for one-citizen nudges, and **Religious Relics** as the persistent attractor. No direct selection of individual citizens for orders. (§6.1.)
- **Simulation tick** — 5 Hz logic, 60 Hz render. (§11.)
- **Multiplayer** — parked. Not in scope for the early prototype. Honest take: real-time networked sim is the kind of thing that pulls a project sideways. When we revisit, the practical options in increasing complexity are (a) hot-seat (zero networking, two players one keyboard, trivial); (b) lockstep determinism (each client runs identical sim; only player commands are exchanged — needs the sim to be deterministic but the bandwidth and "did a message drop" risk drops to near zero because you only sync inputs, not state); (c) authoritative host (one machine runs sim, others receive state — bandwidth-heavier, but no determinism requirement). At 5 Hz with a finite power-cast vocabulary, lockstep is genuinely tractable when we want to do it. Until then: single-player vs AI.

## 14. Still open

- Art direction (pixel? minimal vector? hand-drawn?).
- Citizen icon resolution at the target zoom — 1 px is illegible, 4 px makes a 5000-citizen city look like a smear.
- The "rhetoric" log writer — is the line pool curated by hand, generated procedurally from templates, or some hybrid? (Hand-written is funniest; templated is more replayable.)
- Relic art and feedback — what does shattering look/sound like? This is the most emotional moment in the game for the loser.

---

*Next: start P0 prototype (tile map + camera + terrain render in pygame), AND draft the rival-god AI personality specs in parallel.*
