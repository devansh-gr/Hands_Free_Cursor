"""UDP receiver for the Swift bridge's quaternion stream."""

import json
import socket


class IMUReceiver:
    def __init__(self, host: str, port: int) -> None:
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind((host, port))
        self.sock.setblocking(False)

    def fileno(self) -> int:
        return self.sock.fileno()

    def latest(self) -> dict | None:
        """Drain the socket and return only the newest sample.

        Draining is load-bearing for latency: if the render loop ever stalls,
        processing a backlog of stale packets would replay old head positions.
        """
        newest = None
        while True:
            try:
                data, _ = self.sock.recvfrom(256)
            except BlockingIOError:
                return newest
            try:
                newest = json.loads(data)
            except json.JSONDecodeError:
                continue  # truncated packet; UDP permits this, just skip
