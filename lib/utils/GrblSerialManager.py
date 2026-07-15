"""
grbl_serial_manager.py
~~~~~~~~~~~~~~~~~~~~~~~
Thread-safe GRBL serial manager with native PyQt5/PyQt6 signals.

Signals emitted (connect these in your GUI):
    signals.status_updated(MachineStatus)
    signals.message_received(GrblMessage)
    signals.alarm_raised(str)
    signals.error_raised(str)
    signals.connection_changed(bool)       # True = connected
    signals.stream_progress(int, int)      # lines_done, lines_total
    signals.stream_command_sent(int)       # index of each command as it is written to the device
    signals.stream_finished(bool)          # True = success
    signals.axes_detected(int)            # emitted once when axis count is first auto-detected
    signals.command_sent(str)             # text of every line written to the controller (excludes status polls)

Usage
-----
    from grbl_serial_manager import GrblSerialManager, GrblSignals

    self.grbl = GrblSerialManager(port="/dev/ttyUSB0")
    self.grbl.signals.status_updated.connect(self.on_status)
    self.grbl.signals.alarm_raised.connect(self.on_alarm)
    self.grbl.signals.stream_command_sent.connect(self.on_command_sent)  # receives index
    self.grbl.connect()

    self.grbl.send("G0 X10 Y10")
    self.grbl.stream_commands(["G0 X0 Y0", "G1 X10 F500", "G1 Y10"])
    self.grbl.stream_file("job.gcode")
    self.grbl.feed_hold()
    self.grbl.disconnect()
"""

from __future__ import annotations

import re
import threading
import time
import queue
import logging
from dataclasses import dataclass, field
from enum import Enum, auto
from pathlib import Path
from typing import Optional

try:
    import serial
    import serial.tools.list_ports
except ImportError:
    raise ImportError("pyserial is required: pip install pyserial")

# Support both PyQt5 and PyQt6

try:
    from PyQt5.QtCore import QObject, pyqtSignal
    _PYQT = "PyQt5"
except ImportError:
    raise ImportError("PyQt5 or PyQt6 is required: pip install PyQt5  or  pip install PyQt6")

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

class MachineState(Enum):
    IDLE    = "Idle"
    RUN     = "Run"
    HOLD    = "Hold"
    JOG     = "Jog"
    ALARM   = "Alarm"
    DOOR    = "Door"
    CHECK   = "Check"
    HOME    = "Home"
    SLEEP   = "Sleep"
    UNKNOWN = "Unknown"


# Canonical axis label ordering — values beyond Z are rotary/extended axes.
AXIS_LABELS = ("X", "Y", "Z", "A", "B", "C")


@dataclass
class AxisPosition:
    """
    An n-axis position vector. Axis count is determined at parse time and
    can be anywhere from 2 (XY router) up to 6 (XYZABC).

    Values are accessible by index (pos[0]) or by label (pos["X"]).
    """
    values: list = field(default_factory=list)

    def __getitem__(self, key):
        if isinstance(key, str):
            key = AXIS_LABELS.index(key.upper())
        return self.values[key]

    def __len__(self):
        return len(self.values)

    @property
    def labels(self):
        return AXIS_LABELS[: len(self.values)]

    @property
    def x(self): return self.values[0] if len(self.values) > 0 else 0.0
    @property
    def y(self): return self.values[1] if len(self.values) > 1 else 0.0
    @property
    def z(self): return self.values[2] if len(self.values) > 2 else 0.0
    @property
    def a(self): return self.values[3] if len(self.values) > 3 else 0.0
    @property
    def b(self): return self.values[4] if len(self.values) > 4 else 0.0
    @property
    def c(self): return self.values[5] if len(self.values) > 5 else 0.0

    def __repr__(self):
        parts = [f"{lbl}={v:.3f}" for lbl, v in zip(self.labels, self.values)]
        return f"({', '.join(parts)})"

    @staticmethod
    def zero(n):
        return AxisPosition([0.0] * n)

    @staticmethod
    def from_match(m):
        """Parse all captured groups from a position regex match into an AxisPosition."""
        if not m:
            return AxisPosition()
        return AxisPosition([float(m.group(i + 1)) for i in range(len(m.groups()))])


@dataclass
class MachineStatus:
    state:    MachineState = MachineState.UNKNOWN
    mpos:     AxisPosition = field(default_factory=AxisPosition)
    wpos:     AxisPosition = field(default_factory=AxisPosition)
    wco:      AxisPosition = field(default_factory=AxisPosition)
    feed:     float        = 0.0
    spindle:  float        = 0.0
    num_axes: int          = 0
    raw:      str          = ""


