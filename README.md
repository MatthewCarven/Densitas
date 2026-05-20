# Densitas — Prototype

A god game where belief is density. See `Densitas_GDD.md` for the full design.

## Current milestone — P0: Pixel world

A tile world generated from multi-octave value noise, pre-rendered as pixel-art,
and a scrollable camera. No citizens yet, no powers yet, no rival god yet.

## Running it

Requires **Python 3.10+** (uses `tomllib` on 3.11+ and falls back to the
`tomli` backport on 3.10 — declared in `requirements.txt`).

```bash
pip install -r requirements.txt
python -m densitas.main
```

### A note on pygame-ce

We use **pygame-ce** (the community-edition fork) rather than upstream pygame.
The two are API-compatible — both ship as `import pygame` — but pygame-ce is
the actively-maintained fork and is the recommended choice for new projects.

If you already have upstream `pygame` installed in your environment, **uninstall
it first** before installing pygame-ce; they share the `pygame` namespace and
can't coexist:

```bash
pip uninstall pygame      # if upstream pygame is installed
pip install -r requirements.txt
```

If you ever need to confirm which fork is running, `pygame.IS_CE` is `1` on
pygame-ce and absent on upstream.

## Controls

- **WASD** / **arrow keys** — scroll
- **Mouse to screen edge** — edge-scroll
- **F3** — toggle debug overlay
- **ESC** — quit

## Configuration

Tunable parameters live in `config.toml`. Edit the file, restart the game.
The schema is validated by `densitas/config.py`; an extra or missing key will
raise a clear error at startup.

Notable knobs for P0:

| Key | Meaning |
|-----|---------|
| `world.seed` | Noise seed. Change for a new map. |
| `world.width`, `world.height` | Map shape in tiles. |
| `world.sea_level` … `world.mountain_thresh` | Biome cutoffs on the 0–1 heightmap. |
| `render.art_style` | `"pixel"` (active) or `"vector"` (not yet implemented; raises). |
| `render.tile_size` | Pixels per tile at native zoom. 16 by default. |
| `render.viewport_w`, `render.viewport_h` | Window size. |
| `camera.scroll_speed` | Tiles per second when scrolling. |
| `camera.edge_scroll_px` | Distance from edge that triggers mouse-scroll. |

## Art direction

The renderer is intentionally abstracted: a `Renderer` abstract base class
with two intended implementations:

- **`PixelRenderer` — active.** Procedural pixel-art tile sprites (4 variants
  per tile type) painted at startup, blitted into a pre-rendered world surface.
- **`VectorRenderer` — TODO.** Will draw tiles with `pygame.draw` primitives
  (filled polygons, no sprites). Same `build_world_surface` contract, so
  swapping is a one-line config change.

To switch styles later: change `render.art_style` in `config.toml`. To
implement the vector style: subclass `Renderer` in `densitas/render.py`, add
a branch to `make_renderer()`, done.

## Project layout

```
densitas/
  __init__.py
  main.py        # entry point + game loop
  config.py     # config loader (tomllib / tomli fallback)
  world.py      # World, Tile, multi-octave value noise terrain
  camera.py     # Camera state + WASD/arrow/edge-scroll input
  render.py     # Renderer ABC + PixelRenderer
tests/
  test_world.py  # ~8 unit tests, no pygame display required
config.toml      # all tunable parameters
```

## Tests

```bash
python -m pytest tests/      # if you have pytest
python tests/test_world.py    # direct, no pytest needed
```

The tests don't open a display — they verify world generation, determinism,
tile classification, and camera math. The rendering path is best verified by
running the game once and looking at the result.

## Next milestones

- **P1 — Citizens exist.** 16-tall pixel-art citizen sprites, wander/forage
  behavior, reproduction, population counter in HUD.
- **P2 — Belief field.** 64×64 belief grid, heatmap overlay (off by default,
  toggle with `B`).
- **P2.5 — Fog of war.** Per-god visibility; relic placement constrained.
- **P3 — Powers T0–T1 + Relics.** First playable god, three starting relics.
- … see `TODO.md` for the full backlog.
