"""M8: the Cold chain case family.

The hub's stored temperature readings (the stream a dashboard shows) against an independent
reference logger with its own probe and clock. One case has a real warming event whose stored
readings were overwritten; the controls are a real warming event left alone, and a calibration
window with a clock offset and a counter restart. The checks report that two records disagree.
They never say why, and never infer intent from temperature.
"""

from __future__ import annotations

import json
import random
from datetime import datetime, timedelta

import pytest

from alibi import checks_families
from alibi.baselines import run_b0, run_br
from alibi.contracts import Finding
from alibi.episode import load_answer_key, load_episode_manifest, load_manifest, reproduce_raw_hash, verify_raw_integrity
from alibi.reports import lock_report
from alibi.scoring import score_report
from alibi.sim import steps as S
from alibi.sim.scenario import (
    CARD_COLD_CHAIN,
    COLDCHAIN_BENIGN_VARIANTS,
    COLDCHAIN_INCIDENT_VARIANTS,
    SENSOR,
    build_spec,
    plan_context,
)
from alibi.sim.world import World, logical_clock_base
from alibi.verifier import compute_observations, verify_finding, verify_report

from .conftest import DEV_SEED
from .helpers import without_sources

ALL = COLDCHAIN_INCIDENT_VARIANTS + COLDCHAIN_BENIGN_VARIANTS
GIVEAWAYS = ("attacker", "adversary", "exfil", "sink", "crime", "framed", "malicious", "incident", "truth", "canary",
             "falsif", "tamper")
INTENT_WORDS = ("deliberate", "intentional", "sabotage", "tampered", "falsified", "fraud", "cover")


def _locked(rep, st, m):
    return lock_report(verify_report(rep, st, m), "skipped_for_benchmark", by_human=False)


def _case(make_episode, store_for, variant, seed=DEV_SEED):
    p = make_episode(seed, variant)
    return p, store_for(p), load_manifest(p), load_answer_key(p)


def _temps(st, source, start, end):
    return [e.attrs["temp_c"] for e in st.scan(source=source) if start <= e.ts <= end]


# ----------------------------------------------------------------- scenario, plan and sources
def test_cold_chain_plan_is_one_bounded_scripted_step():
    for seed in range(1, 9):
        spec = build_spec(seed, "coldchain_falsified")
        assert spec["card_id"] == CARD_COLD_CHAIN and spec["difficulty"] == "C1" and spec["plan_source"] == "scripted_scenario"
        assert S.validate_plan(spec["plan"], plan_context(spec)) == [
            {"step": "falsify_readings", "params": {"sensor": SENSOR, "mode": "flatten"}, "delay_s": 30}]
    for variant in COLDCHAIN_BENIGN_VARIANTS:
        assert build_spec(3, variant)["plan"] == [] and build_spec(3, variant)["case_kind"] == "benign"


@pytest.mark.parametrize("level, sensors, bad, why", [
    ("C1", ("fridge-01",), [{"step": "falsify_readings", "params": {"sensor": "freezer-9", "mode": "flatten"}}], "sensor must be one of"),
    ("C1", (), [{"step": "falsify_readings", "params": {"sensor": "fridge-01", "mode": "flatten"}}], "sensor must be one of"),
    ("C1", ("fridge-01",), [{"step": "falsify_readings", "params": {"sensor": "fridge-01", "mode": "set 4.0; drop table"}}], "mode must be one of"),
    ("C1", ("fridge-01",), [{"step": "falsify_readings", "params": {"sensor": "fridge-01", "mode": "flatten", "value": 4.0}}], "takes sensor, mode"),
    ("C1", ("fridge-01",), [{"step": "login_as", "params": {"account": "A"}}], "not allowed at C1"),
    ("L2", ("fridge-01",), [{"step": "login_as", "params": {"account": "A"}},
                            {"step": "falsify_readings", "params": {"sensor": "fridge-01", "mode": "flatten"}}], "not allowed at L2"),
])
def test_the_sensor_step_takes_only_allowlisted_parameters(level, sensors, bad, why):
    ctx = S.PlanContext(level=level, accounts=("A",), sink_ips=("10.20.9.12",), dataset_sizes={"patients_full": 10}, sensors=sensors)
    with pytest.raises(S.PlanError) as err:
        S.validate_plan(bad, ctx)
    assert why in str(err.value)


