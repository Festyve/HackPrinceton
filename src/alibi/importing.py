"""Import evidence that was captured outside the simulator (docs/next-run/CONTRACTS.md, "Capture handoff").

Input is a directory holding the original raw files and one neutral manifest, `capture.json`. The
importer checks the manifest against the files (relative paths that stay inside the directory, sizes,
SHA-256), copies the bytes VERBATIM into a frozen episode, and normalizes them with the same parsers
as any other bundle. Lines the parsers do not understand stay in the evidence as unparsed records;
nothing is rewritten to look like simulator output.

An imported bundle has no sealed answer key. It is UNSCORED: it can be investigated, questioned,
reviewed, locked, exported and used for source-removal experiments, but there is nothing to unseal
and no score. A manifest is rejected if it carries anything that looks like ground truth, so labels
cannot ride into investigator-visible evidence. Each source keeps the origin its capture states
(SIM, DOCKER or HYBRID); this module never upgrades one.

This is the generic path for files in formats the normalizer already reads. A capture that needs
new parsing supplies it with its own importer and reuses the checks and the unscored case mode here.
"""

from __future__ import annotations

import json
import re
import shutil
import stat
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from alibi.contracts import CoverageGap, EvidenceManifest, EvidenceOrigin, SourceInfo
from alibi.episode import EpisodeError, EpisodePaths, _make_readonly, _write_json, bundle_hash, sha256_file
from alibi.evidence.normalize import NORMALIZER_VERSION, classify, normalize_bundle
from alibi.evidence.store import build_store

CAPTURE_FORMAT = "alibi-capture/1"
MANIFEST_NAME = "capture.json"
MAX_ARTIFACTS = 200
MAX_ARTIFACT_BYTES = 25 * 1024 * 1024
MAX_TOTAL_BYTES = 200 * 1024 * 1024
INDEPENDENT_KINDS = {"collector", "flow", "badge", "reference"}


class ImportError_(EpisodeError):
    """The capture cannot be imported as given. Nothing was created."""


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")  # an unknown key (for example a truth label) is an error, not ignored


class CaptureArtifact(_Strict):
    path: str  # relative to the capture directory, e.g. "workstation/var/log/auth.log"
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    size_bytes: int = Field(ge=0)
    origin: EvidenceOrigin = "DOCKER"
    tamper_exposure: Literal["host_local_writable", "independent_witness"] | None = None
    coverage_start: datetime | None = None
    coverage_end: datetime | None = None
    known_gaps: list[CoverageGap] = Field(default_factory=list)
    coverage_note: str = ""
    forwarded_to_collector: bool = False


class CaptureTool(_Strict):
    name: str
    version: str = ""
    image_digests: dict[str, str] = Field(default_factory=dict)


class CaptureManifest(_Strict):
    """The neutral description of a capture. It has no field for what "really" happened."""

    format: Literal["alibi-capture/1"]
    capture_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{2,63}$")
    captured_by: CaptureTool
    capture_start: datetime
    capture_end: datetime
    evidence_origin: EvidenceOrigin
    artifacts: list[CaptureArtifact] = Field(min_length=1, max_length=MAX_ARTIFACTS)
    operational_context: dict[str, Any] = Field(default_factory=dict)
    notes: list[str] = Field(default_factory=list)


# Keys are compared after lowering them and dropping everything but letters and digits, so "groundTruth",
# "Answer_Key" and "ground-truth" are the same key. A key is refused when it IS one of the exact names or
# CONTAINS one of the parts.
_TRUTH_KEYS = {"seed", "steps", "plan", "effects"}
_TRUTH_KEY_PARTS = ("truth", "answer", "label", "scenario", "variant", "adversar", "attacker", "malicious", "culprit",
                    "verdict", "isincident", "casekind", "operatortrue")
# Free text cannot be understood here. Only wording that announces an answer is refused.
_TRUTH_TEXT = re.compile(r"ground[\s_-]*truth|answer[\s_-]*key|\banswer\s*:|\bthe\s+answer\s+is\b|"
                         r"\b(scenario|variant|verdict|culprit)\s*[:=]", re.I)
_SAFE_PATH = re.compile(r"[A-Za-z0-9._@+=,~ -]+(/[A-Za-z0-9._@+=,~ -]+)*")


def _key(name: Any) -> str:
    return re.sub(r"[^a-z0-9]", "", str(name).lower())


def _no_truth(obj: Any, where: str = "operational_context") -> None:
    """Refuse a context that carries ground truth. Public evidence and private labels are kept apart.

    This is a filter for honest mistakes, not a proof: it refuses keys that are named like an answer and text
    that announces one. What a capture author writes in ordinary prose remains their responsibility.
    """
    if isinstance(obj, dict):
        for k, v in obj.items():
            norm = _key(k)
            if norm in _TRUTH_KEYS or any(part in norm for part in _TRUTH_KEY_PARTS):
                raise ImportError_(f"{where} contains the key {k!r}, which looks like ground truth. Keep labels out of "
                                   "the capture manifest; an imported bundle is unscored")
            _no_truth(v, f"{where}.{k}")
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            _no_truth(v, f"{where}[{i}]")
    elif isinstance(obj, str) and _TRUTH_TEXT.search(obj):
        raise ImportError_(f"{where} contains text that looks like ground truth ({_TRUTH_TEXT.search(obj).group(0)!r}). "
                           "Keep labels out of the capture manifest; an imported bundle is unscored")


