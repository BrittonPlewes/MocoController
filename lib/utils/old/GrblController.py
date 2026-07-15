import serial
import time
import re
from PyQt5.QtCore import QObject, pyqtSignal, pyqtSlot

class GrblController(QObject):
    # Signals
    line_received = pyqtSignal(str)        # Raw serial output
    status_parsed = pyqtSignal(dict)      # Processed status (pos, state, etc)
    progress_updated = pyqtSignal(int)
    job_completed = pyqtSignal()
    connection_status = pyqtSignal(bool)

    def __init__(self, port, baud=115200, buffer_size=127, poll_interval=0.2):
        super().__init__()
        self.port = port
        self.baud = baud
        self.buffer_size = buffer_size
        self.poll_interval = poll_interval # Seconds between '?' commands
        
        self.serial_conn = None
        self.is_streaming = False
        self.is_paused = False
        self.running = True

        self.tx_buffer = []
        self.gcode_queue = []
        self.total_lines = 0
        self.lines_sent = 0
        
        self.last_poll_time = 0

    @pyqtSlot()
    def run_listener(self):
        try:
            self.serial_conn = serial.Serial(self.port, self.baud, timeout=0.01)
            self.connection_status.emit(True)
            self.serial_conn.write(b"\r\n\r\n")
            
            while self.running:
                current_time = time.time()

                # 1. POLL: Send '?' at intervals
                if current_time - self.last_poll_time > self.poll_interval:
                    if self.serial_conn.is_open:
                        self.serial_conn.write(b'?')
                        self.last_poll_time = current_time

                # 2. READ: Handle incoming data
                if self.serial_conn.in_waiting:
                    line = self.serial_conn.readline().decode('utf-8', errors='replace').strip()
                    if line:
                        if line.startswith('<'):
                            self._parse_status(line)
                        else:
                            self.line_received.emit(line)
                            self._handle_response(line)

                # 3. WRITE: Stream G-code
                if self.is_streaming and not self.is_paused:
                    self._stream_next_batch()
                
                time.sleep(0.001)

        except Exception as e:
            self.line_received.emit(f"SERIAL ERROR: {e}")
        finally:
            if self.serial_conn: self.serial_conn.close()
            self.connection_status.emit(False)

    def _parse_status(self, line):
        """
        Parses GRBL status strings: <Idle|WPos:0.000,0.000,0.000|Bf:15,127|FS:0,0>
        """
        try:
            # Clean brackets
            clean = line.strip('<> ')
            parts = clean.split('|')
            status_dict = {'state': parts[0]}

            for part in parts[1:]:
                if part.startswith('WPos:') or part.startswith('MPos:'):
                    label, coords = part.split(':')
                    x, y, z = coords.split(',')
                    status_dict[label] = (float(x), float(y), float(z))
                elif part.startswith('Bf:'):
                    # Buffers: planner_blocks, rx_bytes
                    label, vals = part.split(':')
                    p, r = vals.split(',')
                    status_dict['planner_buffer'] = int(p)
                    status_dict['rx_buffer_free'] = int(r)
                elif part.startswith('FS:'):
                    # Feed/Speed
                    label, vals = part.split(':')
                    f, s = vals.split(',')
                    status_dict['feed'] = int(f)
                    status_dict['speed'] = int(s)

            self.status_parsed.emit(status_dict)
        except Exception as e:
            # If parsing fails due to custom grblHAL strings, just emit raw
            self.line_received.emit(f"Parse Error: {line}")

    def _handle_response(self, line):
        if 'ok' in line or 'error' in line:
            if self.tx_buffer:
                self.tx_buffer.pop(0)
            if self.is_streaming and not self.tx_buffer and not self.gcode_queue:
                self.is_streaming = False
                self.job_completed.emit()

    def _stream_next_batch(self):
        while self.gcode_queue:
            next_line = self.gcode_queue[0]
            l_len = len(next_line) + 1
            if sum(self.tx_buffer) + l_len < self.buffer_size:
                cmd = self.gcode_queue.pop(0)
                self.serial_conn.write((cmd + '\n').encode())
                self.tx_buffer.append(l_len)
                self.lines_sent += 1
                prog = int((self.lines_sent / self.total_lines) * 100)
                self.progress_updated.emit(prog)
            else:
                break

    @pyqtSlot(str)
    def send_command(self, cmd):
        if self.serial_conn and self.serial_conn.is_open:
            # High priority commands like ! (pause) or ~ (resume) or ^X (reset)
            self.serial_conn.write(cmd.encode() if len(cmd) == 1 else (cmd + '\n').encode())

    @pyqtSlot(str)
    def start_stream(self, filepath):
        try:
            with open(filepath, 'r') as f:
                self.gcode_queue = [l.strip() for l in f if l.strip() and not l.strip().startswith('(')]
            self.total_lines = len(self.gcode_queue)
            self.lines_sent = 0
            self.is_streaming = True
        except Exception as e:
            self.line_received.emit(f"FILE ERROR: {e}")

    @pyqtSlot()
    def toggle_pause(self):
        """Toggles the pause state and sends immediate feed hold/resume commands."""
        self.is_paused = not self.is_paused
        
        if self.serial_conn and self.serial_conn.is_open:
            if self.is_paused:
                # '!' is the GRBL realtime command for Feed Hold
                self.serial_conn.write(b'!')
            else:
                # '~' is the GRBL realtime command for Cycle Start/Resume
                self.serial_conn.write(b'~')           


    @pyqtSlot()
    def stop(self):
        """Stops the stream and sends a soft reset to the controller."""
        # 1. Stop the Python loop from sending more lines
        self.is_streaming = False
        self.gcode_queue = []
        self.tx_buffer = []
        
        # 2. Send the GRBL Real-time Soft Reset command (Ctrl-X)
        if self.serial_conn and self.serial_conn.is_open:
            self.serial_conn.write(b'\x18') 
            self.line_received.emit("!!! EMERGENCY STOP SENT !!!")                 