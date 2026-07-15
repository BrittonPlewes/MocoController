"""
webportal/server.py

Runs a small Flask-SocketIO web server, in the background, alongside a PyQt5
GUI. Serves the phone-facing jog control page and bridges its WebSocket
events to Qt signals, so the rest of the app can stay 100% PyQt-native.

Usage from your main GUI (see example_integration.py for a fuller example):

    from webportal.server import WebPortalBridge, WebPortalServer

    bridge = WebPortalBridge()
    bridge.jogRequested.connect(my_gui.on_jog)
    bridge.estopRequested.connect(my_gui.on_estop)
    bridge.groupboxRequested.connect(my_gui.on_groupbox)
    bridge.settingsChanged.connect(my_gui.on_jog_settings_changed)

    server = WebPortalServer(bridge, port=8080)
    server.start()   # non-blocking, runs in its own QThread

    # Whenever your app has fresh axis values (timer, hardware callback, etc):
    bridge.update_axes(x=1.23, y=0.0, z=-4.5, a=0.0, b=0.0)

    # On shutdown:
    server.stop()
"""

import ipaddress
import socket
import sys
from pathlib import Path
from typing import List, Optional

from PyQt5.QtCore import QObject, QThread, pyqtSignal

from flask import Flask, send_from_directory
from flask_socketio import SocketIO

STATIC_DIR = Path(__file__).parent / "static"


def _is_private_lan_ip(ip: str) -> bool:
    """
    True for typical home/office LAN ranges (192.168.x.x, 10.x.x.x,
    172.16-31.x.x). False for loopback, link-local, and anything
    globally routable — including VPN tunnel addresses, which are
    "private" in the IP-allocation sense but not usable here since your
    phone isn't on that tunnel.
    """
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    return addr.is_private and not addr.is_loopback and not addr.is_link_local


def get_local_ip() -> str:
    """
    Best-effort LAN IP for this machine, so you can print/display the URL
    to type into the phone's browser. Doesn't actually send any traffic —
    just asks the OS what interface/IP would be used to reach an external
    address, which is a standard trick for finding the "real" LAN IP
    (as opposed to 127.0.0.1) even on machines with multiple interfaces.

    Caveat: if a VPN is active, the OS's default route often points at the
    VPN's tunnel interface, so this can return the VPN's address instead of
    your actual Wi-Fi/Ethernet IP — that address won't be reachable from a
    phone on your home Wi-Fi. See list_candidate_ips() below, which is used
    to cross-check this guess when the server starts.
    """
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


def list_candidate_ips() -> List[str]:
    """
    Enumerate every IPv4 address this machine currently has, across all
    adapters (Wi-Fi, Ethernet, VPN, virtual/Docker adapters, etc.), so you
    can pick the right one by hand if get_local_ip()'s single guess picks
    the wrong interface (most commonly because a VPN is active).
    Best-effort and OS-dependent — not guaranteed to see every adapter.
    """
    ips = set()
    try:
        hostname = socket.gethostname()
        _, _, addrs = socket.gethostbyname_ex(hostname)
        ips.update(addrs)
    except OSError:
        pass
    guess = get_local_ip()
    if guess:
        ips.add(guess)
    return sorted(ips)


class WebPortalBridge(QObject):
    """
    Lives on the Qt GUI thread. All signals below are emitted from the
    Flask-SocketIO worker thread(s), but because this QObject lives on the
    main thread, Qt automatically marshals the emission across via a
    queued connection — no manual locking or invokeMethod needed on your
    end. Just connect these signals to plain slots like any other Qt signal.
    """

    # axis: 'X' | 'Y' | 'Z' | 'A' | 'B'   dir: '+' | '-'
    # amount/speed reflect whatever the phone's sliders were set to at
    # the moment the button was pressed.
    jogRequested = pyqtSignal(str, str, float, float)   # axis, dir, amount, speed
    jogRequestedDict = pyqtSignal(dict)

    # Emergency stop button on the phone.
    estopRequested = pyqtSignal()

    # action: 'Shutter' | 'Home' | 'Zero All'
    groupboxRequested = pyqtSignal(str)

    # Fired when the phone's jog-amount or jog-speed slider settles
    # (on release, not on every drag tick).
    settingsChanged = pyqtSignal(float, float)          # amount, speed

    # Fired whenever a phone connects/disconnects, in case you want to
    # show that in your GUI (e.g. a little "phone connected" badge).
    clientConnected = pyqtSignal()
    clientDisconnected = pyqtSignal()

    def __init__(self):
        super().__init__()
        self._socketio: Optional[SocketIO] = None  # set by WebPortalServer

    def update_axes(self, **axis_values: float) -> None:
        """
        Push live axis values to every connected phone.
        Call with any subset of axes, e.g.:
            bridge.update_axes(x=12.3, z=-4.5)
        Safe to call from the Qt GUI thread (the normal case) or any
        other thread — flask-socketio's emit() handles this internally.
        """
        if self._socketio is None:
            return  # server not started yet; drop silently
        self._socketio.emit("axis_update", axis_values)
    
    def update_axes_list( self, values ):
        self.update_axes(x=values[0], y=values[1], z=values[2], a=values[3], b=values[4])


