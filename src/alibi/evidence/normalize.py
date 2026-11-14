"""Normalize frozen raw artifacts into Events (PLAN 7.1 step 6).

Parsing never mutates raw files and never "fixes" timestamps. Lines that do not
parse stay visible as `unparsed` events and are reported as normalization errors.
Evidence text is data: nothing here evaluates, executes or follows it.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from alibi.contracts import ArtifactRef, Event

NORMALIZER_VERSION = "1.1.0"  # 1.1.0: sensor and reference sources

HOSTNAME_ROLES = {
    "ws-nurse-01": "workstation",
    "rec-srv-01": "records",
    "iot-hub-01": "iot-hub",
    "logcol-01": "collector",
    "net-tap-01": "tap",
}

_LINE = re.compile(r"^(?P<ts>\S+) (?P<hn>\S+) (?P<proc>[A-Za-z0-9_.-]+)(?:\[(?P<pid>\d+)\])?: (?P<msg>.*)$")
_SESS = re.compile(r"\(session (?P<n>\d+)\)")
_OPEN_CONSOLE = re.compile(r"session opened for user (?P<u>\S+) on (?P<tty>\S+) \(session \d+\)")
_OPEN_REMOTE = re.compile(r"session opened for user (?P<u>\S+) from (?P<ip>\S+) port (?P<port>\d+) \(session \d+\)")
_CLOSE = re.compile(r"session closed for user (?P<u>\S+) \(session \d+\)")
_AUTHFAIL = re.compile(r"authentication failure; user=(?P<u>\S+) tty=(?P<tty>\S+)")
_SUDO = re.compile(r"^(?P<u>\S+) : TTY=(?P<tty>\S+) ; COMMAND=(?P<cmd>.*?)(?: \(session \d+\))?$")
_CRON = re.compile(r"^\((?P<u>[^)]+)\) CMD \((?P<cmd>.*)\)$")
_ROT_KEEP = re.compile(r"^rotated (?P<file>\S+) -> (?P<target>\S+) \((?P<note>[^)]*)\)$")
_ROT_ARCH = re.compile(r"^rotated (?P<file>\S+) -> archived off-host (?P<target>\S+) \((?P<note>[^)]*)\)$")
_KV = re.compile(r"(\w+)=(\S+)")
_MQTT = re.compile(r"^Received PUBLISH from (?P<client>\S+) \(q\d, m(?P<mid>\d+), '(?P<topic>[^']+)', (?P<bytes>\d+) bytes\)$")
_COLLECT_FWD = re.compile(r"^origin=(?P<origin>\S+) file=(?P<file>\S+) seq=(?P<seq>\d+) msg=(?P<msg>.*)$")
_COLLECT_HB = re.compile(r"^origin=(?P<origin>\S+) seq=(?P<seq>\d+) status=(?P<status>\S+)$")
_ROTATED_SUFFIX = re.compile(r"\.(\d+)$")


def event_id(artifact: str, byte_offset: int, raw: str) -> str:
    """Opaque and stable for the same bundle. Encodes nothing about labels or truth."""
    h = hashlib.sha256(f"{artifact}\x00{byte_offset}\x00{raw}".encode("utf-8")).hexdigest()
    return f"ev_{h[:12]}"


def _ts(raw: str) -> datetime:
    dt = datetime.fromisoformat(raw)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def classify(artifact: str) -> tuple[str, str, str | None, int]:
    """artifact path -> (kind, host role, logical file, generation)."""
    role, _, rest = artifact.partition("/")
    rest = "/" + rest
    gen = 0
    m = _ROTATED_SUFFIX.search(rest)
    logical = rest
    if m and "/var/log/" in rest:
        gen = int(m.group(1))
        logical = rest[: m.start()]
    if logical.endswith("/auth.log"):
        return "auth", role, logical, gen
    if logical.endswith("/syslog"):
        return "syslog", role, logical, gen
    if logical.endswith("/records-app/access.log"):
        return "app", role, logical, gen
    if logical.endswith("/mosquitto/mosquitto.log"):
        return "mqtt", role, logical, gen
    if logical.endswith("/collected/collected.log"):
        return "collector", role, logical, gen
    if rest.endswith("/.bash_history"):
        return "history", role, None, 0
    if rest.endswith("/fs_stat.tsv"):
        return "fs_stat", role, None, 0
    if rest.endswith(".jsonl") and "/badge/" in rest:
        return "badge", role, None, 0
    if rest == "/flows.jsonl":
        return "flow", role, None, 0
    # --- phase two (additive): cold-chain sources
    if rest.endswith(".jsonl") and "/sensors/" in rest:
        return "sensor", role, None, 0
    if rest.endswith(".csv") and "/coldchain/" in rest:
        return "reference", role, None, 0
    return "unknown", role, None, 0


def parse_log_message(kind: str, proc: str, msg: str, role: str) -> dict[str, Any]:
    """Parse the message part of a syslog-style line into normalized fields."""
    out: dict[str, Any] = {"actor": None, "action": "log", "object": None, "attrs": {}}
    sm = _SESS.search(msg)
    if sm:
        out["attrs"]["session"] = int(sm.group("n"))
        out["attrs"]["session_id"] = f"{role}#{sm.group('n')}"
    if kind == "auth":
        if m := _OPEN_CONSOLE.search(msg):
            out.update(actor=m.group("u"), action="login", object=m.group("tty"))
            out["attrs"].update(origin="console", tty=m.group("tty"))
        elif m := _OPEN_REMOTE.search(msg):
            out.update(actor=m.group("u"), action="login", object=f"ssh:{m.group('ip')}")
            out["attrs"].update(origin="remote", src_ip=m.group("ip"), src_port=int(m.group("port")))
        elif m := _CLOSE.search(msg):
            out.update(actor=m.group("u"), action="logout")
        elif m := _AUTHFAIL.search(msg):
            out.update(actor=m.group("u"), action="auth_failure", object=m.group("tty"))
        elif proc == "sudo" and (m := _SUDO.match(msg)):
            out.update(actor=m.group("u"), action="sudo", object=m.group("cmd"))
            out["attrs"]["tty"] = m.group("tty")
        else:
            out["action"] = "auth_other"
    elif kind == "syslog":
        if proc == "CRON" and (m := _CRON.match(msg)):
            out.update(actor=m.group("u"), action="cron", object=m.group("cmd"))
        elif proc == "logrotate" and (m := _ROT_ARCH.match(msg)):
            out.update(action="log_rotate", object=m.group("file"))
            out["attrs"].update(archived_offhost=True, target=m.group("target"), note=m.group("note"), keep=0)
        elif proc == "logrotate" and (m := _ROT_KEEP.match(msg)):
            out.update(action="log_rotate", object=m.group("file"))
            out["attrs"].update(archived_offhost=False, target=m.group("target"), note=m.group("note"), keep=1,
                                discarded_previous="discarded" in m.group("note"))
        elif proc == "systemd":
            out.update(action="service", object=msg)
        else:
            out["action"] = "syslog"
    elif kind == "app":
        kv = dict(_KV.findall(msg))
        if "action" in kv:
            out.update(actor=kv.get("user"), action=kv["action"],
                       object=kv.get("record") or kv.get("dataset") or kv.get("report"))
            attrs = {"client": kv.get("client"), "status": kv.get("status")}
            if kv.get("bytes", "").isdigit():
                attrs["bytes"] = int(kv["bytes"])
            for k in ("record", "dataset", "report"):
                if k in kv:
                    attrs[k] = kv[k]
            out["attrs"].update(attrs)
        else:
            out["action"] = "app_other"
    elif kind == "mqtt":
        if m := _MQTT.match(msg):
            out.update(actor=m.group("client"), action="publish", object=m.group("topic"))
            out["attrs"].update(bytes=int(m.group("bytes")), mid=int(m.group("mid")))
        else:
            out["action"] = "mqtt_other"
    return out


_KIND_SOURCE = {"auth": "auth", "syslog": "syslog", "app": "app", "mqtt": "mqtt"}


def _iter_lines(text: str) -> Iterator[tuple[int, int, str]]:
    """Yield (1-based line number, byte offset, line without newline)."""
    offset = 0
    for i, line in enumerate(text.split("\n")):
        if line == "" and offset >= len(text.encode("utf-8")):
            break
        yield i + 1, offset, line
        offset += len(line.encode("utf-8")) + 1


def normalize_artifact(artifact: str, text: str) -> tuple[list[Event], list[str]]:
    kind, role, logical, gen = classify(artifact)
    events: list[Event] = []
    errors: list[str] = []

    def emit(line_no: int, off: int, raw: str, ts: datetime, ts_raw: str, **kw: Any) -> None:
        events.append(Event(id=event_id(artifact, off, raw), ts=ts, ts_raw=ts_raw, raw=raw,
                            artifact_ref=ArtifactRef(artifact=artifact, line=line_no, byte_offset=off), **kw))

    def unparsed(line_no: int, off: int, raw: str, why: str, source: str) -> None:
        errors.append(f"{artifact}:{line_no}: {why}")
        emit(line_no, off, raw, datetime(1970, 1, 1, tzinfo=timezone.utc), "", host=role, source=source,
             action="unparsed", attrs={"parse_error": why})

    if kind in _KIND_SOURCE:
        for n, off, raw in _iter_lines(text):
            if not raw:
                continue
            m = _LINE.match(raw)
            if not m:
                unparsed(n, off, raw, "not a syslog-style line", _KIND_SOURCE[kind])
                continue
            try:
                ts = _ts(m.group("ts"))
            except ValueError:
                unparsed(n, off, raw, "bad timestamp", _KIND_SOURCE[kind])
                continue
            f = parse_log_message(kind, m.group("proc"), m.group("msg"), role)
            f["attrs"].update(logical_file=logical, generation=gen, proc=m.group("proc"))
            emit(n, off, raw, ts, m.group("ts"), host=role, source=_KIND_SOURCE[kind], actor=f["actor"],
                 action=f["action"], object=f["object"], attrs=f["attrs"])
    elif kind == "collector":
        for n, off, raw in _iter_lines(text):
            if not raw:
                continue
            m = _LINE.match(raw)
            if not m:
                unparsed(n, off, raw, "not a collector line", "collector")
                continue
            ts = _ts(m.group("ts"))
            if m.group("proc") == "hb" and (h := _COLLECT_HB.match(m.group("msg"))):
                emit(n, off, raw, ts, m.group("ts"), host="collector", source="heartbeat", actor=h.group("origin"),
                     action="heartbeat", attrs={"origin_host": HOSTNAME_ROLES.get(h.group("origin"), h.group("origin")),
                                                "seq": int(h.group("seq")), "status": h.group("status")})
            elif m.group("proc") == "fwd" and (c := _COLLECT_FWD.match(m.group("msg"))):
                origin_role = HOSTNAME_ROLES.get(c.group("origin"), c.group("origin"))
                inner_raw = c.group("msg")
                inner_kind = classify(f"{origin_role}{c.group('file')}")[0]
                attrs: dict[str, Any] = {"origin_host": origin_role, "origin_hostname": c.group("origin"),
                                         "origin_file": c.group("file"), "seq": int(c.group("seq")),
                                         "inner_raw": inner_raw, "inner_source": _KIND_SOURCE.get(inner_kind, "unknown")}
                actor = action = obj = None
                action = "forwarded_line"
                im = _LINE.match(inner_raw)
                if im:
                    attrs["inner_ts"] = im.group("ts")
                    f = parse_log_message(inner_kind, im.group("proc"), im.group("msg"), origin_role)
                    actor, action, obj = f["actor"], f["action"], f["object"]
                    attrs.update(f["attrs"])
                emit(n, off, raw, ts, m.group("ts"), host="collector", source="collector", actor=actor,
                     action=action, object=obj, attrs=attrs)
            else:
                unparsed(n, off, raw, "unrecognized collector record", "collector")
    elif kind == "history":
        account = artifact.split("/home/", 1)[1].split("/", 1)[0]
        pending: tuple[datetime, str] | None = None
        for n, off, raw in _iter_lines(text):
            if not raw:
                continue
            if raw.startswith("#") and raw[1:].isdigit():
                pending = (datetime.fromtimestamp(int(raw[1:]), tz=timezone.utc), raw[1:])
                continue
            if pending is None:
                unparsed(n, off, raw, "history command without a timestamp line", "shell_history")
                continue
            emit(n, off, raw, pending[0], pending[1], host=role, source="shell_history", actor=account, action="exec",
                 object=raw, attrs={"cmd": raw, "argv0": raw.split(" ", 1)[0]})
            pending = None
    elif kind == "fs_stat":
        for n, off, raw in _iter_lines(text):
            if not raw or n == 1:
                continue
            parts = raw.split("\t")
            if len(parts) != 6:
                unparsed(n, off, raw, "expected 6 tab-separated fields", "fs_stat")
                continue
            path, size, mtime, ctime, inode, owner = parts
            emit(n, off, raw, _ts(mtime), mtime, host=role, source="fs_stat", actor=owner, action="file_stat", object=path,
                 attrs={"size": int(size), "mtime": mtime, "ctime": ctime, "inode": int(inode),
                        "note": "ts is mtime; ctime is inode change time, not creation time"})
    elif kind == "badge":
        for n, off, raw in _iter_lines(text):
            if not raw:
                continue
            try:
                rec = json.loads(raw)
                emit(n, off, raw, _ts(rec["ts"]), rec["ts"], host=role, source="badge", actor=rec["badge"],
                     action=f"badge_{rec['event']}", object=rec["reader"], attrs={"seq": rec["seq"]})
            except (ValueError, KeyError) as exc:
                unparsed(n, off, raw, f"bad badge record ({type(exc).__name__})", "badge")
    elif kind == "flow":
        for n, off, raw in _iter_lines(text):
            if not raw:
                continue
            try:
                rec = json.loads(raw)
                start, end = _ts(rec["start"]), _ts(rec["end"])
                emit(n, off, raw, start, rec["start"], host=role, source="flow", actor=rec["src"], action="connect",
                     object=f"{rec['dst']}:{rec['dport']}",
                     attrs={"src": rec["src"], "sport": rec["sport"], "dst": rec["dst"], "dport": rec["dport"],
                            "proto": rec["proto"], "bytes_out": rec["bytes_out"], "bytes_in": rec["bytes_in"],
                            "end": rec["end"], "duration_s": (end - start).total_seconds(),
                            "record_type": "simulated flow record (not a packet capture)"})
            except (ValueError, KeyError) as exc:
                unparsed(n, off, raw, f"bad flow record ({type(exc).__name__})", "flow")
    elif kind == "sensor":
        # the hub's own stored readings (the stream a dashboard shows)
        for n, off, raw in _iter_lines(text):
            if not raw:
                continue
            try:
                rec = json.loads(raw)
                emit(n, off, raw, _ts(rec["ts"]), rec["ts"], host=role, source="sensor", actor=rec["sensor"],
                     action="reading", object=rec["sensor"],
                     attrs={"seq": int(rec["seq"]), "temp_c": float(rec["temp_c"]), "state": rec.get("state")})
            except (ValueError, KeyError, TypeError) as exc:
                unparsed(n, off, raw, f"bad sensor reading ({type(exc).__name__})", "sensor")
    elif kind == "reference":
        # an independent reference logger: ts,logger,monitors,seq,temp_c with a header row
        for n, off, raw in _iter_lines(text):
            if not raw or n == 1:
                continue
            parts = raw.split(",")
            try:
                if len(parts) != 5:
                    raise ValueError("expected 5 fields")
                ts_raw, logger, monitors, seq, temp = parts
                emit(n, off, raw, _ts(ts_raw), ts_raw, host=role, source="reference", actor=logger, action="reading",
                     object=monitors,
                     attrs={"seq": int(seq), "temp_c": float(temp), "logger": logger,
                            "clock_note": "the logger's own clock, not network-synchronised; no offset correction applied"})
            except ValueError as exc:
                unparsed(n, off, raw, f"bad reference reading ({exc})", "reference")
    else:
        errors.append(f"{artifact}: unsupported artifact type; not normalized")
    return events, errors


def normalize_bundle(raw_dir: Path, artifacts: list[str]) -> tuple[list[Event], list[str]]:
    events: list[Event] = []
    errors: list[str] = []
    for artifact in sorted(artifacts):
        text = (raw_dir / artifact).read_text(encoding="utf-8")
        evs, errs = normalize_artifact(artifact, text)
        events.extend(evs)
        errors.extend(errs)
    seen: dict[str, str] = {}
    for ev in events:
        if ev.id in seen:
            errors.append(f"duplicate event id {ev.id} in {ev.artifact_ref.artifact} and {seen[ev.id]}")
        seen[ev.id] = ev.artifact_ref.artifact
    return events, errors
