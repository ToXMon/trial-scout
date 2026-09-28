"""Offline tests for Trial Scout: scoring rules, monitor diff, profile I/O."""

import json

from trial_scout import monitor, profile as profile_mod, scoring


def make_study(**overrides):
    study = {
        "nct_id": "NCT00000001",
        "title": "A phase 2 trial of wonderdrug in Parkinson's",
        "status": "RECRUITING",
        "summary": "summary",
        "conditions": ["Parkinson Disease"],
        "phases": ["PHASE2"],
        "intervention_types": ["Drug"],
        "enrollment": 200,
        "min_age": "40 Years",
        "max_age": "80 Years",
        "sex": "ALL",
        "criteria": (
            "Inclusion Criteria:" + chr(10)
            + "  - Diagnosis of Parkinson disease" + chr(10)
            + "Exclusion Criteria:" + chr(10)
            + "  - Prior deep brain stimulation surgery" + chr(10)
        ),
        "locations": [
            {"facility": "UMMC", "city": "Jackson", "state": "MS",
             "lat": 32.2988, "lon": -90.1848},
            {"facility": "Far Site", "city": "Boston", "state": "MA",
             "lat": 42.3601, "lon": -71.0589},
        ],
    }
    study.update(overrides)
    return study


PROFILE = {
    "age": 70,
    "dbs": "considering",
    "stage": "moderate",
    "levodopa_years": 4,
    "home_city": "jackson_ms",
    "travel": "full_day",
    "willing_observational": "yes",
}


def test_dbs_exclusion_is_detected_and_flags_conflict():
    scored = scoring.score_trial(PROFILE, make_study())
    assert scored["verdict"] == "dbs-conflict"
    texts = [r["text"] for r in scored["reasons"]]
    assert any("Conflict risk" in t for t in texts)
    assert any("Jackson, MS" in t for t in texts)


def test_implanted_dbs_gives_likely_excluded():
    prof = dict(PROFILE, dbs="implanted")
    scored = scoring.score_trial(prof, make_study())
    assert scored["verdict"] == "likely-excluded"


def test_no_dbs_mention_leaves_candidate():
    study = make_study(criteria="Inclusion Criteria:" + chr(10) + "  - PD diagnosis")
    scored = scoring.score_trial(PROFILE, study)
    assert scored["verdict"] == "candidate"


def test_age_and_distance_rules_fire():
    prof = dict(PROFILE, dbs="none")
    scored = scoring.score_trial(dict(prof, age=85), make_study())
    assert scored["verdict"] == "watch"
    scored = scoring.score_trial(
        dict(prof, travel="same_city"),
        make_study(locations=[make_study()["locations"][1]],
                   criteria="Inclusion Criteria: none"),
    )
    assert scored["verdict"] == "watch"
    texts = [r["text"] for r in scored["reasons"]]
    assert any("beyond travel radius" in t for t in texts)


def test_rank_puts_candidates_first():
    a = scoring.score_trial(PROFILE, make_study(criteria="Inclusion Criteria: none"))
    b = scoring.score_trial(PROFILE, make_study(nct_id="NCT00000009"))
    ranked = scoring.rank([b, a])
    assert ranked[0]["verdict"] == "candidate"
    assert ranked[0]["nct_id"] != ranked[1]["nct_id"]


def test_monitor_diff_reports_new_and_status_changes(tmp_path):
    state_path = tmp_path / "state.json"
    first = [make_study(), make_study(nct_id="NCT00000002", title="Second")]
    events, state = monitor.diff(first, {})
    assert [e["kind"] for e in events] == ["new", "new"]
    monitor.save_state(state, state_path)

    second = [
        make_study(),
        make_study(nct_id="NCT00000002", title="Second", status="ACTIVE_NOT_RECRUITING"),
    ]
    events, _ = monitor.diff(second, monitor.load_state(state_path))
    kinds = {e["nct_id"]: e["kind"] for e in events}
    assert kinds["NCT00000002"] == "status_changed"
    assert "NCT00000001" not in kinds
    text = monitor.render_events(events)
    assert "STATUS:" in text


def test_monitor_flags_trials_that_left_recruiting(tmp_path):
    state_path = tmp_path / "state.json"
    first = [make_study(), make_study(nct_id="NCT00000002")]
    _, state = monitor.diff(first, {})
    monitor.save_state(state, state_path)
    events, _ = monitor.diff([make_study()], monitor.load_state(state_path))
    assert events[0]["kind"] == "stopped"


def test_profile_ask_and_roundtrip(tmp_path):
    answers = ["72", "2", "2", "5", "13", "2", "1", ""]
    got = profile_mod.ask(profile_mod.QUESTIONS, input_fn=lambda _: answers.pop(0),
                          print_fn=lambda *_: None)
    assert got["dbs"] == "considering"
    assert got["home_city"] == "natchez_ms"
    path = profile_mod.save(got, tmp_path / "p.json")
    loaded = profile_mod.load(path)
    assert loaded == json.loads(json.dumps(got))


def test_relevance_filter_drops_comorbidity_mentions():
    from trial_scout import client
    cancer = make_study(
        title="Cervical cancer trial allowing PD patients",
        conditions=["Cervical Cancer", "Parkinson Disease"],
    )
    assert client.is_relevant(cancer) is False
    assert client.is_relevant(make_study()) is True
    # Bare "PD" abbreviation in a title is out of scope for the filter.


def test_client_normalize_shape():
    raw = {
        "protocolSection": {
            "identificationModule": {"nctId": "NCT00000001", "briefTitle": "T"},
            "statusModule": {"overallStatus": "RECRUITING"},
            "descriptionModule": {"briefSummary": "s"},
            "designModule": {"phases": ["PHASE3"], "enrollmentInfo": {"count": 10}},
            "conditionsModule": {"conditions": ["Parkinson Disease"]},
            "eligibilityModule": {"minimumAge": "40 Years", "sex": "ALL",
                                  "eligibilityCriteria": "Exclusion Criteria: DBS"},
            "contactsLocationsModule": {"locations": [{
                "facility": "F", "city": "Jackson", "state": "MS",
                "geoPoint": {"lat": 32.3, "lon": -90.2},
            }]},
        }
    }
    from trial_scout import client
    study = client.normalize_study(raw)
    assert study["nct_id"] == "NCT00000001"
    assert study["locations"][0]["lat"] == 32.3
    assert scoring.dbs_hits(study["criteria"])[0]["in_exclusion"] is True
