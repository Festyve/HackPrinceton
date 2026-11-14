"""The two temperature records of a cold-chain case as a read-only evidence view. Offline, no model."""

from __future__ import annotations

import json
import time
from dataclasses import replace
from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from alibi.api.app import create_app
from alibi.config import load_settings
from alibi.episode import load_answer_key
from alibi.orchestrator import Orchestrator

URL = "/api/cases/{}/evidence/sensor-streams"


@pytest.fixture()
def env(tmp_path):
    settings = replace(load_settings({}, dotenv=False), runs_dir=tmp_path / "runs", sealed_dir=tmp_path / "sealed")
    orch = Orchestrator(settings, pace_s=0.0)
    return orch, TestClient(create_app(settings, orch))


def _case(c, preset):
    cid = c.post("/api/cases", json={"preset_id": preset, "runner": "deterministic"}).json()["case"]["case_id"]
    end = time.time() + 60
    while time.time() < end:
        v = c.get(f"/api/cases/{cid}").json()
        if v["case"]["state"] in ("awaiting_review", "failed"):
            assert v["case"]["state"] == "awaiting_review", v["case"]
            return cid, v
        time.sleep(0.05)
    raise AssertionError(cid)


def _series(view, key):
    return next(s for s in view["series"] if s["key"] == key)


def _t(s):
    return datetime.fromisoformat(s)


def test_the_view_shows_both_records_and_where_they_disagree(env):
    orch, c = env
    cid, case = _case(c, "cold-chain")
    r = c.get(URL.format(cid))
    assert r.status_code == 200, r.text
    view = r.json()
    assert view["applicable"] and view["status"] == "discrepancy_unexplained"
    assert "no model inference" in view["produced_by"]
    stored, ref = _series(view, "stored"), _series(view, "reference")
    assert stored["present"] and ref["present"]
    # the trust statement of each record comes from the manifest, not from this view
    assert stored["tamper_exposure"] == "host_local_writable" and ref["tamper_exposure"] == "independent_witness"
    assert stored["total_points"] == len(stored["points"]) > ref["total_points"] == len(ref["points"]) > 20
    assert not stored["truncated"] and not ref["truncated"]

    # every point is a record of this bundle and opens the line it came from
    sample = [p["event_id"] for p in stored["points"][:20] + ref["points"][:20]]
    got = c.get(f"/api/cases/{cid}/evidence/events", params={"ids": ",".join(sample)}).json()
    assert got["missing"] == []
    by_id = {e["id"]: e for e in got["events"]}
    for p in stored["points"][:20] + ref["points"][:20]:
        assert by_id[p["event_id"]]["attrs"]["temp_c"] == p["temp_c"] and by_id[p["event_id"]]["ts"] == p["ts"]
    assert {by_id[p["event_id"]]["source"] for p in stored["points"][:20]} == {"sensor"}
    assert {by_id[p["event_id"]]["source"] for p in ref["points"][:20]} == {"reference"}

    # the unexplained disagreement: the reference left the permitted range while the stored record stayed inside it
    lo, hi = view["permitted_range_c"]
    unexplained = [d for d in view["discrepancies"] if d["classification"] == "unexplained"]
    assert len(unexplained) == 1
    d = unexplained[0]
    assert d["reference_out_of_range"] and not d["local_out_of_range"]
    in_window = lambda pts: [p for p in pts if _t(d["start"]) <= _t(p["ts"]) <= _t(d["end"])]  # noqa: E731
    assert in_window(ref["points"]) and all(not lo <= p["temp_c"] <= hi for p in in_window(ref["points"]))
    assert in_window(stored["points"]) and all(lo <= p["temp_c"] <= hi for p in in_window(stored["points"]))
    assert set(d["reference_event_ids"]) <= {p["event_id"] for p in ref["points"]}
    # a stated maintenance window is shown, and the disagreement inside it is explained by it
    assert view["maintenance_windows"] and view["maintenance_windows"][0]["id"]
    assert any(x["classification"] == "explained_maintenance" for x in view["discrepancies"])
    # the view states what it cannot show
    assert any("does not show which one was changed" in x for x in view["limits"])

    # nothing sealed is in it
    key = load_answer_key(orch._paths(cid))
    text = json.dumps(view)
    for secret in (key.canary, "coldchain_falsified", "variant", "ground_truth", "step_results", "adversary"):
        assert secret not in text, secret


def test_a_real_excursion_that_was_honestly_recorded_shows_two_records_that_agree(env):
    _, c = env
    cid, _ = _case(c, "cold-chain-control")
    view = c.get(URL.format(cid)).json()
    assert view["applicable"] and view["status"] != "discrepancy_unexplained"
    assert not [d for d in view["discrepancies"] if d["classification"] == "unexplained"]
    assert view["excursions"] and all(e["local_agrees"] for e in view["excursions"])
    lo, hi = view["permitted_range_c"]
    assert any(not lo <= p["temp_c"] <= hi for p in _series(view, "stored")["points"])  # the stored record shows the warming too


def test_a_case_without_a_cold_chain_policy_has_nothing_to_compare(env):
    _, c = env
    cid, _ = _case(c, "hero-coverup")
    view = c.get(URL.format(cid)).json()
    assert view == {"applicable": False, "status": "not_applicable", "series": [], "status_reason": view["status_reason"]}
    assert "no cold-chain policy" in view["status_reason"]
    assert c.get("/api/runtime").json()["capabilities"]["sensor_streams"]["endpoint"] is True
    assert c.get(URL.format("case-does-not-exist")).status_code == 404


def test_a_withheld_reference_logger_cannot_be_seen_through_the_view(env):
    _, c = env
    cid, case = _case(c, "cold-chain")
    parent = c.get(URL.format(cid)).json()
    ref_ids = {p["event_id"] for p in _series(parent, "reference")["points"]}
    withheld = [s["source_id"] for s in case["manifest"]["sources"] if s["source"] == "reference"]
    made = c.post(f"/api/cases/{cid}/source-experiments", json={"excluded_source_ids": withheld, "client_token": "no-ref"})
    assert made.status_code == 200, made.text
    child = made.json()["child_case_id"]
    view = c.get(URL.format(child)).json()
    assert view["applicable"] and view["status"] == "not_assessable"
    assert "reference logger" in view["status_reason"] and view["coverage_limits"]
    ref, stored = _series(view, "reference"), _series(view, "stored")
    assert not ref["present"] and ref["points"] == [] and ref["artifacts"] == [] and ref["total_points"] == 0
    assert stored["present"] and stored["points"]
    assert view["discrepancies"] == [] and view["excursions"] == []  # unknown, not "no disagreement"
    text = json.dumps(view)
    assert not [i for i in ref_ids if i in text]
    # the parent is unchanged
    assert c.get(URL.format(cid)).json() == parent
