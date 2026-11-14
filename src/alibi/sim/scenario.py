"""Scenario specifications and the scripted background/adversary generators.

A ScenarioSpec is the complete, saved input of an episode: world parameters, the
variant-specific benign activity, and the *executed* adversary plan (scripted here,
or supplied by a bounded planning model). Re-running `simulate(spec)` reproduces
byte-identical raw evidence.
"""

from __future__ import annotations

import math
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

# SCENARIO_VERSION is part of every random seed below: changing it would change every generated case and
# break byte-for-byte replay of saved recordings. It therefore stays "1.0.0" for good. What the catalog
# contains is tracked separately.
SCENARIO_VERSION = "1.0.0"
SCENARIO_CATALOG_VERSION = "1.1.0"  # 1.1.0: records heist, cold chain, evasion and maintenance variants added

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

# ---------------------------------------------------------------------------- phase-two case families
# The six variants above are the first-run family and are frozen (tests/test_m8_pins.py). Everything
# below is additive: a new variant never changes what an existing (seed, variant) pair produces.
CARD_RECORDS_HEIST = "records-heist"
CARD_COLD_CHAIN = "cold-chain"
CARDS[CARD_INSIDE_JOB]["difficulties"].append("L3")
CARDS[CARD_RECORDS_HEIST] = {
    "id": CARD_RECORDS_HEIST,
    "title": "Records heist",
    "audience_setup": (
        "Someone signs in to the records server itself with an administrator's credential, exports the "
        "synthetic patient database there and sends it out of the clinic network from the server."
    ),
    "tip": "Review exports from the records server during this shift; establish what the evidence supports.",
    "difficulties": ["H1", "H2"],
}
CARDS[CARD_COLD_CHAIN] = {
    "id": CARD_COLD_CHAIN,
    "title": "Cold chain",
    "audience_setup": (
        "The vaccine refrigerator warms beyond its permitted range and someone overwrites the stored "
        "readings so the record looks normal."
    ),
    "tip": "Review the vaccine refrigerator's temperature record for this shift; establish what the evidence supports.",
    "difficulties": ["C1"],
}

EVASION_INCIDENT_VARIANTS = ("incident_evasion",)  # inside job plus the four phase-two steps
MAINTENANCE_BENIGN_VARIANTS = ("benign_maintenance",)  # their legitimate counterparts
HEIST_INCIDENT_VARIANTS = ("heist_incident", "heist_coverup")
HEIST_BENIGN_VARIANTS = ("heist_approved_export",)
COLDCHAIN_INCIDENT_VARIANTS = ("coldchain_falsified",)
COLDCHAIN_BENIGN_VARIANTS = ("coldchain_real_excursion", "coldchain_maintenance")

FAMILY_INCIDENT_VARIANTS = EVASION_INCIDENT_VARIANTS + HEIST_INCIDENT_VARIANTS + COLDCHAIN_INCIDENT_VARIANTS
FAMILY_BENIGN_VARIANTS = MAINTENANCE_BENIGN_VARIANTS + HEIST_BENIGN_VARIANTS + COLDCHAIN_BENIGN_VARIANTS
FAMILY_VARIANTS = FAMILY_INCIDENT_VARIANTS + FAMILY_BENIGN_VARIANTS
ALL_INCIDENT_VARIANTS = INCIDENT_VARIANTS + FAMILY_INCIDENT_VARIANTS
ALL_BENIGN_VARIANTS = BENIGN_VARIANTS + FAMILY_BENIGN_VARIANTS
ALL_VARIANTS = VARIANTS + FAMILY_VARIANTS
VARIANT_CARD: dict[str, str] = {
    **{v: CARD_INSIDE_JOB for v in VARIANTS + EVASION_INCIDENT_VARIANTS + MAINTENANCE_BENIGN_VARIANTS},
    **{v: CARD_RECORDS_HEIST for v in HEIST_INCIDENT_VARIANTS + HEIST_BENIGN_VARIANTS},
    **{v: CARD_COLD_CHAIN for v in COLDCHAIN_INCIDENT_VARIANTS + COLDCHAIN_BENIGN_VARIANTS},
}
VARIANT_DIFFICULTY: dict[str, str] = {
    "incident_plain": "L1", "incident_coverup": "L2", "incident_evasion": "L3",
    "heist_incident": "H1", "heist_coverup": "H2", "coldchain_falsified": "C1",
}
SENSOR = "fridge-01"
REFERENCE_LOGGER = "logger-01"
SENSOR_RANGE_C = (2.0, 8.0)
SENSOR_INTERVAL_S = 60
REFERENCE_INTERVAL_S = 300
REFERENCE_MAX_OFFSET_S = 120

