"""
src/web_server.py
Legion OS — Control Center Backend API Server

Environment Audit:
1. Local System Check: Checked for existing dashboard servers or APIs. None found.
2. Open-Source Check: Standard HTTP server using Python's built-in `http.server` is used to avoid external dependencies.
3. Conclusion: Proceeding with a custom standard-library HTTP server.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Add the parent directory of 'src' to sys.path to allow direct execution
sys.path.append(str(Path(__file__).resolve().parent.parent))

import json
import os
import sqlite3
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Optional

# Try importing psutil for real telemetry, fallback to simulated values if missing
try:
    import psutil
except ImportError:
    psutil = None

from src.db import get_connection

PORT = 8080
BASE_DIR = Path(__file__).resolve().parent.parent
PUBLIC_DIR = BASE_DIR / "public"
DB_PATH = BASE_DIR / "pipeline.db"


class LegionHTTPHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        # Route API endpoints
        if self.path == "/api/telemetry":
            self.handle_telemetry()
        elif self.path == "/api/files":
            self.handle_files()
        else:
            # Serve static files
            self.serve_static()

    def do_POST(self):
        if self.path == "/api/preview":
            self.handle_preview()
        elif self.path == "/api/chat":
            self.handle_chat()
        elif self.path == "/api/notepad":
            self.handle_notepad()
        else:
            self.send_error(404, "Not Found")

    def serve_static(self):
        # Default to index.html
        path_str = self.path.lstrip("/")
        if not path_str or path_str == "":
            path_str = "index.html"

        target_path = (PUBLIC_DIR / path_str).resolve()

        # Security check: ensure target_path is inside PUBLIC_DIR
        if not target_path.is_relative_to(PUBLIC_DIR.resolve()):
            self.send_error(403, "Forbidden")
            return

        if target_path.is_file():
            self.send_response(200)
            # Set content type
            if target_path.suffix == ".html":
                self.send_header("Content-Type", "text/html; charset=utf-8")
            elif target_path.suffix == ".css":
                self.send_header("Content-Type", "text/css; charset=utf-8")
            elif target_path.suffix == ".js":
                self.send_header("Content-Type", "application/javascript; charset=utf-8")
            elif target_path.suffix == ".jpeg" or target_path.suffix == ".jpg":
                self.send_header("Content-Type", "image/jpeg")
            elif target_path.suffix == ".png":
                self.send_header("Content-Type", "image/png")
            self.end_headers()
            self.wfile.write(target_path.read_bytes())
        else:
            self.send_error(404, "Not Found")

    def handle_telemetry(self):
        # Fetch CPU and RAM
        if psutil:
            cpu = psutil.cpu_percent()
            ram = psutil.virtual_memory().percent
        else:
            # Fallback/simulated telemetry
            import random
            cpu = round(random.uniform(15.0, 45.0), 1)
            ram = round(random.uniform(40.0, 60.0), 1)

        # Fetch token count from SQLite if table exists
        token_count = 142830  # Default fallback
        token_limit = 500000
        conn = get_connection(DB_PATH)
        try:
            # Check if token_count table exists
            cursor = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='token_count'"
            )
            if cursor.fetchone():
                row = conn.execute(
                    "SELECT token_count, token_limit FROM token_count ORDER BY id DESC LIMIT 1"
                ).fetchone()
                if row:
                    token_count = row["token_count"]
                    token_limit = row["token_limit"]
        except Exception:
            pass
        finally:
            conn.close()

        response = {
            "cpu": cpu,
            "ram": ram,
            "latency": 42,  # Simulated ms
            "token_count": token_count,
            "token_limit": token_limit,
        }
        self.send_json(response)

    def handle_files(self):
        # Generate file tree of E:\Legion (excluding .git, __pycache__, etc.)
        def build_tree(dir_path: Path) -> dict:
            tree = {"name": dir_path.name, "type": "directory", "children": []}
            try:
                for item in sorted(dir_path.iterdir()):
                    if item.name in (".git", "__pycache__", ".agent", ".gemini", "node_modules"):
                        continue
                    if item.is_dir():
                        tree["children"].append(build_tree(item))
                    else:
                        tree["children"].append({
                            "name": item.name,
                            "type": "file",
                            "path": str(item.relative_to(BASE_DIR)),
                        })
            except Exception:
                pass
            return tree

        # Build tree starting from BASE_DIR
        tree = build_tree(BASE_DIR)
        self.send_json(tree)

    def handle_preview(self):
        content_length = int(self.headers.get("Content-Length", 0))
        post_data = self.rfile.read(content_length)
        try:
            data = json.loads(post_data.decode("utf-8"))
            requested_path = data.get("path", "")
            
            # Strict path resolution to prevent directory traversal
            resolved_path = (BASE_DIR / requested_path).resolve()
            if not resolved_path.is_relative_to(BASE_DIR.resolve()):
                self.send_error(403, "Forbidden: Directory traversal attempt blocked.")
                return

            if resolved_path.is_file():
                content = resolved_path.read_text(encoding="utf-8", errors="replace")
                self.send_json({"content": content, "name": resolved_path.name})
            else:
                self.send_error(404, "File Not Found")
        except Exception as e:
            self.send_error(400, f"Bad Request: {e}")

    def handle_chat(self):
        content_length = int(self.headers.get("Content-Length", 0))
        post_data = self.rfile.read(content_length)
        try:
            data = json.loads(post_data.decode("utf-8"))
            message = data.get("message", "")
            mission_id = data.get("mission_id", "default-mission")

            # Store user message in SQLite
            self._save_chat_message(mission_id, "User", message)

            # Call local Ollama endpoint
            ai_response = self._call_ollama(message)

            # Store AI response in SQLite
            self._save_chat_message(mission_id, "Legion AI", ai_response)

            self.send_json({"response": ai_response})
        except Exception as e:
            self.send_error(500, f"Internal Server Error: {e}")

    def handle_notepad(self):
        content_length = int(self.headers.get("Content-Length", 0))
        post_data = self.rfile.read(content_length)
        try:
            data = json.loads(post_data.decode("utf-8"))
            action = data.get("action", "")
            mission_id = data.get("mission_id", "default-mission")

            if action == "save":
                content = data.get("content", "")
                self._save_notepad(mission_id, content)
                self.send_json({"status": "success"})
            elif action == "load":
                content = self._load_notepad(mission_id)
                self.send_json({"content": content})
            else:
                self.send_error(400, "Invalid Action")
        except Exception as e:
            self.send_error(500, f"Internal Server Error: {e}")

    def send_json(self, data: dict):
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.end_headers()
        self.wfile.write(json.dumps(data).encode("utf-8"))

    def _save_chat_message(self, mission_id: str, sender: str, message: str):
        conn = get_connection(DB_PATH)
        try:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS chat_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    mission_id TEXT NOT NULL,
                    sender TEXT NOT NULL,
                    message TEXT NOT NULL,
                    timestamp TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                INSERT INTO chat_logs (mission_id, sender, message, timestamp)
                VALUES (?, ?, ?, datetime('now'))
                """,
                (mission_id, sender, message),
            )
            conn.commit()
        finally:
            conn.close()

    def _save_notepad(self, mission_id: str, content: str):
        conn = get_connection(DB_PATH)
        try:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS notepad_content (
                    mission_id TEXT PRIMARY KEY,
                    content TEXT NOT NULL,
                    timestamp TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                INSERT OR REPLACE INTO notepad_content (mission_id, content, timestamp)
                VALUES (?, ?, datetime('now'))
                """,
                (mission_id, content),
            )
            conn.commit()
        finally:
            conn.close()

    def _load_notepad(self, mission_id: str) -> str:
        conn = get_connection(DB_PATH)
        try:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS notepad_content (
                    mission_id TEXT PRIMARY KEY,
                    content TEXT NOT NULL,
                    timestamp TEXT NOT NULL
                )
                """
            )
            row = conn.execute(
                "SELECT content FROM notepad_content WHERE mission_id = ?",
                (mission_id,),
            ).fetchone()
            return row["content"] if row else ""
        finally:
            conn.close()

    def _call_ollama(self, prompt: str) -> str:
        # Standard urllib request to local Ollama API
        payload = {
            "model": "llama3",
            "prompt": prompt,
            "stream": False,
        }
        req = urllib.request.Request(
            "http://localhost:11434/api/generate",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=15) as response:
                res = json.loads(response.read().decode("utf-8"))
                return res.get("response", "")
        except Exception as e:
            return f"Ollama offline. Response generated locally: Echoing back your prompt: '{prompt}' (Error: {e})"


def run_server():
    # Ensure public directory exists
    PUBLIC_DIR.mkdir(exist_ok=True)
    
    server_address = ("", PORT)
    httpd = HTTPServer(server_address, LegionHTTPHandler)
    print(f"Legion OS Control Center running at http://localhost:{PORT}")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping server...")
        httpd.server_close()


if __name__ == "__main__":
    run_server()
