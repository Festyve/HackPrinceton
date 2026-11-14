"""Importing evidence captured outside the simulator, as an unscored case. Offline.

No captured evidence exists in this repository yet. These tests feed the importer simulator bytes that
are labeled as simulated (SIM), plus hand-made manifests for the rejection and labeling rules. Nothing
here is evidence of a real capture.
"""

from __future__ import annotations

import json
import time
from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from alibi import importing
from alibi.api.app import create_app
from alibi.config import load_settings
from alibi.episode import artifact_hashes, bundle_hash, episode_paths
from alibi.orchestrator import Orchestrator
from alibi.sim.scenario import build_spec, operational_context, simulate

SEED = 8


def _capture(tmp: Path, name: str = "cap", drop: tuple[str, ...] = (), origin: str = "SIM", per: dict | None = None,
             context: bool = True) -> tuple[Path, dict]:
    """A capture directory made of simulator output, honestly labeled SIM unless a test says otherwise."""
    spec = build_spec(SEED, "incident_coverup")
    sim = simulate(spec)
    src = tmp / name
    for art, text in sim.artifacts.items():
        if art in drop:
            continue
        f = src / art
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_bytes(text.encode("utf-8"))
    importing.write_capture_manifest(
        src, f"{name}-test-1", "unit test (simulator bytes)", origin, datetime.fromisoformat(spec["capture_start"]),
        datetime.fromisoformat(spec["capture_end"]), operational_context=operational_context(spec) if context else {},
        notes=["Synthetic test input."], per_artifact=per)
    return src, sim.artifacts


@pytest.fixture()
def env(tmp_path):
    settings = replace(load_settings({}, dotenv=False), runs_dir=tmp_path / "runs", sealed_dir=tmp_path / "sealed")
    orch = Orchestrator(settings, pace_s=0.0)
    return settings, orch, TestClient(create_app(settings, orch)), tmp_path


def _wait(c, cid, want="awaiting_review"):
    end = time.time() + 60
    while time.time() < end:
        v = c.get(f"/api/cases/{cid}").json()
        if v["case"]["state"] in (want, "failed"):
            assert v["case"]["state"] == want, v["case"]
            return v
        time.sleep(0.05)
    raise AssertionError(cid)


def test_an_imported_bundle_keeps_its_bytes_and_is_investigated_reviewed_exported_but_never_scored(env):
    settings, orch, c, tmp = env
    src, artifacts = _capture(tmp)
    rec = orch.import_case(src, runner_id="deterministic")
    assert rec.state == "frozen" and rec.scored is False and rec.card_id == "imported" and rec.evidence_origin == "SIM"
    paths = orch._paths(rec.case_id)
    assert not paths.sealed.exists()  # no answer key was written, because none exists
    for art, text in artifacts.items():
        assert (paths.raw / art).read_bytes() == text.encode("utf-8")  # verbatim
    v = c.get(f"/api/cases/{rec.case_id}").json()
    assert v["manifest"]["raw_bundle_sha256"] == bundle_hash(artifact_hashes(artifacts))
    assert v["card"]["title"] == "Imported evidence" and "no answer key" in v["card"]["audience_setup"]
    assert v["case"]["labels"]["ground_truth"].startswith("none") and v["case"]["difficulty"] == "unscored"
    assert "ground_truth" in v["manifest"]["operational_context"]["capture"]
    c.post(f"/api/cases/{rec.case_id}/investigate")
    v = _wait(c, rec.case_id)
    kinds = sorted(f["claim_type"] for f in v["report"]["findings"] if f["category"] == "incident_allegation")
    assert kinds == ["data_staging", "local_log_removal", "policy_violating_transfer"]  # the checks work on imported bytes
    locked = c.post(f"/api/cases/{rec.case_id}/review", json={"decision": "accept"}).json()
    assert locked["case"]["state"] == "report_locked"
    nope = c.post(f"/api/cases/{rec.case_id}/reveal")
    assert nope.status_code == 409 and "no answer key" in nope.json()["error"]
    assert c.get(f"/api/cases/{rec.case_id}/reveal-export").status_code == 409
    md = c.get(f"/api/cases/{rec.case_id}/report-export").text
    assert "Simulated evidence (SIM)" in md and locked["report"]["report_sha256"] in md
    q = c.post(f"/api/cases/{rec.case_id}/questions", json={"question": "What is missing?", "client_token": "i-1"}).json()
    assert q["status"] == "unavailable"  # offline; and never a canned answer
    with pytest.raises(Exception) as err:
        orch.save_recording(rec.case_id, "imported-rec")
    assert "regenerating its evidence from a scenario" in str(err.value)
    assert c.get("/api/runtime").json()["capabilities"]["capture_import"]["http"] is False