NURSE_POOL = ["jpark", "mreyes", "aokafor", "lnguyen", "sdubois", "rhaddad", "kcole", "tmori"]
ADMIN_POOL = ["adm-tkim", "adm-vrao", "adm-bsato"]
FRONT_DESK = ["fd-alvarez", "fd-moss"]
FRONT_DESK_IPS = ["10.20.1.31", "10.20.1.32"]
STAGING_NAMES = ["rx-7f3.db", "cache-0a91.bin", "upd-4c2e.pkg", "tmp-b77d.dat", "sess-91ac.db", "idx-3e08.bin"]


def _m(minutes: float) -> timedelta:
    return timedelta(seconds=int(minutes * 60))


def build_spec(seed: int, variant: str, card_id: str = CARD_INSIDE_JOB) -> dict[str, Any]:
    """Derive a complete scenario specification from (seed, variant). Pure and deterministic."""
    if variant not in ALL_VARIANTS:
        raise ValueError(f"unknown variant {variant!r}; choose from {ALL_VARIANTS}")
    if variant in FAMILY_VARIANTS:
        card_id = VARIANT_CARD[variant]  # a phase-two variant belongs to exactly one card
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
        "case_kind": "incident" if variant in ALL_INCIDENT_VARIANTS else "benign",
        "difficulty": VARIANT_DIFFICULTY.get(variant, "none"),
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
    elif variant in FAMILY_VARIANTS:
        _family_spec(spec, rv, t0, t_backup)
    return spec


def _clear_of(start: datetime, other: datetime, minutes: int = 15) -> datetime:
    """Keep a scripted activity from landing on top of another scheduled one."""
    return start + _m(27) if abs((start - other).total_seconds()) < minutes * 60 else start


