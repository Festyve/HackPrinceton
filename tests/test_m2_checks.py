"""M2: deterministic contradiction checks, with positive, benign, incomplete-source and ambiguous cases."""

from __future__ import annotations

from datetime import datetime

import pytest

from alibi import checks
from alibi.baselines import run_br
from alibi.episode import load_answer_key, load_manifest
from alibi.sim.scenario import BENIGN_VARIANTS, VARIANTS, build_spec

from .conftest import DEV_SEED
from .helpers import auth_close, auth_open, context, flow, fwd, hb, mini_case, ts


def _file(rec, host, path):
    return next(f for f in rec["files"] if f["host"] == host and f["file"] == path)


def _seed_where(variant: str, pred, seeds=range(1, 40)) -> int:
    return next(s for s in seeds if pred(build_spec(s, variant)))


# ----------------------------------------------------------------- local vs collector
def test_recovers_the_line_the_collector_retained(coverup, store_for):
    st, m, key = store_for(coverup), load_manifest(coverup), load_answer_key(coverup)
    f = _file(checks.reconcile_logs(st, m), "workstation", "/var/log/auth.log")
    assert f["status"] == "unexplained_local_absence"
    rows = f["unexplained_local_absence"]
    assert len(rows) >= 1
    row = rows[0]
    assert "session opened for user " + key.attribution.account_used in row["line"]
    assert row["session_id"] == key.attribution.session
    kept = st.get([row["collector_event_id"]])[0]
    assert kept.source == "collector" and kept.attrs["inner_raw"] == row["line"]
    before, after = st.get([row["bracket_before_id"]])[0], st.get([row["bracket_after_id"]])[0]
    line_ts = datetime.fromisoformat(row["line_ts"])
    assert before.host == after.host == "workstation" and before.ts <= line_ts <= after.ts  # bracketed locally
    assert st.scan(source="auth", host="workstation", text_contains=row["line"]) == []  # really gone locally


def test_plain_incident_and_benign_cases_have_no_unexplained_absence(make_episode, store_for):
    for variant in ("incident_plain", *BENIGN_VARIANTS):
        p = make_episode(DEV_SEED, variant)
        rec = checks.reconcile_logs(store_for(p), load_manifest(p))
        assert all(not f["unexplained_local_absence"] for f in rec["files"]), variant


def test_routine_rotation_is_explained_by_retention_in_every_case(make_episode, store_for):
    for variant in VARIANTS:
        p = make_episode(DEV_SEED, variant)
        f = _file(checks.reconcile_logs(store_for(p), load_manifest(p)), "records", "/var/log/records-app/access.log")
        assert f["retention_explained_absence"]["count"] > 50, variant  # looks alarming to a naive diff
        assert f["coverage_basis"] == "rotation_record" and f["coverage_boundary_event_ids"]
        assert f["unexplained_local_absence"] == []


def test_forced_second_rotation_on_the_tampered_file_is_still_benign(make_episode, store_for):
    p = make_episode(DEV_SEED, "benign_rotation")
    st, m = store_for(p), load_manifest(p)
    f = _file(checks.reconcile_logs(st, m), "workstation", "/var/log/auth.log")
    assert len(f["rotations"]) == 2 and f["rotations"][-1]["discarded_previous"] is True
    assert f["status"] == "retention_explained_only" and f["retention_explained_absence"]["count"] > 0
    rep = run_br(st, m)
    assert not [x for x in rep.findings if x.category == "incident_allegation"]
    assert any(x.claim_type == "retention_explained_absence" and x.host == "workstation" for x in rep.findings)


def test_collection_gap_is_reported_as_a_gap_not_as_an_incident(make_episode, store_for):
    for cause, label in (("agent_restart", "recorded_service_restart"), ("transport_loss", "unknown")):
        seed = _seed_where("benign_collection_gap", lambda s: s["benign"]["cause"] == cause)
        p = make_episode(seed, "benign_collection_gap")
        st, m = store_for(p), load_manifest(p)
        rec = checks.reconcile_logs(st, m)
        gaps = [g for g in rec["heartbeat_gaps"] if g["host"] == "workstation"]
        want = build_spec(seed, "benign_collection_gap")["benign"]["duration_s"]
        assert len(gaps) == 1 and abs(gaps[0]["seconds"] - want) <= 20 and gaps[0]["cause"] == label
        f = _file(rec, "workstation", "/var/log/auth.log")
        assert f["missing_at_collector"]["in_heartbeat_gap"] >= 1 and f["unexplained_local_absence"] == []
        rep = run_br(st, m)
        assert not [x for x in rep.findings if x.category == "incident_allegation"]
        note = next(x for x in rep.findings if x.claim_type == "collection_gap")
        assert note.category == "unresolved" and "does not show why" in note.rationale


