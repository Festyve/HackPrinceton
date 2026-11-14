"""Exercise real HTTP processes locally with SIM provenance; Docker remains separate.

These regression tests run the same handlers as the containers. They test receipt
ordering, byte preservation and coverage without manufacturing DOCKER fixtures.
"""
import importlib.util
import json
import threading
from contextlib import contextmanager
from pathlib import Path

import pytest

from alibi.capture.manifest import COLLECTOR, LOCAL, package_capture
from alibi.checks import reconcile_logs
from alibi.episode import episode_paths
from alibi.evidence.store import EvidenceStore
from alibi.importing import ImportError_, import_bundle, load_capture

spec = importlib.util.spec_from_file_location("capture_runtime", Path(__file__).parents[1] / "capture/runtime.py")
runtime = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runtime)


@contextmanager
def running(role, root, collector_url=""):
    server = runtime.make_server(role, root, ("127.0.0.1", 0), collector_url)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        thread.join()
        server.server_close()


def capture(tmp_path, mode):
    service_root, collector_root = tmp_path / "service", tmp_path / "collector"
    service_root.mkdir()
    collector_root.mkdir()
    with running("collector", collector_root) as collector_url:
        with running("service", service_root, collector_url) as service_url:
            control = runtime.exercise(service_root, mode, service_url)
    bundle = tmp_path / "bundle"
    for root, artifact in ((service_root, LOCAL), (collector_root, COLLECTOR)):
        dest = bundle / artifact
        dest.parent.mkdir(parents=True)
        dest.write_bytes((root / "evidence" / artifact).read_bytes())
    package_capture(bundle, "test-capture", control, {}, origin="SIM")
    return bundle, control


@pytest.mark.parametrize("mode,expected", [
    ("complete", "consistent"),
    ("missing-local-record", "unexplained_local_absence"),
    ("benign-gap", "inconclusive"),
])
def test_capture_round_trip_and_citations(tmp_path, mode, expected):
    bundle, control = capture(tmp_path, mode)
    local = (bundle / LOCAL).read_bytes().splitlines()
    collector = (bundle / COLLECTOR).read_bytes().splitlines()
    assert len(collector) == 3
    assert len(local) == (3 if mode == "complete" else 2)
    assert len(control["receipts"]) == 3
    public = json.loads((bundle / "capture.json").read_text())
    assert "actions" not in public and "mode" not in public
    assert not (bundle / "control.json").exists()
    if mode == "missing-local-record":
        action = control["actions"][0]
        assert action["at"] > action["receipt"]["received_at"]
        assert b"dummy-2" in collector[1]
        assert all(b"dummy-2" not in line for line in local)
    paths = episode_paths("test-capture", tmp_path / "runs", tmp_path / "sealed")
    manifest = import_bundle(bundle, paths)
    assert manifest.evidence_origin == "SIM"
    assert manifest.normalization_errors == []
    assert not paths.sealed.exists()
    for artifact in (LOCAL, COLLECTOR):
        assert (paths.raw / artifact).read_bytes() == (bundle / artifact).read_bytes()
    with EvidenceStore(paths.db) as store:
        result = reconcile_logs(store, manifest)
        assert len(result["files"]) == 1
        assert result["files"][0]["status"] == expected
        assert len(result["files"][0]["unexplained_local_absence"]) == (mode == "missing-local-record")
        for event in store.scan():
            ref = event.artifact_ref
            original = (paths.raw / ref.artifact).read_bytes()
            assert original[ref.byte_offset:].split(b"\n", 1)[0].decode() == event.raw
            assert original.decode().splitlines()[ref.line - 1] == event.raw


def test_changed_bytes_are_refused(tmp_path):
    bundle, _ = capture(tmp_path, "complete")
    path = bundle / LOCAL
    path.write_bytes(path.read_bytes().replace(b"dummy-1", b"dummy-X"))
    with pytest.raises(ImportError_, match="SHA-256"):
        load_capture(bundle)


