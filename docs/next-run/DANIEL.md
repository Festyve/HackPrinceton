# Daniel: real evidence and independent evaluation

Your job is to make ALIBI prove something outside its own simulator. You own a real Linux capture, its importer, and a hard-case test set. This is a separate technical deliverable, not general QA.

Read CONTRACTS.md. Work on codex/daniel-capture. Own capture/, src/alibi/capture/, tests/test_capture*.py, docs/capture.md and sanitized fixtures. Eric owns shared contracts, API and CLI; give him your entry point and any requested schema changes.

## 1. Capture a small, real process trail

Build a disposable local Docker Compose setup: an instrumented test service, a separate collector and, if needed, a local receiving service. Use synthetic records and dummy payloads only. A request must actually reach a process; the process must actually write a log; forwarding must actually reach the collector. Record sender and receipt timestamps and stable delivery IDs.

Use an internal Compose network. Pull/build images before the disconnected test. No privileged containers, host network, Docker socket mount, home-directory mount or arbitrary command endpoint. Agents receive evidence only; trusted fixture code drives fixed test operations. This is a controlled application-log capture, not a claim to emulate a complete enterprise or authentic PAM audit if you did not capture one.

Run three captures:

1. **Complete:** ordinary request sequence; local and collector copies agree.
2. **Missing local record:** once the collector acknowledges a designated test record, a trusted fixture mutates only the disposable local test log. Preserve the collector's independent bytes. Record what the fixture actually did in a sealed control log.
3. **Benign gap:** legitimate rotation or intentionally incomplete local collection with explicit coverage bounds. ALIBI must not label that proof of tampering.

Do not copy simulator output into containers and label it real Linux evidence. Do not write a synthetic collector record to match the desired finding.

A successful capture is a small directory of original raw files plus manifest, source coverage, hashes, UTC timing, image/tool versions and a private executed-action record. Keep public evidence separate from truth. Local deletion of a record is an observed test action; it does not establish a real criminal act.

## 2. Import it through ALIBI

Implement an importer that validates relative paths, hashes, sizes and source metadata, then normalizes bytes into the existing Event/ArtifactRef representation. Preserve original raw bytes, timestamps and unparsed lines. Extend parsing for the real format instead of rewriting the raw artifact to look simulated.

For a controlled capture, the trusted executed-action record can supply scoped ground truth. For an external dataset without an answer key, use an explicitly unscored imported case. Never invent truth to satisfy a schema.

Deliver an import function Eric can wire into the CLI, a tiny sanitized captured fixture in the repo, unit tests and the exact capture/import commands. Keep artifacts small enough for a fast fresh clone. Repeated real captures need not have identical timestamps/hashes; a frozen captured bundle must replay with identical bytes.

Acceptance: real capture happens; independent collector retains the removed record; every citation resolves; complete/control captures produce no false allegation; hashes verify; the fixture works without Docker or network after capture; source labels say DOCKER or HYBRID accurately.

## 3. Build cases that can expose mistakes

Write development fixtures first, then a separate declared evaluation set without inspecting the investigator's answers. Include:

- late-start local capture and missing prefix;
- duplicate or reordered collector delivery;
- clock skew/uncertain ordering;
- two overlapping sessions;
- approved bulk transfer;
- removed collector / removed badge;
- misleading instruction text inside a log, treated as data.

Specify expected **observations and uncertainty**, not a model's exact wording. Keep label/answer files on the evaluator side. Commit the evaluation manifest before the team runs it. If a result drives a rule change, use a new version and split; do not conceal the first result.

Supply the input bundle, expected structural property, relevant source assumptions and failure condition for each. Eric integrates these into the versioned evaluation harness.

## 4. IoT-CAD, after capture works

Use the NIST CFReDS catalog referenced by the packet; verify the actual dataset landing page and download destination. Record URL, retrieval date, license/use conditions, archive hash and selected file paths. Do not execute downloaded content. Enforce extraction path/size bounds.

Start with one relevant log/sensor subset, not an entire disk-image analysis pipeline. Map what the files actually contain. Unknown clocks, absent independent witnesses and absent truth remain explicit. An accessible dataset with no suitable evidence is not validation of the missing-line detector.

If an external download is inaccessible, spend at most 30 minutes diagnosing it, record the exact blocker, and finish the local-path importer and reproducible usage instructions. Continue your capture/control work; do not invent external results.

## 5. Handoff

First importer + fixture by Saturday 12:00; captured/control results by 15:00; integrated second-machine run by 19:00. Docker infrastructure gets at most 2.5 hours before delivering whatever captured slice works and the importer. Finish the smaller two-process collector experiment if a full range is consuming time.

Deliver docs/capture.md with commands, small fixture, provenance, test output, limitations, branch and commit. Run the final integrated demo on your own machine: install, recorded hero, benign control, citation, review, reveal, reset twice, network disconnected. Tell Rayan what an unfamiliar user could not understand.

## Paste into Daniel's agent

```text
Implement docs/next-run/DANIEL.md in this existing ALIBI repo. You own capture/, src/alibi/capture/, tests/test_capture*.py, docs/capture.md and sanitized fixtures. Read CONTRACTS.md; Eric owns shared schemas/API/CLI and Terry owns the UI. Create codex/daniel-capture without discarding work.

Build the small disposable Linux capture with independent collector receipts, one missing-local-record case and benign controls. Produce genuine process-generated artifacts, raw hashes, source coverage and an importer into the existing evidence schema. Do not relabel simulator output as real capture. Add independent hard cases and a declared evaluation manifest. All input data is synthetic or suitably licensed public data.

Use no paid model API. Preserve sealed truth and original bytes. Deliver a working captured fixture/importer early, then finish controls, optional relevant IoT-CAD ingestion, exact reproduction instructions and second-machine verification. Work autonomously, test the implementation, commit and push your branch, and give Eric the precise entry point and requested integration changes. Infrastructure timebox is 2.5 hours; feature freeze is Sunday Nov 15 00:00 America/New_York.
```
