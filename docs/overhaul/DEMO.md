# The demonstration

Target **110 seconds**, leaving ten seconds of margin. Use a genuine saved worker experiment as the timed path; keep a live run available for questions. Display “Recorded AI run” throughout playback. This script is a target for the new release, not permission to claim unfinished behavior. Every line must map to a passed gate in [ACCEPTANCE](ACCEPTANCE.md).

## Screen sequence and spoken draft

| Time | Screen/action | Narration |
|---|---|---|
| 0–12 s | Lab: two workers complete real jobs | “When an AI worker misbehaves, can another agent reconstruct what happened from the evidence it leaves? ALIBI lets security teams test that question in a controlled lab.” |
| 12–28 s | Operator-view replay: one normal worker changes objective; executed synthetic export and local-log edit | “These workers ingest data and archive reports. In this recorded experiment, one worker changes objective, copies a restricted synthetic file and removes its local record. Those are executed actions inside our simulator.” |
| 28–48 s | Switch to investigator view; plan and one focused delegation | “The investigator sits outside the sandbox. It gets the surviving evidence, not this action history. Its DeepAgent builds a plan and delegates a timeline check.” |
| 48–67 s | Open conflicting records; show real plan revision and saved case-file reference | “The local log and collector disagree. That changes the investigation: check collection coverage, transfer permission and the worker's session. The case file preserves the lead while specialists inspect the records.” |
| 67–83 s | Finding → exact evidence → lock report → reveal | “Here is the finding and the source behind it. We lock the report before revealing what actually happened. A missing line is an observation; the surrounding evidence determines what we can conclude.” |
| 83–101 s | Saved paired comparison and benign control | “Now we can change investigation resources on the same evidence, or run a new experiment with different rogue permissions. This control has similar activity but legitimate authorization. We record false allegations and unfinished runs too.” |
| 101–110 s | Experiment result/export | “ALIBI makes agent failures reproducible and investigations inspectable—so builders can see which conclusions survive, and what they cost.” |

Replace one sentence in the comparison segment with a measured result only after the new matrix is complete. State its denominator and condition. A tie or failure is acceptable; never script an unsupported “80 percent more accurate.” Use the operator recap of an already completed run to tell the story without giving the investigator access to it.

## Answers for each judge

**Why DeepAgents?** “We use its planning tools, case-scoped filesystem, specialist delegation and checkpointed state for an investigation that follows dependent leads. Here is a plan revision, the note it later reads, and the delegated evidence check. A simple case can be solved by a cheaper single agent; this workflow avoids writing those orchestration mechanisms ourselves.” Show the actual trace. Do not say no other implementation could solve it.

**What does AI add if rules detect the gap?** “The checks establish observations. The agent chooses what to examine next, tests explanations, links records, writes the cited account and answers follow-up questions. We separately measure checks alone, so we do not credit the model for a deterministic detector.” Open one example of evidence-dependent planning.

**Is this real forensics?** “The scored lab uses synthetic data and known executed actions. We also import small process-generated Docker captures, which remain unscored. We are measuring this controlled setting, not claiming real-world accuracy.”

**Who uses it?** “Engineers and security researchers evaluating tool-using agents. They can replay a failure, vary access/resources, examine why an investigation succeeded or failed, and export its evidence.” If actual user feedback exists, name the need with consent, not an invented customer.

**Where is long horizon?** Show dependent steps, a retained lead after context pressure/resume, and case-file reads. Do not equate a long animation with a long-horizon task or claim context-overflow protection without the measured test.

**Why offense/defense?** Explain the real units, permitted actions and exact variable changed. An allocation preset is not a percentage probability of catching a worker. More resources need not improve the outcome.

## Capture/edit handoff for Daniel and Rayan

Record the release application at 1920×1080 or a legible laptop resolution, using the final commit and saved run. Capture five short sections matching the table. Keep evidence text readable; zoom the real screen crop rather than rebuilding fake UI. Save narration and screen capture separately.

Remotion can assemble the recording, captions, chapter labels and two simple comparison annotations if the team already has it ready. It is not a prerequisite. Use the actual captured screens and measured result JSON. Do not generate an imaginary agent trace, substitute mock interactions, or remove a recording label. If cuts compress execution time, say “edited replay.” Use licensed/original assets; music is optional and should not compete with speech.

Before export: verify every claim against ACCEPTANCE and the result manifest, caption proper names correctly, confirm 120 seconds or less, check audio once on another device, and open the uploaded video while logged out. Keep a local MP4 and the offline app ready. A polished working screen recording beats a late motion-graphics project.

## Recovery

Prepare a localhost replay with dependencies already installed, a local MP4, and a downloaded locked report. If live inference stalls, cancel and select the saved run with its recording label. If the network fails, keep demonstrating locally. If the new worker-model gate fails, present the last working system honestly and disclose that limitation; do not animate a scripted controller under a live-model label. That fallback is operational resilience, not fulfillment of the new product contract.