def test_missing_line_with_no_later_local_record_is_inconclusive(tmp_path):
    a, b, c = auth_open("09:00:00", "ann", 1), auth_close("09:10:00", "ann", 1), auth_open("09:20:00", "bob", 2)
    st, m = mini_case(tmp_path, {
        "workstation/var/log/auth.log": [a, b],  # capture simply ends before the last collected line
        "collector/var/log/collected/collected.log": [fwd("09:00:01", 1, a), fwd("09:10:01", 2, b), fwd("09:20:01", 3, c)],
    })
    f = checks.reconcile_logs(st, m)["files"][0]
    assert f["unexplained_local_absence"] == [] and len(f["inconclusive_local_absence"]) == 1
    assert f["status"] == "inconclusive"


def test_bracketed_missing_line_is_unexplained_and_duplicates_are_collapsed(tmp_path):
    a, b, c = auth_open("09:00:00", "ann", 1), auth_open("09:05:00", "bob", 2), auth_close("09:10:00", "ann", 1)
    st, m = mini_case(tmp_path, {
        "workstation/var/log/auth.log": [a, c],
        "collector/var/log/collected/collected.log": [
            fwd("09:00:01", 1, a), fwd("09:00:03", 1, a),  # the same sequence number delivered twice
            fwd("09:05:09", 2, b),  # delayed delivery
            fwd("09:10:01", 3, c)],
    })
    f = checks.reconcile_logs(st, m)["files"][0]
    assert f["collector_duplicate_deliveries"] == 1 and f["collector_lines"] == 3
    assert [r["line"] for r in f["unexplained_local_absence"]] == [b]
    assert f["missing_at_collector"]["in_heartbeat_gap"] == f["missing_at_collector"]["outside_heartbeat_gap"] == 0


def test_keep_zero_rotation_explains_everything_before_the_boundary(tmp_path):
    f_path = "/var/log/auth.log"
    old, new1, new2 = auth_open("08:00:00", "ann", 1), auth_open("10:00:00", "bob", 2), auth_close("10:30:00", "bob", 2)
    rot = f"{ts('09:00:00')} ws-nurse-01 logrotate[77]: rotated {f_path} -> archived off-host nas:/a.gz (keep 0)"
    ctx = context()
    ctx["logging_policy"]["forwarded_files"].append({"host": "workstation", "file": "/var/log/syslog"})
    st, m = mini_case(tmp_path, {
        "workstation/var/log/auth.log": [new1, new2],
        "workstation/var/log/syslog": [rot],
        "collector/var/log/collected/collected.log": [
            fwd("08:00:01", 1, old), fwd("09:00:01", 1, rot, file="/var/log/syslog"),
            fwd("10:00:01", 2, new1), fwd("10:30:01", 3, new2)],
    }, ctx)
    f = _file(checks.reconcile_logs(st, m), "workstation", f_path)
    assert f["status"] == "retention_explained_only" and f["retention_explained_absence"]["count"] == 1
    assert f["local_coverage_start"] == ts("09:00:00")


# ----------------------------------------------------------------- transfers and sessions
def test_links_the_transfer_to_its_observed_session(make_episode, store_for):
    for variant in ("incident_plain", "incident_coverup"):
        p = make_episode(DEV_SEED, variant)
        st, m, key = store_for(p), load_manifest(p), load_answer_key(p)
        bad = [t for t in checks.correlate_transfers(st, m)["transfers"] if t["policy_status"] == "not_approved"]
        assert len(bad) == 1
        t = bad[0]
        assert t["src_host"] == "workstation" and t["session_link"] == "single_overlapping_session"
        sess = t["sessions"][0]
        assert sess["session_id"] == key.attribution.session and sess["account"] == key.attribution.account_used
        assert sess["origin"] == "console" and t["staged_object"]["export_event_ids"]
        seen = sess["login_record_seen_in"]
        assert seen == (["collector copy"] if variant == "incident_coverup" else ["local log", "collector copy"])


