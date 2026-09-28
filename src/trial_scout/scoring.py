"""Transparent, rule-based viability scoring.

Every verdict carries its reasons. This is decision support for a family
conversation and a call to a trial site. It is not eligibility determination.
"""

import math
import re

from trial_scout.profile import TRAVEL_OPTIONS, coords_for

NL = chr(10)

DBS_PATTERN = re.compile(
    r"deep[ -]brain[ -]stimulation|(?<![a-z])dbs(?![a-z])", re.IGNORECASE
)

# Trial phases that test a treatment rather than observe the disease.
TREATMENT_PHASES = {"EARLY_PHASE1", "PHASE1", "PHASE2", "PHASE3", "PHASE4"}

ADJACENT_STATE_HINTS = ("MS", "TN", "LA", "AL", "AR")


def haversine_miles(lat1, lon1, lat2, lon2):
    radius = 3958.8
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lon2 - lon1)
    a = (
        math.sin(dphi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(dlmb / 2) ** 2
    )
    return 2 * radius * math.asin(math.sqrt(a))


def _age_years(text):
    if not text:
        return None
    parts = text.strip().split()
    try:
        value = float(parts[0])
    except (ValueError, IndexError):
        return None
    unit = parts[1].lower() if len(parts) > 1 else "years"
    if unit.startswith("month"):
        return value / 12.0
    if unit.startswith("week"):
        return value / 52.0
    if unit.startswith("day"):
        return value / 365.0
    return value


def dbs_hits(criteria):
    """Lines of the criteria text that mention DBS, with a hint of context."""
    hits = []
    in_exclusion = False
    for line in criteria.split(NL):
        stripped = line.strip().lower()
        if stripped.startswith("exclusion"):
            in_exclusion = True
        elif stripped.startswith("inclusion"):
            in_exclusion = False
        if DBS_PATTERN.search(line):
            hits.append({
                "line": line.strip(),
                "in_exclusion": in_exclusion or "exclusion" in stripped,
            })
    return hits


def nearest_site(profile, locations):
    home = coords_for(profile)
    if home is None:
        return None
    best = None
    for loc in locations:
        if loc.get("lat") is None or loc.get("lon") is None:
            continue
        miles = haversine_miles(home[0], home[1], loc["lat"], loc["lon"])
        if best is None or miles < best["miles"]:
            best = {
                "facility": loc.get("facility", ""),
                "city": loc.get("city", ""),
                "state": loc.get("state", ""),
                "miles": miles,
            }
    return best


def is_treatment_trial(study):
    if study.get("phases") and any(ph in TREATMENT_PHASES for ph in study["phases"]):
        return True
    types = study.get("intervention_types") or []
    return any(t in ("Drug", "Biological", "Device", "Genetic", "Cell") for t in types)


def score_trial(profile, study):
    """Return a verdict dict. Rules in order, first hit wins on verdict."""
    reasons = []
    age = profile.get("age", 0)

    # Age window
    min_age = _age_years(study.get("min_age"))
    max_age = _age_years(study.get("max_age"))
    if age and (max_age is not None and age > max_age):
        reasons.append(("negative", f"Age {age} is above the maximum {study.get('max_age')}"))
    elif age and (min_age is not None and age < min_age):
        reasons.append(("negative", f"Age {age} is below the minimum {study.get('min_age')}"))
    else:
        window = f"{study.get('min_age') or 'any'} to {study.get('max_age') or 'any'}"
        reasons.append(("info", f"Age window: {window}"))

    # Distance
    site = nearest_site(profile, study.get("locations", []))
    radius = TRAVEL_OPTIONS.get(profile.get("travel", "half_day"), 150)
    if site is None:
        reasons.append(("negative", "No recruiting site location with coordinates found"))
    else:
        where = f"{site['city']}, {site['state']} ({site['miles']:.0f} mi)"
        if site["miles"] <= radius:
            reasons.append(("positive", f"Nearest site: {where}"))
        else:
            reasons.append(("negative", f"Nearest site: {where} - beyond travel radius"))

    # DBS conflicts
    hits = dbs_hits(study.get("criteria", ""))
    dbs = profile.get("dbs", "none")
    exclusion_hits = [h for h in hits if h["in_exclusion"]]
    if dbs == "implanted" and exclusion_hits:
        reasons.append(("negative", "Likely excluded: DBS implant mentioned in exclusion criteria"))
        reasons.append(("info", "Criteria line: " + exclusion_hits[0]["line"][:200]))
    elif dbs == "considering" and exclusion_hits:
        reasons.append(("negative", "Conflict risk: getting DBS during the study would likely violate exclusion criteria"))
        reasons.append(("info", "Criteria line: " + exclusion_hits[0]["line"][:200]))
    elif dbs == "implanted":
        reasons.append(("info", "DBS implant not mentioned in the exclusion text, but confirm with the site"))
    elif dbs == "considering":
        reasons.append(("info", "No DBS exclusion text found; if he proceeds with DBS later this trial would likely end"))

    # Treatment vs observational
    treatment = is_treatment_trial(study)
    if treatment:
        phases = ", ".join(study.get("phases") or ["device/other"])
        reasons.append(("info", f"Interventional ({phases})"))
    elif profile.get("willing_observational") == "no":
        reasons.append(("negative", "Observational study and profile says treatment-only"))
    else:
        reasons.append(("info", "Observational study (no experimental treatment)"))

    # Verdict: first rule that fires wins.
    hard_negatives = [r for r in reasons if r[0] == "negative"]
    if any("Likely excluded" in r[1] for r in reasons):
        verdict = "likely-excluded"
    elif any("Conflict risk" in r[1] for r in reasons):
        verdict = "dbs-conflict"
    elif hard_negatives:
        verdict = "watch"
    elif site is not None:
        verdict = "candidate"
    else:
        verdict = "needs-verification"

    return {
        "nct_id": study.get("nct_id", ""),
        "title": study.get("title", ""),
        "status": study.get("status", ""),
        "verdict": verdict,
        "nearest_site": site,
        "reasons": [{"kind": kind, "text": text} for kind, text in reasons],
        "url": "https://clinicaltrials.gov/study/" + study.get("nct_id", ""),
    }


VERDICT_ORDER = ["candidate", "dbs-conflict", "needs-verification", "watch", "likely-excluded"]


def rank(scored):
    return sorted(
        scored,
        key=lambda s: (
            VERDICT_ORDER.index(s["verdict"]),
            s["nearest_site"]["miles"] if s.get("nearest_site") else 99999,
        ),
    )


def render_report(profile, scored):
    lines = []
    lines.append("Trial Scout report")
    lines.append("=" * 60)
    lines.append("Decision support only. Not medical advice. A trial site, not")
    lines.append("this report, determines actual eligibility.")
    lines.append("")
    for item in rank(scored):
        lines.append(f"[{item['verdict'].upper()}] {item['nct_id']}  {item['title']}")
        if item.get("nearest_site"):
            site = item["nearest_site"]
            lines.append(f"  site: {site['city']}, {site['state']} ({site['miles']:.0f} mi)")
        lines.append(f"  {item['url']}")
        for reason in item["reasons"]:
            mark = {"positive": "+", "negative": "-", "info": " "}[reason["kind"]]
            lines.append(f"  {mark} {reason['text']}")
        lines.append("")
    return NL.join(lines)
