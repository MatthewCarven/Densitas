# Densitas — Powers Spec Sheet

*v0.3 — May 20, 2026.* All numbers are first-pass; balance is for the prototype to validate.

Notation:
- **Tier:** required population threshold to use at all.
- **Belief cost:** drained from the global belief pool on cast. If insufficient, the cast fails.
- **Strength scaling:** effect magnitude is multiplied by `local_belief(target) / k_tier`. Cast in a dead zone → cast does nothing useful.
- **AoE:** radius in tiles.
- **Cooldown:** per-power cooldown in seconds.
- **Counter:** how a smart opponent neutralizes it.

---

## Persistent — Religious Relic (always available)

Not a "power" per se — a placed object. The god's primary control verb. Each god starts with 3 relics; T3 grants a 4th, T4 a 5th. You place a relic anywhere you can see (the whole map until fog-of-war ships in P2.5).

- **Belief cost:** 0 to place; 0 to retrieve. Cost is opportunity, not belief.
- **Effect:** radiates a passive belief contribution as if it were a citizen with ~20× a normal citizen's amplitude. Also passively attracts nearby player-citizens with surplus capacity over time.
- **Move cooldown:** 30 sec after relocation before the relic is fully effective at its new tile.
- **Destruction:** a relic shatters when local rival-belief exceeds player-belief at the relic's tile by a sustained margin (the rhetoric for this is brutal: *"The Other reached even here."*). Disasters can also destroy it instantly — a Comet on a relic is a real possibility and changes how it's played.
- **Strength scaling:** none — relics have a fixed contribution. The choice of *where* is the entire strategy.

The mental model: relics are how the god *plants intent* on the map. Citizens are the wind, relics are the rocks the wind blows around. You don't tell a citizen to go to the valley; you put a relic in the valley.

**Relic names by god** — see `Densitas_lore_pantheon.md`. The Open Eye places *The First Witness, The Second Witness, The Third Witness*; the Maw places *First Bite, Second Bite, Third Bite*. These names appear in the scripture log when the relic is placed, moved, or shattered.

---

## Tier 0 — Whisper (≥ 1 citizen)

These are free or near-free nudges. They are how you play before you have any real civilization.

**Inspire.** Belief cost 0. Picks one nearby citizen and shoves their wander vector toward the target tile. Tile-scale movement bias for ~5 seconds. *Counter:* none — too weak to need one.

**Calm.** Belief cost 0. Suppresses panic/flee behavior in a tiny radius (2 tiles, 5 sec). Useful right after a disaster. *Counter:* keep disasters compounding.

**Hunger Pang.** Belief cost 1. Targets one rival citizen; they drop whatever they're doing and search for food. Annoyance-tier. *Counter:* abundant food keeps the effect trivial.

---

## Tier 1 — Blessing (≥ 10 citizens)

The "you have a village now" tier. Land sculpting and small miracles.

**Raise Terrain.** Belief cost 5/tile. AoE 1 tile. Lifts one tile by one elevation step. Stacks on repeat casts. *Strength scaling:* if `local_belief < k_1`, no effect. *Counter:* rival lowers it back at equal cost.

**Lower Terrain.** Belief cost 5/tile. Mirror of raise. Lowering a tile to sea level converts it to water — citizens drown if they were on it. *Counter:* citizens flee water; calmly herd them out.

**Bless Field.** Belief cost 10. AoE 4 tiles. Food yield ↑ 100% for 30 sec in radius. Speeds reproduction locally. *Counter:* curse it back, or convert citizens before they multiply.

**Curse Field.** Belief cost 10. AoE 4 tiles. Food yield ↓ 80% for 30 sec. Citizens may wander away from cursed land. *Counter:* bless on top.

**Spring.** Belief cost 25. AoE 1 tile. Creates a fresh-water tile, increasing carrying capacity of adjacent land. Permanent until disaster removes it. *Counter:* lower terrain to drain.

---

## Tier 2 — Tempest (≥ 100 citizens)

The first "weapons" tier. Costs jump, AoEs widen, things start to die.

**Rainstorm.** Belief cost 30. AoE 8 tiles. Boosts crop yield, extinguishes fires, slows citizen movement. Mostly utility. *Counter:* none needed; it's friendly.

**Lightning Strike.** Belief cost 25/strike. AoE point. Kills any citizen on the target tile; small chance to start a fire on flammable terrain. *Strength scaling:* in a dead zone, the bolt misses. *Counter:* keep citizens spread thinly; rainstorm to suppress fire spread.

**Plague.** Belief cost 80. AoE 6 tiles. Citizens in the radius lose health over 20 sec; survivors recover, lost are dead. Affects both gods' citizens equally — surgical. *Counter:* evacuate the radius via pilgrimage; bless to accelerate recovery.

**Pilgrimage.** Belief cost 50. AoE 12 tiles. All player citizens in radius gain a strong wander bias toward target tile. The single most useful tool for densifying — you herd 200 citizens into one square mile and *now* you're cooking. *Counter:* curse the target field so they starve once they arrive.

---

