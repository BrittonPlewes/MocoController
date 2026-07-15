"""
Animation Curve Editor Widget
A PyQt5 widget for previewing and editing animation bezier curves,
inspired by DCC tools like Maya's Graph Editor and Blender's Curve Editor.

Usage:
    python anim_curve_editor.py

Dependencies:
    pip install PyQt5
"""

import sys
import math
from dataclasses import dataclass, field
from typing import List, Optional, Tuple
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QSplitter, QFrame, QToolBar, QAction,
    QSlider, QSpinBox, QDoubleSpinBox, QGroupBox, QFormLayout,
    QComboBox, QCheckBox, QSizePolicy, QStatusBar
)
from PyQt5.QtCore import (
    Qt, QPointF, QRectF, QRect, pyqtSignal, QTimer, QSize
)
from PyQt5.QtGui import (
    QPainter, QPen, QBrush, QColor, QPainterPath, QFont,
    QTransform, QCursor, QLinearGradient, QPalette, QIcon,
    QKeySequence, QFontMetrics
)

from lib.utils.AnimCurve import AnimCurve, KeyFrame

# ─────────────────────────────────────────────
#  Color Palette
# ─────────────────────────────────────────────

class Palette:
    """
    All viewport draw colors are derived from the active QPalette at paint time,
    so the widget automatically matches whatever Qt theme the host app uses.
    Call Palette.resolve(widget) once at the top of paintEvent to get a snapshot.
    """

    CURVE_COLORS = [
        QColor(255, 120,  80),   # red-orange (X)
        QColor( 80, 210, 100),   # green       (Y)
        QColor( 80, 160, 255),   # blue        (Z)
        QColor(220, 120, 255),   # purple
        QColor(255, 220,  60),   # yellow
        QColor( 60, 220, 220),   # cyan
    ]

    @classmethod
    def resolve(cls, widget: 'QWidget') -> 'Palette':
        p = widget.palette()
        inst = cls.__new__(cls)

        base   = p.color(QPalette.Base)           # deepest background
        window = p.color(QPalette.Window)         # panel background
        mid    = p.color(QPalette.Mid)            # slightly lighter than window
        text   = p.color(QPalette.Text)
        dim    = p.color(QPalette.Disabled, QPalette.Text)
        hi     = p.color(QPalette.Highlight)

        inst.BG           = base
        inst.BG_PANEL     = window
        inst.RULER_BG     = mid
        inst.GRID_MAJOR   = _blend(base, text, 0.15)
        inst.GRID_MINOR   = _blend(base, text, 0.07)
        inst.TEXT         = text
        inst.TEXT_DIM     = dim
        inst.ACCENT       = hi
        inst.SELECTION    = QColor(hi.red(), hi.green(), hi.blue(), 60)
        inst.PLAYHEAD     = QColor(255, 220, 60)   # intentionally vivid
        inst.KEY_NORMAL   = _blend(base, text, 0.7)
        inst.KEY_SEL      = QColor(255, 200, 60)
        inst.TANGENT_LINE = QColor(
            hi.red(), hi.green(), hi.blue(),
            120
        )
        inst.TANGENT_HANDLE = hi
        return inst


def _blend(a: QColor, b: QColor, t: float) -> QColor:
    """Linear interpolate between two QColors (t=0 → a, t=1 → b)."""
    return QColor(
        int(a.red()   + (b.red()   - a.red())   * t),
        int(a.green() + (b.green() - a.green()) * t),
        int(a.blue()  + (b.blue()  - a.blue())  * t),
    )


# ─────────────────────────────────────────────
#  Curve Color Registry
# ─────────────────────────────────────────────

class CurveColorRegistry:
    """
    Decouples curve colors from the AnimCurve data object.

    Color resolution order (first match wins):
      1. curve.color  — a per-curve override set directly on the AnimCurve
      2. registry map — a dict[str, QColor] keyed by curve name
      3. fallback fn  — a callable(curve_name: str) -> QColor
      4. built-in default — cycles through Palette.CURVE_COLORS by index

    Usage examples::

        # Simple axis mapping
        reg = CurveColorRegistry({
            "translateX": QColor(255, 80,  80),
            "translateY": QColor( 80, 255, 80),
            "translateZ": QColor( 80, 120, 255),
        })
        editor.set_color_registry(reg)

        # Dynamic fallback — color derived from the name at runtime
        reg = CurveColorRegistry(fallback=lambda name: my_axis_color(name))

        # Override a single curve regardless of registry
        curve.color = QColor(255, 200, 0)   # always wins

        # Clear a per-curve override and fall back to registry
        curve.color = None
    """

    def __init__(
        self,
        mapping: Optional[dict] = None,
        fallback=None,
    ):
        self._map: dict = mapping or {}
        # fallback: callable(name: str) -> QColor, or None
        self._fallback = fallback

    def set(self, name: str, color: QColor) -> None:
        """Add or update a single name→color entry."""
        self._map[name] = color

    def remove(self, name: str) -> None:
        """Remove a name entry (will fall through to fallback/default)."""
        self._map.pop(name, None)

    def resolve(self, curve: 'AnimCurve', index: int = 0) -> QColor:
        """
        Return the display color for *curve*.

        :param curve:  The AnimCurve being drawn.
        :param index:  Its position in the curve list, used for the built-in
                       default cycle when nothing else matches.
        """
        # 1. Per-curve override
        if curve.color is not None:
            return curve.color
        # 2. Registry map
        if curve.name in self._map:
            return self._map[curve.name]
        # 3. Fallback callable
        if self._fallback is not None:
            result = self._fallback(curve.name)
            if result is not None:
                return result
        # 4. Built-in default cycle
        return Palette.CURVE_COLORS[index % len(Palette.CURVE_COLORS)]


# ─────────────────────────────────────────────
#  Curve Viewport
# ─────────────────────────────────────────────

