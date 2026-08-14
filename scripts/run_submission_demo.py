#!/usr/bin/env python3
"""Drive the frozen DecisionVault <3 minute judge demo in the real Chrome UI.

The auth token is injected into the password field through CDP so it never has
to be typed or printed. The two proof actions themselves are real X11 mouse
clicks on the live page. CDP is otherwise used for read-only gates and scrolling.

Expected sequence:

    bash scripts/start_submission_browser.sh
    # start Ubuntu / OBS screen recording
    python3 scripts/run_submission_demo.py
"""

from __future__ import annotations

import base64
import ctypes
import ctypes.util
import hashlib
import json
import os
from pathlib import Path
import secrets
import socket
import struct
import sys
import time
import urllib.parse
import urllib.request
from typing import Any


CDP_PORT = int(os.environ.get("DECISIONVAULT_DEMO_CDP_PORT", "9257"))
APP_URL = os.environ.get(
    "DECISIONVAULT_DEMO_URL",
    "https://mfcr7b2k3j7lrwr44u35i5rchq0fbncb.lambda-url.ap-northeast-1.on.aws/",
)
DISPLAY = os.environ.get("DECISIONVAULT_DEMO_DISPLAY") or os.environ.get("DISPLAY") or ":1"
TOKEN_FILE = Path(os.environ.get("DECISIONVAULT_DEMO_TOKEN_FILE", ".venv/demo-token"))
TIMING_SCALE = float(os.environ.get("DECISIONVAULT_DEMO_TIMING_SCALE", "1"))
if TIMING_SCALE <= 0:
    raise SystemExit("DECISIONVAULT_DEMO_TIMING_SCALE must be > 0")
TARGET_AUTOMATION_SECONDS = 160.0 * TIMING_SCALE
MAX_AUTOMATION_SECONDS = 176.0 if TIMING_SCALE >= 1 else 90.0


class DemoFailure(RuntimeError):
    """A submission recording gate failed."""


def _read_json_url(url: str, timeout: float = 4.0) -> Any:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            return json.load(response)
    except Exception as exc:  # pragma: no cover - operational guard
        raise DemoFailure(f"cannot read {url}: {exc}") from exc


