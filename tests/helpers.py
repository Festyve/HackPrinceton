"""Hand-auditable mini bundles for unit tests of checks, verifier and scorer."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from alibi.contracts import CoverageGap, EvidenceManifest, SourceInfo
from alibi.episode import INDEPENDENT_KINDS, classify
from alibi.evidence.normalize import normalize_artifact
from alibi.evidence.store import EvidenceStore, build_store

WS, COL = "ws-nurse-01", "logcol-01"


def ts(hms: str) -> str:
    return f"2026-11-10T{hms}+00:00"


def dt(hms: str) -> datetime:
    return datetime.fromisoformat(ts(hms))


def auth_open(hms: str, user: str, n: int, tty: str = "tty1") -> str:
    return f"{ts(hms)} {WS} login[900]: pam_unix(login:session): session opened for user {user} on {tty} (session {n})"


def auth_close(hms: str, user: str, n: int) -> str:
    return f"{ts(hms)} {WS} login[900]: pam_unix(login:session): session closed for user {user} (session {n})"


def fwd(hms: str, seq: int, line: str, file: str = "/var/log/auth.log", origin: str = WS) -> str:
    return f"{ts(hms)} {COL} fwd: origin={origin} file={file} seq={seq} msg={line}"


def hb(hms: str, seq: int, origin: str = WS) -> str:
    return f"{ts(hms)} {COL} hb: origin={origin} seq={seq} status=ok"


def flow(start: str, end: str, src: str, dst: str, dport: int, out: int, inn: int = 400) -> str:
    return ('{"start":"%s","end":"%s","src":"%s","sport":40001,"dst":"%s","dport":%d,"proto":"tcp",'
            '"bytes_out":%d,"bytes_in":%d}' % (ts(start), ts(end), src, dst, dport, out, inn))


def context(**over) -> dict:
    ctx = {
        "network_inventory": [
            {"name": WS, "ip": "10.20.1.21", "role": "workstation"},
            {"name": "rec-srv-01", "ip": "10.20.0.10", "role": "records"},
            {"name": "stor-nas-01", "ip": "10.20.0.45", "role": "backup-nas"},
            {"name": "vpn-gw-01", "ip": "10.20.0.250", "role": "vpn-gw"},
        ],
        "accounts": [{"account": "ann", "role": "nurse", "badge": "B-1"}, {"account": "bob", "role": "nurse", "badge": "B-2"}],
        "logging_policy": {
            "heartbeat_interval_s": 10,
            "forwarded_files": [{"host": "workstation", "file": "/var/log/auth.log"}],
            "rotation": [{"host": "workstation", "file": "/var/log/auth.log", "keep": 1}],
        },
        "transfer_policy": {"bulk_threshold_bytes": 5_000_000,
                            "approved_bulk_destinations": [{"ip": "10.20.0.45", "name": "stor-nas-01", "purpose": "backup"}]},
        "remote_access_policy": {"allowed": True, "via": "vpn-gw-01 (10.20.0.250)"},
    }
    ctx.update(over)
    return ctx


def mini_case(tmp_path: Path, artifacts: dict[str, list[str]], ctx: dict | None = None,
              start: str = "06:00:00", end: str = "16:00:00",
              declared: dict[str, tuple[str, str]] | None = None,
              gaps: dict[str, list[tuple[str, str, str]]] | None = None) -> tuple[EvidenceStore, EvidenceManifest]:
    """A hand-written bundle. The manifest lists exactly the artifacts given, as a real one does.

    declared: artifact -> (start, end) the capture STATES it covered; gaps: artifact -> stated gaps.
    """
    events, sources = [], []
    for artifact, lines in artifacts.items():
        evs, errs = normalize_artifact(artifact, "".join(line + "\n" for line in lines))
        assert not errs, errs
        events.extend(evs)
        kind, role, logical, _gen = classify(artifact)
        tss = [e.ts for e in evs if e.action != "unparsed"]
        stated = (declared or {}).get(artifact)
        sources.append(SourceInfo(
            artifact=artifact, host=role, source={"history": "shell_history"}.get(kind, kind), logical_file=logical,
            sha256="0" * 64, size_bytes=sum(len(x) + 1 for x in lines), line_count=len(lines),
            tamper_exposure="independent_witness" if kind in INDEPENDENT_KINDS else "host_local_writable",
            coverage_start=dt(stated[0]) if stated else (min(tss) if tss else None),
            coverage_end=dt(stated[1]) if stated else (max(tss) if tss else None),
            coverage_declared=bool(stated),
            known_gaps=[CoverageGap(start=dt(a), end=dt(b), reason=why) for a, b, why in (gaps or {}).get(artifact, [])],
        ))
    db = tmp_path / f"mini-{len(list(tmp_path.glob('mini-*')))}.duckdb"
    build_store(db, events)
    manifest = EvidenceManifest(bundle_id="bndl-mini", normalizer_version="test", capture_start=dt(start),
                                capture_end=dt(end), sources=sources, raw_bundle_sha256="0" * 64,
                                operational_context=ctx or context())
    return EvidenceStore(db), manifest


def badge(hms: str, badge_id: str, event: str, seq: int = 1) -> str:
    return '{"ts":"%s","badge":"%s","event":"%s","reader":"door-staff-1","seq":%d}' % (ts(hms), badge_id, event, seq)


def without_sources(paths, tmp_path: Path, drop: set[str]) -> tuple[EvidenceStore, EvidenceManifest]:
    """A view of a frozen episode with whole source kinds left out of BOTH the manifest and the store.

    The frozen bundle is only read. Used to check that an absent witness reads as "not assessable"
    rather than as a clean result or an allegation.
    """
    from alibi.episode import load_manifest
    from alibi.evidence.normalize import normalize_bundle

    manifest = load_manifest(paths)
    keep = [s for s in manifest.sources if s.source not in drop]
    events, _ = normalize_bundle(paths.raw, [s.artifact for s in keep])
    db = tmp_path / f"subset-{len(list(tmp_path.glob('subset-*')))}.duckdb"
    build_store(db, events)
    return EvidenceStore(db), manifest.model_copy(update={"sources": keep, "event_count": len(events)})
