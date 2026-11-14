"""Source-removal experiment: "can you still prove it if this witness disappears?"

A child evidence bundle is derived from a parent with chosen sources WITHHELD. The parent's bytes,
report, hashes and sealed truth are never modified. In the child the withheld source is gone from
everywhere an investigator could reach it: the raw files, the event store (rebuilt from the child's
own raw files), the manifest's source list, every check and therefore every model context. The
child starts with an empty case directory: no notes, no findings, no checkpoints, no answers.

Two different things are then available, and they are kept apart:

  compare()   deterministic and immediate. Each claim of the parent's report is re-checked against
              the child's evidence with the same registered predicates. No model, no truth.
  the child   an ordinary case. A fresh investigation of it is a separate, budgeted run.

Truth for research scoring stays what was executed. Only OBSERVABILITY is recomputed: an effect is
observable in the child when at least one record its step produced still exists there. All original
effects are always reported, so a smaller denominator can never read as better detection.
"""

from __future__ import annotations

import hashlib
import json
import secrets
import shutil
from datetime import datetime, timezone
from typing import Any

from alibi import checks, verifier
from alibi.contracts import AnswerKey, EvidenceManifest, InvestigationReport, Score, SourceInfo
from alibi.episode import (
    EpisodeError,
    EpisodePaths,
    _make_readonly,
    _write_json,
    bundle_hash,
    load_answer_key,
    load_episode_manifest,
    load_manifest,
    sha256_file,
    verify_raw_integrity,
)
from alibi.evidence.normalize import normalize_bundle
from alibi.evidence.store import EvidenceStore, build_store
from alibi.scoring import effect_event_ids, raw_index

MAX_EXCLUDED = 20
NO_RECORD_REASON = "every record this step produced is in a source withheld from this evidence view"


def public_source(s: SourceInfo) -> dict[str, Any]:
    return {"source_id": s.source_id, "artifact": s.artifact, "host": s.host, "source": s.source,
            "tamper_exposure": s.tamper_exposure, "lines": s.line_count}


def select_sources(manifest: EvidenceManifest, excluded_source_ids: list[str]) -> tuple[list[SourceInfo], list[SourceInfo]]:
    """(kept, withheld). Only ids that are in the public manifest are accepted; nothing here is a path."""
    wanted = list(dict.fromkeys(str(i) for i in excluded_source_ids))
    if not wanted:
        raise ValueError("name at least one source to withhold")
    if len(wanted) > MAX_EXCLUDED:
        raise ValueError(f"at most {MAX_EXCLUDED} sources can be withheld")
    by_id = {s.source_id: s for s in manifest.sources}
    unknown = [i for i in wanted if i not in by_id]
    if unknown:
        raise ValueError(f"unknown source id(s): {unknown[:5]}. Use the source_id values from this case's manifest")
    withheld = [by_id[i] for i in wanted]
    kept = [s for s in manifest.sources if s.source_id not in set(wanted)]
    if not kept:
        raise ValueError("at least one source must remain in the evidence view")
    return kept, withheld


def create_child_bundle(parent: EpisodePaths, child: EpisodePaths, excluded_source_ids: list[str]) -> EvidenceManifest:
    """Derive the child's evidence and sealed records from the parent. The parent is only read."""
    if child.root.exists() or child.sealed.exists():
        raise EpisodeError(f"episode {child.episode_id} already exists; evidence is immutable, choose a new id")
    problems = verify_raw_integrity(parent)
    if problems:  # never derive an experiment from evidence that no longer matches its own hashes
        raise EpisodeError("the original evidence failed its integrity check: " + "; ".join(problems[:3]))
    pm = load_manifest(parent)
    kept, withheld = select_sources(pm, excluded_source_ids)

    hashes: dict[str, str] = {}
    for s in kept:
        dest = child.raw / s.artifact
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(parent.raw / s.artifact, dest)  # the same bytes, never rewritten
        hashes[s.artifact] = sha256_file(dest)
        if hashes[s.artifact] != s.sha256:
            raise EpisodeError(f"copy of {s.artifact} does not match the original hash")
    raw_hash = bundle_hash(hashes)
    _make_readonly(child.raw)

    # The event store is rebuilt from the child's own raw files, so no record of a withheld source exists in it.
    events, errors = normalize_bundle(child.raw, list(hashes))
    build_store(child.db, events)
    db_hash = sha256_file(child.db)
    child.db.chmod(0o444)

    kinds = sorted({f"{s.host} {s.source}" for s in withheld})
    manifest = pm.model_copy(deep=True, update={
        "bundle_id": f"bndl-{raw_hash[:16]}", "sources": [s.model_copy(deep=True) for s in kept],
        "raw_bundle_sha256": raw_hash, "derived_db_sha256": db_hash, "event_count": len(events),
        "normalization_errors": errors, "capture_complete": False,
        "capture_notes": list(pm.capture_notes) + [
            "This evidence view does not contain every source that exists at the site. Not available here: "
            + ", ".join(kinds) + ". What those sources would have shown is unknown."],
    })
    _write_json(child.manifest, manifest.model_dump(mode="json"))
    child.case.mkdir(parents=True, exist_ok=True)  # fresh and empty: nothing is carried over from the parent

    # Sealed side: what was executed is unchanged; observability is recomputed against the child's evidence.
    pkey, pep = load_answer_key(parent), load_episode_manifest(parent)
    with EvidenceStore(child.db) as store:
        index = raw_index(store)
        effects = []
        for e in pkey.effects:
            here = effect_event_ids(e, store, index)
            still = e.observable and bool(here)
            effects.append(e.model_copy(update={
                "observable": still,
                "unobservable_reason": e.unobservable_reason if still or not e.observable else NO_RECORD_REASON}))
    key = pkey.model_copy(deep=True, update={"episode_id": child.episode_id, "effects": effects,
                                              "canary": f"CANARY-{secrets.token_hex(12)}"})
    child.sealed.mkdir(parents=True, exist_ok=True)
    _write_json(child.answer_key, key.model_dump(mode="json"))
    ep = pep.model_copy(deep=True, update={
        "episode_id": child.episode_id, "bundle_id": manifest.bundle_id, "raw_bundle_sha256": raw_hash,
        "evidence_files": hashes, "created_at": datetime.now(timezone.utc),
        "parent_episode_id": parent.episode_id, "parent_raw_bundle_sha256": pm.raw_bundle_sha256,
        "withheld_sources": [public_source(s) | {"sha256": s.sha256} for s in withheld]})
    _write_json(child.episode_manifest, ep.model_dump(mode="json"))
    return manifest