def test_the_two_temperature_records_are_separate_sources_with_stated_trust(make_episode, store_for):
    p, st, m, key = _case(make_episode, store_for, "coldchain_real_excursion")
    by = {s.source: s for s in m.sources}
    assert by["sensor"].tamper_exposure == "host_local_writable" and by["sensor"].host == "iot-hub"
    assert by["reference"].tamper_exposure == "independent_witness" and by["reference"].host == "reference"
    assert by["sensor"].origin == by["reference"].origin == "SIM" and "own probe and clock" in by["reference"].coverage_note
    assert m.normalization_errors == [] and verify_raw_integrity(p) == []
    saved, again = reproduce_raw_hash(p)
    assert saved == again == m.raw_bundle_sha256
    local, ref = st.scan(source="sensor"), st.scan(source="reference")
    assert len(local) > 500 and len(ref) > 100 and len(local) > 4 * len(ref)  # one-minute stream vs five-minute logger
    assert all(isinstance(e.attrs["temp_c"], float) and e.attrs["seq"] >= 1 and e.object == SENSOR for e in local + ref)
    assert "not network-synchronised" in ref[0].attrs["clock_note"]  # timestamps are kept as the logger recorded them
    raw_line = (p.raw / ref[0].artifact_ref.artifact).read_text().split("\n")[ref[0].artifact_ref.line - 1]
    assert raw_line == ref[0].raw  # every reading resolves to its exact raw line


def test_cold_chain_cases_share_shape_and_reveal_no_card_plan_or_truth(make_episode):
    manifests = {v: load_manifest(make_episode(DEV_SEED, v)) for v in ALL}
    first = manifests["coldchain_falsified"]
    for v, m in manifests.items():
        assert m.operational_context["tip"] == first.operational_context["tip"]
        assert set(m.operational_context) == set(first.operational_context)
        assert set(m.operational_context["coldchain_policy"]) == set(first.operational_context["coldchain_policy"])
        assert len(m.operational_context["coldchain_policy"]["maintenance_windows"]) == 1  # stated in every case
        assert {s.source for s in m.sources} == {s.source for s in first.sources}
        p = make_episode(DEV_SEED, v)
        canary = load_answer_key(p).canary.lower()
        public = json.dumps(json.loads(p.manifest.read_text())).lower()
        assert canary not in public and "cold-chain" not in public and v not in public
        for field in ("seed", "variant", "difficulty", "crime_card", "plan", "operator"):
            assert f'"{field}' not in public, field
        for f in p.raw.rglob("*"):
            if f.is_file():
                body = f.read_text().lower()
                assert canary not in body and not [w for w in GIVEAWAYS if w in body], (v, f.name)


