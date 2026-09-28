"""HTTP API + background scan loop for server deployment.

Env vars:
- TRIAL_PROFILE_JSON: the profile as a JSON object (injected by the scheduler)
- TRIAL_SCOUT_STATE_PATH: where scan state lives (default ./data/trials_state.json)
- TRIAL_SCOUT_NTFY_TOPIC: ntfy topic to push diffs to (optional)
- TRIAL_SCOUT_INTERVAL_MINUTES: rescan interval (default 1440)

Endpoints:
- GET /          -> latest scan as JSON (trials scored + events)
- GET /healthz   -> liveness
"""

import json
import os
import threading
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from trial_scout import client, monitor, scoring

NL = chr(10)

LATEST = {"updated": None, "trials": [], "events": [], "error": None}
LOCK = threading.Lock()


def scan_once(profile, state_path, ntfy_topic=None):
    studies = list(client.fetch_parkinson_studies())
    scored = [scoring.score_trial(profile, study) for study in studies]
    events, new_state = monitor.diff(studies, monitor.load_state(state_path))
    monitor.save_state(new_state, state_path)
    try:
        monitor.notify(events, ntfy_topic) if ntfy_topic else None
    except Exception as exc:  # notification failure must not kill the loop
        events.append({"kind": "notify_error", "nct_id": "", "title": str(exc)})
    return scored, events


def loop(profile, state_path, interval_minutes, ntfy_topic=None):
    while True:
        try:
            scored, events = scan_once(profile, state_path, ntfy_topic)
            with LOCK:
                LATEST["updated"] = datetime.now(timezone.utc).isoformat()
                LATEST["trials"] = scored
                LATEST["events"] = events
                LATEST["error"] = None
        except Exception as exc:
            with LOCK:
                LATEST["error"] = str(exc)
        time.sleep(max(5, interval_minutes) * 60)


class Handler(BaseHTTPRequestHandler):
    def _send(self, code, payload, content_type="application/json"):
        body = payload.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/healthz":
            self._send(200, json.dumps({"ok": True}))
            return
        with LOCK:
            payload = json.dumps({
                "disclaimer": "Decision support only. Not medical advice.",
                "updated": LATEST["updated"],
                "error": LATEST["error"],
                "events": LATEST["events"],
                "trials": LATEST["trials"],
            })
        self._send(200, payload)

    def log_message(self, fmt, *args):  # keep provider logs terse
        pass


def serve(host, port, profile, state_path, interval_minutes, ntfy_topic=None):
    worker = threading.Thread(
        target=loop, args=(profile, state_path, interval_minutes, ntfy_topic), daemon=True
    )
    worker.start()
    server = ThreadingHTTPServer((host, port), Handler)
    server.serve_forever()
