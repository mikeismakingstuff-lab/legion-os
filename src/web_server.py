"""
src/web_server.py
Legion OS — Control Center Backend API Server
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
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
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
        elif self.path == "/api/deliberation":
            self.handle_deliberation()
        elif self.path == "/health":
            self.send_json({"status": "ok"})
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
        elif self.path == "/api/antigravity":
            self.handle_antigravity()
        elif self.path == "/api/committee":
            self.handle_committee()
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
        import time
        import random

        # Fetch CPU and RAM
        if psutil:
            cpu = psutil.cpu_percent()
            ram = psutil.virtual_memory().percent
            cpu_cores = psutil.cpu_count()
            ram_used_gb = psutil.virtual_memory().used / (1024**3)
            ram_total_gb = psutil.virtual_memory().total / (1024**3)
            disk_used_gb = psutil.disk_usage('/').used / (1024**3)
            disk_total_gb = psutil.disk_usage('/').total / (1024**3)
            network_sent = psutil.net_io_counters().bytes_sent
            network_recv = psutil.net_io_counters().bytes_recv
            uptime_seconds = int(time.time() - psutil.boot_time())
            process_count = len(psutil.pids())
        else:
            # Fallback/simulated telemetry
            cpu = round(random.uniform(15.0, 45.0), 1)
            ram = round(random.uniform(40.0, 60.0), 1)
            cpu_cores = 8
            ram_total_gb = 16.0
            ram_used_gb = (ram / 100.0) * ram_total_gb
            disk_total_gb = 512.0
            disk_used_gb = 245.5
            network_sent = int(time.time() * 100) % 1000000
            network_recv = int(time.time() * 250) % 2000000
            uptime_seconds = int(time.time()) % 86400
            process_count = 124

        queue_depth = random.randint(0, 10)
        signal_strength = round(random.uniform(85.0, 99.0), 1)

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
            "latency": random.randint(35, 48),
            "token_count": token_count,
            "token_limit": token_limit,
            "cpu_cores": cpu_cores,
            "ram_used_gb": ram_used_gb,
            "ram_total_gb": ram_total_gb,
            "disk_used_gb": disk_used_gb,
            "disk_total_gb": disk_total_gb,
            "network_sent": network_sent,
            "network_recv": network_recv,
            "uptime_seconds": uptime_seconds,
            "process_count": process_count,
            "queue_depth": queue_depth,
            "signal_strength": signal_strength,
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

    def handle_deliberation(self):
        live_path = BASE_DIR / "committee_live.txt"
        if live_path.is_file():
            content = live_path.read_text(encoding="utf-8", errors="replace")
        else:
            content = "No active deliberation."
        self.send_json({"content": content})

    def handle_committee(self):
        content_length = int(self.headers.get("Content-Length", 0))
        post_data = self.rfile.read(content_length)
        try:
            data = json.loads(post_data.decode("utf-8"))
            message = data.get("message", "")
            
            if not message:
                self.send_error(400, "Message is required")
                return
                
            # Clear the live log file before starting
            live_path = BASE_DIR / "committee_live.txt"
            live_path.write_text("Initializing Committee Protocol...\n", encoding="utf-8")
            
            # Spawn committee.py in a background thread
            def run_committee(prompt):
                try:
                    env = os.environ.copy()
                    env["PYTHONIOENCODING"] = "utf-8"
                    process = subprocess.Popen(
                        ["python", str(BASE_DIR / "committee.py")],
                        stdin=subprocess.PIPE,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        cwd=str(BASE_DIR),
                        env=env
                    )
                    stdout, stderr = process.communicate(input=prompt.encode("utf-8"))
                    if process.returncode != 0:
                        with open(live_path, "a", encoding="utf-8") as f:
                            f.write(f"\n\n### Error running committee\n\n{stderr.decode('utf-8', errors='replace')}")
                except Exception as e:
                    live_path.write_text(f"Error running committee: {e}", encoding="utf-8")

            thread = threading.Thread(target=run_committee, args=(message,))
            thread.daemon = True
            thread.start()
            
            self.send_json({"status": "started"})
        except Exception as e:
            self.send_error(500, f"Internal Server Error: {e}")

    def handle_antigravity(self):
        content_length = int(self.headers.get("Content-Length", 0))
        post_data = self.rfile.read(content_length)
        try:
            data = json.loads(post_data.decode("utf-8"))
            message = data.get("message", "")
            
            # Call OpenRouter with Antigravity model
            url = "https://openrouter.ai/api/v1/chat/completions"
            api_key = "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"
            
            payload = {
                "model": "qwen/qwen-2.5-7b-instruct",
                "messages": [
                    {"role": "system", "content": "You are The Engineer, a powerful AI assistant. You are chatting with the user in their Legion OS Control Center."},
                    {"role": "user", "content": message}
                ],
                "temperature": 0.7,
                "stream": False
            }
            
            req = urllib.request.Request(url)
            req.add_header("Authorization", f"Bearer {api_key}")
            req.add_header("Content-Type", "application/json; charset=utf-8")
            
            data_bytes = json.dumps(payload).encode('utf-8')
            with urllib.request.urlopen(req, data=data_bytes, timeout=30) as response:
                res_data = json.loads(response.read().decode('utf-8'))
                ai_response = res_data['choices'][0]['message']['content']
                self._update_token_usage(len(message) // 4 + len(ai_response) // 4)
                self.send_json({"response": ai_response})
        except Exception as e:
            self.send_error(500, f"Internal Server Error: {e}")

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
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    mission_id TEXT NOT NULL UNIQUE,
                    content TEXT NOT NULL,
                    timestamp TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                INSERT INTO notepad_content (mission_id, content, timestamp)
                VALUES (?, ?, datetime('now'))
                ON CONFLICT(mission_id) DO UPDATE SET
                    content=excluded.content,
                    timestamp=excluded.timestamp
                """,
                (mission_id, content),
            )
            conn.commit()
        finally:
            conn.close()

    def _load_notepad(self, mission_id: str) -> str:
        conn = get_connection(DB_PATH)
        try:
            cursor = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='notepad_content'"
            )
            if not cursor.fetchone():
                return ""
            row = conn.execute(
                "SELECT content FROM notepad_content WHERE mission_id = ? LIMIT 1",
                (mission_id,),
            ).fetchone()
            return row["content"] if row else ""
        finally:
            conn.close()

    def _update_token_usage(self, tokens_used: int):
        conn = get_connection(DB_PATH)
        try:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS token_count (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    token_count INTEGER NOT NULL,
                    token_limit INTEGER NOT NULL
                )
                """
            )
            row = conn.execute("SELECT token_count, token_limit FROM token_count ORDER BY id DESC LIMIT 1").fetchone()
            new_count = (row["token_count"] if row else 142830) + tokens_used
            limit = row["token_limit"] if row else 500000
            conn.execute("INSERT INTO token_count (token_count, token_limit) VALUES (?, ?)", (new_count, limit))
            conn.commit()
        finally:
            conn.close()

    def _call_ollama(self, prompt: str) -> str:
        # Call OpenRouter with Nemotron model
        url = "https://openrouter.ai/api/v1/chat/completions"
        api_key = "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"
        
        payload = {
            "model": "nvidia/nemotron-3-super-120b-a12b:free",
            "messages": [
                {"role": "system", "content": "You are Legion AI, a helpful system assistant."},
                {"role": "user", "content": prompt}
            ],
            "temperature": 0.7,
            "stream": False
        }
        
        req = urllib.request.Request(url)
        req.add_header("Authorization", f"Bearer {api_key}")
        req.add_header("Content-Type", "application/json; charset=utf-8")
        req.add_header("HTTP-Referer", "http://localhost:3000")
        req.add_header("X-Title", "Legion Studio")
        
        try:
            data_bytes = json.dumps(payload).encode('utf-8')
            with urllib.request.urlopen(req, data=data_bytes, timeout=30) as response:
                res_data = json.loads(response.read().decode('utf-8'))
                ai_response = res_data['choices'][0]['message']['content']
                self._update_token_usage(len(prompt) // 4 + len(ai_response) // 4)
                return ai_response
        except Exception as e:
            return f"Error communicating with AI service: {e}"


def main():
    server = HTTPServer(("localhost", PORT), LegionHTTPHandler)
    print(f"Legion OS Control Center Backend running on http://localhost:{PORT}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
