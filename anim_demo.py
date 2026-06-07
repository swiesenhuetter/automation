"""Demo harness + process DSL for the wafer-machine widget.

`anim.py` is the reusable machine widget (model + visuals + visualizer).
This file is the thin demo layer that drives it:

* the small process DSL (`from_slot`, `to`, `expose`, `wait`, …),
* `ProcessRunner` — schedules multiple wafer processes concurrently,
  treating each station as a mutex,
* `MainWindow` — the action-button UI used to play with the widget by
  hand and to launch the demo scenario.

Run this file (not anim.py) to see the full interactive demo.
"""

import sys
from dataclasses import dataclass

from PySide6.QtCore import QObject, QTimer
from PySide6.QtWidgets import (
    QApplication, QComboBox, QHBoxLayout, QLabel, QLineEdit, QMainWindow,
    QPushButton, QSpinBox, QVBoxLayout, QWidget,
)

from machine import CASSETTE_SLOT_COUNT, MachineController
from anim import WaferVisualizer


# ---------- PROCESS DSL ----------
#
# A wafer process is a flat list of (verb, *args) tuples. Each process is
# scoped to a single wafer; multiple processes run concurrently and
# coordinate by treating each station as a mutex — the runner blocks a
# `to(station)` step until that station is free. Time-based verbs
# (`expose`, `wait`) hold their process for a duration without moving a wafer.

# Verb factories — return the same tuples a user could write by hand,
# but with IDE autocomplete + type checks for cheap typo-safety.

def from_slot(n: int):       return ("from_slot", n)
def to(station: str):        return ("to", station)
def to_slot(n: int):         return ("to_slot", n)
def wait(seconds: float):    return ("wait", seconds)


@dataclass(frozen=True)
class Exposure:
    """Parameters for one `expose` step — the seed of the process recipe.

    Only `seconds` is wired up today; `dose`/`intensity` are stubs for the real
    recipe. They are physically linked (dose ~= intensity * time), so once any
    two are given the third can be derived/validated here rather than at the
    call site.
    """
    seconds: float
    dose: float | None = None        # target dose (mJ/cm^2) — future
    intensity: float | None = None   # laser intensity        — future


def expose(seconds: float, *, dose: float | None = None,
           intensity: float | None = None):
    return ("expose", Exposure(seconds, dose=dose, intensity=intensity))


@dataclass
class WaferProcess:
    wafer_id: str
    steps: list[tuple]
    pc: int = 0          # next step to execute
    blocked: bool = False  # waiting on animation / timer


class ProcessRunner(QObject):
    """Drives multiple WaferProcesses concurrently.

    Station occupancy is owned by `MachineController.station_holder`;
    this runner only reads it to decide whether the next `to(station)`
    can proceed. When a station is busy the process parks until it
    frees up. Move completion (via `MachineController.move_completed`)
    and `wait()` timers unblock processes — the tick loop then runs any
    steps that are now executable.
    """

    def __init__(self, controller: MachineController, visualizer: WaferVisualizer, parent=None):
        super().__init__(parent)
        self.controller = controller
        self.visualizer = visualizer
        self.processes: list[WaferProcess] = []
        controller.move_completed.connect(self._on_move_completed)

    def add(self, wafer_id: str, steps: list[tuple]) -> WaferProcess:
        ps = WaferProcess(wafer_id, list(steps))
        self.processes.append(ps)
        self._tick()
        return ps

    def _tick(self):
        # Keep advancing as long as any process made progress this pass —
        # one step may unblock another (e.g. releasing Aligner).
        progressed = True
        while progressed:
            progressed = False
            for ps in self.processes:
                if ps.blocked or ps.pc >= len(ps.steps):
                    continue
                if self._try_step(ps):
                    progressed = True

    def _try_step(self, ps: WaferProcess) -> bool:
        verb, *args = ps.steps[ps.pc]

        if verb == "from_slot":
            # Idempotent on replay: if the wafer already exists, leave it
            # wherever it is. Otherwise create it at the requested slot.
            if ps.wafer_id not in self.controller.wafers:
                self.controller.add_wafer_in_cassette(ps.wafer_id, args[0])
            ps.pc += 1
            return True

        if verb == "to":
            station = args[0]
            holder = self.controller.station_holder.get(station)
            if holder not in (None, ps.wafer_id):
                return False  # blocked on resource — try again next tick
            ps.blocked = True
            ps.pc += 1
            self.controller.request_move(ps.wafer_id, station)
            return True

        if verb == "to_slot":
            ps.blocked = True
            ps.pc += 1
            self.controller.request_load(ps.wafer_id, args[0])
            return True

        if verb == "expose":
            exposure = args[0]
            ps.blocked = True
            ps.pc += 1
            # Beam on -> dwell -> beam off. Exposure owns real time without an
            # animation behind it, so it keeps a lone timer (the step-3 `wait`
            # exception). Only `seconds` is honoured for now.
            self.visualizer.set_laser(True)
            QTimer.singleShot(int(exposure.seconds * 1000),
                              lambda p=ps: self._end_exposure(p))
            return True

        if verb == "wait":
            ps.blocked = True
            ps.pc += 1
            QTimer.singleShot(int(float(args[0]) * 1000), lambda p=ps: self._unblock(p))
            return True

        raise ValueError(f"Unknown verb: {verb!r}")

    def _on_move_completed(self, move):
        for ps in self.processes:
            if ps.wafer_id == move.wafer_id and ps.blocked:
                ps.blocked = False
                break
        self._tick()

    def _end_exposure(self, ps: WaferProcess):
        self.visualizer.set_laser(False)
        self._unblock(ps)

    def _unblock(self, ps: WaferProcess):
        ps.blocked = False
        self._tick()


