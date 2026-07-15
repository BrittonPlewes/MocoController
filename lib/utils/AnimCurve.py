from dataclasses import dataclass, field
from PyQt5.QtCore import QPointF

# ─────────────────────────────────────────────
#  Data Model
# ─────────────────────────────────────────────

@dataclass
class KeyFrame:
    time: float
    value: float
    tangent_in: QPointF = field(default_factory=lambda: QPointF(-0.3, 0.0))
    tangent_out: QPointF = field(default_factory=lambda: QPointF(0.3, 0.0))
    tangent_mode: str = "auto"   # "auto", "free", "aligned", "flat", "stepped"
    selected: bool = False
    locked: bool = False          # when True, in/out handles move as a mirrored pair
    inv: bool = False
    


    @property
    def value(self) -> float:
        return self._value*self._invertMult()

    @value.setter
    def value(self, v: float):
        self._value = v

    @property
    def tangent_in(self) -> QPointF:
        val = self._value-self._tangent_in.y()
        
        point = QPointF( self._tangent_in.x(), self.value- val*self._invertMult()  )
        return point

    @tangent_in.setter
    def tangent_in(self, point: QPointF):
        self._tangent_in = point
    
    @property
    def tangent_out(self) -> QPointF:
        val = self._value-self._tangent_out.y()
        
        point = QPointF( self._tangent_out.x(), self.value- val*self._invertMult()  )
        return point

    @tangent_out.setter
    def tangent_out(self, point: QPointF):
        self._tangent_out = point


    def setInvert( self, inv ):
        self.inv = inv       


    def copy(self):
        k = KeyFrame(self.time, self._value,
                     QPointF(self._tangent_in), QPointF(self._tangent_out),
                     self.tangent_mode, self.selected, self.locked, self.inv)
        return k
    
    def _invertMult(self):
        return ((self.inv*2)-1)*-1    


