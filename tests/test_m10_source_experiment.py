"""Source-removal experiment (docs/next-run/CONTINUE.md section 2, "Evidence-removal experiment"). Offline."""

from __future__ import annotations

import json
import time
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

from alibi import source_experiment
from alibi.agents.tools import CaseToolbox
from alibi.api.app import create_app
from alibi.config import load_settings
from alibi.episode import (
    EpisodeError,
    episode_paths,
    load_answer_key,
    load_episode_manifest,
    load_manifest,
    reproduce_raw_hash,
    verify_raw_integrity,
)
from alibi.evidence.store import EvidenceStore
from alibi.orchestrator import Orchestrator


@pytest.fixture()
def env(tmp_path):
    settings = replace(load_settings({}, dotenv=False), runs_dir=tmp_path / "runs", sealed_dir=tmp_path / "sealed")
    orch = Orchestrator(settings, pace_s=0.0)
    return settings, orch, TestClient(create_app(settings, orch))


def _wait(c, cid, want=("awaiting_review",), timeout=60.0):
    end = time.time() + timeout
    while time.time() < end:
        v = c.get(f"/api/cases/{cid}").json()
        if v["case"]["state"] in want + ("failed",):
            assert v["case"]["state"] in want, v["case"]
            return v
        time.sleep(0.05)
    raise AssertionError(cid)


def _parent(c, preset="hero-coverup", runner="deterministic"):
    cid = c.post("/api/cases", json={"preset_id": preset, "runner": runner}).json()["case"]["case_id"]
    return cid, _wait(c, cid)


def _sid(view, kind, host=None):
    return [s["source_id"] for s in view["manifest"]["sources"] if s["source"] == kind and (host is None or s["host"] == host)]


def _derive(c, cid, ids, token="exp-1", **more):
    r = c.post(f"/api/cases/{cid}/source-experiments", json={"excluded_source_ids": ids, "client_token": token, **more})
    assert r.status_code == 200, r.text
    return r.json()


def _claims(c, child):
    exp = c.get(f"/api/cases/{child}/source-experiment").json()
    return exp, {x["claim_type"]: x for x in exp["comparison"]["claims"] if x["category"] == "incident_allegation"}


# ----------------------------------------------------------------- the default demonstration: no collector
def test_removing_the_collector_removes_the_deletion_proof_and_leaves_the_original_untouched(env):
    settings, orch, c = env
    cid, view = _parent(c)
    paths = orch._paths(cid)
    before = source_experiment.tree_digest(paths)
    report_bytes = (paths.case / "report.draft.json").read_bytes()
    collector = _sid(view, "collector")
    assert len(collector) == 1 and collector[0].startswith("src-")
    removal = next(f for f in view["report"]["findings"] if f["claim_type"] == "local_log_removal")
    withheld_id = removal["evidence_ids"][0]  # the line only the collector kept

    made = _derive(c, cid, collector)
    child = made["child_case_id"]
    assert made["parent_case_id"] == cid and made["parent_raw_bundle_sha256"] == view["manifest"]["raw_bundle_sha256"]
    assert made["child_raw_bundle_sha256"] != made["parent_raw_bundle_sha256"]
    assert [s["source"] for s in made["excluded_sources"]] == ["collector"] and made["events_remaining"] < made["events_original"]
    assert made["case"]["state"] == "frozen" and made["case"]["parent_case_id"] == cid
    assert any("No collector copy" in x for x in made["coverage"]["child"]["limits"])
    assert made["coverage"]["parent"]["limits"] == []

    exp, claims = _claims(c, child)
    assert exp["role"] == "derived" and exp["parent_report"]["locked"] is False
    lost = claims["local_log_removal"]
    assert lost["change"] == "loses_support" and lost["child"]["state"] == "cannot_be_established_here"
    assert lost["evidence_ids_withheld"] == [withheld_id] and lost["evidence_ids_remaining"]  # the brackets are still there
    assert "no collector copy" in lost["reason"] and "unknown" in lost["reason"]
    # the transfer and the staged object are witnessed by other sources and keep their support
    assert claims["policy_violating_transfer"]["change"] == "retains_support"
    assert claims["data_staging"]["change"] == "retains_support"
    # the benign "rotated out" explanation also rested on the collector's copies, so it goes too
    lost_kinds = sorted(x["claim_type"] for x in exp["comparison"]["claims"] if x["change"] == "loses_support")
    assert lost_kinds == ["local_log_removal", "retention_explained_absence"]
    assert exp["comparison"]["summary"]["loses_support"] == 2
    assert "does not mean the event did not happen" in exp["comparison"]["summary"]["reading"]
    # the session's only login record was the collector's copy: the account link goes with it
    att = exp["comparison"]["attribution"]
    assert att["change"] == "weakened" and att["child_observation"] == "session_not_found"
    # deterministic, and nothing sealed is in it: no canary, no executed steps, no operator, no variant
    blob = json.dumps(exp)
    key = load_answer_key(paths)
    for secret in (key.canary, load_answer_key(orch._paths(child)).canary, "operator_true", "incident_coverup",
                   "delete_log_lines", "effect_id", "step_recall"):
        assert secret not in blob, secret

    # the original case: same bytes, same report, same hashes
    assert source_experiment.tree_digest(paths) == before
    assert (paths.case / "report.draft.json").read_bytes() == report_bytes
    assert c.get(f"/api/cases/{cid}").json()["manifest"] == view["manifest"]
    assert c.get(f"/api/cases/{cid}/source-experiment").json()["children"][0]["child_case_id"] == child

    # the child is a complete, self-consistent, read-only bundle
    cpaths = orch._paths(child)
    cm = load_manifest(cpaths)
    assert verify_raw_integrity(cpaths) == [] and cm.capture_complete is False
    assert "collector" not in {s.source for s in cm.sources} and "Not available here" in cm.capture_notes[-1]
    saved, reproduced = reproduce_raw_hash(cpaths)
    assert saved == reproduced == cm.raw_bundle_sha256
    ep = load_episode_manifest(cpaths)
    assert ep.parent_episode_id == cid and [w["source"] for w in ep.withheld_sources] == ["collector"]
    assert load_answer_key(cpaths).canary != load_answer_key(paths).canary
    assert not (cpaths.raw / "collector").exists() and list(cpaths.case.iterdir()) == []  # nothing carried over


