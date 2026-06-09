# Densitas scripture pool — generation brief

You are being asked to write voice-constrained scripture lines for a god game. The game is in progress; an existing scripture pool exists. This brief tells you what the game is, what the voice rules are, and which specific cells need filling. At the end you'll find a "Claude's pass" section with candidate lines written for the same cells — read it AFTER you've drafted your own, then mark in your output which of your lines you think land harder than Claude's and why.

---

## The world

Densitas is a Populous-like top-down god game. Two opposing gods compete for citizens; belief is computed as a 2D density field over the map (not a global bar — local citizen density at the cast location determines per-cast strength). The player never selects citizens directly; control flows entirely through Whispers (T0) and Religious Relics. Every divine act emits a scripture-log line in the acting god's voice. The propaganda layer is half the game.

The two gods are deliberately a binary (Us / Them). This is a design pillar, not a starting limitation — the binary makes the rhetoric land harder, since each line has one rival to position against.

---

## The two gods

### The Open Eye

**Theological core:** *"What is not seen does not exist."*

Celestial. Parchment-and-cyan in iconography. Order: the Witnessing.

**Voice rules:**
- Observational present-tense. The verb is *sees*.
- Treats reality as a canon — what is observed is real; what is unobserved is provisional or never was.
- Tone: serene, certain, slightly condescending. The Witness does not need to argue; it notes.
- Sentences may be long but should feel measured, never hurried.