def test_a_source_removal_experiment_on_imported_evidence_stays_unscored(env):
    _, orch, c, tmp = env
    src, _ = _capture(tmp)
    rec = orch.import_case(src, runner_id="deterministic")
    orch.start_investigation(rec.case_id)
    view = _wait(c, rec.case_id)
    collector = [s["source_id"] for s in view["manifest"]["sources"] if s["source"] == "collector"]
    made = c.post(f"/api/cases/{rec.case_id}/source-experiments", json={"excluded_source_ids": collector, "client_token": "imp-x"})
    assert made.status_code == 200, made.text
    child = made.json()["child_case_id"]
    assert orch.record(child).scored is False and not orch._paths(child).sealed.exists()
    exp = c.get(f"/api/cases/{child}/source-experiment").json()
    by = {x["claim_type"]: x["change"] for x in exp["comparison"]["claims"] if x["category"] == "incident_allegation"}
    assert by == {"local_log_removal": "loses_support", "data_staging": "retains_support", "policy_violating_transfer": "retains_support"}
    c.post(f"/api/cases/{child}/investigate")
    _wait(c, child)
    c.post(f"/api/cases/{child}/review", json={"decision": "reject"})
    assert c.post(f"/api/cases/{child}/reveal").status_code == 409


def test_each_source_keeps_the_origin_and_coverage_its_capture_states(env):
    from alibi import checks
    from alibi.episode import load_manifest
    from alibi.evidence.store import EvidenceStore

    _, orch, c, tmp = env
    auth, old = "workstation/var/log/auth.log", "workstation/var/log/auth.log.1"
    # first, as captured with nothing stated: the removed line is bracketed, so it is reported
    plain, _ = _capture(tmp, name="plain")
    first = orch.import_case(plain, runner_id="deterministic")
    fp = orch._paths(first.case_id)
    with EvidenceStore(fp.db) as st:
        m = load_manifest(fp)
        row = next(r for f in checks.reconcile_logs(st, m)["files"] if f["host"] == "workstation"
                   for r in f["unexplained_local_absence"])
    gone = datetime.fromisoformat(row["line_ts"])
    span = {s.artifact: (s.coverage_start, s.coverage_end) for s in m.sources}
    # then the same bytes from a capture that STATES the host's collection only began after that moment
    per = {auth: {"coverage_start": (gone + timedelta(minutes=1)).isoformat(), "coverage_end": span[auth][1].isoformat(),
                  "coverage_note": "collection on this host started late",
                  "known_gaps": [{"start": (gone + timedelta(minutes=30)).isoformat(),
                                  "end": (gone + timedelta(minutes=35)).isoformat(), "reason": "agent restart"}]},
           old: {"coverage_start": span[old][0].isoformat(), "coverage_end": span[old][1].isoformat()}}
    # (synthetic test input: the bytes are simulator output; the DOCKER label below only exercises label handling)
    src, _ = _capture(tmp, origin="HYBRID", per=per)
    doc = json.loads((src / "capture.json").read_text())
    for a in doc["artifacts"]:
        a["origin"] = "DOCKER" if a["path"] == auth else "SIM"
    (src / "capture.json").write_text(json.dumps(doc))
    rec = orch.import_case(src, runner_id="deterministic")
    v = c.get(f"/api/cases/{rec.case_id}").json()
    by = {s["artifact"]: s for s in v["manifest"]["sources"]}
    assert v["manifest"]["evidence_origin"] == "HYBRID" and v["case"]["labels"]["evidence_origin"] == "HYBRID"
    assert by[auth]["origin"] == "DOCKER" and by["tap/flows.jsonl"]["origin"] == "SIM"
    assert by[auth]["coverage_declared"] is True and by[auth]["known_gaps"][0]["reason"] == "agent restart"
    assert by["tap/flows.jsonl"]["coverage_declared"] is False and v["manifest"]["capture_complete"] is False
    # the stated late start is honored: that line is outside the host's coverage, not "removed"
    c.post(f"/api/cases/{rec.case_id}/investigate")
    rep = _wait(c, rec.case_id)["report"]
    assert not [f for f in rep["findings"] if f["claim_type"] == "local_log_removal" and f["host"] == "workstation"]
    assert any("inconclusive, not an allegation" in q for q in rep["open_questions"])
    c.post(f"/api/cases/{rec.case_id}/review", json={"decision": "accept"})
    md = c.get(f"/api/cases/{rec.case_id}/report-export").text
    assert "HYBRID" in md and "| DOCKER |" in md and "| SIM |" in md


