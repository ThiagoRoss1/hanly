"""Evaluate one expression in a Qt WebEngine page through its local DevTools port.

Standard library only, so a packaged check needs no WebSocket dependency: one
handshake, one masked text frame out, frames read until the matching reply.
Qt WebEngine opens the port only when ``QTWEBENGINE_REMOTE_DEBUGGING`` names it.
"""

from __future__ import annotations

import base64
import json
import os
import socket
import struct
import urllib.request
from typing import Any
from urllib.parse import urlparse


def page_targets(port: int) -> list[dict[str, Any]]:
    """The pages the DevTools endpoint lists; empty while it is not up yet."""

    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/json", timeout=2) as response:
            listing = json.loads(response.read())
    except (OSError, ValueError):
        return []
    return [item for item in listing if item.get("type") == "page"]


def evaluate(port: int, expression: str, *, timeout: float = 10.0) -> Any:
    """Run ``expression`` in the first page and return its JSON value."""

    targets = page_targets(port)
    if not targets:
        raise ConnectionError("no DevTools page is listening")
    url = urlparse(targets[0]["webSocketDebuggerUrl"])
    with socket.create_connection((url.hostname, url.port), timeout=timeout) as connection:
        _handshake(connection, url.hostname or "127.0.0.1", url.port or port, url.path)
        request = {
            "id": 1,
            "method": "Runtime.evaluate",
            "params": {"expression": expression, "returnByValue": True, "awaitPromise": True},
        }
        _send(connection, json.dumps(request).encode("utf-8"))
        while True:
            reply = json.loads(_receive(connection))
            if reply.get("id") == 1:
                return reply.get("result", {}).get("result", {}).get("value")


def _handshake(connection: socket.socket, host: str, port: int, path: str) -> None:
    key = base64.b64encode(os.urandom(16)).decode("ascii")
    connection.sendall(
        (
            f"GET {path} HTTP/1.1\r\nHost: {host}:{port}\r\nUpgrade: websocket\r\n"
            f"Connection: Upgrade\r\nSec-WebSocket-Key: {key}\r\n"
            "Sec-WebSocket-Version: 13\r\n\r\n"
        ).encode("ascii")
    )
    response = b""
    while b"\r\n\r\n" not in response:
        chunk = connection.recv(4096)
        if not chunk:
            raise ConnectionError("the DevTools endpoint closed during the handshake")
        response += chunk
    if not response.startswith(b"HTTP/1.1 101"):
        raise ConnectionError("the DevTools endpoint refused the WebSocket upgrade")


def _send(connection: socket.socket, payload: bytes) -> None:
    mask = os.urandom(4)
    header = bytearray([0x81])
    length = len(payload)
    if length < 126:
        header.append(0x80 | length)
    elif length < 1 << 16:
        header += bytes([0x80 | 126]) + struct.pack(">H", length)
    else:
        header += bytes([0x80 | 127]) + struct.pack(">Q", length)
    masked = bytes(byte ^ mask[index % 4] for index, byte in enumerate(payload))
    connection.sendall(bytes(header) + mask + masked)


def _receive(connection: socket.socket) -> bytes:
    """One whole text message; DevTools sends no fragments for these replies."""

    first, second = _exactly(connection, 2)
    length = second & 0x7F
    if length == 126:
        length = struct.unpack(">H", _exactly(connection, 2))[0]
    elif length == 127:
        length = struct.unpack(">Q", _exactly(connection, 8))[0]
    payload = _exactly(connection, length)
    if first & 0x0F == 0x8:
        raise ConnectionError("the DevTools endpoint closed the connection")
    return payload


def _exactly(connection: socket.socket, size: int) -> bytes:
    data = b""
    while len(data) < size:
        chunk = connection.recv(size - len(data))
        if not chunk:
            raise ConnectionError("the DevTools endpoint closed the connection")
        data += chunk
    return data


__all__ = ["evaluate", "page_targets"]
