"""M2: verifier and scorer fixtures (PLAN 10.1): duplicates, wrong object, wrong host, broad
intervals, nonexistent citations, rejected claims, failed attacks, no-crime episodes, abstention."""

from __future__ import annotations

import inspect
import os
from datetime import timedelta

import pytest

from alibi import baselines, checks, scoring, verifier
from alibi.baselines import run_b0, run_br
from alibi.contracts import AttributionAssessment, Finding, InvestigationReport, TruthEffect
from alibi.episode import create_episode, load_answer_key, load_manifest
from alibi.evidence.store import EvidenceStore
from alibi.reports import lock_report, report_digest
from alibi.scoring import ScoringError, max_matching, score_report
from alibi.sim.scenario import BENIGN_VARIANTS
from alibi.verifier import is_accepted, verify_report

from .conftest import DEV_SEED


@pytest.fixture()
def case(coverup, store_for):
    st = store_for(coverup)
    return st, load_manifest(coverup), load_answer_key(coverup)


def _locked(rep, st, m):
    return lock_report(verify_report(rep, st, m), "skipped_for_benchmark", by_human=False)


def _br(st, m):
    return verify_report(run_br(st, m), st, m)


def _find(rep, claim):
    return next(f for f in rep.findings if f.claim_type == claim)


def _with(rep, *extra, drop=()):
    out = rep.model_copy(deep=True)
    out.findings = [f for f in out.findings if f.id not in drop] + list(extra)
    return out


# ----------------------------------------------------------------- the happy path on a dev fixture
def test_br_reconstructs_the_dev_coverup_case(case):
    st, m, key = case
    sc = score_report(_locked(run_br(st, m), st, m), key, st)
    assert (sc.step_recall.num, sc.step_recall.den) == (3, 3)
    assert (sc.final_precision.num, sc.final_precision.den) == (3, 3)
    assert sc.coverup_detected is True and sc.account_identification_correct is True
    assert sc.attribution_abstained and sc.unsupported_named_attribution == 0 and not sc.false_accusation
    assert sc.failed_or_partial_steps == 1  # the attempt against the collector is recorded, not scored as an effect
    assert {o.outcome for o in sc.effect_outcomes} == {"caught"}


def test_b0_finds_loud_commands_but_not_the_removed_line(case):
    st, m, key = case
    raw = run_b0(st, m)
    rep = _locked(raw, st, m)
    sc = score_report(rep, key, st)
    assert len(rep.findings) == len(raw.findings)  # the verifier never adds or drops findings
    assert (sc.step_recall.num, sc.step_recall.den) == (2, 3) and sc.coverup_detected is False
    missed = [o for o in sc.effect_outcomes if o.outcome == "missed"]
    assert [o.effect_type for o in missed] == ["local_log_removal"]
    assert sc.proposal_precision.den > 5 and sc.proposal_precision.value < 0.5  # raw noise stays visible
    assert sc.final_precision.value == 1.0 and sc.verifier_rejection_rate.value > 0.5


def test_dev_benign_controls_raise_no_final_alert_for_either_baseline(make_episode, store_for):
    for variant in BENIGN_VARIANTS:
        p = make_episode(DEV_SEED, variant)
        st, m, key = store_for(p), load_manifest(p), load_answer_key(p)
        for fn in (run_b0, run_br):
            sc = score_report(_locked(fn(st, m), st, m), key, st)
            assert sc.case_kind == "benign" and sc.benign_false_alert is False, (variant, fn.__name__)
            assert sc.step_recall.value is None and "not applicable" in sc.step_recall.na_reason
            assert sc.account_identification_correct is None and sc.account_identification_na_reason
        assert score_report(_locked(run_b0(st, m), st, m), key, st).proposals_incident > 0  # B0 still raised raw hits
        assert score_report(_locked(run_br(st, m), st, m), key, st).proposals_incident == 0


