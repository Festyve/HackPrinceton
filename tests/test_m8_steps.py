"""M8: the four remaining bounded steps and their legitimate counterparts.

  clear_history        <-> charting through the touch-screen client (no shell history is written)
  timestomp            <-> an administrator's archive restore (old modification times, new change time)
  stop_forwarder       <-> a forwarder stop under an approved change record
  second_host_session  <-> an administrator hop to the records server under the same record

Each step is a state change in the simulated world. A step whose effect no captured source can
show is recorded as unobservable and is never scored.
"""

from __future__ import annotations

import json
import random
from datetime import datetime, timedelta

import pytest

from alibi import checks, checks_families
from alibi.baselines import run_b0, run_br
from alibi.contracts import Finding
from alibi.episode import load_answer_key, load_episode_manifest, load_manifest, reproduce_raw_hash
from alibi.reports import lock_report
from alibi.scoring import score_report
from alibi.sim import steps as S
from alibi.sim.scenario import build_spec, plan_context
from alibi.sim.world import IPS, World, logical_clock_base
from alibi.verifier import compute_observations, verify_finding, verify_report

from .conftest import DEV_SEED
from .helpers import without_sources

GIVEAWAYS = ("attacker", "adversary", "exfil", "sink", "crime", "framed", "malicious", "incident", "truth", "canary")
LOGIN = {"step": "login_as", "params": {"account": "A"}}
STAGE = {"step": "stage_copy", "params": {"src": "patients_full", "dst_dir": "/var/tmp/xfer", "dst_name": "abc.db"}}


def _locked(rep, st, m):
    return lock_report(verify_report(rep, st, m), "skipped_for_benchmark", by_human=False)


def _case(make_episode, store_for, variant, seed=DEV_SEED):
    p = make_episode(seed, variant)
    return p, store_for(p), load_manifest(p), load_answer_key(p)


def _step(key, name, status="succeeded"):
    return next(s for s in key.steps if s.step_name == name and s.execution_status == status)


# ----------------------------------------------------------------- validation
@pytest.mark.parametrize("bad, why", [
    ([LOGIN, {"step": "clear_history", "params": {"scope": "everything; rm -rf ~"}}], "scope must be one of"),
    ([{"step": "clear_history", "params": {"scope": "all"}}], "requires a prior login"),
    ([LOGIN, {"step": "timestomp", "params": {"path": "/etc/passwd", "mode": "backdate_30d"}}], "staged earlier"),
    ([LOGIN, STAGE, {"step": "timestomp", "params": {"path": "/var/tmp/xfer/abc.db", "mode": "1999-01-01"}}], "mode must be one of"),
    ([LOGIN, {"step": "stop_forwarder", "params": {"host": "collector", "duration_s": 120}}], "host must be one of"),
    ([LOGIN, {"step": "stop_forwarder", "params": {"host": "workstation", "duration_s": 86400}}], "duration_s must be"),
    ([LOGIN, {"step": "stop_forwarder", "params": {"host": "workstation", "duration_s": True}}], "duration_s must be"),
    ([LOGIN, {"step": "stop_forwarder", "params": {"host": "workstation", "duration_s": 120, "cmd": "kill -9"}}], "takes host, duration_s"),
    ([{"step": "stop_forwarder", "params": {"host": "workstation", "duration_s": 120}}], "requires a prior login"),
    ([LOGIN, {"step": "second_host_session", "params": {"host": "collector", "account": "adm"}}], "host must be one of"),
    ([LOGIN, {"step": "second_host_session", "params": {"host": "records", "account": "A"}}], "account must be one of"),
    ([{"step": "second_host_session", "params": {"host": "records", "account": "adm"}}], "requires a prior login_as"),
    ([LOGIN, {"step": "second_host_session", "params": {"host": "records", "account": "adm"}},
      {"step": "second_host_session", "params": {"host": "records", "account": "adm"}}], "already open"),
])
def test_the_new_steps_take_only_allowlisted_parameters(bad, why):
    ctx = S.PlanContext(level="L3", accounts=("A",), sink_ips=("10.20.9.12",), dataset_sizes={"patients_full": 10},
                        admin_accounts=("adm",))
    with pytest.raises(S.PlanError) as err:
        S.validate_plan(bad, ctx)
    assert why in str(err.value)


