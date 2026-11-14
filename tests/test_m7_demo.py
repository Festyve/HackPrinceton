"""M7: the committed demo assets work offline and every displayed citation opens."""

from __future__ import annotations

import json
import re
import socket
import time
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

from alibi import orchestrator as orch_mod
from alibi.api.app import WEB_DIST, create_app
from alibi.config import REPO_ROOT, load_settings
from alibi.orchestrator import PRESETS, REPLAY_DIR, Orchestrator

REPLAYS = sorted(p.parent.name for p in REPLAY_DIR.glob("*/recording.json"))


@pytest.fixture()
def client(tmp_path):
    settings = replace(load_settings({}), runs_dir=tmp_path / "runs", sealed_dir=tmp_path / "sealed")
    return TestClient(create_app(settings, Orchestrator(settings, pace_s=0.0)))


def wait(client, cid, want="awaiting_review"):
    for _ in range(1200):
        v = client.get(f"/api/cases/{cid}").json()
        if v["case"]["state"] in (want, "failed"):
            assert v["case"]["state"] == want, v["case"]
            return v
        time.sleep(0.05)
    raise AssertionError("timeout")


def test_demo_recordings_exist_and_are_labeled_as_fixtures():
    assert "hero-coverup-fixture" in REPLAYS
    for name in REPLAYS:
        data = json.loads((REPLAY_DIR / name / "recording.json").read_text())
        meta = data["meta"]
        assert meta["inference_mode"] in ("SCRIPTED_FIXTURE", "LIVE_MODEL", "NO_MODEL_BASELINE")
        if meta["inference_mode"] == "SCRIPTED_FIXTURE":
            assert "no model" in (meta["model_id"] or "").lower() and "No model inference" in meta["note"]
            assert data["report"]["usage"]["llm_calls"] == 0
        if meta["inference_mode"] == "LIVE_MODEL":  # a recording of a real model run carries its provenance
            assert meta["model_id"] and meta["recorded_at"] and meta["git_commit"]
            assert data["report"]["usage"]["llm_calls"] > 0 and data["report"]["usage"]["tokens_in"] > 0
        assert "sk-ant" not in json.dumps(data)  # no credential ever ends up in a recording


@pytest.mark.parametrize("name", REPLAYS)
def test_committed_recording_replays_with_no_network_and_no_inference(client, name, monkeypatch):
    def no_net(self, addr, *a, **k):
        if isinstance(addr, tuple) and addr[0] not in ("127.0.0.1", "localhost", "::1", "testserver"):
            raise AssertionError(f"replay tried to reach {addr}")
        return orig(self, addr, *a, **k)

    orig = socket.socket.connect
    monkeypatch.setattr(socket.socket, "connect", no_net)
    monkeypatch.setattr(orch_mod, "get_runner", lambda *a, **k: (_ for _ in ()).throw(AssertionError("replay ran a runner")))
    saved = json.loads((REPLAY_DIR / name / "recording.json").read_text())
    v = client.post(f"/api/replays/{name}/open", json={}).json()
    cid = v["case"]["case_id"]
    labels = v["case"]["labels"]
    real = saved["meta"]["inference_mode"] == "LIVE_MODEL"
    # a saved real run replays as a RECORDED model run; a fixture stays a fixture. Neither becomes "live".
    want_mode = "RECORDED_MODEL" if real else saved["meta"]["inference_mode"]
    assert labels["playback"] == "REPLAY" and labels["inference"] == want_mode
    assert labels["inference_label"] == ("Recorded AI run" if real else "Scripted fixture · no model inference")
    if real:
        assert labels["model_id"] == saved["meta"]["model_id"]
    v = wait(client, cid)
    assert v["manifest"]["raw_bundle_sha256"] == saved["meta"]["raw_bundle_sha256"]
    assert len(v["report"]["findings"]) == len(saved["report"]["findings"])
    client.post(f"/api/cases/{cid}/review", json={"decision": "accept"})
    score = client.post(f"/api/cases/{cid}/reveal").json()["reveal"]["score"]
    assert score["inference_mode"] == want_mode
    assert (score["usage"]["llm_calls"] > 0) == real  # usage is the recorded run's usage; the replay itself called no model
    if name.startswith("hero-coverup"):
        assert (score["step_recall"]["num"], score["step_recall"]["den"]) == (3, 3)


@pytest.mark.parametrize("preset", [p["id"] for p in PRESETS if p.get("_planner") != "model"])
def test_every_displayed_citation_opens_its_raw_record(client, preset):
    cid = client.post("/api/cases", json={"preset_id": preset}).json()["case"]["case_id"]
    v = wait(client, cid)
    ids = {i for f in v["report"]["findings"] for i in f["evidence_ids"] + f["counterevidence_ids"]}
    ids |= set(v["report"]["attribution"]["supporting_evidence_ids"]) | set(v["report"]["attribution"]["contrary_evidence_ids"])
    for ex in client.get(f"/api/cases/{cid}/explanations").json()["explanations"]:
        ids |= set(ex["evidence_ids"])
    for ev in client.get(f"/api/cases/{cid}/events.json").json()["events"]:
        if ev["type"] == "tool":
            ids |= set(ev["data"]["evidence_ids"])
    for lane in client.get(f"/api/cases/{cid}/evidence/timeline").json()["lanes"]:
        ids |= {m["event_id"] for m in lane["marks"]} | {i for g in lane["gaps"] for i in g["evidence_ids"]}
    assert len(ids) >= 8
    ids = sorted(ids)
    for i in range(0, len(ids), 40):
        got = client.get(f"/api/cases/{cid}/evidence/events", params={"ids": ",".join(ids[i:i + 40])}).json()
        assert got["missing"] == []
        for ev in got["events"]:
            raw = client.get(f"/api/cases/{cid}/evidence/raw", params={"artifact": ev["artifact"], "line": ev["line"], "radius": 0}).json()
            assert raw["lines"][0]["focus"] and raw["lines"][0]["text"] == ev["raw"], ev["id"]
            assert len(raw["sha256"]) == 64


def test_all_presets_offered_to_the_audience_work_and_hide_their_variant(client):
    listed = client.get("/api/presets").json()["presets"]
    assert [p["id"] for p in listed] == ["hero-coverup", "hero-plain", "sealed-control"]
    assert all("_variant" not in p and "variant" not in p for p in listed)
    assert "benign" not in json.dumps(listed).lower()  # the control case does not announce what it is


def test_built_ui_loads_no_external_asset():
    if not (WEB_DIST / "index.html").exists():
        pytest.skip("web/dist is not built: run `npm --prefix web run build`")
    html = (WEB_DIST / "index.html").read_text()
    assert not re.search(r'(?:src|href)="https?://', html)
    for f in WEB_DIST.rglob("*"):
        if f.suffix == ".css":
            assert not re.search(r"url\(\s*['\"]?https?://|@import", f.read_text()), f.name
        if f.suffix == ".js":
            js = f.read_text()
            assert "fonts.googleapis" not in js and "cdn.jsdelivr" not in js and "unpkg.com" not in js
            assert "dangerouslySetInnerHTML" not in (REPO_ROOT / "web" / "src" / "panels.tsx").read_text()


def test_sim_and_tools_never_emit_an_external_url_in_demo_evidence(client):
    cid = client.post("/api/cases", json={"preset_id": "hero-coverup"}).json()["case"]["case_id"]
    v = wait(client, cid)
    inv = json.dumps(v["manifest"]["operational_context"])
    assert not re.search(r"https?://(?!10\.20\.)", inv)  # only addresses inside the synthetic 10.20.0.0/16 world
