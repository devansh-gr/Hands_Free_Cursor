"""Local web control panel server — dependency-free (stdlib only).

The browser cannot read AirPods motion or move the macOS cursor, so the
website is a *front-end* to this local engine: it serves the control-panel
page, streams live telemetry over Server-Sent Events, and accepts commands
over plain POST. The engine main loop drains commands and publishes telemetry;
this server just shuttles them to/from the browser.
"""

import json
import os
import queue
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

WEB_DIR = os.path.join(os.path.dirname(__file__), "..", "web")


class Control:
    """Thread-safe bridge between the HTTP server threads and the engine loop."""

    def __init__(self) -> None:
        self._cmds: "queue.Queue[dict]" = queue.Queue()
        self._lock = threading.Lock()
        self._telemetry: dict = {"streaming": False}

    def push_cmd(self, action: str, value=None) -> None:
        self._cmds.put({"action": action, "value": value})

    def drain(self) -> list[dict]:
        out = []
        while True:
            try:
                out.append(self._cmds.get_nowait())
            except queue.Empty:
                return out

    def set_telemetry(self, d: dict) -> None:
        with self._lock:
            self._telemetry = d

    def get_telemetry(self) -> dict:
        with self._lock:
            return dict(self._telemetry)


def _make_handler(control: Control):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *a):  # silence default request logging
            pass

        def do_GET(self):
            if self.path in ("/", "/index.html"):
                self._serve_file("index.html", "text/html; charset=utf-8")
            elif self.path == "/events":
                self._sse()
            else:
                self.send_error(404)

        def do_POST(self):
            if self.path != "/cmd":
                self.send_error(404)
                return
            length = int(self.headers.get("Content-Length", 0))
            raw = self.rfile.read(length) if length else b"{}"
            try:
                msg = json.loads(raw)
                control.push_cmd(msg.get("action"), msg.get("value"))
                self._json({"ok": True})
            except Exception as e:
                self._json({"ok": False, "error": str(e)}, 400)

        def _serve_file(self, name, ctype):
            try:
                with open(os.path.join(WEB_DIR, name), "rb") as f:
                    data = f.read()
            except OSError:
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _json(self, obj, code=200):
            data = json.dumps(obj).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _sse(self):
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "keep-alive")
            self.end_headers()
            try:
                while True:
                    payload = json.dumps(control.get_telemetry()).encode()
                    self.wfile.write(b"data: " + payload + b"\n\n")
                    self.wfile.flush()
                    time.sleep(0.1)
            except (BrokenPipeError, ConnectionResetError, OSError):
                return  # browser closed the stream

    return Handler


class _QuietServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def handle_error(self, request, client_address):
        # Browsers freely drop SSE/keep-alive sockets; those resets are normal.
        exc = sys.exception()
        if isinstance(exc, (ConnectionResetError, BrokenPipeError, ConnectionAbortedError)):
            return
        super().handle_error(request, client_address)


class ControlServer(threading.Thread):
    def __init__(self, control: Control, host="127.0.0.1", port=8765) -> None:
        super().__init__(daemon=True)
        self.control = control
        self.host = host
        self.port = port
        self.url = f"http://{host}:{port}/"
        self._httpd = None

    def run(self) -> None:
        self._httpd = _QuietServer((self.host, self.port), _make_handler(self.control))
        self._httpd.serve_forever()

    def stop(self) -> None:
        if self._httpd is not None:
            self._httpd.shutdown()