def test_earlier_levels_cannot_use_the_new_steps_and_scripted_plans_validate():
    for level in ("L1", "L2"):
        ctx = S.PlanContext(level=level, accounts=("A",), sink_ips=("10.20.9.12",), dataset_sizes={"patients_full": 10},
                            admin_accounts=("adm",))
        for step in ({"step": "clear_history", "params": {"scope": "all"}},
                     {"step": "stop_forwarder", "params": {"host": "workstation", "duration_s": 120}},
                     {"step": "second_host_session", "params": {"host": "records", "account": "adm"}}):
            with pytest.raises(S.PlanError):
                S.validate_plan([LOGIN, step], ctx)
    for seed in range(1, 9):
        spec = build_spec(seed, "incident_evasion")
        plan = S.validate_plan(spec["plan"], plan_context(spec))
        assert spec["difficulty"] == "L3" and spec["plan_source"] == "scripted_scenario" and len(plan) == 8
        assert {s["step"] for s in plan} >= {"clear_history", "timestomp", "stop_forwarder", "second_host_session"}
    for meta in S.ATTACK_META.values():  # no unverified technique id is ever cited for a phase-two step
        assert meta["label"]
    assert all(S.ATTACK_META[s]["attack_id"] is None
               for s in ("clear_history", "timestomp", "stop_forwarder", "second_host_session", "falsify_readings"))


# ----------------------------------------------------------------- preconditions and recorded failures
def _world() -> tuple[World, S.StepExecutor, datetime]:
    t0 = logical_clock_base() + timedelta(hours=9)
    w = World(random.Random(7), t0 - timedelta(hours=1), t0 + timedelta(hours=2))
    ctx = S.PlanContext(level="L3", accounts=("nurse",), sink_ips=("10.20.9.12",), dataset_sizes={"patients_full": 9_000_000},
                        admin_accounts=("adm",))
    return w, S.StepExecutor(w, ctx), t0


def test_each_step_fails_cleanly_when_its_precondition_is_not_met():
    w, ex, t0 = _world()
    for step in ({"step": "clear_history", "params": {"scope": "all"}},
                 {"step": "timestomp", "params": {"path": "/var/tmp/xfer/abc.db", "mode": "backdate_30d"}},
                 {"step": "stop_forwarder", "params": {"host": "workstation", "duration_s": 120}},
                 {"step": "second_host_session", "params": {"host": "records", "account": "adm"}}):
        res = ex.execute(step, t0)
        assert res.status == "failed" and res.effect_type is None and "no active" in res.outcome, step["step"]
    assert w.forwarder_down == {} and w.sessions == {} and w.flows == []  # nothing changed in the world

    ex.execute(LOGIN | {"params": {"account": "nurse"}}, t0 + timedelta(seconds=10))
    none = ex.execute({"step": "clear_history", "params": {"scope": "own_session"}}, t0 + timedelta(seconds=20))
    assert none.status == "failed" and "no shell-history entries" in none.outcome
    gone = ex.execute({"step": "timestomp", "params": {"path": "/var/tmp/xfer/abc.db", "mode": "backdate_30d"}}, t0 + timedelta(seconds=30))
    assert gone.status == "failed" and "does not exist" in gone.outcome
    # a nurse account may not control services: a denied attempt, logged like any denied privileged command
    denied = ex.execute({"step": "stop_forwarder", "params": {"host": "workstation", "duration_s": 120}}, t0 + timedelta(seconds=40))
    assert denied.status == "failed" and "permission denied" in denied.outcome and denied.effect_type is None
    assert w.forwarder_down == {} and "NOT in sudoers" in denied.traces[0].raw
    nowhere = ex.execute({"step": "stop_forwarder", "params": {"host": "records", "duration_s": 120}}, t0 + timedelta(seconds=50))
    assert nowhere.status == "failed" and "no active session on records" in nowhere.outcome
    hop = ex.execute({"step": "second_host_session", "params": {"host": "records", "account": "adm"}}, t0 + timedelta(seconds=60))
    again = ex.execute({"step": "second_host_session", "params": {"host": "records", "account": "adm"}}, t0 + timedelta(seconds=70))
    assert hop.status == "succeeded" and again.status == "failed" and "already open" in again.outcome
    ok = ex.execute({"step": "stop_forwarder", "params": {"host": "records", "duration_s": 120}}, t0 + timedelta(seconds=80))
    assert ok.status == "succeeded" and ok.effect_type == "forwarding_stopped" and ok.observable
    assert w.forwarder_down["records"] == [(t0 + timedelta(seconds=81), t0 + timedelta(seconds=201))]