def tree_digest(paths: EpisodePaths) -> str:
    """A digest over an episode's evidence and sealed files (names and bytes). Used to show a parent is untouched."""
    h = hashlib.sha256()
    for base in (paths.evidence, paths.sealed):
        for f in sorted(p for p in base.rglob("*") if p.is_file()):
            h.update(str(f.relative_to(base)).encode("utf-8") + b"\x00" + sha256_file(f).encode("ascii") + b"\n")
    return h.hexdigest()


# ----------------------------------------------------------------------------- deterministic comparison


def _coverage(store: EvidenceStore, manifest: EvidenceManifest) -> dict[str, Any]:
    from alibi.runners import summarize_reconcile, summarize_transfers

    rec, xfer = checks.reconcile_logs(store, manifest), checks.correlate_transfers(store, manifest)
    return {"local_vs_collector": summarize_reconcile(rec)[0], "transfers": summarize_transfers(xfer)[0],
            "limits": list(rec.get("coverage_limits", [])) + list(xfer.get("coverage_limits", [])),
            "files_not_assessable": rec.get("coverage", {}).get("files_not_assessable", [])}


def compare(parent_report: InvestigationReport | None, parent_store: EvidenceStore, parent_manifest: EvidenceManifest,
            child_store: EvidenceStore, child_manifest: EvidenceManifest) -> dict[str, Any]:
    """What happens to each of the parent report's claims when the withheld sources are gone.

    Pure and deterministic: the same registered predicates the verifier uses, run on the child's
    evidence. It reads no sealed file and states no conclusion of its own. A claim that loses support
    becomes "cannot be established from this view", which is different from "did not happen".
    """
    out: dict[str, Any] = {
        "method": "each claim of the original report is re-checked against the reduced evidence with the same "
                  "deterministic predicates; no model is involved and no ground truth is read",
        "coverage": {"parent": _coverage(parent_store, parent_manifest), "child": _coverage(child_store, child_manifest)},
        "claims": [], "attribution": None, "summary": None,
    }
    if parent_report is None:
        out["note"] = ("The original case has no report yet, so there are no claims to compare. The coverage change "
                       "above is already final; claim changes appear once the original case has a report.")
        return out
    obs = verifier.compute_observations(child_store, child_manifest)
    counts = {"retains_support": 0, "loses_support": 0, "never_supported": 0}
    for f in parent_report.findings:
        cited = list(dict.fromkeys(f.evidence_ids + f.counterevidence_ids))
        here = child_store.existing_ids(cited) if cited else set()
        gone = [i for i in f.evidence_ids if i not in here]
        probe = f.model_copy(deep=True, update={
            "evidence_ids": [i for i in f.evidence_ids if i in here],
            "counterevidence_ids": [i for i in f.counterevidence_ids if i in here],
            "status": f.status if f.status == "downgraded_by_skeptic" else "proposed",
            "verification_status": "not_checked", "verifier_notes": []})
        again = verifier.verify_finding(probe, child_store, obs)
        was = f.verification_status == "supported_observation"
        now = again.verification_status == "supported_observation"
        change = "retains_support" if was and now else "loses_support" if was else "never_supported"
        counts[change] += 1
        if now:
            reason = "the deterministic check still supports this from the remaining evidence" + (
                f" ({len(gone)} of its cited record(s) are in a withheld source)" if gone else "")
        elif f.evidence_ids and not probe.evidence_ids:
            reason = "every record cited for this claim is in a withheld source; it cannot be established from this view"
        else:
            reason = (again.verifier_notes or ["no deterministic support in this view"])[0]
        out["claims"].append({
            "finding_id": f.id, "claim_type": f.claim_type, "category": f.category, "host": f.host,
            "object_or_session": f.object_or_session,
            "parent": {"status": f.status, "verification_status": f.verification_status},
            "child": {"verification_status": again.verification_status,
                      "establishable": now, "state": "supported" if now else "cannot_be_established_here"},
            "change": change, "reason": reason,
            "evidence_ids_remaining": probe.evidence_ids, "evidence_ids_withheld": gone,
        })
    ref = parent_report.attribution.session_ref
    if ref:
        p = checks.assess_presence(parent_store, parent_manifest, ref)
        c = checks.assess_presence(child_store, child_manifest, ref)
        same = p.get("observation") == c.get("observation")
        out["attribution"] = {
            "session_ref": ref, "account_used": parent_report.attribution.account_used,
            "parent_observation": p.get("observation"), "child_observation": c.get("observation"),
            "change": "unchanged" if same else "weakened",
            "child_statement": c.get("statement") or "The session cannot be examined in this evidence view.",
            "evidence_ids_remaining": sorted(child_store.existing_ids(
                parent_report.attribution.supporting_evidence_ids + parent_report.attribution.contrary_evidence_ids)),
            "note": "Account activity identifies a credential, not a person, with or without this source.",
        }
    out["summary"] = {**counts, "claims_total": len(parent_report.findings),
                      "reading": "loses_support means the claim cannot be established from this evidence view. "
                                 "It does not mean the event did not happen."}
    return out


