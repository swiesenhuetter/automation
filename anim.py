import math
import sys
from dataclasses import dataclass, field
from enum import Enum, auto
from PySide6.QtCore import (
    QObject, Signal, QPointF, QPropertyAnimation, QEasingCurve,
    Property, QRectF, Qt, QSequentialAnimationGroup,
)
from PySide6.QtWidgets import (
    QApplication, QGraphicsScene, QGraphicsView, QGraphicsObject,
    QGraphicsEllipseItem, QGraphicsPolygonItem, QGraphicsRectItem,
    QGraphicsLineItem, QGraphicsTextItem,
)
from PySide6.QtGui import QBrush, QColor, QFont, QPen, QPolygonF


CASSETTE_SLOT_COUNT = 25
EFFECTOR_COUNT = 2
REST_EXTENSION = 60   # arm length when "retracted" — keeps the two effector tips apart


# ---------- LAYOUT (all scene geometry lives here) ----------

SCENE_RECT    = (-60, 0, 560, 450)   # (x, y, width, height)

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


# ---------- COLOUR PALETTE ----------
#
# Named tokens that the themes assemble. Where Qt's SVG colour-name
# table contains an exact RGB match we use `QColor("name")`; otherwise
# we use a descriptive or hex-suffix name so the value is still
# obvious at a glance.

# Mono — Qt named.
BLACK       = QColor("black")
WHITE       = QColor("white")
LIGHT_GRAY  = QColor("lightgray")   # = #d3d3d3, exact SVG match
GAINSBORO   = QColor("gainsboro")   # = (220, 220, 220), exact SVG match

# Custom grey ladder (Qt has no exact name for these shades).
GRAY_DDD    = QColor("#dddddd")
GRAY_CCC    = QColor("#cccccc")
GRAY_BBB    = QColor("#bbbbbb")
GRAY_A0     = QColor(160, 160, 160)
GRAY_999    = QColor("#999999")
GRAY_909    = QColor("#909090")
GRAY_80     = QColor(80, 80, 80)
GRAY_6A     = QColor("#6a6a6a")
GRAY_666    = QColor("#666666")
GRAY_555    = QColor("#555555")
GRAY_444    = QColor("#444444")
GRAY_3A     = QColor("#3a3a3a")
GRAY_333    = QColor("#333333")
NEAR_BLACK  = QColor(20, 20, 20)

# Blues — named after their role/use rather than RGB.
WAFER_BLUE_FILL          = QColor(0, 120, 212, 150)   # light-mode wafer
WAFER_BLUE_FILL_BRIGHT   = QColor(80, 170, 255, 170)  # dark-mode wafer
MASK_BLUE_FILL           = QColor(0, 100, 200, 120)   # light-mode mask
MASK_BLUE_FILL_BRIGHT    = QColor(80, 170, 255, 140)  # dark-mode mask
MASK_BLUE_OUTLINE        = QColor(0, 60, 160)         # light-mode mask outline
MASK_BLUE_OUTLINE_LIGHT  = QColor(160, 200, 255)      # dark-mode mask outline
DEEP_NAVY                = QColor(20, 30, 50)         # dark-mode mask text

# Reds — laser beam (translucent, two intensities).
BEAM_RED          = QColor(255, 40, 40, 60)
BEAM_RED_BRIGHT   = QColor(255, 80, 80, 80)


# ---------- FONTS ----------
#
# Shared font for wafer IDs and station names — bigger than the Qt
# default so labels are readable at the scene's natural zoom level.
# The mask font stays calculated (`MaskVisual` sizes it from mask
# height so it scales with the mask glyph).

LABEL_FONT = QFont()
LABEL_FONT.setPixelSize(16)


# ---------- THEME (named colour tokens) ----------
#
# QGraphicsItem is not styled by Qt stylesheets, so we centralise the colours
# here instead. Each visual asks the active THEME for a named token rather than
# instantiating a QColor at the use-site. Switching to dark mode = build a new
# Theme and rebuild the static scene items.

