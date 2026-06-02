"""Domain model for the wafer machine — state only, no Qt graphics.

This is the single source of truth for *what is true* about the machine:
wafers, stations, the cassette, and the dual-effector robot. It deliberately
imports no QGraphics types — only `QObject`/`Signal` (for change
notifications) and `QPointF` (geometry). The view (`anim.py`) and the process
runner (`anim_demo.py`) both depend on this module, never the reverse.

Note: this model is still *timeless* — `trigger_*` mutators apply moves
instantly and the view is what makes them appear to take time. Elevating
timing into this layer is a later refactor step.
"""

from dataclasses import dataclass, field
from enum import Enum, auto

from PySide6.QtCore import QObject, Signal, QPointF


CASSETTE_SLOT_COUNT = 25
EFFECTOR_COUNT = 2


# ---------- LAYOUT (physical machine placement) ----------

EXPOSURE_POS  = QPointF(50, 300)
EXPOSURE_SIZE = (150, 150)           # (width, height)

CASSETTE_POS  = QPointF(400, 200)
CASSETTE_SIZE = (100, 200)

ALIGNER_POS   = QPointF(250, 80)
ALIGNER_SIZE  = (80, 60)

ROBOT_POS     = QPointF(250, 220)
ROBOT_SIZE    = (50, 50)

LASER_Y       = 20    # y of the laser body (top of scene)
MASK_HEIGHT   = 15
MASK_GAP      = 16     # clear gap between mask bottom and exposure box top


class LocationType(Enum):
    STATION = auto()   # Single-slot stations (Aligner, Exposure Box)
    SLOT = auto()      # Cassette slots
    EFFECTOR = auto()  # Robot arms


@dataclass(frozen=True)
class Location:
    type: LocationType
    name: str = ""
    index: int = 0

    @classmethod
    def station(cls, name: str):
        return cls(LocationType.STATION, name)

    @classmethod
    def slot(cls, name: str, index: int):
        return cls(LocationType.SLOT, name, index)

    @classmethod
    def effector(cls, index: int):
        return cls(LocationType.EFFECTOR, "Robot", index)


# ---------- DOMAIN MODEL (no Qt graphics) ----------

@dataclass
class Station:
    name: str
    pos: QPointF
    width: float
    height: float


@dataclass
class Cassette(Station):
    slot_count: int = CASSETTE_SLOT_COUNT
    # `slots[i]` is the wafer id currently sitting in slot i, or None.
    # The model owns this; the visualizer and ProcessRunner only read it.
    slots: list[str | None] = field(default_factory=list)

    def __post_init__(self):
        if not self.slots:
            self.slots = [None] * self.slot_count

    def slot_pos(self, slot_index: int) -> QPointF:
        pitch = self.height / self.slot_count
        y_top = self.pos.y() - self.height / 2
        return QPointF(self.pos.x(), y_top + (slot_index + 0.5) * pitch)


@dataclass
class Robot(Station):
    """Dual-effector rotating robot. The body stays at .pos forever."""
    effector_count: int = EFFECTOR_COUNT
    # `effectors[i]` is the wafer id parked on effector i, or None. This
    # tracks *parked* occupancy only (wafers whose location is EFFECTOR).
    # In-flight carry during a station->station move is still owned by the
    # visualizer until moves become time-aware in the model (step 3).
    effectors: list[str | None] = field(default_factory=list)

    def __post_init__(self):
        if not self.effectors:
            self.effectors = [None] * self.effector_count


@dataclass
class Laser:
    name: str
    pos: QPointF
    target: QPointF    # centre of the top edge of the illuminated area
    width: float       # laser aperture width
    target_width: float  # width of the illuminated area at target


@dataclass
class Mask:
    name: str
    pos: QPointF
    width: float
    height: float


@dataclass
class Wafer:
    id: str
    location: Location | None = None


