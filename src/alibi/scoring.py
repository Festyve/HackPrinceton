"""Deterministic scorer (PLAN 10.1-10.2). Runs in the trusted boundary, after lock.

Matching rule, fixed before any test split (see docs/evaluation-config.json):
a final accepted incident allegation matches a successful, observable truth effect
when ALL of these hold
  1. claim type equals the internal effect type (ATT&CK ids are not used),
  2. same host,
  3. same object (file path / staged path / destination address) or same session,
  4. the finding window is at most MAX_WINDOW_S wide and overlaps the effect window
     within TOLERANCE_S,
  5. the finding cites at least one record that the executed step actually produced.
Matching is one-to-one maximum matching with deterministic tie-breaking (findings
and effects in id order). A finding or an effect earns at most one true positive.
"""

from __future__ import annotations

import hashlib
import re
from datetime import timedelta

from alibi.contracts import (
    AnswerKey,
    EffectOutcome,
    Finding,
    FindingOutcome,
    InvestigationReport,
    MatchRecord,
    Ratio,
    Score,
    TruthEffect,
)
from alibi.evidence.store import EvidenceStore
from alibi.verifier import is_accepted

SCORER_VERSION = "1.0.0"
TOLERANCE_S = 120
MAX_WINDOW_S = 1800
ANTI_FORENSIC_EFFECTS = ("local_log_removal",
                         # phase two: these effect types do not occur in a first-run case
                         "timestamp_alteration", "forwarding_stopped")
LOGIN_STEP_NAMES = ("login_as", "login_remote")
_IP = re.compile(r"(\d+\.\d+\.\d+\.\d+)")


class ScoringError(RuntimeError):
    pass


def effect_event_ids(effect: TruthEffect, store: EvidenceStore, index: dict[str, list] | None = None) -> set[str]:
    """Resolve the sealed pointers of one effect to investigator-visible event ids."""
    index = index if index is not None else raw_index(store)
    ids: set[str] = set()
    for ptr in effect.evidence:
        cands = index.get(ptr.raw_sha256, [])
        if len(cands) > 1 and ptr.ts is not None:
            exact = [c for c in cands if abs((c[1] - ptr.ts).total_seconds()) <= 2]
            cands = exact or cands
        ids.update(c[0] for c in cands)
    return ids


def raw_index(store: EvidenceStore) -> dict[str, list]:
    index: dict[str, list] = {}
    for ev in store.scan():
        if ev.source == "heartbeat":
            continue
        index.setdefault(hashlib.sha256(ev.raw.encode("utf-8")).hexdigest(), []).append((ev.id, ev.ts))
    return index


def _object_matches(f: Finding, e: TruthEffect) -> bool:
    claimed = (f.object_or_session or "").strip()
    if not claimed:
        return False
    if e.session and claimed == e.session:
        return True
    if e.effect_type == "policy_violating_transfer":
        want = _IP.search(e.object)
        got = _IP.search(claimed)
        return bool(want and got and want.group(1) == got.group(1))
    return claimed == e.object


def compatible(f: Finding, e: TruthEffect, e_ids: set[str]) -> bool:
    if f.category != "incident_allegation" or f.claim_type != e.effect_type or f.host != e.host:
        return False
    if not _object_matches(f, e):
        return False
    if (f.t_end - f.t_start).total_seconds() > MAX_WINDOW_S:
        return False
    tol = timedelta(seconds=TOLERANCE_S)
    if not (f.t_start - tol <= e.t_end and e.t_start <= f.t_end + tol):
        return False
    return bool(set(f.evidence_ids) & e_ids)


def max_matching(findings: list[Finding], effects: list[TruthEffect], ids: dict[str, set[str]]) -> dict[str, str]:
    """Kuhn's algorithm with findings and effects visited in id order. Returns finding_id -> effect_id."""
    fs = sorted(findings, key=lambda f: f.id)
    es = sorted(effects, key=lambda e: e.effect_id)
    adj = {f.id: [e.effect_id for e in es if compatible(f, e, ids[e.effect_id])] for f in fs}
    owner: dict[str, str] = {}  # effect_id -> finding_id

    def try_assign(fid: str, seen: set[str]) -> bool:
        for eid in adj[fid]:
            if eid in seen:
                continue
            seen.add(eid)
            if eid not in owner or try_assign(owner[eid], seen):
                owner[eid] = fid
                return True
        return False

    for f in fs:
        try_assign(f.id, set())
    return {fid: eid for eid, fid in owner.items()}


def _person(name: str | None) -> str | None:
    if not name:
        return None
    return name.strip().lower().removeprefix("person:")