@dataclass(frozen=True)
class Theme:
    # Wafers
    wafer_fill: QColor
    wafer_outline: QColor
    wafer_text: QColor
    # Robot
    robot_body_fill: QColor
    robot_body_outline: QColor
    robot_arm: QColor
    robot_tip_fill: QColor
    robot_tip_outline: QColor
    # Laser
    laser_body_fill: QColor
    laser_body_outline: QColor
    laser_beam: QColor
    # Mask
    mask_loaded_fill: QColor
    mask_loaded_outline: QColor
    mask_loaded_text: QColor
    mask_unloaded_outline: QColor
    mask_unloaded_text: QColor
    # Stations / cassette
    station_fill: QColor
    cassette_slot_line: QColor


LIGHT_THEME = Theme(
    wafer_fill=WAFER_BLUE_FILL,
    wafer_outline=BLACK,
    wafer_text=BLACK,
    robot_body_fill=GRAY_666,
    robot_body_outline=BLACK,
    robot_arm=GRAY_555,
    robot_tip_fill=GRAY_333,
    robot_tip_outline=BLACK,
    laser_body_fill=GRAY_444,
    laser_body_outline=BLACK,
    laser_beam=BEAM_RED,
    mask_loaded_fill=MASK_BLUE_FILL,
    mask_loaded_outline=MASK_BLUE_OUTLINE,
    mask_loaded_text=WHITE,
    mask_unloaded_outline=GRAY_80,
    mask_unloaded_text=GRAY_80,
    station_fill=LIGHT_GRAY,
    cassette_slot_line=GRAY_909,
)


DARK_THEME = Theme(
    # Starting values — tune to taste once you can preview against a dark bg.
    wafer_fill=WAFER_BLUE_FILL_BRIGHT,
    wafer_outline=GAINSBORO,
    wafer_text=GAINSBORO,
    robot_body_fill=GRAY_BBB,
    robot_body_outline=NEAR_BLACK,
    robot_arm=GRAY_999,
    robot_tip_fill=GRAY_DDD,
    robot_tip_outline=NEAR_BLACK,
    laser_body_fill=GRAY_CCC,
    laser_body_outline=NEAR_BLACK,
    laser_beam=BEAM_RED_BRIGHT,
    mask_loaded_fill=MASK_BLUE_FILL_BRIGHT,
    mask_loaded_outline=MASK_BLUE_OUTLINE_LIGHT,
    mask_loaded_text=DEEP_NAVY,
    mask_unloaded_outline=GRAY_A0,
    mask_unloaded_text=GRAY_A0,
    station_fill=GRAY_3A,
    cassette_slot_line=GRAY_6A,
)


THEME: Theme = LIGHT_THEME


class WaferViewMode(Enum):
    TOP_DOWN = auto()   # circle (in transit, on robot, on station)
    SIDE_SLOT = auto()  # flat slab (parked in cassette slot)


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
    location: str = ""   # "<station>", "Cassette:<slot>", or "Robot:<effector>"


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
        if loc.startswith("Cassette:"):
            slot = int(loc.split(":", 1)[1])
            cassette = self._cassette()
            if 0 <= slot < cassette.slot_count and cassette.slots[slot] == wafer.id:
                cassette.slots[slot] = None
        elif loc.startswith("Robot:"):
            pass  # robot effectors are tracked by the visualizer
        elif self.station_holder.get(loc) == wafer.id:
            self.station_holder[loc] = None

    # ---- mutators ----

    def add_wafer_in_cassette(self, wafer_id, slot_index) -> Wafer:
        assert wafer_id not in self.wafers, f"wafer {wafer_id!r} already exists"
        cassette = self._cassette()
        assert cassette.slots[slot_index] is None, (
            f"slot {slot_index} already holds {cassette.slots[slot_index]!r}"
        )
        wafer = Wafer(id=wafer_id, location=f"Cassette:{slot_index}")
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
            wafer.location = f"{destination}:0"
            station.slots[0] = wafer.id
        else:
            wafer.location = destination
            self.station_holder[destination] = wafer.id
        self.wafer_moved.emit(wafer)

    def trigger_load_to_cassette_slot(self, wafer_id, slot_index):
        wafer = self.wafers.get(wafer_id)
        cassette = self.stations.get("Cassette")
        if wafer is None or not isinstance(cassette, Cassette):
            return
        self._release(wafer)
        wafer.location = f"Cassette:{slot_index}"
        cassette.slots[slot_index] = wafer.id
        self.wafer_moved.emit(wafer)

    def trigger_park_on_robot(self, wafer_id, effector_index):
        wafer = self.wafers.get(wafer_id)
        if wafer is None:
            return
        self._release(wafer)
        wafer.location = f"Robot:{effector_index}"
        self.wafer_moved.emit(wafer)

    def free_effectors(self) -> list[int]:
        occupied = {
            int(w.location.split(":", 1)[1])
            for w in self.wafers.values() if w.location.startswith("Robot:")
        }
        return [i for i in range(EFFECTOR_COUNT) if i not in occupied]


