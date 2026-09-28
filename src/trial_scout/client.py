"""ClinicalTrials.gov v2 API client. stdlib only, no API key required.

Docs: https://clinicaltrials.gov/data-api/api
"""

import json
import urllib.parse
import urllib.request

BASE = "https://clinicaltrials.gov/api/v2/studies"

FIELDS = "|".join([
    "NCTId",
    "BriefTitle",
    "OverallStatus",
    "BriefSummary",
    "Condition",
    "Phase",
    "EnrollmentCount",
    "MinimumAge",
    "MaximumAge",
    "Sex",
    "EligibilityCriteria",
    "LocationFacility",
    "LocationCity",
    "LocationState",
    "LocationGeoPoint",
    "StartDate",
])

STATUSES = ["RECRUITING", "ENROLLING_BY_INVITATION"]


def _get(url):
    request = urllib.request.Request(url, headers={"User-Agent": "trial-scout/0.1"})
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.loads(response.read().decode("utf-8"))


def _first(module, key, default=""):
    value = module.get(key) if module else None
    if isinstance(value, list):
        return value[0] if value else default
    return value if value is not None else default


def normalize_study(study):
    """Flatten one v2 API study into the shape the scorer and monitor use."""
    p = study.get("protocolSection", {})
    ident = p.get("identificationModule", {})
    status_m = p.get("statusModule", {})
    design = p.get("designModule", {})
    conditions = p.get("conditionsModule", {})
    eligibility = p.get("eligibilityModule", {})
    contacts = p.get("contactsLocationsModule", {})
    interventions = p.get("armsInterventionsModule", {})

    locations = []
    for loc in contacts.get("locations", []) or []:
        geo = loc.get("geoPoint") or {}
        locations.append({
            "facility": loc.get("facility", ""),
            "city": loc.get("city", ""),
            "state": loc.get("state", ""),
            "lat": geo.get("lat"),
            "lon": geo.get("lon"),
        })

    intervention_types = sorted({
        (item.get("type") or "").strip()
        for item in (interventions.get("interventions") or [])
        if item.get("type")
    })

    phases = design.get("phases") or []
    return {
        "nct_id": ident.get("nctId", ""),
        "title": ident.get("briefTitle", ""),
        "status": status_m.get("overallStatus", ""),
        "summary": ident and (p.get("descriptionModule", {}) or {}).get("briefSummary", ""),
        "conditions": conditions.get("conditions") or [],
        "phases": phases,
        "intervention_types": intervention_types,
        "enrollment": design.get("enrollmentInfo", {}).get("count"),
        "min_age": eligibility.get("minimumAge", ""),
        "max_age": eligibility.get("maximumAge", ""),
        "sex": eligibility.get("sex", "ALL"),
        "criteria": eligibility.get("eligibilityCriteria", "") or "",
        "locations": locations,
    }


def is_relevant(study):
    """API query.cond matches trials that merely allow PD patients as a
    comorbidity (e.g. an oncology trial). Keep trials where the title
    mentions Parkinson, or every listed condition is Parkinson-related."""
    conditions = [c.lower() for c in (study.get("conditions") or [])]
    if "parkinson" in study.get("title", "").lower():
        return True
    return bool(conditions) and all(
        "parkinson" in c or c.strip() in ("pd", "idiopathic pd") for c in conditions
    )


def fetch_parkinson_studies(statuses=None, max_pages=10, fetch_fn=None):
    """Yield normalized, PD-relevant studies across the configured statuses."""
    fetch_fn = fetch_fn or _get
    statuses = statuses or STATUSES
    seen = set()
    for status in statuses:
        page_token = None
        for _ in range(max_pages):
            params = {
                "query.cond": "Parkinson Disease",
                "filter.overallStatus": status,
                "fields": FIELDS,
                "pageSize": "100",
            }
            if page_token:
                params["pageToken"] = page_token
            url = BASE + "?" + urllib.parse.urlencode(params)
            payload = fetch_fn(url)
            for study in payload.get("studies", []):
                normalized = normalize_study(study)
                nct = normalized["nct_id"]
                if nct and nct not in seen and is_relevant(normalized):
                    seen.add(nct)
                    yield normalized
            page_token = (payload.get("nextPageToken") or "").strip()
            if not page_token:
                break


def fetch_study(nct_id, fetch_fn=None):
    fetch_fn = fetch_fn or _get
    url = BASE + "/" + urllib.parse.quote(nct_id)
    return normalize_study(fetch_fn(url))
