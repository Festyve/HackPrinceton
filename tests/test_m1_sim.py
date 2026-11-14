"""M1: SimBackend, bounded step library, freeze, normalization, manifests."""

from __future__ import annotations

import json
import os
import stat

import pytest

from alibi.contracts import EvidenceManifest
from alibi.episode import (
    artifact_hashes,
    bundle_hash,
    create_episode,
    load_answer_key,
    load_episode_manifest,
    load_manifest,
    reproduce_raw_hash,
    verify_raw_integrity,
)
from alibi.evidence.normalize import normalize_artifact
from alibi.sim import steps as S
from alibi.sim.scenario import BENIGN_VARIANTS, VARIANTS, build_spec, plan_context, simulate

from .conftest import DEV_SEED


# ----------------------------------------------------------------- determinism / reproduction
def test_same_spec_reproduces_byte_identical_raw_evidence():
    spec = build_spec(11, "incident_coverup")
    a, b = simulate(spec), simulate(json.loads(json.dumps(spec)))
    assert a.artifacts == b.artifacts
    assert bundle_hash(artifact_hashes(a.artifacts)) == bundle_hash(artifact_hashes(b.artifacts))


def test_saved_scenario_reproduces_the_frozen_bundle_hash(coverup):
    saved, again = reproduce_raw_hash(coverup)
    assert saved == again == load_manifest(coverup).raw_bundle_sha256


def test_different_seeds_and_variants_give_different_evidence():
    hashes = {bundle_hash(artifact_hashes(simulate(build_spec(s, v)).artifacts))
              for s in (1, 2) for v in VARIANTS}
    assert len(hashes) == 2 * len(VARIANTS)


def test_cases_vary_accounts_destinations_and_paths_across_seeds():
    specs = [build_spec(s, "incident_coverup") for s in range(1, 9)]
    assert len({sp["crime"]["framed_account"] for sp in specs}) >= 3
    assert len({sp["crime"]["sink_ip"] for sp in specs}) >= 4
    assert len({sp["plan"][1]["params"]["dst_name"] for sp in specs}) >= 3


# ----------------------------------------------------------------- frozen evidence
def test_frozen_raw_files_are_read_only_and_intact(coverup):
    assert verify_raw_integrity(coverup) == []
    for f in coverup.raw.rglob("*"):
        if f.is_file():
            assert not (f.stat().st_mode & (stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH)), f
    with pytest.raises(PermissionError):
        (coverup.raw / "tap" / "flows.jsonl").open("a")


def test_integrity_check_detects_a_modified_artifact(roots):
    p = create_episode(seed=5, variant="incident_plain", runs_dir=roots[0], sealed_dir=roots[1], episode_id="t-tamper-5")
    target = p.raw / "workstation" / "var" / "log" / "auth.log"
    os.chmod(target, 0o644)
    target.write_text(target.read_text() + "2026-11-10T23:00:00+00:00 ws-nurse-01 login[1]: injected\n")
    problems = verify_raw_integrity(p)
    assert any("auth.log" in x for x in problems)


def test_episode_id_cannot_be_reused_or_escape_the_runs_dir(roots, coverup):
    with pytest.raises(Exception):
        create_episode(seed=1, variant="incident_plain", runs_dir=roots[0], sealed_dir=roots[1],
                       episode_id=coverup.episode_id)
    for bad in ("../x", "a/b", "/abs", "..", "UPPER", "x"):
        with pytest.raises(Exception):
            create_episode(seed=1, variant="incident_plain", runs_dir=roots[0], sealed_dir=roots[1], episode_id=bad)


# ----------------------------------------------------------------- manifests and leakage
GIVEAWAYS = ("attacker", "adversary", "exfil", "sink", "crime", "framed", "malicious", "incident", "truth", "canary")


def test_public_manifest_has_no_truth_and_private_manifest_has_the_spec(coverup):
    public = json.loads(coverup.manifest.read_text())
    text = json.dumps(public).lower()
    key = load_answer_key(coverup)
    priv = load_episode_manifest(coverup)
    assert key.canary.lower() not in text
    for field in ("seed", "variant", "difficulty", "crime_card", "plan", "operator"):
        assert f'"{field}' not in text, field
    assert priv.seed == DEV_SEED and priv.scenario_spec["plan"] and priv.plan_source == "scripted_scenario"
    assert EvidenceManifest.model_validate(public).bundle_id.startswith("bndl-")
    assert DEV_SEED and str(coverup.episode_id) not in text  # bundle id is not derived from the episode id


def test_raw_evidence_contains_no_canary_or_giveaway_labels(make_episode):
    for variant in VARIANTS:
        p = make_episode(DEV_SEED, variant)
        canary = load_answer_key(p).canary
        for f in p.raw.rglob("*"):
            if f.is_file():
                body = f.read_text().lower()
                assert canary.lower() not in body
                for word in GIVEAWAYS:
                    assert word not in body, (variant, f.name, word)