def _family_spec(spec: dict[str, Any], rv: random.Random, t0: datetime, t_backup: datetime) -> None:
    """Scenario parameters of the phase-two variants. Uses only the variant's own random stream."""
    variant, acc = spec["variant"], spec["accounts"]
    nurse_a, nurse_b, admin = acc["nurse_a"], acc["nurse_b"], acc["admin"]
    dmz = spec["dmz_ips"]
    spec["change_id_base"] = rv.randrange(4100, 9800)  # numbering of the shift's change records

    if variant in HEIST_INCIDENT_VARIANTS + HEIST_BENIGN_VARIANTS:
        partner = rv.choice(dmz)
        a0 = t0 + timedelta(seconds=rv.randrange(int(1.2 * 3600), int(2.4 * 3600)))
        spec["heist"] = {"partner_ip": partner, "approved_start": iso(a0),
                         "approved_name": f"reg-{rv.randrange(100, 999)}.db"}
        if variant in HEIST_INCIDENT_VARIANTS:
            start = _clear_of(t0 + timedelta(seconds=rv.randrange(int(3.2 * 3600), int(6.3 * 3600))), t_backup)
            sink = rv.choice([ip for ip in dmz if ip != partner])
            spec["crime"] = {
                "start": iso(start), "framed_account": admin,
                # an administrator's credential used remotely: by its holder, or by someone else who has it
                "operator_person": rv.choice([f"person:{nurse_a}", f"person:{nurse_b}", f"person:{admin}"]),
                "owner_badged_out": False, "sink_ip": sink,
            }
            spec["plan"] = heist_plan(rv, spec["difficulty"], admin, sink)
    elif variant in EVASION_INCIDENT_VARIANTS:
        framed = rv.choice([nurse_a, nurse_b])
        other = nurse_b if framed == nurse_a else nurse_a
        start = _clear_of(t0 + timedelta(seconds=rv.randrange(3 * 3600, int(6.2 * 3600))), t_backup)
        sink = rv.choice(dmz)
        spec["crime"] = {"start": iso(start), "framed_account": framed,
                         "operator_person": rv.choice([f"person:{other}", f"person:{admin}"]),
                         "owner_badged_out": rv.random() < 0.5, "sink_ip": sink}
        spec["plan"] = evasion_plan(rv, framed, admin, sink)
        # the shift's change record names a maintenance window that does NOT cover the incident
        spec["benign"] = {"maintenance_start": iso(t0 + timedelta(seconds=rv.randrange(int(1.1 * 3600), int(2.2 * 3600)))),
                          "parts": []}
    elif variant in MAINTENANCE_BENIGN_VARIANTS:
        start = _clear_of(t0 + timedelta(seconds=rv.randrange(int(3.0 * 3600), int(5.8 * 3600))), t_backup, 25)
        spec["benign"] = {"maintenance_start": iso(start), "forwarder_gap_s": rv.randrange(150, 330),
                          "gui_actor": rv.choice([nurse_a, nurse_b]),
                          "parts": ["forwarder_stop", "restore", "second_host", "gui_session"]}
    else:  # cold chain
        ex0 = t0 + timedelta(seconds=rv.randrange(int(2.5 * 3600), int(5.5 * 3600)))
        spec["coldchain"] = {
            "excursion_start": iso(ex0), "excursion_minutes": rv.randrange(13, 21),
            "peak_c": round(9.6 + rv.randrange(0, 30) / 10, 1),
            "reference_clock_offset_s": rv.choice([-75, -40, 35, 60, 90]),
            "maintenance_start": iso(t0 + timedelta(seconds=rv.randrange(int(0.8 * 3600), int(1.8 * 3600)))),
            "maintenance_minutes": rv.randrange(8, 14),
            # the maintenance control has no warming event; the other two have a real one
            "has_excursion": variant != "coldchain_maintenance",
        }
        if variant in COLDCHAIN_INCIDENT_VARIANTS:
            spec["crime"] = {"start": iso(ex0 + _m(spec["coldchain"]["excursion_minutes"] + rv.randrange(25, 50))),
                             "framed_account": None,
                             "operator_person": rv.choice([f"person:{nurse_a}", f"person:{nurse_b}", f"person:{admin}"]),
                             "owner_badged_out": False, "sink_ip": None}
            spec["plan"] = [{"step": "falsify_readings", "params": {"sensor": SENSOR, "mode": "flatten"}, "delay_s": 30}]


def heist_plan(rv: random.Random, level: str, admin: str, sink_ip: str) -> list[dict[str, Any]]:
    """Records-server plan. A SCRIPTED SCENARIO: no model chose these steps."""
    dst_dir, dst_name = rv.choice(list(S.DUMP_DIRS)), rv.choice(STAGING_NAMES)
    plan: list[dict[str, Any]] = [
        {"step": "login_remote", "params": {"host": "records", "account": admin, "via": "vpn-gw"}, "delay_s": 20},
        {"step": "export_dump", "params": {"dataset": "patients_full", "dst_dir": dst_dir, "dst_name": dst_name},
         "delay_s": rv.randrange(50, 150)},
        {"step": "exfil_http", "params": {"path": f"{dst_dir}/{dst_name}", "dst": sink_ip}, "delay_s": rv.randrange(60, 200)},
    ]
    if level == "H2":
        if rv.random() < 0.5:  # an attempt against the independent collector: it fails and is recorded
            plan.append({"step": "delete_log_lines",
                         "params": {"host": "collector", "file": APP_LOG, "event_selection": "own_exports"},
                         "delay_s": rv.randrange(30, 90)})
        plan.append({"step": "delete_log_lines",
                     "params": {"host": "records", "file": APP_LOG, "event_selection": "own_exports"},
                     "delay_s": rv.randrange(30, 120)})
    return plan


