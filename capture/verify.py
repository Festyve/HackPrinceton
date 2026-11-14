"""Import and verify a completed Docker capture run, without model calls.

Private controls are read only by this external verifier. Each CLI import receives
just its evidence directory. Verification results stay beside the captured output.
"""
import argparse
import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from alibi.baselines import findings_from_reconcile
from alibi.capture.manifest import COLLECTOR, LOCAL
from alibi.checks import reconcile_logs
from alibi.episode import episode_paths, load_manifest
from alibi.evidence.store import EvidenceStore
from alibi.importing import load_capture

EXPECTED = {
    "complete": "consistent",
    "missing-local-record": "unexplained_local_absence",
    "benign-gap": "inconclusive",
}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def verify_case(output, mode):
    """Use the CLI, then check raw bytes, receipt ordering and imported coverage."""
    bundle = output / "evidence" / mode
    control = json.loads((output / "private" / f"{mode}.json").read_text())
    capture, files = load_capture(bundle)
    require(capture.evidence_origin == "DOCKER", "capture must declare DOCKER provenance")
    require(set(files) == {LOCAL, COLLECTOR}, "unexpected raw artifacts")
    artifact_hashes = {}
    for artifact in capture.artifacts:
        raw = files[artifact.path].read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        require(digest == artifact.sha256, f"hash mismatch for {artifact.path}")
        require(len(raw) == artifact.size_bytes, f"size mismatch for {artifact.path}")
        require(artifact.origin == "DOCKER", "unexpected artifact origin")
        artifact_hashes[artifact.path] = digest

    # This is the existing ALIBI command, invoked through its Python module so
    # the verifier uses exactly the same interpreter and installed dependencies.
    runs, sealed = output / "imported-runs", output / "imported-sealed"
    env = dict(os.environ, RUNTIME_MODE="offline", LLM_MAX_USD="0",
               ALIBI_RUNS_DIR=str(runs), ALIBI_SEALED_DIR=str(sealed))
    completed = subprocess.run(
        [sys.executable, "-m", "alibi.cli", "import", str(bundle), "--runner", "deterministic"],
        env=env, capture_output=True, text=True, check=True,
    )
    imported = json.loads(completed.stdout)
    require(imported["scored"] is False, "import unexpectedly reported a scored case")
    require(imported["state"] == "frozen", "case did not freeze")
    paths = episode_paths(imported["case_id"], runs, sealed)
    manifest = load_manifest(paths)
    require(not paths.sealed.exists(), "unexpected sealed answer key")
    require(not manifest.normalization_errors, "normalization errors")
    for artifact, original in files.items():
        require(original.read_bytes() == (paths.raw / artifact).read_bytes(), "import changed raw bytes")

    with EvidenceStore(paths.db) as store:
        comparison = reconcile_logs(store, manifest)
        require(len(comparison["files"]) == 1, "comparison did not select exactly one file")
        result = comparison["files"][0]
        require(result["status"] == EXPECTED[mode], f"unexpected comparison: {result['status']}")
        findings = findings_from_reconcile(comparison)
        removals = [finding for finding in findings if finding.claim_type == "local_log_removal"]
        require(len(removals) == int(mode == "missing-local-record"), "unexpected removal findings")
        for event in store.scan():
            reference = event.artifact_ref
            raw = (paths.raw / reference.artifact).read_bytes()
            require(raw[reference.byte_offset:].split(b"\n", 1)[0].decode() == event.raw,
                    "byte-offset citation does not resolve")
            require(raw.decode().splitlines()[reference.line - 1] == event.raw,
                    "line citation does not resolve")

    local_lines = files[LOCAL].read_bytes().splitlines()
    collector_lines = files[COLLECTOR].read_bytes().splitlines()
    require(len(collector_lines) == 3, "collector must retain all three deliveries")
    require(len(local_lines) == (3 if mode == "complete" else 2), "unexpected local line count")
    retained = collector_lines[1].split(b" msg=", 1)[1]
    receipt = control["receipts"][1]
    require(hashlib.sha256(retained).hexdigest() == receipt["sha256"], "receipt hash differs from collector")
    require(receipt["seq"] == 2, "unexpected delivery ID")
    require(collector_lines[1].split(b" ", 1)[0].decode() == receipt["received_at"], "receipt timestamp differs")
    if mode == "missing-local-record":
        action = control["actions"][0]
        require(retained not in local_lines, "deliberately removed record still present locally")
        require(action["removed_sha256"] == receipt["sha256"], "removed record hash differs")
        require(datetime.fromisoformat(action["at"]) > datetime.fromisoformat(receipt["received_at"]),
                "removal did not follow collector receipt")

    source = next(source for source in manifest.sources if source.artifact == LOCAL)
    require(source.coverage_declared, "local coverage was not declared")
    if mode == "benign-gap":
        require(len(source.known_gaps) == 1, "missing benign coverage gap")
        gap = source.known_gaps[0]
        sender_time = datetime.fromisoformat(retained.split(b" ", 1)[0].decode())
        require(gap.start <= sender_time <= gap.end, "missing record is outside declared gap")
        require(bool(gap.reason), "coverage gap lacks a reason")
        require(len(result["inconclusive_local_absence"]) == 1, "gap absence not marked inconclusive")

    return {"scenario": mode, "passed": True, "cli": imported,
            "artifact_hashes": artifact_hashes, "raw_bundle_sha256": manifest.raw_bundle_sha256,
            "status": result["status"], "removal_findings": len(removals),
            "coverage_start": source.coverage_start.isoformat(),
            "coverage_end": source.coverage_end.isoformat(),
            "known_gaps": [gap.model_dump(mode="json") for gap in source.known_gaps],
            "private_actions": control["actions"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    output = args.output.resolve()
    results = []
    for mode in EXPECTED:
        try:
            results.append(verify_case(output, mode))
        except Exception as exc:
            # Each scenario is an independent acceptance check. Record its
            # failure and continue so one bad bundle cannot hide other results.
            error = str(exc)
            if isinstance(exc, subprocess.CalledProcessError):
                error += "\n" + (exc.stderr or "")
            results.append({"scenario": mode, "passed": False, "error": error})
    # Contains private action details and therefore belongs with the controls.
    report = output / "private" / "verification.json"
    report.write_text(json.dumps(results, indent=2) + "\n")
    report.chmod(0o600)
    print(json.dumps(results, indent=2))
    return 0 if all(result["passed"] for result in results) else 1


if __name__ == "__main__":
    sys.exit(main())
