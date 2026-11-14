"""Shared data contracts (PLAN section 6).

Public evidence types (Event, EvidenceManifest, Finding, ...) and private truth
types (AnswerKeyStep, TruthEffect, AnswerKey, EpisodeManifest) live in one module so
producers and consumers cannot drift, but they are versioned independently and the
private types are only ever serialized by trusted orchestrator/scorer code.

Extend only by adding optional fields.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

EVIDENCE_SCHEMA_VERSION = "1.0.0"
TRUTH_SCHEMA_VERSION = "1.0.0"
REPORT_SCHEMA_VERSION = "1.0.0"

HostRole = Literal["workstation", "records", "iot-hub", "collector", "tap"]

EvidenceOrigin = Literal["SIM", "DOCKER", "HYBRID"]
InferenceMode = Literal["LIVE_MODEL", "RECORDED_MODEL", "SCRIPTED_FIXTURE", "NO_MODEL_BASELINE"]
PlaybackMode = Literal["LIVE", "REPLAY"]

INFERENCE_LABELS: dict[str, str] = {
    "LIVE_MODEL": "Live model",
    "RECORDED_MODEL": "Recorded AI run",
    "SCRIPTED_FIXTURE": "Scripted fixture · no model inference",
    "NO_MODEL_BASELINE": "Deterministic baseline · no model inference",
}


def utc(dt: datetime) -> datetime:
    """Normalize to an aware UTC datetime."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def iso(dt: datetime) -> str:
    return utc(dt).strftime("%Y-%m-%dT%H:%M:%S+00:00")


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


# --------------------------------------------------------------------------- evidence


class ArtifactRef(Strict):
    """Provenance of one normalized row: which captured file and where in it."""

    artifact: str  # path relative to the evidence bundle root
    line: int  # 1-based line number
    byte_offset: int


class Event(Strict):
    """One normalized row of evidence.

    `actor` is an *observed account or device*, never the hidden true operator.
    `ts` is the timestamp as recorded by the source; it is never "fixed" at ingest.
    """

    id: str
    ts: datetime
    ts_raw: str
    host: str
    source: str
    actor: str | None = None
    action: str
    object: str | None = None
    attrs: dict[str, Any] = Field(default_factory=dict)
    raw: str
    artifact_ref: ArtifactRef
    clock_assumption: str = "source clock recorded as UTC; no skew correction applied"
    ts_normalized: datetime | None = None
    ts_uncertainty_s: float | None = None

    @field_validator("ts")
    @classmethod
    def _ts_utc(cls, v: datetime) -> datetime:
        return utc(v)


class CoverageGap(Strict):
    """A stated interval in which a source is known NOT to have been recording."""

    start: datetime
    end: datetime
    reason: str = ""


class SourceInfo(Strict):
    """Explicit trust/coverage metadata for one evidence source."""

    artifact: str
    host: str
    source: str
    logical_file: str | None = None  # e.g. /var/log/auth.log for auth.log and auth.log.1
    sha256: str
    size_bytes: int
    line_count: int
    origin: EvidenceOrigin = "SIM"
    # who could have modified this artifact inside the modeled world
    tamper_exposure: Literal["host_local_writable", "independent_witness"]
    coverage_start: datetime | None = None
    coverage_end: datetime | None = None
    coverage_note: str = ""
    # False: coverage_start/end are just the first and last record that survive in the artifact.
    # True: they are a statement by whoever captured the source about when it was recording.
    coverage_declared: bool = False
    known_gaps: list[CoverageGap] = Field(default_factory=list)
    forwarded_to_collector: bool = False


class EvidenceManifest(Strict):
    """Investigator-visible manifest. Contains no seed, card, difficulty, plan or truth."""

    bundle_id: str
    schema_version: str = EVIDENCE_SCHEMA_VERSION
    normalizer_version: str
    evidence_origin: EvidenceOrigin = "SIM"
    capture_start: datetime
    capture_end: datetime
    capture_complete: bool = True
    capture_notes: list[str] = Field(default_factory=list)
    sources: list[SourceInfo]
    raw_bundle_sha256: str  # hash over the sorted (artifact, sha256) list
    derived_db_sha256: str | None = None
    event_count: int | None = None
    normalization_errors: list[str] = Field(default_factory=list)
    operational_context: dict[str, Any] = Field(default_factory=dict)
    integrity_note: str = (
        "Hashes support integrity checking after capture. They do not prove the original "
        "source was truthful and are not a legal chain of custody."
    )


