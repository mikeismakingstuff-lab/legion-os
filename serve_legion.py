"""
LEGION Context Server
Serves the LEGION project folder over HTTP so Claude (via web_fetch/web_search)
and Antigravity can both read live project state from one source of truth.

Usage:
    python serve_legion.py

Then point it at your LEGION repo root by editing SERVE_DIR below,
or pass it as an argument:
    python serve_legion.py /path/to/legion-os
"""

import sys
import os
from http.server import HTTPServer, SimpleHTTPRequestHandler
from functools import partial

# --- CONFIG ---
PORT = 8420
SECRET_PATH = "legion-x9k2m4p8q1"   # obscurity token - change this to your own random string
SERVE_DIR = sys.argv[1] if len(sys.argv) > 1 else "."
# ---------------

class ScopedHandler(SimpleHTTPRequestHandler):
    """Only serves requests that include the secret path prefix. Read-only."""

    def translate_path(self, path):
        # Strip the secret prefix before resolving to a real file path
        prefix = f"/{SECRET_PATH}"
        if path.startswith(prefix):
            path = path[len(prefix):] or "/"
        else:
            path = "/__blocked__"  # will 404
        return super().translate_path(path)

    def do_GET(self):
        if not self.path.startswith(f"/{SECRET_PATH}"):
            self.send_error(404, "Not found")
            return
        return super().do_GET()

    # Block any write-like methods just in case
    def do_POST(self):
        self.send_error(405, "Read-only server")

    def do_PUT(self):
        self.send_error(405, "Read-only server")

    def do_DELETE(self):
        self.send_error(405, "Read-only server")

    def log_message(self, format, *args):
        # Timestamped logging so you can see every access (who's reading what, when)
        print(f"[{self.log_date_time_string()}] {self.address_string()} - {format % args}")


def main():
    os.chdir(SERVE_DIR)
    handler = partial(ScopedHandler, directory=SERVE_DIR)
    server = HTTPServer(("0.0.0.0", PORT), handler)
    print(f"Serving {os.path.abspath(SERVE_DIR)}")
    print(f"Local URL:  http://localhost:{PORT}/{SECRET_PATH}/")
    print(f"LAN URL:    http://<your-lan-ip>:{PORT}/{SECRET_PATH}/")
    print("Run a tunnel (ngrok/cloudflared) pointed at this port to get a public URL.")
    print("Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down.")


if __name__ == "__main__":
    main()