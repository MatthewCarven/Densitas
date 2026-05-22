# Densitas — Cast Queue (Raise / Lower)

*v0.1 — 2026-05-21. Short spec for the click-to-queue terrain workflow.*

While playtesting P3 PR2, sculpting any meaningful coastline became a
clicky exercise in waiting out the 2 s cooldown. The Cast Queue feature
lets the player click a chain of Raise (or Lower) tiles and have the
engine drip-feed them through the existing cooldown machinery, with
visible feedback on both the map and the HUD.

This is a small, contained feature — one new dataclass, one new tick
step, one new render method, ~150 LOC + 7 tests. It ships in front of
the Menu PR because Matthew wants to *play* with this immediately.

---

## §1 Pillars

1. **Enqueue debits, cancel refunds.** Clicking to queue immediately
   pulls `spec.belief_cost` from the pool. Cancelling refunds it. No
   mid-batch "you ran out" surprises; the cost is visible the moment
   you commit.
2. **Raise and Lower only.** Other powers (Inspire, Calm, Hunger Pang,
   Bless, Curse) keep the existing fire-once-on-LMB behaviour. The
   queue exists to solve a specific terrain-sculpting pain; Bless/Curse
   queues feel artificial. Architecture supports extending later.
3. **Visible state, always.** Every queued tile gets a chevron overlay
   on the map; the HUD cooldown row gets a count badge. The player
   never has to remember what's in the queue.
4. **Re-validate at dispatch, burn on invalid.** A queued tile's state
   may shift before its turn (another cast lowered it; a Bless landed).
   If `_tile_valid_for` fails at dispatch, the cast is silently
   discarded — belief stays spent, scripture log records a one-liner.
   The gesture happened; the world moved on.
5. **Same cooldown machinery as direct casts.** A drained queue entry
   takes the cooldown exactly as if the player had clicked. Queue
   length × cooldown is the wildly-inaccurate ETA shown on hover.

---

## §2 Data model

`densitas/powers.py` gains:

```python
@dataclass
class QueuedCast:
    kind: PowerKind        # PowerKind.RAISE or PowerKind.LOWER
    faction: int
    tx: int
    ty: int
    queued_at: float       # sim_t at enqueue (for ETA, FIFO ordering)
    paid: float            # belief_cost actually debited (for refund accuracy)
```

`PowerSystem` gains:

```python
self.queues: dict[tuple[int, int], list[QueuedCast]] = {}
self.cfg_queue_cap: int = self.cfg.queue_cap   # default 16 per (faction, kind)
```

Key shape `(faction, int(kind))` mirrors the cooldowns dict so the same
lookup logic applies. List = FIFO; pop from the front, push at the back.

---

## §3 Lifecycle in `tick()`

Drain step added after the existing tick body. Order matters: regen +
cooldown bleed happen first so a just-cleared cooldown can dispatch in
the same tick.

```python
def tick(self, dt, citizens, sim_t):
    # 1. Pool regen          (existing)
    # 2. Cooldown bleed      (existing)
    # 3. Effect timers       (existing)
    # 4. Scripture log fade  (existing)
    # 5. NEW: Drain queues.
    for (faction, kind_val), q in list(self.queues.items()):
        if not q:                                        # empty list
            continue
        if self.cooldowns.get((faction, kind_val), 0.0) > 0.0:
            continue                                     # still cooling
        qc = q.pop(0)                                    # FIFO
        self._dispatch_queued(qc, citizens, sim_t)
        if not q:
            del self.queues[(faction, kind_val)]
```

`_dispatch_queued(qc, citizens, sim_t)` re-validates the tile, sets the
cooldown, runs the dispatch table entry, and emits a scripture line.
On re-validation failure, emits a "wasted gesture" line (rhetoric key
`"queued_invalid"`) and consumes the cooldown anyway so spamming
invalid queues doesn't avoid the cooldown bill.

---

## §4 `cast_or_queue` entry point