# --------------------------------------------------------------------------- findings

ClaimType = Literal[
    "local_log_removal",
    "policy_violating_transfer",
    "data_staging",
    "collection_gap",
    "retention_explained_absence",
    "policy_consistent_transfer",
    "account_use",
    "other",
    # --- phase two (additive): remaining case families and bounded steps
    "timestamp_alteration",  # a file's recorded modification time contradicts independent records
    "forwarding_stopped",  # log forwarding stopped by a recorded command outside approved maintenance
    "second_host_session",  # a session on one host opened from another monitored host, outside access policy
    "sensor_stream_discrepancy",  # a local sensor stream disagrees with its independent reference
    "shell_history_gap",  # note: recorded activity with no matching shell-history command
    "metadata_change",  # note: a file's metadata changed after its recorded modification time
    "temperature_excursion",  # note: readings outside the stated range, in agreement across sources
    "sensor_maintenance",  # note: a discrepancy inside a stated maintenance or clock condition
    "policy_consistent_access",  # note: cross-host access or a forwarding stop covered by a change record
]
FindingCategory = Literal[
    "incident_allegation",  # asserts a scorable incident effect occurred
    "neutral_reconstruction",  # what happened, without alleging wrongdoing
    "benign_explanation",  # a suspicious-looking thing explained benignly
    "unresolved",  # an anomaly whose cause is not established
]
FindingStatus = Literal["proposed", "verified", "rejected_by_verifier", "downgraded_by_skeptic"]
VerificationStatus = Literal[
    "not_checked",
    "invalid_reference",  # cites ids that do not exist in the bundle
    "structurally_valid",  # ids resolve and are consistent with host/window
    "supported_observation",  # a registered rule predicate confirms the modeled observation
    "unresolved_interpretation",  # ids are fine but no predicate supports the claim
]

INCIDENT_CLAIM_TYPES: tuple[str, ...] = (
    "local_log_removal",
    "policy_violating_transfer",
    "data_staging",
    "timestamp_alteration",
    "forwarding_stopped",
    "second_host_session",
    "sensor_stream_discrepancy",
)


class Finding(Strict):
    """A claim produced by an investigator system.

    `verified` only ever means "a deterministic predicate supports this modeled
    observation". It never means a person is proven responsible.
    """

    id: str
    claim_type: ClaimType
    category: FindingCategory
    attack_id: str | None = None
    technique_family: str | None = None
    host: str
    actor_claimed: str | None = None  # a human named as responsible; normally None
    account_used: str | None = None
    t_start: datetime
    t_end: datetime
    object_or_session: str | None = None
    evidence_ids: list[str] = Field(default_factory=list)
    counterevidence_ids: list[str] = Field(default_factory=list)
    check_refs: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    rationale: str = ""
    assumptions: list[str] = Field(default_factory=list)
    alternative_explanations: list[str] = Field(default_factory=list)
    status: FindingStatus = "proposed"
    verification_status: VerificationStatus = "not_checked"
    verifier_notes: list[str] = Field(default_factory=list)
    skeptic_note: str | None = None
    produced_by: str | None = None  # lead / integrity-auditor / B0 / BR ...

    @field_validator("t_start", "t_end")
    @classmethod
    def _utc(cls, v: datetime) -> datetime:
        return utc(v)


HumanIdentity = Literal["supported_named_actor", "unknown", "insufficient_evidence", "not_assessed"]
ReviewStatus = Literal["pending", "accepted", "rejected", "skipped_for_benchmark"]


class AttributionAssessment(Strict):
    """Separates account use from human identity. Replaces an automatic accusation."""

    account_used: str | None = None
    session_ref: str | None = None
    human_identity: HumanIdentity = "not_assessed"
    named_person_accused: str | None = None
    named_person_exonerated: str | None = None
    supporting_evidence_ids: list[str] = Field(default_factory=list)
    contrary_evidence_ids: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    limits: list[str] = Field(default_factory=list)
    statement: str = ""
    review_status: ReviewStatus = "pending"
    approved_by_human: bool = False
    approved_at: datetime | None = None