def test_approved_bulk_transfers_are_consistent_with_policy(make_episode, store_for):
    p = make_episode(DEV_SEED, "benign_approved_transfer")
    st, m = store_for(p), load_manifest(p)
    xfers = checks.correlate_transfers(st, m)["transfers"]
    assert {t["policy_status"] for t in xfers} == {"approved"}
    adhoc = next(t for t in xfers if t["src_host"] == "workstation")
    assert adhoc["staged_object"] and adhoc["session_link"] == "single_overlapping_session"  # same shape as the crime
    rep = run_br(st, m)
    assert not [x for x in rep.findings if x.category == "incident_allegation"]
    assert sum(x.claim_type == "policy_consistent_transfer" for x in rep.findings) == 2
    assert rep.attribution.human_identity == "not_assessed" and rep.attribution.account_used is None


def test_two_overlapping_sessions_make_the_link_ambiguous(tmp_path):
    a, b = auth_open("09:00:00", "ann", 1), auth_open("09:01:00", "bob", 2, tty="tty2")
    st, m = mini_case(tmp_path, {
        "workstation/var/log/auth.log": [a, b],
        "collector/var/log/collected/collected.log": [fwd("09:00:01", 1, a), fwd("09:01:01", 2, b)],
        "tap/flows.jsonl": [flow("09:05:00", "09:05:09", "10.20.1.21", "10.20.9.50", 8080, 9_000_000)],
    })
    t = checks.correlate_transfers(st, m)["transfers"][0]
    assert t["policy_status"] == "not_approved" and t["session_link"] == "ambiguous_multiple" and len(t["sessions"]) == 2


def test_small_flows_to_the_same_destination_are_not_transfers(coverup, store_for):
    st, m, key = store_for(coverup), load_manifest(coverup), load_answer_key(coverup)
    dst = next(e.object for e in key.effects if e.effect_type == "policy_violating_transfer").split(":")[0]
    assert len(st.scan(source="flow", object_contains=dst + ":")) > 1  # the address also appears in routine traffic
    assert sum(t["dst"] == dst for t in checks.correlate_transfers(st, m)["transfers"]) == 1


# ----------------------------------------------------------------- account vs person
@pytest.mark.parametrize("badged_out, observation", [
    (True, "console_session_while_holder_badged_out"), (False, "console_session_while_holder_badged_in")])
def test_presence_check_never_names_or_clears_a_person(make_episode, store_for, badged_out, observation):
    seed = _seed_where("incident_coverup", lambda s: s["crime"]["owner_badged_out"] is badged_out)
    p = make_episode(seed, "incident_coverup")
    st, m, key = store_for(p), load_manifest(p), load_answer_key(p)
    a = checks.assess_presence(st, m, key.attribution.session)
    assert a["observation"] == observation and a["supports_named_person"] is False
    assert a["badge_event_ids"] and st.get(a["badge_event_ids"])[0].source == "badge"
    assert key.attribution.operator_true.split(":")[1] not in a["statement"]
    assert "does not identify who was" in a["statement"] or "equally" in a["statement"]
    rep = run_br(st, m)
    assert rep.attribution.account_used == key.attribution.account_used
    assert rep.attribution.human_identity == "insufficient_evidence"
    assert rep.attribution.named_person_accused is None and rep.attribution.named_person_exonerated is None
    assert all(f.actor_claimed is None for f in rep.findings)
    assert "Human operator not established" in rep.attribution.statement


def test_remote_session_badge_is_not_informative(make_episode, store_for):
    p = make_episode(DEV_SEED, "benign_remote_login")
    st, m = store_for(p), load_manifest(p)
    actor = build_spec(DEV_SEED, "benign_remote_login")["benign"]["actor"]
    sess = [s for s in checks.reconstruct_sessions(st, "workstation").values() if s.origin == "remote" and s.account == actor]
    assert sess
    a = checks.assess_presence(st, m, sess[-1].session_id)
    assert a["observation"] == "remote_session_badge_not_informative" and a["remote_access_permitted_by_policy"] is True
    assert not [x for x in run_br(st, m).findings if x.category == "incident_allegation"]


def test_unknown_session_and_missing_badge_are_reported_not_guessed(tmp_path):
    a = auth_open("09:00:00", "ann", 1)
    st, m = mini_case(tmp_path, {"workstation/var/log/auth.log": [a],
                                 "collector/var/log/collected/collected.log": [fwd("09:00:01", 1, a), hb("09:00:05", 1)]})
    assert checks.assess_presence(st, m, "workstation#99")["observation"] == "session_not_found"
    assert checks.assess_presence(st, m, "workstation#1")["observation"] == "no_badge_data_before_session"


def test_checks_are_deterministic(coverup, store_for):
    st, m = store_for(coverup), load_manifest(coverup)
    assert checks.reconcile_logs(st, m) == checks.reconcile_logs(st, m)
    assert checks.correlate_transfers(st, m) == checks.correlate_transfers(st, m)
