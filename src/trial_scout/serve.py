"""HTTP app for the Trial Scout front-end: dashboard API, AI chat, background scans.

Env vars:
- TRIAL_PROFILE_JSON: profile JSON injected by the scheduler (optional)
- TRIAL_SCOUT_STATE_PATH: scan state location (default ./data/trials_state.json)
- TRIAL_SCOUT_PROFILE_PATH: profile file the UI can edit (default ./data/trial_profile.json)
- TRIAL_SCOUT_NTFY_TOPIC: ntfy topic for diffs (optional)
- TRIAL_SCOUT_INTERVAL_MINUTES: rescan interval (default 1440)
- TRIAL_SCOUT_DIGEST_PATH: markdown research digest shown in the UI
- OPENAI_API_KEY: enables the chat endpoint
- OPENAI_MODEL: default gpt-4o-mini

Endpoints:
- GET  /              dashboard (static)
- GET  /api/trials    latest scan JSON
- GET  /api/context   research digest + summary
- GET  /api/profile   current profile
- POST /api/profile    save profile JSON from the UI
- POST /api/rescan    run a scan now (background thread)
- POST /api/chat      chat completions grounded in profile + trials
- GET  /healthz       liveness
"""

import json
import os
import threading
import time
import urllib.request
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from trial_scout import client, monitor, scoring

NL = chr(10)
WEB_DIR = Path(__file__).resolve().parent / "web"
LATEST = {"updated": None, "trials": [], "events": [], "error": None}
LOCK = threading.Lock()
RESCANNING = {"busy": False}

CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".ico": "image/x-icon",
}

SYSTEM_RULES = [
    "You are a patient-friendly assistant helping a family understand "
    "Parkinson's disease clinical trials.",
    "Never give medical advice, never recommend starting or stopping any "
    "treatment, never interpret symptoms.",
    "You may explain what a trial studies, what phase means, what typical "
    "requirements look like, and how to talk to the trial site or the doctor.",
    "Always encourage contacting the trial site and the care team for real "
    "decisions.",
    "Use short sentences, plain words, and a warm respectful tone suitable "
    "for an older reader.",
    "If asked something you cannot answer from the trial data, say so and "
    "suggest who to ask.",
]


def env(name, default=None):
    return os.environ.get(name, default)


def current_profile():
    # The UI-editable file wins so family edits are never shadowed by the
    # scheduler-injected default. ENV is the fallback when no file exists.
    path_p = Path(env("TRIAL_SCOUT_PROFILE_PATH", "data/trial_profile.json"))
    if path_p.exists():
        try:
            return json.loads(path_p.read_text())
        except ValueError:
            pass
    raw = env("TRIAL_PROFILE_JSON")
    if raw:
        try:
            return json.loads(raw)
        except ValueError:
            pass
    return {}


def profile_summary(profile):
    if not profile:
        return "not set"
    dbs = {"none": "no DBS implant, not considering",
           "considering": "considering deep brain stimulation",
           "implanted": "has a DBS implant"}.get(profile.get("dbs"), "?")
    return (
        f"age {profile.get('age')}, {dbs}, stage: {profile.get('stage')}, "
        f"levodopa for {profile.get('levodopa_years')} years"
    )


def scan_once(profile, state_path, ntfy_topic=None):
    studies = list(client.fetch_parkinson_studies())
    scored = [scoring.score_trial(profile, study) for study in studies]
    events, new_state = monitor.diff(studies, monitor.load_state(state_path))
    monitor.save_state(new_state, state_path)
    if ntfy_topic and events:
        try:
            monitor.notify(events, ntfy_topic)
        except Exception as exc:
            events.append({"kind": "notify_error", "nct_id": "", "title": str(exc)})
    return scored, events


def run_scan(profile, state_path, ntfy_topic=None):
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


def loop(profile, state_path, interval_minutes, ntfy_topic=None):
    while True:
        run_scan(current_profile(), state_path, ntfy_topic)
        time.sleep(max(5, interval_minutes) * 60)


def _rescan_thread():
    try:
        run_scan(current_profile(),
                 env("TRIAL_SCOUT_STATE_PATH", "data/trials_state.json"),
                 env("TRIAL_SCOUT_NTFY_TOPIC") or None)
    finally:
        RESCANNING["busy"] = False


