"""Phase-one cases are frozen: new case families and steps must not change them.

The values below were computed at commit 0de232d, BEFORE any simulator, check or baseline
code for the new families existed. A change here means a first-run bundle or baseline
result would no longer reproduce; that needs a version bump and a fresh declared split,
never an edit to this file.
"""

from __future__ import annotations

import hashlib
import json

import pytest

from alibi.baselines import run_b0, run_br
from alibi.episode import artifact_hashes, bundle_hash, load_manifest
from alibi.sim.scenario import build_spec, simulate
from alibi.verifier import verify_report

# (seed, variant) -> raw_bundle_sha256. Benchmark test seeds, demo presets and the development seed.
RAW_BUNDLE_SHA256 = {
    (101, "incident_plain"): "2ef68c85c7b51c206cf5c13b56d370b92a4d6599051d0237461cd8b61125a6da",
    (102, "incident_plain"): "7b554aad640f523c3d091684022162c794a13659efdeba222360e0d20ec43df7",
    (103, "incident_plain"): "6d83f9a2aa5e2a0709c90ee6a19487c6e8302e09229374df9021adad2fd3c09b",
    (104, "incident_plain"): "ec06c6f85e96ca2db941dd37f084b85cbf3769030ba022b8c4efb1c43df892a5",
    (105, "incident_coverup"): "8f72b187cf81b29a7aafddc68898ad289146a6a1821c2572af3e3ef42d58784e",
    (106, "incident_coverup"): "faa4d064f0290fe136225225b961db15fe94e119c4d4da39d61676dec2e4ef5d",
    (107, "incident_coverup"): "de8e9639d3ec6bfbfe702b31775b32149ae36e6d5752416d4bdabc77e15b476f",
    (108, "incident_coverup"): "ceb8e79cfa1580a8021e706c833b9830ae926bb1305afe792dc3a7801d76042e",
    (109, "benign_rotation"): "5e5b5ec67633e67de4db618f30e2fdc0f3d165b993d54bcfbf885f4836d16a68",
    (110, "benign_approved_transfer"): "6b86c8203b2372ed40f0c42b97ebebec41dc609eb2beaa61ecc943e87e80f995",
    (111, "benign_remote_login"): "70dfa7ac0c275aa188d2d3345f00a62baa944ea45c6c02c7bff9048a4f520abc",
    (112, "benign_collection_gap"): "2cd6c099234d468b4eb28bb89a53e6a8dfd4162dd9221ac821d7dee4d7a9c34a",
    (9023, "incident_coverup"): "646e90a648ad486f1b8f81a173ce6b4a865ba8edebef63ce98a367ddbff31444",
    (9002, "incident_plain"): "64e29bb56dd3401b434a91ed70e6691ce339d81f8ef10c71820c75c1a1c2dd73",
    (9003, "benign_rotation"): "d3c60b04d4d51b938049b8ecda21c3e3929a6e5f5620e76433d0f2f14c64bb29",
    (9027, "incident_coverup"): "a4034ce3b4f0422bf67cb7b162d712a764958a0a482f990fd43e2b7832fafc34",
    (3, "incident_plain"): "bf0b5e4a3b2b7c9abf6e15ec9f2294a8068cf2d6e6a9d13689d08f6dbaf8db9c",
    (3, "incident_coverup"): "b3de34b424b527825fb35e55b01125490e21c8d90e771240b9eb3d843fb514a9",
    (3, "benign_rotation"): "e8aca7334d41daeba39d07ec3360c5ed92fe79a14886ed22a0efea1487e264fe",
    (3, "benign_approved_transfer"): "925d897ee0f415867e5136f829d58d83d7ae272998f842d43891cda2f3fac7c2",
    (3, "benign_remote_login"): "75dc82c8024bcfea3a9b5aa133d9460d5f7f237d21490bb3d9223710b5f5a48f",
    (3, "benign_collection_gap"): "4831f84545af745b0ddef3784554b2f48dd2f7bce92227c990049b9d5aaa489b",
}

# (seed, variant) -> (B0 findings digest, BR findings digest, operational-context digest)
BASELINE_DIGESTS = {
    (3, "incident_plain"): ("7648af76573c9c4b", "be3f5c45ec75594a", "5e370fa2e12fcf88"),
    (3, "incident_coverup"): ("5d161a206e95291c", "73c27edab317ac79", "5e370fa2e12fcf88"),
    (3, "benign_rotation"): ("b92b1cd26a28a998", "8c1b89677bacabc8", "5e370fa2e12fcf88"),
    (3, "benign_approved_transfer"): ("3a3a556f018f9b1d", "e2456751b7fd2ec2", "5e370fa2e12fcf88"),
    (3, "benign_remote_login"): ("c06fa74324a54857", "4002420096f42132", "5e370fa2e12fcf88"),
    (3, "benign_collection_gap"): ("4e265ee0971912a3", "301131a6156460dd", "5e370fa2e12fcf88"),
    (9023, "incident_coverup"): ("f906de42c34ed38b", "bfa7556a810e95e4", "b1e38bef11df78ce"),
    (101, "incident_plain"): ("a0fcbb85dfd851b2", "c56d1942e55d55da", "87a594e5a9acd87f"),
}


def _digest(report) -> str:
    rows = sorted((f.claim_type, f.category, f.host, f.object_or_session or "", f.t_start.isoformat(), f.t_end.isoformat(),
                   f.status, f.verification_status, tuple(f.evidence_ids), f.rationale) for f in report.findings)
    return hashlib.sha256(json.dumps(rows, default=str).encode()).hexdigest()[:16]


@pytest.mark.parametrize("seed, variant", sorted(RAW_BUNDLE_SHA256))
def test_first_run_raw_bundles_are_byte_identical(seed, variant):
    sim = simulate(build_spec(seed, variant))
    assert bundle_hash(artifact_hashes(sim.artifacts)) == RAW_BUNDLE_SHA256[(seed, variant)]


@pytest.mark.parametrize("seed, variant", sorted(BASELINE_DIGESTS))
def test_first_run_baseline_results_and_context_are_unchanged(make_episode, store_for, seed, variant):
    p = make_episode(seed, variant)
    st, m = store_for(p), load_manifest(p)
    b0, br, ctx = BASELINE_DIGESTS[(seed, variant)]
    assert _digest(verify_report(run_b0(st, m), st, m)) == b0
    assert _digest(verify_report(run_br(st, m), st, m)) == br
    assert hashlib.sha256(json.dumps(m.operational_context, sort_keys=True, default=str).encode()).hexdigest()[:16] == ctx
