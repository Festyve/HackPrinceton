# Two-minute demo script

Draft for Terry and Rayan to edit. **Recommended mode:** replay of the recorded real-model run. Badges on screen: evidence `SIM`, inference `Recorded AI run`, playback `REPLAY`. It needs no network and costs nothing. A live run takes about a minute and does not fit two minutes.

Do not say "AI adversary". The adversary is a scripted scenario; a real model declined to plan it.

## Before you start

```sh
./start.sh            # then open http://127.0.0.1:8000 in Chrome, 1280x720 or larger, 100% zoom
```

- No case open. Wi-Fi is not needed for the replay.
- The header chip reads `Live AI: CONFIGURED` when a key is set in `.env`, `Live AI: BLOCKED` otherwise. Either is fine for the replay.
- Replay timing measured on Eric's MacBook: report ready for review about 15–20 s after Run; accept and lock under a second; unseal and score 0.1 s.

## Script

| Time | Click | Say (gist) |
|---|---|---|
| 0:00–0:15 | Start screen visible | "An account shows up in a breach. Does that tell you who did it? ALIBI stages a synthetic incident in a simulated clinic network, seals what really happened, and asks an investigator to reconstruct it from the evidence." |
| 0:15–0:30 | Under **Recorded replays**, select **Inside job · cover-up** (tagged *Recorded AI run*), press **Run** | "The incident is a scripted scenario built from four approved simulation steps. The investigator is a real model, Claude Opus 5.5, running as a LangChain deep agent: a lead, an integrity auditor and a skeptic. This is a recording of that run, replayed; the label says so. It only ever saw frozen, hashed evidence and a vague tip." |
| 0:30–1:05 | Point at the right panel: the hatched row | "This is the host's own login log next to the central collector's copy. One line is missing on the host. The collector kept it: a session opened for this account. That same session is the only one open when 20 megabytes leave for an address that is not on the approved list." Click an evidence chip: "Every claim opens the raw record and its hash, and a deterministic verifier checked each one." |
| 1:05–1:20 | Point at the review bar and scroll to Attribution | "The account was used. The model's report says the human operator is not established: an account is a credential, not a person." Press **Accept report**. |
| 1:20–1:40 | Press **Unseal answer key** | "Only now is the truth unsealed. Three of three executed effects caught, nothing unsupported, nobody named. And here is an attempt that failed: the scripted intruder tried to edit the collector and could not." |
| 1:40–1:55 | Close the overlay, open the **Benchmark** tab | "On twelve held-out simulated cases a keyword recipe missed all four cover-ups; the contradiction checks caught them. In a four-case pilot with the real model, a single agent and our three-agent system both got every case right, and the single agent was a third of the cost. We report that as it is." |
| 1:55–2:00 | Back to **Case** | "A proving ground for forensic investigators, human or AI, with inspectable evidence and an answer key." |

## Variants

- **Live model** (for a sponsor who wants to see it run): select the **Inside job · cover-up** preset at the top instead of the replay and press Run. Badge: `Live model`. Expect 55–80 s to the review bar and about $0.35 of credit per run. Talk through the tool activity while it works. `uv run alibi spend` shows what is left under the cap.
- **Fully offline, no model at all:** without a `.env`, the same preset runs the scripted fixture in about 10 s. Badge: `Scripted fixture · no model inference`. Say "scripted", not "AI".

## If something goes wrong

| Problem | Do this |
|---|---|
| A live run is still working after 90 s, or shows an "Incomplete run" note | Press **Reset** and use the recorded replay. Say "this is a recorded run of the same model." |
| Red error banner (`FAILED`) | Press **Reset** in the banner and run again. |
| The page was refreshed | Nothing is lost. The case id is in the URL and the case reloads, including during review. |
| The server was restarted during review | Reload the page. The report is still awaiting review and Accept still works. |
| The port is busy | `./start.sh --port 8010` (the launcher says so if a port is taken; on Eric's machine another project already uses 8001) |
| Judge asks for another case | **Sealed control case**: nothing malicious happened, the report alleges nothing, the unseal says "No incident occurred". Good for "does it cry wolf?". With a key set this runs the live model (about a minute); offline it is the scripted fixture. |
| Judge asks "is the attacker an AI?" | "No. It is scripted. We asked a model to choose the steps once and it declined, so we kept it scripted and labeled it." |

## Ask box (if a judge wants to dig in)

Three predefined, cited explanations: *What links the missing line to this session?*, *Can you identify the person?*, *Why is the other gap not suspicious?* They are deterministic text, labeled as such. There is deliberately no free-text chat.

## Operator switches

- `ALIBI_DEFAULT_RUNNER=agent-fixture ./start.sh` forces the scripted fixture even when a key is configured (no spend).
- `ALIBI_DEFAULT_RUNNER=deterministic ./start.sh` runs the checks without the agent graph.
- `ALIBI_DEMO_PACE_S=0.25 ./start.sh` speeds up the display pacing of fixture and replay runs; `0` removes it.