def test_failed_forwarding_prevents_fixture_removal(tmp_path):
    # An unavailable collector must never authorize the local removal step.
    root = tmp_path / "service"
    root.mkdir()
    with running("service", root, "http://127.0.0.1:1") as url:
        with pytest.raises(OSError):
            runtime.exercise(root, "missing-local-record", url)
    assert b"dummy-1" in (root / "evidence" / LOCAL).read_bytes()
    assert not (root / "control.json").exists()


@pytest.mark.parametrize("mode,expected", [
    ("complete", "consistent"),
    ("missing-local-record", "unexplained_local_absence"),
    ("benign-gap", "inconclusive"),
])
def test_frozen_docker_fixture_offline(tmp_path, mode, expected):
    bundle = Path(__file__).parent / "fixtures" / "capture" / mode
    capture_manifest, files = load_capture(bundle)
    assert capture_manifest.evidence_origin == "DOCKER"
    assert capture_manifest.captured_by.image_digests["service"].startswith("sha256:")
    paths = episode_paths("frozen-capture", tmp_path / "runs", tmp_path / "sealed")
    manifest = import_bundle(bundle, paths)
    assert manifest.normalization_errors == []
    for artifact, original in files.items():
        assert (paths.raw / artifact).read_bytes() == original.read_bytes()
    with EvidenceStore(paths.db) as store:
        result = reconcile_logs(store, manifest)["files"][0]
        assert result["status"] == expected
        assert len(result["unexplained_local_absence"]) == (mode == "missing-local-record")
        for event in store.scan():
            ref = event.artifact_ref
            raw = (paths.raw / ref.artifact).read_bytes()
            assert raw[ref.byte_offset:].split(b"\n", 1)[0].decode() == event.raw


@pytest.mark.parametrize("change,expected", [
    ("late-start", "inconclusive"),
    ("duplicate-reordered-delivery", "consistent"),
    ("removed-collector", "not_assessable"),
])
def test_coverage_and_delivery_controls(tmp_path, change, expected):
    """Independent changes to frozen input exercise uncertainty and deduplication.

    Modified bytes are explicitly SIM test inputs. The committed Docker fixture
    stays immutable. Each variant changes one condition in the complete bundle.
    """
    import shutil
    from datetime import datetime

    source = Path(__file__).parent / "fixtures/capture/complete"
    bundle = tmp_path / "variant"
    shutil.copytree(source, bundle)
    public = json.loads((bundle / "capture.json").read_text())
    control = {"capture_start": public["capture_start"],
               "capture_end": public["capture_end"], "known_gaps": []}
    if change == "duplicate-reordered-delivery":
        file = bundle / COLLECTOR
        lines = file.read_bytes().splitlines(keepends=True)
        file.write_bytes(lines[2] + lines[0] + lines[1] + lines[1])
    elif change == "late-start":
        file = bundle / LOCAL
        lines = file.read_bytes().splitlines(keepends=True)
        file.write_bytes(lines[1] + lines[2])
    else:
        (bundle / COLLECTOR).unlink()
    package_capture(bundle, "variant-test", control, {}, origin="SIM")
    if change == "late-start":
        public = json.loads((bundle / "capture.json").read_text())
        next_line_time = lines[1].split(b" ", 1)[0].decode()
        for artifact in public["artifacts"]:
            if artifact["path"] == LOCAL:
                artifact["coverage_start"] = datetime.fromisoformat(next_line_time).isoformat()
        (bundle / "capture.json").write_text(json.dumps(public))
    paths = episode_paths("variant-test", tmp_path / "runs", tmp_path / "sealed")
    manifest = import_bundle(bundle, paths)
    with EvidenceStore(paths.db) as store:
        result = reconcile_logs(store, manifest)["files"][0]
        assert result["status"] == expected
        assert result["unexplained_local_absence"] == []
        if change == "duplicate-reordered-delivery":
            assert result["collector_duplicate_deliveries"] == 1