def test_incident_and_benign_manifests_have_the_same_shape_and_tip(make_episode):
    inc = load_manifest(make_episode(DEV_SEED, "incident_coverup"))
    for variant in BENIGN_VARIANTS:
        ben = load_manifest(make_episode(DEV_SEED, variant))
        assert ben.operational_context["tip"] == inc.operational_context["tip"]
        assert set(ben.operational_context) == set(inc.operational_context)
        assert {s.source for s in ben.sources} == {s.source for s in inc.sources}
        assert 0.8 < ben.event_count / inc.event_count < 1.25  # comparable volume


def test_event_ids_are_opaque_unique_and_stable(coverup, store_for):
    st = store_for(coverup)
    evs = st.scan(source="auth")
    assert len({e.id for e in evs}) == len(evs)
    for e in evs:
        assert e.id.startswith("ev_") and len(e.id) == 15
        assert not any(w in e.id for w in ("s1", "step", "L2", "crime"))
    again = normalize_artifact("workstation/var/log/auth.log",
                               (coverup.raw / "workstation/var/log/auth.log").read_text())[0]
    assert {e.id for e in again} <= {e.id for e in evs}


# ----------------------------------------------------------------- normalization
def test_simulated_bundle_normalizes_without_errors(coverup):
    m = load_manifest(coverup)
    assert m.normalization_errors == [] and m.event_count > 5000
    assert all(s.sha256 and s.line_count > 0 for s in m.sources)
    witness = {s.source for s in m.sources if s.tamper_exposure == "independent_witness"}
    assert witness == {"collector", "flow", "badge"}


def test_unparseable_lines_stay_visible_as_errors_not_silently_dropped():
    text = ("2026-11-10T07:00:00+00:00 ws-nurse-01 login[9]: pam_unix(login:session): session opened for user a on tty1 (session 1)\n"
            "this is not a log line\n"
            "not-a-timestamp ws-nurse-01 login[9]: something\n")
    events, errors = normalize_artifact("workstation/var/log/auth.log", text)
    assert len(events) == 3 and len(errors) == 2
    assert [e.action for e in events] == ["login", "unparsed", "unparsed"]
    assert events[1].raw == "this is not a log line"


def test_timestamps_are_preserved_as_recorded(coverup, store_for):
    ev = store_for(coverup).search(source="auth", host="workstation", limit=1)[0]
    assert ev.raw.startswith(ev.ts_raw) and ev.ts.isoformat().startswith(ev.ts_raw[:19])
    hist = store_for(coverup).search(source="shell_history", limit=1)[0]
    assert hist.ts_raw.isdigit() and int(hist.ts_raw) == int(hist.ts.timestamp())


def test_every_event_reference_resolves_to_its_raw_line(coverup, store_for):
    st = store_for(coverup)
    for source in ("auth", "collector", "flow", "badge", "shell_history", "fs_stat", "app", "syslog"):
        ev = st.search(source=source, limit=1)[0]
        data = (coverup.raw / ev.artifact_ref.artifact).read_bytes()
        line = data[ev.artifact_ref.byte_offset:].split(b"\n", 1)[0].decode()
        assert line == ev.raw, source


# ----------------------------------------------------------------- step library and answer key
def test_every_executed_step_outcome_is_recorded_including_failures(coverup):
    key = load_answer_key(coverup)
    assert [s.step_name for s in key.steps][:3] == ["login_as", "stage_copy", "exfil_http"]
    assert all(s.execution_status in ("succeeded", "failed", "partial") and s.outcome for s in key.steps)
    failed = [s for s in key.steps if s.execution_status == "failed"]
    assert failed and all(s.effect_id is None for s in failed)  # an attempt is not an effect
    assert {e.effect_type for e in key.effects} == {"data_staging", "policy_violating_transfer", "local_log_removal"}
    assert key.attribution.framed and key.attribution.operator_true != key.attribution.account_owner_person
    assert key.attribution.named_attribution_supportable is False


def test_benign_cases_have_no_adversary_steps_but_record_benign_outcomes(make_episode):
    for variant in BENIGN_VARIANTS:
        key = load_answer_key(make_episode(DEV_SEED, variant))
        assert key.case_kind == "benign" and key.steps == [] and key.effects == []
        assert {"scheduled_rotation", "approved_bulk_transfer", "remote_login"} <= {b.kind for b in key.benign_outcomes}


def test_coverup_removes_the_local_line_but_the_collector_retains_it(coverup, store_for):
    st = store_for(coverup)
    key = load_answer_key(coverup)
    sid = key.attribution.session
    local = st.scan(source="auth", host="workstation", session_id=sid, action="login")
    kept = st.scan(source="collector", origin_host="workstation", session_id=sid, action="login")
    assert local == [] and len(kept) >= 1
    assert st.scan(source="auth", host="workstation", session_id=sid, action="logout")  # orphan close remains