# ----------------------------------------------------------------- verifier
def test_fabricated_citation_is_rejected_and_counted(case):
    st, m, key = case
    br = run_br(st, m)
    fake = _find(br, "policy_violating_transfer").model_copy(update={"id": "X-1", "evidence_ids": ["ev_doesnotexist"]})
    rep = _locked(_with(br, fake), st, m)
    bad = next(f for f in rep.findings if f.id == "X-1")
    assert bad.verification_status == "invalid_reference" and bad.status == "rejected_by_verifier"
    sc = score_report(rep, key, st)
    assert sc.evidence_reference_validity.value < 1.0
    assert sc.proposal_precision.den == sc.final_precision.den + 1  # the rejected claim still counts as a proposal
    assert next(o for o in sc.finding_outcomes if o.finding_id == "X-1").outcome == "rejected"


def test_rotation_explained_absence_cannot_be_alleged_as_tampering(case):
    st, m, _ = case
    rec = checks.reconcile_logs(st, m)
    app = next(f for f in rec["files"] if f["file"].endswith("access.log"))
    ids = app["retention_explained_absence"]["sample_collector_event_ids"]
    ev = st.get(ids)[0]
    claim = Finding(id="X-2", claim_type="local_log_removal", category="incident_allegation", host="records",
                    t_start=ev.ts - timedelta(minutes=5), t_end=ev.ts + timedelta(minutes=5),
                    object_or_session=app["file"], evidence_ids=ids)
    out = verifier.verify_finding(claim, st, verifier.compute_observations(st, m))
    assert out.status == "rejected_by_verifier" and "retention boundary" in out.verifier_notes[0]
    assert not is_accepted(out)


def test_approved_transfer_cannot_be_alleged_as_a_violation(make_episode, store_for):
    p = make_episode(DEV_SEED, "benign_approved_transfer")
    st, m, key = store_for(p), load_manifest(p), load_answer_key(p)
    t = next(t for t in checks.correlate_transfers(st, m)["transfers"] if t["src_host"] == "workstation")
    fl = st.get([t["flow_event_id"]])[0]
    so = t["staged_object"]
    claims = [
        Finding(id="X-3", claim_type="policy_violating_transfer", category="incident_allegation", host="workstation",
                t_start=fl.ts, t_end=fl.ts + timedelta(minutes=1), object_or_session=f"{t['dst']}:{t['dport']}",
                evidence_ids=[fl.id]),
        Finding(id="X-4", claim_type="data_staging", category="incident_allegation", host="workstation",
                t_start=fl.ts - timedelta(minutes=3), t_end=fl.ts, object_or_session=so["path"],
                evidence_ids=[so["fs_stat_event_id"]]),
    ]
    rep = _locked(_with(run_br(st, m), *claims), st, m)
    for fid in ("X-3", "X-4"):
        f = next(f for f in rep.findings if f.id == fid)
        assert f.status == "rejected_by_verifier", fid
    assert "approved" in next(f for f in rep.findings if f.id == "X-3").verifier_notes[0]
    assert score_report(rep, key, st).benign_false_alert is False


def test_allegation_without_evidence_or_with_an_episode_wide_window_is_not_accepted(case):
    st, m, key = case
    br = run_br(st, m)
    good = _find(br, "policy_violating_transfer")
    empty = good.model_copy(update={"id": "X-5", "evidence_ids": []})
    broad = good.model_copy(update={"id": "X-6", "t_start": m.capture_start, "t_end": m.capture_end})
    rep = _locked(_with(br, empty, broad, drop=(good.id,)), st, m)
    f5, f6 = (next(f for f in rep.findings if f.id == i) for i in ("X-5", "X-6"))
    assert f5.status == "rejected_by_verifier" and not is_accepted(f6)
    assert "too broad" in f6.verifier_notes[0]
    sc = score_report(rep, key, st)
    assert next(o for o in sc.effect_outcomes if o.effect_type == "policy_violating_transfer").outcome == "missed"
    assert sc.step_recall.num == 2  # a claim spanning the whole episode collects no credit


def test_verified_never_means_a_person_is_proven_responsible(case):
    st, m, key = case
    br = run_br(st, m)
    owner = key.attribution.account_used  # the framed account holder
    named = _find(br, "policy_violating_transfer").model_copy(update={"actor_claimed": owner})
    rep = _with(br, named, drop=(named.id,))
    rep.attribution = AttributionAssessment(account_used=owner, human_identity="supported_named_actor",
                                            named_person_accused=owner)
    rep = _locked(rep, st, m)
    f = next(f for f in rep.findings if f.id == named.id)
    assert any("does not establish who operated" in n for n in f.verifier_notes)
    sc = score_report(rep, key, st)
    assert sc.attribution_abstained is False and sc.unsupported_named_attribution == 1
    assert sc.false_accusation is True  # the account owner was framed; naming them is a false accusation