class Usage(Strict):
    """Measured resource use. 'No paid charge' does not mean 'no model usage'."""

    llm_calls: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    tokens_cache_read: int = 0
    cost_estimate_usd: float = 0.0
    wall_seconds: float | None = None  # investigation time excluding human review
    tool_calls: int = 0
    scripted_turns: int = 0  # turns produced by a scripted policy, never a model
    retries: int = 0
    errors: int = 0
    timed_out: bool = False


class ReviewEvent(Strict):
    at: datetime
    decision: Literal["accepted", "rejected", "skipped_for_benchmark"]
    by_human: bool
    note: str = ""


class InvestigationReport(Strict):
    schema_version: str = REPORT_SCHEMA_VERSION
    report_id: str
    bundle_id: str
    system_id: str  # B0 | BR | B1 | B1+ | B2 | ALIBI | ALIBI-FIXTURE
    system_label: str = ""
    inference_mode: InferenceMode
    model_id: str | None = None
    findings: list[Finding] = Field(default_factory=list)
    attribution: AttributionAssessment = Field(default_factory=AttributionAssessment)
    summary: str = ""
    open_questions: list[str] = Field(default_factory=list)
    usage: Usage = Field(default_factory=Usage)
    created_at: datetime | None = None
    locked: bool = False
    locked_at: datetime | None = None
    report_sha256: str | None = None
    review_history: list[ReviewEvent] = Field(default_factory=list)
    verifier_version: str | None = None


# --------------------------------------------------------------------------- private truth

EffectType = Literal[
    "data_staging", "policy_violating_transfer", "local_log_removal",
    # --- phase two (additive)
    "timestamp_alteration", "forwarding_stopped", "second_host_session", "sensor_stream_discrepancy",
    "shell_history_removal",  # never observable in a capture: shell history has no independent copy
]
ExecutionStatus = Literal["succeeded", "failed", "partial"]


class EvidencePointer(Strict):
    """Private pointer from truth to a captured line (resolved to Event ids by the scorer)."""

    artifact_logical: str  # e.g. "workstation:/var/log/auth.log", "tap:flows", "collector"
    raw_sha256: str  # sha256 of the exact raw line as generated
    role: Literal["direct", "collector_copy", "removed_local"] = "direct"
    ts: datetime | None = None


class TruthEffect(Strict):
    """A successful, scorable effect of an executed step. Sealed."""

    effect_id: str
    step_id: str
    effect_type: EffectType
    host: str
    object: str  # destination, file path, or logical log path
    session: str | None = None
    t_start: datetime
    t_end: datetime
    observable: bool = True
    unobservable_reason: str | None = None
    evidence: list[EvidencePointer] = Field(default_factory=list)


class AnswerKeyStep(Strict):
    """One step the adversary attempted, as actually executed. Sealed."""

    step_id: str
    step_name: str
    attack_id: str | None = None
    attack_label: str | None = None
    host: str
    operator_true: str
    account_used: str | None = None
    t_start: datetime
    t_end: datetime
    params: dict[str, Any] = Field(default_factory=dict)
    artifacts_touched: list[str] = Field(default_factory=list)
    difficulty: str
    crime_card_id: str
    execution_status: ExecutionStatus
    outcome: str
    affected_object: str | None = None
    affected_session: str | None = None
    effect_id: str | None = None  # set only when a scorable effect resulted


class BenignOutcome(Strict):
    """A legitimate, suspicious-looking activity in the world. Sealed."""

    outcome_id: str
    kind: str  # scheduled_rotation | approved_bulk_transfer | remote_login | collection_gap | ...
    host: str
    actor_account: str | None = None
    t_start: datetime
    t_end: datetime
    description: str


class AttributionTruth(Strict):
    account_used: str | None = None
    account_owner_person: str | None = None
    operator_true: str | None = None
    framed: bool = False
    session: str | None = None
    # P0 world: no scenario supports naming a human from the modeled evidence.
    named_attribution_supportable: bool = False