def test_plain_incident_keeps_the_local_login_line(plain, store_for):
    sid = load_answer_key(plain).attribution.session
    assert len(store_for(plain).scan(source="auth", host="workstation", session_id=sid, action="login")) == 1


@pytest.mark.parametrize("bad, why", [
    ([{"step": "run_shell", "params": {"cmd": "id"}}], "not allowed"),
    ([{"step": "login_as", "params": {"account": "root"}}], "account must be one of"),
    ([{"step": "stage_copy", "params": {"src": "patients_full", "dst_dir": "/var/tmp/xfer", "dst_name": "a.db"}}], "requires a prior login_as"),
    ([{"step": "login_as", "params": {"account": "A"}},
      {"step": "stage_copy", "params": {"src": "/etc/shadow", "dst_dir": "/var/tmp/xfer", "dst_name": "a.db"}}], "src must be one of"),
    ([{"step": "login_as", "params": {"account": "A"}},
      {"step": "stage_copy", "params": {"src": "patients_full", "dst_dir": "/etc", "dst_name": "a.db"}}], "dst_dir must be one of"),
    ([{"step": "login_as", "params": {"account": "A"}},
      {"step": "stage_copy", "params": {"src": "patients_full", "dst_dir": "/var/tmp/xfer", "dst_name": "../../x; rm -rf ~"}}], "dst_name must match"),
    ([{"step": "login_as", "params": {"account": "A"}},
      {"step": "stage_copy", "params": {"src": "patients_full", "dst_dir": "/var/tmp/xfer", "dst_name": "abc.db"}},
      {"step": "exfil_http", "params": {"path": "/var/tmp/xfer/abc.db", "dst": "8.8.8.8"}}], "internal sink"),
    ([{"step": "login_as", "params": {"account": "A"}},
      {"step": "exfil_http", "params": {"path": "/etc/passwd", "dst": "10.20.9.12"}}], "staged earlier"),
    ([{"step": "login_as", "params": {"account": "A"}},
      {"step": "delete_log_lines", "params": {"host": "workstation", "file": "/var/log/auth.log", "event_selection": ".*"}}], "event_selection must be one of"),
    ([{"step": "login_as", "params": {"account": "A"}},
      {"step": "delete_log_lines", "params": {"host": "workstation", "file": "/etc/passwd", "event_selection": "own_session_all"}}], "file must be one of"),
    ([{"step": "login_as", "params": {"account": "A"}, "delay_s": 1}], "delay_s must be between"),
    ([{"step": "login_as", "params": {"account": "A"}, "exec": "x"}], "unknown keys"),
    ([{"step": "login_as", "params": {"account": "A"}}] * 9, "maximum is 8"),
])
def test_plan_validation_rejects_anything_outside_the_bounded_library(bad, why):
    ctx = S.PlanContext(level="L2", accounts=("A", "B"), sink_ips=("10.20.9.12",), dataset_sizes={"patients_full": 10})
    with pytest.raises(S.PlanError) as err:
        S.validate_plan(bad, ctx)
    assert why in str(err.value)


def test_level_one_cannot_use_anti_forensics():
    ctx = S.PlanContext(level="L1", accounts=("A",), sink_ips=("10.20.9.12",), dataset_sizes={"patients_full": 10})
    with pytest.raises(S.PlanError):
        S.validate_plan([{"step": "login_as", "params": {"account": "A"}},
                         {"step": "delete_log_lines", "params": {"host": "workstation", "file": "/var/log/auth.log",
                                                                 "event_selection": "own_session_all"}}], ctx)


def test_scripted_plans_pass_their_own_validation():
    for seed in range(1, 13):
        for variant in ("incident_plain", "incident_coverup"):
            spec = build_spec(seed, variant)
            assert S.validate_plan(spec["plan"], plan_context(spec))
            assert spec["plan_source"] == "scripted_scenario"


def test_step_library_exposes_no_shell_or_code_execution():
    names = {n[4:] for n in dir(S.StepExecutor) if n.startswith("_do_")}
    assert names == {"login_as", "stage_copy", "exfil_http", "delete_log_lines",
                     # phase two: still fixed state changes in the simulated world, nothing executable
                     "login_remote", "export_dump", "second_host_session", "stop_forwarder", "clear_history",
                     "timestomp", "falsify_readings"}
    src = (S.__file__ and open(S.__file__).read()) or ""
    for forbidden in ("subprocess", "os.system", "eval(", "exec(", "socket", "requests", "urllib", "httpx"):
        assert forbidden not in src, forbidden