def test_a_backdated_file_with_no_independent_arrival_record_is_unobservable():
    """An export made while forwarding is down has no collector copy, and a local export has no flow."""
    w, ex, t0 = _world()
    ex.ctx.level = "H2"
    ex.execute({"step": "login_remote", "params": {"host": "records", "account": "adm", "via": "vpn-gw"}}, t0)
    ex.execute({"step": "stop_forwarder", "params": {"host": "records", "duration_s": 600}}, t0 + timedelta(seconds=20))
    dump = ex.execute({"step": "export_dump", "params": {"dataset": "patients_full", "dst_dir": "/srv/records/tmp", "dst_name": "abc.db"}},
                      t0 + timedelta(seconds=60))
    res = ex.execute({"step": "timestomp", "params": {"path": "/srv/records/tmp/abc.db", "mode": "backdate_30d"}}, t0 + timedelta(seconds=120))
    assert dump.status == res.status == "succeeded" and res.effect_type == "timestamp_alteration"
    assert res.observable is False and "no independent record" in res.unobservable_reason
    st = w.files["records"]["/srv/records/tmp/abc.db"]
    assert st["ctime"] == t0 + timedelta(seconds=120) and st["ctime"] - st["mtime"] > timedelta(days=29)


# ----------------------------------------------------------------- the executed incident
def test_every_step_outcome_is_recorded_and_only_observable_effects_can_be_scored(make_episode, store_for):
    p, st, m, key = _case(make_episode, store_for, "incident_evasion")
    assert [s.step_name for s in key.steps] == ["login_as", "stage_copy", "exfil_http", "timestomp", "stop_forwarder",
                                                "second_host_session", "stop_forwarder", "clear_history"]
    denied = _step(key, "stop_forwarder", "failed")
    assert denied.host == "workstation" and denied.effect_id is None and "permission denied" in denied.outcome
    by_type = {e.effect_type: e for e in key.effects}
    assert set(by_type) == {"data_staging", "policy_violating_transfer", "timestamp_alteration", "second_host_session",
                            "forwarding_stopped", "shell_history_removal"}
    hidden = by_type["shell_history_removal"]
    assert hidden.observable is False and "not forwarded" in hidden.unobservable_reason
    assert all(e.observable for t, e in by_type.items() if t != "shell_history_removal")
    saved, again = reproduce_raw_hash(p)
    assert saved == again and m.normalization_errors == []

    sc = score_report(_locked(run_br(st, m), st, m), key, st)
    assert (sc.step_recall.num, sc.step_recall.den) == (5, 5)  # the unobservable effect is not in the denominator
    assert sc.unobservable_effects == 1 and sc.failed_or_partial_steps == 1
    assert [o.effect_type for o in sc.effect_outcomes if o.outcome == "unobservable"] == ["shell_history_removal"]
    assert sc.final_precision.value == 1.0 and sc.evidence_reference_validity.value == 1.0
    assert sc.coverup_detected is True and sc.account_identification_correct is True and sc.attribution_abstained


def test_cleared_history_is_reported_as_an_open_observation_never_an_allegation(make_episode, store_for):
    p, st, m, key = _case(make_episode, store_for, "incident_evasion")
    sid, account = key.attribution.session, key.attribution.account_used
    login, cleared = _step(key, "login_as"), _step(key, "clear_history")
    during = [e for e in st.scan(source="shell_history", host="workstation", actor=account)
              if login.t_start <= e.ts <= cleared.t_start]
    assert during == []  # the commands of that session are gone from the host, and nothing else held them
    assert st.scan(source="shell_history", host="workstation", actor=account)  # the account's other history is intact
    res = checks_families.review_shell_history(st, m)
    row = next(r for r in res["sessions"] if r["session_id"] == sid)
    assert row["classification"] == "no_history_for_session" and row["requests_without_history_command"] >= 1
    assert any("touch-screen" in x for x in res["limits"])
    rep = verify_report(run_br(st, m), st, m)
    note = next(f for f in rep.findings if f.claim_type == "shell_history_gap" and f.object_or_session == sid)
    assert note.category == "unresolved" and note.verification_status == "supported_observation"
    assert "cannot show that anything was removed" in note.rationale
    # even a system that alleges it gets no credit: the effect is not observable, so it is not scorable
    claim = note.model_copy(update={"id": "X-1", "category": "incident_allegation", "claim_type": "other",
                                    "status": "proposed", "verification_status": "not_checked"})
    sc = score_report(_locked(rep.model_copy(update={"findings": [claim]}), st, m), key, st)
    assert sc.step_recall.num == 0 and sc.final_accepted_incident == 0


