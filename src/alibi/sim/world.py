"""SimBackend world model: a deterministic synthetic clinic network.

The world keeps *state* (local log files, the collector's copies, shell histories,
file metadata, flow records, badge records). Actions are scheduled on a logical
clock and executed in time order, so an anti-forensic step at time t can only touch
what existed locally at t, and can never touch the independent witnesses
(collector, tap, badge reader).

Same simulator version + scenario specification + seed => byte-identical artifacts.
No wall-clock time, no network, no real personal data.
"""

from __future__ import annotations

import hashlib
import heapq
import json
import random
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from alibi.contracts import iso

SIMULATOR_VERSION = "1.1.0"  # 1.1.0: sensor/reference streams, forwarder control, metadata times; first-run output unchanged

HOSTNAMES = {
    "workstation": "ws-nurse-01",
    "records": "rec-srv-01",
    "iot-hub": "iot-hub-01",
    "collector": "logcol-01",
    "tap": "net-tap-01",
}
IPS = {
    "workstation": "10.20.1.21",
    "records": "10.20.0.10",
    "iot-hub": "10.20.0.30",
    "collector": "10.20.0.40",
    "backup-nas": "10.20.0.45",
    "lab-gw": "10.20.8.20",
    "vpn-gw": "10.20.0.250",
    "admin-laptop": "10.20.1.90",
    "printer": "10.20.1.60",
    "gateway": "10.20.0.1",
    "update-mirror": "10.20.9.10",
}
EXTRA_NAMES = {
    "backup-nas": "stor-nas-01",
    "lab-gw": "lab-gw-01",
    "vpn-gw": "vpn-gw-01",
    "admin-laptop": "adm-lt-01",
    "printer": "prn-01",
    "gateway": "gw-01",
    "update-mirror": "upd-mirror-01",
}
BULK_THRESHOLD_BYTES = 5_000_000
HEARTBEAT_INTERVAL_S = 10

AUTH_LOG = "/var/log/auth.log"
SYSLOG = "/var/log/syslog"
APP_LOG = "/var/log/records-app/access.log"
MQTT_LOG = "/var/log/mosquitto/mosquitto.log"


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@dataclass
class LogLine:
    ts: datetime
    text: str
    uid: int


@dataclass
class LogFile:
    role: str
    path: str
    forwarded: bool
    keep: int  # rotated generations kept on the host (0 = archived off-host)
    current: list[LogLine] = field(default_factory=list)
    rotated: list[LogLine] | None = None  # the single kept generation (.1)
    rotations: list[datetime] = field(default_factory=list)


@dataclass
class Session:
    session_id: str
    number: int
    role: str
    account: str
    origin: str  # "console" | "remote"
    tty: str | None
    src_ip: str | None
    opened: datetime
    closed: datetime | None = None
    proc: str = "login"
    pid: int = 0


@dataclass
class TraceRef:
    """A line the simulator wrote, remembered so truth can point at it."""

    artifact_logical: str
    raw: str
    ts: datetime
    role: str = "direct"