# ---------- VIEW ----------

class WaferItem(QGraphicsObject):
    DIAMETER = 80
    SIDE_THICKNESS = 3

    def __init__(self, wafer: Wafer, parent=None):
        super().__init__(parent)
        self.wafer = wafer
        self._pos = QPointF(0, 0)
        self.mode = WaferViewMode.TOP_DOWN
        self.bounding_rect = QRectF(-self.DIAMETER / 2, -self.DIAMETER / 2,
                                    self.DIAMETER, self.DIAMETER)

    def boundingRect(self):
        return self.bounding_rect

    def paint(self, painter, option, widget=None):
        painter.setBrush(QBrush(THEME.wafer_fill))
        painter.setPen(QPen(THEME.wafer_outline, 1))
        if self.mode == WaferViewMode.TOP_DOWN:
            r = self.DIAMETER / 2
            painter.drawEllipse(QRectF(-r, -r, self.DIAMETER, self.DIAMETER))
            painter.setPen(QPen(THEME.wafer_text))
            painter.setFont(LABEL_FONT)
            painter.drawText(self.bounding_rect, Qt.AlignmentFlag.AlignCenter, self.wafer.id)
        else:
            t = self.SIDE_THICKNESS
            painter.drawRect(QRectF(-self.DIAMETER / 2, -t / 2, self.DIAMETER, t))

    def set_mode(self, mode):
        if self.mode != mode:
            self.mode = mode
            self.update()

    def get_pos(self):
        return self._pos

    def set_pos(self, pos):
        self._pos = pos
        super().setPos(pos)

    wafer_pos = Property(QPointF, get_pos, set_pos)