# ---------- DEMO ----------

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.machine = MachineController()
        self.visualizer = WaferVisualizer(self.machine)
        self.runner = ProcessRunner(self.machine, self.visualizer)

        layout = QVBoxLayout()
        layout.addWidget(self.visualizer)

        selector_row = QHBoxLayout()
        selector_row.addWidget(QLabel("Wafer:"))
        self.wafer_combo = QComboBox()
        # Keep the picker in sync with the model: every wafer ever added shows
        # up here, including ones created lazily by a process's from_slot step.
        self.machine.wafer_added.connect(lambda w: self.wafer_combo.addItem(w.id))
        selector_row.addWidget(self.wafer_combo)
        layout.addLayout(selector_row)

        # Seed the initial cassette load now that both the visualizer and the
        # combo are listening on wafer_added.
        for i, wid in enumerate(["W_A", "W_B", "W_C", "W_D"]):
            self.machine.add_wafer_in_cassette(wid, i)

        for label, dest in [("Move to Aligner", "Aligner"),
                            ("Move to Exposure", "Exposure Box")]:
            btn = QPushButton(label)
            btn.clicked.connect(lambda _=False, d=dest: self._move(d))
            layout.addWidget(btn)

        cassette_row = QHBoxLayout()
        btn_to_slot = QPushButton("To Cassette Slot")
        btn_to_slot.clicked.connect(self._park_in_cassette)
        self.slot_spin = QSpinBox()
        self.slot_spin.setRange(0, CASSETTE_SLOT_COUNT - 1)
        cassette_row.addWidget(btn_to_slot)
        cassette_row.addWidget(self.slot_spin)
        layout.addLayout(cassette_row)

        btn_park_robot = QPushButton("Park on robot (next free effector)")
        btn_park_robot.clicked.connect(self._park_on_robot)
        layout.addWidget(btn_park_robot)

        btn_demo = QPushButton("Run demo (two interleaving processes)")
        btn_demo.clicked.connect(self._run_demo)
        layout.addWidget(btn_demo)

        btn_laser = QPushButton("Laser")
        btn_laser.setCheckable(True)
        btn_laser.toggled.connect(self.visualizer.set_laser)
        layout.addWidget(btn_laser)

        mask_row = QHBoxLayout()
        self.btn_mask = QPushButton("Load Mask")
        self.btn_mask.setCheckable(True)
        self.btn_mask.toggled.connect(self._toggle_mask)
        self.mask_id_edit = QLineEdit()
        self.mask_id_edit.setPlaceholderText("mask id")
        mask_row.addWidget(self.btn_mask)
        mask_row.addWidget(self.mask_id_edit)
        layout.addLayout(mask_row)

        container = QWidget()
        container.setLayout(layout)
        self.setCentralWidget(container)

    def _selected_wafer_id(self) -> str:
        return self.wafer_combo.currentText()

    def _move(self, destination: str):
        self.machine.request_move(self._selected_wafer_id(), destination)

    def _park_in_cassette(self):
        self.machine.request_load(self._selected_wafer_id(), self.slot_spin.value())

    def _park_on_robot(self):
        free = self.machine.free_effectors()
        if not free:
            print("Robot is full")
            return
        self.machine.request_park(self._selected_wafer_id(), free[0])

    def _toggle_mask(self, loaded: bool):
        self.visualizer.set_mask_loaded(loaded, self.mask_id_edit.text())

    def _run_demo(self):
        # Two wafers racing for the same stations. W_X starts first and
        # holds Aligner; W_Y blocks on `to("Aligner")` until W_X moves
        # onward to the Exposure Box, then proceeds.
        self.runner.add("W_X", [
            from_slot(10),
            to("Aligner"),
            to("Exposure Box"),
            expose(4.5),
            to_slot(10),
        ])
        self.runner.add("W_Y", [
            from_slot(11),
            to("Aligner"),
            to("Exposure Box"),
            expose(4.0),
            to_slot(11),
        ])


if __name__ == "__main__":
    app = QApplication(sys.argv)
    w = MainWindow()
    w.show()
    sys.exit(app.exec())