# ----------------------------------------------------------------- the overwritten record
def test_overwritten_readings_disagree_with_the_reference_and_br_reports_only_that(make_episode, store_for):
    for seed in (DEV_SEED, 5, 12):
        p, st, m, key = _case(make_episode, store_for, "coldchain_falsified", seed)
        lo, hi = m.operational_context["coldchain_policy"]["permitted_range_c"]
        (eff,) = key.effects
        assert (eff.effect_type, eff.host, eff.object, eff.observable) == ("sensor_stream_discrepancy", "iot-hub", SENSOR, True)
        assert (eff.t_end - eff.t_start) <= timedelta(minutes=30)
        assert {ptr.artifact_logical for ptr in eff.evidence} == {"iot-hub:sensor", "reference"}
        # the stored stream now looks normal across the altered interval; the reference still shows the warming
        stored = _temps(st, "sensor", eff.t_start, eff.t_end)
        assert stored and all(lo <= t <= hi for t in stored)
        assert max(_temps(st, "reference", eff.t_start - timedelta(minutes=3), eff.t_end + timedelta(minutes=3))) > hi
        assert not [e for e in st.scan(source="sensor") if e.attrs["state"] == "alarm"]

        res = checks_families.compare_sensor_streams(st, m)
        (bad,) = [d for d in res["discrepancies"] if d["classification"] == "unexplained"]
        assert res["status"] == "discrepancy_unexplained" and bad["reference_readings"] >= 2
        assert bad["reference_out_of_range"] is True and bad["local_out_of_range"] is False
        assert [e["local_agrees"] for e in res["excursions"]] == [False]
        assert res["publish_counter"]["status"] == "match"  # readings were overwritten, not removed
        assert any("does not show which one was changed" in x for x in res["limits"])

        rep = _locked(run_br(st, m), st, m)
        sc = score_report(rep, key, st)
        assert (sc.step_recall.num, sc.step_recall.den) == (1, 1) and sc.final_precision.value == 1.0
        assert sc.evidence_reference_validity.value == 1.0 and sc.false_claims_final == 0
        assert sc.account_identification_correct is None and "no account was used" in sc.account_identification_na_reason
        assert sc.attribution_abstained and not sc.false_accusation and sc.unsupported_named_attribution == 0
        (claim,) = [f for f in rep.findings if f.category == "incident_allegation"]
        assert claim.claim_type == "sensor_stream_discrepancy" and claim.object_or_session == SENSOR and claim.status == "verified"
        refs = {e.source for e in st.get(claim.evidence_ids)}
        assert refs == {"sensor", "reference"}  # both records are cited
        text = (claim.rationale + " " + rep.attribution.statement + " " + rep.summary).lower()
        assert "does not show which was changed, why, or by whom" in claim.rationale
        assert not [w for w in INTENT_WORDS if w in text] and claim.actor_claimed is None and claim.account_used is None
        assert rep.attribution.account_used is None and "Human operator not established" in rep.attribution.statement
        assert any("temperature records" in q for q in rep.open_questions)
        # the keyword recipe has nothing to match in a temperature record
        assert score_report(_locked(run_b0(st, m), st, m), key, st).step_recall.num == 0


# ----------------------------------------------------------------- the controls
def test_a_real_warming_event_left_alone_is_reported_as_an_excursion_not_an_allegation(make_episode, store_for):
    for seed in (DEV_SEED, 5, 12, 33):
        p, st, m, key = _case(make_episode, store_for, "coldchain_real_excursion", seed)
        assert key.case_kind == "benign" and key.effects == [] and key.steps == []
        assert "temperature_excursion" in {b.kind for b in key.benign_outcomes}
        res = checks_families.compare_sensor_streams(st, m)
        assert not [d for d in res["discrepancies"] if d["classification"] == "unexplained"], seed
        assert len(res["excursions"]) == 1 and res["excursions"][0]["local_agrees"] is True
        hi = res["permitted_range_c"][1]
        assert res["excursions"][0]["peak_c"] > hi
        for run in (run_br, run_b0):
            sc = score_report(_locked(run(st, m), st, m), key, st)
            assert sc.benign_false_alert is False and sc.final_accepted_incident == 0, (seed, run.__name__)
        rep = verify_report(run_br(st, m), st, m)
        note = next(f for f in rep.findings if f.claim_type == "temperature_excursion")
        assert note.category == "neutral_reconstruction" and note.verification_status == "supported_observation"
        assert "show the same warming" in note.rationale and "does not show why" in note.rationale
        assert not [w for w in INTENT_WORDS if w in note.rationale.lower()]


def test_calibration_clock_offset_and_counter_restart_are_explained_by_stated_conditions(make_episode, store_for):
    for seed in (DEV_SEED, 5, 12, 33):
        p, st, m, key = _case(make_episode, store_for, "coldchain_maintenance", seed)
        spec = load_episode_manifest(p).scenario_spec
        assert spec["coldchain"]["reference_clock_offset_s"] != 0 and key.effects == []
        assert {"sensor_maintenance", "reference_clock_offset"} <= {b.kind for b in key.benign_outcomes}
        res = checks_families.compare_sensor_streams(st, m)
        mw = m.operational_context["coldchain_policy"]["maintenance_windows"][0]
        assert res["status"] == "discrepancy_explained" and res["excursions"] == []
        assert {d["classification"] for d in res["discrepancies"]} == {"explained_maintenance"}
        assert all(d["maintenance_id"] == mw["id"] for d in res["discrepancies"])
        # the probe's counter restarts when it is reconnected: flagged, and inside the stated window
        assert [r["in_maintenance_window"] for r in res["sequence"]["local_restarts"]] == [True]
        assert res["sequence"]["local_gaps"] == [] and res["publish_counter"]["status"] == "match"
        for run in (run_br, run_b0):
            sc = score_report(_locked(run(st, m), st, m), key, st)
            assert sc.benign_false_alert is False and sc.final_accepted_incident == 0, (seed, run.__name__)
        rep = verify_report(run_br(st, m), st, m)
        note = next(f for f in rep.findings if f.claim_type == "sensor_maintenance")
        assert note.category == "benign_explanation" and mw["id"] in note.rationale
        assert note.verification_status == "supported_observation"


