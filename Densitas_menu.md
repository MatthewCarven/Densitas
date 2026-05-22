# Densitas — Start Menu + Game State + Session Presets

*v0.1 — 2026-05-21. Implementation spec for the player-facing front door.*

Up to P3 PR2 the game has launched straight into a hard-coded simulation
from `config.toml`. This milestone turns that single entry point into a
real start experience: a title screen, a New Game panel, and a session
preset system that lets the player choose how long they want to play.

The work also forces a long-overdue refactor of `main.py` from "one big
setup pass + one while loop" into a `GameState` machine with a `Game`
object that can be built, torn down, and rebuilt without restarting the
process. That refactor is load-bearing for the pause menu (later) and
the end-of-round screen (P6).

---

## §1 Pillars

1. **The menu is the contract.** Whatever appears on the New Game panel
   is what the engine *guarantees* to honour. If we surface a "Rivals: 2"
   choice, the simulation must spawn two rivals — even if those rivals
   are stub-faction citizens until P4 lands real AI. No fake knobs.
2. **In-engine, single window.** The menu is the first state of the same
   pygame loop the game uses. Same window, same fonts, same parchment +
   cyan/blood palette as the HUD. No tkinter launcher, no separate
   binaries. The architectural payoff: pause menu (P3.5+) and
   end-of-round screen (P6) share the same overlay machinery.
3. **Three paces, one balance pass.** Casual / Standard / Epic differ in
   **world size + tier thresholds only**. Lifespan, hunger rate, food
   regen, belief regen all stay at their tuned defaults — those got a
   playtest pass in P1.5 and we don't want to invalidate the tuning by
   forking the numeric universe. Pace × Size produces a 3×3 matrix of
   sessions; that's enough variety without exploding the balance space.
4. **Six choices on the New Game panel, no more.** God / World size /
   Pace / Rivals / Seed / Begin. Saved games, difficulty, win-condition,
   map type all come later. Choice paralysis is the death of a god game.
5. **Standard is the recommended default.** Pre-selected on first open.
   The "RECOMMENDED" tag sits beside it. Casual and Epic are explicit
   opt-ins for shorter or longer sessions.

---

## §2 GameState machine

`densitas/game.py` introduces a `GameState` enum and a `Game` class that
owns everything a running simulation needs: world, food, citizens,
belief, power system, HUD, renderer, world surface, camera. `main.py`
becomes a thin dispatcher.

```python
class GameState(enum.IntEnum):
    MENU    = 0   # title + New Game panel (this milestone)
    PLAYING = 1   # the simulation runs (current behaviour)
    PAUSED  = 2   # placeholder — stub for now, real pause in P3.5
    ENDED   = 3   # placeholder — win/lose summary in P6
```

State transitions for this milestone:

```
MENU --Begin--> PLAYING --ESC--> MENU  (current behaviour, lifted)
```

PAUSED / ENDED are declared so callers can `if state == GameState.PAUSED`
without an AttributeError when the relevant features ship.

### §2.1 Main loop shape

```python
state = GameState.MENU
menu  = MenuScreen(cfg_defaults, fonts)
game: Optional[Game] = None

while running:
    events = pygame.event.get()
    if state == GameState.MENU:
        menu.handle_events(events)
        if menu.begin_clicked:
            game = Game.from_options(menu.options, cfg_defaults)
            state = GameState.PLAYING
        menu.draw(screen)
    elif state == GameState.PLAYING:
        for e in events:
            if e.type == pygame.KEYDOWN and e.key == pygame.K_ESCAPE \
                    and game.active_mode is None:
                state = GameState.MENU      # back to menu, drop the Game
                game = None
                continue
            game.handle_event(e)
        game.tick(dt, sim_t_ref)
        game.draw(screen)
    pygame.display.flip()
```

Quit (window close) still ends the process; ESC from PLAYING with no
power mode active drops the player back to the menu. ESC with a mode
active continues to cancel the mode (current PR2 behaviour).

### §2.2 Game object

`densitas/game.py :: Game`:

