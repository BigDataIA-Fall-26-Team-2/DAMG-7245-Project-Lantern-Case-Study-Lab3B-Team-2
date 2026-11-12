"""Local-only web interface for the Part 0 harness."""
import argparse
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
from pathlib import Path
import secrets
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from creditwatch.chat import Harness


def handler_for(harness):
    sessions = {}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass  # Do not log credentials or chat content.

        def respond(self, status, payload, cookie=None):
            data = json.dumps(payload).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", "no-store")
            if cookie:
                self.send_header("Set-Cookie", cookie)
            self.end_headers()
            self.wfile.write(data)

        def session_id(self):
            cookie = SimpleCookie(self.headers.get("Cookie", ""))
            return cookie["session"].value if "session" in cookie else ""

        def do_GET(self):
            if self.path != "/":
                self.respond(404, {"error": "Not found"})
                return
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Frame-Options", "DENY")
            self.end_headers()
            self.wfile.write(Path(__file__).with_name("index.html").read_bytes())

        def do_POST(self):
            expected = f"http://127.0.0.1:{self.server.server_port}"
            if self.headers.get("Origin") != expected:
                self.respond(403, {"error": "Open the chat at " + expected})
                return
            try:
                size = int(self.headers.get("Content-Length", "0"))
                if not 0 < size <= 16384:
                    raise ValueError("Invalid request size")
                body = json.loads(self.rfile.read(size))
                if not isinstance(body, dict):
                    raise ValueError("Expected an object")
                now = time.monotonic()
                for sid, (_, expiry) in list(sessions.items()):
                    if expiry <= now:
                        del sessions[sid]
                sid = self.session_id()
                if self.path == "/login":
                    session = harness.login("priya", body.get("token", ""), body.get("mandate", ""))
                    sessions.pop(sid, None)
                    sid = secrets.token_urlsafe(32)
                    sessions[sid] = (session, now + 3600)
                    self.respond(200, {"reply": session.reply("/session")},
                                 f"session={sid}; HttpOnly; SameSite=Strict; Path=/; Max-Age=3600")
                elif self.path == "/logout":
                    sessions.pop(sid, None)
                    self.respond(200, {"reply": "Logged out"}, "session=; HttpOnly; SameSite=Strict; Path=/; Max-Age=0")
                elif self.path == "/chat":
                    if sid not in sessions:
                        raise PermissionError("Log in first; your session may have expired.")
                    if set(body) != {"message"} or not isinstance(body["message"], str):
                        raise ValueError("Chat accepts only a message; log out to change mandate.")
                    self.respond(200, {"reply": sessions[sid][0].reply(body["message"])})
                else:
                    self.respond(404, {"error": "Not found"})
            except PermissionError as exc:
                self.respond(401, {"error": str(exc)})
            except (ValueError, TypeError, AttributeError):
                self.respond(400, {"error": "Invalid request or missing workspace"})
            except (OSError, RuntimeError):
                self.respond(500, {"error": "Check the workspace and skill lockfile; run notebook 00."})

    return Handler


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    server = HTTPServer(("127.0.0.1", args.port), handler_for(Harness(ROOT)))
    print(f"Open http://127.0.0.1:{args.port} — Ctrl+C stops the server", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
