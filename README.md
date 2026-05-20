# Densitas

> A god game where belief is density.

<p align="center">
  <img src="docs/p0_world.png" alt="A procedurally-generated continent — coastline, forest, hills, mountains." width="800">
</p>

## What it is

Densitas is a top-down god game in the spirit of *Populous*, with one
distinguishing mechanic: **belief is a 2D density field, not a global mana bar.**
Citizens radiate a small aura of faith around themselves. Where they cluster,
belief intensifies. Where belief intensifies, the god can act. Where belief is
thin, the god is nearly powerless.

Total population determines which **tiers of godly power** are unlocked.
Local population density determines **how potent any given act of power can be
at a specific place**. A spell cast in the heart of your capital and the same
spell cast at the edge of the wilderness produce very different results.

The full design lives in [`Densitas_GDD.md`](Densitas_GDD.md).

## The two gods

<table>
  <tr>
    <td width="50%" align="center">
      <img src="docs/glyph_open_eye.png" alt="The Open Eye glyph" width="160"><br>
      <b>The Open Eye</b><br>
      <i>Order of the Witnessing</i>
    </td>
    <td width="50%" align="center">
      <img src="docs/glyph_maw.png" alt="The Maw glyph" width="160"><br>
      <b>The Maw</b><br>
      <i>Order of the Hungry</i>
    </td>
  </tr>
  <tr>
    <td>
      <blockquote>What is not seen does not exist. The gaze of the god grants the world its reality.</blockquote>
    </td>
    <td>
      <blockquote>Hunger is the only honest emotion. To be devoured is to be made holy.</blockquote>
    </td>
  </tr>
</table>

Full theology, plus three more sketched gods (The Open Hand, The Numbering,
The Empty Throne) and a handful of heresies, in
[`Densitas_lore_pantheon.md`](Densitas_lore_pantheon.md).

## Status

| Milestone | State |
|-----------|-------|
| **P0 — Pixel world** (tile map, terrain, camera, debug HUD) | ✅ shipped |
| P1 — Citizens exist (16-tall pixel sprites, wander, reproduce) | next |
| P2 — Belief field (density grid, heatmap overlay) | planned |
| P2.5 — Fog of war | planned |
| P3 — Powers T0–T1 + Religious Relics | planned |
| P4 — Rival god AI | planned |
| P5 — Tiers T2–T4 (Tempest, Cataclysm, Apocalypse) | planned |
| P6 — Win/lose conditions + polish | planned |

Full backlog in [`TODO.md`](TODO.md); history of decisions in [`WORKLOG.md`](WORKLOG.md).

## Running it

Requires **Python 3.10+** (uses stdlib `tomllib` on 3.11+ and the `tomli`
backport on 3.10 — both declared in `requirements.txt`).

```bash
pip install -r requirements.txt
python -m densitas.main
```

### A note on pygame-ce

Densitas uses **pygame-ce** (the community-edition fork) rather than upstream
pygame. The two are API-compatible — both ship as `import pygame` — but
pygame-ce is the actively-maintained fork and is the recommended choice for
new projects.

If you already have upstream `pygame` installed in your environment,
**uninstall it first** before installing pygame-ce; they share the `pygame`
namespace and cannot coexist:

```bash
pip uninstall pygame
pip install -r requirements.txt
```

To confirm which fork you're running: `pygame.IS_CE` is `1` on pygame-ce and
absent on upstream.

## Controls

- **WASD** / **arrow keys** — scroll the map
- **Mouse to screen edge** — edge-scroll
- **F3** — toggle debug overlay
- **ESC** — quit

## Configuration

Every tunable parameter lives in [`config.toml`](config.toml). Edit a value,
restart the game. The schema is validated by `densitas/config.py`; a missing
or extra key raises a clear error at startup.

The most useful knobs for P0:

| Key | Meaning |
|-----|---------|
| `world.seed` | Noise seed. Change for a new map. |
| `world.width`, `world.height` | Map shape in tiles (default 256×192). |
| `world.sea_level` … `world.mountain_thresh` | Biome cutoffs on the 0–1 heightmap. |
| `render.art_style` | `"pixel"` (active) or `"vector"` (planned). |
| `render.tile_size` | Pixels per tile at native zoom (default 16). 