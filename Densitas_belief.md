# Densitas — Belief Field Spec (P2)

**Status:** v0.1, 2026-05-20. Implements the central distinguishing mechanic of *Densitas*: belief is a **2D scalar field**, not a global mana bar.

The field arises from citizen positions. Where citizens cluster, belief is dense; where they thin out, belief decays toward zero. Powers query this field at their cast site — local density *is* divine strength.

---

## 1. Pillars

1. **Belief is positional.** A god with 200 citizens scattered along a coast has less power at any one tile than a god with 100 citizens packed around a temple.
2. **Belief has no time-decay.** A citizen contributes the same belief regardless of how long they have lived. Decay happens when citizens *die* or *convert*, not on a clock. (Locked in §13 of the GDD.)
3. **Belief is per-faction.** Each god has their own grid. Conflict surfaces only when the player queries (e.g. "is rival belief dominant on this tile?").
4. **The field is cheap.** Recomputed at the citizen tick rate (5 Hz), not the render rate. Pure function of current positions.

---

## 2. Grid

- **Resolution:** `64 × 48`, mirroring the default `256 × 192`-tile world at 4-tile sampling. One belief cell covers a 4×4 patch of world tiles.
- **Storage:** `numpy.ndarray(shape=(n_factions, grid_h, grid_w), dtype=float32)`.
- **Indexing:** `belief[faction, cy, cx]` where `(cx, cy) = (world_tx // 4, world_ty // 4)`.
- **`n_factions = 2`** in P2 (Open Eye = 0, Maw = 1). The rival faction grid stays empty until P4 spawns rival citizens.

The 64×48 grid is exact for the default world. If world dims aren't multiples of 4, the grid rounds up; trailing cells stay zero.

---

## 3. Kernel

Each tick:

1. Zero the per-faction grid.
2. For each living (non-DYING) citizen, splat `amplitude = 1.0` into their belief cell.
3. Apply 2 passes of a 3-wide separable box blur in each axis.

Two passes of a 3-cell box ≈ a Gaussian with σ ≈ 1.4 cells (≈ 5.6 world tiles). This is the **belief radius** — the distance at which one citizen's contribution falls to ~37% of its peak.

The box blur is **volume-preserving**, so `total(faction) == population(faction)` exactly (mod float drift). This makes the integral interpretable: it equals the citizen count.

Why box blur and not Gaussian? Box blur is O(n) per axis with simple cumulative-sum tricks, and two passes already look smooth at this resolution. We get to skip the SciPy dependency.

---

## 4. Recompute cadence

- Belief recomputes once per **citizen tick** (default 5 Hz).
- Called from `main.py` immediately after `CitizenManager.tick(...)`.
- Cost budget at 200 citizens, 64×48 grid: scatter ~200 writes + 4 passes over 64×48 = ~12K cell touches. Well under a millisecond.

---

## 5. Query API

```python
class BeliefField:
    def query(self, world_tx: int, world_ty: int, faction: int = 0) -> float:
        ...  # returns belief at the given world tile

    def total(self, faction: int = 0) -> float:
        ...  # returns the sum of the field for that faction == population

    def dominant_faction(self, world_tx: int, world_ty: int) -> int | None:
        ...  # which faction has greater belief at this tile, or None if tied/zero

    def grid(self, faction: int = 0) -> np.ndarray:
        ...  # the raw grid for read-only access by the renderer
```

**`query`** is the primitive that future power-casts use. P3 powers multiply their effect by `belief.query(cast_x, cast_y, faction=0)`.

**`dominant_faction`** is the future relic-shatter trigger and CONVERTED-state input. Stubbed in P2; wired in P3/P4.

---

## 6. Regen accounting

P2 does not introduce spending. There is no power-cast verb yet. We expose `total(0)` to the HUD so the player can see their belief tick up as the population grows.

Future (P3): a per-cast cost is subtracted from a `spent_total` running tally. The relevant quantity for tier-gating remains *population* (per the GDD), not belief. Belief is the *per-cast strength multiplier*. Tier eligibility uses population; cast strength uses belief at the cast site.

---

## 7. Overlay

The heatmap overlay is **off by default**. Toggle key: `B`.

- Render path: build a 64×48 RGBA surface once per recompute. Per cell, RGB is faction-tinted (cyan for Open Eye, red-orange for Maw, mixed where both factions overlap), alpha scales with magnitude.
- Upscale via `pygame.transform.scale` to world pixel dimensions, then blit using the existing viewport machinery.
- The overlay sits **above** the world surface but **below** citizen sprites.

When the field is empty, the overlay is fully transparent — toggling shows a clean world.

---

## 8. Faction isolation

- Per-faction grids share no state. Splatting a faction-0 citizen never touches the faction-1 grid.
- Tests assert this explicitly.

---

## 9. Deliberately omitted (P2)

- **Belief decay over time.** Locked out by design (GDD §13).
- **Spend ledger.** No powers yet.
- **Per-tile belief boost from relics.** Relics are P3.
- **Conversion logic.** CONVERTED state is wired in P4.
- **Fog-of-war interaction.** The overlay reveals the full belief field for both factions in P2 for debug ease. P2.5 will clip the rival's belief to player-visible tiles.

---

## 10. Contract with the rest of the codebase

| Caller | Method | When |
|---|---|---|
| `main.py` | `BeliefField(cfg.belief, world, n_factions=2)` | once at world load |
| `main.py` | `belief.recompute(citizen_mgr.citizens)` | after each `citizen_mgr.tick(...)` |
| `hud.py` | `belief.total(0)` | every render frame |
| `render.py` | `belief.grid(faction)` | every recompute, to build overlay surface |
| `main.py` | toggle `show_belief_overlay` | on `K_b` keydown |

The renderer never mutates the field. The citizen manager never reads it.

---

## 11. Tunables (`[belief]` in `config.toml`)

```toml
[belief]
grid_w           = 64       # belief cells across (4 world-tiles per cell at default world)
grid_h           = 48       # belief cells tall
amplitude        = 1.0      # per-citizen splat magnitude
blur_passes      = 2        # box-blur passes
blur_radius      = 1        # cells (kernel width = 2*radius + 1 = 3)
recompute_hz     = 5        # match citizen tick_hz for now
overlay_alpha_max = 180     # 0..255 — peak alpha at the densest cell
```

Open knob: at P3, we may need `belief_radius_cells` separate from blur passes if power-casts want a sharper or wider field than the visual overlay. Park until then.
