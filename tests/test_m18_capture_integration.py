"""Captured evidence through the whole pipeline: import, investigation, experiment, review, export. Offline.

The three bundles under tests/fixtures/capture/ were written by running processes in the Docker capture
(docs/capture.md) and are labeled DOCKER. Their own byte-level tests are in tests/test_capture.py. This file
checks what the rest of the system does with them. Anything written by hand here is labeled SIM.
"""

from __future__ import annotations

import json
import time
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from alibi import export, importing
from alibi.api.app import create_app
from alibi.config import load_settings
from alibi.episode import episode_paths
from alibi.evidence.store import EvidenceStore, _naive
from alibi.orchestrator import Orchestrator

FIXTURES = Path(__file__).parent / "fixtures" / "capture"
LOCAL = "records/var/log/records-app/access.log"
COLLECTOR = "collector/collected/collected.log"


@pytest.fixture()
def env(tmp_path):
    settings = replace(load_settings({}, dotenv=False), runs_dir=tmp_path / "runs", sealed_dir=tmp_path / "sealed")
    orch = Orchestrator(settings, pace_s=0.0)
    return settings, orch, TestClient(create_app(settings, orch)), tmp_path


def _wait(orch, case_id):
    end = time.time() + 60
    while time.time() < end:
        if orch.record(case_id).state in ("awaiting_review", "failed", "cancelled"):
            break
        time.sleep(0.02)
    assert orch.record(case_id).state == "awaiting_review", orch.record(case_id).error


def _investigated(orch, directory, runner="deterministic"):
    rec = orch.import_case(str(directory), title=None, runner_id=runner, investigation_mode=None)
    orch.start_investigation(rec.case_id)
    _wait(orch, rec.case_id)
    return rec.case_id, orch.view(rec.case_id)


@pytest.mark.parametrize("name,alleged", [("complete", []), ("missing-local-record", ["local_log_removal"]), ("benign-gap", [])])
def test_a_captured_bundle_is_investigated_reviewed_and_exported_as_unscored_docker_evidence(env, name, alleged):
    settings, orch, c, _ = env
    case_id, view = _investigated(orch, FIXTURES / name)
    labels = view["case"]["labels"]
    assert labels["evidence_origin"] == "DOCKER" and labels["inference"] == "NO_MODEL_BASELINE"
    assert "not scored" in labels["ground_truth"] and view["case"]["scored"] is False
    assert {s["origin"] for s in view["manifest"]["sources"]} == {"DOCKER"}
    report = view["report"]
    incidents = [f for f in report["findings"] if f["category"] == "incident_allegation"]
    assert [f["claim_type"] for f in incidents] == alleged and all(f["status"] == "verified" for f in incidents)
    assert report["attribution"]["named_person_accused"] is None
    # there is no answer key to unseal, and saying so is an ordinary answer
    r = c.post(f"/api/cases/{case_id}/reveal")
    assert r.status_code == 409 and "no answer key" in r.text
    orch.review(case_id, "accept", "")
    md = export.render_markdown(orch.report_export(case_id))
    assert md.count("| DOCKER |") == 2 and "No scenario and no answer key are known to this system" in md
    assert not episode_paths(case_id, settings.runs_dir, settings.sealed_dir).sealed.exists()


@pytest.mark.parametrize("runner", ["deterministic", "agent-fixture"])
def test_the_captured_removal_cites_the_line_the_collector_kept_and_asks_nothing_about_a_scenario(env, runner):
    """Both runners that need no model: the deterministic checks and the scripted fixture (the offline default)."""
    settings, orch, _, _ = env
    case_id, view = _investigated(orch, FIXTURES / "missing-local-record", runner)
    report = view["report"]
    assert view["case"]["labels"]["inference"] == {"deterministic": "NO_MODEL_BASELINE", "agent-fixture": "SCRIPTED_FIXTURE"}[runner]
    finding = report["findings"][0]
    with EvidenceStore(episode_paths(case_id, settings.runs_dir, settings.sealed_dir).db) as store:
        cited = store.get(finding["evidence_ids"])
    kept = [e for e in cited if e.source == "collector"]
    assert len(kept) == 1 and "record=dummy-2" in kept[0].raw
    assert sorted(e.artifact_ref.artifact for e in cited if e.source != "collector") == [LOCAL, LOCAL]
    assert "record=dummy-2" not in (FIXTURES / "missing-local-record" / LOCAL).read_text()
    # the capture has an account but no session, no transfer and no badge directory: nothing is asked or assumed about them
    assert report["attribution"]["account_used"] == "demo" and report["attribution"]["human_identity"] == "insufficient_evidence"
    assert report["attribution"]["assumptions"] == []
    questions = report["open_questions"]
    assert questions[0] == "Who had access to the account demo when these records were written?"
    assert not any("clinic" in q or "linked session" in q or "destination" in q for q in questions)
    assert any(q.startswith("Coverage limit: No network flow source") for q in questions)


