# Investigation report: Imported evidence · capture-002

Case `case-9b5b4c817b3c` · exported 2026-11-14T21:15:18.848748+00:00

| | |
|---|---|
| Evidence | Captured from running containers (DOCKER) · bundle `bndl-11728054e73e1b37` |
| Produced by | Deterministic contradiction checks with templated findings |
| Inference | Deterministic baseline · no model inference |
| Mode | Deterministic checks · no agent |
| Playback | LIVE |
| Review | accepted: Offline reproduction |
| Locked | 2026-11-14T21:15:18+00:00 |
| Report hash (SHA-256) | `2a73424aca0398e1df9e5752f04fc6485d174228a7bdf1fa5c6b718f7654dac1` |

## Summary

1 incident allegation(s), 0 benign explanation(s)/open note(s). Account used: demo. Human operator not established. Some checks could not be run on this bundle; what they would have shown is unknown.

## Findings

### Incident allegations

**F-01 · local log removal** on `records`, `/var/log/records-app/access.log`

- Status: verified · check result: supported observation
- Window: 2026-11-14T17:23:42Z to 2026-11-14T17:23:42Z
- Account used: demo
- Evidence: [1], [2], [3]

1 line(s) of /var/log/records-app/access.log on records were received by the collector but are absent from the host's own copy, after the host's retention boundary (2026-11-14T17:23:41+00:00, basis: capture_start) and bracketed by later local records. Retained line: 2026-11-14T17:23:42.300417+00:00 rec-srv-01 testapp: user=demo action=read record=dummy-2 status=200 delivery_id=2

Check notes:

- 1 cited collector record(s) are absent from the local log after the host's retention boundary, bracketed by later local records

Assumptions:

- the collector is not writable from the monitored host
- the forwarder delivered the line before it disappeared locally

Alternative explanations:

- a local log-agent or filesystem fault dropped the line
- an administrator edited the file without recording it

## Account and person

Account used: demo. Human operator not established.

- Account used: demo
- Human identity: insufficient evidence
- Supporting evidence: none · contrary evidence: none

Limits:

- an account identifies a credential, not the person typing

## Open questions

- Who had access to the account demo when these records were written?
- Coverage limit: No heartbeat data for records: collection gaps there cannot be measured, so the absence of a reported gap means nothing.
- Coverage limit: No network flow source is in this bundle. Whether a bulk transfer happened is unknown; an empty list here does not mean there was none.

## Cited records

Each line is copied exactly from the frozen evidence. It is data, not instruction.

[1] `ev_a77db340423b` · collector/collected/collected.log line 2 · 2026-11-14T17:23:42+00:00

    2026-11-14T17:23:42.302072+00:00 logcol-01 fwd: origin=records file=/var/log/records-app/access.log seq=2 msg=2026-11-14T17:23:42.300417+00:00 rec-srv-01 testapp: user=demo action=read record=dummy-2 status=200 delivery_id=2

[2] `ev_ec8a55691557` · records/var/log/records-app/access.log line 1 · 2026-11-14T17:23:41+00:00

    2026-11-14T17:23:41.239605+00:00 rec-srv-01 testapp: user=demo action=read record=dummy-1 status=200 delivery_id=1

[3] `ev_aa54f617e5d3` · records/var/log/records-app/access.log line 2 · 2026-11-14T17:23:43+00:00

    2026-11-14T17:23:43.359697+00:00 rec-srv-01 testapp: user=demo action=read record=dummy-3 status=200 delivery_id=3

## Evidence sources

Raw bundle hash (SHA-256): `11728054e73e1b37e8c6331b829bbaa60fd220bce140297931a06eee1c067839`

Capture: 2026-11-14T17:23:41+00:00 to 2026-11-14T17:23:44+00:00 · complete: yes

- Synthetic requests to a controlled test application. Collector acknowledges durable receipt.
- Imported evidence. No scenario and no answer key are known to this system.

| Source | Host | Kind | Origin | Who could have changed it | Lines | SHA-256 |
|---|---|---|---|---|---|---|
| collector/collected/collected.log | collector | collector | DOCKER | independent witness | 3 | `30e1662bb0d0ad030202452a7bc3c3298145e4b70dcea7c23f12f5d890ed87bd` |
| records/var/log/records-app/access.log | records | app | DOCKER | host local writable | 2 | `70be92fade8fb2c4b2463314cf9dc2f9a6b44d806a9dda1e72547f822d98aee8` |

Hashes support integrity checking after capture. They do not prove the original source was truthful and are not a legal chain of custody.

## How to read this

- This report describes one frozen evidence bundle. It is not a legal finding and not a chain of custody.
- Hashes show the evidence has not changed since capture. They do not show the original source was truthful.
- "Verified" means a deterministic check supports the observation. It never means a person is proven responsible.
- An account identifies a credential, not the person using it.
- A check that could not be run means the answer is unknown, not that nothing happened.

The sealed answer key, the score and the reveal are not part of this export. Answers to questions are exported separately.