```python
def cast_or_queue(self, kind, faction, tx, ty, citizens, world, food,
                   belief, sim_t) -> CastReceipt:
    """If the power is ready (no cooldown), behave like cast(). If on
    cooldown AND kind is queueable, enqueue. Else return the same
    failure receipt cast() would."""
    if not _is_queueable(kind):
        return self.cast(kind, faction, tx, ty, citizens, world, food,
                         belief, sim_t)
    # Ready -> immediate fire (which sets cooldown, debits, dispatches).
    if self.cooldowns.get((faction, int(kind)), 0.0) <= 0.0 \
       and not self.queues.get((faction, int(kind)), []):
        return self.cast(kind, faction, tx, ty, citizens, world, food,
                         belief, sim_t)
    # Queue path — validate, debit, append.
    ok, reason = self.can_cast(kind, faction, tx, ty, citizens, world,
                               skip_cooldown=True)
    if not ok:
        return CastReceipt(kind, faction, tx, ty, sim_t, sim_t,
                           ok=False, reason=reason)
    spec = POWERS[kind]
    q = self.queues.setdefault((faction, int(kind)), [])
    if len(q) >= self.cfg.queue_cap:
        return CastReceipt(kind, faction, tx, ty, sim_t, sim_t,
                           ok=False, reason="queue full")
    self.pool[faction] -= spec.belief_cost
    q.append(QueuedCast(kind=kind, faction=faction, tx=tx, ty=ty,
                         queued_at=sim_t, paid=spec.belief_cost))
    return CastReceipt(kind, faction, tx, ty, sim_t, sim_t,
                       ok=True, reason="queued")
```

Why a separate entry point: `cast()` stays the pure single-shot contract
the tests depend on. `cast_or_queue()` is what `main.py` calls from
LMB. The tests that exercise queuing call it directly; the tests that
exercise immediate casts keep using `cast()` unchanged.

`can_cast(..., skip_cooldown=True)` is the only signature change to
the existing public API — defaults to False so behaviour is preserved
for every call site that doesn't opt in.

### §4.1 `_is_queueable`

```python
QUEUEABLE_KINDS: frozenset[int] = frozenset({
    int(PowerKind.RAISE), int(PowerKind.LOWER),
})
def _is_queueable(kind: PowerKind) -> bool:
    return int(kind) in QUEUEABLE_KINDS
```

One line to change later if we extend.

---

## §5 Cancel mechanics

Two surfaces, both implemented:

### §5.1 RMB on a queued tile (in matching mode)

```python
def cancel_queued_at(self, tx, ty, kind, faction) -> bool:
    """Remove the first QueuedCast matching (tx, ty, kind, faction) and
    refund its `paid` cost. Returns True if something was cancelled."""
    q = self.queues.get((faction, int(kind)))
    if not q:
        return False
    for i, qc in enumerate(q):
        if qc.tx == int(tx) and qc.ty == int(ty):
            self.pool[faction] += qc.paid
            del q[i]
            if not q:
                del self.queues[(faction, int(kind))]
            return True
    return False
```

In `main.py`, the existing RMB handler grows a prelude:

```python
elif event.button == 3:  # RMB
    if active_mode in (PowerKind.RAISE, PowerKind.LOWER) and pygame.mouse.get_focused():
        mx, my = event.pos
        tx, ty = _screen_to_tile(mx, my, cam, cfg)
        if power_system.cancel_queued_at(tx, ty, active_mode, faction=0):
            continue   # consumed; don't fall through to mode-cancel
    active_mode = None
```

So RMB on a queued tile cancels that tile; RMB elsewhere (or on no
tile) keeps doing what it does today (exits the mode).

### §5.2 `C` clears the current mode's queue

```python
def clear_queue(self, kind, faction) -> int:
    """Refund every queued cast for (kind, faction). Returns count cleared."""
    q = self.queues.pop((faction, int(kind)), [])
    refund = sum(qc.paid for qc in q)
    self.pool[faction] += refund
    return len(q)
```

`main.py` key handler:

```python
elif event.key == pygame.K_c:
    if active_mode in (PowerKind.RAISE, PowerKind.LOWER):
        n = power_system.clear_queue(active_mode, faction=0)
        if n:
            print(f"cleared {n} from queue")   # later: HUD flash
```

