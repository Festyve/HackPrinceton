"""The matrix and batch scripts keep what their docstrings promise (the findings of an independent review).

Offline and fast: no key, no network, no model call. A run that needs a model is never started here: where a
script's loop is driven, the runner is replaced by one that raises, and the worker-lab cases use scripted
workers and the deterministic checks. The saved results under benchmarks/ are only read; every tampered copy is
made in memory or in a temporary directory.
"""

from __future__ import annotations

import copy
import importlib.util
import json
import shutil
import subprocess
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from alibi.agents import gateway
from alibi.config import RunCaps, load_settings
from alibi.episode import artifact_hashes, bundle_hash
from alibi.orchestrator import Orchestrator
from alibi.sim.scenario import simulate

ROOT = Path(__file__).resolve().parents[1]
RUN = "20261114t212052z"  # the one committed run of the matrix


def _script(name: str):
    spec = importlib.util.spec_from_file_location(f"m21_{name}", ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def batch():
    return _script("run_daniel_live_batch")


@pytest.fixture(scope="module")
def matrix():
    return _script("run_lab_matrix")


@pytest.fixture(scope="module")
def reader():
    return _script("read_lab_matrix")


# ---------------------------------------------------------------- run_daniel_live_batch: the status of a row

# What the runner writes: `stop_reason = f"stopped because {exc}"`, then `f"Incomplete run: {stop_reason}."`,
# around the gateway's ModelRefused("the model declined this request (safety classifier category: ...)").
REFUSAL = "Incomplete run: stopped because the model declined this request (safety classifier category: not given)."
CAPPED = "Incomplete run: stopped by the budget gateway: call cap reached (4 model calls per investigation)."


@pytest.mark.parametrize("stop, status", [
    (None, "completed"),
    (REFUSAL, "refused"),
    ("Incomplete run: stopped because the model DECLINED this request.", "refused"),
    ("Incomplete run: the model's Refusal ended the run.", "refused"),
    (CAPPED, "capped"),
    ("Incomplete run: stopped at the turn limit before requesting review.", "unresolved"),
    ("Incomplete run: the investigator ended without requesting review.", "unresolved"),
])
def test_a_stop_reason_becomes_the_status_of_its_row(batch, stop, status):
    assert batch._status_for(stop) == status


class _Refuser(BaseChatModel):
    """TEST DOUBLE: answers with the provider's refusal stop reason. Nothing is sent anywhere."""

    @property
    def _llm_type(self) -> str:
        return "refuser-test-double"

    def _generate(self, messages, stop=None, run_manager=None, **kw) -> ChatResult:
        return ChatResult(generations=[ChatGeneration(message=AIMessage(
            content="", usage_metadata={"input_tokens": 500, "output_tokens": 5, "total_tokens": 505},
            response_metadata={"stop_reason": "refusal", "model_name": "m"}))])


def test_the_gateways_own_refusal_is_a_refused_row_not_an_unresolved_one(batch):
    with pytest.raises(gateway.ModelRefused) as err:
        gateway.wrap(_Refuser(), gateway.BudgetLedger(None, RunCaps(), kind="local"), "lead-investigator").invoke("look")
    stop = f"Incomplete run: stopped because {err.value}."  # the runner's wording around the gateway's message
    assert stop == REFUSAL
    assert "refus" not in stop.lower() and "budget gateway" not in stop  # all that the old mapping looked for
    assert batch._status_for(stop) == "refused"


# ---------------------------------------------------------------- run_daniel_live_batch: evidence, before any run


def _blocked():
    return SimpleNamespace(live_block_reason=lambda: "blocked for this test", lead_model=None)


def test_the_preflight_measures_the_evidence_of_every_cell_of_the_batch(batch):
    protocol = batch.read_protocol()
    measured = batch.check_evidence(protocol)
    assert set(measured) == {cell["case_id"] for cell in protocol["batches"][batch.BATCH]["cells"]}
    for case_id, found in measured.items():
        case = protocol["cases"][case_id]
        assert found["raw_bundle_sha256"] == case["raw_bundle_sha256"]
        assert found["capture_manifest_sha256"] == case["capture_manifest_sha256"]
        assert found["evidence_origin"] in ("SIM", "DOCKER", "HYBRID")


@pytest.mark.parametrize("field, message", [("raw_bundle_sha256", "the evidence of"),
                                            ("capture_manifest_sha256", "the capture manifest of")])
def test_a_mismatch_on_the_last_cell_stops_the_preflight_not_the_run_after_earlier_cells(batch, field, message):
    protocol = batch.read_protocol()
    protocol["versions"]["live_sources"] = {}  # this checkout is not the pinned runtime; the pins are not the subject
    # with the evidence intact, the first thing that stops this preflight is the blocked runtime
    with pytest.raises(ValueError, match="live inference is blocked"):
        batch.preflight(protocol, _blocked())
    last = protocol["batches"][batch.BATCH]["cells"][-1]["case_id"]
    protocol["cases"][last][field] = "0" * 64
    with pytest.raises(ValueError, match=f"{message} {last} differs from the protocol"):
        batch.preflight(protocol, _blocked())


def test_a_cell_that_cannot_be_imported_or_run_is_a_failed_row_and_the_next_cell_is_still_attempted(
        batch, tmp_path, monkeypatch):
    """The loop of the batch, with nothing that could reach a model: the runner is replaced by one that raises."""
    protocol = batch.read_protocol()
    cells = protocol["batches"][batch.BATCH]["cells"]
    model = protocol["conditions"][cells[0]["condition"]]["model"]
    settings = replace(load_settings({}, dotenv=False), lead_model=model)
    monkeypatch.setattr(batch, "load_settings", lambda: settings)
    monkeypatch.setattr(batch, "preflight", lambda protocol, settings: {"evidence": batch.check_evidence(protocol)})
    monkeypatch.setattr(batch.gateway, "global_spend_for",
                        lambda settings: SimpleNamespace(snapshot=lambda: {"spent_usd": 0.0}))
    real_import, imports, runners = batch.import_bundle, [], []

    def importing(source, paths):
        imports.append(source.name)
        if len(imports) == 1:
            raise OSError("the fixture could not be read")
        manifest = real_import(source, paths)
        if len(imports) == 2:  # as if the fixture had been changed after the preflight
            return manifest.model_copy(update={"raw_bundle_sha256": "0" * 64})
        return manifest

    def no_runner(*args, **kwargs):
        runners.append(args)
        raise RuntimeError("no model is available in this test")

    monkeypatch.setattr(batch, "import_bundle", importing)
    monkeypatch.setattr(batch, "get_runner", no_runner)
    output = tmp_path / "live"
    summary = batch.run_batch(output)  # also validated by Daniel's validator before it returns

    rows = [json.loads(line) for line in (output / "outcomes.jsonl").read_text().splitlines()]
    assert [(r["case_id"], r["condition"]) for r in rows] == [(c["case_id"], c["condition"]) for c in cells]
    assert summary["runs"] == len(cells) == len(json.loads((output / "results.json").read_text())["runs"])
    assert {r["status"] for r in rows} == {"failed"}
    assert rows[0]["stop_reason"] == "OSError: the fixture could not be read"
    assert rows[1]["stop_reason"] == "ValueError: the evidence changed after the preflight"
    assert all(r["stop_reason"] == "RuntimeError: no model is available in this test" for r in rows[2:])
    assert len(imports) == len(cells) and len(runners) == len(cells) - 2  # the two bad cells never reached a runner
    for row in rows:
        case = protocol["cases"][row["case_id"]]
        assert (row["evidence_sha256"], row["manifest_sha256"]) == (case["raw_bundle_sha256"], case["capture_manifest_sha256"])
        assert row["used"]["calls"] == 0 and row["used"]["cost_usd"] == 0 and row["report"] is None and row["score"] is None


# ---------------------------------------------------------------- run_lab_matrix: the two guards


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


@pytest.fixture()
def repo(tmp_path, monkeypatch):
    """A git repository of its own in a temporary directory. The real repository is not touched."""
    for name in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_PREFIX", "GIT_COMMON_DIR"):
        monkeypatch.delenv(name, raising=False)  # set when tests run from a git hook; they would point at the real one
    root = tmp_path / "repo"
    (root / "suite").mkdir(parents=True)
    (tmp_path / "no-hooks").mkdir()
    _git(root, "init", "-q")
    for key, value in (("user.name", "test"), ("user.email", "test@example.invalid"), ("commit.gpgsign", "false"),
                       ("core.hooksPath", str(tmp_path / "no-hooks"))):
        _git(root, "config", key, value)
    (root / "code.py").write_text("x = 1\n")
    _git(root, "add", "code.py")
    _git(root, "commit", "-q", "-m", "code")
    return root


def test_a_protocol_that_was_not_committed_does_not_pass(matrix, repo):
    protocol = repo / "suite" / "protocol.json"
    protocol.write_text('{"cells": []}\n')
    assert matrix._clean(repo)  # the earlier guard alone: it does not see an untracked file
    assert not matrix._protocol_committed(protocol, repo)  # untracked
    _git(repo, "add", "suite/protocol.json")
    assert not matrix._protocol_committed(protocol, repo)  # staged, never committed
    _git(repo, "commit", "-q", "-m", "protocol")
    assert matrix._protocol_committed(protocol, repo)
    protocol.write_text('{"cells": [1]}\n')
    assert not matrix._protocol_committed(protocol, repo)  # changed after the commit
    _git(repo, "checkout", "--", "suite/protocol.json")
    assert matrix._protocol_committed(protocol, repo)
    protocol.unlink()
    assert not matrix._protocol_committed(protocol, repo)  # deleted


def test_the_protocol_guard_fails_closed_where_git_knows_nothing_of_the_file(matrix, tmp_path, monkeypatch):
    for name in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE"):
        monkeypatch.delenv(name, raising=False)
    (tmp_path / "protocol.json").write_text("{}\n")
    assert not matrix._protocol_committed(tmp_path / "protocol.json", tmp_path)


def test_a_second_run_needs_again_and_is_never_a_replacement(matrix, tmp_path):
    suite = tmp_path / "suite"
    suite.mkdir()
    (suite / "protocol.json").write_text("{}\n")
    (suite / "README.md").write_text("not a run\n")
    assert matrix._runs(suite) == []
    assert matrix._run_refusal(suite, RUN, again=False) is None  # the first run
    (suite / RUN).mkdir()
    assert matrix._runs(suite) == [RUN]
    refusal = matrix._run_refusal(suite, "20261115t000000z", again=False)
    assert refusal and "--again" in refusal and RUN in refusal and "not a replacement" in refusal
    assert matrix._run_refusal(suite, "20261115t000000z", again=True) is None  # a separate run in a new directory
    for again in (False, True):  # the same directory is never written into, asked for or not
        assert "already exists" in matrix._run_refusal(suite, RUN, again=again)


@pytest.fixture()
def suite_copy(matrix, tmp_path, monkeypatch):
    """`main` pointed at a copy of the suite. Settings are never loaded: a refusal comes first, or the test fails."""
    suite = tmp_path / "suite"
    shutil.copytree(matrix.SUITE, suite)
    monkeypatch.setattr(matrix, "SUITE", suite)
    monkeypatch.setattr(matrix, "PROTOCOL", suite / "protocol.json")
    monkeypatch.setattr(matrix, "_clean", lambda: True)
    monkeypatch.setattr(matrix, "_protocol_committed", lambda: True)

    def never():
        raise AssertionError("the run was not refused before the settings were loaded")

    monkeypatch.setattr(matrix, "load_settings", never)
    return suite


def test_run_refuses_while_a_run_exists_and_an_uncommitted_protocol_refuses_too(matrix, suite_copy, monkeypatch, capsys):
    before = sorted(p.name for p in suite_copy.iterdir())
    assert matrix.main(["--check"]) == 0 and "--run refuses without --again" in capsys.readouterr().out
    assert matrix.main(["--run"]) == 2
    assert "--again" in capsys.readouterr().err
    monkeypatch.setattr(matrix, "_protocol_committed", lambda: False)
    assert matrix.main(["--run", "--again"]) == 2
    assert "not tracked by git" in capsys.readouterr().err
    assert sorted(p.name for p in suite_copy.iterdir()) == before  # nothing was made


def test_again_passes_the_second_run_guard_and_makes_no_directory_while_live_cells_are_blocked(
        matrix, suite_copy, monkeypatch, capsys):
    monkeypatch.setattr(matrix, "load_settings", _blocked)
    assert matrix.main(["--run", "--again"]) == 2
    assert "live cells are blocked" in capsys.readouterr().err
    assert matrix._runs(suite_copy) == [RUN]


# ---------------------------------------------------------------- run_lab_matrix: what a cell saves

CELL = {"id": "T1-incident", "group": "presets", "variant": "incident", "seed": 11, "preset": "balanced",
        "ordinary_work": "scripted", "runner": "deterministic", "worst_case_usd": 0.0}
NAMES = {kind: f"T1-incident.{kind}.json" for kind in ("report", "trace", "scenario")}


def _lab(tmp_path: Path, pace_s: float = 0.0) -> Orchestrator:
    settings = replace(load_settings({}, dotenv=False), runs_dir=tmp_path / "runs", sealed_dir=tmp_path / "sealed")
    return Orchestrator(settings, pace_s=pace_s)


def _case(orch: Orchestrator, token: str) -> str:
    return orch.create_lab_case(variant="incident", seed=CELL["seed"], preset="balanced", ordinary_work="scripted",
                                runner_id="deterministic", client_token=token).case_id


def test_a_locked_cell_saves_its_report_trace_and_scenario_and_the_scenario_only_after_the_reveal(
        matrix, tmp_path, monkeypatch):
    orch, out_dir = _lab(tmp_path), tmp_path / "run"
    out_dir.mkdir()
    case_id = _case(orch, "m21-locked")
    orch.start_investigation(case_id)
    state = matrix._wait(orch, case_id)
    assert state == "awaiting_review"
    real, states = matrix.load_episode_manifest, []

    def sealed(paths):
        states.append(orch.record(case_id).state)
        return real(paths)

    monkeypatch.setattr(matrix, "load_episode_manifest", sealed)
    result = matrix._result(orch, case_id, CELL, state, out_dir)

    assert states == ["scored"]  # the sealed scenario was read once, after the lock and the reveal
    assert result["terminal_status"] == "complete" and "attachment_errors" not in result
    assert result["attachments"] == NAMES
    assert sorted(p.name for p in out_dir.iterdir()) == sorted(NAMES.values())
    report = json.loads((out_dir / NAMES["report"]).read_text())
    assert report["locked"] is True and report["report_sha256"] == result["report_sha256"]
    trace = json.loads((out_dir / NAMES["trace"]).read_text())
    assert trace["case_id"] == case_id and trace["spans"]
    # the saved scenario is enough to regenerate the evidence of the run, byte for byte
    scenario = json.loads((out_dir / NAMES["scenario"]).read_text())
    assert scenario["lab"]["tape"] and scenario["seed"] == CELL["seed"]
    assert bundle_hash(artifact_hashes(simulate(scenario).artifacts)) == result["raw_bundle_sha256"]


def test_a_cell_that_passes_the_wait_is_asked_to_stop_and_never_saves_the_sealed_scenario(matrix, tmp_path):
    orch, out_dir = _lab(tmp_path, pace_s=0.3), tmp_path / "run"  # paced, so that it is still running when asked
    out_dir.mkdir()
    case_id = _case(orch, "m21-slow")
    orch.start_investigation(case_id)
    assert orch.record(case_id).state == "investigating"
    cancel = matrix._stop(orch, case_id, wait_s=20)
    assert cancel["requested"] is True and cancel["stopped"] is True and cancel["state_after"] == "cancelled"
    result = matrix._result(orch, case_id, CELL, "investigating", out_dir)  # the state when the wait ended
    assert result["terminal_status"] == "did_not_finish_in_time" and result["scored"] is None
    assert result["attachments"] == {"report": None, "trace": NAMES["trace"], "scenario": None}
    assert [p.name for p in out_dir.iterdir()] == [NAMES["trace"]]  # no report was locked, so the truth stays sealed


def test_a_run_that_does_not_stop_is_recorded_as_not_stopped(matrix):
    class Deaf:
        """TEST DOUBLE for the orchestrator: a run that never notices the request."""
        asked = 0

        def cancel(self, case_id):
            self.asked += 1

        def record(self, case_id):
            return SimpleNamespace(state="investigating")

    orch = Deaf()
    cancel = matrix._stop(orch, "case-deaf", wait_s=0.3)
    assert orch.asked == 1
    assert cancel == {"requested": True, "stopped": False, "state_after": "investigating", "waited_up_to_s": 0.3}


def test_an_attachment_that_cannot_be_written_is_stated_and_does_not_lose_the_result(matrix, tmp_path):
    out = {"cell": "T1-incident", "attachments": {"report": None, "trace": None, "scenario": None}}

    def broken():
        raise RuntimeError("no trace")

    matrix._attach(out, tmp_path, "trace", broken)
    matrix._attach(out, tmp_path, "report", lambda: {"locked": True})
    assert out["attachments"] == {"report": NAMES["report"], "trace": None, "scenario": None}
    assert out["attachment_errors"] == {"trace": "RuntimeError: no trace"}
    assert [p.name for p in tmp_path.iterdir()] == [NAMES["report"]]


# ---------------------------------------------------------------- read_lab_matrix: the checks


@pytest.fixture()
def committed(reader):
    proto, results, run_dir = reader.load(None)
    assert run_dir.name == RUN
    return proto, copy.deepcopy(results), run_dir


def _fresh_and_derived(proto):
    cells = proto["cells"]
    fresh = next(c["id"] for c in cells if not c.get("derive_from"))
    derived = next(c for c in cells if c.get("comparison") in ("investigator_budget", "workflow"))
    return fresh, derived["id"], derived["derive_from"]


def test_the_committed_run_passes_every_check(reader, committed):
    proto, results, run_dir = committed
    assert len(results) == len(proto["cells"]) == 18
    assert reader.check(proto, results) == []
    assert reader.check(proto, results, run_dir) == []


def test_an_ordinary_request_that_was_not_chosen_is_a_problem(reader, committed):
    proto, results, _ = committed
    fresh, derived, _parent = _fresh_and_derived(proto)
    results[fresh]["ordinary_requests"] = {"chosen": 7, "refused": 1}
    problems = reader.check(proto, results)
    assert len(problems) == 1 and problems[0].startswith(f"{fresh}: not every ordinary request") and "1 refused" in problems[0]
    results[fresh]["ordinary_requests"] = {"invalid_output": 2, "stopped_by_budget": 6}
    assert "2 invalid_output, 6 stopped_by_budget" in reader.check(proto, results)[0]
    results[fresh]["ordinary_requests"] = None  # not recorded is not the same as all chosen
    assert reader.check(proto, results) == [f"{fresh}: the statuses of the workers' ordinary requests were not recorded"]
    # only a fresh execution does ordinary work; a derived cell replays its parent's
    results[fresh]["ordinary_requests"] = {"chosen": 8}
    results[derived]["ordinary_requests"] = {"chosen": 7, "refused": 1}
    assert reader.check(proto, results) == []


def test_a_missing_cell_is_a_problem(reader, committed):
    proto, results, _ = committed
    fresh, _derived, _parent = _fresh_and_derived(proto)
    del results[fresh]
    assert f"{fresh}: declared but has no result" in reader.check(proto, results)
    results["Z9-undeclared"] = {"terminal_status": "complete"}
    assert "Z9-undeclared: has a result but was not declared" in reader.check(proto, results)


def test_a_derived_cell_whose_bundle_hash_differs_from_its_parents_is_a_problem(reader, committed):
    proto, results, _ = committed
    _fresh, derived, parent = _fresh_and_derived(proto)
    assert results[derived]["raw_bundle_sha256"] == results[parent]["raw_bundle_sha256"]
    results[derived]["raw_bundle_sha256"] = "0" * 64
    assert reader.check(proto, results) == [
        f"{derived}: declared as the same evidence as {parent} but the bundle hash differs"]


def test_a_saved_comparison_other_than_the_declared_one_is_a_problem(reader, committed):
    proto, results, _ = committed
    _fresh, derived, _parent = _fresh_and_derived(proto)
    declared = next(c["comparison"] for c in proto["cells"] if c["id"] == derived)
    results[derived]["lineage"]["comparison"] = "rogue_permissions"
    assert reader.check(proto, results) == [
        f"{derived}: the saved lineage names the comparison rogue_permissions, the protocol declared {declared}"]
    del results[derived]["lineage"]
    assert reader.check(proto, results) == [
        f"{derived}: the saved lineage names the comparison None, the protocol declared {declared}"]


def test_two_fresh_executions_with_one_bundle_hash_and_a_result_without_a_status_are_problems(reader, committed):
    proto, results, _ = committed
    first, second = [c["id"] for c in proto["cells"] if not c.get("derive_from")][:2]
    results[second]["raw_bundle_sha256"] = results[first]["raw_bundle_sha256"]
    assert f"{second}: a separate execution with the same bundle hash as {first}" in reader.check(proto, results)
    del results[first]["terminal_status"]
    assert f"{first}: the result has no terminal status" in reader.check(proto, results)


# ---------------------------------------------------------------- read_lab_matrix: the report and repeated runs


def _section(text: str, title: str) -> str:
    return text.split(f"## {title}\n", 1)[1].split("\n## ", 1)[0]


def test_the_report_of_the_committed_run_is_written_and_says_what_the_checks_cells_really_changed(reader, tmp_path, capsys):
    target = tmp_path / "matrix.md"
    assert reader.main(["--write", str(target)]) == 0
    assert reader.main(["--strict", "--write", str(target)]) == 0  # one run: --strict has nothing to object to
    assert "PROBLEM" not in capsys.readouterr().err
    text = target.read_text()
    assert "has been run" not in text and "The reader's checks passed" in text
    sentence = ("the saved lineage names only the investigator's request allowance as what differs from the parent "
                "cell, but what actually differs is the investigator: the deterministic checks ran instead of a live model")
    assert text.count(sentence) == 1
    section = _section(text, "The deterministic checks alone, no model")
    assert f"For each cell below, {sentence}" in section and section.count("| O-") == 6


def test_the_checks_cells_are_the_ones_whose_saved_lineage_leaves_the_investigator_out(reader, committed):
    proto, results, _ = committed
    found = reader.lineage_omits_investigator(proto, results)
    assert found == [c["id"] for c in proto["cells"] if c["group"] == "deterministic_checks"] and len(found) == 6
    for cid in found:  # what the saved files say, which is left as it is
        assert set(results[cid]["lineage"]["changed"]) == {"investigator_requests"}
        assert results[cid]["labels"]["inference"] == "NO_MODEL_BASELINE"


@pytest.fixture()
def two_runs(reader, tmp_path, monkeypatch):
    suite = tmp_path / "suite"
    shutil.copytree(reader.SUITE, suite)
    shutil.copytree(suite / RUN, suite / "20261115t090000z")
    monkeypatch.setattr(reader, "SUITE", suite)
    return suite


def test_a_repeated_run_is_said_at_the_top_and_fails_only_a_strict_read(reader, two_runs, tmp_path, capsys):
    target = tmp_path / "matrix.md"
    assert reader.main(["--write", str(target)]) == 0
    assert "2 run directories" in capsys.readouterr().err
    lines = target.read_text().splitlines()
    assert lines[0].startswith("# ") and lines[2].startswith("**This matrix has been run 2 times.**")
    assert f"`{RUN}`, `20261115t090000z`" in lines[2] and "Only `20261115t090000z` is rendered here" in lines[2]
    assert lines[4].startswith("Run `20261115t090000z`")
    assert reader.main(["--strict", "--write", str(target)]) == 1
    assert "--strict makes that a failure" in capsys.readouterr().err
    # the earlier run can still be read by name, and the note still names both
    assert reader.main([RUN, "--write", str(target)]) == 0
    text = target.read_text()
    assert f"Only `{RUN}` is rendered here" in text and f"\nRun `{RUN}`" in text
    with pytest.raises(SystemExit, match="no run directory named nothing-here"):
        reader.load("nothing-here")


def test_attachments_are_not_results_and_each_must_be_named_and_present(reader, two_runs):
    run_dir = two_runs / RUN
    proto, results, loaded = reader.load(RUN)
    cell = next(iter(results))
    (run_dir / f"{cell}.trace.json").write_text("{}\n")
    proto, results, loaded = reader.load(RUN)
    assert len(results) == len(proto["cells"])  # the attachment was not read as a result
    assert reader.check(proto, results, loaded) == [f"{cell}.trace.json: an attachment file that no result names"]
    saved = json.loads((run_dir / f"{cell}.json").read_text())
    saved["attachments"] = {"report": f"{cell}.report.json", "trace": f"{cell}.trace.json", "scenario": None}
    (run_dir / f"{cell}.json").write_text(json.dumps(saved, indent=1) + "\n")
    proto, results, loaded = reader.load(RUN)
    assert reader.check(proto, results, loaded) == [f"{cell}.report.json: named as an attachment by a result but missing"]
    (run_dir / f"{cell}.report.json").write_text("{}\n")
    assert reader.check(proto, results, loaded) == []