def test_unparseable_lines_stay_in_the_evidence_as_they_were(env):
    _, orch, c, tmp = env
    src, _ = _capture(tmp)
    f = src / "workstation/var/log/syslog"
    odd = "this line is in a format nobody taught the parser\n"
    f.write_text(f.read_text() + odd)
    importing.write_capture_manifest(src, "cap-odd-1", "unit test", "SIM", datetime.fromisoformat("2026-11-10T06:00:00+00:00"),
                                     datetime.fromisoformat("2026-11-10T16:00:00+00:00"))
    rec = orch.import_case(src, runner_id="deterministic")
    paths = orch._paths(rec.case_id)
    assert (paths.raw / "workstation/var/log/syslog").read_text().endswith(odd)  # not rewritten, not dropped
    v = c.get(f"/api/cases/{rec.case_id}").json()
    syslog = next(s for s in v["manifest"]["sources"] if s["artifact"] == "workstation/var/log/syslog")
    assert "could not be parsed" in syslog["coverage_note"]


@pytest.mark.parametrize("break_it, expect", [
    (lambda src, doc: doc["artifacts"][0].update(sha256="0" * 64), "does not match its SHA-256"),
    (lambda src, doc: doc["artifacts"][0].update(size_bytes=1), "the manifest says 1"),
    (lambda src, doc: doc["artifacts"][0].update(path="../outside.log"), "relative path inside"),
    (lambda src, doc: doc["artifacts"][0].update(path="/etc/passwd"), "relative path inside"),
    (lambda src, doc: doc.update(answer_key={"steps": ["exfil"]}), "not a valid alibi-capture/1 manifest"),
    (lambda src, doc: doc["operational_context"].update(ground_truth={"attacker": "nurse"}), "looks like ground truth"),
    (lambda src, doc: doc["operational_context"].update(notes=[{"is_incident": True}]), "looks like ground truth"),
    (lambda src, doc: doc.update(evidence_origin="DOCKER"), "a mixed capture must say HYBRID"),
    (lambda src, doc: doc.update(format="something-else"), "not a valid alibi-capture/1 manifest"),
    (lambda src, doc: (src / doc["artifacts"][0]["path"]).write_text("tampered after the manifest was written\n"), "the manifest says"),
])
def test_a_capture_that_does_not_match_its_manifest_or_carries_truth_is_refused(env, break_it, expect):
    settings, orch, c, tmp = env
    src, _ = _capture(tmp)
    doc = json.loads((src / "capture.json").read_text())
    break_it(src, doc)
    if (src / "capture.json").exists():
        (src / "capture.json").write_text(json.dumps(doc))
    with pytest.raises(importing.ImportError_) as err:
        orch.import_case(src, runner_id="deterministic")
    assert expect in str(err.value)
    assert not settings.runs_dir.exists() or [p.name for p in settings.runs_dir.iterdir()] == []  # nothing left behind


def test_links_unknown_locations_and_missing_manifests_are_refused(env, tmp_path):
    settings, orch, c, tmp = env
    src, _ = _capture(tmp)
    secret = tmp / "outside-secret.txt"
    secret.write_text("not part of the capture\n")
    link = src / "workstation/var/log/syslog"
    link.unlink()
    link.symlink_to(secret)
    with pytest.raises(importing.ImportError_) as err:
        importing.load_capture(src)
    assert "is a link" in str(err.value) or "manifest says" in str(err.value)
    other, _ = _capture(tmp, name="other")
    (other / "notes.bin").write_bytes(b"\x00\x01")
    importing.write_capture_manifest(other, "cap-other-1", "unit test", "SIM", datetime(2026, 11, 10, 6), datetime(2026, 11, 10, 16))
    with pytest.raises(importing.ImportError_) as err:
        importing.load_capture(other)
    assert "not at a location the normalizer recognizes" in str(err.value)
    with pytest.raises(importing.ImportError_):
        importing.load_capture(tmp / "does-not-exist")
    with pytest.raises(importing.ImportError_):
        importing.import_bundle(tmp / "does-not-exist", episode_paths("case-aaaaaaaaaaaa", settings.runs_dir, settings.sealed_dir))


def test_import_command_reports_origins_and_that_the_case_is_unscored(env, monkeypatch, capsys):
    from alibi import cli

    settings, orch, c, tmp = env
    src, _ = _capture(tmp)
    monkeypatch.setattr(cli, "load_settings", lambda: settings)
    assert cli.main(["import", str(src), "--title", "Test capture", "--runner", "deterministic"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["scored"] is False and out["evidence_origin"] == "SIM" and out["state"] == "frozen"
    assert {s["origin"] for s in out["sources"]} == {"SIM"} and out["events"] > 1000
    assert cli.main(["import", str(tmp / "nope")]) == 1 and "not a capture directory" in capsys.readouterr().err