# ----------------------------------------------------------------------------- research scoring of a child


def scoring_summary(score: Score, child_key: AnswerKey, parent_key: AnswerKey, child_store: EvidenceStore,
                    parent_store: EvidenceStore) -> dict[str, Any]:
    """Recall for a child, with every original effect listed and both denominators stated."""
    c_index, p_index = raw_index(child_store), raw_index(parent_store)
    outcome = {o.effect_id: o.outcome for o in score.effect_outcomes}
    rows = []
    for e in parent_key.effects:
        mine = next(x for x in child_key.effects if x.effect_id == e.effect_id)
        got = outcome.get(e.effect_id, "unobservable")
        rows.append({
            "effect_id": e.effect_id, "effect_type": e.effect_type, "host": e.host,
            "records_in_original": len(effect_event_ids(e, parent_store, p_index)),
            "records_in_this_view": len(effect_event_ids(mine, child_store, c_index)),
            "observable_in_original": e.observable, "observable_in_this_view": mine.observable,
            "outcome": "caught" if got == "caught" else "not_established" if mine.observable else "no_record_in_this_view",
        })
    total = len([e for e in parent_key.effects if e.observable])
    here = sum(r["observable_in_this_view"] for r in rows)
    caught = sum(r["outcome"] == "caught" for r in rows)
    return {
        "effects_total_original": total, "effects_with_records_in_this_view": here,
        "effects_with_no_record_in_this_view": total - here, "caught": caught,
        "recall_conditional": {"num": caught, "den": here, "value": (caught / here) if here else None,
                               "meaning": "of the effects that still have a record in this view"},
        "recall_of_all_original": {"num": caught, "den": total, "value": (caught / total) if total else None,
                                   "meaning": "of every effect that was observable in the original evidence"},
        "effects": rows,
        "note": ("Fewer effects are observable here because evidence was withheld, not because less happened. "
                 "'not_established' means a record remains but the report did not establish the effect; "
                 "'no_record_in_this_view' means nothing the step produced is in this evidence."),
    }


def describe(parent_manifest: EvidenceManifest, child_manifest: EvidenceManifest, withheld: list[dict[str, Any]]) -> dict[str, Any]:
    return {"parent_bundle_id": parent_manifest.bundle_id, "parent_raw_bundle_sha256": parent_manifest.raw_bundle_sha256,
            "child_bundle_id": child_manifest.bundle_id, "child_raw_bundle_sha256": child_manifest.raw_bundle_sha256,
            "excluded_sources": [{k: v for k, v in s.items() if k != "sha256"} for s in withheld],
            "sources_remaining": len(child_manifest.sources), "events_remaining": child_manifest.event_count,
            "events_original": parent_manifest.event_count}


__all__ = ["compare", "create_child_bundle", "describe", "public_source", "scoring_summary", "select_sources", "tree_digest"]
_ = json  # (kept for callers that serialize the results)
