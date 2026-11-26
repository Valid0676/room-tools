#!/usr/bin/env python3
"""
Room tools bridge for a Behringer X32 / X32 Compact.

Serves room-tuning.html and feedback-finder.html at http://localhost:8032 and
relays OSC messages from those pages to the mixer over UDP port 10023.
Browsers can't send UDP, so this relay is what lets the page read and write
the desk's EQ. Uses only the Python standard library.

Run:   python x32_bridge.py   (or RoomTools.exe)   then open http://localhost:8032
Flags: --port 8032   --no-browser
"""
import argparse
import functools
import json
import os
import socket
import struct
import sys
import threading
import time
import webbrowser
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

VERSION = "dev"  # replaced with the build number by the GitHub build
# Inside a PyInstaller exe the pages are unpacked to sys._MEIPASS.
HERE = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
# Only the parts of the desk these pages need.
ALLOWED = ("/info", "/xinfo", "/status", "/main/st/eq", "/main/st/insert", "/fx/")


# ---------------------------------------------------------------- OSC codec
def _pad(b: bytes) -> bytes:
    return b + b"\0" * (4 - len(b) % 4)


def osc_encode(address, args):
    tags, data = ",", b""
    for t, v in args:
        if t == "i":
            tags += "i"; data += struct.pack(">i", int(v))
        elif t == "f":
            tags += "f"; data += struct.pack(">f", float(v))
        elif t == "s":
            tags += "s"; data += _pad(str(v).encode())
        else:
            raise ValueError("unsupported OSC type " + str(t))
    return _pad(address.encode()) + _pad(tags.encode()) + data


def _read_str(buf, i):
    end = buf.index(b"\0", i)
    return buf[i:end].decode(errors="replace"), (end + 4) & ~3


def osc_decode(buf):
    addr, i = _read_str(buf, 0)
    if i >= len(buf):
        return addr, []
    tags, i = _read_str(buf, i)
    out = []
    for t in tags[1:]:
        if t == "i":
            out.append(struct.unpack(">i", buf[i:i + 4])[0]); i += 4
        elif t == "f":
            out.append(struct.unpack(">f", buf[i:i + 4])[0]); i += 4
        elif t == "s":
            s, i = _read_str(buf, i); out.append(s)
        elif t == "b":
            n = struct.unpack(">i", buf[i:i + 4])[0]; i += 4
            out.append(buf[i:i + n].hex()); i = (i + n + 3) & ~3
        else:
            break
    return addr, out


# ---------------------------------------------------------------- UDP relay
class Relay:
    def __init__(self):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind(("0.0.0.0", 0))
        self.lock = threading.Lock()

    def _drain(self):
        self.sock.setblocking(False)
        try:
            while True:
                self.sock.recv(65535)
        except OSError:
            pass
        finally:
            self.sock.setblocking(True)

    def _wait(self, addr, timeout):
        deadline = time.monotonic() + timeout
        while True:
            left = deadline - time.monotonic()
            if left <= 0:
                return {"address": addr, "error": "no reply from the mixer"}
            self.sock.settimeout(left)
            try:
                data, _ = self.sock.recvfrom(65535)
            except socket.timeout:
                return {"address": addr, "error": "no reply from the mixer"}
            except OSError as e:
                return {"address": addr, "error": "mixer not reachable (%s)" % e}
            try:
                a, args = osc_decode(data)
            except Exception:
                continue
            if a == addr:
                return {"address": a, "args": args}

    def exchange(self, host, port, messages, timeout):
        results = []
        with self.lock:
            self._drain()
            for m in messages:
                addr = str(m.get("address", ""))
                if results and results[-1].get("error", "").startswith(("no reply", "mixer not reachable", "skipped")):
                    # the desk stopped answering: fail fast instead of waiting out every message
                    results.append({"address": addr, "error": "skipped: an earlier message got no reply"})
                    continue
                if not addr.startswith(ALLOWED):
                    results.append({"address": addr, "error": "address not allowed by bridge"})
                    continue
                try:
                    pkt = osc_encode(addr, m.get("args", []))
                    self.sock.sendto(pkt, (host, port))
                except (OSError, ValueError) as e:
                    results.append({"address": addr, "error": str(e)})
                    continue
                if m.get("reply"):
                    results.append(self._wait(addr, timeout))
                else:
                    results.append({"address": addr, "ok": True})
                    time.sleep(0.003)  # gentle pacing for the desk
        return results


RELAY = Relay()


# ---------------------------------------------------------------- HTTP
class Handler(SimpleHTTPRequestHandler):
    def end_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Private-Network", "true")
        self.end_headers()

    def _json(self, code, obj):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            self.send_response(302)
            self.send_header("Location", "/room-tuning.html")
            self.end_headers()
            return
        if self.path == "/api/ping":
            return self._json(200, {"ok": True, "bridge": VERSION})
        return super().do_GET()

    def do_POST(self):
        if self.path != "/api/osc":
            return self._json(404, {"error": "not found"})
        try:
            n = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(n) or b"{}")
            host = str(body.get("host", "")).strip()
            if not host:
                return self._json(400, {"error": "missing mixer IP address"})
            port = int(body.get("port", 10023))
            timeout = min(3.0, max(0.05, float(body.get("timeout", 0.5))))
            results = RELAY.exchange(host, port, body.get("messages", []), timeout)
            return self._json(200, {"results": results})
        except Exception as e:  # report, don't crash the server
            return self._json(500, {"error": str(e)})

    def log_message(self, fmt, *args):
        pass


def main():
    ap = argparse.ArgumentParser(description="Serve the room tools and relay OSC to an X32.")
    ap.add_argument("--port", type=int, default=8032)
    ap.add_argument("--no-browser", action="store_true")
    a = ap.parse_args()
    handler = functools.partial(Handler, directory=HERE)
    server = None
    for port in range(a.port, a.port + 10):  # use the next free port if this one is taken
        try:
            server = ThreadingHTTPServer(("127.0.0.1", port), handler)
            break
        except OSError:
            continue
    if server is None:
        print("Ports %d-%d are all in use. Close other copies of Room Tools and try again." % (a.port, a.port + 9))
        if getattr(sys, "frozen", False):
            input("Press Enter to close.")
        return
    url = "http://localhost:%d/" % server.server_address[1]
    if os.name == "nt":
        os.system("title Room Tools " + VERSION)
    print("Room Tools %s running at %s" % (VERSION, url))
    print("Keep this window open while you work. Press Ctrl+C to stop.")
    if not a.no_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