def test_the_stated_window_is_what_explains_the_calibration_readings(make_episode, store_for):
    """The control's evidence, read against a policy that states no maintenance window."""
    p, st, m, key = _case(make_episode, store_for, "coldchain_maintenance")
    cp = {**m.operational_context["coldchain_policy"], "maintenance_windows": []}
    bare = m.model_copy(update={"operational_context": {**m.operational_context, "coldchain_policy": cp}})
    res = checks_families.compare_sensor_streams(st, bare)
    kinds = {d["classification"] for d in res["discrepancies"]}
    assert kinds <= {"unexplained", "isolated_reading"} and kinds  # no window on file, so nothing explains them
    assert [r["in_maintenance_window"] for r in res["sequence"]["local_restarts"]] == [False]


# ----------------------------------------------------------------- verifier predicates
def test_the_verifier_supports_only_a_real_unexplained_discrepancy(make_episode, store_for):
    p, st, m, key = _case(make_episode, store_for, "coldchain_falsified")
    obs = compute_observations(st, m)
    sens = obs.families["sensors"]
    bad = next(d for d in sens["discrepancies"] if d["classification"] == "unexplained")
    cal = next(d for d in sens["discrepancies"] if d["classification"] == "explained_maintenance")

    def claim(ids, start, end):
        return Finding(id="X-1", claim_type="sensor_stream_discrepancy", category="incident_allegation", host="iot-hub",
                       t_start=datetime.fromisoformat(start), t_end=datetime.fromisoformat(end), object_or_session=SENSOR,
                       evidence_ids=ids)

    ok = verify_finding(claim(bad["reference_event_ids"], bad["start"], bad["end"]), st, obs)
    assert ok.status == "verified" and ok.verification_status == "supported_observation"
    in_window = verify_finding(claim(cal["reference_event_ids"] + cal["local_event_ids"][:3], cal["start"], cal["end"]), st, obs)
    assert in_window.status == "rejected_by_verifier" and "maintenance window" in in_window.verifier_notes[0]
    quiet = [e.id for e in st.scan(source="reference")][:2]  # ordinary readings at the start of the shift
    normal = verify_finding(claim(quiet, bad["start"], bad["end"]), st, obs)
    assert normal.status == "proposed" and normal.verification_status == "unresolved_interpretation"
    wrong_time = verify_finding(claim(bad["reference_event_ids"], cal["start"], cal["end"]), st, obs)
    assert wrong_time.status == "proposed" and "outside the stated time window" in wrong_time.verifier_notes[0]
    ghost = verify_finding(claim(["ev_doesnotexist"], bad["start"], bad["end"]), st, obs)
    assert ghost.verification_status == "invalid_reference"


# ----------------------------------------------------------------- absent witnesses
def test_without_the_reference_logger_the_stored_record_cannot_be_checked(make_episode, tmp_path):
    p = make_episode(DEV_SEED, "coldchain_falsified")
    st, m = without_sources(p, tmp_path, {"reference"})
    res = checks_families.compare_sensor_streams(st, m)
    assert res["status"] == "not_assessable" and "reference logger" in res["status_reason"] and "unknown" in res["status_reason"]
    rep = verify_report(run_br(st, m), st, m)
    assert not [f for f in rep.findings if f.category == "incident_allegation"]  # the stored stream alone looks normal ...
    assert not [f for f in rep.findings if f.claim_type in ("temperature_excursion", "sensor_maintenance")]
    assert any(q.startswith("Coverage limit:") and "reference logger" in q for q in rep.open_questions)  # ... and that is said
    assert "unknown" in rep.summary
    obs = compute_observations(st, m)
    ev = st.scan(source="sensor")[300]
    out = verify_finding(Finding(id="X-1", claim_type="sensor_stream_discrepancy", category="incident_allegation",
                                 host="iot-hub", t_start=ev.ts, t_end=ev.ts, object_or_session=SENSOR, evidence_ids=[ev.id]), st, obs)
    assert out.status == "proposed" and "reference logger" in out.verifier_notes[0]
    st.close()

    st, m = without_sources(p, tmp_path, {"sensor"})
    assert checks_families.compare_sensor_streams(st, m)["status"] == "not_assessable"
    assert not [f for f in run_br(st, m).findings if f.category == "incident_allegation"]
    st.close()


