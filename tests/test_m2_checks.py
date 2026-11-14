"""M2: deterministic contradiction checks, with positive, benign, incomplete-source and ambiguous cases."""

from __future__ import annotations

from datetime import datetime

import pytest

from alibi import checks, verifier
from alibi.baselines import run_br
from alibi.evidence_views import compare_local_collector
from alibi.explain import explanations
from alibi.runners import summarize_reconcile, summarize_transfers
from alibi.episode import load_answer_key, load_manifest
from alibi.sim.scenario import BENIGN_VARIANTS, VARIANTS, build_spec

from .conftest import DEV_SEED
from .helpers import auth_close, auth_open, badge, context, flow, fwd, hb, mini_case, ts


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
    # no badge reader in the bundle at all: presence is unknown, and the check says which kind of unknown
    none = checks.assess_presence(st, m, "workstation#1")
    assert none["observation"] == "badge_source_not_in_bundle" and "unknown" in none["statement"]
    # a badge reader that simply recorded nothing for this badge before the session
    st2, m2 = mini_case(tmp_path, {"workstation/var/log/auth.log": [a],
                                   "collector/var/log/collected/collected.log": [fwd("09:00:01", 1, a)],
                                   "iot-hub/badge/door-staff-1.jsonl": [badge("11:00:00", "B-1", "out")]})
    assert checks.assess_presence(st2, m2, "workstation#1")["observation"] == "no_badge_data_before_session"


def test_checks_are_deterministic(coverup, store_for):
    st, m = store_for(coverup), load_manifest(coverup)
    assert checks.reconcile_logs(st, m) == checks.reconcile_logs(st, m)
    assert checks.correlate_transfers(st, m) == checks.correlate_transfers(st, m)


# ----------------------------------------------------------------- coverage: unknown is not clean, and not an allegation
def _allegations(st, m):
    return [x for x in run_br(st, m).findings if x.category == "incident_allegation"]


def test_missing_prefix_is_inconclusive_never_an_allegation(tmp_path):
    """The host copy starts later than the collector's records and nothing local precedes the line."""
    a, b, c = auth_open("09:00:00", "ann", 1), auth_close("09:10:00", "ann", 1), auth_open("09:20:00", "bob", 2)
    st, m = mini_case(tmp_path, {
        "workstation/var/log/auth.log": [b, c],  # late-start local capture: the first line was never captured
        "collector/var/log/collected/collected.log": [fwd("09:00:01", 1, a), fwd("09:10:01", 2, b), fwd("09:20:01", 3, c)],
    })
    rec = checks.reconcile_logs(st, m)
    f = rec["files"][0]
    assert f["unexplained_local_absence"] == [] and f["status"] == "inconclusive"
    row = f["inconclusive_local_absence"][0]
    assert row["line"] == a and row["bracket_before_id"] is None and row["bracket_after_id"]
    assert "no earlier local record" in row["reason"]
    assert _allegations(st, m) == []
    rep = run_br(st, m)
    assert any("inconclusive, not an allegation" in q for q in rep.open_questions)
    q1 = explanations(st, m, None)[0]
    assert q1["answer"].startswith("Inconclusive") and "before and after" not in q1["answer"]


def test_both_brackets_are_cited_before_saying_before_and_after(tmp_path):
    a, b, c = auth_open("09:00:00", "ann", 1), auth_open("09:05:00", "bob", 2), auth_close("09:10:00", "ann", 1)
    st, m = mini_case(tmp_path, {
        "workstation/var/log/auth.log": [a, c],
        "collector/var/log/collected/collected.log": [fwd("09:00:01", 1, a), fwd("09:05:01", 2, b), fwd("09:10:01", 3, c)],
    })
    row = checks.reconcile_logs(st, m)["files"][0]["unexplained_local_absence"][0]
    assert row["bracket_before_id"] and row["bracket_after_id"]
    q1 = explanations(st, m, None)[0]
    assert "before and after" in q1["answer"]
    assert {row["bracket_before_id"], row["bracket_after_id"], row["collector_event_id"]} <= set(q1["evidence_ids"])
    removal = next(x for x in run_br(st, m).findings if x.claim_type == "local_log_removal")
    assert {row["bracket_before_id"], row["bracket_after_id"]} <= set(removal.evidence_ids)