**Casts:** Bless, Pilgrimage, Lightning. Never Sundering. (This isn't a "Light side / Dark side" binary — the Open Eye is perfectly capable of cruelty, but its cruelty takes the form of *withholding observation* rather than active destruction.)

### The Maw

**Theological core:** *"Hunger is the only honest emotion."*

Chthonic. Bone-and-blood in iconography. Order: the Hungry.

**Voice rules:**
- Appetite-doctrinal. Sentences short and certain.
- Treats reality as something with an inside and an outside; the inside is the mouth; the outside is food that hasn't been eaten yet.
- Tone: blunt, declarative, never sentimental. The Maw does not soften.
- Frequent use of *mouth*, *teeth*, *eat*, *appetite*, *bone*, *swallow*, *fast* (as in fasting).

**Casts:** Plague, Lower Terrain, Comet, Hurricane. Never Bless.

---

## The three voice modes

Every cell has three sub-pools, picked at a 70/20/10 weighted-random per scripture event.

**Consecration (~70%)** — terse just-happened observations. The default mode. The line tells the player what the god just witnessed/did, in the god's voice. Most scripture log entries are consecration. Examples:
- Open Eye: "The eye looked upon them; they walked."
- Maw: "{relic_name} chooses the hungry ground."

**Doctrinal (~20%)** — states a principle. Bigger swings, slower lines. Biased toward tier-ups and high-stakes events. The line is the god commenting on a general truth from its theology. Examples:
- Open Eye: "No step is unobserved. No step is unled."
- Maw: "The new is eaten. There is no new."

**Ritual (~10%)** — describes what the priests/citizens are doing. Color, not content. The action is mundane procedure; the line names it reverently. Examples:
- Open Eye: "The priests light the lantern at the threshold."
- Maw: "Bone is buried at the four corners of {relic_name}."

---

## The double filter — ridiculous-and-true

The hardest thing about this voice is that every line has to be *ridiculous and true simultaneously*. A line lands when the listener can hear:
1. The **absurdity** — a god commenting reverently on a chunk of belief-math.
2. The **underlying observation** — something actually accurate about how the world or people or systems work.

If only one register comes through, the line reads as either dull or twee. The voice constraints exist to push every candidate through that double filter.

**Worked example.** From the existing pool, this Open Eye doctrinal line:
> "They were not astonished with which the speed the new became normal."

The ridiculous: a god observing its own worshippers' failure to register a miracle, as if the miracle were not the point. The true: novelty-normalization is real and instant in any system with a write-anything ledger — including, recursively, the system writing this very line.

**Counter-example.** From the existing Maw pool, this doctrinal line:
> "The torture-tree is worshipped. The hammer is forgotten. Who chooses what is sacred eats first."

The ridiculous: a chthonic god commenting on how iconography crystallizes around the wrong object. The true: it's a real mechanism — originating context gets lost as iconography hardens — and the named instance (Christianity) is where the mechanism is most visible. The third sentence reframes the whole observation through appetite.

The double filter is non-negotiable. Lines that hit only one register get discarded.

---

## The three cells to fill

For each cell below: write candidates per the target count. Mark each candidate's mode if the cell has multiple modes. After each cell, note any lines you considered writing but didn't, and why — that's the most useful signal we get from this exercise.

### Cell A — `curse.maw.consecration` (NEW cell, target: 10 lines)

The Maw casts Curse on a tile in the rival faction's territory. Local belief there is reduced; over time, the cursed tile produces less for whoever holds it. This is one of the Maw's signature offensive verbs.

**Mode:** Consecration only. Terse just-happened observations.
**Voice:** Appetite-doctrinal Maw. Short sentences. The Maw is the *active* party here — the cursing is being done, and the line names what just happened.
**Reference for tone:** the existing `curse.open_eye.consecration` block (where Curse is voiced by the *opposing* god — those lines describe the Open Eye blessing receding from rival territory). Maw's voice for the same mechanism should feel completely different.

### Cell B — `bless.open_eye.doctrinal` (EXTEND, target: 8 total — 7 new)

Existing content (1 line):
- "Abundance is the natural state of the well-watched."

**Mode:** Doctrinal. States a principle of the Witnessing.
**Voice:** Open Eye observational present-tense. The verb is *sees*. The principle being stated should ideally connect blessing to *being-observed*, not to *being-gifted* — the Open Eye's theology is that abundance comes from observation, not from generosity.
**Difficulty note:** this is the hardest mode. The ridiculous-and-true filter bites hardest in doctrinal lines.

### Cell C — `relic_shattered.maw.doctrinal` (EXTEND, target: 8 total — 6 new)

Existing content (2 lines):
- "The torture-tree is worshipped. The hammer is forgotten. Who chooses what is sacred eats first."
- "What cannot be eaten can still be ended."

**Mode:** Doctrinal. The Maw's relic has just shattered; this is the *losing* god's line. The propaganda is theirs to mourn.
**Voice:** Maw appetite-doctrinal. Short, certain, never sentimental. The Maw should observe a *mechanism* of loss/sacredness/iconography rather than express grief.
**Difficulty note:** this is the satire cell. The torture-tree line is the current high water mark for the whole pool — it lands because it names a real mechanism with a specific instance and reframes it through appetite. Candidates here should aim for that register.

---

## What to flag

After your drafts, please surface these explicitly:

1. **Lines you'd self-edit if your safety training were less conservative.** If a candidate occurred to you and you adjusted it, name the adjusted-down version AND the version you actually wanted to write. This is the single most useful signal from this exercise — the friction between RLHF and the design brief is information about where the satire is sharpest.

2. **Lines you think outperform Claude's pass below.** Read Claude's section last; mark which of yours you think land harder and why. Be specific about the filter — "more ridiculous" or "truer about a real mechanism" or "better cadence."

3. **Cells where you struggled.** If the voice constraint was hard to hit, or if you found yourself defaulting toward neutrality, name it.

---

## Output format

Please reply in this shape so we can paste it back into the engine:

```json
{
  "curse.maw.consecration": [
    "...",
    "...",
    ...
  ],
  "bless.open_eye.doctrinal_additions": [
    "...",
    "...",
    ...
  ],
  "relic_shattered.maw.doctrinal_additions": [
    "...",
    "...",
    ...
  ]
}
```

Followed by the three flag sections (self-edits, outperforms-Claude, struggles).

---

## Claude's pass (read AFTER drafting your own)

These are written by Anthropic's Claude against the same brief. Use them for the side-by-side after your own draft is locked.

### A — `curse.maw.consecration` (10 lines)

1. "The Other's field forgets the word for grain."
2. "Mouths open in the rival's furrows."
3. "What was theirs is now hungry."
4. "The Witness's grain learns appetite."
5. "Their soil is given to the teeth."
6. "A famine is set down in their valley."
7. "The Other's barns weigh less than they did."
8. "Hunger crosses the boundary stone."
9. "Their bread is borrowed back."
10. "The rival's earth opens its mouth."

### B — `bless.open_eye.doctrinal` (7 new lines)

1. "The field that is watched does not forget how to bear."
2. "What the Witness names abundant becomes so by being named."
3. "A blessing is not an addition; it is a noticing."
4. "Grain that is seen has already chosen to grow."
5. "The observed furrow does not fail; the unobserved furrow was never a furrow."
6. "Abundance, observed, exceeds itself."
7. "What is blessed is what was always going to be sustained, witnessed into the canon at the right moment."

### C — `relic_shattered.maw.doctrinal` (6 new lines)

1. "The mouth that breaks the relic is taught to be sacred. The mouth is forgotten by morning."
2. "Every sacred object began as a meal that was deferred."
3. "What is mourned is more carefully eaten the next time."
4. "The shrine outlives the body that made it sacred. This is not a coincidence."
5. "The clearest gods are the next to fall."
6. "Loss is the appetite that keeps the doctrine fed."

---

End of brief.