def test_a_backdated_staged_file_is_found_through_independent_arrival_records(make_episode, store_for):
    p, st, m, key = _case(make_episode, store_for, "incident_evasion")
    eff = next(e for e in key.effects if e.effect_type == "timestamp_alteration")
    row = next(e for e in st.scan(source="fs_stat", host="workstation") if e.object == eff.object)
    ctime = datetime.fromisoformat(row.attrs["ctime"])
    assert ctime == eff.t_start and ctime - row.ts > timedelta(days=29)
    # the first-run staging rule looks for a file MODIFIED shortly before the transfer, so it no longer sees this one
    bad = next(t for t in checks.correlate_transfers(st, m)["transfers"] if t["policy_status"] == "not_approved")
    assert bad["staged_object"] is None
    res = checks_families.review_file_times(st, m)
    hit = next(r for r in res["files"] if r["path"] == eff.object)
    assert res["status"] == "contradiction_present" and hit["classification"] == "contradicted_by_independent_records"
    assert hit["retrieval_flow_event_ids"] and hit["export_event_ids"] and hit["linked_transfer"]["policy_status"] == "not_approved"
    assert st.get(hit["retrieval_flow_event_ids"])[0].source == "flow"  # the tap, which the host cannot write
    rep = verify_report(run_br(st, m), st, m)
    stomp = next(f for f in rep.findings if f.claim_type == "timestamp_alteration")
    staged = next(f for f in rep.findings if f.claim_type == "data_staging")
    assert stomp.status == staged.status == "verified" and stomp.object_or_session == staged.object_or_session == eff.object
    assert row.id in stomp.evidence_ids and "who changed it is not shown" in stomp.rationale


def test_a_forwarding_stop_leaves_a_gap_and_a_recorded_command_at_the_collector(make_episode, store_for):
    p, st, m, key = _case(make_episode, store_for, "incident_evasion")
    eff = next(e for e in key.effects if e.effect_type == "forwarding_stopped")
    admin = load_episode_manifest(p).scenario_spec["accounts"]["admin"]
    res = checks_families.review_forwarding(st, m)
    gap = next(g for g in res["gaps"] if g["host"] == "records")
    assert abs(gap["seconds"] - (eff.t_end - eff.t_start).total_seconds()) <= 25
    assert gap["policy_status"] == "outside_approved_maintenance" and gap["stopped_by_account"] == admin
    cmds = st.get(gap["stop_command_event_ids"])
    assert {e.source for e in cmds} == {"auth", "collector"}  # the command reached the collector before forwarding stopped
    assert [g for g in res["gaps"] if g["host"] == "workstation"] == []  # the denied attempt there stopped nothing
    denied = [e for e in st.scan(source="auth", host="workstation") if "NOT in sudoers" in e.raw]
    assert len(denied) == 1
    during = [e for e in st.scan(source="auth", host="records") if eff.t_start + timedelta(seconds=2) <= e.ts < eff.t_end]
    held = {e.attrs["inner_raw"] for e in st.scan(source="collector", origin_host="records")}
    assert all(e.raw not in held for e in during)
    rep = verify_report(run_br(st, m), st, m)
    claim = next(f for f in rep.findings if f.claim_type == "forwarding_stopped")
    assert claim.host == "records" and claim.status == "verified" and claim.account_used == admin
    assert not [f for f in rep.findings if f.claim_type == "forwarding_stopped" and f.host == "workstation"]