def evasion_plan(rv: random.Random, account: str, admin: str, sink_ip: str) -> list[dict[str, Any]]:
    """Inside job plus the four phase-two steps. A SCRIPTED SCENARIO: no model chose these steps."""
    dst_dir = rv.choice(["/var/tmp/.pkg-cache", "/tmp/.font-unix", "/home/{account}/Downloads"])
    dst_name = rv.choice(STAGING_NAMES)
    path = S.staging_path(dst_dir, dst_name, account)
    return [
        {"step": "login_as", "params": {"account": account}, "delay_s": 20},
        {"step": "stage_copy", "params": {"src": "patients_full", "dst_dir": dst_dir, "dst_name": dst_name},
         "delay_s": rv.randrange(40, 90)},
        {"step": "exfil_http", "params": {"path": path, "dst": sink_ip}, "delay_s": rv.randrange(40, 100)},
        {"step": "timestomp", "params": {"path": path, "mode": "backdate_30d"}, "delay_s": rv.randrange(25, 60)},
        # a nurse account may not control services: this attempt fails and is recorded
        {"step": "stop_forwarder", "params": {"host": "workstation", "duration_s": rv.randrange(120, 300)},
         "delay_s": rv.randrange(20, 45)},
        {"step": "second_host_session", "params": {"host": "records", "account": admin}, "delay_s": rv.randrange(25, 60)},
        {"step": "stop_forwarder", "params": {"host": "records", "duration_s": rv.randrange(120, 300)},
         "delay_s": rv.randrange(25, 60)},
        {"step": "clear_history", "params": {"scope": "own_session"}, "delay_s": rv.randrange(25, 60)},
    ]


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
        admin_accounts=(acc["admin"],),
        sensors=(SENSOR,) if spec.get("card_id") == CARD_COLD_CHAIN else (),
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
    ctx: dict[str, Any] = {
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
    if spec["variant"] in FAMILY_VARIANTS:
        _family_context(spec, ctx)
    return ctx


def change_records(spec: dict[str, Any]) -> list[dict[str, Any]]:
    """The shift's approved operational changes, as an investigator would be given them.

    Every phase-two case has the same kinds of record whether or not anything went wrong:
    a record never says what an incident was, only what was approved.
    """
    acc, base = spec["accounts"], spec.get("change_id_base", 4100)
    variant = spec["variant"]
    out: list[dict[str, Any]] = []
    if "heist" in spec:
        hx = spec["heist"]
        a0 = _parse(hx["approved_start"])
        out.append({
            "id": f"CHG-{base}", "kind": "bulk_export", "requested_by": acc["admin"], "approved_by": "clinic manager",
            "source_host": "records", "dataset": "immunization_registry",
            "destination_ip": hx["partner_ip"], "destination_name": "state immunization registry (partner gateway)",
            "window_start": iso(a0 - _m(20)), "window_end": iso(a0 + _m(40)),
            "note": "quarterly registry submission; one export to this destination in this window",
        })
    if variant in EVASION_INCIDENT_VARIANTS + MAINTENANCE_BENIGN_VARIANTS:
        m0 = _parse(spec["benign"]["maintenance_start"])
        out.append({
            "id": f"CHG-{base + 7}", "kind": "maintenance", "requested_by": acc["admin"], "approved_by": "clinic manager",
            "hosts": ["workstation", "records"], "window_start": iso(m0 - _m(10)), "window_end": iso(m0 + _m(35)),
            "activities": ["log forwarder maintenance", "restore of user documents from backup",
                           "administrator access to the records server from the nurse workstation"],
            "note": "work carried out by the requesting administrator under this record",
        })
    return out


def _family_context(spec: dict[str, Any], ctx: dict[str, Any]) -> None:
    """Operating knowledge that only the phase-two families need. Same shape for incident and benign."""
    acc = spec["accounts"]
    ctx["change_records"] = change_records(spec)
    ctx["change_policy"] = (
        "Bulk exports made on the records server, stopping log forwarding, and administrator sessions that do not "
        "come from the administrator laptop or the VPN gateway each need an approved change record covering the "
        "host and the time. A destination named in an approved export record is approved for that export only."
    )
    ctx["remote_access_policy"]["admin_sources"] = [
        {"name": EXTRA_NAMES["admin-laptop"], "ip": IPS["admin-laptop"]},
        {"name": EXTRA_NAMES["vpn-gw"], "ip": IPS["vpn-gw"]},
    ]
    ctx["remote_access_policy"]["admin_accounts"] = [acc["admin"]]
    ctx["history_policy"] = {
        "cli_clients_record_history": True,
        "note": ("The command-line clinic clients write shell history. The touch-screen charting client does not, "
                 "so records activity without a matching history command is not by itself evidence of removal."),
    }
    if spec["card_id"] == CARD_COLD_CHAIN:
        cc = spec["coldchain"]
        m0 = _parse(cc["maintenance_start"])
        ctx["coldchain_policy"] = {
            "sensor": SENSOR, "permitted_range_c": list(SENSOR_RANGE_C), "local_interval_s": SENSOR_INTERVAL_S,
            "local_stream": ("readings stored on the IoT hub and shown on the ward dashboard; the store is writable "
                             "on the hub"),
            "reference": {
                "logger": REFERENCE_LOGGER, "interval_s": REFERENCE_INTERVAL_S,
                "independence": ("a separate battery logger with its own probe in the same refrigerator; it is not "
                                 "connected to the hub and cannot be written from it"),
                "clock": (f"not network-synchronised; its clock may differ from the hub by up to "
                          f"{REFERENCE_MAX_OFFSET_S} s"),
                "max_clock_offset_s": REFERENCE_MAX_OFFSET_S,
                "probe_tolerance_c": 0.8,
            },
            "excursion_rule": "two or more consecutive reference readings outside the permitted range",
            "maintenance_windows": [{
                "id": f"CAL-{spec.get('change_id_base', 4100) + 3}", "kind": "probe_calibration",
                "window_start": iso(m0), "window_end": iso(m0 + _m(cc["maintenance_minutes"])),
                "note": ("the hub's probe is taken out for an ice-point check; its readings are not refrigerator "
                         "temperatures during this window and its counter restarts afterwards"),
            }],
            "note": ("A temperature record describes the refrigerator. It does not show why it warmed or who "
                     "handled the record."),
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

    console_crime = bool(crime) and spec["card_id"] == CARD_INSIDE_JOB  # always true for the first-run family
    if console_crime:
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
        if kind == "gui_open":
            # the touch-screen charting client: the same records request, but no shell history is written
            size = 2000 + rb.randrange(0, 7000)
            w.log("records", APP_LOG, ts + timedelta(seconds=1), "records-app[880]",
                  f"user={account} client={client_ip} action=open_record record={rid} bytes={size} status=200")
            w.flow(ts + timedelta(seconds=1), ws_ip, rec_ip, 443, 500 + rb.randrange(0, 400), size + 300)
        elif kind == "open":
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
    if console_crime:
        reserved.append((crime_start - _m(3), crime_start + _m(22)))
    if variant in MAINTENANCE_BENIGN_VARIANTS:
        g0 = _parse(benign["maintenance_start"])
        reserved.append((g0 - _m(2), g0 + _m(16)))  # the touch-screen session of the control
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

    # ================= phase two: activity that exists only in the new case families =================
    # Nothing in this section runs for a first-run variant, so their random streams are untouched.
    if "heist" in spec:
        _sim_approved_export(w, rb, spec, admin, outcomes)
    if variant in MAINTENANCE_BENIGN_VARIANTS:
        gui = next((n for n in (benign["gui_actor"], nurse_a, nurse_b)
                    if present(n, _parse(benign["maintenance_start"]) - _m(1), _parse(benign["maintenance_start"]) + _m(14))),
                   benign["gui_actor"])
        console_session(gui, _parse(benign["maintenance_start"]) + timedelta(seconds=50), 600, ["gui_open"] * 6)
        _sim_maintenance(w, rb, spec, admin, gui, t0, outcomes)
    if spec["card_id"] == CARD_COLD_CHAIN:
        _sim_cold_chain(w, spec, outcomes)

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
                for k, extra in enumerate(executor.extra_sessions.values()):  # second-host sessions close first
                    w.schedule(max(res.t_end, ts) + timedelta(seconds=15 + 4 * k),
                               lambda t2, extra=extra: w.close_session(extra, t2))
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


# --------------------------------------------------------------------------- phase-two legitimate activity
# Each function below writes ordinary, legitimate activity into the world. They are called only for
# the phase-two variants and record what they did as sealed benign outcomes.


def _sudo(w: World, role: str, admin: str, session_no: int, ts: datetime, cmd: str) -> None:
    w.history(role, admin, ts, f"sudo {cmd}")
    w.log(role, AUTH_LOG, ts, f"sudo[{w.next_pid()}]", f"{admin} : TTY=pts/0 ; COMMAND={cmd} (session {session_no})")


def _sim_approved_export(w: World, rb: random.Random, spec: dict[str, Any], admin: str,
                         outcomes: list[dict[str, Any]]) -> None:
    """The quarterly registry submission: an export made ON the records server under an approved change
    record and sent to the partner it names. It is in every records-family case, incident or not."""
    hx = spec["heist"]
    a0, partner, rec_ip = _parse(hx["approved_start"]), hx["partner_ip"], IPS["records"]
    size = spec["dataset_sizes"]["immunization_registry"]
    path = f"/srv/records/tmp/{hx['approved_name']}"
    t_dump = a0 + timedelta(seconds=40 + rb.randrange(0, 30))
    t_send = t_dump + timedelta(seconds=80 + rb.randrange(0, 60))
    t_close = t_send + timedelta(seconds=90 + rb.randrange(0, 120))
    state: dict[str, Any] = {}

    def _open(ts: datetime) -> None:
        state["sess"], _ = w.open_session("records", admin, ts, origin="remote", src_ip=IPS["vpn-gw"])

    def _dump(ts: datetime) -> None:
        w.history("records", admin, ts, f"records-dump --dataset immunization_registry --out {path}")
        w.log("records", APP_LOG, ts + timedelta(seconds=1), "records-app[880]",
              f"user={admin} client=127.0.0.1 action=export_bulk dataset=immunization_registry bytes={size} status=200")
        w.write_file("records", path, size, admin, ts + timedelta(seconds=max(3, size // 6_000_000)))

    def _send(ts: datetime) -> None:
        w.history("records", admin, ts, f"curl -s -T {path} https://{partner}:8443/submit/{hx['approved_name']}")
        w.flow(ts, rec_ip, partner, 8443, size + 3300 + rb.randrange(0, 700), 410 + rb.randrange(0, 90),
               duration_s=max(4, size // 1_500_000))

    w.schedule(a0, _open)
    w.schedule(t_dump, _dump)
    w.schedule(t_send, _send)
    w.schedule(t_close, lambda ts: w.close_session(state["sess"], ts))
    outcomes.append({"kind": "approved_bulk_transfer", "host": "records", "actor_account": admin,
                     "t_start": t_dump, "t_end": t_send + timedelta(seconds=30),
                     "description": ("registry export made on the records server and sent to the partner gateway "
                                     "named in an approved change record")})


def _sim_maintenance(w: World, rb: random.Random, spec: dict[str, Any], admin: str, gui: str, t0: datetime,
                     outcomes: list[dict[str, Any]]) -> None:
    """Approved maintenance by the administrator: the legitimate counterparts of the four phase-two steps.

    forwarder stop/start  <-> stop_forwarder         (a collection gap with a recorded, approved cause)
    restore from backup   <-> timestomp              (old modification times with a recent change time)
    hop to the records server <-> second_host_session (an administrator session from the nurse workstation)
    touch-screen session  <-> clear_history          (records activity with no shell history; see caller)
    """
    benign = spec["benign"]
    m0, gap_s = _parse(benign["maintenance_start"]), benign["forwarder_gap_s"]
    ws_ip, day = IPS["workstation"], timedelta(days=1)
    t_stop = m0 + timedelta(seconds=45)
    t_start = t_stop + timedelta(seconds=1 + gap_s)
    t_restore = t_start + timedelta(seconds=50 + rb.randrange(0, 40))
    t_hop = t_restore + timedelta(seconds=60 + rb.randrange(0, 40))
    t_hop_end = t_hop + timedelta(seconds=120 + rb.randrange(0, 90))
    t_close = t_hop_end + timedelta(seconds=30 + rb.randrange(0, 60))
    state: dict[str, Any] = {}

    def _open(ts: datetime) -> None:
        state["sess"], _ = w.open_session("workstation", admin, ts, origin="remote", src_ip=IPS["admin-laptop"])

    def _stop(ts: datetime) -> None:
        _sudo(w, "workstation", admin, state["sess"].number, ts, "/usr/bin/systemctl stop log-forwarder")
        w.log("workstation", SYSLOG, ts, "systemd[1]", "Stopping log-forwarder.service...")
        w.stop_forwarding("workstation", ts + timedelta(seconds=1), t_start)

    def _start(ts: datetime) -> None:
        _sudo(w, "workstation", admin, state["sess"].number, ts, "/usr/bin/systemctl start log-forwarder")
        w.log("workstation", SYSLOG, ts + timedelta(seconds=1), "systemd[1]", "Started log-forwarder.service.")

    def _restore(ts: datetime) -> None:
        src = f"{EXTRA_NAMES['backup-nas']}:/backup/{HOSTNAMES['workstation']}/home/{gui}/Documents/"
        _sudo(w, "workstation", admin, state["sess"].number, ts, f"/usr/bin/rsync -a {src} /home/{gui}/Documents/")
        total = 0
        for i in range(3):
            size = 60_000 + rb.randrange(0, 240_000)
            total += size
            w.restore_file("workstation", f"/home/{gui}/Documents/census-10{20 + i}.csv", size, gui,
                           t0 - day * (12 - i) + _m(rb.randrange(0, 400)), ts + timedelta(seconds=2 + i))
        # the workstation pulls from the backup store: it is the client of this connection
        w.flow(ts + timedelta(seconds=1), ws_ip, IPS["backup-nas"], 873, 2400 + rb.randrange(0, 600), total + 5000, duration_s=3)

    def _hop(ts: datetime) -> None:
        w.history("workstation", admin, ts - timedelta(seconds=2), f"ssh {HOSTNAMES['records']}")
        s2, _ = w.open_session("records", admin, ts, origin="remote", src_ip=ws_ip)
        state["s2"] = s2
        for off, cmd in ((25, "df -h"), (60, "/usr/bin/systemctl status records-app")):
            if cmd.startswith("/"):
                w.schedule(ts + timedelta(seconds=off), lambda t2, cmd=cmd: _sudo(w, "records", admin, s2.number, t2, cmd))
            else:
                w.schedule(ts + timedelta(seconds=off), lambda t2, cmd=cmd: w.history("records", admin, t2, cmd))

    w.schedule(m0, _open)
    w.schedule(t_stop, _stop)
    w.schedule(t_start, _start)
    w.schedule(t_restore, _restore)
    w.schedule(t_hop, _hop)
    w.schedule(t_hop_end, lambda ts: w.close_session(state["s2"], ts))
    w.schedule(t_close, lambda ts: w.close_session(state["sess"], ts))
    outcomes += [
        {"kind": "approved_forwarder_stop", "host": "workstation", "actor_account": admin, "t_start": t_stop,
         "t_end": t_start, "description": "log forwarding stopped and restarted for maintenance under an approved change record"},
        {"kind": "restore_from_backup", "host": "workstation", "actor_account": admin, "t_start": t_restore,
         "t_end": t_restore + timedelta(seconds=6),
         "description": "documents restored from backup with their original modification times preserved"},
        {"kind": "approved_second_host_session", "host": "records", "actor_account": admin, "t_start": t_hop,
         "t_end": t_hop_end, "description": "administrator session on the records server opened from the nurse workstation under the change record"},
        {"kind": "touch_screen_session", "host": "workstation", "actor_account": gui, "t_start": m0 + timedelta(seconds=50),
         "t_end": m0 + timedelta(seconds=650), "description": "charting through the touch-screen client, which writes no shell history"},
    ]


def _sim_cold_chain(w: World, spec: dict[str, Any], outcomes: list[dict[str, Any]]) -> None:
    """The vaccine refrigerator: the hub's own stored readings and an independent reference logger.

    Both describe one simulated temperature. A real warming event (in two of the three variants) appears
    in both. The reference logger keeps its own clock and is not reachable from the hub.
    """
    cc, seed, variant = spec["coldchain"], spec["seed"], spec["variant"]
    rs = random.Random(f"alibi-sensor:{spec['scenario_version']}:{seed}:{variant}")
    lo, hi = SENSOR_RANGE_C
    w.sensor_range = SENSOR_RANGE_C
    w.reference_clock_offset_s = cc["reference_clock_offset_s"]
    cs, ce = w.capture_start, w.capture_end
    ex0, ex_min, peak = _parse(cc["excursion_start"]), cc["excursion_minutes"], cc["peak_c"]
    m_start = _parse(cc["maintenance_start"])
    m_end = m_start + _m(cc["maintenance_minutes"])
    offset = timedelta(seconds=cc["reference_clock_offset_s"])

    def true_temp(ts: datetime) -> float:
        temp = 4.6 + 0.6 * math.sin((ts - cs).total_seconds() / 540.0)  # compressor cycle
        if cc["has_excursion"]:
            x = (ts - ex0).total_seconds() / 60.0
            if 0 <= x <= ex_min + 12:
                rise = min(1.0, x / 6.0)
                fall = 1.0 if x <= ex_min else max(0.0, 1.0 - (x - ex_min) / 12.0)
                temp += (peak - 4.6) * rise * fall
        return temp

    state = {"calibrating": False}

    def _read(ts: datetime) -> None:
        if m_start <= ts < m_end:  # the hub's probe is in an ice bath for its calibration check
            rec = w.sensor_reading(SENSOR, ts, 0.1 + rs.randrange(0, 4) / 10, "calibration")
            state["calibrating"] = True
        else:
            temp = true_temp(ts) + rs.uniform(-0.15, 0.15)
            rec = w.sensor_reading(SENSOR, ts, temp, "ok" if lo <= round(temp, 1) <= hi else "alarm")
            if state["calibrating"]:
                rec["seq"] = 1  # the probe was reconnected: its counter starts again
                state["calibrating"] = False
        w._mqtt_mid += 1
        w.log("iot-hub", MQTT_LOG, ts, "mosquitto[410]",
              f"Received PUBLISH from {SENSOR} (q1, m{w._mqtt_mid}, 'clinic/coldchain/{SENSOR}/temp', "
              f"{len(w.sensor_line(rec))} bytes)")

    t = cs + timedelta(seconds=20)
    while t <= ce:
        w.schedule(t, _read)
        t += timedelta(seconds=SENSOR_INTERVAL_S)
    t = cs + timedelta(seconds=95)
    while t <= ce:
        w.schedule(t, lambda ts: w.reference_reading(REFERENCE_LOGGER, SENSOR, ts + offset,
                                                     true_temp(ts) + 0.2 + rs.uniform(-0.2, 0.2)))
        t += timedelta(seconds=REFERENCE_INTERVAL_S)

    outcomes.append({"kind": "sensor_maintenance", "host": "iot-hub", "actor_account": None, "t_start": m_start,
                     "t_end": m_end, "description": "scheduled ice-point calibration of the hub's probe (stated in the policy)"})
    outcomes.append({"kind": "reference_clock_offset", "host": "reference", "actor_account": None, "t_start": cs,
                     "t_end": ce, "description": f"the reference logger's clock differs from the hub by {cc['reference_clock_offset_s']} s"})
    if cc["has_excursion"]:
        outcomes.append({"kind": "temperature_excursion", "host": "iot-hub", "actor_account": None, "t_start": ex0,
                         "t_end": ex0 + _m(ex_min + 12),
                         "description": "the refrigerator door was left ajar during restocking: a real warming event"})