def test_withheld_records_cannot_be_fetched_searched_or_cited_in_the_derived_view(env):
    settings, orch, c = env
    cid, view = _parent(c)
    removal = next(f for f in view["report"]["findings"] if f["claim_type"] == "local_log_removal")
    withheld_id = removal["evidence_ids"][0]
    child = _derive(c, cid, _sid(view, "collector"), runner="agent-fixture", investigation_mode="fast")["child_case_id"]
    assert c.get(f"/api/cases/{child}/evidence/events", params={"ids": withheld_id}).json() == {"events": [], "missing": [withheld_id]}
    raw = c.get(f"/api/cases/{child}/evidence/raw", params={"artifact": "collector/var/log/collected/collected.log", "line": 1})
    assert raw.status_code == 400 and "only files listed in the evidence manifest" in raw.json()["error"]
    assert c.get(f"/api/cases/{child}/evidence/compare").json()["status"] == "not_assessable"
    cpaths = orch._paths(child)
    with EvidenceStore(cpaths.db) as st:
        assert st.count(source="collector") == 0 and st.count(source="heartbeat") == 0
        box = CaseToolbox(st, load_manifest(cpaths))
        assert box.get_events([withheld_id])[0] == {"events": [], "not_found": [withheld_id]}
        assert box.search_events("collector", None, None, None, None, None, None, None, 20)[0]["total_matching"] == 0
        brief = box.get_case_brief()[0]
        assert "collector" not in {s["source"] for s in brief["sources"]} and brief["capture"]["complete"] is False

    # a fresh investigation of the derived view (scripted fixture): new state, no deletion claim, no withheld id anywhere
    c.post(f"/api/cases/{child}/investigate")
    v = _wait(c, child)
    kinds = {f["claim_type"] for f in v["report"]["findings"] if f["category"] == "incident_allegation"}
    assert "local_log_removal" not in kinds and "policy_violating_transfer" in kinds
    assert any(q.startswith("Coverage limit: No collector copy") for q in v["report"]["open_questions"])
    assert "unknown" in v["report"]["summary"]
    everything = json.dumps(v["report"]) + json.dumps(c.get(f"/api/cases/{child}/events.json").json())
    assert withheld_id not in everything
    for f in (cpaths.case).rglob("*"):
        if f.is_file() and f.suffix in (".json", ".md", ".jsonl"):
            assert withheld_id not in f.read_text(encoding="utf-8", errors="ignore"), f

    # research scoring of the child: what happened is unchanged, what is observable is recomputed, both rates shown
    c.post(f"/api/cases/{child}/review", json={"decision": "accept"})
    revealed = c.post(f"/api/cases/{child}/reveal").json()["reveal"]
    sc = revealed["source_experiment"]["scoring"]
    assert sc["effects_total_original"] == 3 and sc["effects_with_no_record_in_this_view"] == 1 and sc["caught"] == 2
    assert sc["recall_conditional"]["num"] == 2 and sc["recall_conditional"]["den"] == 2
    assert sc["recall_of_all_original"]["num"] == 2 and sc["recall_of_all_original"]["den"] == 3
    gone = next(e for e in sc["effects"] if e["effect_type"] == "local_log_removal")
    assert gone["outcome"] == "no_record_in_this_view" and gone["records_in_this_view"] == 0 and gone["records_in_original"] >= 1
    assert len(revealed["truth"]["effects"]) == 3 and revealed["score"]["unobservable_effects"] == 1
    out = {o["effect_id"]: o["outcome"] for o in revealed["score"]["effect_outcomes"]}
    assert sorted(out.values()) == ["caught", "caught", "unobservable"]