class CurveViewport(QWidget):
    """The main OpenGL-style curve drawing canvas."""

    selectionChanged = pyqtSignal()
    keyframeEdited   = pyqtSignal()
    timeChanged      = pyqtSignal(float)

    HANDLE_RADIUS = 4
    TANGENT_HANDLE_RADIUS = 4
    KEY_HIT_RADIUS = 8
    TANGENT_HIT_RADIUS = 7

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(400, 300)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setCursor(Qt.ArrowCursor)

        # View state
        self._view_offset = QPointF(0.0, 0.0)   # world units
        self._view_scale  = QPointF(80.0, -60.0) # px per world unit (y flipped)
        self._time_range  = (0.0, 10.0)
        self._value_range = (-2.0, 2.0)

        self.curves: List[AnimCurve] = []
        self.color_registry: CurveColorRegistry = CurveColorRegistry()
        self.current_time: float = 0.0
        self.time_scale: float = 1.0   # multiply raw time by this for display (e.g. 1/160 to convert ticks→frames)
        self._show_tangents = True
        self._snap_time = False
        self._snap_value = False
        self._snap_playhead = False   # snap playhead to whole frames (1/time_scale ticks)

        # Interaction state
        self._drag_mode: Optional[str] = None   # "pan", "key", "tangent_in", "tangent_out", "select_rect", "time"
        self._drag_start_mouse = QPointF()
        self._drag_start_world = QPointF()
        self._drag_key: Optional[Tuple[AnimCurve, KeyFrame]] = None
        # Multi-key drag: list of (curve, key, start_time, start_value)
        self._drag_keys: List[Tuple[AnimCurve, KeyFrame, float, float]] = []
        self._drag_tangent: Optional[Tuple[AnimCurve, KeyFrame, str]] = None
        self._select_rect_start = QPointF()
        self._select_rect_end   = QPointF()
        self._is_selecting_rect = False

        self._hovered_key: Optional[Tuple[AnimCurve, KeyFrame]] = None

        self.setContextMenuPolicy(Qt.DefaultContextMenu)

    # ── coordinate transforms ──────────────────

    def world_to_screen(self, wx: float, wy: float) -> QPointF:
        cx = (wx - self._view_offset.x()) * self._view_scale.x()
        cy = (wy - self._view_offset.y()) * self._view_scale.y()
        return QPointF(cx + self.width() / 2, cy + self.height() / 2)

    def screen_to_world(self, sx: float, sy: float) -> QPointF:
        wx = (sx - self.width() / 2) / self._view_scale.x() + self._view_offset.x()
        wy = (sy - self.height() / 2) / self._view_scale.y() + self._view_offset.y()
        return QPointF(wx, wy)

    def _world_pt(self, p: QPointF) -> QPointF:
        return self.world_to_screen(p.x(), p.y())

    def _ticks_to_display(self, t: float) -> float:
        """Convert a raw time value (ticks) to the display unit (e.g. frames)."""
        return t * self.time_scale

    def _display_to_ticks(self, t: float) -> float:
        """Convert a display-unit time back to raw ticks."""
        return t / self.time_scale if self.time_scale != 0.0 else t

    # ── painting ───────────────────────────────

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        pal = Palette.resolve(self)
        p.fillRect(self.rect(), pal.BG)
        self._draw_grid(p, pal)
        self._draw_curves(p, pal)
        if self._is_selecting_rect:
            self._draw_selection_rect(p, pal)
        self._draw_playhead(p, pal)
        self._draw_rulers(p, pal)
        self._draw_overlay_info(p, pal)

    def _draw_grid(self, painter: QPainter, pal: Palette):
        w, h = self.width(), self.height()
        tl = self.screen_to_world(0, 0)
        br = self.screen_to_world(w, h)

        t_min, t_max = min(tl.x(), br.x()), max(tl.x(), br.x())
        v_min, v_max = min(tl.y(), br.y()), max(tl.y(), br.y())

        def nice_step(span):
            raw = span / 8
            mag = 10 ** math.floor(math.log10(max(raw, 1e-9)))
            for m in [1, 2, 5, 10]:
                if raw <= m * mag:
                    return m * mag
            return 10 * mag

        t_step = nice_step(t_max - t_min)
        v_step = nice_step(v_max - v_min)
        t_minor = t_step / 5
        v_minor = v_step / 5

        painter.setPen(QPen(pal.GRID_MINOR, 0.5))
        t = math.floor(t_min / t_minor) * t_minor
        while t <= t_max + t_minor:
            sx = self.world_to_screen(t, 0).x()
            painter.drawLine(int(sx), 0, int(sx), h)
            t += t_minor
        v = math.floor(v_min / v_minor) * v_minor
        while v <= v_max + v_minor:
            sy = self.world_to_screen(0, v).y()
            painter.drawLine(0, int(sy), w, int(sy))
            v += v_minor

        painter.setPen(QPen(pal.GRID_MAJOR, 1.0))
        t = math.floor(t_min / t_step) * t_step
        while t <= t_max + t_step:
            sx = self.world_to_screen(t, 0).x()
            painter.drawLine(int(sx), 0, int(sx), h)
            t += t_step
        v = math.floor(v_min / v_step) * v_step
        while v <= v_max + v_step:
            sy = self.world_to_screen(0, v).y()
            painter.drawLine(0, int(sy), w, int(sy))
            v += v_step

        # Zero axes — slightly brighter than major grid
        axis_color = _blend(pal.GRID_MAJOR, pal.TEXT, 0.25)
        painter.setPen(QPen(axis_color, 1.5))
        sy0 = self.world_to_screen(0, 0).y()
        painter.drawLine(0, int(sy0), w, int(sy0))
        sx0 = self.world_to_screen(0, 0).x()
        painter.drawLine(int(sx0), 0, int(sx0), h)

    def _draw_curves(self, painter: QPainter, pal: Palette):
        w = self.width()
        tl = self.screen_to_world(0, 0)
        br = self.screen_to_world(w, self.height())
        t_min = min(tl.x(), br.x())
        t_max = max(tl.x(), br.x())
        STEPS = max(w, 400)

        for i, curve in enumerate(self.curves):
            if not curve.visible or not curve.keyframes:
                continue

            keys = sorted(curve.keyframes, key=lambda k: k.time)

            path = QPainterPath()
            first = True
            for j in range(STEPS + 1):
                t = t_min + (t_max - t_min) * j / STEPS
                v = curve.evaluate(t)
                sp = self.world_to_screen(t, v)
                if first:
                    path.moveTo(sp)
                    first = False
                else:
                    path.lineTo(sp)

            alpha = 255 if curve.selected else 180
            if curve.locked:
                alpha = min(alpha, 90)
            color = QColor(self.color_registry.resolve(curve, i))
            color.setAlpha(alpha)
            width = 2.0 if curve.selected else 1.5
            painter.setPen(QPen(color, width, Qt.SolidLine, Qt.RoundCap))
            painter.setBrush(Qt.NoBrush)
            painter.drawPath(path)

            if self._show_tangents:
                self._draw_tangents(painter, curve, keys, pal)

            self._draw_keyframes(painter, curve, keys, pal)

    def _draw_tangents(self, painter: QPainter, curve: AnimCurve, keys: List[KeyFrame], pal: Palette):
        for i, key in enumerate(keys):
            if not key.selected:
                continue
            ksp = self.world_to_screen(key.time, key.value)

            if i > 0:
                prev = keys[i - 1]
                seg_dt = key.time - prev.time
                tin_w = QPointF(key.time + key.tangent_in.x() * seg_dt,
                                key.value + key.tangent_in.y())
                tin_s = self.world_to_screen(tin_w.x(), tin_w.y())
                painter.setPen(QPen(pal.TANGENT_LINE, 1.0, Qt.SolidLine))
                painter.drawLine(ksp.toPoint(), tin_s.toPoint())
                painter.setPen(Qt.NoPen)
                painter.setBrush(pal.TANGENT_HANDLE)
                r = self.TANGENT_HANDLE_RADIUS
                painter.drawEllipse(tin_s, r, r)

            if i < len(keys) - 1:
                nxt = keys[i + 1]
                seg_dt = nxt.time - key.time
                tout_w = QPointF(key.time + key.tangent_out.x() * seg_dt,
                                 key.value + key.tangent_out.y())
                tout_s = self.world_to_screen(tout_w.x(), tout_w.y())
                painter.setPen(QPen(pal.TANGENT_LINE, 1.0, Qt.SolidLine))
                painter.drawLine(ksp.toPoint(), tout_s.toPoint())
                painter.setPen(Qt.NoPen)
                painter.setBrush(pal.TANGENT_HANDLE)
                r = self.TANGENT_HANDLE_RADIUS
                painter.drawEllipse(tout_s, r, r)

    def _draw_keyframes(self, painter: QPainter, curve: AnimCurve, keys: List[KeyFrame], pal: Palette):
        for key in keys:
            sp = self.world_to_screen(key.time, key.value)
            is_hovered = (curve, key) == self._hovered_key

            if curve.locked:
                r = self.HANDLE_RADIUS * 0.65
                painter.setPen(QPen(_blend(pal.KEY_NORMAL, pal.BG, 0.5), 0.75))
                painter.setBrush(_blend(pal.KEY_NORMAL, pal.BG, 0.6))
            elif key.selected:
                r = self.HANDLE_RADIUS * 1.35
                painter.setPen(QPen(pal.TEXT, 1.75))
                painter.setBrush(pal.KEY_SEL)
            elif is_hovered:
                r = self.HANDLE_RADIUS * 1.15
                painter.setPen(QPen(pal.TEXT, 1.0))
                painter.setBrush(_blend(pal.KEY_NORMAL, pal.TEXT, 0.3))
            else:
                r = self.HANDLE_RADIUS
                painter.setPen(QPen(_blend(pal.KEY_NORMAL, pal.BG, 0.3), 1.0))
                painter.setBrush(pal.KEY_NORMAL)

            if key.tangent_mode == "stepped":
                painter.save()
                painter.translate(sp)
                painter.rotate(45)
                painter.drawRect(QRectF(-r * 0.8, -r * 0.8, r * 1.6, r * 1.6))
                painter.restore()
            else:
                painter.drawRect(QRectF(sp.x() - r, sp.y() - r, r * 2, r * 2))

            # Small accent dot in centre of locked keys
            if key.locked:
                painter.setPen(Qt.NoPen)
                painter.setBrush(pal.ACCENT)
                painter.drawEllipse(sp, 2, 2)

    def _draw_playhead(self, painter: QPainter, pal: Palette):
        sx = self.world_to_screen(self.current_time, 0).x()
        h = self.height()
        painter.setPen(QPen(pal.PLAYHEAD, 1.5, Qt.SolidLine))
        painter.drawLine(int(sx), 20, int(sx), h)
        painter.setPen(Qt.NoPen)
        painter.setBrush(pal.PLAYHEAD)
        tri = QPainterPath()
        tri.moveTo(sx, 28)
        tri.lineTo(sx - 6, 18)
        tri.lineTo(sx + 6, 18)
        tri.closeSubpath()
        painter.drawPath(tri)

    def _draw_rulers(self, painter: QPainter, pal: Palette):
        w, h = self.width(), self.height()
        ruler_h = 20

        painter.fillRect(0, 0, w, ruler_h, pal.RULER_BG)
        tl = self.screen_to_world(0, 0)
        br = self.screen_to_world(w, h)
        t_min, t_max = min(tl.x(), br.x()), max(tl.x(), br.x())

        def nice_step(span):
            raw = span / 10
            if raw <= 0:
                return 1
            mag = 10 ** math.floor(math.log10(max(raw, 1e-9)))
            for m in [1, 2, 5, 10]:
                if raw <= m * mag:
                    return m * mag
            return 10 * mag

        t_step = nice_step(t_max - t_min)
        painter.setFont(QFont("Monospace", 8))

        t = math.floor(t_min / t_step) * t_step
        while t <= t_max + t_step:
            sx = int(self.world_to_screen(t, 0).x())
            painter.setPen(QPen(pal.GRID_MAJOR, 0.5))
            painter.drawLine(sx, ruler_h - 6, sx, ruler_h)
            painter.setPen(pal.TEXT_DIM)
            display_t = self._ticks_to_display(t)
            abs_t = abs(display_t)
            if abs_t == 0 or (0.01 <= abs_t < 10_000):
                label = f"{display_t:g}"
            else:
                label = f"{display_t:.3g}"
            painter.drawText(sx + 2, ruler_h - 5, label)
            t += t_step

        painter.setPen(QPen(pal.GRID_MAJOR, 1.0))
        painter.drawLine(0, ruler_h, w, ruler_h)

    def _draw_selection_rect(self, painter: QPainter, pal: Palette):
        rect = QRectF(self._select_rect_start, self._select_rect_end).normalized()
        painter.setPen(QPen(pal.ACCENT, 1.0, Qt.DashLine))
        painter.setBrush(pal.SELECTION)
        painter.drawRect(rect)

    def _draw_overlay_info(self, painter: QPainter, pal: Palette):
        painter.setFont(QFont("Monospace", 8))
        painter.setPen(pal.TEXT_DIM)
        world_mouse = self.screen_to_world(
            self._last_mouse_x if hasattr(self, '_last_mouse_x') else 0,
            self._last_mouse_y if hasattr(self, '_last_mouse_y') else 0,
        )
        display_t = self._ticks_to_display(world_mouse.x())
        text = f"T: {display_t:.3f}  V: {world_mouse.y():.3f}"
        painter.drawText(self.rect().adjusted(8, 24, -8, -6), Qt.AlignBottom | Qt.AlignLeft, text)

    # ── hit testing ────────────────────────────

    def _hit_key(self, mouse: QPointF) -> Optional[Tuple['AnimCurve', KeyFrame]]:
        for curve in reversed(self.curves):
            if not curve.visible or curve.locked:
                continue
            for key in curve.keyframes:
                sp = self.world_to_screen(key.time, key.value)
                if (mouse - sp).manhattanLength() <= self.KEY_HIT_RADIUS + 2:
                    return (curve, key)
        return None

    def _hit_tangent(self, mouse: QPointF) -> Optional[Tuple['AnimCurve', KeyFrame, str]]:
        for curve in self.curves:
            if not curve.visible or curve.locked:
                continue
            keys = sorted(curve.keyframes, key=lambda k: k.time)
            for i, key in enumerate(keys):
                if not key.selected:
                    continue
                if i > 0:
                    prev = keys[i - 1]
                    seg_dt = key.time - prev.time
                    tin_w = QPointF(key.time + key.tangent_in.x() * seg_dt,
                                    key.value + key.tangent_in.y())
                    tin_s = self.world_to_screen(tin_w.x(), tin_w.y())
                    if (mouse - tin_s).manhattanLength() <= self.TANGENT_HIT_RADIUS + 2:
                        return (curve, key, "in")
                if i < len(keys) - 1:
                    nxt = keys[i + 1]
                    seg_dt = nxt.time - key.time
                    tout_w = QPointF(key.time + key.tangent_out.x() * seg_dt,
                                     key.value + key.tangent_out.y())
                    tout_s = self.world_to_screen(tout_w.x(), tout_w.y())
                    if (mouse - tout_s).manhattanLength() <= self.TANGENT_HIT_RADIUS + 2:
                        return (curve, key, "out")
        return None

    # ── mouse events ───────────────────────────

    def mousePressEvent(self, event):
        pos = QPointF(event.pos())
        world = self.screen_to_world(pos.x(), pos.y())
        self._drag_start_mouse = pos
        self._drag_start_world = world

        if event.button() == Qt.MiddleButton:
            self._drag_mode = "pan"
            self.setCursor(Qt.SizeAllCursor)
            return

        if event.button() == Qt.LeftButton:
            # Ruler → scrub time
            if pos.y() < 20:
                self._drag_mode = "time"
                self.current_time = world.x()
                self.timeChanged.emit(self._ticks_to_display(self.current_time))
                self.update()
                return

            # Tangent handle?
            if self._show_tangents:
                th = self._hit_tangent(pos)
                if th:
                    self._drag_tangent = th
                    self._drag_mode = "tangent_in" if th[2] == "in" else "tangent_out"
                    return

            # Key?
            hit = self._hit_key(pos)
            if hit:
                curve, key = hit
                mods = event.modifiers()
                if not (mods & Qt.ShiftModifier):
                    if not key.selected:
                        self._deselect_all()
                key.selected = not key.selected if (mods & Qt.ShiftModifier) else True
                self._drag_key = hit
                self._drag_mode = "key"
                self._drag_start_world = QPointF(key.time, key.value)
                # Snapshot start positions of all selected keys for multi-drag
                self._drag_keys = [
                    (c, k, k.time, k.value)
                    for c in self.curves for k in c.keyframes if k.selected
                ]
                self.selectionChanged.emit()
                self.update()
                return

            # Empty space → start rect select or deselect
            mods = event.modifiers()
            if not (mods & Qt.ShiftModifier):
                self._deselect_all()
                self.selectionChanged.emit()
            self._is_selecting_rect = True
            self._select_rect_start = pos
            self._select_rect_end = pos
            self._drag_mode = "select_rect"
            self.update()

    def mouseMoveEvent(self, event):
        pos = QPointF(event.pos())
        self._last_mouse_x = pos.x()
        self._last_mouse_y = pos.y()
        world = self.screen_to_world(pos.x(), pos.y())
        delta_mouse = pos - self._drag_start_mouse

        if self._drag_mode == "pan":
            dx = delta_mouse.x() / self._view_scale.x()
            dy = delta_mouse.y() / self._view_scale.y()
            self._view_offset -= QPointF(dx, dy)
            self._drag_start_mouse = pos
            self.update()
            return

        if self._drag_mode == "time":
            t = max(world.x(), 0.0)
            if self._snap_playhead and self.time_scale != 0.0:
                ticks_per_frame = 1.0 / self.time_scale
                t = round(t / ticks_per_frame) * ticks_per_frame
            self.current_time = t
            self.timeChanged.emit(self._ticks_to_display(self.current_time))
            self.update()
            return

        if self._drag_mode == "key" and self._drag_keys:
            world_start = self.screen_to_world(self._drag_start_mouse.x(), self._drag_start_mouse.y())
            dt = world.x() - world_start.x()
            dv = world.y() - world_start.y()
            for c, k, start_t, start_v in self._drag_keys:
                new_t = start_t + dt
                new_v = start_v + dv
                if self._snap_time:
                    new_t = round(new_t * 4) / 4
                k.time = max(0.0, new_t)
                k.value = new_v
            # Don't recalculate tangents mid-drag — deferred to mouseRelease
            self.keyframeEdited.emit()
            self.update()
            return

        if self._drag_mode in ("tangent_in", "tangent_out") and self._drag_tangent:
            curve, key, side = self._drag_tangent
            keys = sorted(curve.keyframes, key=lambda k: k.time)
            idx = keys.index(key)
            dx = world.x() - key.time
            dy = world.y() - key.value
            if side == "in" and idx > 0:
                seg_dt = key.time - keys[idx - 1].time
                if seg_dt > 1e-9:
                    key.tangent_in = QPointF(dx / seg_dt, dy)
                    if key.locked and idx < len(keys) - 1:
                        # Mirror length+direction onto out handle
                        out_dt = keys[idx + 1].time - key.time
                        scale = out_dt / seg_dt if seg_dt > 1e-9 else 1.0
                        key.tangent_out = QPointF(-key.tangent_in.x() * scale,
                                                  -key.tangent_in.y())
            elif side == "out" and idx < len(keys) - 1:
                seg_dt = keys[idx + 1].time - key.time
                if seg_dt > 1e-9:
                    key.tangent_out = QPointF(dx / seg_dt, dy)
                    if key.locked and idx > 0:
                        # Mirror length+direction onto in handle
                        in_dt = key.time - keys[idx - 1].time
                        scale = in_dt / seg_dt if seg_dt > 1e-9 else 1.0
                        key.tangent_in = QPointF(-key.tangent_out.x() * scale,
                                                 -key.tangent_out.y())
            if not key.locked and key.tangent_mode == "aligned":
                self._align_tangent(key, side)
            self.keyframeEdited.emit()
            self.update()
            return

        if self._drag_mode == "select_rect":
            self._select_rect_end = pos
            self.update()
            return

        # Hover
        old_hover = self._hovered_key
        self._hovered_key = self._hit_key(pos)
        if self._hovered_key != old_hover:
            self.setCursor(Qt.SizeAllCursor if self._hovered_key else Qt.ArrowCursor)
            self.update()

        self.update()  # for coord overlay

    def mouseReleaseEvent(self, event):
        if self._drag_mode == "select_rect":
            self._finish_rect_select(event.modifiers())
        elif self._drag_mode == "key" and self._drag_keys:
            # Recalculate auto tangents for every moved key and its neighbours
            to_update: List[Tuple[AnimCurve, KeyFrame]] = []
            for curve, key, _, _ in self._drag_keys:
                keys = sorted(curve.keyframes, key=lambda k: k.time)
                idx = keys.index(key)
                if key.tangent_mode == "auto":
                    to_update.append((curve, key))
                if idx > 0 and keys[idx - 1].tangent_mode == "auto":
                    to_update.append((curve, keys[idx - 1]))
                if idx < len(keys) - 1 and keys[idx + 1].tangent_mode == "auto":
                    to_update.append((curve, keys[idx + 1]))
            # Deduplicate and update
            seen = set()
            for curve, k in to_update:
                if id(k) not in seen:
                    seen.add(id(k))
                    self._auto_tangent(curve, k)
            if to_update:
                self.keyframeEdited.emit()
        self._drag_mode = None
        self._drag_key = None
        self._drag_keys = []
        self._drag_tangent = None
        self._is_selecting_rect = False
        self.setCursor(Qt.ArrowCursor)
        self.update()

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.LeftButton and event.pos().y() > 20:
            world = self.screen_to_world(event.pos().x(), event.pos().y())
            hit = self._hit_key(QPointF(event.pos()))
            if not hit:
                # Add keyframe on visible curve (first selected, or first visible)
                target = None
                for c in self.curves:
                    if c.selected and c.visible and not c.locked:
                        target = c
                        break
                if not target:
                    for c in self.curves:
                        if c.visible and not c.locked:
                            target = c
                            break
                if target:
                    key = KeyFrame(world.x(), world.y())
                    target.keyframes.append(key)
                    # Only auto-tangent the new key and its immediate neighbours
                    # that are still in auto mode — leave all other keys untouched
                    sorted_keys = sorted(target.keyframes, key=lambda k: k.time)
                    idx = sorted_keys.index(key)
                    to_update = [key]
                    if idx > 0 and sorted_keys[idx - 1].tangent_mode == "auto":
                        to_update.append(sorted_keys[idx - 1])
                    if idx < len(sorted_keys) - 1 and sorted_keys[idx + 1].tangent_mode == "auto":
                        to_update.append(sorted_keys[idx + 1])
                    for k in to_update:
                        self._auto_tangent(target, k)
                    self.keyframeEdited.emit()
                    self.update()

    def wheelEvent(self, event):
        pos = QPointF(event.pos())
        world_before = self.screen_to_world(pos.x(), pos.y())
        mods = event.modifiers()

        delta = event.angleDelta().y() / 120.0
        factor = 1.15 ** delta

        if mods & Qt.ControlModifier:
            self._view_scale = QPointF(self._view_scale.x(),
                                       self._view_scale.y() * factor)
        elif mods & Qt.ShiftModifier:
            self._view_scale = QPointF(self._view_scale.x() * factor,
                                       self._view_scale.y())
        else:
            self._view_scale = QPointF(self._view_scale.x() * factor,
                                       self._view_scale.y() * factor)

        world_after = self.screen_to_world(pos.x(), pos.y())
        self._view_offset -= world_after - world_before
        self.update()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Delete or event.key() == Qt.Key_Backspace:
            self._delete_selected()
        elif event.key() == Qt.Key_A:
            self._select_all()
        elif event.key() == Qt.Key_F:
            self.frame_all()
        elif event.key() == Qt.Key_S and not event.modifiers():
            self._flatten_selected_tangents()
        elif event.key() == Qt.Key_L and not event.modifiers():
            self._toggle_lock_selected()

    # ── helpers ────────────────────────────────

    def _deselect_all(self):
        for curve in self.curves:
            for key in curve.keyframes:
                key.selected = False

    def _select_all(self):
        for curve in self.curves:
            if curve.visible and not curve.locked:
                for key in curve.keyframes:
                    key.selected = True
        self.selectionChanged.emit()
        self.update()

    def _finish_rect_select(self, mods):
        rect = QRectF(self._select_rect_start, self._select_rect_end).normalized()
        if not (mods & Qt.ShiftModifier):
            self._deselect_all()
        for curve in self.curves:
            if not curve.visible or curve.locked:
                continue
            for key in curve.keyframes:
                sp = self.world_to_screen(key.time, key.value)
                if rect.contains(sp):
                    key.selected = True
        self.selectionChanged.emit()
        self.update()

    def _delete_selected(self):
        for curve in self.curves:
            curve.keyframes = [k for k in curve.keyframes if not k.selected]
        self.keyframeEdited.emit()
        self.update()

    def _flatten_selected_tangents(self):
        for curve in self.curves:
            for key in curve.keyframes:
                if key.selected:
                    key.tangent_in  = QPointF(key.tangent_in.x(),  0.0)
                    key.tangent_out = QPointF(key.tangent_out.x(), 0.0)
                    key.tangent_mode = "flat"
        self.keyframeEdited.emit()
        self.update()

    def _toggle_lock_selected(self):
        """Toggle locked handles on all selected keys. If any are unlocked, lock all; otherwise unlock all."""
        selected = [k for c in self.curves for k in c.keyframes if k.selected]
        if not selected:
            return
        any_unlocked = any(not k.locked for k in selected)
        for key in selected:
            key.locked = any_unlocked
        self.keyframeEdited.emit()
        self.update()

    def _auto_tangent(self, curve: AnimCurve, key: KeyFrame):
        if key.tangent_mode != "auto":
            return
        keys = sorted(curve.keyframes, key=lambda k: k.time)
        idx = keys.index(key)
        if idx > 0 and idx < len(keys) - 1:
            prev, nxt = keys[idx - 1], keys[idx + 1]
            slope = (nxt.value - prev.value) / max(nxt.time - prev.time, 1e-9)
            key.tangent_in  = QPointF(-0.333, -slope * 0.333)
            key.tangent_out = QPointF( 0.333,  slope * 0.333)
        elif idx == 0 and len(keys) > 1:
            nxt = keys[1]
            slope = (nxt.value - key.value) / max(nxt.time - key.time, 1e-9)
            key.tangent_out = QPointF(0.333, slope * 0.333)
        elif idx == len(keys) - 1 and len(keys) > 1:
            prev = keys[-2]
            slope = (key.value - prev.value) / max(key.time - prev.time, 1e-9)
            key.tangent_in = QPointF(-0.333, -slope * 0.333)

    def _auto_tangents_all(self, curve: AnimCurve):
        keys = sorted(curve.keyframes, key=lambda k: k.time)
        for key in keys:
            if key.tangent_mode in ("auto",):
                self._auto_tangent(curve, key)

    def _align_tangent(self, key: KeyFrame, edited_side: str):
        if edited_side == "out":
            mag = math.sqrt(key.tangent_in.x()**2 + key.tangent_in.y()**2)
            if key.tangent_out.x() == 0 and key.tangent_out.y() == 0:
                return
            omag = math.sqrt(key.tangent_out.x()**2 + key.tangent_out.y()**2)
            scale = mag / max(omag, 1e-9)
            key.tangent_in = QPointF(-key.tangent_out.x() * scale,
                                     -key.tangent_out.y() * scale)
        else:
            mag = math.sqrt(key.tangent_out.x()**2 + key.tangent_out.y()**2)
            if key.tangent_in.x() == 0 and key.tangent_in.y() == 0:
                return
            imag = math.sqrt(key.tangent_in.x()**2 + key.tangent_in.y()**2)
            scale = mag / max(imag, 1e-9)
            key.tangent_out = QPointF(-key.tangent_in.x() * scale,
                                      -key.tangent_in.y() * scale)

    def frame_all(self):
        """Fit all keyframes into view."""
        all_keys = [k for c in self.curves if c.visible for k in c.keyframes]
        if not all_keys:
            return
        t_min = min(k.time  for k in all_keys)
        t_max = max(k.time  for k in all_keys)
        v_min = min(k.value for k in all_keys)
        v_max = max(k.value for k in all_keys)
        t_pad = max((t_max - t_min) * 0.1, 0.5)
        v_pad = max((v_max - v_min) * 0.15, 0.5)
        t_min -= t_pad; t_max += t_pad
        v_min -= v_pad; v_max += v_pad
        self._view_offset = QPointF((t_min + t_max) / 2, (v_min + v_max) / 2)
        sx = self.width()  / max(t_max - t_min, 1e-9)
        sy = -self.height() / max(v_max - v_min, 1e-9)
        self._view_scale = QPointF(sx, sy)
        self.update()

    def frame_selected(self):
        keys = [k for c in self.curves if c.visible for k in c.keyframes if k.selected]
        if not keys:
            self.frame_all()
            return
        t_min = min(k.time  for k in keys)
        t_max = max(k.time  for k in keys)
        v_min = min(k.value for k in keys)
        v_max = max(k.value for k in keys)
        t_pad = max((t_max - t_min) * 0.15, 0.5)
        v_pad = max((v_max - v_min) * 0.2,  0.5)
        t_min -= t_pad; t_max += t_pad
        v_min -= v_pad; v_max += v_pad
        self._view_offset = QPointF((t_min + t_max) / 2, (v_min + v_max) / 2)
        sx =  self.width()  / max(t_max - t_min, 1e-9)
        sy = -self.height() / max(v_max - v_min, 1e-9)
        self._view_scale = QPointF(sx, sy)
        self.update()


