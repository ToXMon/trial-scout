# trial-scout

Monitors ClinicalTrials.gov for recruiting Parkinson's disease trials and
scores them against one person's situation (age, DBS status, location, travel
radius) with transparent, rule-based reasons.

**Decision support only. Not medical advice. A trial site, not this tool,
determines actual eligibility.**

## Commands

- `trial-scout profile` - interactive questionnaire, saves a local profile
- `trial-scout scan` - fetch, score, and report; `--json` for machine output
- `trial-scout watch --interval-minutes 360` - rescan loop
- `trial-scout show NCT12345678` - print one trial's criteria
- `trial-scout serve` - HTTP API + background scan loop for server deploys

Server mode env vars: `TRIAL_PROFILE_JSON`, `TRIAL_SCOUT_NTFY_TOPIC`
(push diffs to ntfy.sh), `TRIAL_SCOUT_STATE_PATH`,
`TRIAL_SCOUT_INTERVAL_MINUTES`. Endpoints: `/` (latest scan JSON),
`/healthz`.

Runs on Akash; see the parent project for the deployment SDL.

Co-Authored-By line not needed; generated as part of the
parkinsons-discovery project by AdaL.
