"""CLI: trial-scout profile | scan | watch | show"""

import argparse
import sys
import time
from pathlib import Path

from trial_scout import client, monitor, profile as profile_mod, scoring

REPO_ROOT = Path(__file__).resolve().parents[2]


def _paths(args):
    profile_path = Path(args.profile) if args.profile else profile_mod.default_profile_path(REPO_ROOT)
    state_path = Path(args.state) if args.state else monitor.default_state_path(REPO_ROOT)
    return profile_path, state_path


def cmd_profile(args):
    answers = profile_mod.ask(profile_mod.QUESTIONS)
    path = profile_mod.save(answers, _paths(args)[0])
    print("")
    print("Profile saved to " + str(path))
    print("Next: trial-scout scan")
    return 0


def cmd_scan(args):
    profile_path, state_path = _paths(args)
    if not profile_path.exists():
        print("No profile found. Run: trial-scout profile", file=sys.stderr)
        return 1
    prof = profile_mod.load(profile_path)
    print("Fetching recruiting Parkinson's trials from ClinicalTrials.gov...")
    studies = list(client.fetch_parkinson_studies(max_pages=args.max_pages))
    print(f"Fetched {len(studies)} recruiting studies. Scoring...")
    scored = [scoring.score_trial(prof, study) for study in studies]

    events, new_state = monitor.diff(studies, monitor.load_state(state_path))
    monitor.save_state(new_state, state_path)

    if args.json:
        import json
        print(json.dumps({"trials": scored, "events": events}, indent=2))
        return 0

    if not args.no_events:
        print("")
        print("Changes since last scan:")
        print(monitor.render_events(events))
        print("")

    if args.report_path:
        report = scoring.render_report(prof, scored)
        Path(args.report_path).write_text(report + chr(10))
        print("Full report written to " + args.report_path)
    else:
        print(scoring.render_report(prof, scored))
    return 0


def cmd_watch(args):
    profile_path, state_path = _paths(args)
    while True:
        code = cmd_scan(argparse.Namespace(
            profile=str(profile_path), state=str(state_path),
            max_pages=args.max_pages, json=False,
            no_events=False, report_path=args.report_path,
        ))
        if code != 0:
            return code
        if args.once:
            return 0
        print(f"Sleeping {args.interval_minutes} minutes (Ctrl-C to stop)...")
        time.sleep(args.interval_minutes * 60)


def cmd_show(args):
    study = client.fetch_study(args.nct_id)
    print(study["nct_id"] + "  " + study["title"])
    print("status: " + study["status"] + "   phases: " + ", ".join(study["phases"] or ["n/a"]))
    print("ages: " + str(study["min_age"] or "any") + " to " + str(study["max_age"] or "any"))
    print("")
    print(study["criteria"] or "(no criteria text returned)")
    return 0


def cmd_serve(args):
    import os

    from trial_scout import serve as serve_mod

    raw = os.environ.get("TRIAL_PROFILE_JSON")
    if raw:
        import json

        prof = json.loads(raw)
    else:
        profile_path, _ = _paths(args)
        if not profile_path.exists():
            print("No profile: set TRIAL_PROFILE_JSON or run trial-scout profile",
                  file=sys.stderr)
            return 1
        prof = profile_mod.load(profile_path)
    state_path = Path(os.environ.get("TRIAL_SCOUT_STATE_PATH", "data/trials_state.json"))
    topic = os.environ.get("TRIAL_SCOUT_NTFY_TOPIC") or None
    interval = int(os.environ.get("TRIAL_SCOUT_INTERVAL_MINUTES", str(args.interval_minutes)))
    print(f"Serving on {args.host}:{args.port}; rescan every {interval} min")
    serve_mod.serve(args.host, args.port, prof, state_path, interval, topic)
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="trial-scout",
        description=(
            "Monitor Parkinson's clinical trials for one person's situation. "
            "Decision support only, not medical advice."
        ),
    )
    parser.add_argument("--profile", default=None, help="Path to profile JSON")
    parser.add_argument("--state", default=None, help="Path to state JSON")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("profile", help="Interactive questionnaire to build the profile")

    scan = sub.add_parser("scan", help="Fetch, score, and diff trials")
    scan.add_argument("--json", action="store_true", help="Emit JSON instead of text")
    scan.add_argument("--max-pages", type=int, default=10)
    scan.add_argument("--no-events", action="store_true", help="Skip the diff section")
    scan.add_argument("--report-path", default=None, help="Write full report to a file")

    watch = sub.add_parser("watch", help="Rescan on an interval (or use cron + scan)")
    watch.add_argument("--interval-minutes", type=int, default=360)
    watch.add_argument("--once", action="store_true", help="Single pass, then exit")
    watch.add_argument("--max-pages", type=int, default=10)
    watch.add_argument("--report-path", default=None)

    show = sub.add_parser("show", help="Print one trial's full criteria")
    show.add_argument("nct_id")

    serve = sub.add_parser("serve", help="HTTP API + background scan loop")
    serve.add_argument("--host", default="0.0.0.0")
    serve.add_argument("--port", type=int, default=8080)
    serve.add_argument("--interval-minutes", type=int, default=1440)

    args = parser.parse_args(argv)
    commands = {
        "profile": cmd_profile,
        "scan": cmd_scan,
        "watch": cmd_watch,
        "show": cmd_show,
        "serve": cmd_serve,
    }
    return commands[args.command](args)


if __name__ == "__main__":
    raise SystemExit(main())