def test_a_second_host_session_is_tied_to_the_source_host_by_auth_and_tap_records(make_episode, store_for):
    p, st, m, key = _case(make_episode, store_for, "incident_evasion")
    eff = next(e for e in key.effects if e.effect_type == "second_host_session")
    res = checks_families.link_sessions(st, m)
    hop = next(s for s in res["sessions"] if s["session"]["session_id"] == eff.session)
    assert hop["target_host"] == "records" and hop["source_host"] == "workstation" and hop["source_ip"] == IPS["workstation"]
    assert hop["policy_status"] == "outside_stated_policy" and hop["account_role"] == "it-admin"
    assert [s["session_id"] for s in hop["source_host_sessions"]] == [key.attribution.session]
    assert st.get(hop["connection_flow_event_ids"])[0].attrs["dport"] == 22
    assert any("not who opened the second session" in x for x in res["limits"])
    # the administrator's ordinary sessions from the administrator laptop are not cross-host sessions at all
    assert all(s["source_host"] in ("workstation", "records") for s in res["sessions"])
    rep = verify_report(run_br(st, m), st, m)
    claim = next(f for f in rep.findings if f.claim_type == "second_host_session")
    assert claim.status == "verified" and claim.object_or_session == eff.session and claim.actor_claimed is None


# ----------------------------------------------------------------- the legitimate counterparts
def test_the_maintenance_control_contains_all_four_counterparts_and_alleges_nothing(make_episode, store_for):
    for seed in (DEV_SEED, 2, 9):
        p, st, m, key = _case(make_episode, store_for, "benign_maintenance", seed)
        assert key.case_kind == "benign" and key.steps == [] and key.effects == []
        assert {"approved_forwarder_stop", "restore_from_backup", "approved_second_host_session",
                "touch_screen_session"} <= {b.kind for b in key.benign_outcomes}
        for run in (run_br, run_b0):
            sc = score_report(_locked(run(st, m), st, m), key, st)
            assert sc.benign_false_alert is False and sc.final_accepted_incident == 0, (seed, run.__name__)
        obs = checks_families.observations(st, m)
        gap = next(g for g in obs["forwarding"]["gaps"] if g["host"] == "workstation")
        assert gap["policy_status"] == "covered_by_change_record" and gap["stop_command_event_ids"]
        files = obs["file_times"]["files"]
        assert len(files) == 3 and {r["classification"] for r in files} == {"explained_restore"}
        assert all(r["restore_event_ids"] and r["change_record_id"] for r in files)
        hop = obs["cross_host"]["sessions"]
        assert len(hop) == 1 and hop[0]["policy_status"] == "covered_by_change_record"
        assert any(r["classification"] == "no_history_for_session" for r in obs["shell_history"]["sessions"])
        rep = verify_report(run_br(st, m), st, m)
        assert not [f for f in rep.findings if f.category == "incident_allegation"]
        kinds = {f.claim_type for f in rep.findings}
        assert {"policy_consistent_access", "metadata_change", "shell_history_gap", "collection_gap"} <= kinds
        assert all(f.verification_status == "supported_observation" for f in rep.findings
                   if f.claim_type in checks_families.NOTE_CLAIMS)
        assert rep.attribution.human_identity == "not_assessed"


def test_approval_is_what_makes_the_same_actions_legitimate(make_episode, store_for):
    """The control's evidence, read against different operating knowledge."""
    p, st, m, key = _case(make_episode, store_for, "benign_maintenance")
    ctx = m.operational_context
    # 1. the same shift with no approved change on file: the stop and the hop are now outside policy
    unapproved = m.model_copy(update={"operational_context": {**ctx, "change_records": []}})
    claims = {f.claim_type for f in verify_report(run_br(st, unapproved), st, unapproved).findings
              if f.category == "incident_allegation" and f.status == "verified"}
    assert claims == {"forwarding_stopped", "second_host_session"}  # the restore is still a recorded restore
    # 2. no change records and no administrator-source policy STATED: that is unknown, not a violation
    rap = {k: v for k, v in ctx["remote_access_policy"].items() if k != "admin_sources"}
    silent = m.model_copy(update={"operational_context": {**{k: v for k, v in ctx.items() if k != "change_records"},
                                                          "remote_access_policy": rap}})
    obs = checks_families.observations(st, silent)
    assert obs["forwarding"]["gaps"][0]["policy_status"] == "policy_not_stated"
    assert obs["cross_host"]["sessions"][0]["policy_status"] == "policy_not_stated"
    assert not [f for f in run_br(st, silent).findings if f.category == "incident_allegation"]