class RobotVisual(QObject):
    """Dual-effector robot.

    Geometry: body sits at ``home_pos``. Two effectors point 180° apart.
    State is (rotation_deg, extension_0, extension_1) — all animatable Qt properties.
    The tip of effector ``i`` is at ``home + extension_i * (cos α, sin α)``,
    where ``α = rotation + i * 180°``.
    """

    tip_0_moved = Signal(QPointF)
    tip_1_moved = Signal(QPointF)

    BODY_DIAMETER = 50
    TIP_SIZE = 16
    ARM_THICKNESS = 10

    def __init__(self, home_pos: QPointF, parent=None):
        super().__init__(parent)
        self.home_pos = home_pos
        self._rotation_deg = 0.0
        self._extensions = [REST_EXTENSION, REST_EXTENSION]

        body_rect = QRectF(home_pos.x() - self.BODY_DIAMETER / 2,
                           home_pos.y() - self.BODY_DIAMETER / 2,
                           self.BODY_DIAMETER, self.BODY_DIAMETER)
        self.body = QGraphicsEllipseItem(body_rect)
        self.body.setBrush(QBrush(THEME.robot_body_fill))
        self.body.setPen(QPen(THEME.robot_body_outline, 2))
        self.body.setZValue(4)

        self.arms = []
        self.tips = []
        for _ in range(EFFECTOR_COUNT):
            arm = QGraphicsLineItem()
            pen = QPen(THEME.robot_arm, self.ARM_THICKNESS)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            arm.setPen(pen)
            arm.setZValue(3)  # below body so the body covers the arm root
            self.arms.append(arm)

            tip = QGraphicsRectItem(QRectF(-self.TIP_SIZE / 2, -self.TIP_SIZE / 2,
                                           self.TIP_SIZE, self.TIP_SIZE))
            tip.setBrush(QBrush(THEME.robot_tip_fill))
            tip.setPen(QPen(THEME.robot_tip_outline, 1))
            tip.setZValue(5)
            self.tips.append(tip)

        self._refresh(0)
        self._refresh(1)

    def add_to_scene(self, scene: QGraphicsScene):
        for arm in self.arms:
            scene.addItem(arm)
        scene.addItem(self.body)
        for tip in self.tips:
            scene.addItem(tip)

    def effector_angle_deg(self, effector_index: int) -> float:
        return self._rotation_deg + effector_index * 180.0

    def tip_pos(self, effector_index: int) -> QPointF:
        angle = math.radians(self.effector_angle_deg(effector_index))
        ext = self._extensions[effector_index]
        return QPointF(self.home_pos.x() + math.cos(angle) * ext,
                       self.home_pos.y() + math.sin(angle) * ext)

    def angle_to(self, target: QPointF) -> float:
        """Angle in degrees from robot home to target, in scene coords (y grows downward)."""
        dx = target.x() - self.home_pos.x()
        dy = target.y() - self.home_pos.y()
        return math.degrees(math.atan2(dy, dx))

    def distance_to(self, target: QPointF) -> float:
        return math.hypot(target.x() - self.home_pos.x(), target.y() - self.home_pos.y())

    def rotation_for_effector_facing(self, effector_index: int, target: QPointF) -> float:
        """Rotation angle such that the given effector points at the target."""
        return self.angle_to(target) - effector_index * 180.0

    def _refresh(self, effector_index: int):
        tip = self.tip_pos(effector_index)
        self.tips[effector_index].setPos(tip)
        self.arms[effector_index].setLine(self.home_pos.x(), self.home_pos.y(),
                                          tip.x(), tip.y())
        (self.tip_0_moved if effector_index == 0 else self.tip_1_moved).emit(tip)

    # --- Animatable properties ---

    def get_rotation_deg(self) -> float:
        return self._rotation_deg

    def set_rotation_deg(self, deg: float):
        self._rotation_deg = float(deg)
        self._refresh(0)
        self._refresh(1)

    rotation_deg = Property(float, get_rotation_deg, set_rotation_deg)

    def get_extension_0(self) -> float:
        return self._extensions[0]

    def set_extension_0(self, ext: float):
        self._extensions[0] = float(ext)
        self._refresh(0)

    extension_0 = Property(float, get_extension_0, set_extension_0)

    def get_extension_1(self) -> float:
        return self._extensions[1]

    def set_extension_1(self, ext: float):
        self._extensions[1] = float(ext)
        self._refresh(1)

    extension_1 = Property(float, get_extension_1, set_extension_1)


def shortest_rotation_target(current: float, target: float) -> float:
    """Pick an equivalent target angle (±360 k) closest to current — minimises rotation path."""
    diff = ((target - current) + 180.0) % 360.0 - 180.0
    return current + diff