# ─────────────────────────────────────────────
#  Curve List Panel
# ─────────────────────────────────────────────

class CurveListPanel(QWidget):
    curveVisibilityChanged = pyqtSignal()
    curveSelectionChanged  = pyqtSignal()
    curveLockChanged       = pyqtSignal()

    def __init__(self, curves: List[AnimCurve],
                 color_registry: Optional[CurveColorRegistry] = None,
                 parent=None):
        super().__init__(parent)
        self.curves = curves
        self._registry = color_registry or CurveColorRegistry()
        self.setFixedWidth(180)
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(2)

        header = QLabel("CURVES")
        header.setEnabled(False)
        layout.addWidget(header)

        #print( self.curves)

        self._rows: List[Tuple[AnimCurve, QCheckBox, QPushButton, QPushButton]] = []
        for i, curve in enumerate(self.curves):
            row = QHBoxLayout()
            row.setContentsMargins(2, 1, 2, 1)
            row.setSpacing(2)

            vis_btn = QCheckBox()
            vis_btn.setChecked(curve.visible)
            vis_btn.setFixedWidth(18)
            vis_btn.setToolTip("Show/hide curve")
            vis_btn.stateChanged.connect(lambda state, c=curve: self._toggle_vis(c, state))

            c = self._registry.resolve(curve, i)
            swatch = QFrame()
            swatch.setFixedSize(10, 10)
            swatch.setStyleSheet(
                f"background: rgb({c.red()},{c.green()},{c.blue()}); border-radius: 2px;"
            )

            lbl = QPushButton(curve.name)
            lbl.setCheckable(True)
            lbl.setChecked(curve.selected)
            lbl.setFlat(True)
            lbl.clicked.connect(lambda checked, c=curve: self._toggle_sel(c, checked))

            lock_btn = QPushButton("🔓" if not curve.locked else "🔒")
            lock_btn.setFixedSize(22, 22)
            lock_btn.setFlat(True)
            lock_btn.setToolTip("Lock curve (keys not selectable)")
            lock_btn.clicked.connect(lambda _, c=curve, b=lock_btn: self._toggle_lock(c, b))

            row.addWidget(vis_btn)
            row.addWidget(swatch)
            row.addWidget(lbl, 1)
            row.addWidget(lock_btn)
            layout.addLayout(row)
            self._rows.append((curve, vis_btn, lbl, lock_btn))

        layout.addStretch()

    def _toggle_vis(self, curve: AnimCurve, state: int):
        curve.visible = bool(state)
        self.curveVisibilityChanged.emit()

    def _toggle_sel(self, curve: AnimCurve, checked: bool):
        curve.selected = checked
        self.curveSelectionChanged.emit()

    def _toggle_lock(self, curve: AnimCurve, btn: QPushButton):
        curve.locked = not curve.locked
        btn.setText("🔒" if curve.locked else "🔓")
        self.curveLockChanged.emit()

    def refresh(self):
        for curve, vis_btn, lbl, lock_btn in self._rows:
            vis_btn.setChecked(curve.visible)
            lbl.setChecked(curve.selected)
            lock_btn.setText("🔒" if curve.locked else "🔓")