@dataclass
class AnimCurve:
    name: str
    color: Optional[QColor] = None   # None → resolved via CurveColorRegistry at draw time
    keyframes: List[KeyFrame] = field(default_factory=list)
    visible: bool = True
    selected: bool = False
    locked: bool = False   # curve is visible but keys are not selectable/draggable
    ticksPerFrame: int = 0
    invert: bool = False
    t_offset: float = 0.0
    
    # ── Forward lookup: time → value ──────────────────────────────────────────

    def _invertMult(self):
        return ((self.invert*2)-1)*-1
    
    def setInvert( self, inv ):
        self.invert = inv
        for key in self.keyframes:
            key.setInvert(inv)

    def evaluate(self, t: float, ticks: bool = True) -> float:        
        if not ticks:
            t = t*self.ticksPerFrame

        t+= self.t_offset*self.ticksPerFrame

        keys = sorted(self.keyframes, key=lambda k: k.time)
        if not keys:
            return 0.0
        if t <= keys[0].time:
            return keys[0].value
        if t >= keys[-1].time:
            return keys[-1].value

        for i in range(len(keys) - 1):
            k0, k1 = keys[i], keys[i + 1]
            if k0.time <= t <= k1.time:
                return self._eval_segment(k0, k1, t)  #*self._invertMult()
        return 0.0

    # ── Inverse lookup: value → [times] ───────────────────────────────────────
 
    def evaluate_inverse(self, value: float, tolerance: float = 1e-5, ticks: bool = True) -> List[float]:
        """Return all times at which the curve equals *value*.
 
        Because a curve can be multi-valued (e.g. a bounce) this always returns
        a list.  Results are sorted in ascending time order.
 
        Strategy per segment
        --------------------
        1. Build the same four Bezier control points used by _eval_segment.
        2. Use Newton-Raphson to solve for every `u` in [0, 1] where B_y(u) == value,
           seeding from multiple starting points so we catch all roots.
        3. Each valid `u` is mapped back through B_x(u) to get the actual time.
 
        Stepped segments contribute the keyframe time if value == k0.value.
        """
        keys = sorted(self.keyframes, key=lambda k: k.time)
        if not keys:
            return []
 
        times: List[float] = []
 
        # Check flat extrapolation regions
        if abs(keys[0].value - value) < tolerance:
            times.append(keys[0].time)
        if len(keys) > 1 and abs(keys[-1].value - value) < tolerance:
            times.append(keys[-1].time)
 
        for i in range(len(keys) - 1):
            k0, k1 = keys[i], keys[i + 1]
            segment_times = self._inverse_segment(k0, k1, value, tolerance)
            times.extend(segment_times)
 
        # Deduplicate and sort
        times.sort()
        deduped: List[float] = []
        for t in times:
            if not deduped or abs(t - deduped[-1]) > tolerance:
                t-= self.t_offset*self.ticksPerFrame
                if not ticks:
                    t = t/self.ticksPerFrame
                deduped.append(t)
        return deduped
 
    def _inverse_segment(
        self, k0: KeyFrame, k1: KeyFrame, target_value: float, tolerance: float
    ) -> List[float]:
        """Find all times within segment [k0, k1] where the curve == target_value."""
        dt = k1.time - k0.time
        if dt == 0:
            return []
 
        # Stepped: whole segment holds k0.value
        if k0.tangent_mode == "stepped":
            if abs(k0.value - target_value) < tolerance:
                return [k0.time]
            return []
 
        # Build the same control points as _eval_segment
        p0 = QPointF(k0.time, k0.value)
        p3 = QPointF(k1.time, k1.value)
        p1 = p0 + QPointF(k0.tangent_out.x() * dt, k0.tangent_out.y())
        p2 = p3 + QPointF(k1.tangent_in.x() * dt, k1.tangent_in.y())
 
        y0, y1, y2, y3 = p0.y(), p1.y(), p2.y(), p3.y()
        x0, x1, x2, x3 = p0.x(), p1.x(), p2.x(), p3.x()
 
        # Solve B_y(u) = target_value via Newton-Raphson from several seeds
        # to catch multiple roots across the [0, 1] parameter range.
        NUM_SEEDS = 16
        found_u: List[float] = []
 
        for seed_i in range(NUM_SEEDS):
            u = seed_i / (NUM_SEEDS - 1)   # evenly spaced seeds in [0, 1]
            for _ in range(32):
                y = self._bezier(y0, y1, y2, y3, u)
                dy = (3*(1-u)**2*(y1-y0) + 6*(1-u)*u*(y2-y1) + 3*u**2*(y3-y2))
                if abs(dy) < 1e-12:
                    break
                u -= (y - target_value) / dy
                u = max(0.0, min(1.0, u))
 
            y_final = self._bezier(y0, y1, y2, y3, u)
            if abs(y_final - target_value) < tolerance and 0.0 <= u <= 1.0:
                # Check it isn't a duplicate of an already-found root
                if not any(abs(u - uu) < 1e-6 for uu in found_u):
                    found_u.append(u)
 
        # Map each valid u back to an actual time via B_x(u)
        result_times: List[float] = []
        for u in found_u:
            t = self._bezier(x0, x1, x2, x3, u)
            # Clamp to segment bounds to absorb floating-point drift
            t = max(k0.time, min(k1.time, t))
            result_times.append(t)
 
        return result_times

    # ── Shared bezier helpers ─────────────────────────────────────────────────

    def _eval_segment(self, k0: KeyFrame, k1: KeyFrame, t: float) -> float:
        dt = k1.time - k0.time
        if dt == 0:
            return k1.value
        u = (t - k0.time) / dt

        if k0.tangent_mode == "stepped":
            return k0.value

        # Cubic hermite via bezier control points
        p0 = QPointF(k0.time, k0.value)
        p3 = QPointF(k1.time, k1.value)
        p1 = p0 + QPointF(k0.tangent_out.x() * dt, k0.tangent_out.y())
        p2 = p3 + QPointF(k1.tangent_in.x() * dt, k1.tangent_in.y())

        # Solve for u given t using Newton-Raphson on X
        uu = self._solve_t_for_x(p0.x(), p1.x(), p2.x(), p3.x(), t)
        return self._bezier_y(p0.y(), p1.y(), p2.y(), p3.y(), uu)

    @staticmethod
    def _bezier(p0, p1, p2, p3, t):
        mt = 1 - t
        return mt**3*p0 + 3*mt**2*t*p1 + 3*mt*t**2*p2 + t**3*p3

    def _bezier_y(self, y0, y1, y2, y3, t):
        return self._bezier(y0, y1, y2, y3, t)

    def _solve_t_for_x(self, x0, x1, x2, x3, target_x, iterations=8):
        t = (target_x - x0) / max(x3 - x0, 1e-9)
        for _ in range(iterations):
            x = self._bezier(x0, x1, x2, x3, t)
            dx = (3*(1-t)**2*(x1-x0) + 6*(1-t)*t*(x2-x1) + 3*t**2*(x3-x2))
            if abs(dx) < 1e-10:
                break
            t -= (x - target_x) / dx
            t = max(0.0, min(1.0, t))
        return t
