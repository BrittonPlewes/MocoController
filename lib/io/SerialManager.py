import threading
import time
import queue
import serial
import serial.tools.list_ports


from PyQt5 import QtCore

# ----------------------------------------------------------------------------
# Helper: serial manager (background thread reading, write from any thread)
# ----------------------------------------------------------------------------

class SerialManager:
    """Manages the serial port in a background thread, and provides a send-and-wait method.

    The manager calls a provided callback whenever a line is received from the device.
    It also sets an internal Event whenever an acknowledgment-like token is seen.
    """
    def __init__(self, on_line_callback=None):
        self.s = None  # serial.Serial instance
        self._thread = None
        self._stop = threading.Event()
        self.on_line = on_line_callback
        self._lock = threading.Lock()
        self._ack_event = threading.Event()
        self._last_response = None

    def open(self, port, baud=115200, timeout=0.1):
        #with self._lock:
        if self.s and self.s.is_open:
            raise RuntimeError('already open')
        self.s = serial.Serial(     port, 
                                    baudrate=baud, 
                                    timeout=timeout, 
                                    rtscts=True,
                                    write_timeout=0.1)
        #self.s.write(str.encode('\r\n\r\n'))            
        #time.sleep(0.5)            
        #self.s.flushInput()
        self._stop.clear()
        self._thread = threading.Thread(target=self._read_loop, daemon=True)
        self._thread.start()

    


    def close(self):
        with self._lock:
            self._stop.set()
            if self._thread:
                self._thread.join(timeout=0.5)
                self._thread = None
            if self.s:
                try:
                    self.s.close()
                except Exception:
                    pass
                self.s = None

    def is_open(self):
        with self._lock:
            return self.s is not None and self.s.is_open

    def _read_loop(self):
        while not self._stop.is_set():
            try:
                if not self.s or not self.s.is_open:
                    break

                with self._lock:
                    raw = self.s.readline()

                if not raw:
                    continue
                try:
                    line = raw.decode(errors='ignore').rstrip('\r\n')
                except Exception:
                    line = repr(raw)
                # check for ack tokens
                low = line.lower()
                if 'ok' in low or 'error' in low or 'alarm' in low or 'grblhal' in low:
                    # set ack event and stash response
                    self._last_response = line
                    self._ack_event.set()
                # callback to GUI
                if self.on_line:
                    try:
                        self.on_line(line)
                    except Exception:
                        pass
            except serial.SerialException as e:
                if self.on_line:
                    self.on_line(f"<serial error> {e}")
                break
            except Exception:
                # swallow and continue
                continue

    def read_line( self ):
        return self.s.readline()

    def send_line(self, line: str, add_newline=True):
        """Send a single line to the serial device. Non-blocking.
        """
        with self._lock:
            if not self.s or not self.s.is_open:
                raise RuntimeError('serial port not open')
            #print( line.encode('ascii') )
            #to_send = (line + ('\n' if add_newline else '')).encode(encoding="ascii", errors="ignore")
            to_send = (line + ('\r\n' if add_newline else '')).encode('utf-8')
            self.s.write(to_send)
            self.s.flush()

    def send_and_wait_ack(self, line: str, timeout=5.0):
        """Write a line and block until an ack-like token is seen or timeout.

        Returns tuple: (ok_boolean, response_text_or_None)
        """
        self._ack_event.clear()        
        try:
            self.send_line(line, add_newline=True)
        except Exception as e:
            return False, f"<send error> {e}"
        waited = self._ack_event.wait(timeout)
        return bool(waited), self._last_response

    def write_raw(self, data: bytes):
        with self._lock:
            self.s.write(data)
            self.s.flush()



class SerialSignalEmitter(QtCore.QObject):
    line_received = QtCore.pyqtSignal(str)
    pgmCmd_sent =   QtCore.pyqtSignal(int)