# ─────────────────────────────────────────────
#  Properties Panel
# ─────────────────────────────────────────────

class PropertiesPanel(QWidget):
    valueChanged = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedWidth(200)
        self.time_scale: float = 1.0   # kept in sync with the viewport
        self._selected_key: Optional[Tuple[AnimCurve, KeyFrame]] = None
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(4)

        header = QLabel("KEY PROPERTIES")
        header.setEnabled(False)
        layout.addWidget(header)

        grp = QGroupBox("Selected Key")
        form = QFormLayout(grp)
        form.setSpacing(4)

        self._time_spin = QDoubleSpinBox()
        self._time_spin.setRange(-9999, 9999)
        self._time_spin.setDecimals(3)
        self._time_spin.valueChanged.connect(self._on_time_changed)

        self._value_spin = QDoubleSpinBox()
        self._value_spin.setRange(-9999, 9999)
        self._value_spin.setDecimals(3)
        self._value_spin.valueChanged.connect(self._on_value_changed)

        self._tangent_mode = QComboBox()
        self._tangent_mode.addItems(["auto", "free", "aligned", "flat", "stepped"])
        self._tangent_mode.currentTextChanged.connect(self._on_tangent_mode_changed)

        self._locked_chk = QCheckBox("Lock handles [L]")
        self._locked_chk.stateChanged.connect(self._on_locked_changed)

        for label, widget in [("Time", self._time_spin),
                               ("Value", self._value_spin),
                               ("Tangent", self._tangent_mode)]:
            form.addRow(QLabel(label), widget)
        form.addRow(self._locked_chk)

        layout.addWidget(grp)
        layout.addStretch()

        self._no_sel_label = QLabel("No key selected")
        self._no_sel_label.setStyleSheet("color: #555; font: 9px 'Courier New'; padding: 4px;")
        self._no_sel_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self._no_sel_label)
        grp.setVisible(False)
        self._grp = grp

    def set_selected_keys(self, curves: List[AnimCurve]):
        selected = [(c, k) for c in curves for k in c.keyframes if k.selected]
        if len(selected) == 1:
            c, key = selected[0]
            self._selected_key = (c, key)
            self._grp.setVisible(True)
            self._no_sel_label.setVisible(False)
            self._time_spin.blockSignals(True)
            self._value_spin.blockSignals(True)
            self._tangent_mode.blockSignals(True)
            self._locked_chk.blockSignals(True)
            self._time_spin.setValue(key.time * self.time_scale)
            self._value_spin.setValue(key.value)
            self._tangent_mode.setCurrentText(key.tangent_mode)
            self._locked_chk.setChecked(key.locked)
            self._time_spin.blockSignals(False)
            self._value_spin.blockSignals(False)
            self._tangent_mode.blockSignals(False)
            self._locked_chk.blockSignals(False)
        else:
            self._selected_key = None
            self._grp.setVisible(False)
            count = len(selected)
            self._no_sel_label.setText(
                f"{count} keys selected" if count > 1 else "No key selected"
            )
            self._no_sel_label.setVisible(True)

    def _on_time_changed(self, v):
        if self._selected_key:
            scale = self.time_scale if self.time_scale != 0.0 else 1.0
            self._selected_key[1].time = v / scale
            self.valueChanged.emit()

    def _on_value_changed(self, v):
        if self._selected_key:
            self._selected_key[1].value = v
            self.valueChanged.emit()

    def _on_tangent_mode_changed(self, mode):
        if self._selected_key:
            self._selected_key[1].tangent_mode = mode
            self.valueChanged.emit()

    def _on_locked_changed(self, state):
        if self._selected_key:
            self._selected_key[1].locked = bool(state)
            self.valueChanged.emit()


