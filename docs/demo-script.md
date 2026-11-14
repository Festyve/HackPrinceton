# Two-minute demo script (offline wording)

Draft for Terry and Rayan to edit. **Mode this script is written for:** evidence `SIM`, inference `Scripted fixture · no model inference`, playback `LIVE`. If a real model run exists by Sunday, swap the two marked lines. Do not narrate a fixture as AI.

## Before you start

```sh
./start.sh            # then open http://127.0.0.1:8000 in Chrome, 1280x720 or larger, 100% zoom
```

- Check the header: `Live AI: BLOCKED` (or `CONFIGURED` if the runtime was fixed) and no case open.
- Wi‑Fi is not needed. Nothing loads from the network.
- Measured on Eric's MacBook with the default pacing: evidence generated in 0.24 s, first finding on screen at about 3 s, report ready for review at about 11 s, accept and lock 0.5 s, unseal and score 0.1 s. The investigation itself computes in under a second; the rest is display pacing so the audience can follow.

## Script

| Time | Click | Say (gist) |
|---|---|---|
| 0:00–0:15 | Start screen visible | "An account shows up in a breach. Does that tell you who did it? ALIBI stages a synthetic incident in a simulated clinic network, seals what really happened, and asks an investigator to reconstruct it from the evidence." |
| 0:15–0:30 | Select **Inside job · cover-up**, press **Run** | "The adversary can only pick from four approved simulation steps. The investigator gets frozen, hashed evidence and a vague tip. It never sees the answer key." **[offline]** "Today the investigator is a scripted fixture: a real DeepAgents graph with the model swapped for scripted control flow. The label on screen says so." |
| 0:30–1:05 | Point at the right panel: the hatched row | "This is the host's own login log next to the central collector's copy. One line is missing on the host. The collector kept it: a session opened for this account. That same session is the only one open when 20 megabytes leave for an address that is not on the approved list." Click an evidence chip: "Every claim opens the raw record and its hash." |
| 1:05–1:20 | Point at the review bar and scroll to Attribution | "The account was used. The badge shows the account holder had left the building, which argues against them, but it does not tell us who was at the keyboard. So the report says: human operator not established." Press **Accept report**. |
| 1:20–1:40 | Press **Unseal answer key** | "Only now is the truth unsealed. Three of three executed effects caught, nothing unsupported. And here is an attempt that failed: the adversary tried to edit the collector and could not." |
| 1:40–1:55 | Close the overlay, open the **Benchmark** tab | "On twelve held-out simulated cases, a keyword recipe caught 16 of 20 effects and none of the four cover-ups, with 172 raw hits. The contradiction checks caught 20 of 20 with no false alerts on the benign controls. That is engineering, not AI: the AI rows are honestly marked not run." |
| 1:55–2:00 | Back to **Case** | "A proving ground for forensic investigators, with inspectable evidence and an answer key." |

## If something goes wrong

| Problem | Do this |
|---|---|
| The run does not reach review within 20 s | Press **Reset**, then choose **Recorded replays → Inside job · cover-up** and press **Run**. The playback badge reads `REPLAY`. Say "this is a recorded scripted run." |
| Red error banner (`FAILED`) | Press **Reset** in the banner and run again. |
| The page was refreshed | Nothing is lost. The case id is in the URL and the case reloads, including during review. |
| The server was restarted during review | Reload the page. The report is still awaiting review and Accept still works. |
| The port is busy | `./start.sh --port 8010` (the launcher says so if a port is taken; on Eric's machine another project already uses 8001) |
| Judge asks for another case | **Sealed control case**: nothing malicious happened, the report alleges nothing, the unseal says "No incident occurred". Good for "does it cry wolf?". |

## Ask box (if a judge wants to dig in)

Three predefined, cited explanations: *What links the missing line to this session?*, *Can you identify the person?*, *Why is the other gap not suspicious?* They are deterministic text, labeled as such. There is deliberately no free-text chat.

## Operator fallback switches

- `ALIBI_DEFAULT_RUNNER=deterministic ./start.sh` runs the checks without the agent graph (label: *Deterministic baseline · no model inference*).
- `ALIBI_DEMO_PACE_S=0.25 ./start.sh` speeds up the display pacing; `0` removes it.