# ----------------------------------------------------------------- the step itself
def _hub(readings: list[tuple[int, float, str]], reference: list[tuple[int, float]]) -> tuple[World, S.StepExecutor, datetime]:
    t0 = logical_clock_base() + timedelta(hours=9)
    w = World(random.Random(5), t0 - timedelta(hours=1), t0 + timedelta(hours=2))
    w.sensor_range = (2.0, 8.0)
    for minute, temp, state in readings:
        w.sensor_reading(SENSOR, t0 + timedelta(minutes=minute), temp, state)
    for minute, temp in reference:
        w.reference_reading("logger-01", SENSOR, t0 + timedelta(minutes=minute), temp)
    ctx = S.PlanContext(level="C1", accounts=(), sink_ips=(), dataset_sizes={}, sensors=(SENSOR,))
    return w, S.StepExecutor(w, ctx), t0


def test_falsify_readings_needs_stored_alarm_readings_and_leaves_calibration_readings_alone():
    step = {"step": "falsify_readings", "params": {"sensor": SENSOR, "mode": "flatten"}}
    w, ex, t0 = _hub([(0, 4.5, "ok"), (1, 0.2, "calibration"), (2, 4.6, "ok")], [(1, 4.7)])
    res = ex.execute(step, t0 + timedelta(minutes=30))
    assert res.status == "failed" and res.effect_type is None and "no out-of-range reading" in res.outcome
    assert [r["temp_c"] for r in w.sensor_local[SENSOR]] == [4.5, 0.2, 4.6]  # nothing was touched

    w, ex, t0 = _hub([(0, 4.5, "ok"), (1, 0.2, "calibration"), (10, 9.4, "alarm"), (11, 10.1, "alarm"), (12, 4.9, "ok"),
                      (40, 9.9, "alarm")], [(10, 9.6), (15, 5.0)])
    res = ex.execute(step, t0 + timedelta(minutes=30))  # the alarm at minute 40 has not happened yet
    rows = w.sensor_local[SENSOR]
    assert res.status == "succeeded" and res.observable and res.effect_type == "sensor_stream_discrepancy"
    assert res.effect_window == (t0 + timedelta(minutes=10), t0 + timedelta(minutes=11))
    assert [r["state"] for r in rows] == ["ok", "calibration", "ok", "ok", "ok", "alarm"]
    assert rows[1]["temp_c"] == 0.2 and rows[5]["temp_c"] == 9.9 and all(2.0 <= r["temp_c"] <= 8.0 for r in rows[2:5])
    assert [r["seq"] for r in rows] == [1, 2, 3, 4, 5, 6]  # values were overwritten; no reading was removed
    assert w.sensor_ref["logger-01"][0]["temp_c"] == 9.6  # the reference logger is out of reach
    assert {t.artifact_logical for t in res.traces} == {"iot-hub:sensor", "reference"}


def test_an_altered_interval_the_reference_did_not_record_is_unobservable_and_unscored():
    step = {"step": "falsify_readings", "params": {"sensor": SENSOR, "mode": "flatten"}}
    w, ex, t0 = _hub([(10, 9.4, "alarm"), (11, 10.1, "alarm")], [(60, 4.8)])  # the logger has nothing near minute 10
    res = ex.execute(step, t0 + timedelta(minutes=30))
    assert res.status == "succeeded" and res.observable is False
    assert "recorded no out-of-range reading" in res.unobservable_reason