# ─────────────────────────────────────────────
#  Curve Editor Widget  (embeddable)
# ─────────────────────────────────────────────

class AnimCurveEditor(QWidget):
    """
    Self-contained animation curve editor widget.

    Drop it into any layout like any other QWidget:

        editor = AnimCurveEditor(parent=self)
        editor.set_curves([...])          # supply your own AnimCurve list
        layout.addWidget(editor)

    Color registry — decouple curve colors from curve data::

        reg = CurveColorRegistry({
            "translateX": QColor(255, 80,  80),
            "translateY": QColor( 80, 255, 80),
            "translateZ": QColor( 80, 120, 255),
        })
        editor.set_color_registry(reg)

        # Or pass at construction time
        editor = AnimCurveEditor(curves=my_curves, color_registry=reg)

    Signals forwarded from the inner viewport:
        timeChanged(float)      – playhead scrubbed
        keyframeEdited()        – any key/tangent modified
        selectionChanged()      – key selection changed

    Useful attributes after construction:
        editor.curves           – the live List[AnimCurve]
        editor.color_registry   – the CurveColorRegistry in use
        editor.viewport         – the CurveViewport canvas
        editor.current_time     – property, r/w
    """

    timeChanged      = pyqtSignal(float)
    timeChangedValues= pyqtSignal(list)
    keyframeEdited   = pyqtSignal()
    selectionChanged = pyqtSignal()

    def __init__(self, curves: Optional[List[AnimCurve]] = None,
                 color_registry: Optional[CurveColorRegistry] = None,
                 time_scale: float = 1.0,
                 parent=None):
        super().__init__(parent)
        self.setMinimumSize(600, 300)

        self.curves: List[AnimCurve] = curves if curves is not None else []
        self.color_registry: CurveColorRegistry = color_registry or CurveColorRegistry()
        self._initial_time_scale = time_scale
        self._build_ui()
        self._connect_signals()
        QTimer.singleShot(100, self.viewport.frame_all)

    # ── public API ─────────────────────────────

    def set_curves(self, curves: List[AnimCurve], reframe: bool=True) -> None:
        """Replace the current curve list and refresh the editor."""
        self.curves = curves
        self.viewport.curves = curves
        self._rebuild_curve_list()
        if reframe:
            self.viewport.frame_all()

    def set_color_registry(self, registry: CurveColorRegistry) -> None:
        """Swap in a new color registry and refresh all visuals."""
        self.color_registry = registry
        self.viewport.color_registry = registry
        self._rebuild_curve_list()
        self.viewport.update()

    def add_curve(self, curve: AnimCurve) -> None:
        """Append a single curve and refresh."""
        self.curves.append(curve)
        self.viewport.curves = self.curves
        self._rebuild_curve_list()
        self.viewport.update()

    @property
    def current_time(self) -> float:
        """Current playhead position in raw ticks."""
        return self.viewport.current_time

    @current_time.setter
    def current_time(self, t: float) -> None:
        """Set playhead in raw ticks; label shows display units."""        
        t = t/self.time_scale  
        self.viewport.current_time = t
        display_t = self.viewport._ticks_to_display(t)
        self._time_lbl.setText(f"T: {display_t:.3f}")
        self.viewport.timeChanged.emit(display_t)
        self.viewport.update()        

    @property
    def time_scale(self) -> float:
        """Multiplier applied to raw time values for display (e.g. 1/160 converts ticks→frames)."""
        return self.viewport.time_scale

    @time_scale.setter
    def time_scale(self, scale: float) -> None:
        self.viewport.time_scale = scale
        self.props.time_scale = scale
        self.viewport.update()

    @property
    def snap_playhead(self) -> bool:
        """If True, the playhead snaps to whole frame boundaries when scrubbed."""
        return self.viewport._snap_playhead

    @snap_playhead.setter
    def snap_playhead(self, on: bool) -> None:
        self.viewport._snap_playhead = on
        self._snap_ph_toggle.setChecked(on)   # keep toolbar button in sync

    # ── internal build ─────────────────────────

    @staticmethod
    def _auto_tangent(curve: AnimCurve, key: KeyFrame) -> None:
        if key.tangent_mode != "auto":
            return
        keys = sorted(curve.keyframes, key=lambda k: k.time)
        idx = keys.index(key)
        if 0 < idx < len(keys) - 1:
            prev, nxt = keys[idx - 1], keys[idx + 1]
            slope = (nxt.value - prev.value) / max(nxt.time - prev.time, 1e-9)
            key.tangent_in  = QPointF(-0.333, -slope * 0.333)
            key.tangent_out = QPointF( 0.333,  slope * 0.333)
        elif idx == 0 and len(keys) > 1:
            nxt = keys[1]
            slope = (nxt.value - key.value) / max(nxt.time - key.time, 1e-9)
            key.tangent_out = QPointF( 0.333,  slope * 0.333)
            key.tangent_in  = QPointF(-0.333, -slope * 0.333)
        elif idx == len(keys) - 1 and len(keys) > 1:
            prev = keys[-2]
            slope = (key.value - prev.value) / max(key.time - prev.time, 1e-9)
            key.tangent_in  = QPointF(-0.333, -slope * 0.333)
            key.tangent_out = QPointF( 0.333,  slope * 0.333)

    def _build_ui(self) -> None:
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # Body row
        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)

        # Curve list panel
        self.curve_list = CurveListPanel(self.curves, self.color_registry)
        body.addWidget(self.curve_list)

        body.addWidget(self._vline())

        # Viewport — created before toolbar so toolbar callbacks can reference it
        self.viewport = CurveViewport()
        self.viewport.curves = self.curves
        self.viewport.color_registry = self.color_registry
        self.viewport.time_scale = self._initial_time_scale
        body.addWidget(self.viewport, 1)

        body.addWidget(self._vline())

        # Properties panel
        self.props = PropertiesPanel()
        self.props.time_scale = self._initial_time_scale
        body.addWidget(self.props)

        # Toolbar sits above the body
        main_layout.addWidget(self._build_toolbar())
        main_layout.addLayout(body, 1)

        # Bottom bar: hint text left, curve value readout right
        bottom = QWidget()
        bottom.setFixedHeight(20)
        bottom_layout = QHBoxLayout(bottom)
        bottom_layout.setContentsMargins(6, 0, 6, 0)
        bottom_layout.setSpacing(0)

        self._status = QLabel(
            "Double-click to add key  |  Del to remove  |  F frame all  |  "
            "S flatten  |  L lock handles  |  Scroll zoom  |  MMB pan"
        )
        self._status.setEnabled(False)
        bottom_layout.addWidget(self._status)

        bottom_layout.addStretch()

        self._curve_readout = QLabel("")
        self._curve_readout.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        bottom_layout.addWidget(self._curve_readout)

        main_layout.addWidget(bottom)

    @staticmethod
    def _vline() -> QFrame:
        f = QFrame()
        f.setFrameShape(QFrame.VLine)
        f.setFrameShadow(QFrame.Sunken)
        return f

    def _build_toolbar(self) -> QWidget:
        bar = QWidget()
        bar.setFixedHeight(36)
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(8, 2, 8, 2)
        layout.setSpacing(4)

        def btn(label, tip, cb):
            b = QPushButton(label)
            b.setToolTip(tip)
            b.setFixedHeight(26)
            b.clicked.connect(cb)
            return b

        layout.addWidget(btn("Frame All [F]",    "Frame all keyframes",                self.viewport.frame_all))
        layout.addWidget(btn("Frame Sel",        "Frame selected keyframes",           self.viewport.frame_selected))
        layout.addWidget(btn("Select All [A]",   "Select all keys",                    self.viewport._select_all))
        layout.addWidget(btn("Delete",           "Delete selected keys",               self.viewport._delete_selected))
        layout.addWidget(btn("Flatten [S]",      "Flatten selected tangents",          self.viewport._flatten_selected_tangents))
        layout.addWidget(btn("Lock [L]",         "Toggle locked handles on selection", self.viewport._toggle_lock_selected))

        layout.addSpacing(16)

        self._tan_toggle = QPushButton("Tangents: ON")
        self._tan_toggle.setCheckable(True)
        self._tan_toggle.setChecked(True)
        self._tan_toggle.setFixedHeight(26)
        self._tan_toggle.toggled.connect(self._toggle_tangents)
        layout.addWidget(self._tan_toggle)

        self._snap_ph_toggle = QPushButton("Snap: OFF")
        self._snap_ph_toggle.setCheckable(True)
        self._snap_ph_toggle.setChecked(False)
        self._snap_ph_toggle.setFixedHeight(26)
        self._snap_ph_toggle.setToolTip("Snap playhead to whole frames")
        self._snap_ph_toggle.toggled.connect(self._toggle_snap_playhead)
        layout.addWidget(self._snap_ph_toggle)

        layout.addSpacing(16)

        self._time_lbl = QLabel("T: 0.000")
        layout.addWidget(self._time_lbl)

        layout.addStretch()

        layout.addWidget(btn("+ Add Curve", "Add a new curve", self._add_curve))

        return bar

    def _connect_signals(self) -> None:
        self.viewport.selectionChanged.connect(self._on_selection_changed)
        self.viewport.keyframeEdited.connect(self._on_key_edited)
        self.viewport.timeChanged.connect(self._on_time_changed)
        self.curve_list.curveVisibilityChanged.connect(self.viewport.update)
        self.curve_list.curveVisibilityChanged.connect(self._update_curve_readout)
        self.curve_list.curveSelectionChanged.connect(self.viewport.update)
        self.curve_list.curveLockChanged.connect(self.viewport.update)
        self.props.valueChanged.connect(self.viewport.update)
        self.props.valueChanged.connect(self._update_curve_readout)
        # Re-emit for external consumers
        self.viewport.timeChanged.connect(self.timeChanged)
        self.viewport.keyframeEdited.connect(self.keyframeEdited)
        self.viewport.selectionChanged.connect(self.selectionChanged)

    # ── slots ──────────────────────────────────

    def _toggle_tangents(self, on: bool) -> None:
        self.viewport._show_tangents = on
        self._tan_toggle.setText(f"Tangents: {'ON' if on else 'OFF'}")
        self.viewport.update()

    def _toggle_snap_playhead(self, on: bool) -> None:
        self.viewport._snap_playhead = on
        self._snap_ph_toggle.setText(f"Snap: {'ON' if on else 'OFF'}")

    def _on_selection_changed(self) -> None:
        self.props.set_selected_keys(self.curves)

    def _on_key_edited(self) -> None:
        self.props.set_selected_keys(self.curves)
        self.viewport.update()
        self._update_curve_readout()

    def _on_time_changed(self, t: float) -> None:
        self._time_lbl.setText(f"T: {t:.3f}")
        self._update_curve_readout()

    def _update_curve_readout(self) -> None:
        t = self.viewport.current_time
        parts = []
        curve_values = []
        for i, curve in enumerate(self.curves):
            if not curve.visible or not curve.keyframes:
                continue
            v = curve.evaluate(t)
            curve_values.append(v)            
            color = self.color_registry.resolve(curve, i)
            hex_col = f"#{color.red():02x}{color.green():02x}{color.blue():02x}"
            parts.append(
                f'<span style="color:{hex_col};">&#9632; {curve.name}: <b>{v:.4g}</b></span>'
            )
        self._curve_readout.setText("&nbsp;&nbsp;".join(parts))
        self.timeChangedValues.emit(curve_values)

    def _add_curve(self) -> None:
        idx = len(self.curves)
        # No color set — registry will resolve it at draw time
        curve = AnimCurve(f"curve{idx + 1}")
        curve.keyframes = [KeyFrame(0.0, 0.0), KeyFrame(5.0, 1.0), KeyFrame(10.0, 0.0)]
        for key in curve.keyframes:
            self._auto_tangent(curve, key)
        self.curves.append(curve)
        self.viewport.curves = self.curves
        self._rebuild_curve_list()
        self.viewport.update()

    def _rebuild_curve_list(self) -> None:
        """Swap in a fresh CurveListPanel reflecting the current curve list."""
        old = self.curve_list
        self.curve_list = CurveListPanel(self.curves, self.color_registry)
        self.curve_list.curveVisibilityChanged.connect(self.viewport.update)
        self.curve_list.curveSelectionChanged.connect(self.viewport.update)
        # Find the body QHBoxLayout that owns the old panel and replace it
        body_layout = old.parent().layout()
        body_layout.replaceWidget(old, self.curve_list)
        old.deleteLater()