class World:
    """Mutable world state plus an event queue on a logical clock."""

    def __init__(self, rng: random.Random, capture_start: datetime, capture_end: datetime):
        self.rng = rng
        self.capture_start = capture_start
        self.capture_end = capture_end
        self._queue: list[tuple[datetime, int, Callable[[datetime], None]]] = []
        self._order = 0
        self._uid = 0
        self.logs: dict[tuple[str, str], LogFile] = {}
        self.collector_lines: list[tuple[datetime, int, str]] = []
        self._fwd_seq: dict[tuple[str, str], int] = {}
        self.forwarder_down: dict[str, list[tuple[datetime, datetime]]] = {}
        self.histories: dict[tuple[str, str], list[tuple[datetime, str]]] = {}
        self.files: dict[str, dict[str, dict[str, Any]]] = {"workstation": {}, "records": {}}
        self._inode = {"workstation": 262_200 + rng.randrange(0, 4000), "records": 524_400 + rng.randrange(0, 4000)}
        self.flows: list[dict[str, Any]] = []
        self.badge_events: list[dict[str, Any]] = []
        self._badge_seq = 100 + rng.randrange(0, 800)
        self._mqtt_mid = 4000 + rng.randrange(0, 3000)
        self.sessions: dict[str, Session] = {}
        self._session_no = {"workstation": 20 + rng.randrange(0, 60), "records": 300 + rng.randrange(0, 200)}
        self._pid = 2000 + rng.randrange(0, 500)
        self._sport = 40_000 + rng.randrange(0, 5000)
        self.console_busy_until: datetime | None = None
        self.now: datetime = capture_start
        # Cold-chain sensor state. Empty in every other case family, and then nothing is rendered for it.
        self.sensor_local: dict[str, list[dict[str, Any]]] = {}  # the hub's own (host-local, writable) store
        self.sensor_ref: dict[str, list[dict[str, Any]]] = {}  # an independent reference logger

        self.add_log("workstation", AUTH_LOG, forwarded=True, keep=1)
        self.add_log("workstation", SYSLOG, forwarded=True, keep=1)
        self.add_log("records", AUTH_LOG, forwarded=True, keep=1)
        self.add_log("records", SYSLOG, forwarded=True, keep=1)
        self.add_log("records", APP_LOG, forwarded=True, keep=0)
        self.add_log("iot-hub", MQTT_LOG, forwarded=True, keep=1)

    # ------------------------------------------------------------------ scheduling
    def schedule(self, ts: datetime, fn: Callable[[datetime], None]) -> None:
        self._order += 1
        heapq.heappush(self._queue, (ts, self._order, fn))

    def run(self) -> None:
        while self._queue:
            ts, _, fn = heapq.heappop(self._queue)
            self.now = ts
            fn(ts)

    # ------------------------------------------------------------------ primitives
    def next_pid(self) -> int:
        self._pid += self.rng.randrange(1, 9)
        return self._pid

    def next_sport(self) -> int:
        self._sport += self.rng.randrange(1, 13)
        if self._sport > 60_000:
            self._sport = 40_000
        return self._sport

    def add_log(self, role: str, path: str, *, forwarded: bool, keep: int) -> LogFile:
        lf = LogFile(role=role, path=path, forwarded=forwarded, keep=keep)
        self.logs[(role, path)] = lf
        self._fwd_seq[(role, path)] = 0
        return lf

    def forwarder_up(self, role: str, ts: datetime) -> bool:
        return not any(a <= ts < b for a, b in self.forwarder_down.get(role, []))

    def log(self, role: str, path: str, ts: datetime, proc: str, msg: str) -> TraceRef:
        """Append a line to a host-local log and (if up) ship a copy to the collector."""
        lf = self.logs[(role, path)]
        text = f"{iso(ts)} {HOSTNAMES[role]} {proc}: {msg}"
        self._uid += 1
        lf.current.append(LogLine(ts=ts, text=text, uid=self._uid))
        if lf.forwarded and self.forwarder_up(role, ts):
            self._fwd_seq[(role, path)] += 1
            seq = self._fwd_seq[(role, path)]
            recv = ts + timedelta(seconds=self.rng.choice([0, 0, 1, 1, 2]))
            ctext = f"origin={HOSTNAMES[role]} file={path} seq={seq} msg={text}"
            self._order += 1
            self.collector_lines.append((recv, self._order, ctext))
            if self.rng.random() < 0.01:  # occasional retransmit: same seq delivered twice
                self._order += 1
                self.collector_lines.append((recv + timedelta(seconds=self.rng.randrange(1, 4)), self._order, ctext))
        return TraceRef(artifact_logical=f"{role}:{path}", raw=text, ts=ts)

    def collector_copy_of(self, role: str, path: str, text: str) -> TraceRef | None:
        """Find the collector's (first) copy of a local line, if it was ever shipped."""
        needle = f" msg={text}"
        prefix = f"origin={HOSTNAMES[role]} file={path} "
        for recv, _, ctext in self.collector_lines:
            if ctext.startswith(prefix) and ctext.endswith(needle):
                return TraceRef(
                    artifact_logical="collector",
                    raw=f"{iso(recv)} {HOSTNAMES['collector']} fwd: {ctext}",
                    ts=recv,
                    role="collector_copy",
                )
        return None

    def rotate(self, role: str, path: str, ts: datetime) -> int:
        """Rotate a local log. Returns the number of lines that left the host."""
        lf = self.logs[(role, path)]
        gone = 0
        if lf.keep >= 1:
            if lf.rotated is not None:
                gone = len(lf.rotated)  # previous .1 is discarded
            lf.rotated = lf.current
        else:
            gone = len(lf.current)  # archived off-host, not part of a local capture
        lf.current = []
        lf.rotations.append(ts)
        return gone

    def history(self, role: str, account: str, ts: datetime, cmd: str) -> TraceRef:
        self.histories.setdefault((role, account), []).append((ts, cmd))
        return TraceRef(artifact_logical=f"{role}:history:{account}", raw=cmd, ts=ts)

    def write_file(self, role: str, path: str, size: int, owner: str, ts: datetime) -> TraceRef:
        prev = self.files[role].get(path)
        if prev is None:
            self._inode[role] += self.rng.randrange(1, 40)
            inode = self._inode[role]
        else:
            inode = prev["inode"]
        self.files[role][path] = {"size": size, "mtime": ts, "ctime": ts, "inode": inode, "owner": owner}
        return TraceRef(artifact_logical=f"{role}:fs_stat", raw=self._stat_row(path, self.files[role][path]), ts=ts)

    @staticmethod
    def _stat_row(path: str, st: dict[str, Any]) -> str:
        return f"{path}\t{st['size']}\t{iso(st['mtime'])}\t{iso(st['ctime'])}\t{st['inode']}\t{st['owner']}"

    # ------------------------------------------------------------------ phase-two primitives
    def set_file_times(self, role: str, path: str, mtime: datetime, ctime: datetime) -> TraceRef:
        """Change a file's recorded modification time. The inode change time moves to `ctime`, as it
        does on a real filesystem: metadata edits cannot back-date ctime."""
        st = self.files[role][path]
        st["mtime"], st["ctime"] = mtime, ctime
        return TraceRef(artifact_logical=f"{role}:fs_stat", raw=self._stat_row(path, st), ts=mtime)

    def restore_file(self, role: str, path: str, size: int, owner: str, mtime: datetime, ctime: datetime) -> TraceRef:
        """A file restored with its original modification time preserved (as an archive restore does)."""
        prev = self.files[role].get(path)
        if prev is None:
            self._inode[role] += self.rng.randrange(1, 40)
            inode = self._inode[role]
        else:
            inode = prev["inode"]
        self.files[role][path] = {"size": size, "mtime": mtime, "ctime": ctime, "inode": inode, "owner": owner}
        return TraceRef(artifact_logical=f"{role}:fs_stat", raw=self._stat_row(path, self.files[role][path]), ts=mtime)

    def clear_history(self, role: str, account: str, since: datetime | None) -> list[tuple[datetime, str]]:
        """Remove shell-history entries (all, or those at/after `since`). Returns what was removed."""
        cmds = self.histories.get((role, account), [])
        gone = [c for c in cmds if since is None or c[0] >= since]
        self.histories[(role, account)] = [c for c in cmds if not (since is None or c[0] >= since)]
        return gone

    def stop_forwarding(self, role: str, start: datetime, end: datetime) -> None:
        """Log forwarding from `role` is down in [start, end). Lines written then never reach the collector."""
        self.forwarder_down.setdefault(role, []).append((start, end))

    def last_flow_ref(self) -> TraceRef:
        rec = self.flows[-1]
        return TraceRef(artifact_logical="tap:flows", raw=self._flow_line(rec), ts=datetime.fromisoformat(rec["start"]))

    def sensor_reading(self, sensor: str, ts: datetime, temp_c: float, state: str = "ok") -> dict[str, Any]:
        """One reading in the hub's own store (the stream a dashboard shows). Host-local and writable."""
        rows = self.sensor_local.setdefault(sensor, [])
        rec = {"ts": iso(ts), "sensor": sensor, "seq": (rows[-1]["seq"] + 1 if rows else 1),
               "temp_c": round(temp_c, 1), "state": state}
        rows.append(rec)
        return rec

    def reference_reading(self, logger: str, sensor: str, ts: datetime, temp_c: float) -> dict[str, Any]:
        """One reading of the independent reference logger (its own probe, clock and storage)."""
        rows = self.sensor_ref.setdefault(logger, [])
        rec = {"ts": iso(ts), "logger": logger, "monitors": sensor, "seq": (rows[-1]["seq"] + 1 if rows else 1),
               "temp_c": round(temp_c, 1)}
        rows.append(rec)
        return rec

    @staticmethod
    def sensor_line(rec: dict[str, Any]) -> str:
        return json.dumps(rec, separators=(",", ":"))

    @staticmethod
    def reference_line(rec: dict[str, Any]) -> str:
        return f"{rec['ts']},{rec['logger']},{rec['monitors']},{rec['seq']},{rec['temp_c']:.1f}"

    def flow(self, start: datetime, src: str, dst: str, dport: int, bytes_out: int, bytes_in: int,
             duration_s: float | None = None) -> TraceRef:
        if duration_s is None:
            duration_s = max(1.0, (bytes_out + bytes_in) / 2_500_000) + self.rng.randrange(0, 2)
        rec = {
            "start": iso(start),
            "end": iso(start + timedelta(seconds=int(round(duration_s)))),
            "src": src,
            "sport": self.next_sport(),
            "dst": dst,
            "dport": dport,
            "proto": "tcp",
            "bytes_out": int(bytes_out),
            "bytes_in": int(bytes_in),
        }
        self._order += 1
        rec["_order"] = self._order
        self.flows.append(rec)
        return TraceRef(artifact_logical="tap:flows", raw=self._flow_line(rec), ts=start)

    @staticmethod
    def _flow_line(rec: dict[str, Any]) -> str:
        pub = {k: v for k, v in rec.items() if not k.startswith("_")}
        return json.dumps(pub, separators=(",", ":"))

    def badge(self, ts: datetime, badge_id: str, event: str, reader: str = "door-staff-1") -> TraceRef:
        self._badge_seq += 1
        rec = {"ts": iso(ts), "reader": reader, "badge": badge_id, "event": event, "seq": self._badge_seq}
        self.badge_events.append(rec)
        self._mqtt_mid += 1
        payload = len(json.dumps(rec, separators=(",", ":")))
        self.log("iot-hub", MQTT_LOG, ts, "mosquitto[410]",
                 f"Received PUBLISH from badge-{reader} (q1, m{self._mqtt_mid}, 'clinic/door/{reader}/badge', {payload} bytes)")
        return TraceRef(artifact_logical="iot-hub:badge", raw=json.dumps(rec, separators=(",", ":")), ts=ts)

    # ------------------------------------------------------------------ sessions
    def open_session(self, role: str, account: str, ts: datetime, *, origin: str,
                     tty: str | None = None, src_ip: str | None = None) -> tuple[Session, TraceRef]:
        self._session_no[role] += 1
        n = self._session_no[role]
        pid = self.next_pid()
        if origin == "console":
            proc = "login"
            msg = f"pam_unix(login:session): session opened for user {account} on {tty} (session {n})"
        else:
            proc = "sshd"
            msg = (f"pam_unix(sshd:session): session opened for user {account} from {src_ip} "
                   f"port {self.next_sport()} (session {n})")
        sess = Session(session_id=f"{role}#{n}", number=n, role=role, account=account, origin=origin,
                       tty=tty, src_ip=src_ip, opened=ts, proc=proc, pid=pid)
        self.sessions[sess.session_id] = sess
        ref = self.log(role, AUTH_LOG, ts, f"{proc}[{pid}]", msg)
        if origin == "remote" and src_ip:
            self.flow(ts, src_ip, IPS[role], 22, 3000 + self.rng.randrange(0, 9000), 9000 + self.rng.randrange(0, 40000),
                      duration_s=30 + self.rng.randrange(0, 200))
        return sess, ref

    def close_session(self, sess: Session, ts: datetime) -> TraceRef:
        sess.closed = ts
        svc = "login" if sess.origin == "console" else "sshd"
        return self.log(sess.role, AUTH_LOG, ts, f"{sess.proc}[{sess.pid}]",
                        f"pam_unix({svc}:session): session closed for user {sess.account} (session {sess.number})")

    # ------------------------------------------------------------------ rendering
    def heartbeat_lines(self) -> list[tuple[datetime, int, str]]:
        out: list[tuple[datetime, int, str]] = []
        for idx, role in enumerate(("workstation", "records", "iot-hub")):
            seq = 2000 + idx * 37
            t = self.capture_start + timedelta(seconds=2 + idx * 3)
            was_down = False
            while t <= self.capture_end:
                if self.forwarder_up(role, t):
                    if was_down:
                        seq = 0  # agent restarted: sender-side counter starts again
                        was_down = False
                    seq += 1
                    out.append((t, idx, f"origin={HOSTNAMES[role]} seq={seq} status=ok"))
                else:
                    was_down = True
                t += timedelta(seconds=HEARTBEAT_INTERVAL_S)
        return out

    def render_artifacts(self) -> dict[str, str]:
        """Serialize the captured state to artifact files (path -> text). Deterministic."""
        arts: dict[str, str] = {}
        for (role, path), lf in sorted(self.logs.items()):
            base = f"{role}{path}"
            arts[base] = "".join(line.text + "\n" for line in lf.current)
            if lf.keep >= 1 and lf.rotated is not None:
                arts[base + ".1"] = "".join(line.text + "\n" for line in lf.rotated)
        for (role, account), cmds in sorted(self.histories.items()):
            body = "".join(f"#{int(ts.timestamp())}\n{cmd}\n" for ts, cmd in cmds)
            arts[f"{role}/home/{account}/.bash_history"] = body
        for role in ("workstation", "records"):
            rows = ["path\tsize\tmtime\tctime\tinode\towner"]
            rows += [self._stat_row(p, st) for p, st in sorted(self.files[role].items())]
            arts[f"{role}/fs_stat.tsv"] = "\n".join(rows) + "\n"
        arts["iot-hub/badge/door-staff-1.jsonl"] = "".join(
            json.dumps(rec, separators=(",", ":")) + "\n" for rec in self.badge_events
        )
        merged: list[tuple[datetime, int, int, str]] = []
        for recv, order, ctext in self.collector_lines:
            merged.append((recv, 0, order, f"{iso(recv)} {HOSTNAMES['collector']} fwd: {ctext}"))
        for ts, idx, text in self.heartbeat_lines():
            merged.append((ts, 1, idx, f"{iso(ts)} {HOSTNAMES['collector']} hb: {text}"))
        merged.sort(key=lambda r: (r[0], r[1], r[2]))
        arts["collector/var/log/collected/collected.log"] = "".join(r[3] + "\n" for r in merged)
        flows = sorted(self.flows, key=lambda r: (r["start"], r["_order"]))
        arts["tap/flows.jsonl"] = "".join(self._flow_line(r) + "\n" for r in flows)
        # cold-chain sources exist only in that case family; nothing is added to any other bundle
        for sensor, rows in sorted(self.sensor_local.items()):
            arts[f"iot-hub/sensors/{sensor}.jsonl"] = "".join(self.sensor_line(r) + "\n" for r in rows)
        for logger, rows in sorted(self.sensor_ref.items()):
            arts[f"reference/coldchain/{logger}.csv"] = "ts,logger,monitors,seq,temp_c\n" + "".join(
                self.reference_line(r) + "\n" for r in rows)
        return arts


def logical_clock_base() -> datetime:
    """Fixed logical date for every simulated shift (not wall-clock time)."""
    return datetime(2026, 11, 10, 0, 0, 0, tzinfo=timezone.utc)