def test_incident_and_control_share_shape_tip_and_reveal_nothing(make_episode):
    inc = load_manifest(make_episode(DEV_SEED, "incident_evasion"))
    ben = load_manifest(make_episode(DEV_SEED, "benign_maintenance"))
    old = load_manifest(make_episode(DEV_SEED, "incident_coverup"))
    assert inc.operational_context["tip"] == ben.operational_context["tip"] == old.operational_context["tip"]
    assert set(inc.operational_context) == set(ben.operational_context)
    assert [c["kind"] for c in inc.operational_context["change_records"]] == ["maintenance"] == \
        [c["kind"] for c in ben.operational_context["change_records"]]
    assert {s.source for s in inc.sources} == {s.source for s in ben.sources} == {s.source for s in old.sources}
    for variant in ("incident_evasion", "benign_maintenance"):
        p = make_episode(DEV_SEED, variant)
        canary = load_answer_key(p).canary.lower()
        public = json.dumps(json.loads(p.manifest.read_text())).lower()
        assert canary not in public and variant not in public
        for field in ("seed", "variant", "difficulty", "crime_card", "plan", "operator"):
            assert f'"{field}' not in public, field
        for f in p.raw.rglob("*"):
            if f.is_file():
                body = f.read_text().lower()
                assert canary not in body and not [w for w in GIVEAWAYS if w in body], (variant, f.name)


# ----------------------------------------------------------------- absent witnesses and first-run bundles
def test_absent_witnesses_make_these_claims_unknown_not_clean_and_not_alleged(make_episode, tmp_path):
    p = make_episode(DEV_SEED, "incident_evasion")
    st, m = without_sources(p, tmp_path, {"flow", "app", "collector"})
    obs = checks_families.observations(st, m)
    assert obs["forwarding"]["status"] == "not_assessable" and "unknown" in obs["forwarding"]["status_reason"]
    stomp = next(r for r in obs["file_times"]["files"] if r["gap_seconds"] > 86400)
    assert stomp["classification"] == "unexplained_metadata_change"  # nothing independent is left to contradict it
    rep = verify_report(run_br(st, m), st, m)
    claims = {f.claim_type for f in rep.findings if f.category == "incident_allegation"}
    assert not claims & {"timestamp_alteration", "forwarding_stopped", "data_staging", "policy_violating_transfer"}
    assert any(f.claim_type == "metadata_change" and f.category == "unresolved" for f in rep.findings)
    limits = [q for q in rep.open_questions if q.startswith("Coverage limit:")]
    assert any("collector" in q.lower() for q in limits) and any("flow" in q.lower() for q in limits)
    assert "unknown" in rep.summary
    st.close()

    st, m = without_sources(p, tmp_path, {"fs_stat"})
    res = checks_families.review_file_times(st, m)
    assert res["status"] == "not_assessable" and res["files"] == []
    st.close()
    st, m = without_sources(p, tmp_path, {"auth", "collector"})
    assert checks_families.link_sessions(st, m)["status"] == "not_assessable"
    assert checks_families.review_shell_history(st, m)["status"] == "not_assessable"
    st.close()


def test_first_run_bundles_get_no_phase_two_observations_or_findings(coverup, store_for):
    st, m = store_for(coverup), load_manifest(coverup)
    assert checks_families.applies(m) is False and checks_families.observations(st, m) == {}
    assert checks_families.findings({}) == [] and compute_observations(st, m).families == {}
    ev = st.scan(source="auth", host="workstation")[0]
    claim = Finding(id="X-1", claim_type="forwarding_stopped", category="incident_allegation", host="workstation",
                    t_start=ev.ts, t_end=ev.ts, object_or_session="log-forwarder", evidence_ids=[ev.id])
    out = verify_finding(claim, st, compute_observations(st, m))
    assert out.status == "proposed" and out.verification_status == "unresolved_interpretation"
    assert "does not carry the operating context" in out.verifier_notes[0]