def load_capture(src_dir: Path) -> tuple[CaptureManifest, dict[str, Path]]:
    """Validate a capture directory. Returns the manifest and artifact path -> real file. Reads only."""
    src_dir = Path(src_dir)
    mf = src_dir / MANIFEST_NAME
    if not src_dir.is_dir() or not mf.is_file():
        raise ImportError_(f"{src_dir} is not a capture directory: {MANIFEST_NAME} is missing")
    try:
        manifest = CaptureManifest.model_validate_json(mf.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        raise ImportError_(f"{MANIFEST_NAME} is not a valid {CAPTURE_FORMAT} manifest: {str(exc)[:400]}") from exc
    if "tip" in manifest.operational_context:
        # the tip is the first thing an investigating model reads, so a capture does not get to write it
        raise ImportError_("operational_context.tip is not accepted: every imported case starts from the same neutral "
                           "tip, so a capture cannot tell the investigator what to find")
    _no_truth(manifest.operational_context)
    _no_truth(manifest.notes, "notes")
    if manifest.capture_end < manifest.capture_start:
        raise ImportError_("capture_end is before capture_start")
    root = src_dir.resolve()
    files: dict[str, Path] = {}
    total = 0
    for art in manifest.artifacts:
        rel = Path(art.path)
        if rel.is_absolute() or ".." in rel.parts or art.path != rel.as_posix() or art.path in files:
            raise ImportError_(f"artifact path {art.path!r} must be a unique relative path inside the capture directory")
        if not _SAFE_PATH.fullmatch(art.path):
            # the name is printed in reports and exports: no line breaks, control characters or markup in it
            raise ImportError_(f"artifact path {art.path!r} may contain only letters, digits, spaces and . _ @ + = , ~ - "
                               "between slashes")
        f = src_dir / rel
        if f.is_symlink() or not f.is_file() or root not in f.resolve().parents:
            raise ImportError_(f"artifact {art.path!r} is missing, is a link, or leaves the capture directory")
        size = f.stat().st_size
        if size != art.size_bytes:
            raise ImportError_(f"artifact {art.path!r} is {size} bytes; the manifest says {art.size_bytes}")
        if size > MAX_ARTIFACT_BYTES:
            raise ImportError_(f"artifact {art.path!r} is larger than {MAX_ARTIFACT_BYTES} bytes")
        total += size
        if sha256_file(f) != art.sha256:
            raise ImportError_(f"artifact {art.path!r} does not match its SHA-256 in the manifest")
        if classify(art.path)[0] == "unknown":
            raise ImportError_(f"artifact {art.path!r} is not at a location the normalizer recognizes "
                               "(<host role>/<path>, e.g. workstation/var/log/auth.log)")
        files[art.path] = f
    if total > MAX_TOTAL_BYTES:
        raise ImportError_(f"the capture is larger than {MAX_TOTAL_BYTES} bytes in total")
    origins = {a.origin for a in manifest.artifacts}
    if manifest.evidence_origin != "HYBRID" and origins != {manifest.evidence_origin}:
        raise ImportError_(f"evidence_origin is {manifest.evidence_origin} but artifacts state {sorted(origins)}; "
                           "a mixed capture must say HYBRID")
    return manifest, files


def import_bundle(src_dir: Path, paths: EpisodePaths) -> EvidenceManifest:
    """Freeze a validated capture as an unscored episode. The source directory is only read."""
    if paths.root.exists() or paths.sealed.exists():
        raise EpisodeError(f"episode {paths.episode_id} already exists; evidence is immutable, choose a new id")
    capture, files = load_capture(src_dir)
    hashes: dict[str, str] = {}
    try:
        for rel, f in files.items():
            dest = paths.raw / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(f, dest)  # the original bytes, unchanged
            hashes[rel] = sha256_file(dest)
        raw_hash = bundle_hash(hashes)
        _make_readonly(paths.raw)
        try:
            events, errors = normalize_bundle(paths.raw, list(hashes))
        except UnicodeDecodeError as exc:
            raise ImportError_(f"an artifact is not UTF-8 text: {exc}") from exc
        build_store(paths.db, events)
        db_hash = sha256_file(paths.db)
        paths.db.chmod(stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH)
        by_art: dict[str, list[datetime]] = {}
        unparsed: dict[str, int] = {}
        for ev in events:
            if ev.action == "unparsed":
                unparsed[ev.artifact_ref.artifact] = unparsed.get(ev.artifact_ref.artifact, 0) + 1
            else:
                by_art.setdefault(ev.artifact_ref.artifact, []).append(ev.ts)
        sources: list[SourceInfo] = []
        for art in capture.artifacts:
            kind, role, logical, _gen = classify(art.path)
            tss = by_art.get(art.path, [])
            stated = art.coverage_start is not None and art.coverage_end is not None
            note = art.coverage_note
            if unparsed.get(art.path):
                note = (note + " " if note else "") + f"{unparsed[art.path]} line(s) could not be parsed and are kept as unparsed records."
            sources.append(SourceInfo(
                artifact=art.path, host=role, source={"history": "shell_history"}.get(kind, kind), logical_file=logical,
                sha256=hashes[art.path], size_bytes=art.size_bytes,
                line_count=(paths.raw / art.path).read_text(encoding="utf-8").count("\n"), origin=art.origin,
                tamper_exposure=art.tamper_exposure or ("independent_witness" if kind in INDEPENDENT_KINDS else "host_local_writable"),
                coverage_start=art.coverage_start if stated else (min(tss) if tss else None),
                coverage_end=art.coverage_end if stated else (max(tss) if tss else None),
                coverage_declared=stated, known_gaps=art.known_gaps, coverage_note=note,
                forwarded_to_collector=art.forwarded_to_collector))
        context = dict(capture.operational_context)
        context["tip"] = "Review this evidence; establish what it supports."
        context["capture"] = {"capture_id": capture.capture_id, "captured_by": capture.captured_by.model_dump(),
                              "ground_truth": "none: this evidence was imported and has no answer key"}
        manifest = EvidenceManifest(
            bundle_id=f"bndl-{raw_hash[:16]}", normalizer_version=NORMALIZER_VERSION, evidence_origin=capture.evidence_origin,
            capture_start=capture.capture_start, capture_end=capture.capture_end,
            capture_complete=all(s.coverage_declared and not s.known_gaps for s in sources),
            capture_notes=list(capture.notes) + ["Imported evidence. No scenario and no answer key are known to this system."],
            sources=sources, raw_bundle_sha256=raw_hash, derived_db_sha256=db_hash, event_count=len(events),
            normalization_errors=errors, operational_context=context)
        _write_json(paths.manifest, manifest.model_dump(mode="json"))
        paths.case.mkdir(parents=True, exist_ok=True)
        return manifest
    except Exception:
        from alibi.episode import _make_writable

        _make_writable(paths.root)  # never leave a half-imported bundle behind
        shutil.rmtree(paths.root, ignore_errors=True)
        raise


SIMULATED_FRAMING = "a frozen evidence bundle from a small clinic network"
IMPORTED_FRAMING = ("a frozen evidence bundle that was imported from outside this system. Nothing is known about where "
                    "it came from beyond its manifest: assume nothing about the organization, its people or its data")


def is_imported(manifest: EvidenceManifest) -> bool:
    """True for evidence that came through this importer: it has no scenario and no answer key."""
    return "capture" in manifest.operational_context


def neutral_framing(prompt: str) -> str:
    """A model prompt for imported evidence: the simulated clinic is not mentioned, the rest is word for word."""
    if SIMULATED_FRAMING not in prompt:
        raise ValueError("this prompt does not carry the simulated-case framing, so it cannot be made neutral")
    return prompt.replace(SIMULATED_FRAMING, IMPORTED_FRAMING)


def framing_for(manifest: EvidenceManifest, prompt: str) -> str:
    """The prompt as written for a simulated clinic case, or reworded for imported evidence or a worker-lab case."""
    if is_imported(manifest):
        return neutral_framing(prompt)
    if "lab" in manifest.operational_context:
        from alibi.lab.engine import LAB_FRAMING

        if SIMULATED_FRAMING not in prompt:
            raise ValueError("this prompt does not carry the simulated-case framing, so it cannot be reworded")
        return prompt.replace(SIMULATED_FRAMING, LAB_FRAMING)
    return prompt


def write_capture_manifest(src_dir: Path, capture_id: str, tool: str, origin: EvidenceOrigin, capture_start: datetime,
                           capture_end: datetime, *, operational_context: dict[str, Any] | None = None,
                           notes: list[str] | None = None, per_artifact: dict[str, dict[str, Any]] | None = None) -> Path:
    """Write capture.json for the files already in src_dir (sizes and hashes are computed from the files).

    A convenience for capture tooling and tests. `per_artifact` adds stated fields (origin, coverage, gaps) by path.
    """
    src_dir = Path(src_dir)
    arts = []
    for f in sorted(p for p in src_dir.rglob("*") if p.is_file() and p.name != MANIFEST_NAME):
        rel = f.relative_to(src_dir).as_posix()
        arts.append({"path": rel, "sha256": sha256_file(f), "size_bytes": f.stat().st_size, "origin": origin,
                     **((per_artifact or {}).get(rel) or {})})
    doc = {"format": CAPTURE_FORMAT, "capture_id": capture_id, "captured_by": {"name": tool},
           "capture_start": capture_start.isoformat(), "capture_end": capture_end.isoformat(), "evidence_origin": origin,
           "artifacts": arts, "operational_context": operational_context or {}, "notes": notes or []}
    out = src_dir / MANIFEST_NAME
    out.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    return out