def test_stated_source_coverage_is_honored_even_when_both_brackets_exist(tmp_path):
    """A line that falls between two captured generations, outside the window each one STATES it covered."""
    x, a, c, d = (auth_open("08:10:00", "ann", 1), auth_close("09:00:00", "ann", 1),
                  auth_open("09:20:00", "bob", 2), auth_close("09:30:00", "bob", 2))
    arts = {"workstation/var/log/auth.log.1": [x], "workstation/var/log/auth.log": [c, d],
            "collector/var/log/collected/collected.log": [fwd("08:10:01", 1, x), fwd("09:00:01", 2, a),
                                                          fwd("09:20:01", 3, c), fwd("09:30:01", 4, d)]}
    st, m = mini_case(tmp_path, arts)  # nothing stated: both brackets exist, so the line is unexplained
    assert [r["line"] for r in checks.reconcile_logs(st, m)["files"][0]["unexplained_local_absence"]] == [a]
    st, m = mini_case(tmp_path, arts, declared={"workstation/var/log/auth.log.1": ("08:00:00", "08:30:00"),
                                                "workstation/var/log/auth.log": ("09:15:00", "10:00:00")})
    f = checks.reconcile_logs(st, m)["files"][0]
    assert f["unexplained_local_absence"] == [] and f["status"] == "inconclusive"
    assert "outside the window" in f["inconclusive_local_absence"][0]["reason"] and _allegations(st, m) == []
    # a stated gap inside an otherwise covered file does the same
    st, m = mini_case(tmp_path, {"workstation/var/log/auth.log": [x, c, d], "collector/var/log/collected/collected.log":
                                 arts["collector/var/log/collected/collected.log"]},
                      gaps={"workstation/var/log/auth.log": [("08:55:00", "09:05:00", "log agent paused for maintenance")]})
    f = checks.reconcile_logs(st, m)["files"][0]
    assert f["unexplained_local_absence"] == [] and "log agent paused" in f["inconclusive_local_absence"][0]["reason"]


def test_missing_collector_is_not_assessable_not_consistent(tmp_path):
    a, b = auth_open("09:00:00", "ann", 1), auth_close("09:10:00", "ann", 1)
    st, m = mini_case(tmp_path, {"workstation/var/log/auth.log": [a, b]})  # no independent copy at all
    rec = checks.reconcile_logs(st, m)
    f = rec["files"][0]
    assert f["status"] == "not_assessable" and "no collector copy" in f["status_reason"]
    assert rec["coverage"]["collector_present"] is False and rec["coverage"]["heartbeat"] == {"workstation": "not_available"}
    assert f["unexplained_local_absence"] == [] and f["missing_at_collector"]["all_local_event_ids"] == []
    assert rec["coverage_limits"] and "unknown" in rec["coverage_limits"][0]
    rep = run_br(st, m)
    assert rep.findings == []  # nothing alleged, nothing called benign, no invented collection gap
    assert "unknown" in rep.summary and any(q.startswith("Coverage limit:") for q in rep.open_questions)
    text, _ = summarize_reconcile(rec)
    assert "NOT assessable" in text and text.startswith("0 forwarded logs compared")
    q1, _, q3 = explanations(st, m, None)
    assert q1["answer"].startswith("Unknown") and "No line is unexplainedly missing" not in q1["answer"]
    assert "cannot be measured" in q3["answer"] and "There is no other gap" not in q3["answer"]
    view = compare_local_collector(st, m, "workstation", "/var/log/auth.log")
    assert view["status"] == "not_assessable" and view["status_reason"]


def test_missing_host_copy_is_not_read_as_removal(tmp_path):
    a, b = auth_open("09:00:00", "ann", 1), auth_close("09:10:00", "ann", 1)
    st, m = mini_case(tmp_path, {"collector/var/log/collected/collected.log": [
        fwd("09:00:01", 1, a), fwd("09:10:01", 2, b), hb("09:00:05", 1), hb("09:00:15", 2)]})
    f = checks.reconcile_logs(st, m)["files"][0]
    assert f["status"] == "not_assessable" and f["collector_lines"] == 2 and f["unexplained_local_absence"] == []
    assert "not evidence of removal" in f["status_reason"] and _allegations(st, m) == []
    obs = verifier.compute_observations(st, m)
    assert obs.removal == []