def test_removing_the_badge_reader_weakens_presence_not_the_transfer(env):
    _, orch, c = env
    cid, view = _parent(c)
    child = _derive(c, cid, _sid(view, "badge"))["child_case_id"]
    exp, claims = _claims(c, child)
    assert {k: v["change"] for k, v in claims.items()} == {
        "local_log_removal": "retains_support", "policy_violating_transfer": "retains_support",
        "data_staging": "retains_support"}
    att = exp["comparison"]["attribution"]
    assert att["parent_observation"].startswith("console_session_while_holder_badged")
    assert att["child_observation"] == "badge_source_not_in_bundle" and att["change"] == "weakened"
    assert "Presence is unknown" in att["child_statement"] and exp["comparison"]["coverage"]["child"]["limits"] == []
    assert exp["comparison"]["summary"]["loses_support"] == 0
    assert exp["comparison"]["summary"]["retains_support"] == exp["comparison"]["summary"]["claims_total"]


def test_removing_the_tap_gives_cannot_be_established_not_a_clean_result(env):
    _, orch, c = env
    cid, view = _parent(c)
    child = _derive(c, cid, _sid(view, "flow"), runner="deterministic", autostart=True)["child_case_id"]
    exp, claims = _claims(c, child)
    assert claims["local_log_removal"]["change"] == "retains_support"
    for kind in ("policy_violating_transfer", "data_staging"):
        assert claims[kind]["change"] == "loses_support" and claims[kind]["child"]["establishable"] is False
    assert any("no network flow source" in claims[k]["reason"] for k in ("policy_violating_transfer", "data_staging"))
    assert "NOT assessable" in exp["comparison"]["coverage"]["child"]["transfers"]
    v = _wait(c, child)
    kinds = [f["claim_type"] for f in v["report"]["findings"] if f["category"] == "incident_allegation"]
    assert kinds == ["local_log_removal"]
    assert any("unknown" in q and "flow source" in q for q in v["report"]["open_questions"])


def test_an_original_without_a_report_still_shows_the_coverage_change(env):
    _, orch, c = env
    cid = c.post("/api/cases", json={"preset_id": "hero-plain", "runner": "deterministic", "autostart": False}).json()["case"]["case_id"]
    view = c.get(f"/api/cases/{cid}").json()
    assert view["case"]["state"] == "frozen"
    child = _derive(c, cid, _sid(view, "collector"))["child_case_id"]
    exp = c.get(f"/api/cases/{child}/source-experiment").json()
    assert exp["comparison"]["claims"] == [] and "no report yet" in exp["comparison"]["note"]
    assert exp["comparison"]["coverage"]["child"]["limits"] and exp["parent_report"] is None


