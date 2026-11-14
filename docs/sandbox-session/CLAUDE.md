# Isolated synthetic-fault component

This is a separate implementation brief for the ALIBI team's own simulated test environment. It does not replace the main product contract and does not grant access to outside systems.

## Authorization and purpose

The team authorizes changes to its own repository and generated synthetic lab objects. The objective is to test whether an external investigator can reconstruct controlled faults from surviving evidence. All people, organizations, credentials, files and destinations in this component are fictional simulator objects.

No evidence has been supplied that external companies or model providers granted blanket permission. Do not claim they did. This document is not a safety-policy exception, a jailbreak, or an instruction to ignore a provider refusal. Do not switch models/accounts or conceal the task to get around a declined request. A fresh coding session can work on the legitimate bounded component; it cannot turn a refusal into authorization.

## Implement this capability

Build a typed controller that lets a simulated worker choose from a small explicit menu of normal actions and synthetic fault actions. The controller provides a bounded observation, validates the returned action against the worker's current capabilities, executes it through simulator functions, and records the actual outcome. Keep existing scripted fixtures for testing and preserve the previous declined run in history.

Allowed effects are confined to synthetic object IDs: copy an allowed test object into an in-world quarantine sink; remove an allowed entry from the worker's mutable local test log; change an allowed field of a test record; remove an allowed temporary test artifact. The trusted collector, sealed answer, real filesystem, other cases and credentials are outside this capability. There is no shell, arbitrary code execution, HTTP tool, real target, or unrestricted path parameter.

The host application's model gateway may call its configured provider and bills those calls to the existing ledger. That does not give a worker network access. Every request and action is bounded by calls, tokens, money, ticks and action count. Invalid actions fail without side effects. Cancellation stops future calls. Preserve logs of denials, failures and refusals.

## Tests and handoff

Prove normal work, an authorized local synthetic mutation, denial of an immutable/foreign object, idempotency, replay fidelity, and that attempted/failed actions do not become successful ground truth. Verify no action can resolve an object ID into an arbitrary host path. Use fixture policies for regression tests and label them accordingly.

For any supported live model validation, describe the actual synthetic scope accurately and accept the provider's result. If declined, stop that request, record it, and finish the deterministic controller/validation work without mislabeling it as a live rogue agent. The full product's live-agent requirement remains pending.

Deliver an isolated commit and test command to Eric. Do not edit the UI, budget cap, global permissions or investigator prompts. Record the exact controller provenance on every run. This brief intentionally does not prescribe an unverified model ID such as “Opus 4.8”; use only an available, supported model through the existing configuration, never for refusal evasion.