def test_missing_flow_source_means_transfers_are_unknown_not_zero(tmp_path):
    a = auth_open("09:00:00", "ann", 1)
    st, m = mini_case(tmp_path, {"workstation/var/log/auth.log": [a],
                                 "collector/var/log/collected/collected.log": [fwd("09:00:01", 1, a)]})
    xfer = checks.correlate_transfers(st, m)
    assert xfer["status"] == "not_assessable" and xfer["transfers"] == [] and xfer["coverage"]["flow"] is False
    assert "does not mean there was none" in xfer["coverage_limits"][0]
    text, _ = summarize_transfers(xfer)
    assert "NOT assessable" in text and "0 bulk" not in text
    assert any("flow source" in q for q in run_br(st, m).open_questions)
    # with a flow source but no login records, a transfer is reported and its session link is 'unknown', not 'none'
    st, m = mini_case(tmp_path, {"tap/flows.jsonl": [flow("09:05:00", "09:05:09", "10.20.1.21", "10.20.9.50", 8080, 9_000_000)]})
    xfer = checks.correlate_transfers(st, m)
    assert xfer["status"] == "assessed" and xfer["transfers"][0]["session_link"] == "unknown_no_login_records_in_bundle"
    assert xfer["coverage"] == {"flow": True, "sessions": False, "shell_history": False, "file_metadata": False}
    assert len(xfer["coverage_limits"]) == 3


def test_no_heartbeat_data_is_not_reported_as_no_gap(tmp_path):
    a, b = auth_open("09:00:00", "ann", 1), auth_close("09:10:00", "ann", 1)
    st, m = mini_case(tmp_path, {"workstation/var/log/auth.log": [a, b],
                                 "collector/var/log/collected/collected.log": [fwd("09:00:01", 1, a)]})  # b never arrived
    rec = checks.reconcile_logs(st, m)
    f = rec["files"][0]
    assert f["heartbeat_coverage"] == "not_available" and f["missing_at_collector"]["outside_heartbeat_gap"] == 1
    assert any("cannot be measured" in x for x in rec["coverage_limits"])
    note = next(x for x in run_br(st, m).findings if x.claim_type == "collection_gap")
    assert "no heartbeat data" in note.rationale and "no heartbeat gap to explain it" not in note.rationale


def test_lines_outside_the_collectors_stated_window_are_not_a_collection_gap(tmp_path):
    a, b = auth_open("09:00:00", "ann", 1), auth_close("09:10:00", "ann", 1)
    col = "collector/var/log/collected/collected.log"
    st, m = mini_case(tmp_path, {"workstation/var/log/auth.log": [a, b], col: [fwd("09:10:01", 1, b)]},
                      declared={col: ("09:05:00", "10:00:00")})  # the collector says it only started at 09:05
    f = checks.reconcile_logs(st, m)["files"][0]
    mac = f["missing_at_collector"]
    assert mac["outside_collector_coverage"] == 1 and mac["outside_heartbeat_gap"] == 0
    assert f["status"] == "collector_coverage_limited" and run_br(st, m).findings == []


def test_existing_cases_are_unchanged_by_the_coverage_rules(make_episode, store_for):
    """Every simulated variant still has all its sources, so nothing becomes 'not assessable' or loses a bracket."""
    for variant in VARIANTS:
        p = make_episode(DEV_SEED, variant)
        st, m = store_for(p), load_manifest(p)
        rec, xfer = checks.reconcile_logs(st, m), checks.correlate_transfers(st, m)
        assert rec["coverage_limits"] == [] and xfer["coverage_limits"] == [] and xfer["status"] == "assessed"
        assert rec["coverage"]["files_not_assessable"] == [] and set(rec["coverage"]["heartbeat"].values()) == {"available"}
        for f in rec["files"]:
            assert f["status"] != "not_assessable"
            assert all(r["bracket_before_id"] and r["bracket_after_id"] for r in f["unexplained_local_absence"])