class LaserVisual:
    BODY_HEIGHT = 14

    def __init__(self, pos: QPointF, target: QPointF,
                 source_width: float, target_width: float,
                 mask_top_y: float, mask_bottom_y: float):
        hw = source_width / 2
        body_rect = QRectF(pos.x() - hw, pos.y() - self.BODY_HEIGHT / 2,
                           source_width, self.BODY_HEIGHT)
        self.body = QGraphicsRectItem(body_rect)
        self.body.setBrush(QBrush(THEME.laser_body_fill))
        self.body.setPen(QPen(THEME.laser_body_outline, 1))
        self.body.setZValue(6)

        beam_top_y = pos.y() + self.BODY_HEIGHT / 2
        thw = target_width / 2

        self.beam_upper = self._make_beam(QPolygonF([
            QPointF(pos.x() - hw,      beam_top_y),
            QPointF(pos.x() + hw,      beam_top_y),
            QPointF(target.x() + thw,  mask_top_y),
            QPointF(target.x() - thw,  mask_top_y),
        ]))
        self.beam_lower = self._make_beam(QPolygonF([
            QPointF(target.x() - thw,  mask_bottom_y),
            QPointF(target.x() + thw,  mask_bottom_y),
            QPointF(target.x() + thw,  target.y()),
            QPointF(target.x() - thw,  target.y()),
        ]))

    def _make_beam(self, poly: QPolygonF) -> QGraphicsPolygonItem:
        item = QGraphicsPolygonItem(poly)
        item.setBrush(QBrush(THEME.laser_beam))
        item.setPen(QPen(Qt.PenStyle.NoPen))
        item.setZValue(2)
        item.setVisible(False)
        return item

    def add_to_scene(self, scene: QGraphicsScene):
        scene.addItem(self.beam_upper)
        scene.addItem(self.beam_lower)
        scene.addItem(self.body)

    def set_active(self, on: bool):
        self.beam_upper.setVisible(on)
        self.beam_lower.setVisible(on)


class MaskVisual:
    def __init__(self, pos: QPointF, width: float, height: float):
        self._center = pos
        rect = QRectF(pos.x() - width / 2, pos.y() - height / 2, width, height)
        self.item = QGraphicsRectItem(rect)
        self.item.setZValue(8)

        self._label = QGraphicsTextItem()
        font = QFont()
        font.setPixelSize(int(height) - 2)
        self._label.setFont(font)
        self._label.setZValue(9)

        self._apply(loaded=False, mask_id="")

    def add_to_scene(self, scene: QGraphicsScene):
        scene.addItem(self.item)
        scene.addItem(self._label)

    def set_loaded(self, loaded: bool, mask_id: str = ""):
        self._apply(loaded, mask_id)

    def _apply(self, loaded: bool, mask_id: str):
        if loaded:
            self.item.setBrush(QBrush(THEME.mask_loaded_fill))
            self.item.setPen(QPen(THEME.mask_loaded_outline, 1))
            self._label.setDefaultTextColor(THEME.mask_loaded_text)
            self._label.setPlainText(mask_id or "???")
        else:
            self.item.setBrush(QBrush(Qt.BrushStyle.NoBrush))
            self.item.setPen(QPen(THEME.mask_unloaded_outline, 1))
            self._label.setDefaultTextColor(THEME.mask_unloaded_text)
            self._label.setPlainText("no mask")
        br = self._label.boundingRect()
        self._label.setPos(self._center.x() - br.width() / 2,
                           self._center.y() - br.height() / 2)


