# Judge questions

**Where is the AI?**

The investigator. A real Claude model ran the DeepAgents graph, used evidence tools, delegated, wrote findings and paused for review. The committed recording and eight pilot reports document that. The incident itself is scripted. Replay is labeled Recorded AI run; it is not live inference.

**What does it find that keyword search misses?**

A line that is no longer in the local log. The collector retained a copy. Our fixed keyword recipe detected zero of four cover-ups; the comparison checks detected four. This is a comparison with that recipe, not a claim that existing forensic tools cannot compare logs.

**Does the model discover the missing line itself?**

The deterministic checks identify the discrepancy. The model uses those observations to investigate, explain alternatives and produce a cited report. The original pilot did not measure discovery without the checks; the next evaluation adds those arms.

**Why multiple agents?**

They separate collection/integrity work from skeptical review and produce an inspectable investigation. In our four-case pilot they did not improve accuracy and cost more. That result supports offering a faster single-agent mode; it does not support a claim that delegation wins.

**How do you know a finding is correct?**

We distinguish a valid citation, a supported modeled observation, and agreement with executed ground truth. The answer key is checked only after report lock. None of those establishes legal truth or human identity.

**Can the investigator read the answer key?**

Its tools do not expose it. It has no shell, arbitrary SQL, filesystem path or URL tool. Canary and hostile-tool tests check the boundary. This is a tested agent capability boundary, not an operating-system security claim.

**What about malicious instructions inside logs?**

Logs are untrusted data and render as text. Tool-boundary tests cover hostile content. A real model's behavior on injected evidence needs its own measured test; we do not infer that from a scripted test.

**Is synthetic evidence enough?**

It gives a reproducible answer key and controlled comparisons. It does not establish real-world performance. The independent capture work is designed to test the same pipeline on process-produced Linux artifacts, with its own provenance and controls.

**Could someone use this?**

Training teams can inspect how an investigator reached a conclusion. Builders can compare investigator configurations against the same sealed case. The source-removal experiment adds a practical question for log owners: which conclusions depend on keeping this witness?

**How much does it cost?**

The recorded demo costs no model calls. The first pilot cost approximately $0.50 for four single-agent runs and $1.30 for four specialist runs. New runtime costs must be measured on the selected model. The team has authorized $20 total across development and demonstration, tracked by a ledger that reserves before each call and keeps unknown outcomes at their worst case; Console billing remains authoritative.