## Tier 3 — Cataclysm (≥ 1,000 citizens)

Reshape-the-world tier. One cast per minute, expensive, devastating.

**Earthquake.** Belief cost 250. AoE 12 tiles, propagating outward over ~4 sec. Randomly raises and lowers tiles; collapses buildings; kills citizens in low-elevation tiles that turn into water. *Strength scaling:* damage ∝ local belief at epicenter, so casting deep inside your own territory and targeting the rival's land works best (sustained density at cast origin). *Counter:* the rival's earthquake counter-cast can stabilize tiles, but it's the same belief cost — exchange of blows.

**Volcano.** Belief cost 400. AoE 8 tiles. Raises a central peak to mountain elevation; emits lava periodically for 60 sec, burning surrounding terrain to blighted. Permanent terrain change. *Counter:* none in-tier. T4 Flood can submerge it.

**Hurricane.** Belief cost 300. AoE 16 tiles, but moves across the map in a path the player draws. Kills citizens caught in the eye; floods low terrain; flattens buildings. Lasts 30 sec. *Counter:* densify on high ground; rainstorm slightly weakens it.

**Holy War.** Belief cost 200. Summons N zealot bands at target, where N = floor(total_belief / 1000). Zealots are special citizen units: 5× combat-effective, attack rival citizens on contact, last 90 sec then dissolve. *Counter:* convert them by overwhelming local belief; or kill them with lightning.

---

## Tier 4 — Apocalypse (≥ 5,000 citizens AND peak density ≥ holy-site threshold)

End-the-game tier. Casts are slow, expensive, irreversible, and almost always decide the round.

**The Flood.** Belief cost 1,000. Sea level rises 2 elevation steps across the entire map over 90 sec. Permanently submerges everything below the new line. *Counter:* raise your capital onto high ground in advance (T1 work over the long term); the rival who has been preparing wins.

**Comet.** Belief cost 800. Single point target. After a 10-sec warning streak across the sky, lands and destroys everything in an 8-tile radius (instant kill, terrain blighted, buildings flattened). *Strength scaling:* destruction radius scales with local belief at *cast origin* — you cast it from your most blessed altar. *Counter:* no in-game counter; it's the win-button. Strategic counter: don't let your population concentrate in one place the rival can target.

**Sundering.** Belief cost 1,200. Draws a line across the map; raises elevation along the line into an impassable wall AND simultaneously lowers the two parallel strips beside it into ocean. Cuts the map in half. Used to isolate the rival from half their territory. *Counter:* none; play around it.

**Divine Manifest.** Belief cost 1,500. The god briefly walks the world as a single, gigantic, slow-moving figure. Anywhere they step, terrain is reshaped, citizens convert in a 6-tile aura, rival citizens die in a 3-tile aura. Lasts 30 sec. Player controls movement directly. *Counter:* the rival's own Divine Manifest cancels yours if they cast simultaneously; otherwise it almost wins the round.

---

## Cross-cutting rules

- **Belief regenerates** from the citizen field continuously, no time-decay otherwise. Roughly: `belief_per_sec ≈ population × 0.02 × (1 + density_bonus)`. So a 1000-citizen city densely packed regenerates faster than 1000 nomads. If your citizens die, the regen stops — that's the only "lose" condition for belief.
- **Local belief is sampled at the target tile** for most powers; some (Comet, Earthquake) sample at the cast origin instead, rewarding fortified holy sites.
- **Failed cast** (insufficient belief, dead zone, or below tier) → 50% refund, full cooldown applied. Prevents griefing the AI by spamming, but doesn't punish honest attempts.
- **Counter-casting:** any T3+ power can be partially canceled by the rival casting the same or higher tier within 2 sec at overlapping AoE — belief cost is paid by both, effects partially cancel.
- **Cooldowns:** T0 0 sec, T1 2 sec, T2 6 sec, T3 30 sec, T4 90 sec.

---

## Design notes

- We deliberately do not give the player a "smite" button that kills citizens cheaply. War is fought through density, conversion, and disasters that scale with local belief. This keeps the central mechanic load-bearing.
- Holy War is the closest thing to a direct combat power. It still respects the density rule via the `N = floor(total_belief / 1000)` band count.
- T4 powers are designed to be *terrifying* if you can cast them, and to be *prevented* by play at lower tiers — keep the rival from ever reaching 5,000 dense citizens, or accept that one of you is about to flood the world.

---

## Rhetoric pool — the three voice modes

Every cast emits exactly one scripture-log line. The line is picked from a pool keyed on three things: the **power** being cast, the **god** casting it, and the **voice mode**. The voice mode rotates so the log doesn't drone — most lines are *consecration mode* (terse, just-happened), but every fourth or fifth line escalates to *doctrinal* (states a principle) or *ritual-procedural* (describes what the priests/citizens are doing about it).

The voice should *always* dignify the act. Never apologize, never wink. See GDD §10 for tone.

### Mode 1 — Consecration

Short, present-tense, descriptive. The cast just happened; the log states it and consecrates it in the same breath. This is the default for ~70% of log lines.

- Plague: *"The unworthy among us were 