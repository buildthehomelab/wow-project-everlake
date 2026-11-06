#!/usr/bin/env python3
"""Receives diagnostic reports from player machines (everlake-client.sh check) on the LAN.

    PUT /<name>   body = the report   -> saved as /reports/<time>-<name>.txt

Run it with: docker compose --profile tools up -d report-drop   (port 8099)
"""
import datetime
import http.server
import os
import re

OUT = os.environ.get("REPORTS_DIR", "/reports")


class Handler(http.server.BaseHTTPRequestHandler):
    def do_PUT(self):
        name = re.sub(r"[^A-Za-z0-9_.-]", "_", self.path.strip("/"))[:60] or "report"
        size = int(self.headers.get("Content-Length", 0))
        if size > 2_000_000:
            self.send_response(413); self.end_headers(); return
        body = self.rfile.read(size)
        stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
        path = os.path.join(OUT, f"{stamp}-{name}.txt")
        with open(path, "wb") as f:
            f.write(body)
        self.send_response(200); self.end_headers()
        self.wfile.write(f"saved {os.path.basename(path)}\n".encode())

    def log_message(self, fmt, *args):
        print(self.address_string(), fmt % args, flush=True)


if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    http.server.ThreadingHTTPServer(("0.0.0.0", 8099), Handler).serve_forever()