class _WebSocket:
    """Tiny RFC6455 client sufficient for local Chrome DevTools Protocol."""

    def __init__(self, url: str) -> None:
        parsed = urllib.parse.urlsplit(url)
        if parsed.scheme != "ws" or not parsed.hostname:
            raise DemoFailure(f"unsupported CDP websocket URL: {url}")
        host = parsed.hostname
        port = parsed.port or 80
        path = parsed.path or "/"
        if parsed.query:
            path += "?" + parsed.query
        self.sock = socket.create_connection((host, port), timeout=4.0)
        key = base64.b64encode(secrets.token_bytes(16)).decode("ascii")
        request = (
            f"GET {path} HTTP/1.1\r\n"
            f"Host: {host}:{port}\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            "Sec-WebSocket-Version: 13\r\n\r\n"
        )
        self.sock.sendall(request.encode("ascii"))
        headers = self._recv_until(b"\r\n\r\n")
        first_line = headers.split(b"\r\n", 1)[0]
        if b" 101 " not in first_line:
            raise DemoFailure(f"CDP websocket handshake failed: {first_line!r}")
        accept = base64.b64encode(
            hashlib.sha1(
                (key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode("ascii")
            ).digest()
        ).decode("ascii")
        if f"sec-websocket-accept: {accept}".lower().encode() not in headers.lower():
            raise DemoFailure("CDP websocket handshake returned an invalid accept key")

    def close(self) -> None:
        try:
            self.sock.close()
        except OSError:
            pass

    def _recv_until(self, marker: bytes) -> bytes:
        data = bytearray()
        while marker not in data:
            chunk = self.sock.recv(4096)
            if not chunk:
                raise DemoFailure("CDP websocket closed during handshake")
            data.extend(chunk)
        return bytes(data)

    @staticmethod
    def _mask(payload: bytes, key: bytes) -> bytes:
        return bytes(value ^ key[index % 4] for index, value in enumerate(payload))

    def send_text(self, text: str) -> None:
        payload = text.encode("utf-8")
        mask_key = secrets.token_bytes(4)
        length = len(payload)
        if length < 126:
            header = bytes((0x81, 0x80 | length))
        elif length <= 0xFFFF:
            header = bytes((0x81, 0x80 | 126)) + struct.pack("!H", length)
        else:
            header = bytes((0x81, 0x80 | 127)) + struct.pack("!Q", length)
        self.sock.sendall(header + mask_key + self._mask(payload, mask_key))

    def _recv_exact(self, count: int) -> bytes:
        data = bytearray()
        while len(data) < count:
            chunk = self.sock.recv(count - len(data))
            if not chunk:
                raise DemoFailure("CDP websocket closed")
            data.extend(chunk)
        return bytes(data)

    def recv_text(self, timeout: float) -> str:
        self.sock.settimeout(timeout)
        fragments = bytearray()
        while True:
            first, second = self._recv_exact(2)
            fin = bool(first & 0x80)
            opcode = first & 0x0F
            masked = bool(second & 0x80)
            length = second & 0x7F
            if length == 126:
                length = struct.unpack("!H", self._recv_exact(2))[0]
            elif length == 127:
                length = struct.unpack("!Q", self._recv_exact(8))[0]
            mask_key = self._recv_exact(4) if masked else b""
            payload = self._recv_exact(length)
            if masked:
                payload = self._mask(payload, mask_key)
            if opcode == 0x8:
                raise DemoFailure("CDP websocket closed by Chrome")
            if opcode == 0x9:
                self._send_control(0xA, payload)
                continue
            if opcode in (0x1, 0x0):
                fragments.extend(payload)
                if fin:
                    return fragments.decode("utf-8")

    def _send_control(self, opcode: int, payload: bytes) -> None:
        mask_key = secrets.token_bytes(4)
        self.sock.sendall(
            bytes((0x80 | opcode, 0x80 | len(payload)))
            + mask_key
            + self._mask(payload, mask_key)
        )


class CDPClient:
    def __init__(self, port: int, app_url: str) -> None:
        targets = _read_json_url(f"http://127.0.0.1:{port}/json")
        if not isinstance(targets, list):
            raise DemoFailure("CDP target list is invalid")
        prefix = app_url.rstrip("/")
        pages = [target for target in targets if target.get("type") == "page"]
        target = next(
            (page for page in pages if str(page.get("url", "")).startswith(prefix)),
            pages[0] if pages else None,
        )
        if not target or not target.get("webSocketDebuggerUrl"):
            raise DemoFailure("DecisionVault page target is unavailable")
        self.socket = _WebSocket(str(target["webSocketDebuggerUrl"]))
        self.next_id = 0

    def close(self) -> None:
        self.socket.close()

    def command(
        self, method: str, params: dict[str, Any] | None = None, *, timeout: float = 8.0
    ) -> dict[str, Any]:
        self.next_id += 1
        request_id = self.next_id
        self.socket.send_text(
            json.dumps({"id": request_id, "method": method, "params": params or {}})
        )
        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise DemoFailure(f"CDP command timed out: {method}")
            try:
                message = json.loads(self.socket.recv_text(remaining))
            except socket.timeout as exc:
                raise DemoFailure(f"CDP command timed out: {method}") from exc
            if message.get("id") != request_id:
                continue
            if "error" in message:
                raise DemoFailure(f"CDP {method} failed: {message['error']}")
            return message.get("result", {})

    def evaluate(self, expression: str, *, timeout: float = 8.0) -> Any:
        result = self.command(
            "Runtime.evaluate",
            {"expression": expression, "returnByValue": True, "awaitPromise": True},
            timeout=timeout,
        )
        if result.get("exceptionDetails"):
            raise DemoFailure("a browser gate raised a JavaScript exception")
        return result.get("result", {}).get("value")


class X11Mouse:
    def __init__(self, display_name: str) -> None:
        x11_name = ctypes.util.find_library("X11")
        xtst_name = ctypes.util.find_library("Xtst")
        if not x11_name or not xtst_name:
            raise DemoFailure("libX11/libXtst is required for real browser clicks")
        self.x11 = ctypes.CDLL(x11_name)
        self.xtst = ctypes.CDLL(xtst_name)
        self.x11.XOpenDisplay.argtypes = [ctypes.c_char_p]
        self.x11.XOpenDisplay.restype = ctypes.c_void_p
        self.x11.XFlush.argtypes = [ctypes.c_void_p]
        self.xtst.XTestFakeMotionEvent.argtypes = [
            ctypes.c_void_p,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_ulong,
        ]
        self.xtst.XTestFakeButtonEvent.argtypes = [
            ctypes.c_void_p,
            ctypes.c_uint,
            ctypes.c_int,
            ctypes.c_ulong,
        ]
        self.display = self.x11.XOpenDisplay(display_name.encode())
        if not self.display:
            raise DemoFailure(f"cannot open X11 display {display_name}")

    def click(self, x: int, y: int) -> None:
        self.xtst.XTestFakeMotionEvent(self.display, -1, x, y, 0)
        self.xtst.XTestFakeButtonEvent(self.display, 1, 1, 0)
        self.xtst.XTestFakeButtonEvent(self.display, 1, 0, 0)
        self.x11.XFlush(self.display)


def _token() -> str:
    value = os.environ.get("DECISIONVAULT_DEMO_TOKEN", "").strip()
    if value:
        return value
    try:
        value = TOKEN_FILE.read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise DemoFailure(
            f"demo token not found; expected {TOKEN_FILE} or DECISIONVAULT_DEMO_TOKEN"
        ) from exc
    if not value:
        raise DemoFailure("demo token file is empty")
    return value


def _wait_for(cdp: CDPClient, expression: str, *, timeout: float, label: str) -> Any:
    deadline = time.monotonic() + timeout
    last: Any = None
    while time.monotonic() < deadline:
        last = cdp.evaluate(expression)
        if last:
            return last
        time.sleep(0.25)
    raise DemoFailure(f"timed out waiting for {label}; last={last!r}")


def _center(cdp: CDPClient, element_id: str) -> tuple[int, int]:
    rect = cdp.evaluate(
        "(() => {const e=document.getElementById(%s);"
        "if(!e)return null;const r=e.getBoundingClientRect();"
        "const ox=screenX+Math.max(0,(outerWidth-innerWidth)/2);"
        "const oy=screenY+Math.max(0,outerHeight-innerHeight);"
        "return {x:r.left+r.width/2+ox,y:r.top+r.height/2+oy,w:r.width,h:r.height};})()"
        % json.dumps(element_id)
    )
    if not rect or rect["w"] < 2 or rect["h"] < 2:
        raise DemoFailure(f"element #{element_id} is not clickable")
    return round(rect["x"]), round(rect["y"])


def _scroll_to(cdp: CDPClient, element_id: str) -> None:
    ok = cdp.evaluate(
        "(() => {const e=document.getElementById(%s);if(!e)return false;"
        "e.scrollIntoView({behavior:'smooth',block:'center'});return true;})()"
        % json.dumps(element_id)
    )
    if not ok:
        raise DemoFailure(f"cannot scroll to #{element_id}")
    time.sleep(1.0)


def _pause_until(started: float, seconds: float) -> None:
    remaining = (seconds * TIMING_SCALE) - (time.monotonic() - started)
    if remaining > 0:
        time.sleep(remaining)


def main() -> int:
    started = time.monotonic()
    cdp = CDPClient(CDP_PORT, APP_URL)
    try:
        mouse = X11Mouse(DISPLAY)
        viewport = cdp.evaluate(
            "({innerWidth,innerHeight,outerWidth,outerHeight,screenX,screenY,"
            "dpr:devicePixelRatio,screenWidth:screen.width,screenHeight:screen.height})"
        )
        if not viewport or viewport["screenWidth"] != 1920 or viewport["screenHeight"] != 1080:
            raise DemoFailure(f"expected a 1920x1080 recording screen, got {viewport!r}")
        if viewport["innerWidth"] < 1900 or viewport["innerHeight"] < 950:
            raise DemoFailure(f"browser content area is too small for the frozen demo: {viewport!r}")
        if viewport["screenX"] != 0 or viewport["screenY"] != 0 or viewport["dpr"] != 1:
            raise DemoFailure(f"unexpected kiosk geometry/DPR: {viewport!r}")
        health = _wait_for(
            cdp,
            "document.getElementById('healthText')?.textContent.includes('Live on AWS Lambda')===true",
            timeout=12,
            label="live AWS health banner",
        )
        if not health:
            raise DemoFailure("live health banner did not become ready")

        print("PASS gate: 1920x1080 live AWS page ready")
        _pause_until(started, 38.0)

        token = _token()
        cdp.evaluate(
            "(() => {const e=document.getElementById('token');e.value=%s;"
            "e.dispatchEvent(new Event('input',{bubbles:true}));return e.value.length;})()"
            % json.dumps(token)
        )
        del token
        _scroll_to(cdp, "run")
        mouse.click(*_center(cdp, "run"))
        _wait_for(
            cdp,
            "document.getElementById('status').textContent==='Live cross-agent proof completed.'",
            timeout=35,
            label="cross-agent proof",
        )
        live_pass = cdp.evaluate(
            "document.getElementById('delta').textContent.startsWith('PASS')"
            " && document.getElementById('offStrategy').textContent==='GENERIC_RETRY'"
            " && document.getElementById('onStrategy').textContent==='REFRESH_PAYMENT_TOKEN'"
        )
        if not live_pass:
            raise DemoFailure("cross-agent proof completed without the expected PASS state")
        _scroll_to(cdp, "delta")
        print("PASS gate: Memory OFF/ON causal strategy change visible")
        _pause_until(started, 88.0)

        _scroll_to(cdp, "govern")
        mouse.click(*_center(cdp, "govern"))
        _wait_for(
            cdp,
            "document.getElementById('status').textContent==='Live conflict safety proof completed.'",
            timeout=35,
            label="conflict safety proof",
        )
        conflict_pass = cdp.evaluate(
            "document.getElementById('governanceDelta').textContent.startsWith('PASS')"
            " && document.getElementById('governanceDelta').textContent.includes('CONFLICT_ABSTAIN')"
        )
        if not conflict_pass:
            raise DemoFailure("conflict proof completed without CONFLICT_ABSTAIN PASS")
        _scroll_to(cdp, "governanceDelta")
        print("PASS gate: contradictory shared memory abstention visible")
        _pause_until(started, 116.0)

        _scroll_to(cdp, "submissionEvidence")
        evidence_pass = cdp.evaluate(
            "document.getElementById('submissionEvidence').textContent.includes('14/14')"
            " && document.getElementById('submissionEvidence').textContent.includes('VECTOR(1024)')"
            " && document.getElementById('submissionEvidence').textContent.includes('Managed MCP')"
        )
        if not evidence_pass:
            raise DemoFailure("submission evidence panel is incomplete")
        print("PASS gate: DVI / MCP / benchmark evidence visible")
        _pause_until(started, 148.0)

        cdp.evaluate("window.scrollTo({top:0,behavior:'smooth'});true")
        time.sleep(1.0)
        _pause_until(started, 160.0)
        elapsed = time.monotonic() - started
        if elapsed > MAX_AUTOMATION_SECONDS:
            raise DemoFailure(f"automation exceeded recording ceiling: {elapsed:.1f}s")
        print(f"PASS: submission automation complete in {elapsed:.1f}s")
        return 0
    finally:
        cdp.close()


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except DemoFailure as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        raise SystemExit(2)