def test_a_simulated_case_keeps_its_scenario_questions_and_assumption(env):
    """The change above is for imported evidence only: a simulated case reads exactly as it did."""
    _, orch, _, _ = env
    rec = orch.create_case(preset_id="hero-coverup", runner_id="deterministic")
    orch.start_investigation(rec.case_id)
    _wait(orch, rec.case_id)
    report = orch.view(rec.case_id)["report"]
    assert report["open_questions"][:2] == ["Who had access to the credential used in the linked session?",
                                            "Was the destination known to anyone at the clinic?"]
    assert report["attribution"]["assumptions"] == ["badge-to-account assignments in the supplied directory are current"]


def test_a_model_is_not_told_that_imported_evidence_comes_from_the_simulated_clinic(env, monkeypatch):
    """Simulated cases are framed as a small clinic network. Imported evidence is not: nothing is known about it."""
    from alibi.agents import investigator
    from alibi.agents.tools import CaseToolbox
    from alibi.episode import load_manifest
    from alibi.questions import QA_SYSTEM

    settings, orch, _, _ = env
    seen: list[str] = []
    monkeypatch.setattr(investigator, "create_deep_agent", lambda **kw: seen.append(kw["system_prompt"]))
    imported = orch.import_case(str(FIXTURES / "complete"), title=None, runner_id="deterministic", investigation_mode=None)
    simulated = orch.create_case(preset_id="hero-coverup", runner_id="deterministic")
    for case_id in (imported.case_id, simulated.case_id):
        paths = episode_paths(case_id, settings.runs_dir, settings.sealed_dir)
        with EvidenceStore(paths.db) as store:
            toolbox = CaseToolbox(store, load_manifest(paths))
            investigator.build_single_agent(toolbox, model=None, checkpointer=None)
            investigator.build_investigator(toolbox, lead_model=None, auditor_model=None, skeptic_model=None, checkpointer=None)
    for prompt in seen[:2]:  # the imported case: fast mode, then the lead of the three-agent mode
        assert "clinic" not in prompt.lower() and "imported from outside this system" in prompt
        assert "assume nothing about the organization, its people or its data" in prompt
    # the simulated case gets exactly the prompts the evaluation fingerprinted
    assert seen[2] == investigator.single_prompt(True, True) + investigator.family_addendum(toolbox)
    assert seen[3] == investigator.lead_prompt(True, True) + investigator.family_addendum(toolbox)
    assert "small clinic network" in seen[2] and "small clinic network" in seen[3]
    neutral = importing.neutral_framing(QA_SYSTEM)
    assert "clinic" not in neutral.lower() and neutral.replace(importing.IMPORTED_FRAMING, importing.SIMULATED_FRAMING) == QA_SYSTEM
    assert importing.is_imported(load_manifest(episode_paths(imported.case_id, settings.runs_dir, settings.sealed_dir)))
    assert not importing.is_imported(load_manifest(episode_paths(simulated.case_id, settings.runs_dir, settings.sealed_dir)))
    with pytest.raises(ValueError):
        importing.neutral_framing("a prompt that never mentioned the simulated network")


def test_without_the_collector_the_captured_removal_cannot_be_established(env):
    _, orch, _, _ = env
    case_id, _ = _investigated(orch, FIXTURES / "missing-local-record")
    sources = orch.source_experiment(case_id)["sources"]
    collector = [s["source_id"] for s in sources if s["source"] == "collector"]
    child = orch.create_source_experiment(case_id, collector, "capture-test-1", runner_id="deterministic")
    exp = orch.source_experiment(child.case_id)
    assert [s["artifact"] for s in exp["excluded_sources"]] == [COLLECTOR]
    assert (exp["events_original"], exp["events_remaining"]) == (5, 2)
    assert [(row["claim_type"], row["change"]) for row in exp["comparison"]["claims"]] == [("local_log_removal", "loses_support")]
    assert child.evidence_origin == "DOCKER" and child.scored is False
    orch.start_investigation(child.case_id)
    _wait(orch, child.case_id)
    derived = orch.view(child.case_id)["report"]
    assert [f for f in derived["findings"] if f["category"] == "incident_allegation"] == []