class WebPortalServer(QThread):
    """
    Runs the Flask-SocketIO dev server in a background QThread so it
    never blocks the Qt event loop. Uses async_mode='threading' rather
    than eventlet/gevent — those monkey-patch Python's socket/threading
    modules at import time, which can interact badly with Qt's own
    threading. Plain threading mode avoids that entirely and is plenty
    fast for a handful of LAN-connected phones sending jog commands.
    """

    def __init__(self, bridge: WebPortalBridge, host: str = "0.0.0.0", port: int = 8080):
        super().__init__()
        self._bridge = bridge
        self._host = host
        self._port = port

        self._app = Flask(__name__, static_folder=None)
        self._socketio = SocketIO(self._app, async_mode="threading", cors_allowed_origins="*")
        bridge._socketio = self._socketio

        self._register_routes()
        self._register_events()

    # -- Flask routes --------------------------------------------------

    def _register_routes(self) -> None:
        app = self._app

        @app.route("/")
        def index():
            return send_from_directory(STATIC_DIR, "index.html")

        @app.route("/<path:filename>")
        def static_files(filename):
            return send_from_directory(STATIC_DIR, filename)

    # -- SocketIO events -------------------------------------------------

    def _register_events(self) -> None:
        socketio = self._socketio
        bridge = self._bridge

        @socketio.on("connect")
        def _on_connect():
            bridge.clientConnected.emit()

        @socketio.on("disconnect")
        def _on_disconnect():
            bridge.clientDisconnected.emit()

        @socketio.on("jog")
        def _on_jog(data):
            axis = str(data.get("axis", ""))
            direction = str(data.get("dir", ""))
            amount = float(data.get("amount", 0.0))
            speed = float(data.get("speed", 0.0))
            bridge.jogRequested.emit(axis, direction, amount, speed)

            if "-" in direction:
                amount *= -1
            
            jogData = dict()
            jogData['axis'] = "XYZABC".index(axis)
            jogData['feedrate'] = speed*60
            jogData['amount'] = amount
            jogData['abs'] = False

            bridge.jogRequestedDict.emit(jogData)


        @socketio.on("estop")
        def _on_estop(*_args):
            bridge.estopRequested.emit()

        @socketio.on("groupbox")
        def _on_groupbox(data):
            action = str(data.get("action", ""))
            bridge.groupboxRequested.emit(action)

        @socketio.on("settings")
        def _on_settings(data):
            amount = float(data.get("amount", 0.0))
            speed = float(data.get("speed", 0.0))
            bridge.settingsChanged.emit(amount, speed)

    # -- QThread lifecycle -----------------------------------------------

    def run(self) -> None:
        guess = get_local_ip()
        candidates = list_candidate_ips()

        if _is_private_lan_ip(guess):
            print(f"[webportal] serving on http://{guess}:{self._port}  "
                  f"(open this on your phone, on the same Wi-Fi)")
        else:
            print(f"[webportal] serving on port {self._port}")
            print(f"[webportal] WARNING: best-guess IP ({guess}) doesn't look like a normal "
                  f"LAN address — you likely have a VPN active and it grabbed the default route.")
            lan_candidates = [ip for ip in candidates if _is_private_lan_ip(ip)]
            if lan_candidates:
                print("[webportal] try one of these instead (usually the 192.168.x.x one):")
                for ip in lan_candidates:
                    print(f"[webportal]   http://{ip}:{self._port}")
            else:
                print("[webportal] no obvious LAN candidate found — run 'ipconfig' (Windows) "
                      "or 'ifconfig'/'ip addr' (Mac/Linux) and look for your Wi-Fi adapter's IPv4 address.")

        # allow_unsafe_werkzeug: the dev server normally refuses to run
        # outside the process's main thread; we're intentionally running it
        # in this QThread instead, which is fine for a LAN-only local tool
        # like this but should not be exposed to the open internet.
        self._socketio.run(
            self._app,
            host=self._host,
            port=self._port,
            use_reloader=False,
            allow_unsafe_werkzeug=True,
        )

    def stop(self) -> None:
        """
        Best-effort shutdown. The Werkzeug dev server used by flask-socketio
        in threading mode doesn't expose a clean stop() the way a production
        server would; since this thread is a daemon-style background worker
        tied to your app's lifetime, it's fine to just let it die with the
        process on exit. This method is here as a placeholder if you swap in
        a production-grade server (e.g. waitress) later.
        """
        self.terminate()
        self.wait()
