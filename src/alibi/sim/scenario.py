"""Scenario specifications and the scripted background/adversary generators.

A ScenarioSpec is the complete, saved input of an episode: world parameters, the
variant-specific benign activity, and the *executed* adversary plan (scripted here,
or supplied by a bounded planning model). Re-running `simulate(spec)` reproduces
byte-identical raw evidence.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from alibi.contracts import iso
from alibi.sim import steps as S
from alibi.sim.world import (
    APP_LOG,
    AUTH_LOG,
    BULK_THRESHOLD_BYTES,
    EXTRA_NAMES,
    HEARTBEAT_INTERVAL_S,
    HOSTNAMES,
    IPS,
    MQTT_LOG,
    SIMULATOR_VERSION,
    SYSLOG,
    World,
    logical_clock_base,
)

SCENARIO_VERSION = "1.0.0"

CARD_INSIDE_JOB = "inside-job"
CARDS: dict[str, dict[str, Any]] = {
    CARD_INSIDE_JOB: {
        "id": CARD_INSIDE_JOB,
        "title": "Inside job",
        "audience_setup": (
            "Someone uses another staff member's account at the shared nurse station to "
            "copy the synthetic patient database out of the clinic network."
        ),
        # The tip never says whether the case is malicious; benign controls get the same text.
        "tip": "Review records access and transfers during this shift; establish what the evidence supports.",
        "difficulties": ["L1", "L2"],
    }
}

INCIDENT_VARIANTS = ("incident_plain", "incident_coverup")
BENIGN_VARIANTS = ("benign_rotation", "benign_approved_transfer", "benign_remote_login", "benign_collection_gap")
VARIANTS = INCIDENT_VARIANTS + BENIGN_VARIANTS

NURSE_POOL = ["jpark", "mreyes", "aokafor", "lnguyen", "sdubois", "rhaddad", "kcole", "tmori"]
ADMIN_POOL = ["adm-tkim", "adm-vrao", "adm-bsato"]
FRONT_DESK = ["fd-alvarez", "fd-moss"]
FRONT_DESK_IPS = ["10.20.1.31", "10.20.1.32"]
STAGING_NAMES = ["rx-7f3.db", "cache-0a91.bin", "upd-4c2e.pkg", "tmp-b77d.dat", "sess-91ac.db", "idx-3e08.bin"]


def _m(minutes: float) -> timedelta:
    return timedelta(seconds=int(minutes * 60))


def build_spec(seed: int, variant: str, card_id: str = CARD_INSIDE_JOB) -> dict[str, Any]:
    """Derive a complete scenario specification from (seed, variant). Pure and deterministic."""
    if variant not in VARIANTS:
        raise ValueError(f"unknown variant {variant!r}; choose from {VARIANTS}")
    if card_id not in CARDS:
        raise ValueError(f"unknown crime card {card_id!r}")
    rw = random.Random(f"alibi-world:{SCENARIO_VERSION}:{seed}")
    nurse_a, nurse_b = rw.sample(NURSE_POOL, 2)
    admin = rw.choice(ADMIN_POOL)
    badge_nums = rw.sample(range(1100, 6999), 5)
    badges = {
        nurse_a: f"B-{badge_nums[0]}",
        nurse_b: f"B-{badge_nums[1]}",
        admin: f"B-{badge_nums[2]}",
        "facilities-1": f"B-{badge_nums[3]}",
        "pharmacy-1": f"B-{badge_nums[4]}",
    }
    dmz_ips = [f"10.20.9.{n}" for n in sorted(rw.sample(range(12, 99), 4))]
    dataset_sizes = {
        "patients_full": rw.randrange(16_000_000, 24_000_000),
        "immunization_registry": rw.randrange(8_000_000, 13_000_000),
    }
    t0 = logical_clock_base() + timedelta(hours=7) + _m(rw.randrange(-10, 11))
    t_rot = t0 + timedelta(hours=2) + _m(rw.randrange(-10, 11))
    t_backup = t0 + timedelta(hours=5) + _m(rw.randrange(-15, 16))

    rv = random.Random(f"alibi-variant:{SCENARIO_VERSION}:{seed}:{variant}")
    spec: dict[str, Any] = {
        "scenario_version": SCENARIO_VERSION,
        "simulator_version": SIMULATOR_VERSION,
        "seed": seed,
        "card_id": card_id,
        "variant": variant,
        "case_kind": "incident" if variant in INCIDENT_VARIANTS else "benign",
        "difficulty": {"incident_plain": "L1", "incident_coverup": "L2"}.get(variant, "none"),
        "accounts": {"nurse_a": nurse_a, "nurse_b": nurse_b, "admin": admin},
        "badges": badges,
        "dmz_ips": dmz_ips,
        "dataset_sizes": dataset_sizes,
        "t0": iso(t0),
        "capture_start": iso(t0 - _m(45)),
        "capture_end": iso(t0 + timedelta(hours=8) + _m(15)),
        "t_rot": iso(t_rot),
        "t_backup": iso(t_backup),
        "crime": None,
        "plan": [],
        "plan_source": "scripted_scenario",
        "benign": {},
    }

    if variant in INCIDENT_VARIANTS:
        framed = rv.choice([nurse_a, nurse_b])
        other = nurse_b if framed == nurse_a else nurse_a
        operator = rv.choice([f"person:{other}", f"person:{admin}"])
        start = t0 + timedelta(seconds=rv.randrange(3 * 3600, int(6.5 * 3600)))
        if abs((start - t_backup).total_seconds()) < 15 * 60:
            start += _m(27)
        sink = rv.choice(dmz_ips)
        level = spec["difficulty"]
        spec["crime"] = {
            "start": iso(start),
            "framed_account": framed,
            "operator_person": operator,
            "owner_badged_out": rv.random() < 0.5,
            "sink_ip": sink,
        }
        spec["plan"] = scripted_plan(rv, level, framed, sink)
    elif variant == "benign_rotation":
        spec["benign"] = {"forced_rotation_at": iso(t0 + timedelta(hours=5, minutes=30) + _m(rv.randrange(-20, 21)))}
    elif variant == "benign_approved_transfer":
        spec["benign"] = {
            "actor": rv.choice([nurse_a, nurse_b]),
            "start": iso(t0 + timedelta(seconds=rv.randrange(int(3.2 * 3600), int(6.2 * 3600)))),
            "dst_name": f"imm-registry-{rv.randrange(100, 999)}.db",
        }
    elif variant == "benign_remote_login":
        spec["benign"] = {
            "actor": rv.choice([nurse_a, nurse_b]),
            "start": iso(t0 + timedelta(seconds=rv.randrange(int(3.2 * 3600), int(6.0 * 3600)))),
            "duration_s": rv.randrange(700, 1100),
        }
    elif variant == "benign_collection_gap":
        spec["benign"] = {
            "start": iso(t0 + timedelta(seconds=rv.randrange(int(2.8 * 3600), int(6.4 * 3600)))),
            "duration_s": rv.randrange(180, 400),
            "cause": rv.choice(["agent_restart", "transport_loss"]),
        }
    return spec


def scripted_plan(rv: random.Random, level: str, account: str, sink_ip: str) -> list[dict[str, Any]]:
    """A hand-authored adversary plan template with seeded parameters.

    This is a SCRIPTED SCENARIO: no model chose these steps.
    """
    dst_dir = rv.choice(["/var/tmp/.pkg-cache", "/tmp/.font-unix", "/home/{account}/Downloads"])
    dst_name = rv.choice(STAGING_NAMES)
    path = S.staging_path(dst_dir, dst_name, account)
    plan: list[dict[str, Any]] = [
        {"step": "login_as", "params": {"account": account}, "delay_s": 20},
        {"step": "stage_copy", "params": {"src": "patients_full", "dst_dir": dst_dir, "dst_name": dst_name},
         "delay_s": rv.randrange(45, 140)},
        {"step": "exfil_http", "params": {"path": path, "dst": sink_ip}, "delay_s": rv.randrange(60, 200)},
    ]
    if level == "L2":
        if rv.random() < 0.5:
            # An attempt against the independent collector. It fails and is recorded as an attempt.
            plan.append({"step": "delete_log_lines",
                         "params": {"host": "collector", "file": AUTH_LOG, "event_selection": "own_session_all"},
                         "delay_s": rv.randrange(30, 90)})
        plan.append({"step": "delete_log_lines",
                     "params": {"host": "workstation", "file": AUTH_LOG,
                                "event_selection": rv.choice(list(S.DELETE_SELECTIONS))},
                     "delay_s": rv.randrange(30, 120)})
    return plan


def plan_context(spec: dict[str, Any]) -> S.PlanContext:
    acc = spec["accounts"]
    return S.PlanContext(
        level=spec["difficulty"],
        accounts=(acc["nurse_a"], acc["nurse_b"]),
        sink_ips=tuple(spec["dmz_ips"]),
        dataset_sizes=dict(spec["dataset_sizes"]),
    )


def operational_context(spec: dict[str, Any]) -> dict[str, Any]:
    """Investigator-visible operating knowledge. Identical in shape for incident and benign cases."""
    acc, badges = spec["accounts"], spec["badges"]
    inventory = [{"name": HOSTNAMES[r], "ip": IPS[r], "role": r} for r in ("workstation", "records", "iot-hub", "collector")]
    inventory += [{"name": EXTRA_NAMES[k], "ip": IPS[k], "role": k} for k in
                  ("backup-nas", "lab-gw", "vpn-gw", "admin-laptop", "printer", "gateway", "update-mirror")]
    inventory += [{"name": f"fd-term-{i + 1:02d}", "ip": ip, "role": "front-desk terminal"} for i, ip in enumerate(FRONT_DESK_IPS)]
    inventory.append({"range": "10.20.9.0/24", "role": "vendor/partner DMZ",
                      "note": "devices in this range are not individually inventoried"})
    return {
        "site": "Northside Clinic (synthetic)",
        "clock_note": "All sources record UTC in this simulated world; no clock skew is modeled.",
        "network_inventory": inventory,
        "accounts": [
            {"account": acc["nurse_a"], "role": "nurse", "badge": badges[acc["nurse_a"]]},
            {"account": acc["nurse_b"], "role": "nurse", "badge": badges[acc["nurse_b"]]},
            {"account": acc["admin"], "role": "it-admin", "badge": badges[acc["admin"]]},
            {"account": FRONT_DESK[0], "role": "front desk", "badge": None},
            {"account": FRONT_DESK[1], "role": "front desk", "badge": None},
            {"account": "svc-backup", "role": "service account", "badge": None},
        ],
        "other_badges": [
            {"badge": badges["facilities-1"], "holder": "facilities staff (no system account)"},
            {"badge": badges["pharmacy-1"], "holder": "pharmacy staff (no system account)"},
        ],
        "logging_policy": {
            "heartbeat_interval_s": HEARTBEAT_INTERVAL_S,
            "forwarded_files": [
                {"host": "workstation", "file": AUTH_LOG}, {"host": "workstation", "file": SYSLOG},
                {"host": "records", "file": AUTH_LOG}, {"host": "records", "file": SYSLOG},
                {"host": "records", "file": APP_LOG}, {"host": "iot-hub", "file": MQTT_LOG},
            ],
            "not_forwarded": ["shell histories", "file metadata snapshots"],
            "rotation": [
                {"host": "workstation", "file": AUTH_LOG, "keep": 1,
                 "note": "one rotated generation (.1) stays on the host; older generations are discarded"},
                {"host": "records", "file": APP_LOG, "keep": 0,
                 "note": "the rotated segment is archived off-host and is not part of a local capture"},
            ],
            "independent_witnesses": ["collector", "tap", "badge reader"],
            "host_local_sources": ["auth.log", "syslog", "records-app access.log", "shell history", "file metadata"],
        },
        "transfer_policy": {
            "bulk_threshold_bytes": BULK_THRESHOLD_BYTES,
            "approved_bulk_destinations": [
                {"ip": IPS["backup-nas"], "name": EXTRA_NAMES["backup-nas"], "purpose": "backup and log archive"},
                {"ip": IPS["lab-gw"], "name": EXTRA_NAMES["lab-gw"], "purpose": "laboratory and registry submissions"},
            ],
            "note": "In this scenario a bulk outbound transfer of clinic data to any other destination violates policy.",
        },
        "remote_access_policy": {
            "allowed": True,
            "via": f"{EXTRA_NAMES['vpn-gw']} ({IPS['vpn-gw']})",
            "note": "Staff may work remotely. Badge records do not cover remote sessions.",
        },
        "attribution_note": (
            "An account name identifies a credential, not a person. Console credentials at the shared "
            "station have been found written down before; badge readers can miss tailgating."
        ),
    }


# --------------------------------------------------------------------------- simulation


@dataclass
class SimOutput:
    spec: dict[str, Any]
    artifacts: dict[str, str]
    step_results: list[S.StepResult]
    benign_outcomes: list[dict[str, Any]] = field(default_factory=list)
    adversary_session: str | None = None
    world: World | None = None


def _parse(ts: str) -> datetime:
    return datetime.fromisoformat(ts)


def simulate(spec: dict[str, Any]) -> SimOutput:
    """Run one episode on the SimBackend. Deterministic for a given spec."""
    seed, variant = spec["seed"], spec["variant"]
    rb = random.Random(f"alibi-bg:{spec['scenario_version']}:{seed}:{variant}")
    t0 = _parse(spec["t0"])
    w = World(rb, _parse(spec["capture_start"]), _parse(spec["capture_end"]))
    acc, badges, benign = spec["accounts"], spec["badges"], spec["benign"]
    nurse_a, nurse_b, admin = acc["nurse_a"], acc["nurse_b"], acc["admin"]
    outcomes: list[dict[str, Any]] = []
    ws_ip, rec_ip = IPS["workstation"], IPS["records"]
    record_ids = [f"P-{n}" for n in rb.sample(range(10_000, 10_999), 160)]

    # ---------------- baseline files (older than the capture window)
    day = timedelta(days=1)
    for n in (nurse_a, nurse_b):
        for i in range(4):
            w.write_file("workstation", f"/home/{n}/Documents/census-110{6 + i}.csv", 40_000 + rb.randrange(0, 200_000), n,
                         t0 - day * (4 - i) + _m(rb.randrange(0, 400)))
    for i in range(3):
        w.write_file("workstation", f"/var/tmp/xfer/imm-registry-{100 + i}.db", 8_000_000 + rb.randrange(0, 4_000_000),
                     nurse_a, t0 - day * (30 * (3 - i)))
    for name in ("patients.db", "appointments.db", "audit.db"):
        w.write_file("records", f"/srv/records/{name}", spec["dataset_sizes"]["patients_full"] + rb.randrange(0, 900_000),
                     "records-app", t0 - _m(rb.randrange(5, 300)))

    # ---------------- presence (badge) schedule
    crime = spec["crime"]
    crime_start = _parse(crime["start"]) if crime else None
    presence: dict[str, list[tuple[datetime, datetime]]] = {}

    def nurse_presence(n: str, arrive: datetime, leave: datetime, brk: tuple[datetime, datetime]) -> None:
        presence[n] = [(arrive, brk[0]), (brk[1], leave)]

    brk_a = t0 + timedelta(seconds=rb.randrange(int(3.5 * 3600), int(4.25 * 3600)))
    brk_a = (brk_a, brk_a + _m(rb.randrange(25, 41)))
    brk_b = t0 + timedelta(seconds=rb.randrange(int(4.75 * 3600), int(5.5 * 3600)))
    brk_b = (brk_b, brk_b + _m(rb.randrange(25, 41)))
    breaks = {nurse_a: brk_a, nurse_b: brk_b}

    def move_break(n: str, start: datetime, end: datetime) -> None:
        breaks[n] = (start, end)

    if crime:
        framed = crime["framed_account"]
        if crime["owner_badged_out"]:
            move_break(framed, crime_start - _m(rb.randrange(6, 16)), crime_start + _m(rb.randrange(18, 30)))
        else:
            b0, b1 = breaks[framed]
            if b0 - _m(20) < crime_start < b1 + _m(20):  # keep the owner in the building during the crime
                shift = (crime_start - b0) + _m(45)
                move_break(framed, b0 + shift, b1 + shift)
    if variant == "benign_remote_login":
        rs = _parse(benign["start"])
        move_break(benign["actor"], rs - _m(rb.randrange(8, 15)), rs + timedelta(seconds=benign["duration_s"]) + _m(rb.randrange(10, 20)))

    nurse_presence(nurse_a, t0 - _m(rb.randrange(5, 13)), t0 + timedelta(hours=7, minutes=45) + _m(rb.randrange(0, 21)), breaks[nurse_a])
    nurse_presence(nurse_b, t0 + _m(rb.randrange(55, 81)), t0 + timedelta(hours=8) + _m(rb.randrange(0, 11)), breaks[nurse_b])
    presence[admin] = [(t0 + _m(rb.randrange(20, 41)), t0 + timedelta(hours=7) + _m(rb.randrange(0, 31)))]
    presence["facilities-1"] = [(t0 + _m(rb.randrange(30, 90)), t0 + _m(rb.randrange(150, 240)))]
    presence["pharmacy-1"] = [(t0 + _m(rb.randrange(10, 50)), t0 + timedelta(hours=4) + _m(rb.randrange(0, 60))),
                              (t0 + timedelta(hours=5) + _m(rb.randrange(10, 50)), t0 + timedelta(hours=7) + _m(rb.randrange(20, 60)))]
    for who in list(presence):
        presence[who] = [(a + timedelta(seconds=rb.randrange(0, 50)), b + timedelta(seconds=rb.randrange(0, 50)))
                         for a, b in presence[who]]
    for who, spans in presence.items():
        for a, b in spans:
            w.schedule(a, lambda ts, who=who: w.badge(ts, badges[who], "in"))
            w.schedule(b, lambda ts, who=who: w.badge(ts, badges[who], "out"))

    def present(n: str, a: datetime, b: datetime) -> bool:
        return any(s <= a and b <= e for s, e in presence[n])

    # ---------------- nurse activity primitives
    def act(account: str, ts: datetime, kind: str | None = None, client_ip: str = ws_ip) -> None:
        kind = kind or rb.choices(
            ["open", "update", "report", "lab", "print", "misc"], weights=[45, 20, 8, 9, 6, 12])[0]
        rid = rb.choice(record_ids)
        if kind == "open":
            w.history("workstation", account, ts, f"clinic-notes open {rid}")
            size = 2000 + rb.randrange(0, 7000)
            w.log("records", APP_LOG, ts + timedelta(seconds=1), "records-app[880]",
                  f"user={account} client={client_ip} action=open_record record={rid} bytes={size} status=200")
            w.flow(ts + timedelta(seconds=1), ws_ip, rec_ip, 443, 500 + rb.randrange(0, 400), size + 300)
        elif kind == "update":
            w.history("workstation", account, ts, f"clinic-notes update {rid}")
            w.log("records", APP_LOG, ts + timedelta(seconds=1), "records-app[880]",
                  f"user={account} client={client_ip} action=update_note record={rid} bytes={400 + rb.randrange(0, 900)} status=200")
            w.flow(ts + timedelta(seconds=1), ws_ip, rec_ip, 443, 1200 + rb.randrange(0, 2500), 420)
        elif kind == "report":
            size = 40_000 + rb.randrange(0, 260_000)
            path = f"/home/{account}/Documents/census-1110-{rb.randrange(10, 99)}.csv"
            w.history("workstation", account, ts, f"clinic-export --report daily-census --out {path}")
            w.log("records", APP_LOG, ts + timedelta(seconds=1), "records-app[880]",
                  f"user={account} client={client_ip} action=export_report report=daily-census bytes={size} status=200")
            w.flow(ts + timedelta(seconds=1), ws_ip, rec_ip, 443, 700 + rb.randrange(0, 300), size + 900)
            w.write_file("workstation", path, size, account, ts + timedelta(seconds=2))
        elif kind == "lab":
            num = rb.randrange(100, 999)
            path = f"/home/{account}/Documents/lab-req-{num}.pdf"
            size = 100_000 + rb.randrange(0, 800_000)
            w.history("workstation", account, ts, f"clinic-labs request --patient {rid} --out {path}")
            w.write_file("workstation", path, size, account, ts + timedelta(seconds=1))
            w.history("workstation", account, ts + timedelta(seconds=6),
                      f"curl -s -T {path} http://{IPS['lab-gw']}/upload/lab-req-{num}.pdf")
            w.flow(ts + timedelta(seconds=6), ws_ip, IPS["lab-gw"], 80, size + 1500, 300 + rb.randrange(0, 100))
        elif kind == "print":
            w.history("workstation", account, ts, f"lpr /home/{account}/Documents/census-1109.csv")
            w.flow(ts + timedelta(seconds=1), ws_ip, IPS["printer"], 631, 50_000 + rb.randrange(0, 250_000), 600)
        else:
            w.history("workstation", account, ts, rb.choice(
                ["ls ~/Documents", "clinic-sched view", "clinic-noets open", "whoami", "clinic-sched view --tomorrow", "df -h ~"]))

    def console_session(account: str, start: datetime, dur: int, kinds: list[str] | None = None) -> None:
        def _open(ts: datetime) -> None:
            if rb.random() < 0.08:
                w.log("workstation", AUTH_LOG, ts - timedelta(seconds=7), f"login[{w.next_pid()}]",
                      f"pam_unix(login:auth): authentication failure; user={account} tty=tty1")
            sess, _ = w.open_session("workstation", account, ts, origin="console", tty="tty1")
            w.console_busy_until = ts + timedelta(seconds=dur)
            w.schedule(ts + timedelta(seconds=dur), lambda t2, sess=sess: w.close_session(sess, t2))
        w.schedule(start, _open)
        n_acts = len(kinds) if kinds else max(3, dur // 130)
        offs = sorted(rb.sample(range(15, max(40, dur - 15)), min(n_acts, max(1, (dur - 30) // 12))))
        for i, off in enumerate(offs):
            k = kinds[i] if kinds and i < len(kinds) else None
            w.schedule(start + timedelta(seconds=off), lambda ts, k=k: act(account, ts, k))

    def remote_session(account: str, start: datetime, dur: int, kinds: list[str]) -> None:
        def _open(ts: datetime) -> None:
            sess, _ = w.open_session("workstation", account, ts, origin="remote", src_ip=IPS["vpn-gw"])
            w.schedule(ts + timedelta(seconds=dur), lambda t2, sess=sess: w.close_session(sess, t2))
        w.schedule(start, _open)
        offs = sorted(rb.sample(range(20, dur - 20), len(kinds)))
        for off, k in zip(offs, kinds):
            w.schedule(start + timedelta(seconds=off), lambda ts, k=k: act(account, ts, k))

    # ---------------- reserved console slots
    reserved: list[tuple[datetime, datetime]] = []
    if crime:
        reserved.append((crime_start - _m(3), crime_start + _m(22)))
    if variant == "benign_approved_transfer":
        ts0 = _parse(benign["start"])
        reserved.append((ts0 - _m(2), ts0 + _m(14)))
    if variant == "benign_collection_gap":
        # someone logs in at the shared station while forwarding is interrupted, so the host
        # holds records the collector never received
        g0 = _parse(benign["start"])
        who = next((n for n in (nurse_a, nurse_b)
                    if present(n, g0 - _m(2), g0 + timedelta(seconds=benign["duration_s"]) + _m(6))), None)
        if who is not None:
            reserved.append((g0 - _m(2), g0 + timedelta(seconds=benign["duration_s"]) + _m(5)))
            console_session(who, g0 + timedelta(seconds=35), benign["duration_s"] + 110)

    # ---------------- routine console sessions (shared station, one user at a time)
    t = t0 + timedelta(seconds=rb.randrange(120, 420))
    end_sessions = t0 + timedelta(hours=7, minutes=35)
    last = None
    while t < end_sessions:
        dur = rb.randrange(360, 1320)
        hit = next(((a, b) for a, b in reserved if t < b and t + timedelta(seconds=dur) > a), None)
        if hit:
            t = hit[1] + timedelta(seconds=rb.randrange(60, 240))
            continue
        cands = [n for n in (nurse_a, nurse_b) if present(n, t - _m(1), t + timedelta(seconds=dur) + _m(1))]
        if not cands:
            t += timedelta(seconds=300)
            continue
        who = rb.choice([n for n in cands if n != last] or cands)
        last = who
        console_session(who, t, dur)
        t += timedelta(seconds=dur + rb.randrange(120, 720))

    # ---------------- legitimate remote access (present in every case)
    pre = t0 - _m(rb.randrange(30, 41))
    pre_dur = rb.randrange(360, 600)
    remote_session(nurse_a, pre, pre_dur, ["open", "update", "open", "update"])
    outcomes.append({"kind": "remote_login", "host": "workstation", "actor_account": nurse_a,
                     "t_start": pre, "t_end": pre + timedelta(seconds=pre_dur),
                     "description": "pre-shift remote charting through the VPN gateway"})
    if variant == "benign_remote_login":
        rs, rd = _parse(benign["start"]), benign["duration_s"]
        remote_session(benign["actor"], rs, rd, ["open", "update", "report", "open", "lab", "update"])
        outcomes.append({"kind": "remote_login", "host": "workstation", "actor_account": benign["actor"],
                         "t_start": rs, "t_end": rs + timedelta(seconds=rd),
                         "description": "mid-shift remote session by the account owner while badged out"})

    # ---------------- approved ad-hoc bulk transfer (benign control)
    if variant == "benign_approved_transfer":
        actor, ts0 = benign["actor"], _parse(benign["start"])
        size = spec["dataset_sizes"]["immunization_registry"]
        path = f"/var/tmp/xfer/{benign['dst_name']}"

        def _approved(ts: datetime) -> None:
            w.history("workstation", actor, ts, f"clinic-export --dataset immunization_registry --out {path}")
            w.log("records", APP_LOG, ts + timedelta(seconds=1), "records-app[880]",
                  f"user={actor} client={ws_ip} action=export_bulk dataset=immunization_registry bytes={size} status=200")
            w.flow(ts + timedelta(seconds=1), ws_ip, rec_ip, 443, 1500, size + 2200, duration_s=max(3, size // 4_000_000))
            w.write_file("workstation", path, size, actor, ts + timedelta(seconds=4))
            up = ts + timedelta(seconds=95)
            w.history("workstation", actor, up, f"curl -s -T {path} http://{IPS['lab-gw']}/upload/{benign['dst_name']}")
            w.flow(up, ws_ip, IPS["lab-gw"], 80, size + 3300, 410, duration_s=max(4, size // 1_500_000))
        console_session(actor, ts0, 600, ["open", "update"])
        w.schedule(ts0 + timedelta(seconds=140), _approved)
        outcomes.append({"kind": "approved_bulk_transfer", "host": "workstation", "actor_account": actor,
                         "t_start": ts0 + timedelta(seconds=140), "t_end": ts0 + timedelta(seconds=260),
                         "description": "registry export staged and uploaded to the approved lab gateway"})

    # ---------------- front desk terminals (records traffic that never touches the nurse station)
    for i, fd in enumerate(FRONT_DESK):
        tt = t0 + timedelta(seconds=rb.randrange(60, 400))
        while tt < t0 + timedelta(hours=8):
            def _fd(ts: datetime, fd=fd, ip=FRONT_DESK_IPS[i]) -> None:
                rid = rb.choice(record_ids)
                action = rb.choice(["open_record", "open_record", "open_record", "update_note"])
                size = 1500 + rb.randrange(0, 6000)
                w.log("records", APP_LOG, ts, "records-app[880]",
                      f"user={fd} client={ip} action={action} record={rid} bytes={size} status=200")
                w.flow(ts, ip, rec_ip, 443, 500 + rb.randrange(0, 500), size + 300)
            w.schedule(tt, _fd)
            tt += timedelta(seconds=rb.randrange(35, 150))

    # ---------------- it-admin maintenance
    adm_rec = t0 + _m(rb.randrange(42, 62)) + timedelta(seconds=rb.randrange(0, 60))

    def _admin_records(ts: datetime) -> None:
        sess, _ = w.open_session("records", admin, ts, origin="remote", src_ip=IPS["admin-laptop"])
        for off, cmd in ((30, "df -h"), (70, "sudo systemctl status records-app"), (150, "sudo tail -n 50 /var/log/records-app/access.log")):
            w.history("records", admin, ts + timedelta(seconds=off), cmd)
            if cmd.startswith("sudo"):
                w.log("records", AUTH_LOG, ts + timedelta(seconds=off), f"sudo[{w.next_pid()}]",
                      f"{admin} : TTY=pts/0 ; COMMAND={cmd[5:]} (session {sess.number})")
        w.schedule(ts + timedelta(seconds=rb.randrange(300, 600)), lambda t2: w.close_session(sess, t2))
    w.schedule(adm_rec, _admin_records)

    adm_ws = t0 + timedelta(hours=6) + _m(rb.randrange(-20, 21)) + timedelta(seconds=rb.randrange(0, 60))
    forced_rot = _parse(benign["forced_rotation_at"]) if variant == "benign_rotation" else None
    gap = None
    if variant == "benign_collection_gap":
        g0 = _parse(benign["start"])
        gap = (g0, g0 + timedelta(seconds=benign["duration_s"]))
        w.forwarder_down["workstation"] = [gap]
        outcomes.append({"kind": "collection_gap", "host": "workstation", "actor_account": None,
                         "t_start": gap[0], "t_end": gap[1],
                         "description": f"log forwarding from the workstation interrupted ({benign['cause']})"})
        if benign["cause"] == "agent_restart":
            adm_ws = g0 - timedelta(seconds=40)

    def _admin_ws(ts: datetime) -> None:
        sess, _ = w.open_session("workstation", admin, ts, origin="remote", src_ip=IPS["admin-laptop"])
        cmds: list[tuple[int, str]] = [(17 + rb.randrange(0, 9), "uptime"), (52 + rb.randrange(0, 30), "sudo apt list --upgradable")]
        if gap and benign["cause"] == "agent_restart":
            cmds = [(15, "uptime"), (36, "sudo systemctl restart log-forwarder")]
        if forced_rot is not None:
            cmds = [(20, "uptime"), (max(40, int((forced_rot - ts).total_seconds()) - 2), "sudo logrotate -f /etc/logrotate.d/clinic")]
        for off, cmd in cmds:
            w.history("workstation", admin, ts + timedelta(seconds=off), cmd)
            if cmd.startswith("sudo"):
                w.log("workstation", AUTH_LOG, ts + timedelta(seconds=off), f"sudo[{w.next_pid()}]",
                      f"{admin} : TTY=pts/0 ; COMMAND={cmd[5:]} (session {sess.number})")
        w.schedule(ts + timedelta(seconds=cmds[-1][0] + rb.randrange(60, 200)), lambda t2: w.close_session(sess, t2))
    if forced_rot is not None:
        adm_ws = forced_rot - timedelta(seconds=rb.randrange(120, 240))
    w.schedule(adm_ws, _admin_ws)

    if gap and benign["cause"] == "agent_restart":
        w.schedule(gap[0] - timedelta(seconds=2), lambda ts: w.log("workstation", SYSLOG, ts, "systemd[1]", "Stopping log-forwarder.service..."))
        w.schedule(gap[1] + timedelta(seconds=1), lambda ts: w.log("workstation", SYSLOG, ts, "systemd[1]", "Started log-forwarder.service."))

    # ---------------- scheduled rotation (present in every case)
    t_rot = _parse(spec["t_rot"])
    datestr = t0.strftime("%Y%m%d")

    def _rotate_ws(ts: datetime, forced: bool = False) -> None:
        if not forced:
            w.log("workstation", SYSLOG, ts, f"CRON[{w.next_pid()}]", "(root) CMD (/usr/sbin/logrotate /etc/logrotate.d/clinic)")
        gone = w.rotate("workstation", AUTH_LOG, ts + timedelta(seconds=1))
        note = "keep 1" if gone == 0 else f"keep 1; previous {AUTH_LOG}.1 discarded"
        w.log("workstation", SYSLOG, ts + timedelta(seconds=1), f"logrotate[{w.next_pid()}]",
              f"rotated {AUTH_LOG} -> {AUTH_LOG}.1 ({note})")

    def _rotate_rec(ts: datetime) -> None:
        w.log("records", SYSLOG, ts, f"CRON[{w.next_pid()}]", "(root) CMD (/usr/sbin/logrotate /etc/logrotate.d/records-app)")
        gone = w.rotate("records", APP_LOG, ts + timedelta(seconds=1))
        w.log("records", SYSLOG, ts + timedelta(seconds=1), f"logrotate[{w.next_pid()}]",
              f"rotated {APP_LOG} -> archived off-host {EXTRA_NAMES['backup-nas']}:/archive/{HOSTNAMES['records']}/access-{datestr}.log.gz (keep 0)")
        w.flow(ts + timedelta(seconds=2), rec_ip, IPS["backup-nas"], 873, 9000 + gone * 40, 700)
    w.schedule(t_rot, _rotate_ws)
    w.schedule(t_rot + timedelta(seconds=3), _rotate_rec)
    outcomes.append({"kind": "scheduled_rotation", "host": "workstation", "actor_account": "root", "t_start": t_rot,
                     "t_end": t_rot + timedelta(seconds=5), "description": "scheduled log rotation on workstation and records"})
    if forced_rot is not None:
        w.schedule(forced_rot, lambda ts: _rotate_ws(ts, forced=True))
        outcomes.append({"kind": "forced_rotation", "host": "workstation", "actor_account": admin, "t_start": forced_rot,
                         "t_end": forced_rot + timedelta(seconds=3),
                         "description": "administrator forced a second rotation; the earlier .1 generation was discarded by policy"})

    # ---------------- scheduled backup (approved bulk transfer, present in every case)
    t_backup = _parse(spec["t_backup"])
    psize = spec["dataset_sizes"]["patients_full"]

    def _backup(ts: datetime) -> None:
        w.log("records", SYSLOG, ts, f"CRON[{w.next_pid()}]", "(svc-backup) CMD (/opt/clinic/bin/backup-incremental)")
        w.log("records", APP_LOG, ts + timedelta(seconds=2), "records-app[880]",
              f"user=svc-backup client=127.0.0.1 action=export_bulk dataset=patients_full bytes={psize} status=200")
        w.flow(ts + timedelta(seconds=4), rec_ip, IPS["backup-nas"], 873, psize + 5200, 900, duration_s=max(5, psize // 3_000_000))
    w.schedule(t_backup, _backup)
    outcomes.append({"kind": "approved_bulk_transfer", "host": "records", "actor_account": "svc-backup", "t_start": t_backup,
                     "t_end": t_backup + timedelta(seconds=20), "description": "scheduled backup to the approved NAS"})

    # ---------------- background network noise
    cs, ce = w.capture_start, w.capture_end
    for src in (ws_ip, rec_ip, IPS["iot-hub"], IPS["collector"]):
        tt = cs + timedelta(seconds=rb.randrange(5, 300))
        while tt < ce:
            w.schedule(tt, lambda ts, src=src: w.flow(ts, src, IPS["gateway"], rb.choice([53, 123]), 76 + rb.randrange(0, 60), 76 + rb.randrange(0, 180), duration_s=1))
            tt += timedelta(seconds=rb.randrange(240, 560))
    for src in (ws_ip, rec_ip, IPS["iot-hub"]):
        tt = cs + timedelta(seconds=rb.randrange(30, 600))
        while tt < ce:
            w.schedule(tt, lambda ts, src=src: w.flow(ts, src, IPS["collector"], 6514, 40_000 + rb.randrange(0, 160_000), 1200, duration_s=3))
            tt += timedelta(seconds=600)
    for src in (ws_ip, IPS["iot-hub"]):
        tt = cs + timedelta(seconds=rb.randrange(60, 700))
        while tt < ce:  # vendor telemetry: small flows to DMZ addresses, in every case
            w.schedule(tt, lambda ts, src=src: w.flow(ts, src, rb.choice(spec["dmz_ips"]), rb.choice([443, 8080]), 400 + rb.randrange(0, 40_000), 300 + rb.randrange(0, 900)))
            tt += timedelta(seconds=rb.randrange(360, 840))
    for src in (ws_ip, rec_ip):
        tt = cs + timedelta(seconds=rb.randrange(200, 2400))
        while tt < ce:
            w.schedule(tt, lambda ts, src=src: w.flow(ts, src, IPS["update-mirror"], 80, 600 + rb.randrange(0, 500), 5000 + rb.randrange(0, 2_000_000)))
            tt += timedelta(seconds=rb.randrange(2400, 3600))
    tt = cs + timedelta(seconds=rb.randrange(100, 900))
    while tt < ce:
        w.schedule(tt, lambda ts: w.log(rb.choice(["workstation", "records"]), SYSLOG, ts, f"systemd-timesyncd[{640}]",
                                        f"Synchronized to time server {IPS['gateway']}:123."))
        tt += timedelta(seconds=rb.randrange(900, 1900))

    # ---------------- optional hostile evidence text (PLAN 2.11: evidence is untrusted input)
    # Used by tests to plant prompt-injection / markup strings in a log line. It is evidence text
    # only; nothing in the simulator, the tools or the UI interprets it.
    for item in spec.get("injected_evidence", []):
        at = _parse(item["at"])
        w.schedule(at, lambda ts, text=item["text"]: w.log(
            "workstation", AUTH_LOG, ts, f"login[{w.next_pid()}]",
            f"pam_unix(login:auth): authentication failure; user={text} tty=tty1"))

    # ---------------- the adversary (executes the saved plan; nothing else)
    executor: S.StepExecutor | None = None
    if crime and spec["plan"]:
        ctx = plan_context(spec)
        plan = S.validate_plan(spec["plan"], ctx)
        executor = S.StepExecutor(w, ctx)

        def _run_step(i: int, ts: datetime) -> None:
            res = executor.execute(plan[i], ts)
            if i == 0 and res.status == "succeeded":
                w.console_busy_until = ts + _m(22)
            if i + 1 < len(plan):
                nxt = max(res.t_end, ts) + timedelta(seconds=plan[i + 1]["delay_s"])
                w.schedule(nxt, lambda t2, j=i + 1: _run_step(j, t2))
            elif executor.session is not None:
                out = max(res.t_end, ts) + timedelta(seconds=40 + (seed % 50))
                w.schedule(out, lambda t2: (w.close_session(executor.session, t2), setattr(w, "console_busy_until", t2)))
        w.schedule(crime_start + timedelta(seconds=plan[0]["delay_s"]), lambda ts: _run_step(0, ts))

    w.run()
    return SimOutput(
        spec=spec,
        artifacts=w.render_artifacts(),
        step_results=executor.results if executor else [],
        benign_outcomes=outcomes,
        adversary_session=executor.session.session_id if executor and executor.session else None,
        world=w,
    )
