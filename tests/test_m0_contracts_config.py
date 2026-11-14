"""M0: the contracts and the zero-spend configuration behave as specified."""

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from alibi.config import ConfigError, load_settings
from alibi.contracts import (
    AnswerKey,
    ArtifactRef,
    AttributionAssessment,
    Event,
    EvidenceManifest,
    Finding,
    Ratio,
)

T = datetime(2026, 11, 10, 12, 0, 0, tzinfo=timezone.utc)


def _event(**kw):
    base = dict(
        id="ev_0123456789ab",
        ts=T,
        ts_raw="2026-11-10T12:00:00+00:00",
        host="workstation",
        source="auth",
        actor="acct-a",
        action="login",
        object="tty1",
        raw="raw line",
        artifact_ref=ArtifactRef(artifact="workstation/var/log/auth.log", line=1, byte_offset=0),
    )
    base.update(kw)
    return Event(**base)


def test_event_normalizes_naive_timestamp_to_utc_and_keeps_raw():
    ev = _event(ts=datetime(2026, 11, 10, 12, 0, 0))
    assert ev.ts.tzinfo is not None and ev.ts.utcoffset().total_seconds() == 0
    assert ev.ts_raw == "2026-11-10T12:00:00+00:00"


def test_contracts_reject_unknown_fields_so_truth_cannot_ride_along():
    # An investigator-visible Event must not silently accept a truth-bearing field.
    with pytest.raises(ValidationError):
        _event(operator_true="someone")
    with pytest.raises(ValidationError):
        EvidenceManifest(
            bundle_id="b",
            normalizer_version="1",
            capture_start=T,
            capture_end=T,
            sources=[],
            raw_bundle_sha256="x",
            seed=7,
        )


def test_public_manifest_schema_has_no_truth_fields():
    public = set(EvidenceManifest.model_fields)
    forbidden = {"seed", "crime_card", "crime_card_id", "difficulty", "steps", "plan", "score",
                 "operator_true", "canary", "case_kind", "variant", "scenario_spec"}
    assert not (public & forbidden)
    assert "canary" in AnswerKey.model_fields  # the private type does carry it


def test_finding_confidence_bounds_and_default_status():
    f = Finding(id="f1", claim_type="local_log_removal", category="incident_allegation",
                host="workstation", t_start=T, t_end=T)
    assert f.status == "proposed" and f.verification_status == "not_checked"
    with pytest.raises(ValidationError):
        Finding(id="f2", claim_type="local_log_removal", category="incident_allegation",
                host="workstation", t_start=T, t_end=T, confidence=1.5)


def test_attribution_defaults_never_accuse_or_fake_approval():
    a = AttributionAssessment()
    assert a.named_person_accused is None and a.named_person_exonerated is None
    assert a.approved_by_human is False and a.review_status == "pending"


def test_ratio_is_null_with_reason_not_zero_when_not_applicable():
    r = Ratio.of(0, 0, na_reason="no-crime recall is not applicable")
    assert r.value is None and r.na_reason == "no-crime recall is not applicable"
    assert Ratio.of(2, 3).value == pytest.approx(2 / 3)


def test_default_settings_are_offline_and_zero_spend():
    s = load_settings({})
    assert s.runtime_mode == "offline" and s.offline
    assert s.llm_max_usd == 0 and s.bench_max_system_runs == 0
    assert s.host == "127.0.0.1"
    assert "offline" in s.live_block_reason()
    assert s.public_dict()["paid_overage_authorized_usd"] == 0


def test_live_mode_is_blocked_without_explicit_zero_charge_route():
    assert "LEAD_MODEL" in load_settings({"RUNTIME_MODE": "live"}).live_block_reason()
    s = load_settings({"RUNTIME_MODE": "live", "LEAD_MODEL": "x:y"})
    assert "LIVE_PROVIDER_KIND" in s.live_block_reason()
    s = load_settings({"RUNTIME_MODE": "live", "LEAD_MODEL": "anthropic:y",
                       "LIVE_PROVIDER_KIND": "included_credits"})
    assert "LLM_MAX_USD" in s.live_block_reason()
    s = load_settings({"RUNTIME_MODE": "live", "LEAD_MODEL": "anthropic:y",
                       "LIVE_PROVIDER_KIND": "included_credits", "LLM_MAX_USD": "5"})
    assert "pricing" in s.live_block_reason().lower()
    # a provider whose counting and output clamp are not verified is never billed, whatever else is set
    s = load_settings({"RUNTIME_MODE": "live", "LEAD_MODEL": "x:y", "LIVE_PROVIDER_KIND": "included_credits",
                       "LLM_MAX_USD": "5", "LLM_PRICE_IN_PER_MTOK": "1", "LLM_PRICE_OUT_PER_MTOK": "5"})
    assert "Billed routes are limited to anthropic" in s.live_block_reason()
    # and a hosted provider cannot be declared local to escape the money accounting
    s = load_settings({"RUNTIME_MODE": "live", "LEAD_MODEL": "anthropic:y", "LIVE_PROVIDER_KIND": "local"})
    assert "only for models served on this machine" in s.live_block_reason()
    s = load_settings({"RUNTIME_MODE": "live", "LEAD_MODEL": "ollama:y", "LIVE_PROVIDER_KIND": "local"})
    assert s.live_block_reason() is None


def test_ambiguous_legacy_cap_name_is_rejected():
    with pytest.raises(ConfigError):
        load_settings({"BENCH_MAX_LLM_EPISODES": "3"})
    with pytest.raises(ConfigError):
        load_settings({"RUNTIME_MODE": "turbo"})
    with pytest.raises(ConfigError):
        load_settings({"LLM_MAX_USD": "-1"})