# ─────────────────────────────────────────────
#  Standalone entry point
# ─────────────────────────────────────────────

def _make_demo_curves() -> List[AnimCurve]:
    """Build a small set of demo curves for standalone testing."""

    def auto_all(curve):
        keys = sorted(curve.keyframes, key=lambda k: k.time)
        for key in keys:
            if key.tangent_mode != "auto":
                continue
            idx = keys.index(key)
            if 0 < idx < len(keys) - 1:
                prev, nxt = keys[idx - 1], keys[idx + 1]
                slope = (nxt.value - prev.value) / max(nxt.time - prev.time, 1e-9)
                key.tangent_in  = QPointF(-0.333, -slope * 0.333)
                key.tangent_out = QPointF( 0.333,  slope * 0.333)
            elif idx == 0 and len(keys) > 1:
                nxt = keys[1]
                slope = (nxt.value - key.value) / max(nxt.time - key.time, 1e-9)
                key.tangent_out = QPointF( 0.333,  slope * 0.333)
                key.tangent_in  = QPointF(-0.333, -slope * 0.333)
            elif idx == len(keys) - 1 and len(keys) > 1:
                prev = keys[-2]
                slope = (key.value - prev.value) / max(key.time - prev.time, 1e-9)
                key.tangent_in  = QPointF(-0.333, -slope * 0.333)
                key.tangent_out = QPointF( 0.333,  slope * 0.333)

    # No colors set — registry (or default cycle) will resolve them
    c1 = AnimCurve("translateX")
    c1.keyframes = [KeyFrame(0,0), KeyFrame(2,1.5), KeyFrame(5,-0.5), KeyFrame(8,2), KeyFrame(10,1)]
    auto_all(c1)

    c2 = AnimCurve("translateY")
    c2.keyframes = [KeyFrame(0,0), KeyFrame(1.5,2), KeyFrame(3,0.2), KeyFrame(4.5,1.2), KeyFrame(6,0), KeyFrame(10,0)]
    auto_all(c2)

    c3 = AnimCurve("scaleX")
    c3.keyframes = [KeyFrame(0,1), KeyFrame(4,1.8), KeyFrame(7,0.7), KeyFrame(10,1)]
    auto_all(c3)

    return [c1, c2, c3]


def main():
    app = QApplication(sys.argv)

    # No palette forced here — the widget inherits whatever theme the app uses.
    # To test with a specific theme, e.g.:
    #   app.setStyle("Fusion")
    # or load qt_themes before creating the QApplication.

    win = QMainWindow()
    win.setWindowTitle("Animation Curve Editor")
    win.resize(1200, 680)

    editor = AnimCurveEditor(curves=_make_demo_curves())
    win.setCentralWidget(editor)

    editor.timeChanged.connect(lambda t: None)   # replace with your handler

    win.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()