def test_the_terminal_can_import_and_investigate_a_capture(env, monkeypatch, capsys):
    from alibi import cli

    settings, orch, _, tmp = env
    monkeypatch.setattr(cli, "load_settings", lambda: settings)
    assert cli.main(["import", str(FIXTURES / "missing-local-record"), "--runner", "deterministic", "--investigate"]) == 0
    out = capsys.readouterr().out
    assert '"evidence_origin": "DOCKER"' in out and '"scored": false' in out
    assert "evidence DOCKER" in out and "state awaiting_review" in out
    assert "incident_allegation" in out and "local_log_removal" in out and "account: demo" in out
    # the two steps separately: freeze first, investigate by case id afterwards
    assert cli.main(["import", str(FIXTURES / "benign-gap"), "--runner", "deterministic"]) == 0
    frozen = json.loads(capsys.readouterr().out)
    assert frozen["state"] == "frozen" and frozen["next"].startswith(f"alibi investigate {frozen['case_id']}")
    assert cli.main(["investigate", frozen["case_id"]]) == 0
    out = capsys.readouterr().out
    assert "state awaiting_review" in out and "no findings" in out
    assert cli.main(["investigate", "case-000000000000"]) == 1 and "error" in capsys.readouterr().err


# ---------------------------------------------------------------- records closer together than one second


def _subsecond_capture(tmp: Path) -> Path:
    """Three requests 100 ms apart, all inside one second; the host's copy lacks the second. Hand-written: SIM."""
    t0 = datetime(2026, 11, 14, 18, 0, 0, 100000, tzinfo=timezone.utc)

    def at(i: int, extra_us: int = 0) -> str:
        return (t0 + timedelta(milliseconds=100 * i, microseconds=extra_us)).isoformat(timespec="microseconds")

    local = [f"{at(i)} rec-srv-01 testapp: user=demo action=read record=dummy-{i + 1} status=200 delivery_id={i + 1}"
             for i in range(3)]
    kept = [f"{at(i, 900)} logcol-01 fwd: origin=records file=/var/log/records-app/access.log seq={i + 1} msg={local[i]}"
            for i in range(3)]
    src = tmp / "subsecond"
    (src / LOCAL).parent.mkdir(parents=True)
    (src / COLLECTOR).parent.mkdir(parents=True)
    (src / LOCAL).write_text(local[0] + "\n" + local[2] + "\n")
    (src / COLLECTOR).write_text("\n".join(kept) + "\n")
    start, end = t0 - timedelta(milliseconds=50), t0 + timedelta(milliseconds=400)
    cover = {"coverage_start": start.isoformat(), "coverage_end": end.isoformat()}
    importing.write_capture_manifest(
        src, "subsecond-test", "hand-written test input", "SIM", start, end,
        per_artifact={LOCAL: {**cover, "known_gaps": [], "forwarded_to_collector": True}, COLLECTOR: cover},
        operational_context={"logging_policy": {"forwarded_files": [{"host": "records", "file": "/var/log/records-app/access.log"}]}},
        notes=["Hand-written test input."])
    return src


def test_a_line_missing_between_two_records_in_the_same_second_is_still_bracketed(env):
    """Before the store kept sub-second time, the later local record was read as earlier than the missing line."""
    settings, orch, _, tmp = env
    case_id, view = _investigated(orch, _subsecond_capture(tmp))
    assert view["case"]["labels"]["evidence_origin"] == "SIM"
    incidents = [f for f in view["report"]["findings"] if f["category"] == "incident_allegation"]
    assert [(f["claim_type"], f["status"]) for f in incidents] == [("local_log_removal", "verified")]
    with EvidenceStore(episode_paths(case_id, settings.runs_dir, settings.sealed_dir).db) as store:
        events = store.scan()
        # stored with their real time, and so in their real order across the two files
        assert [e.ts.microsecond for e in events] == [100000, 100900, 200900, 300000, 300900]
        assert [e.source == "collector" for e in events] == [False, True, True, False, True]
        # a bound given to the second means through that second, as the times are displayed to the second
        second = datetime(2026, 11, 14, 18, 0, 0, tzinfo=timezone.utc)
        assert store.count(t_start=second, t_end=second) == 5
        assert store.count(t_end=second - timedelta(seconds=1)) == 0
        # a bound that states a fraction is taken exactly
        assert store.count(t_end=second + timedelta(milliseconds=200)) == 2
        assert store.count(t_start=second + timedelta(milliseconds=200)) == 3


def test_whole_second_times_are_stored_exactly_as_before():
    assert _naive(datetime(2026, 11, 14, 18, 0, 5, tzinfo=timezone.utc)) == "2026-11-14 18:00:05"
    assert _naive(datetime(2026, 11, 14, 18, 0, 5, 250000, tzinfo=timezone.utc)) == "2026-11-14 18:00:05.250000"