`C` outside of Raise/Lower mode is a no-op (preserves the key for
future use without binding it globally).

---

## §6 Visible feedback

### §6.1 Map chevrons

New abstract method `Renderer.blit_cast_queue(screen, queues, font,
cam_x, cam_y)`. `PixelRenderer` paints:

* **Amber ▲** centred on each queued Raise tile (16 × 16 alpha-blended
  shape, drawn over the tile surface and under the citizens for clarity).
* **Brown ▼** for queued Lower.
* Tiny **1-digit position number** in the upper-right of the chevron
  (queue position; goes up to 9 — beyond that we just stop drawing the
  digit since the chevron is the load-bearing signal).
* Chevrons drawn for ALL queued casts of the player faction, regardless
  of which mode is active — so you see your Raise queue even while
  you've switched to Lower.

Drawn after `blit_citizens` and before `blit_cast_preview` so the
preview AoE always sits on top.

### §6.2 HUD count badge

`hud.py :: _draw_cooldown_row` grows: if a power has a non-empty
queue, paint a small superscript number in the upper-right corner of
the icon. Uses `font_small` (11 px) in `HUD_AMBER` so it's visible
against the parchment background.

```python
n_queued = len(powers.queues.get((0, kind_val), []))
if n_queued:
    badge = self.font_small.render(str(n_queued), True, HUD_AMBER)
    screen.blit(badge, (icon_x + icon_w - badge.get_width() - 2,
                        icon_y + 2))
```

Hover tooltip — `"queued: N · next in ~{N×cooldown:.1f}s"` — is left to
a polish pass.

### §6.3 Debug overlay line

`_draw_debug` in `main.py` gets one more line:

```
Queue:  R x 3 (next 1.4s)  L x 0
```

Same wildly-inaccurate ETA.

---

## §7 Edge cases

* **Queue while cooldown is exactly zero, queue non-empty.** The
  `cast_or_queue` "ready path" requires *both* cooldown clear AND
  queue empty — otherwise the new click jumps ahead of already-queued
  tiles. Always append to the back.
* **Tile state changes between enqueue and dispatch.** Re-validate via
  `_tile_valid_for`. On fail, log a `queued_invalid` rhetoric line,
  set the cooldown anyway, do not refund. The world ate the gesture.
* **Faction dies / population drops below tier between enqueue and
  dispatch.** Same handling as tile change — re-validate, fail-silent,
  no refund. Tier was met at enqueue; the rite was witnessed by enough
  faithful at that moment.
* **Queue cap exceeded.** New enqueue returns `CastReceipt(ok=False,
  reason="queue full")`. Default cap 16 per (faction, kind); tunable.
* **`C` pressed with empty queue.** No-op, no flash.
* **Mode-switch while queue is non-empty.** Queue persists. Switching
  from Raise to Lower doesn't drop Raise's queue.
* **Pool refund on cancel exceeds soft cap.** P3 has no pool cap;
  refund applies unconditionally. P5 soft cap (`TODO(P5)`) will need
  to decide.

---

## §8 Config schema

`densitas/config.py :: PowerConfig` grows one field:

```python
queue_cap: int = 16   # max queued casts per (faction, queueable kind)
```

`config.toml`:

```toml
[powers]
# ... existing fields ...
queue_cap = 16
```

Default 16 is plenty for ergonomic chains and small enough that a
runaway-finger doesn't queue 200 casts at once. A coastline rework
is typically 5-12 tiles.

---

## §9 Tests (target: 7, total 85)

`tests/test_powers.py` appends:

25. `cast_or_queue` on a ready Raise fires immediately (same as `cast`).
26. `cast_or_queue` on a cooling Raise enqueues; pool drops by 5;
    queue length is 1.
27. Two enqueues + one tick past cooldown → first dispatches, queue
    length 1, world.tiles updated.
28. `cancel_queued_at(tx, ty, RAISE, 0)` removes one entry and refunds
    the cost.
