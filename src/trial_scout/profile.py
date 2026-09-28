"""Interactive profile for the person we are scouting trials for.

Everything is a plain JSON file under data/ (gitignored). No medical advice
here: the questions exist so the scorer can apply transparent rules.
"""

import json
from pathlib import Path

NL = chr(10)

# Coords keep the tool dependency-free: no geocoding service, no API key.
CITIES = {
    "jackson_ms": (32.2988, -90.1848),
    "gulfport_ms": (30.3674, -89.0928),
    "southaven_ms": (34.9889, -90.0126),
    "hattiesburg_ms": (31.3271, -89.2903),
    "biloxi_ms": (30.3960, -88.8853),
    "meridian_ms": (32.3643, -88.7037),
    "tupelo_ms": (34.2576, -88.7034),
    "greenville_ms": (33.4101, -90.9205),
    "oxford_ms": (34.3665, -89.5193),
    "starkville_ms": (33.4504, -88.7996),
    "columbus_ms": (33.4957, -88.4193),
    "vicksburg_ms": (32.3526, -90.8779),
    "natchez_ms": (31.5489, -91.4032),
    "laurel_ms": (31.6941, -89.1306),
    "memphis_tn": (35.1495, -90.0490),
    "new_orleans_la": (29.9511, -90.0715),
    "baton_rouge_la": (30.4515, -91.1871),
    "shreveport_la": (32.5252, -93.7502),
    "birmingham_al": (33.5186, -86.8104),
    "mobile_al": (30.6954, -88.0399),
    "little_rock_ar": (34.7465, -92.2896),
    "huntsville_al": (34.7304, -86.5861),
    "houston_tx": (29.7604, -95.3698),
}

CITY_LABELS = {
    "jackson_ms": "Jackson, MS",
    "gulfport_ms": "Gulfport, MS",
    "southaven_ms": "Southaven, MS",
    "hattiesburg_ms": "Hattiesburg, MS",
    "biloxi_ms": "Biloxi, MS",
    "meridian_ms": "Meridian, MS",
    "tupelo_ms": "Tupelo, MS",
    "greenville_ms": "Greenville, MS",
    "oxford_ms": "Oxford, MS",
    "starkville_ms": "Starkville, MS",
    "columbus_ms": "Columbus, MS",
    "vicksburg_ms": "Vicksburg, MS",
    "natchez_ms": "Natchez, MS",
    "laurel_ms": "Laurel, MS",
    "memphis_tn": "Memphis, TN",
    "new_orleans_la": "New Orleans, LA",
    "baton_rouge_la": "Baton Rouge, LA",
    "shreveport_la": "Shreveport, LA",
    "birmingham_al": "Birmingham, AL",
    "mobile_al": "Mobile, AL",
    "little_rock_ar": "Little Rock, AR",
    "huntsville_al": "Huntsville, AL",
    "houston_tx": "Houston, TX",
    "other": "Somewhere else (enter lat,lon manually)",
}

TRAVEL_OPTIONS = {
    "same_city": 50,
    "half_day": 150,
    "full_day": 300,
    "any": 100000,
}

TRAVEL_LABELS = {
    "same_city": "Same city / about an hour (50 mi)",
    "half_day": "Up to about 2.5 hours drive (150 mi)",
    "full_day": "Up to about 5 hours drive (300 mi)",
    "any": "Anywhere in the US (would fly)",
}

QUESTIONS = [
    (
        "age",
        "How old is he (whole years)?",
        "int",
        None,
    ),
    (
        "dbs",
        "Deep brain stimulation status? This matters a lot: many "
        "disease-modifying trials exclude people with a DBS implant, and some "
        "exclude people who might get one during the study.",
        "choice",
        [
            ("none", "No implant, not considering it"),
            ("considering", "Considering it (may get DBS in the next year or two)"),
            ("implanted", "Already has a DBS implant"),
        ],
    ),
    (
        "stage",
        "Where would you place his disease today?",
        "choice",
        [
            ("early", "Diagnosed within the last few years, still independent"),
            ("moderate", "Symptoms affect daily life, meds are doing real work"),
            ("advanced", "Significant daily-care needs or motor fluctuations"),
            ("unsure", "Not sure"),
        ],
    ),
    (
        "levodopa_years",
        "Roughly how many years on levodopa/carbidopa? (many trials cap this; "
        "0 if not on it, -1 if unsure)",
        "int",
        None,
    ),
    (
        "home_city",
        "Where does he live (choose the closest option)?",
        "choice",
        [(key, CITY_LABELS[key]) for key in CITIES] + [("other", CITY_LABELS["other"])],
    ),
    (
        "travel",
        "How far is he realistically willing to travel for visits?",
        "choice",
        [(key, TRAVEL_LABELS[key]) for key in TRAVEL_OPTIONS],
    ),
    (
        "willing_observational",
        "Include observational / registry studies (no drug, just visits and "
        "data) in the reports?",
        "choice",
        [("yes", "Yes"), ("no", "Trials with treatment only")],
    ),
    (
        "email",
        "Email address for digest summaries (optional, just stored in the "
        "profile; enter nothing to skip)",
        "text",
        None,
    ),
]


def ask(questions, input_fn=input, print_fn=print):
    """Run the questionnaire. input_fn/print_fn are injectable for tests."""
    answers = {}
    for key, prompt, kind, options in questions:
        print_fn("")
        print_fn(prompt)
        if kind == "choice":
            for i, (value, label) in enumerate(options, start=1):
                print_fn(f"  {i}. {label}")
            while True:
                raw = input_fn("Choice number (or blank for 1): ").strip()
                if raw == "":
                    raw = "1"
                if raw.isdigit() and 1 <= int(raw) <= len(options):
                    answers[key] = options[int(raw) - 1][0]
                    break
                print_fn("  Pick a number from the list.")
        elif kind == "int":
            while True:
                raw = input_fn("Answer: ").strip() or "0"
                try:
                    answers[key] = int(raw)
                    break
                except ValueError:
                    print_fn("  Whole numbers only.")
        else:
            raw = input_fn("Answer (blank to skip): ").strip()
            answers[key] = raw
    if answers.get("home_city") == "other":
        print_fn("")
        print_fn("Enter latitude,longitude in decimal degrees (e.g. 31.32,-89.29).")
        while True:
            raw = input_fn("Coords: ").strip()
            try:
                lat_s, lon_s = raw.split(",")
                lat, lon = float(lat_s.strip()), float(lon_s.strip())
                answers["home_coords"] = [lat, lon]
                break
            except ValueError:
                print_fn("  Format: 31.32,-89.29")
    return answers


def coords_for(profile):
    if "home_coords" in profile:
        return tuple(profile["home_coords"])
    key = profile.get("home_city")
    return CITIES.get(key)


def default_profile_path(base):
    return Path(base) / "data" / "trial_profile.json"


def save(profile, path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(profile, indent=2) + NL)
    return path


def load(path):
    return json.loads(Path(path).read_text())
