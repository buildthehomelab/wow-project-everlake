#!/usr/bin/env python3
"""A CDN for a patched build (gate 2): our files from a folder, everything else passed through to Blizzard.

    python3 tools/tact/cdn.py --dir <patch.py --out folder> [--port 80] [--log cdn.log]

Serves the folder patch.py wrote (<cdn path>/config/.., <cdn path>/data/..) with byte ranges, as Blizzard's CDN
does. Any other path is fetched from Blizzard's CDN hosts named in build.json (with the same byte range) and
streamed back, so the client sees one CDN that has Blizzard's build plus ours. Every request is logged with where
it was answered from, which is the point of the experiment: it shows what the client asks for.
"""
import argparse
import http.server
import json
import os
import re
import sys
import threading
import time
import urllib.error
import urllib.request

LOCK = threading.Lock()


def log_line(out, text):
    line = "%s %s" % (time.strftime("%H:%M:%S"), text)
    with LOCK:
        print(line, flush=True)
        if out:
            out.write(line + "\n")
            out.flush()


def make_handler(folder, hosts, out):
    class Handler(http.server.BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, fmt, *args):  # replaced by log_line
            pass

        def do_HEAD(self):
            self.answer(head=True)

        def do_GET(self):
            self.answer(head=False)

        def answer(self, head):
            path = self.path.split("?")[0]
            want = self.headers.get("Range")
            local = os.path.normpath(os.path.join(folder, path.lstrip("/")))
            if local.startswith(folder + os.sep) and os.path.isfile(local):
                self.serve_local(local, want, head, path)
            else:
                self.pass_through(path, want, head)

        def serve_local(self, local, want, head, path):
            size = os.path.getsize(local)
            start, end, status = 0, size - 1, 200
            m = re.fullmatch(r"bytes=(\d*)-(\d*)", want or "")
            if m and (m.group(1) or m.group(2)):
                if m.group(1):
                    start = int(m.group(1))
                    end = min(int(m.group(2)), size - 1) if m.group(2) else size - 1
                else:
                    start, end = max(0, size - int(m.group(2))), size - 1
                status = 206
            if start > end:
                self.send_response(416)
                self.send_header("Content-Range", "bytes */%d" % size)
                self.send_header("Content-Length", "0")
                self.end_headers()
                log_line(out, "OURS     416 %s %s" % (path, want))
                return
            self.send_response(status)
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("Content-Length", str(end - start + 1))
            self.send_header("Accept-Ranges", "bytes")
            if status == 206:
                self.send_header("Content-Range", "bytes %d-%d/%d" % (start, end, size))
            self.end_headers()
            if not head:
                with open(local, "rb") as f:
                    f.seek(start)
                    left = end - start + 1
                    while left:
                        chunk = f.read(min(left, 1 << 20))
                        self.wfile.write(chunk)
                        left -= len(chunk)
            log_line(out, "OURS     %d %s %s %d bytes" % (status, path, want or "", end - start + 1))

        def pass_through(self, path, want, head):
            last = None
            for host in hosts:
                req = urllib.request.Request("http://%s%s" % (host, path), method="HEAD" if head else "GET")
                if want:
                    req.add_header("Range", want)
                try:
                    resp = urllib.request.urlopen(req, timeout=30)
                except urllib.error.HTTPError as e:
                    resp = e
                except (urllib.error.URLError, OSError) as e:
                    last = e
                    continue
                self.send_response(resp.status if hasattr(resp, "status") else resp.code)
                length = resp.headers.get("Content-Length")
                for key in ("Content-Type", "Content-Length", "Content-Range", "Accept-Ranges"):
                    if resp.headers.get(key):
                        self.send_header(key, resp.headers[key])
                if length is None:
                    self.send_header("Connection", "close")
                    self.close_connection = True
                self.end_headers()
                sent = 0
                if not head:
                    while True:
                        chunk = resp.read(1 << 20)
                        if not chunk:
                            break
                        self.wfile.write(chunk)
                        sent += len(chunk)
                code = resp.status if hasattr(resp, "status") else resp.code
                log_line(out, "BLIZZARD %d %s %s %d bytes (%s)" % (code, path, want or "", sent, host))
                return
            self.send_response(502)
            self.send_header("Content-Length", "0")
            self.end_headers()
            log_line(out, "FAILED   502 %s %s: %s" % (path, want or "", last))

    return Handler


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--dir", required=True, help="the folder patch.py --out wrote")
    ap.add_argument("--port", type=int, default=80)
    ap.add_argument("--bind", default="0.0.0.0")
    ap.add_argument("--log", help="also append every request to this file")
    args = ap.parse_args()
    folder = os.path.realpath(args.dir)
    summary = json.load(open(os.path.join(folder, "build.json")))
    out = open(args.log, "a") if args.log else None
    server = http.server.ThreadingHTTPServer((args.bind, args.port),
                                             make_handler(folder, summary["blizzard_hosts"], out))
    log_line(out, "CDN on %s:%d: build %s / CDN config %s from %s, the rest from %s" % (
        args.bind, args.port, summary["build_key"], summary["cdn_key"], folder, ", ".join(summary["blizzard_hosts"])))
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    sys.exit(main())