29. `clear_queue(RAISE, 0)` removes all entries and refunds the sum.
30. Queued cast becomes invalid before dispatch (manually mutate tile
    to MOUNTAIN) → drained silently, pool *not* refunded, cooldown
    set, scripture line emitted with `queued_invalid` key.
31. Queue cap (set to 3) — 4th enqueue fails with `"queue full"`,
    pool unchanged.

Existing 78 tests stay green — `cast()`, `can_cast()` (with default
`skip_cooldown=False`), and the dispatch machinery are unchanged.

---

## §10 File impact

| Surface              | Owner   | Change                                              |
|----------------------|---------|-----------------------------------------------------|
| `densitas/powers.py` | extend  | `QueuedCast`, `queues`, `cast_or_queue`, drain in tick, `cancel_queued_at`, `clear_queue`, `_is_queueable`, `skip_cooldown` flag on `can_cast` |
| `densitas/render.py` | extend  | `Renderer.blit_cast_queue` abstract + `PixelRenderer` impl (chevron painter) |
| `densitas/hud.py`    | tweak   | queue-count superscript on cooldown row icons       |
| `densitas/main.py`   | tweak   | LMB → `cast_or_queue`, RMB-on-tile-cancels-first, `C` clears, debug overlay line |
| `densitas/config.py` + `config.toml` | extend | `queue_cap`             |
| `densitas/rhetoric.py` + `rhetoric.json` | extend | `queued_invalid` lines for Open Eye (Maw lines deferred to P4) |
| `tests/test_powers.py` | extend | tests 25-31                                        |
| `Densitas_queue.md`  | new     | this spec                                           |
| `WORKLOG.md` / `TODO.md` / `README.md` | extend | feature + new keybindings (`C`, RMB-on-queued) |

Total: 0 new modules + 7 modified files + 1 new spec. The Renderer ABC
contract grows by one method (`blit_cast_queue`).

---

## §11 Acceptance criteria

After this milestone ships:

* In Raise mode, click ten tiles rapidly → all ten get amber ▲ chevrons
  with 1-9 numbered positions; pool drops by 50 belief; cooldown row
  shows `R⁹` (capped at 9 in the badge text, but the queue is 10 long).
* Wait 20 s without further input → all ten Raises process at ~2 s
  intervals, chevrons disappear as their tile fires, world surface
  repaints each time, food.cap/regen follow the new biomes.
* Right-click a queued tile (in Raise mode) → that tile's chevron
  vanishes, pool refunds 5 belief, the rest of the queue shifts up
  one position.
* Press `C` in Raise mode with five queued → all chevrons vanish, pool
  refunds 25 belief, badge drops to blank.
* Switch from Raise to Lower while Raise queue is non-empty → Raise
  chevrons stay visible; the Raise queue keeps draining at the regular
  cadence even though you're now placing Lower queues.
* Queue 5 Raises on the same tile (which will become FOREST → HILL →
  MOUNTAIN partway through) → the first few fire as expected; once
  the tile hits MOUNTAIN, subsequent dispatches log `queued_invalid`
  scripture lines and burn cost + cooldown without changing the world.

---

## §12 Deferred / out of scope

* **Bless / Curse / Inspire / Hunger Pang queuing.** Add `int(PowerKind.X)`
  to `QUEUEABLE_KINDS` if the playtest later proves the desire.
* **Hover tooltip on the count badge.** Just paint the number for now.
* **Drag-to-queue.** Click-drag across tiles to enqueue a line — would
  be lovely, but every UI library that supports it without writing a
  hit-test grid does so by being heavier than pygame. Defer until we
  find a real ergonomic gap that single clicks don't fill.
* **Visual ETA bar on each chevron.** Tiny pie-slice clock showing
  time-until-dispatch for each queued tile. Polish, not core.
* **Refund partial cost on `queued_invalid` dispatch.** Currently full
  burn. If playtest finds it punishing we revisit.

---

## §13 Open questions

None as of v0.1. The three forks (debit-on-enqueue, R/L only, both
cancel modes) were locked in the 2026-05-21 design discussion.

---

*Spec ends.*