class AnswerKey(Strict):
    schema_version: str = TRUTH_SCHEMA_VERSION
    episode_id: str
    crime_card_id: str
    case_kind: Literal["incident", "benign"]
    difficulty: str
    steps: list[AnswerKeyStep] = Field(default_factory=list)
    effects: list[TruthEffect] = Field(default_factory=list)
    benign_outcomes: list[BenignOutcome] = Field(default_factory=list)
    attribution: AttributionTruth = Field(default_factory=AttributionTruth)
    executed_plan_sha256: str = ""
    canary: str  # unique private token; must never appear in investigator-visible output


class EpisodeManifest(Strict):
    """Orchestrator/scorer only until reveal."""

    schema_version: str = TRUTH_SCHEMA_VERSION
    episode_id: str
    bundle_id: str
    seed: int
    backend: Literal["sim", "docker", "hybrid"] = "sim"
    simulator_version: str
    scenario_version: str
    crime_card_id: str
    case_kind: Literal["incident", "benign"]
    variant: str
    difficulty: str
    plan_source: Literal["scripted_scenario", "model_generated"] = "scripted_scenario"
    plan_model_id: str | None = None
    scenario_spec: dict[str, Any] = Field(default_factory=dict)
    executed_plan_sha256: str = ""
    raw_bundle_sha256: str = ""
    evidence_files: dict[str, str] = Field(default_factory=dict)  # artifact -> sha256
    # nondeterministic run metadata, kept apart from deterministic evidence hashes
    created_at: datetime | None = None
    git_commit: str | None = None
    package_versions: dict[str, str] = Field(default_factory=dict)


# --------------------------------------------------------------------------- scoring


class Ratio(Strict):
    """A metric with integer numerator/denominator. value is None when not applicable."""

    num: int | None = None
    den: int | None = None
    value: float | None = None
    na_reason: str | None = None

    @classmethod
    def of(cls, num: int, den: int, na_reason: str = "denominator is zero") -> "Ratio":
        if den == 0:
            return cls(num=num, den=den, value=None, na_reason=na_reason)
        return cls(num=num, den=den, value=num / den)

    @classmethod
    def na(cls, reason: str) -> "Ratio":
        return cls(num=None, den=None, value=None, na_reason=reason)


class MatchRecord(Strict):
    finding_id: str
    effect_id: str
    effect_type: str


class FindingOutcome(Strict):
    finding_id: str
    outcome: Literal[
        "matched",  # final accepted allegation matched one truth effect
        "matched_but_not_accepted",  # would match, but rejected/unresolved after verification
        "unsupported",  # final accepted allegation with no matching truth effect
        "rejected",  # proposal rejected/downgraded; no truth match
        "duplicate",  # compatible with an effect already credited to another finding
        "not_an_allegation",  # benign explanation / neutral / unresolved note
    ]
    effect_id: str | None = None
    reason: str = ""


class EffectOutcome(Strict):
    effect_id: str
    effect_type: str
    host: str
    object: str
    t_start: datetime
    t_end: datetime
    outcome: Literal["caught", "missed", "unobservable"]
    finding_id: str | None = None
    description: str = ""


class Score(Strict):
    scorer_version: str
    report_id: str
    episode_id: str
    system_id: str
    inference_mode: InferenceMode
    case_kind: Literal["incident", "benign"]
    step_recall: Ratio
    proposal_precision: Ratio
    final_precision: Ratio
    evidence_reference_validity: Ratio
    supported_claim_rate: Ratio
    verifier_rejection_rate: Ratio
    coverup_detected: bool | None = None
    coverup_detected_na_reason: str | None = None
    account_identification_correct: bool | None = None
    account_identification_na_reason: str | None = None
    attribution_abstained: bool
    unsupported_named_attribution: int = 0
    false_accusation: bool = False
    named_attribution_correct: bool | None = None
    benign_false_alert: bool | None = None  # only meaningful for benign cases
    false_claims_final: int = 0
    proposals_total: int = 0
    proposals_incident: int = 0
    final_accepted_incident: int = 0
    unobservable_effects: int = 0
    failed_or_partial_steps: int = 0
    matches: list[MatchRecord] = Field(default_factory=list)
    finding_outcomes: list[FindingOutcome] = Field(default_factory=list)
    effect_outcomes: list[EffectOutcome] = Field(default_factory=list)
    usage: Usage = Field(default_factory=Usage)
    review_status: ReviewStatus = "pending"
    approved_by_human: bool = False
    report_sha256: str | None = None
    notes: list[str] = Field(default_factory=list)