class WaferVisualizer(QGraphicsView):
    LEG_DURATION_MS = 400   # rotate / extend / retract: ~6 legs per move

    # Fired after a queued move animation has fully finished. The
    # ProcessRunner uses this to advance per-wafer processes once their
    # current move is done.
    wafer_arrived = Signal(str)

    def __init__(self, controller: MachineController):
        super().__init__()
        self.controller = controller
        self.scene = QGraphicsScene(*SCENE_RECT, self)
        self.setScene(self.scene)
        self.wafer_items: dict[str, WaferItem] = {}
        self.robot: RobotVisual | None = None
        self.laser_visual: LaserVisual | None = None
        self.mask_visual: MaskVisual | None = None

        # _effector_wafers[i] is the WaferItem currently riding effector i (or None).
        # Updated only via _attach / _detach during animation playback.
        self._effector_wafers: list[WaferItem | None] = [None] * EFFECTOR_COUNT

        # Robot serves one move at a time. Snapshot target location at queue time.
        self._move_queue: list[tuple[Wafer, str]] = []
        self._busy = False
        self._current_seq: QSequentialAnimationGroup | None = None
        self._current_wafer: Wafer | None = None

        self._draw_static_scene()
        controller.wafer_added.connect(self._on_wafer_added)
        controller.wafer_moved.connect(self._on_wafer_moved)

    # ---- static drawing ----

    def _draw_static_scene(self):
        self.robot = RobotVisual(self.controller.robot.pos)
        self.robot.add_to_scene(self.scene)
        mask = self.controller.mask
        mask_top_y = mask.pos.y() - mask.height / 2
        mask_bottom_y = mask.pos.y() + mask.height / 2
        laser = self.controller.laser
        self.laser_visual = LaserVisual(
            laser.pos, laser.target, laser.width, laser.target_width,
            mask_top_y, mask_bottom_y,
        )
        self.laser_visual.add_to_scene(self.scene)
        self.mask_visual = MaskVisual(mask.pos, mask.width, mask.height)
        self.mask_visual.add_to_scene(self.scene)
        for station in self.controller.stations.values():
            x, y = station.pos.toTuple()
            rect = QRectF(x - station.width / 2, y - station.height / 2,
                          station.width, station.height)
            self.scene.addRect(rect, brush=QBrush(THEME.station_fill))
            text = self.scene.addText(station.name)
            text.setFont(LABEL_FONT)
            tr = text.boundingRect()
            text.setPos(x - tr.width() / 2, y + station.height / 2 + 2)
            if isinstance(station, Cassette):
                pen = QPen(THEME.cassette_slot_line)
                for i in range(station.slot_count):
                    sp = station.slot_pos(i)
                    self.scene.addLine(sp.x() - station.width / 2 + 4, sp.y(),
                                       sp.x() + station.width / 2 - 4, sp.y(), pen)

    def set_laser(self, on: bool):
        if self.laser_visual:
            self.laser_visual.set_active(on)

    def set_mask_loaded(self, loaded: bool, mask_id: str = ""):
        if self.mask_visual:
            self.mask_visual.set_loaded(loaded, mask_id)

    # ---- wafer lifecycle ----

    def _on_wafer_added(self, wafer: Wafer):
        item = WaferItem(wafer)
        item.setZValue(10)
        pos, mode = self._resolve(wafer.location)
        item.set_pos(pos)
        item.set_mode(mode)
        self.scene.addItem(item)
        self.wafer_items[wafer.id] = item

    def _on_wafer_moved(self, wafer: Wafer):
        self._move_queue.append((wafer, wafer.location))
        if not self._busy:
            self._process_next()

    # ---- choreography ----

    def _process_next(self):
        if not self._move_queue or self.robot is None:
            self._busy = False
            return
        wafer, target_location = self._move_queue.pop(0)
        item = self.wafer_items.get(wafer.id)
        if item is None:
            self._process_next()
            return

        source_effector = self._find_carrying_effector(item)
        target_effector = self._pick_effector(item, target_location, source_effector)
        if target_effector is None:
            # Either no free effector for pickup, or destination effector is busy.
            self._busy = False
            self._process_next()
            return

        self._busy = True
        target_pos, target_mode = self._resolve(target_location)
        item.set_mode(WaferViewMode.TOP_DOWN)

        seq = QSequentialAnimationGroup(self)

        # ---- pickup phase (only if wafer is not already on the robot) ----
        if source_effector is None:
            pickup_pos = item.get_pos()
            self._add_reach_legs(seq, target_effector, pickup_pos,
                                 on_arrived=lambda: self._attach(item, target_effector))

        # ---- drop phase (only if destination is a station, not the robot) ----
        if not target_location.startswith("Robot:"):
            self._add_reach_legs(seq, target_effector, target_pos,
                                 on_arrived=lambda: self._deliver(item, target_mode, target_effector))

        seq.finished.connect(self._on_sequence_done)
        self._current_seq = seq
        self._current_wafer = wafer
        seq.start()

    def _add_reach_legs(self, seq: QSequentialAnimationGroup, effector: int,
                        target_pos: QPointF, on_arrived):
        """Append three legs: rotate-to-face, extend-to-target, retract-to-rest.
        ``on_arrived`` fires between the extend and the retract (i.e. at the apex)."""
        assert self.robot is not None
        target_rotation = self.robot.rotation_for_effector_facing(effector, target_pos)
        target_rotation = shortest_rotation_target(self.robot.get_rotation_deg(), target_rotation)
        target_extension = self.robot.distance_to(target_pos)

        rotate = self._anim(b"rotation_deg", target_rotation)
        extend = self._anim(self._ext_prop(effector), target_extension)
        retract = self._anim(self._ext_prop(effector), REST_EXTENSION)

        seq.addAnimation(rotate)
        seq.addAnimation(extend)
        seq.addAnimation(retract)

        extend.finished.connect(on_arrived)

    def _anim(self, prop_name: bytes, end_value) -> QPropertyAnimation:
        anim = QPropertyAnimation(self.robot, prop_name)
        anim.setDuration(self.LEG_DURATION_MS)
        anim.setEasingCurve(QEasingCurve.InOutQuad)
        anim.setEndValue(end_value)
        return anim

    @staticmethod
    def _ext_prop(effector: int) -> bytes:
        return b"extension_0" if effector == 0 else b"extension_1"

    # ---- effector bookkeeping ----

    def _find_carrying_effector(self, item: WaferItem) -> int | None:
        for i, occupant in enumerate(self._effector_wafers):
            if occupant is item:
                return i
        return None

    def _pick_effector(self, item: WaferItem, target_location: str,
                       source_effector: int | None) -> int | None:
        """Return the effector to use for this move, or None if not feasible."""
        if target_location.startswith("Robot:"):
            dest_e = int(target_location.split(":", 1)[1])
            if source_effector is not None and source_effector != dest_e:
                return None  # can't move between effectors (they share rotation)
            if source_effector is None and self._effector_wafers[dest_e] is not None:
                return None  # destination effector occupied
            return dest_e
        # Destination is a regular station / cassette slot.
        if source_effector is not None:
            return source_effector
        # Pick first free effector.
        for i, occupant in enumerate(self._effector_wafers):
            if occupant is None:
                return i
        return None

    def _attach(self, item: WaferItem, effector: int):
        sig = self.robot.tip_0_moved if effector == 0 else self.robot.tip_1_moved
        sig.connect(item.set_pos)
        self._effector_wafers[effector] = item

    def _deliver(self, item: WaferItem, target_mode: WaferViewMode, effector: int):
        sig = self.robot.tip_0_moved if effector == 0 else self.robot.tip_1_moved
        try:
            sig.disconnect(item.set_pos)
        except (RuntimeError, TypeError):
            pass
        self._effector_wafers[effector] = None
        item.set_mode(target_mode)

    def _on_sequence_done(self):
        finished_wafer = self._current_wafer
        self._current_seq = None
        self._current_wafer = None
        if finished_wafer is not None:
            self.wafer_arrived.emit(finished_wafer.id)
        self._process_next()

    # ---- location resolution ----

    def _resolve(self, location: str) -> tuple[QPointF, WaferViewMode]:
        if location.startswith("Cassette:"):
            slot = int(location.split(":", 1)[1])
            cassette = self.controller.stations["Cassette"]
            assert isinstance(cassette, Cassette)
            return cassette.slot_pos(slot), WaferViewMode.SIDE_SLOT
        if location.startswith("Robot:"):
            effector = int(location.split(":", 1)[1])
            assert self.robot is not None
            return self.robot.tip_pos(effector), WaferViewMode.TOP_DOWN
        station = self.controller.stations.get(location)
        if station is not None:
            return station.pos, WaferViewMode.TOP_DOWN
        return QPointF(0, 0), WaferViewMode.TOP_DOWN


if __name__ == "__main__":
    # Stand-alone widget harness. Shows the visualizer with two wafers in
    # the cassette and nothing else. For the full interactive demo
    # (action buttons + the process DSL + the two-wafer race) run
    # anim_demo.py instead.
    app = QApplication(sys.argv)
    machine = MachineController()
    view = WaferVisualizer(machine)
    machine.add_wafer_in_cassette("W_A", 0)
    machine.add_wafer_in_cassette("W_B", 1)
    view.show()
    sys.exit(app.exec())