class GrblMessage:
    class Kind(Enum):
        OK       = auto()
        ERROR    = auto()
        ALARM    = auto()
        STATUS   = auto()
        WELCOME  = auto()
        SETTING  = auto()
        FEEDBACK = auto()
        UNKNOWN  = auto()

    def __init__(self, kind: "GrblMessage.Kind", text: str,
                 status: Optional[MachineStatus] = None):
        self.kind   = kind
        self.text   = text
        self.status = status

    def __repr__(self) -> str:
        return f"GrblMessage({self.kind.name}, {self.text!r})"


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------

# State is always the first token: <State|...> or <State:subcode|...>
_STATE_RE = re.compile(r"<([^|>]+)")

# Position fields: capture up to 6 comma-separated floats after the key.
# Each axis slot is an explicit optional group so re.groups() returns them all.
_CV = r"(-?[\d.]+)"   # one captured float value
_OV = r"(?:,(-?[\d.]+))?"  # one optional additional axis

def _pos_re(key: str) -> "re.Pattern":
    """
    Build a position regex for a given field key (MPos, WPos, WCO).
    Groups 1-6 correspond to axes X Y Z A B C; trailing axes are None if absent.
    """
    return re.compile(
        r"\|" + key + r":" + _CV + (_OV * 5)
    )

_MPOS_RE = _pos_re("MPos")
_WPOS_RE = _pos_re("WPos")
_WCO_RE  = _pos_re("WCO")
_FS_RE   = re.compile(r"\|FS:(-?[\d.]+),(-?[\d.]+)")  # feed,spindle (GRBL 1.1)
_F_RE    = re.compile(r"\|F:(-?[\d.]+)")               # feed only (some variants)


def _parse_pos(m: "re.Match | None") -> "AxisPosition":
    """Convert a position regex match into an AxisPosition, dropping trailing None groups."""
    if not m:
        return AxisPosition()
    return AxisPosition([float(v) for v in m.groups() if v is not None])


def parse_response(line: str) -> GrblMessage:
    line = line.strip()

    if line == "ok":
        return GrblMessage(GrblMessage.Kind.OK, line)
    if line.startswith("error:"):
        return GrblMessage(GrblMessage.Kind.ERROR, line)
    if line.startswith("ALARM:"):
        return GrblMessage(GrblMessage.Kind.ALARM, line)
    if line.startswith("Grbl "):
        return GrblMessage(GrblMessage.Kind.WELCOME, line)
    if line.startswith("$"):
        return GrblMessage(GrblMessage.Kind.SETTING, line)
    if line.startswith("[") and line.endswith("]"):
        return GrblMessage(GrblMessage.Kind.FEEDBACK, line)
    if line.startswith("<") and line.endswith(">"):
        return GrblMessage(GrblMessage.Kind.STATUS, line, status=_parse_status(line))

    return GrblMessage(GrblMessage.Kind.UNKNOWN, line)


def _parse_status(line: str, expected_axes: int = 0) -> MachineStatus:
    """
    Parse a GRBL status string into a MachineStatus.

    Parameters
    ----------
    line          : Raw status string, e.g. "<Idle|MPos:0,0,0,0|WCO:0,0,0,0|FS:0,0>"
    expected_axes : If > 0, zero-pad or truncate position vectors to this length.
                    If 0 (default), the axis count is inferred from the message itself.
    """
    # --- state ---
    sm = _STATE_RE.search(line)
    if not sm:
        return MachineStatus(raw=line)
    state_str = sm.group(1).split(":")[0].strip()
    try:
        state = MachineState(state_str)
    except ValueError:
        state = MachineState.UNKNOWN

    # --- positions ---
    mpos = _parse_pos(_MPOS_RE.search(line))
    wpos = _parse_pos(_WPOS_RE.search(line))
    wco  = _parse_pos(_WCO_RE.search(line))

    # Infer axis count from whichever position field is present
    detected = max(len(mpos), len(wpos), len(wco))
    num_axes = expected_axes if expected_axes > 0 else detected

    # Normalise all position vectors to num_axes (pad with 0.0 if needed)
    def _normalise(pos: AxisPosition) -> AxisPosition:
        if len(pos) == num_axes:
            return pos
        vals = pos.values + [0.0] * num_axes
        return AxisPosition(vals[:num_axes])

    mpos = _normalise(mpos)
    wpos = _normalise(wpos)
    wco  = _normalise(wco)

    # --- feed / spindle ---
    fs_m = _FS_RE.search(line)
    if fs_m:
        feed, spindle = float(fs_m.group(1)), float(fs_m.group(2))
    else:
        f_m     = _F_RE.search(line)
        feed    = float(f_m.group(1)) if f_m else 0.0
        spindle = 0.0

    return MachineStatus(
        state=state,
        mpos=mpos,
        wpos=wpos,
        wco=wco,
        feed=feed,
        spindle=spindle,
        num_axes=num_axes,
        raw=line,
    )