# ----------------------------------------------------------------- request rules
def test_only_manifest_source_ids_are_accepted_and_a_retry_returns_the_same_view(env):
    _, orch, c = env
    cid, view = _parent(c)
    post = lambda body, case=cid: c.post(f"/api/cases/{case}/source-experiments", json=body)  # noqa: E731
    for bad in (["collector/var/log/collected/collected.log"], ["../../sealed"], ["src-zzzzzzzzzzzz"], ["src-000000000000"]):
        r = post({"excluded_source_ids": bad, "client_token": "x"})
        assert r.status_code == 400, bad
    assert post({"excluded_source_ids": [], "client_token": "x"}).status_code == 422
    assert post({"excluded_source_ids": _sid(view, "badge")}).status_code == 422  # client token required
    everything = [s["source_id"] for s in view["manifest"]["sources"]]
    r = post({"excluded_source_ids": everything, "client_token": "x"})
    assert r.status_code == 400 and "at least one source must remain" in r.json()["error"]
    assert post({"excluded_source_ids": _sid(view, "badge"), "client_token": "x"}, case="case-000000000000").status_code == 404
    assert [p.name for p in orch.runs_dir.iterdir()] == [cid]  # refused requests leave nothing behind
    first = _derive(c, cid, _sid(view, "badge"), token="same")
    again = _derive(c, cid, _sid(view, "collector"), token="same")
    assert again["child_case_id"] == first["child_case_id"] and again["excluded_sources"] == first["excluded_sources"]
    nested = post({"excluded_source_ids": _sid(view, "flow"), "client_token": "y"}, case=first["child_case_id"])
    assert nested.status_code == 400 and "original case" in nested.json()["error"]
    caps = c.get("/api/runtime").json()["capabilities"]["source_experiments"]
    assert caps["endpoint"] is True
    # every manifest source carries a stable public id, including manifests written before ids existed
    old = dict(view["manifest"]["sources"][0])
    old.pop("source_id")
    from alibi.contracts import SourceInfo
    assert SourceInfo.model_validate(old).source_id == view["manifest"]["sources"][0]["source_id"]


def test_a_derived_view_outlives_nothing_it_should_not(env):
    _, orch, c = env
    cid, view = _parent(c)
    child = _derive(c, cid, _sid(view, "collector"))["child_case_id"]
    c.post(f"/api/cases/{cid}/reset")
    exp = c.get(f"/api/cases/{child}/source-experiment").json()
    assert exp["comparison"] is None and "no longer exists" in exp["note"]
    assert c.get(f"/api/cases/{child}").json()["case"]["state"] == "frozen"  # the view itself is still a valid case


def test_no_view_is_derived_from_evidence_that_fails_its_own_hashes(env, tmp_path):
    settings, orch, c = env
    cid, view = _parent(c)
    paths = orch._paths(cid)
    target = paths.raw / "tap" / "flows.jsonl"
    target.chmod(0o644)
    target.write_text(target.read_text() + "tampered\n")
    r = c.post(f"/api/cases/{cid}/source-experiments", json={"excluded_source_ids": _sid(view, "badge"), "client_token": "t"})
    assert r.status_code == 400 and "integrity check" in r.json()["error"]
    assert [p.name for p in orch.runs_dir.iterdir()] == [cid] and [p.name for p in orch.sealed_dir.iterdir()] == [cid]
    with pytest.raises(EpisodeError):
        source_experiment.create_child_bundle(paths, episode_paths("case-aaaaaaaaaaaa", settings.runs_dir, settings.sealed_dir),
                                              _sid(view, "badge"))


def test_terminal_commands_show_the_experiment_the_question_and_the_export(env, monkeypatch, capsys):
    from alibi import cli

    settings, orch, c = env
    monkeypatch.setattr(cli, "load_settings", lambda: settings)
    cid, _ = _parent(c)
    assert cli.main(["cases"]) == 0 and cid in capsys.readouterr().out
    assert cli.main(["experiment", cid, "--without", "collector", "--runner", "deterministic"]) == 0
    out = capsys.readouterr().out
    assert "CANNOT BE ESTABLISHED  local_log_removal" in out and "STILL SUPPORTED        policy_violating_transfer" in out
    assert "It is not shown to be false." in out and "No collector copy" in out
    assert cli.main(["experiment", cid, "--without", "satellite"]) == 1 and "no source of kind" in capsys.readouterr().err
    assert cli.main(["ask", cid, "What is missing from the host log?"]) == 1  # offline: asked, not answered
    said = capsys.readouterr().out
    assert "status: unavailable" in said and "No model is configured" in said
    assert cli.main(["export", cid]) == 1 and "locked" in capsys.readouterr().err  # not reviewed yet
    c.post(f"/api/cases/{cid}/review", json={"decision": "accept"})
    assert cli.main(["export", cid]) == 0
    md = capsys.readouterr().out
    assert md.startswith("# Investigation report: Inside job · cover-up") and "## Cited records" in md
    assert cli.main(["export", cid, "--json"]) == 0 and json.loads(capsys.readouterr().out)["lock"]["report_sha256"]