class MachineController(QObject):
    wafer_added = Signal(object)
    wafer_moved = Signal(object)

    def __init__(self):
        super().__init__()
        self.robot = Robot("Robot", ROBOT_POS, *ROBOT_SIZE)
        exposure_box = Station("Exposure Box", EXPOSURE_POS, *EXPOSURE_SIZE)
        exposure_top = exposure_box.pos.y() - exposure_box.height / 2
        self.laser = Laser(
            "Laser",
            pos=QPointF(exposure_box.pos.x(), LASER_Y),
            target=QPointF(exposure_box.pos.x(), exposure_top),
            width=exposure_box.width / 2,
            target_width=exposure_box.width,
        )
        self.mask = Mask(
            "Mask",
            pos=QPointF(exposure_box.pos.x(), exposure_top - MASK_GAP - MASK_HEIGHT / 2),
            width=exposure_box.width,
            height=MASK_HEIGHT,
        )
        self.stations: dict[str, Station] = {
            "Exposure Box": exposure_box,
            "Cassette": Cassette("Cassette", CASSETTE_POS, *CASSETTE_SIZE),
            "Aligner": Station("Aligner", ALIGNER_POS, *ALIGNER_SIZE),
        }
        # Station occupancy: which wafer (if any) currently holds each
        # single-slot station. The cassette is not in here because its
        # slots are tracked separately on the Cassette itself.
        self.station_holder: dict[str, str | None] = {
            name: None for name, st in self.stations.items() if not isinstance(st, Cassette)
        }
        self.wafers: dict[str, Wafer] = {}

    # ---- model invariants ----

    def _cassette(self) -> Cassette:
        cassette = self.stations["Cassette"]
        assert isinstance(cassette, Cassette)
        return cassette

    def _release(self, wafer: Wafer):
        """Clear whatever station/slot this wafer currently holds."""
        loc = wafer.location
        if not loc:
            return
        if loc.type == LocationType.SLOT:
            cassette = self._cassette()
            if 0 <= loc.index < cassette.slot_count and cassette.slots[loc.index] == wafer.id:
                cassette.slots[loc.index] = None
        elif loc.type == LocationType.EFFECTOR:
            if 0 <= loc.index < len(self.robot.effectors) and self.robot.effectors[loc.index] == wafer.id:
                self.robot.effectors[loc.index] = None
        elif loc.type == LocationType.STATION:
            if self.station_holder.get(loc.name) == wafer.id:
                self.station_holder[loc.name] = None

    # ---- mutators ----

    def add_wafer_in_cassette(self, wafer_id, slot_index) -> Wafer:
        assert wafer_id not in self.wafers, f"wafer {wafer_id!r} already exists"
        cassette = self._cassette()
        assert cassette.slots[slot_index] is None, (
            f"slot {slot_index} already holds {cassette.slots[slot_index]!r}"
        )
        wafer = Wafer(id=wafer_id, location=Location.slot("Cassette", slot_index))
        self.wafers[wafer_id] = wafer
        cassette.slots[slot_index] = wafer_id
        self.wafer_added.emit(wafer)
        return wafer

    def trigger_hardware_move(self, wafer_id, destination):
        wafer = self.wafers.get(wafer_id)
        station = self.stations.get(destination)
        if wafer is None or station is None:
            return
        self._release(wafer)
        if isinstance(station, Cassette):
            wafer.location = Location.slot(destination, 0)
            station.slots[0] = wafer.id
        else:
            wafer.location = Location.station(destination)
            self.station_holder[destination] = wafer.id
        self.wafer_moved.emit(wafer)

    def trigger_load_to_cassette_slot(self, wafer_id, slot_index):
        wafer = self.wafers.get(wafer_id)
        cassette = self.stations.get("Cassette")
        if wafer is None or not isinstance(cassette, Cassette):
            return
        self._release(wafer)
        wafer.location = Location.slot("Cassette", slot_index)
        cassette.slots[slot_index] = wafer.id
        self.wafer_moved.emit(wafer)

    def trigger_park_on_robot(self, wafer_id, effector_index):
        wafer = self.wafers.get(wafer_id)
        if wafer is None:
            return
        self._release(wafer)
        wafer.location = Location.effector(effector_index)
        self.robot.effectors[effector_index] = wafer.id
        self.wafer_moved.emit(wafer)

    def free_effectors(self) -> list[int]:
        return [i for i, w in enumerate(self.robot.effectors) if w is None]