# ---------------------------------------------------------------------------
# Qt Signals container
# ---------------------------------------------------------------------------

class GrblSignals(QObject):
    """
    All signals emitted by GrblSerialManager.
    Connect these in your GUI widgets — they are thread-safe.
    """
    status_updated      = pyqtSignal(object)   # MachineStatus
    message_received    = pyqtSignal(object)   # GrblMessage
    alarm_raised        = pyqtSignal(str)
    error_raised        = pyqtSignal(str)
    connection_changed  = pyqtSignal(bool)     # True = connected
    stream_progress     = pyqtSignal(int, int) # done, total
    stream_command_sent = pyqtSignal(int)      # index of command written to device
    stream_finished     = pyqtSignal(bool)     # success
    axes_detected       = pyqtSignal(int)      # emitted once when axis count is first determined
    command_sent        = pyqtSignal(str)      # text of every line written to the controller (excludes status polls)


# ---------------------------------------------------------------------------
# Serial Manager
# ---------------------------------------------------------------------------

class GrblSerialManager:
    """
    Thread-safe GRBL serial manager with PyQt signals.

    Parameters
    ----------
    port          : Serial port string, e.g. "/dev/ttyUSB0" or "COM3"
    baud          : Baud rate (default 115200)
    poll_interval : Seconds between '?' status polls (0 = disabled)
    rx_buffer_size: GRBL receive buffer size for streaming flow-control
    """

    CMD_RESET      = b"\x18"
    CMD_STATUS     = b"?"
    CMD_HOLD       = b"!"
    CMD_RESUME     = b"~"
    CMD_JOG_CANCEL = b"\x85"
    CMD_STOP       = b"\x19"

    def __init__(
        self,
        port: str = "",
        baud: int = 115200,
        poll_interval: float = 0.25,
        rx_buffer_size: int = 127,
        axes: int = 0,
    ) -> None:
        """
        Parameters
        ----------
        axes : Expected number of axes (2–6).  When 0 (default) the axis count
               is auto-detected from the first status message received and the
               axes_detected signal is emitted.  Set explicitly to suppress
               auto-detection and lock in a fixed count.
        """
        self.port            = port
        self.baud            = baud
        self.poll_interval   = poll_interval
        self.rx_buffer_size  = rx_buffer_size
        self.axes            = axes   # 0 = auto-detect

        self.signals  = GrblSignals()
        self.status   = MachineStatus()
        self._axes_detected  = axes > 0   # True once we know the axis count

        self._serial:  Optional[serial.Serial] = None
        self._lock     = threading.Lock()
        self._stop_evt = threading.Event()
        self._tx_queue: queue.Queue[str] = queue.Queue()

        self._streaming    = False
        self._stream_lock  = threading.Lock()

    # ------------------------------------------------------------------
    # Port enumeration
    # ------------------------------------------------------------------

    @staticmethod
    def list_ports() -> list[str]:
        return [p.device for p in serial.tools.list_ports.comports()]

    # ------------------------------------------------------------------
    # Connection
    # ------------------------------------------------------------------

    def connect(self, port: str = "", baud: int = 0) -> None:
        if port:
            self.port = port
        if baud:
            self.baud = baud

        if not self.port:
            raise ValueError("No serial port specified.")

        if self._serial and self._serial.is_open:
            logger.warning("Already connected.")
            return

        logger.info(f"Connecting to {self.port} @ {self.baud}…")
        self._serial = serial.Serial(port=self.port, baudrate=self.baud, timeout=1.0)
        time.sleep(2.0)
        self._serial.flushInput()

        self._stop_evt.clear()

        for target, name in [
            (self._reader_loop, "grbl-reader"),
            (self._writer_loop, "grbl-writer"),
        ]:
            t = threading.Thread(target=target, name=name, daemon=True)
            t.start()

        if self.poll_interval > 0:
            t = threading.Thread(target=self._poll_loop, name="grbl-poller", daemon=True)
            t.start()

        self.signals.connection_changed.emit(True)
        logger.info("Connected.")

    def disconnect(self) -> None:
        logger.info("Disconnecting…")
        self._stop_evt.set()
        self._tx_queue.put_nowait("\x00")   # unblock writer

        time.sleep(0.3)

        if self._serial and self._serial.is_open:
            self._serial.close()
        self._serial = None

        self.signals.connection_changed.emit(False)
        logger.info("Disconnected.")

    @property
    def is_connected(self) -> bool:
        return bool(self._serial and self._serial.is_open)

    # ------------------------------------------------------------------
    # Command API
    # ------------------------------------------------------------------

    def send(self, cmd: str) -> None:
        """Queue a G-code line for sending."""
        self._tx_queue.put(cmd.strip())

    def send_realtime(self, cmd: bytes) -> None:
        """Send a real-time single-byte command immediately."""
        with self._lock:
            if self._serial and self._serial.is_open:
                self._serial.write(cmd)

    # Convenience real-time commands
    def soft_reset(self)   -> None: self.send_realtime(self.CMD_RESET)
    def feed_hold(self)    -> None: self.send_realtime(self.CMD_HOLD)
    def cycle_start(self)  -> None: self.send_realtime(self.CMD_RESUME)
    def request_status(self) -> None: self.send_realtime(self.CMD_STATUS)
    def jog_cancel(self)   -> None: self.send_realtime(self.CMD_JOG_CANCEL)    
    def unlock(self)       -> None: self.send("$X")    

    def jog(    self,
                x: float = 0, y: float = 0, z: float = 0, a: float = 0, b: float = 0,
                feed: float = 1000,
                units: str = "G21",
                abs_mode: bool = False
    ) -> None:
        """Send a $J jog command."""

        distance_mode = "G91"
        if abs_mode:
            distance_mode = "G90"

        parts = [f"$J={units}", distance_mode]
        if x: parts.append(f"X{x:.3f}")
        if y: parts.append(f"Y{y:.3f}")
        if z: parts.append(f"Z{z:.3f}")
        if a: parts.append(f"A{a:.3f}")
        if b: parts.append(f"B{b:.3f}")
        parts.append(f"F{feed:.0f}")
        self.send(" ".join(parts))

    def set(    self, x = None, y = None, z = None, a = None, b = None ):

        parts = ["G92"]

        if x: parts.append(f"X{x:.3f}")
        if y: parts.append(f"Y{y:.3f}")
        if z: parts.append(f"Z{z:.3f}")
        if a: parts.append(f"A{a:.3f}")
        if b: parts.append(f"B{b:.3f}")

        self.send(" ".join(parts))

    def home( self, axis=None ):
        axes = "XYZABC"        
        self.send("$H"+axes[axis] if axis else "")

    # ------------------------------------------------------------------
    # Streaming
    # ------------------------------------------------------------------

    def stream_commands(self, commands: list[str]) -> None:
        """
        Stream an explicit list of G-code command strings.

        Each non-empty string is sent as one line.  Comments (;… and (…))
        are NOT stripped here — pass pre-cleaned strings or use stream_file
        if you want automatic comment removal.

        Signals fired during streaming:
            stream_command_sent(index)   — as each command is written to the device
            stream_progress(done, total) — after each acknowledgement is received
            stream_finished(success)     — when the job ends
        """
        gcode = [c.strip() for c in commands if c.strip()]
        if not gcode:
            raise ValueError("Command list is empty.")
        with self._stream_lock:
            if self._streaming:
                raise RuntimeError("A job is already streaming.")
            self._streaming = True

        threading.Thread(
            target=self._stream_worker,
            args=(gcode,),
            name="grbl-streamer",
            daemon=True,
        ).start()

    def stream_file(self, path: str | Path, skip_comments: bool = True) -> None:
        """
        Stream a G-code file.  Parses and optionally strips comments, then
        delegates to stream_commands so both paths share the same worker.
        """
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"File not found: {path}")

        raw_lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        gcode: list[str] = []
        for raw in raw_lines:
            line = raw.strip()
            if skip_comments:
                line = re.sub(r"\(.*?\)", "", line)
                line = re.sub(r";.*$", "", line).strip()
            if line:
                gcode.append(line)

        self.stream_commands(gcode)

    def _stream_worker(self, gcode: list[str]) -> None:
        """
        Shared streaming worker used by both stream_commands and stream_file.

        Uses character-counting flow control to keep GRBL's RX buffer full
        without overflowing it.

        Emits:
            stream_command_sent(send_idx)  when a command is written to the port
            stream_progress(recv_idx, total) when an ok/error is received
            stream_finished(success) on exit
        """
        total      = len(gcode)
        buf_counts: list[int] = []   # byte-count of each in-flight command
        send_idx   = 0               # next command index to write
        recv_idx   = 0               # number of acknowledged commands
        success    = True

        stream_rx: queue.Queue[GrblMessage] = queue.Queue()
        self._stream_rx = stream_rx

        logger.info(f"Streaming {total} commands…")

        try:
            while recv_idx < total and not self._stop_evt.is_set():
                # Write as many commands as fit in the RX buffer
                while send_idx < total:
                    line = gcode[send_idx]
                    nb   = len(line) + 1   # +1 for the \n
                    if sum(buf_counts) + nb > self.rx_buffer_size:
                        break
                    self._write_line(line + "\n")
                    buf_counts.append(nb)
                    self.signals.stream_command_sent.emit(send_idx)
                    logger.debug(f"  → [{send_idx}] {line}")
                    send_idx += 1

                # Wait for the next acknowledgement
                try:
                    msg = stream_rx.get(timeout=15.0)
                except queue.Empty:
                    logger.error("Timeout waiting for GRBL response during streaming.")
                    success = False
                    break

                if buf_counts:
                    buf_counts.pop(0)
                recv_idx += 1

                self.signals.stream_progress.emit(recv_idx, total)

                if msg.kind in (GrblMessage.Kind.ERROR, GrblMessage.Kind.ALARM):
                    logger.error(f"Stopping stream at command {recv_idx}: {msg.text}")
                    success = False
                    break

        except Exception as exc:
            logger.exception(f"Stream error: {exc}")
            success = False
        finally:
            self._stream_rx = None
            with self._stream_lock:
                self._streaming = False
            self.signals.stream_finished.emit(success)
            logger.info(f"Stream complete — {recv_idx}/{total} commands (success={success})")

    # ------------------------------------------------------------------
    # Background threads
    # ------------------------------------------------------------------

    def _reader_loop(self) -> None:
        while not self._stop_evt.is_set():
            try:
                if self._serial and self._serial.in_waiting:
                    raw = self._serial.readline().decode("utf-8", errors="replace").strip()
                    if not raw:
                        continue
                    logger.debug(f"← {raw}")
                    msg = parse_response(raw)
                    self._dispatch(msg)
                else:
                    time.sleep(0.005)
            except serial.SerialException as e:
                logger.error(f"Reader: {e}")
                self._stop_evt.set()
            except Exception as e:
                logger.exception(f"Reader: {e}")

    def _writer_loop(self) -> None:
        while not self._stop_evt.is_set():
            try:
                cmd = self._tx_queue.get(timeout=0.1)
                if cmd == "\x00":
                    break
                self._write_line(cmd + "\n")
                logger.debug(f"→ {cmd}")
            except queue.Empty:
                continue
            except serial.SerialException as e:
                logger.error(f"Writer: {e}")
                self._stop_evt.set()

    def _poll_loop(self) -> None:
        while not self._stop_evt.is_set():
            if self.is_connected:
                self.send_realtime(self.CMD_STATUS)
            time.sleep(self.poll_interval)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _write_line(self, data: str) -> None:
        with self._lock:
            if self._serial and self._serial.is_open:
                self._serial.write(data.encode("utf-8"))
        text = data.strip()
        if text and text != "?":
            self.signals.command_sent.emit(text)

    def _dispatch(self, msg: GrblMessage) -> None:
        # If streaming, route ok/error/alarm into the stream queue
        stream_rx = getattr(self, "_stream_rx", None)
        if stream_rx and msg.kind in (
            GrblMessage.Kind.OK,
            GrblMessage.Kind.ERROR,
            GrblMessage.Kind.ALARM,
        ):
            stream_rx.put_nowait(msg)

        # Always emit the general signal
        self.signals.message_received.emit(msg)

        if msg.kind == GrblMessage.Kind.STATUS:
            # Re-parse with our current axis expectation so the status object
            # reflects the correct (possibly overridden) axis count.
            status = _parse_status(msg.text, expected_axes=self.axes)

            # Auto-detect: fire axes_detected once on first non-zero count.
            if not self._axes_detected and status.num_axes > 0:
                self.axes           = status.num_axes
                self._axes_detected = True
                logger.info(f"Auto-detected {self.axes} axes.")
                self.signals.axes_detected.emit(self.axes)

            self.status = status
            self.signals.status_updated.emit(status)
        elif msg.kind == GrblMessage.Kind.ALARM:
            self.signals.alarm_raised.emit(msg.text)
        elif msg.kind == GrblMessage.Kind.ERROR:
            self.signals.error_raised.emit(msg.text)