class Handler(BaseHTTPRequestHandler):

    def _send(self, code, payload, content_type="application/json"):
        body = payload if isinstance(payload, bytes) else payload.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _json(self, code, obj):
        self._send(code, json.dumps(obj))

    def _body(self):
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0 or length > 200000:
            return {}
        try:
            return json.loads(self.rfile.read(length).decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return {}

    def _static(self, name):
        path = (WEB_DIR / name).resolve()
        if not str(path).startswith(str(WEB_DIR)) or not path.exists():
            self._json(404, {"error": "not found"})
            return
        ctype = CONTENT_TYPES.get(path.suffix, "text/plain")
        self._send(200, path.read_bytes(), ctype)

    def do_GET(self):
        path = self.path.split("?")[0]
        if path in ("/", "/index.html"):
            self._static("index.html")
        elif path == "/style.css":
            self._static("style.css")
        elif path == "/app.js":
            self._static("app.js")
        elif path == "/healthz":
            self._json(200, {"ok": True})
        elif path == "/api/trials":
            with LOCK:
                self._json(200, {
                    "disclaimer": "Decision support only. Not medical advice.",
                    "updated": LATEST["updated"],
                    "error": LATEST["error"],
                    "events": LATEST["events"],
                    "trials": LATEST["trials"],
                })
        elif path == "/api/context":
            self._context()
        elif path == "/api/profile":
            self._json(200, {"profile": current_profile()})
        else:
            self._json(404, {"error": "not found"})

    def do_POST(self):
        path = self.path.split("?")[0]
        if path == "/api/profile":
            prof = self._body()
            if not isinstance(prof, dict) or "age" not in prof:
                self._json(400, {"error": "profile JSON with at least an age is required"})
                return
            path_p = Path(env("TRIAL_SCOUT_PROFILE_PATH", "data/trial_profile.json"))
            path_p.parent.mkdir(parents=True, exist_ok=True)
            path_p.write_text(json.dumps(prof, indent=2) + NL)
            self._json(200, {"saved": True})
        elif path == "/api/rescan":
            if RESCANNING["busy"]:
                self._json(202, {"started": False, "reason": "scan already running"})
                return
            RESCANNING["busy"] = True
            threading.Thread(target=_rescan_thread, daemon=True).start()
            self._json(202, {"started": True})
        elif path == "/api/chat":
            self._chat(self._body())
        else:
            self._json(404, {"error": "not found"})

    def _context(self):
        digest_path = Path(env("TRIAL_SCOUT_DIGEST_PATH", "data/research_digest.md"))
        digest = ""
        if digest_path.exists():
            digest = digest_path.read_text(errors="replace")[:12000]
        with LOCK:
            trials = LATEST["trials"]
            updated = LATEST["updated"]
        candidates = [t for t in trials if t["verdict"] == "candidate"]
        conflicts = [t for t in trials if t["verdict"] == "dbs-conflict"]
        self._json(200, {
            "updated": updated,
            "total": len(trials),
            "candidates": len(candidates),
            "dbs_conflicts": len(conflicts),
            "digest": digest,
            "digest_available": bool(digest),
        })

    def _chat(self, body):
        key = env("OPENAI_API_KEY")
        messages = body.get("messages") or []
        if not key:
            self._json(200, {"reply": "The AI helper is not set up yet. "
                              "Ask Tolu to add the OpenAI key to the deployment."})
            return
        if not messages or not isinstance(messages, list):
            self._json(400, {"error": "messages required"})
            return
        profile = current_profile()
        with LOCK:
            trials = LATEST["trials"]
            updated = LATEST["updated"]
        top = scoring.rank(trials)[:25]
        listing = NL.join(
            f"- {t['nct_id']} [{t['verdict']}] {t['title'][:110]}"
            + (f" site {t['nearest_site']['city']}, {t['nearest_site']['state']}"
               f" ({t['nearest_site']['miles']:.0f} mi)" if t.get("nearest_site") else "")
            for t in top
        )
        digest_path = Path(env("TRIAL_SCOUT_DIGEST_PATH", "data/research_digest.md"))
        digest = digest_path.read_text(errors="replace")[:4000] if digest_path.exists() else ""
        system = NL.join(SYSTEM_RULES) + NL + NL + (
            f"Family situation: {profile_summary(profile)}. "
            f"Data refreshed: {updated}. Current shortlist:{NL}{listing}"
        )
        if digest:
            system += NL + NL + "Recent research notes:" + NL + digest
        payload = json.dumps({
            "model": env("OPENAI_MODEL", "gpt-4o-mini"),
            "messages": [{"role": "system", "content": system}]
            + messages[-10:],
            "max_tokens": 700,
            "temperature": 0.4,
        }).encode("utf-8")
        request = urllib.request.Request(
            "https://api.openai.com/v1/chat/completions",
            data=payload,
            headers={"Content-Type": "application/json",
                     "Authorization": "Bearer " + key},
        )
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                result = json.loads(response.read().decode("utf-8"))
            reply = result["choices"][0]["message"]["content"]
            self._json(200, {"reply": reply})
        except Exception as exc:
            self._json(502, {"reply": "The AI helper had a connection problem. "
                             "Try again in a moment. (" + str(exc)[:120] + ")"})

    def log_message(self, fmt, *args):
        pass


def serve(host, port, profile, state_path, interval_minutes, ntfy_topic=None):
    if profile:
        run_scan(profile, state_path, ntfy_topic)
    worker = threading.Thread(
        target=loop, args=(current_profile(), state_path, interval_minutes, ntfy_topic),
        daemon=True,
    )
    worker.start()
    server = ThreadingHTTPServer((host, port), Handler)
    server.serve_forever()