def score_report(report: InvestigationReport, key: AnswerKey, store: EvidenceStore) -> Score:
    """Score a LOCKED report against the sealed key. Never mutates the report."""
    if not report.locked:
        raise ScoringError("the report is not locked; scoring and reveal are refused until it is")
    index = raw_index(store)
    observable = [e for e in key.effects if e.observable]
    unobservable = [e for e in key.effects if not e.observable]
    e_ids = {e.effect_id: effect_event_ids(e, store, index) for e in key.effects}

    proposals = [f for f in report.findings if f.category == "incident_allegation"]
    accepted = [f for f in proposals if is_accepted(f)]
    match = max_matching(accepted, observable, e_ids)
    would = max_matching([f for f in proposals if not is_accepted(f)], observable, e_ids)

    finding_outcomes: list[FindingOutcome] = []
    for f in sorted(report.findings, key=lambda f: f.id):
        if f.category != "incident_allegation":
            finding_outcomes.append(FindingOutcome(finding_id=f.id, outcome="not_an_allegation",
                                                   reason=f"{f.category.replace('_', ' ')}; not scored as an incident claim"))
        elif f.id in match:
            finding_outcomes.append(FindingOutcome(finding_id=f.id, outcome="matched", effect_id=match[f.id],
                                                   reason="matches one executed, successful effect"))
        elif is_accepted(f):
            dup = next((e.effect_id for e in observable if compatible(f, e, e_ids[e.effect_id])), None)
            if dup:
                finding_outcomes.append(FindingOutcome(finding_id=f.id, outcome="duplicate", effect_id=dup,
                                                       reason="that effect is already credited to another finding"))
            else:
                finding_outcomes.append(FindingOutcome(finding_id=f.id, outcome="unsupported",
                                                       reason="accepted allegation with no matching executed effect"))
        elif f.id in would:
            finding_outcomes.append(FindingOutcome(finding_id=f.id, outcome="matched_but_not_accepted", effect_id=would[f.id],
                                                   reason="would match an effect but was not accepted after verification"))
        else:
            finding_outcomes.append(FindingOutcome(finding_id=f.id, outcome="rejected",
                                                   reason="; ".join(f.verifier_notes[:1]) or f.status))

    caught = {eid: fid for fid, eid in match.items()}
    effect_outcomes = [
        EffectOutcome(effect_id=e.effect_id, effect_type=e.effect_type, host=e.host, object=e.object,
                      t_start=e.t_start, t_end=e.t_end,
                      outcome="caught" if e.effect_id in caught else "missed", finding_id=caught.get(e.effect_id))
        for e in observable
    ] + [
        EffectOutcome(effect_id=e.effect_id, effect_type=e.effect_type, host=e.host, object=e.object,
                      t_start=e.t_start, t_end=e.t_end, outcome="unobservable",
                      description=e.unobservable_reason or "") for e in unobservable
    ]

    benign = key.case_kind == "benign"
    tp = len(match)
    all_cited = [i for f in report.findings for i in f.evidence_ids + f.counterevidence_ids]
    all_cited += report.attribution.supporting_evidence_ids + report.attribution.contrary_evidence_ids
    existing = store.existing_ids(all_cited)
    supported = [f for f in proposals if f.verification_status == "supported_observation"]

    anti = [e for e in observable if e.effect_type in ANTI_FORENSIC_EFFECTS]
    coverup = (any(e.effect_id in caught for e in anti) if anti else None)

    named = {_person(report.attribution.named_person_accused)} | {_person(f.actor_claimed) for f in report.findings}
    named.discard(None)
    abstained = not named and report.attribution.human_identity in ("unknown", "insufficient_evidence", "not_assessed")
    truth_operator = _person(key.attribution.operator_true)
    supportable = key.attribution.named_attribution_supportable
    unsupported_named = 0 if supportable else len(named)
    false_accusation = any(n != truth_operator for n in named)
    named_correct = None
    if named and supportable:
        named_correct = named == {truth_operator}

    if benign:
        account_ok, account_na = None, "no incident occurred; account identification is not applicable"
    elif not any(s.step_name in LOGIN_STEP_NAMES for s in key.steps):
        # phase two: an incident whose executed steps involved no account at all (e.g. a stored sensor record)
        account_ok, account_na = None, "no account was used in the executed steps; account identification is not applicable"
    else:
        account_ok = report.attribution.account_used is not None and \
            report.attribution.account_used == key.attribution.account_used
        account_na = None

    recall = Ratio.na("no-crime case: recall is not applicable") if benign else \
        Ratio.of(tp, len(observable), na_reason="no observable scorable effect")
    return Score(
        scorer_version=SCORER_VERSION, report_id=report.report_id, episode_id=key.episode_id,
        system_id=report.system_id, inference_mode=report.inference_mode, case_kind=key.case_kind,
        step_recall=recall,
        proposal_precision=Ratio.of(tp, len(proposals), na_reason="no incident allegation was proposed"),
        final_precision=Ratio.of(tp, len(accepted), na_reason="no incident allegation was accepted"),
        evidence_reference_validity=Ratio.of(sum(i in existing for i in all_cited), len(all_cited),
                                             na_reason="no evidence was cited"),
        supported_claim_rate=Ratio.of(len(supported), len(proposals), na_reason="no incident allegation was proposed"),
        verifier_rejection_rate=Ratio.of(len(proposals) - len(accepted), len(proposals),
                                         na_reason="no incident allegation was proposed"),
        coverup_detected=coverup,
        coverup_detected_na_reason=None if anti else "no successful anti-forensic effect in this case",
        account_identification_correct=account_ok, account_identification_na_reason=account_na,
        attribution_abstained=abstained, unsupported_named_attribution=unsupported_named,
        false_accusation=false_accusation, named_attribution_correct=named_correct,
        benign_false_alert=(len(accepted) > 0) if benign else None,
        false_claims_final=len(accepted) - tp, proposals_total=len(report.findings),
        proposals_incident=len(proposals), final_accepted_incident=len(accepted),
        unobservable_effects=len(unobservable),
        failed_or_partial_steps=sum(s.execution_status != "succeeded" for s in key.steps),
        matches=[MatchRecord(finding_id=fid, effect_id=eid,
                             effect_type=next(e.effect_type for e in observable if e.effect_id == eid))
                 for fid, eid in sorted(match.items())],
        finding_outcomes=finding_outcomes, effect_outcomes=effect_outcomes, usage=report.usage,
        review_status=report.attribution.review_status, approved_by_human=report.attribution.approved_by_human,
        report_sha256=report.report_sha256,
        notes=["Scores describe agreement with a controlled simulation, not real-world forensic accuracy."],
    )
