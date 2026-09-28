"""State tracking so scans can say what is NEW or CHANGED since last time.

State lives in data/trials_state.json (gitignored). Run `scan` on a cron and
it will only surface the diff.
"""

import json
import urllib.request
from pathlib import Path

NL = chr(10)


def notify(events, topic, server="https://ntfy.sh", title="Trial Scout"):
    """Push the diff to an ntfy topic so the family gets pinged."""
    if not events or not topic:
        return False
    body = render_events(events)
    request = urllib.request.Request(
        server.rstrip("/") + "/" + topic,
        data=body.encode("utf-8"),
        headers={"Title": title, "Tags": "microscope", "Priority": "default"},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.status == 200


def default_state_path(base):
    return Path(base) / "data" / "trials_state.json"


def load_state(path):
    path = Path(path)
    if not path.exists():
        return {}
    return json.loads(path.read_text())


def save_state(state, path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2, sort_keys=True) + NL)


def diff(current, state):
    """Compare normalized studies against stored state.

    Returns (events, new_state). Events are dicts with kind in
    {new, status_changed} and are sorted newest-relevance first.
    """
    events = []
    new_state = {}
    for study in current:
        nct = study["nct_id"]
        new_state[nct] = {
            "status": study.get("status", ""),
            "title": study.get("title", ""),
        }
        previous = state.get(nct)
        if previous is None:
            events.append({
                "kind": "new",
                "nct_id": nct,
                "title": study.get("title", ""),
                "status": study.get("status", ""),
            })
        elif previous.get("status") != study.get("status"):
            events.append({
                "kind": "status_changed",
                "nct_id": nct,
                "title": study.get("title", ""),
                "old_status": previous.get("status", ""),
                "status": study.get("status", ""),
            })
    # Trials that left the recruiting set entirely.
    for nct, previous in sorted(state.items()):
        if nct not in new_state and previous.get("status") in (
            "RECRUITING",
            "ENROLLING_BY_INVITATION",
        ):
            events.append({
                "kind": "stopped",
                "nct_id": nct,
                "title": previous.get("title", ""),
                "old_status": previous.get("status", ""),
            })
    return events, new_state


def render_events(events):
    if not events:
        return "No changes since the last scan."
    lines = []
    for event in events:
        if event["kind"] == "new":
            lines.append(f"NEW: {event['nct_id']} {event['title']}")
        elif event["kind"] == "status_changed":
            lines.append(
                f"STATUS: {event['nct_id']} {event['old_status']} -> {event['status']}"
                f" {event['title']}"
            )
        else:
            lines.append(f"LEFT RECRUITING: {event['nct_id']} {event['title']}")
        lines.append(f"  https://clinicaltrials.gov/study/{event['nct_id']}")
    return NL.join(lines)
