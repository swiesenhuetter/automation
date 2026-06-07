# Step 3 — Make "a move takes time" a model concept (design 2)

## Goal

Today `trigger_*` teleports the model to the destination instantly; the **view**
makes it *look* timed and announces completion via `wafer_arrived`. The process
runner therefore waits on a GUI signal — business logic depends on the view.

Step 3 inverts this: the **model** owns a move's lifecycle, its motion
time-scale, and the single-robot sequencing. The view renders the active move
and reports back; the runner advances on a **model** signal.

## Design (2): the animation is the clock — no QTimers for moves

We deliberately avoid adding QTimers. The model does **not** schedule
completion. Instead:

- `model.request_*(...)` builds a `Move`, reserves occupancy, enqueues it, and
  pumps the queue → emits `move_started(move)`. Schedules nothing.
- The view builds the rotate/extend/retract animation for that move; when the
  animation `finished` fires, it calls `model.complete_move(move.id)`.
- `model.complete_move` emits `move_completed(move)` and pumps the next move.

The animation's `finished` *is* the clock tick. Tests pump the model directly
(`request_* ` then `complete_move`) with no Qt loop — the model never depends on
what drives it.

## What the model owns vs. defers (3a scope)

**Owns now:**
- The move queue and one-at-a-time robot sequencing (absorbed from the view's
  `_busy` / `_move_queue`).
- The motion time-scale: `LEG_DURATION_MS` moves from a view constant to a
  machine constant, carried on each `Move`. The view reads `move.leg_duration_ms`
  per leg, so the look is preserved exactly and the view no longer hardcodes it.
- The completion *event* and its ordering.

**Deferred (out of scope for 3a):**
- *Partial physical states.* Occupancy reservation (`station_holder`,
  `cassette.slots`, `robot.effectors`) and `wafer.location` stay set
  **synchronously at request time** — exactly as today — so the runner's mutex
  timing is unchanged. We do not model "source frees at pickup, not at request."
  What becomes time-aware is the completion event and the sequencing, not every
  intermediate state.
- *Effector allocation.* `_pick_effector`, `_find_carrying_effector`,
  `_effector_wafers`, `_attach`/`_deliver` stay view-side. Moving them into the
  model (via `Move.carrier`) and deleting the step-2 duplication is **step 3b**.
- *Speed-based duration.* A flat per-leg `LEG_DURATION_MS` is used now. Computing
  duration from rotation/extension speeds needs the kinematic geometry that lives
  in `RobotVisual` (`angle_to`, `distance_to`) to move model-side — a separate
  follow-on, not smuggled into 3a.

## API

`machine.py`:

```python
@dataclass
class Move:
    id: int
    wafer_id: str
    source: Location | None
    dest: Location
    leg_duration_ms: int = LEG_DURATION_MS

class MachineController(QObject):
    wafer_added    = Signal(object)
    move_started   = Signal(object)   # a move was dequeued; view animates it
    move_completed = Signal(object)   # active move finished; runner advances

    def request_move(self, wafer_id, destination) -> Move | None: ...
    def request_load(self, wafer_id, slot_index) -> Move | None: ...
    def request_park(self, wafer_id, effector_index) -> Move | None: ...
    def complete_move(self, move_id: int): ...   # called by the view
```

The old `trigger_*` mutators are renamed to `request_*` and `wafer_moved` is
replaced by `move_started` / `move_completed`.

## View (`anim.py`) — pump + cosmetics

- Connects `controller.move_started` → `_on_move_started(move)`: pick the
  effector (still view-side), animate the legs using `move.leg_duration_ms`, and
  on the sequence's `finished` call `controller.complete_move(move.id)`.
- Deleted: `wafer_arrived`, `_busy`, `_move_queue`, the queueing in
  `_process_next`, and the `LEG_DURATION_MS` class constant.

## Runner (`anim_demo.py`) — one wire change

`visualizer.wafer_arrived` → `controller.move_completed`. The process layer no
longer references the view. Dependency triangle closes: `view → machine`,
`process → machine`, nothing back.

## The `wait` exception

`wait(seconds)` (exposure dwell) has no animation to ride, so it keeps its single
`QTimer.singleShot` in the runner. That is the one legitimate standalone timer.
Unifying it onto a shared clock is what would later motivate design (3) (a single
animated clock property with model-owned `position(t)`).

## Testability (the payoff)

```python
m = MachineController()
m.add_wafer_in_cassette("W", 0)
mv = m.request_move("W", "Aligner")   # emits move_started; nothing scheduled
m.complete_move(mv.id)                 # emits move_completed; pumps next
assert m.wafers["W"].location == Location.station("Aligner")
```

No animation, no timer, deterministic.

## Split

- **3a** — queue + durations + lifecycle + runner flip; effectors stay view-side.
- **3b** — `Move.carrier`, model allocates the effector in `_pump`, model tracks
  in-flight carry, delete `_effector_wafers`/`_attach`/`_deliver`/`_pick_effector`.
