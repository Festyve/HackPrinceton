# Claims register

Each public claim, what supports it, its limitation and its status. Numbers come from saved runs. Nothing here is a target or a projection.

| # | Claim | Support | Limitation | Status |
|---|---|---|---|---|
| 1 | Executing a simulated incident records what actually happened, including failed attempts | `tests/test_m1_sim.py::test_every_executed_step_outcome_is_recorded_including_failures`; `uv run alibi steps <id>` | Ground truth of a simulation, not of a real network | Demonstrated |
| 2 | The same simulator version, scenario and seed reproduce byte-identical raw evidence | `uv run alibi verify <id>`; `test_saved_scenario_reproduces_the_frozen_bundle_hash` | The derived DuckDB file and run ids are not part of this guarantee | Demonstrated |
| 3 | A host log line removed by the adversary is recovered from the collector's copy, with bracketing local records | `tests/test_m2_checks.py::test_recovers_the_line_the_collector_retained`; hero case in the UI | Requires the forwarder to have shipped the line before removal; modeled world only | Demonstrated (SIM) |
| 4 | Legitimate log rotation, a forced second rotation, approved bulk transfers, remote logins and collection gaps are not reported as incidents | `tests/test_m2_checks.py` benign tests; benchmark T09–T12: BR 0/4 benign final false alerts | Four control types, one seed each in the test split | Demonstrated (SIM) |
| 5 | The report separates the account used from the human operator and names no one | `test_presence_check_never_names_or_clears_a_person`; attribution panel | In the P0 world no scenario supports naming a person, so correct naming is untested | Demonstrated (SIM) |
| 6 | On the declared 12-case offline suite the keyword baseline B0 caught 16/20 scorable effects and 0/4 cover-ups; the rule-based baseline BR caught 20/20 and 4/4 | `benchmarks/offline-v1/results.json`, `docs/benchmark.md`, locked reports in `benchmarks/offline-v1/reports/` | n = 12, simulated, checks developed against this simulator; descriptive only | Measured |
| 7 | B0 raised 172 raw allegations of which 16 were correct; the shared verifier accepted exactly those 16 | Same results file (`proposal_precision` 16/172, `final_precision` 16/16) | The verifier embeds the same policy knowledge BR uses | Measured |
| 8 | Fabricated citations, duplicates, wrong-host, wrong-object and episode-wide claims earn no credit | `tests/test_m2_verifier_scorer.py` | Fixture tests | Demonstrated |
| 9 | The investigator side cannot reach the answer key, a shell, SQL or the filesystem through its tools | `tests/test_m3_agents.py` (tool audit, hostile attempts, canary), `tests/test_m4_api_isolation.py` | Agent capability boundary, not OS isolation | Demonstrated |
| 10 | Reveal is refused until the report is locked; truth is absent from every pre-reveal response and stream | `test_reveal_is_refused_until_the_report_is_locked`, `test_no_truth_before_reveal_in_any_response_stream_or_case_file` | — | Demonstrated |
| 11 | A real DeepAgents graph (lead, integrity-auditor, skeptic) runs with delegation, todos, case notes, a review interrupt and checkpoint resume | `tests/test_m3_agents.py::test_fixture_graph_delegates_keeps_notes_and_pauses_for_review`, `test_review_interrupt_resumes_in_a_fresh_runner_and_cannot_rerun` | **Driven by a scripted policy, not a model.** This is plumbing evidence only | Demonstrated with a fixture |
| 12 | An AI investigator reconstructs incidents / delegation helps / the adversary is model-planned | None | No zero-charge model runtime was available | **BLOCKED: not demonstrated** |
| 13 | The demo runs with no network and no key; recorded runs replay with their provenance label | `tests/test_m7_demo.py`, `test_offline_run_opens_no_network_connection_and_builds_no_live_model` | Recordings are scripted fixtures | Demonstrated |
| 14 | The case board completes run → review → lock → reveal → reset in a real browser at 1280×720 | `tests/test_browser.py` (8 tests, headless Chrome) | Not tested on the venue projector | Demonstrated locally |
| 15 | Paid model spend so far is $0 and model calls are 0 | `benchmarks/offline-v1/results.json` (`runtime.model_calls_made`), default settings | — | True as of the handoff |
| 16 | Real Linux artifacts / Docker range / IoT-CAD validation | None | Not built, not downloaded | **Not claimed** |

Wording to avoid until item 12 changes: "AI investigator", "AI adversary", "the agent found", "multi-agent beats single-agent", any latency or token figure for a model.