```python
@dataclass
class Game:
    cfg: Config             # the merged config — defaults + preset overrides
    world: World
    food:  FoodField
    citizens: CitizenManager
    belief: BeliefField
    power_system: PowerSystem
    renderer: Renderer
    world_surface: pygame.Surface
    camera: Camera
    hud: HUD
    rhetoric: Rhetoric

    active_mode: Optional[PowerKind] = None
    sim_time: float = 0.0
    sim_accumulator: float = 0.0
    last_cast_failed_at: float = -1.0
    last_cast_reason: str = ""
    show_debug: bool = True
    show_belief_overlay: bool = False
    show_food_overlay: bool = False

    @classmethod
    def from_options(cls, opts: "GameOptions", base_cfg: Config) -> "Game": ...
    def handle_event(self, event: pygame.event.Event) -> None: ...
    def tick(self, dt: float) -> None: ...
    def draw(self, screen: pygame.Surface) -> None: ...
```

The fields are the same things `main.py` currently builds locally —
they're just pulled together so the state machine can construct and
discard them as one unit.

---

## §3 GameOptions

`densitas/game.py :: GameOptions` is the menu's output and `Game`'s
input. Frozen dataclass, no hidden state.

```python
@dataclass(frozen=True)
class GameOptions:
    god: int               # 0 = Open Eye, 1 = Maw (P4 unlocks 1)
    world_size: WorldSize  # SMALL / MEDIUM / LARGE
    pace: PaceLevel        # CASUAL / STANDARD / EPIC
    rival_count: int       # 0..3
    seed: int              # 0 = "random"; menu rolls a fresh one on Begin
```

When the menu calls `Game.from_options(opts, base_cfg)`:

1. Merge the preset overrides into `base_cfg` (see §4).
2. Generate world with the merged WorldConfig.
3. Build food / citizens / belief as today.
4. If `rival_count > 0`, call `citizens.spawn_rival_stub(world, n=rival_count_to_citizen_count(rival_count), faction=1, seed=opts.seed^1)`.
5. Wire PowerSystem (with the mutate_tile closure, per PR2).

`rival_count_to_citizen_count`: maps the human-facing rival count to
the stub-spawn population per rival. P3.5 placeholder formula:
`rivals * 8` (so 1 rival = 8 stub citizens at the canonical 3/4-across,
mid-height spawn point). P4 replaces this with real AI start state.

---

## §4 Preset system

`densitas/presets.py` is a small lookup module — no behaviour, pure
data — that maps PaceLevel × WorldSize to a numeric override dict.

### §4.1 Enums

```python
class WorldSize(enum.IntEnum):
    SMALL  = 0   # 128 x 96  — quick board
    MEDIUM = 1   # 256 x 192 — current default
    LARGE  = 2   # 512 x 384 — epic-scale

class PaceLevel(enum.IntEnum):
    CASUAL   = 0
    STANDARD = 1
    EPIC     = 2
```

### §4.2 Tier-threshold presets (the only Pace-driven knob)

| Pace     | T0 | T1  | T2  | T3   | T4   | Sim arc to T4 (est)  |
|----------|----|-----|-----|------|------|----------------------|
| CASUAL   | 1  | 8   | 40  | 200  | 800  | 15–25 real-time min  |
| STANDARD | 1  | 10  | 100 | 1000 | 5000 | 45–90 real-time min  |
| EPIC     | 1  | 12  | 120 | 1500 | 8000 | 2–4 hours            |

STANDARD matches the current hard-coded `TIERS` in `citizen.py`.
CASUAL drops thresholds to scale population pressure to a lunch session.
EPIC bumps T4 to 8000 to make Apocalypse a genuine late-game milestone
rather than something a Standard-tuning player blunders into.

### §4.3 World-size presets

| Size   | width × height | tile_size px | spawn radius | rationale                |
|--------|----------------|--------------|--------------|--------------------------|
| SMALL  | 128 × 96       | 16           | 4            | fast world-gen, full HUD |
| MEDIUM | 256 × 192      | 16           | 5            | current default          |
| LARGE  | 512 × 384      | 12           | 7            | smaller tile px so the   |
|        |                |              |              | viewport still shows arc |

### §4.4 Lookup shape

```python
@dataclass(frozen=True)
class PresetBundle:
    tiers: tuple[tuple[str, int], ...]
    world: dict      # WorldConfig field overrides
    citizen: dict    # CitizenConfig field overrides (just spawn_radius_tiles for now)

PRESETS: dict[tuple[PaceLevel, WorldSize], PresetBundle] = { ... }

def merge(base: Config, opts: GameOptions) -> Config:
    """Return a new Config with preset overrides applied. base is unchanged."""
```

`merge` uses `dataclasses.replace` so the original `Config` stays
immutable.

---

## §5 Tier thresholds — moving from constant to config

Currently `densitas/citizen.py` has:

```python
TIERS: tuple[tuple[str, int], ...] = (
    ("T0 Whisper", 1), ("T1 Blessing", 10), ...
)
def tier_for(population: int) -> tuple[str, int]: ...
```

This becomes:

```python
DEFAULT_TIERS = (...)   # the STANDARD preset, used when no override

def tier_for(population: int,
             tiers: tuple[tuple[str, int], ...] = DEFAULT_TIERS
             ) -> tuple[str, int]: ...
```

Call-site updates:

| Site                       | Change                                    |
|----------------------------|-------------------------------------------|
| `powers.py :: can_cast`    | `tier_for(pop, self.cfg.tiers)`           |
| `hud.py :: draw`           | takes `tiers` arg from `Game`             |
| `tests/test_powers.py`     | `tier_for(...)` calls already work — the default unchanged |
| `tests/test_citizen.py`    | ditto                                     |

A new `tiers: tuple[tuple[str, int], ...]` field is added to `PowerConfig`
(it's the natural home — the tier gate is checked by the power system).
Default is `DEFAULT_TIERS`; presets override.

---

## §6 Menu UI

`densitas/menu.py` — pure pygame, no third-party widget kit. Buttons
are rendered as parchment-bordered rounded rects with the same fonts as
the HUD.

### §6.1 Title screen

```
                 ╔═════════════════════════════════════════╗
                 ║                                         ║
                 ║                D E N S I T A S          ║
                 ║                                         ║
                 ║       belief is what they are given,    ║
                 ║       not what they freely hold         ║
                 ║                                         ║
                 ║         ┌───────────────────────┐       ║
                 ║         │     NEW GAME          │       ║
                 ║         └───────────────────────┘       ║
                 ║         ┌───────────────────────┐       ║
                 ║         │  Continue  (greyed)   │       ║
                 ║         └───────────────────────┘       ║
                 ║         ┌───────────────────────┐       ║
                 ║         │      QUIT             │       ║
                 ║         └───────────────────────┘       ║
                 ║                                         ║
                 ╚═════════════════════════════════════════╝
```

Subtitle is one of three rotating epigraphs (deterministic, indexed by
day-of-year) so returning players see slight variation. Settings button
is deferred — not on the menu until we have settings to put on it.

### §6.2 New Game panel

Clicking NEW GAME slides the panel in from the right (or just fades in
— fade is cheaper to implement first; slide is a polish pass).

```
┌─ NEW GAME ────────────────────────────┐
│                                       │
│  GOD                                  │
│   ◉ Open Eye    ○ Maw                 │
│                                       │
│  WORLD SIZE                           │
│   ○ Small   ◉ Medium   ○ Large        │
│                                       │
│  PACE                                 │
│   ○ Casual  ◉ Standard (rec.)  ○ Epic │
│                                       │
│  RIVALS                               │
│   ◉ None   ○ 1   ○ 2   ○ 3            │
│                                       │
│  SEED                                 │
│   ◉ Random   ○ Custom: [____42____]   │
│                                       │
│            ┌─────────────┐            │
│            │    BEGIN    │            │
│            └─────────────┘            │
│                                       │
│  ← back                               │
│                                       │
└───────────────────────────────────────┘
```

Radio buttons are mouse-and-keyboard navigable: number keys 1–4 cycle
options within the focused row, arrow keys move between rows.
Tab/Shift-Tab also moves between rows for accessibility.

### §6.3 Visual style

* Parchment background (`(216, 201, 168)` at 90% alpha over the dark
  panel).
* Selected radio: cyan dot (Open Eye palette) for player faction 0.
* Unselected radio: dim outline.
* Hover: subtle parchment glow on the row.
* BEGIN button: parchment background with cyan border; greys out if the
  options state is invalid (currently can't be — every field has a
  default — but the affordance is reserved for save-game errors later).

### §6.4 Rhetoric on the menu

The subtitle rotates one of three lines (deterministic by date):

```python
EPIGRAPHS = [
    "belief is what they are given, not what they freely hold",
    "the world is the proof of the god that watches it",
    "what is not seen does not exist",
]
```

The third is The Open Eye's doctrine; the second is the line that names
the game's central thesis; the first is the subtitle of `Densitas_GDD.md`.
This grounds the menu in the same voice as the scripture log.

---

## §7 Input bindings (menu mode)

| Key / mouse          | Action                                          |
|----------------------|-------------------------------------------------|
| `↑` / `↓`            | Move focus between rows (or menu buttons)       |
| `←` / `→`            | Cycle option within focused row                 |
| `1`-`4`              | Pick option N within focused row                |
| `Tab` / `Shift+Tab`  | Same as ↑/↓                                     |
| `Enter`              | Activate focused button (NEW GAME / BEGIN)      |
| `Esc`                | If New Game panel open → close it. Else → quit. |
| Mouse click          | Standard radio / button hit                     |
| Mouse hover          | Highlight row / button                          |

The in-PLAYING bindings (1-7 for power modes, B/F overlays, F3 debug,
etc.) are unchanged.

---

## §8 Config schema additions

`densitas/config.py` gains:

```python
@dataclass(frozen=True)
class TierSpec:
    name: str
    threshold: int

@dataclass(frozen=True)
class SessionConfig:
    default_god: int           # 0 Open Eye, 1 Maw
    default_pace: str          # "casual" / "standard" / "epic"
    default_world_size: str    # "small" / "medium" / "large"
    default_rival_count: int   # 0..3
    epigraph_seed: int         # so epigraph rotation is testable
```

The existing `PowerConfig` gains a `tiers: tuple[TierSpec, ...]` field
(default = DEFAULT_TIERS). Presets fill it.

`config.toml`:

```toml
[session]
default_god         = 0       # 0=Open Eye, 1=Maw
default_pace        = "standard"
default_world_size  = "medium"
default_rival_count = 0
epigraph_seed       = 0       # 0 = rotate by date

[[powers.tiers]]    # TOML array-of-tables — repeats per tier
name      = "T0 Whisper"
threshold = 1

[[powers.tiers]]
name      = "T1 Blessing"
threshold = 10

# ...repeated for T2-T4
```

When a preset overrides tiers, the `Game.from_options` step replaces
`cfg.powers.tiers` via `dataclasses.replace`.

---

## §9 Tests (target: 15 new, total 93)

`tests/test_presets.py` (8 tests):

1. `merge` returns a new Config; the input is unchanged.
2. STANDARD + MEDIUM matches the default `config.toml` numbers exactly.
3. CASUAL drops T4 to 800; EPIC raises T4 to 8000.
4. SMALL gives a 128 × 96 world; LARGE gives 512 × 384.
5. Unknown (pace, size) combination raises a clear `KeyError`.
6. Tier thresholds round-trip through `tier_for(pop, tiers=cfg.powers.tiers)`.
7. `rival_count` of 0 spawns zero rivals; 3 spawns 24 stub citizens.
8. Seed of 0 in opts → `Game.from_options` rolls a fresh random seed.

`tests/test_game.py` (4 tests):

9. `Game.from_options(opts, cfg)` builds without crashing for every
   (god, size, pace, rival_count) cross-product.
10. After construction, `game.tick(0.2)` runs cleanly five times — sim
    advances, no exceptions.
11. `game.draw(headless_surface)` paints without crashing in dummy SDL.
12. ESC in PLAYING with no `active_mode` returns the state machine to
    MENU (tested via main-loop harness, not pure Game).

`tests/test_menu.py` (3 tests):

13. Default focus on first open is the BEGIN row of NEW GAME (after
    NEW GAME clicked).
14. Pressing `2` on the focused GOD row selects Maw.
15. `MenuScreen.options` reflects user choices after a sequence of
    radio toggles.

Existing 78 tests must still pass after the `tier_for(pop, tiers)`
signature change — the default arg keeps them green without edits.

---

## §10 File impact

| Surface                 | Owner   | Change                                                          |
|-------------------------|---------|-----------------------------------------------------------------|
| `densitas/menu.py`      | new     | `MenuScreen`, `NewGamePanel`, `RadioRow`, `Button` widgets      |
| `densitas/presets.py`   | new     | `WorldSize`, `PaceLevel`, `PresetBundle`, `PRESETS`, `merge`    |
| `densitas/game.py`      | new     | `GameState`, `GameOptions`, `Game` dataclass + `from_options`   |
| `densitas/main.py`      | gut     | state-machine dispatcher; setup pulled into `Game.from_options` |
| `densitas/config.py`    | extend  | `SessionConfig`, `TierSpec`, `[session]` block, `tiers` on PowerConfig |
| `densitas/citizen.py`   | tweak   | `tier_for(pop, tiers=DEFAULT_TIERS)` signature                  |
| `densitas/powers.py`    | tweak   | pass `self.cfg.tiers` into `tier_for(...)`                      |
| `densitas/hud.py`       | tweak   | accept `tiers` arg into `draw()`                                |
| `config.toml`           | extend  | `[session]` block + `[[powers.tiers]]` array-of-tables          |
| `tests/test_presets.py` | new     | 8 tests                                                         |
| `tests/test_game.py`    | new     | 4 tests                                                         |
| `tests/test_menu.py`    | new     | 3 tests                                                         |
| `Densitas_menu.md`      | new     | this spec                                                       |
| `WORKLOG.md` / `TODO.md` / `README.md` | extend | menu PR status + new keybindings              |

Total: 3 new modules + 3 new test files + 1 new spec + 6 modified
modules + 1 modified config + 3 modified docs. The menu shipped, the
state machine shipped, the preset system shipped — all in one PR.

---

## §11 PR slicing

One PR for the lot. The pieces are interdependent enough that landing
them separately would leave the codebase in a "menu shows but doesn't
launch a game" state for the duration of the intermediate commits.

Internal sequence (so I work top-down rather than getting lost):

1. **`Densitas_menu.md`** (this doc) — sign-off gate.
2. **`densitas/presets.py`** + `tests/test_presets.py` — leaf module,
   no deps on the rest of the code. 8 tests pass.
3. **`densitas/config.py` + `config.toml`** — `SessionConfig`,
   `TierSpec`, `tiers` field on PowerConfig. Existing tests still pass
   because `tier_for`'s default arg holds.
4. **`densitas/citizen.py` + `densitas/powers.py` + `densitas/hud.py`**
   — call-site updates for `tier_for(pop, tiers)`. All 78 prior tests
   still pass.
5. **`densitas/game.py`** + `tests/test_game.py` — pulls today's
   `main.py` setup into a class. 4 tests pass.
6. **`densitas/menu.py`** + `tests/test_menu.py` — pure UI. 3 tests
   pass.
7. **`densitas/main.py`** rewrite — state-machine dispatcher. Headless
   smoke test: import, build Game from default options, tick five sim
   seconds, exit clean.
8. **Doc updates** — TODO checks, WORKLOG entry, README status row,
   README keybindings.

Each step has its own commit-worthy test bar. If we have to bail mid-PR
the codebase stays green at the most recent boundary.

---

## §12 Acceptance criteria

After this milestone ships:

* Launching the game shows the title screen, NOT the simulation.
* Clicking NEW GAME opens the panel with God / Size / Pace / Rivals /
  Seed pre-filled to the defaults from `config.toml`.
* Clicking BEGIN with Casual + Small + 0 rivals starts a 128 × 96
  simulation with tier thresholds 1 / 8 / 40 / 200 / 800.
* Clicking BEGIN with Epic + Large + 3 rivals starts a 512 × 384
  simulation with 24 faction-1 stub citizens spawned at the canonical
  rival origin.
* ESC during PLAYING (no power mode) returns to the menu; clicking
  NEW GAME + BEGIN starts a fresh simulation in the same process.
* Existing P0-P3 behaviour inside PLAYING is unchanged.
* All 93 tests pass.

---

## §13 Deferred / out of scope

* **Save / load.** The "Continue" button is greyed out. Comes with P6.
* **Settings screen.** No options worth the screen yet (no audio, no
  rebindable keys, no graphics options). Reserve the architectural seam
  by leaving GameState.PAUSED declared.
* **Pause menu.** GameState.PAUSED is declared but PLAYING doesn't
  transition into it; P3.5 lands real pause.
* **End-of-round summary.** GameState.ENDED is declared but unused.
  Ships with P6 win/lose.
* **Difficulty / win-condition pickers.** Two more rows worth adding to
  the panel once P4 (rival AI) and P6 (win conditions) exist.
* **Menu epigraph rotation by playtime.** Currently date-based; could
  evolve to "lines unlock as you reach milestones" but that's a polish
  pass for after P6.
* **Animated background.** A tiny world generated in the background
  with citizens wandering on the title screen would be lovely. After P4
  / P5 when we have visual richness to show off; not now.

---

## §14 Open questions

None as of v0.1. Matthew picked the three big forks (Full set, In-engine,
World-size + tier thresholds only) in the 2026-05-21 design pass.

If anything in this spec doesn't match what was discussed, **flag it**
before §11 step 2 starts — once the presets module lands, the rest of
the work is mechanical.

---

*Spec ends.*