# ----------------------------------------------------------------- scorer fixtures
def test_duplicate_findings_do_not_earn_extra_credit(case):
    st, m, key = case
    br = _br(st, m)
    dup = _find(br, "policy_violating_transfer").model_copy(update={"id": "Z-dup"})
    sc = score_report(lock_report(_with(br, dup), "skipped_for_benchmark", by_human=False), key, st)
    assert (sc.step_recall.num, sc.step_recall.den) == (3, 3)
    assert (sc.final_precision.num, sc.final_precision.den) == (3, 4)
    assert sum(o.outcome == "duplicate" for o in sc.finding_outcomes) == 1
    assert len({mm.effect_id for mm in sc.matches}) == len(sc.matches) == 3


def test_wrong_object_right_host_is_unsupported(case):
    st, m, key = case
    br = _br(st, m)
    t = _find(br, "policy_violating_transfer")
    wrong = t.model_copy(update={"object_or_session": "10.20.9.250:8080"})
    sc = score_report(lock_report(_with(br, wrong, drop=(t.id,)), "skipped_for_benchmark", by_human=False), key, st)
    assert next(o for o in sc.finding_outcomes if o.finding_id == t.id).outcome == "unsupported"
    assert sc.false_claims_final == 1 and sc.step_recall.num == 2


def test_wrong_host_right_time_is_not_accepted(case):
    st, m, key = case
    br = run_br(st, m)
    t = _find(br, "policy_violating_transfer")
    rep = _locked(_with(br, t.model_copy(update={"host": "records"}), drop=()), st, m)
    rep.findings = [f for f in rep.findings if not (f.id == t.id and f.host == "workstation")]
    moved = next(f for f in rep.findings if f.id == t.id)
    assert moved.host == "records" and not is_accepted(moved)
    rep2 = lock_report(rep.model_copy(update={"locked": False}), "skipped_for_benchmark", by_human=False)
    assert score_report(rep2, key, st).step_recall.num == 2


def test_failed_attack_step_earns_no_credit(case):
    st, m, key = case
    assert any(s.execution_status == "failed" and s.host == "collector" for s in key.steps)
    br = run_br(st, m)
    removal = _find(br, "local_log_removal")
    on_collector = removal.model_copy(update={"id": "X-7", "host": "collector"})
    rep = _locked(_with(br, on_collector), st, m)
    sc = score_report(rep, key, st)
    assert next(o for o in sc.finding_outcomes if o.finding_id == "X-7").outcome in ("rejected", "matched_but_not_accepted")
    assert sc.step_recall.num == 3 and len(sc.matches) == 3


def test_empty_report_abstains_but_scores_zero_recall(case):
    st, m, key = case
    rep = InvestigationReport(report_id="r-empty", bundle_id=m.bundle_id, system_id="EMPTY", inference_mode="NO_MODEL_BASELINE")
    sc = score_report(_locked(rep, st, m), key, st)
    assert sc.attribution_abstained is True
    assert (sc.step_recall.num, sc.step_recall.den, sc.step_recall.value) == (0, 3, 0.0)  # refusal is not optimal
    assert sc.final_precision.value is None and sc.final_precision.na_reason
    assert sc.account_identification_correct is False and sc.coverup_detected is False


def test_an_accepted_allegation_in_a_no_crime_case_is_a_false_alert(make_episode, store_for):
    p = make_episode(DEV_SEED, "benign_rotation")
    st, m, key = store_for(p), load_manifest(p), load_answer_key(p)
    ev = st.search(source="flow", limit=1)[0]
    forced = Finding(id="X-8", claim_type="policy_violating_transfer", category="incident_allegation", host="workstation",
                     t_start=ev.ts, t_end=ev.ts, object_or_session="10.20.9.1:80", evidence_ids=[ev.id],
                     status="verified", verification_status="supported_observation")
    rep = InvestigationReport(report_id="r-x", bundle_id=m.bundle_id, system_id="T", inference_mode="NO_MODEL_BASELINE",
                              findings=[forced])
    sc = score_report(lock_report(rep, "skipped_for_benchmark", by_human=False), key, st)  # scorer logic only
    assert sc.benign_false_alert is True and sc.false_claims_final == 1 and sc.step_recall.value is None


