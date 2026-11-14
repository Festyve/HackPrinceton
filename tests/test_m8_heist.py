"""M8: the Records heist case family.

An export made ON the records server with an administrator's credential, staged there and sent
out from the server; an approved export of the same shape as the control. Everything runs through
the same simulator, normalizer, checks, verifier and scorer as the first family.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta

import pytest

from alibi import checks, checks_families
from alibi.baselines import run_b0, run_br
from alibi.episode import load_answer_key, load_episode_manifest, load_manifest, reproduce_raw_hash, verify_raw_integrity
from alibi.reports import lock_report
from alibi.scoring import score_report
from alibi.sim import steps as S
from alibi.sim.scenario import (
    ALL_VARIANTS,
    CARD_RECORDS_HEIST,
    HEIST_BENIGN_VARIANTS,
    HEIST_INCIDENT_VARIANTS,
    VARIANTS,
    build_spec,
    plan_context,
)
from alibi.sim.world import APP_LOG
from alibi.verifier import verify_report

from .conftest import DEV_SEED
from .helpers import without_sources

GIVEAWAYS = ("attacker", "adversary", "exfil", "sink", "crime", "framed", "malicious", "incident", "truth", "canary", "heist")


def _locked(rep, st, m):
    return lock_report(verify_report(rep, st, m), "skipped_for_benchmark", by_human=False)


def _case(make_episode, store_for, variant, seed=DEV_SEED):
    p = make_episode(seed, variant)
    return p, store_for(p), load_manifest(p), load_answer_key(p)


# ----------------------------------------------------------------- scenario and plan
def test_new_variants_are_additive_and_the_first_family_list_is_untouched():
    assert VARIANTS == ("incident_plain", "incident_coverup", "benign_rotation", "benign_approved_transfer",
                        "benign_remote_login", "benign_collection_gap")
    assert set(HEIST_INCIDENT_VARIANTS + HEIST_BENIGN_VARIANTS) <= set(ALL_VARIANTS) and len(set(ALL_VARIANTS)) == len(ALL_VARIANTS)
    with pytest.raises(ValueError):
        build_spec(1, "heist_everything")


def test_heist_plans_are_scripted_bounded_and_start_on_the_records_server():
    for seed in range(1, 9):
        for variant, level in (("heist_incident", "H1"), ("heist_coverup", "H2")):
            spec = build_spec(seed, variant)
            assert spec["card_id"] == CARD_RECORDS_HEIST and spec["difficulty"] == level
            assert spec["plan_source"] == "scripted_scenario" and spec["case_kind"] == "incident"
            plan = S.validate_plan(spec["plan"], plan_context(spec))
            assert [s["step"] for s in plan][:3] == ["login_remote", "export_dump", "exfil_http"]
            assert spec["crime"]["sink_ip"] != spec["heist"]["partner_ip"]  # never the approved partner
    assert build_spec(3, "heist_approved_export")["plan"] == [] and build_spec(3, "heist_approved_export")["crime"] is None


@pytest.mark.parametrize("level, bad, why", [
    ("H1", [{"step": "login_remote", "params": {"host": "records", "account": "nurse", "via": "vpn-gw"}}], "account must be one of"),
    ("H1", [{"step": "login_remote", "params": {"host": "collector", "account": "adm", "via": "vpn-gw"}}], "host must be one of"),
    ("H1", [{"step": "login_remote", "params": {"host": "records", "account": "adm", "via": "8.8.8.8"}}], "via must be one of"),
    ("H1", [{"step": "export_dump", "params": {"dataset": "patients_full", "dst_dir": "/srv/records/tmp", "dst_name": "a.db"}}],
     "requires a prior session on the records host"),
    ("H1", [{"step": "login_remote", "params": {"host": "records", "account": "adm", "via": "vpn-gw"}},
            {"step": "export_dump", "params": {"dataset": "patients_full", "dst_dir": "/etc", "dst_name": "abc.db"}}], "dst_dir must be one of"),
    ("H1", [{"step": "login_remote", "params": {"host": "records", "account": "adm", "via": "vpn-gw"}},
            {"step": "export_dump", "params": {"dataset": "/etc/shadow", "dst_dir": "/srv/records/tmp", "dst_name": "abc.db"}}],
     "dataset must be one of"),
    ("H1", [{"step": "login_remote", "params": {"host": "records", "account": "adm", "via": "vpn-gw"}},
            {"step": "delete_log_lines", "params": {"host": "records", "file": APP_LOG, "event_selection": "own_exports"}}], "not allowed at H1"),
    ("H2", [{"step": "login_remote", "params": {"host": "records", "account": "adm", "via": "vpn-gw"}},
            {"step": "delete_log_lines", "params": {"host": "workstation", "file": APP_LOG, "event_selection": "own_exports"}}], "host must be one of"),
    ("H2", [{"step": "login_as", "params": {"account": "adm"}}], "not allowed at H2"),
    ("L2", [{"step": "login_remote", "params": {"host": "records", "account": "adm", "via": "vpn-gw"}}], "not allowed at L2"),
    ("L2", [{"step": "login_as", "params": {"account": "A"}},
            {"step": "delete_log_lines", "params": {"host": "workstation", "file": "/var/log/auth.log", "event_selection": "own_exports"}}],
     "event_selection must be one of"),
])
def test_records_steps_are_validated_against_allowlists(level, bad, why):
    ctx = S.PlanContext(level=level, accounts=("A",), sink_ips=("10.20.9.12",), dataset_sizes={"patients_full": 10},
                        admin_accounts=("adm",))
    with pytest.raises(S.PlanError) as err:
        S.validate_plan(bad, ctx)
    assert why in str(err.value)


# ----------------------------------------------------------------- what the simulator produced
def test_heist_runs_on_the_records_server_and_truth_records_what_executed(make_episode, store_for):
    p, st, m, key = _case(make_episode, store_for, "heist_coverup")
    spec = load_episode_manifest(p).scenario_spec
    admin = spec["accounts"]["admin"]
    assert [s.step_name for s in key.steps][:3] == ["login_remote", "export_dump", "exfil_http"]
    assert {e.host for e in key.effects} == {"records"}
    assert {e.effect_type for e in key.effects} == {"data_staging", "policy_violating_transfer", "local_log_removal"}
    assert key.attribution.account_used == admin and key.attribution.session.startswith("records#")
    assert key.attribution.named_attribution_supportable is False
    assert all(s.execution_status in ("succeeded", "failed") and s.outcome for s in key.steps)
    # the session came in through the VPN gateway: nothing in this case happens at the nurse console
    login = st.scan(source="collector", origin_host="records", session_id=key.attribution.session, action="login")
    assert login and login[0].attrs["src_ip"] == "10.20.0.250"
    assert verify_raw_integrity(p) == []
    saved, again = reproduce_raw_hash(p)
    assert saved == again == m.raw_bundle_sha256 and m.normalization_errors == []


def test_heist_evidence_and_manifest_reveal_no_card_plan_or_truth(make_episode):
    for variant in HEIST_INCIDENT_VARIANTS + HEIST_BENIGN_VARIANTS:
        p = make_episode(DEV_SEED, variant)
        key = load_answer_key(p)
        public = json.dumps(json.loads(p.manifest.read_text())).lower()
        assert key.canary.lower() not in public and "records-heist" not in public and variant not in public
        for field in ("seed", "variant", "difficulty", "crime_card", "plan", "operator"):
            assert f'"{field}' not in public, field
        for f in p.raw.rglob("*"):
            if f.is_file():
                body = f.read_text().lower()
                assert key.canary.lower() not in body
                for word in GIVEAWAYS:
                    assert word not in body, (variant, f.name, word)


def test_incident_and_control_have_the_same_shape_tip_and_change_records(make_episode):
    inc = load_manifest(make_episode(DEV_SEED, "heist_coverup"))
    ben = load_manifest(make_episode(DEV_SEED, "heist_approved_export"))
    assert ben.operational_context["tip"] == inc.operational_context["tip"]
    assert set(ben.operational_context) == set(inc.operational_context)
    assert {s.source for s in ben.sources} == {s.source for s in inc.sources}
    for ctx in (inc.operational_context, ben.operational_context):  # the approved export is on file in both
        assert [c["kind"] for c in ctx["change_records"]] == ["bulk_export"]
        assert set(ctx["change_records"][0]) == {"id", "kind", "requested_by", "approved_by", "source_host", "dataset",
                                                 "destination_ip", "destination_name", "window_start", "window_end", "note"}


# ----------------------------------------------------------------- the deterministic baseline finds it
@pytest.mark.parametrize("variant, effects", [("heist_incident", 2), ("heist_coverup", 3)])
def test_br_finds_every_scored_heist_effect_with_resolvable_citations(make_episode, store_for, variant, effects):
    for seed in (DEV_SEED, 6, 9):  # 6 and 9: the approved export postdates the rotation, so both exports are in the live log
        p, st, m, key = _case(make_episode, store_for, variant, seed)
        rep = _locked(run_br(st, m), st, m)
        sc = score_report(rep, key, st)
        assert (sc.step_recall.num, sc.step_recall.den) == (effects, effects), seed
        assert sc.final_precision.value == 1.0 and sc.false_claims_final == 0
        assert sc.evidence_reference_validity.value == 1.0 and sc.evidence_reference_validity.den > 0
        assert sc.account_identification_correct is True and sc.attribution_abstained and not sc.false_accusation
        assert sc.coverup_detected is (True if variant == "heist_coverup" else None)
        assert {f.host for f in rep.findings if f.category == "incident_allegation"} == {"records"}
        assert "Human operator not established" in rep.attribution.statement
        assert rep.attribution.named_person_accused is None and all(f.actor_claimed is None for f in rep.findings)


def test_the_keyword_recipe_misses_the_removed_export_record(make_episode, store_for):
    p, st, m, key = _case(make_episode, store_for, "heist_coverup")
    sc = score_report(_locked(run_b0(st, m), st, m), key, st)
    assert sc.coverup_detected is False
    assert [o.effect_type for o in sc.effect_outcomes if o.outcome == "missed"] == ["local_log_removal"]


def test_the_export_record_is_gone_from_the_server_log_and_kept_by_the_collector(make_episode, store_for):
    p, st, m, key = _case(make_episode, store_for, "heist_coverup")
    admin = key.attribution.account_used
    eff = next(e for e in key.effects if e.effect_type == "local_log_removal")
    local = [e for e in st.scan(source="app", action="export_bulk", actor=admin) if e.ts >= eff.t_start - timedelta(seconds=5)]
    kept = [e for e in st.scan(source="collector", action="export_bulk", actor=admin)
            if datetime.fromisoformat(e.attrs["inner_ts"]) >= eff.t_start - timedelta(seconds=5)]
    assert local == [] and len(kept) >= 1 and eff.object == APP_LOG and eff.host == "records"
    f = next(x for x in checks.reconcile_logs(st, m)["files"] if (x["host"], x["file"]) == ("records", APP_LOG))
    row = f["unexplained_local_absence"][0]
    assert f["status"] == "unexplained_local_absence" and row["bracket_before_id"] and row["bracket_after_id"]
    assert "action=export_bulk" in row["line"] and "client=127.0.0.1" in row["line"]


def test_an_attempt_against_the_collector_is_recorded_as_failed_and_never_scored(make_episode):
    seed = next(s for s in range(1, 40) if any(st["params"].get("host") == "collector" for st in build_spec(s, "heist_coverup")["plan"]))
    key = load_answer_key(make_episode(seed, "heist_coverup"))
    failed = [s for s in key.steps if s.execution_status == "failed"]
    assert len(failed) == 1 and failed[0].host == "collector" and failed[0].effect_id is None
    assert "not writable" in failed[0].outcome and len(key.effects) == 3


# ----------------------------------------------------------------- approvals
def test_the_approved_export_control_alleges_nothing(make_episode, store_for):
    for seed in (DEV_SEED, 6, 11):
        p, st, m, key = _case(make_episode, store_for, "heist_approved_export", seed)
        assert key.case_kind == "benign" and key.steps == [] and key.effects == []
        for run in (run_br, run_b0):
            sc = score_report(_locked(run(st, m), st, m), key, st)
            assert sc.benign_false_alert is False and sc.final_accepted_incident == 0, (seed, run.__name__)
        rep = verify_report(run_br(st, m), st, m)
        assert not [f for f in rep.findings if f.category == "incident_allegation"]
        partner = m.operational_context["change_records"][0]["destination_ip"]
        ok = next(f for f in rep.findings if f.claim_type == "policy_consistent_transfer" and partner in (f.object_or_session or ""))
        assert "change record" in ok.rationale and ok.verification_status == "supported_observation"
        assert rep.attribution.human_identity == "not_assessed"


def test_a_change_record_covers_only_the_export_it_names(make_episode, store_for):
    p, st, m, key = _case(make_episode, store_for, "heist_incident")
    ctx = m.operational_context
    cr = ctx["change_records"][0]
    inside = datetime.fromisoformat(cr["window_start"]) + timedelta(minutes=5)
    assert checks.export_approval_for(ctx, "records", cr["destination_ip"], inside)["id"] == cr["id"]
    assert checks.export_approval_for(ctx, "records", "10.20.9.250", inside) is None  # another destination
    assert checks.export_approval_for(ctx, "workstation", cr["destination_ip"], inside) is None  # another source host
    assert checks.export_approval_for(ctx, "records", cr["destination_ip"], inside + timedelta(hours=3)) is None  # outside the window
    assert checks.export_approval_for({}, "records", cr["destination_ip"], inside) is None  # no records stated

    rows = checks.correlate_transfers(st, m)["transfers"]
    approved = next(t for t in rows if t["dst"] == cr["destination_ip"])
    assert approved["policy_status"] == "approved" and approved["change_record_id"] == cr["id"]
    bad = [t for t in rows if t["policy_status"] == "not_approved"]
    assert len(bad) == 1 and bad[0]["src_host"] == "records" and "no approved change record" in bad[0]["policy_note"]
    assert bad[0]["session_link"] == "single_overlapping_session" and bad[0]["sessions"][0]["origin"] == "remote"
    assert bad[0]["staged_object"]["export_event_ids"]  # the export made on the server itself is linked to its file


def test_export_review_tells_scheduled_approved_and_unapproved_exports_apart(make_episode, store_for):
    p, st, m, key = _case(make_episode, store_for, "heist_incident")
    res = checks_families.review_exports(st, m)
    assert res["status"] == "unapproved_export_present" and res["coverage_limits"] == []
    by = {}
    for r in res["exports"]:
        by.setdefault(r["approval"]["status"], []).append(r)
    assert {"scheduled_job", "approved_change_record", "no_covering_change_record"} <= set(by)
    bad = by["no_covering_change_record"]
    assert len(bad) == 1 and bad[0]["made_on_records_server"] and bad[0]["dataset"] == "patients_full"
    assert bad[0]["user"] == key.attribution.account_used
    assert bad[0]["linked_transfers"] and bad[0]["linked_transfers"][0]["policy_status"] == "not_approved"
    assert set(bad[0]["record_seen_in"]) == {"records-app log", "collector copy"}
    assert st.existing_ids(bad[0]["local_event_ids"] + bad[0]["collector_event_ids"])
    ok = by["approved_change_record"][0]
    assert ok["dataset"] == "immunization_registry" and ok["linked_transfers"][0]["policy_status"] == "approved"
    assert by["scheduled_job"][0]["user"] == "svc-backup" and by["scheduled_job"][0]["approval"]["evidence_ids"]
    control = checks_families.review_exports(*_case(make_episode, store_for, "heist_approved_export")[1:3])
    assert control["status"] == "all_exports_accounted_for"


# ----------------------------------------------------------------- absent witnesses are unknown, not clean
def test_without_the_collector_the_removed_record_cannot_be_shown_and_nothing_is_invented(make_episode, tmp_path):
    p = make_episode(DEV_SEED, "heist_coverup")
    st, m = without_sources(p, tmp_path, {"collector"})
    rec = checks.reconcile_logs(st, m)
    assert {f["status"] for f in rec["files"]} == {"not_assessable"} and rec["coverage"]["collector_present"] is False
    rep = verify_report(run_br(st, m), st, m)
    claims = {f.claim_type for f in rep.findings if f.category == "incident_allegation"}
    assert "local_log_removal" not in claims  # the server's own log looks complete; without a witness that is unknown
    assert {"policy_violating_transfer", "data_staging"} <= claims  # the tap and the file metadata still show these
    assert any(q.startswith("Coverage limit:") and "collector" in q.lower() for q in rep.open_questions)
    assert "unknown" in rep.summary
    exp = checks_families.review_exports(st, m)
    assert any("collector" in x for x in exp["coverage_limits"])
    st.close()


def test_without_the_tap_transfers_are_unknown_and_no_transfer_is_alleged(make_episode, tmp_path):
    p = make_episode(DEV_SEED, "heist_incident")
    st, m = without_sources(p, tmp_path, {"flow"})
    assert checks.correlate_transfers(st, m)["status"] == "not_assessable"
    rep = verify_report(run_br(st, m), st, m)
    assert not [f for f in rep.findings if f.category == "incident_allegation"]
    assert any("flow source" in q for q in rep.open_questions)
    exp = checks_families.review_exports(st, m)
    assert exp["status"] == "unapproved_export_present"  # the export record itself is still there ...
    assert all(r["linked_transfers"] == [] for r in exp["exports"])  # ... but where the data went is unknown
    assert any("flow source" in x for x in exp["coverage_limits"])
    st.close()


def test_without_any_copy_of_the_application_log_exports_are_not_assessable(make_episode, tmp_path):
    p = make_episode(DEV_SEED, "heist_incident")
    st, m = without_sources(p, tmp_path, {"app", "collector"})
    exp = checks_families.review_exports(st, m)
    assert exp["status"] == "not_assessable" and exp["exports"] == [] and "unknown" in exp["status_reason"]
    st.close()
