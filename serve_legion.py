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
import base64
from http.server import HTTPServer, SimpleHTTPRequestHandler
from functools import partial

# --- CONFIG ---
PORT = 8420
AUTH_USERNAME = os.environ.get("LEGION_SERVER_USER", "legion")
AUTH_PASSWORD = os.environ.get("LEGION_SERVER_PASSWORD")
SERVE_DIR = sys.argv[1] if len(sys.argv) > 1 else "."
BIND_ADDRESS = "127.0.0.1"
# ---------------

if not AUTH_PASSWORD:
    sys.stderr.write(
        "[ERROR] LEGION_SERVER_PASSWORD is not set. Refusing to start with no "
        "credential rather than fall back to a hardcoded default.\n"
        "Set it first, e.g.:\n"
        "  set LEGION_SERVER_PASSWORD=your-password-here   (Windows cmd)\n"
        "  $env:LEGION_SERVER_PASSWORD=\"your-password-here\"  (PowerShell)\n"
    )
    sys.exit(1)

class AuthHandler(SimpleHTTPRequestHandler):
    """Serves requests only if valid Basic Auth is provided. Read-only."""

    def do_AUTHHEAD(self):
        self.send_response(401)
        self.send_header("WWW-Authenticate", 'Basic realm="LEGION Context Server"')
        self.send_header("Content-type", "text/html")
        self.end_headers()

    def check_auth(self):
        auth_header = self.headers.get("Authorization")
        if not auth_header:
            return False
        
        try:
            auth_type, encoded_credentials = auth_header.split(" ", 1)
            if auth_type.lower() != "basic":
                return False
            
            decoded_credentials = base64.b64decode(encoded_credentials).decode("utf-8")
            username, password = decoded_credentials.split(":", 1)
            
            return username == AUTH_USERNAME and password == AUTH_PASSWORD
        except Exception:
            return False

    def do_GET(self):
        if not self.check_auth():
            self.do_AUTHHEAD()
            self.wfile.write(b"Unauthorized")
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
    handler = partial(AuthHandler, directory=SERVE_DIR)
    server = HTTPServer((BIND_ADDRESS, PORT), handler)
    print(f"Serving {os.path.abspath(SERVE_DIR)}")
    print(f"Local URL:  http://{BIND_ADDRESS}:{PORT}/")
    print("Server is secured with HTTP Basic Authentication.")
    print("Run a tunnel (ngrok/cloudflared) pointed at this port to get a public URL.")
    print("Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down.")


if __name__ == "__main__":
    main()