def test_unobservable_effects_leave_the_recall_denominator(case):
    st, m, key = case
    key2 = key.model_copy(deep=True)
    key2.effects[0].observable = False
    key2.effects[0].unobservable_reason = "test: the affected segment left the host before capture"
    sc = score_report(_locked(run_br(st, m), st, m), key2, st)
    assert sc.unobservable_effects == 1 and sc.step_recall.den == 2
    assert sum(o.outcome == "unobservable" for o in sc.effect_outcomes) == 1


def test_matching_is_one_to_one_and_maximum_not_greedy(case):
    st, m, key = case
    e = next(x for x in key.effects if x.effect_type == "policy_violating_transfer")
    e2 = e.model_copy(update={"effect_id": "e9"})
    ids = {e.effect_id: {"a", "b"}, "e9": {"a"}}
    base = dict(claim_type="policy_violating_transfer", category="incident_allegation", host=e.host,
                t_start=e.t_start, t_end=e.t_end, object_or_session=e.object, status="verified")
    f1 = Finding(id="f1", evidence_ids=["a"], **base)  # compatible with both effects
    f2 = Finding(id="f2", evidence_ids=["b"], **base)  # compatible only with the first
    assert max_matching([f1, f2], [e, e2], ids) == {"f1": "e9", "f2": e.effect_id}
    assert len(max_matching([f1, f1.model_copy(update={"id": "f3"})], [e2], ids)) == 1
    assert max_matching([f1, f2], [e, e2], ids) == max_matching([f2, f1], [e2, e], ids)  # order independent


def test_scoring_requires_a_locked_report_and_never_mutates_it(case):
    st, m, key = case
    rep = _br(st, m)
    with pytest.raises(ScoringError):
        score_report(rep, key, st)
    locked = lock_report(rep, "skipped_for_benchmark", by_human=False)
    before = locked.model_dump_json()
    score_report(locked, key, st)
    assert locked.model_dump_json() == before and locked.report_sha256 == report_digest(locked)


def test_batch_lock_never_fabricates_human_approval_and_locking_is_idempotent(case):
    st, m, _ = case
    rep = _br(st, m)
    batch = lock_report(rep, "skipped_for_benchmark", by_human=False)
    assert batch.attribution.approved_by_human is False and batch.attribution.review_status == "skipped_for_benchmark"
    assert lock_report(batch, "accepted", by_human=True) is batch  # a second decision cannot rewrite a locked report
    human = lock_report(rep, "accepted", by_human=True)
    assert human.attribution.approved_by_human is True and human.report_sha256 == batch.report_sha256
    rejected = lock_report(rep, "rejected", by_human=True, note="needs work")
    assert rejected.locked and rejected.attribution.approved_by_human is False
    assert len(rejected.findings) == len(rep.findings) and rejected.review_history[0].decision == "rejected"
    with pytest.raises(ValueError):
        lock_report(rep, "skipped_for_benchmark", by_human=True)


# ----------------------------------------------------------------- baselines stay on their side of the barrier
def test_investigator_side_modules_never_reference_truth():
    for mod in (baselines, checks, verifier):
        src = inspect.getsource(mod)
        for word in ("answer_key", "AnswerKey", "sealed", "episode_manifest", "load_answer_key", "canary",
                     "scenario_spec", "alibi.episode", "alibi.scoring", "alibi.sim"):
            assert word not in src, (mod.__name__, word)


def test_baselines_run_with_the_sealed_directory_unreadable(roots):
    p = create_episode(seed=6, variant="incident_coverup", runs_dir=roots[0], sealed_dir=roots[1], episode_id="t-nosealed-6")
    m = load_manifest(p)
    os.chmod(p.sealed, 0o000)
    try:
        with EvidenceStore(p.db) as st:
            br, b0 = _br(st, m), verify_report(run_b0(st, m), st, m)
        assert sum(is_accepted(f) for f in br.findings) == 3 and sum(is_accepted(f) for f in b0.findings) == 2
    finally:
        os.chmod(p.sealed, 0o755)
