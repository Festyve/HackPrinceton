# Local verification

Run from the repository root after installing the locked Python and web dependencies:

```sh
npm --prefix web run build
.venv/bin/python -m pytest
.venv/bin/python web/evaluation/investigator_eval.py --output test-results/investigator-eval.json
.venv/bin/python web/evaluation/capture_walkthrough.py
```

The investigator evaluation compares the existing scripted policy running through the real DeepAgents graph with the keyword recipe on six development cases, including a validated failed attempt against an independent collector. It denies network connections, uses temporary evidence/sealed directories and reads truth only after locking reports. It validates reference validity, attribution abstention and no incident allegations for controls/failed interference. This is regression coverage, not a new AI accuracy benchmark. Official benchmark files and real-model recordings are untouched.

The capture script runs a temporary offline server and system Google Chrome at 1280×720 and 1440×900. It rejects external browser requests, checks JavaScript errors and captures seven states at each size: library, active investigation, review, raw mismatch, reveal, benign and incomplete collection. The fixtures it saves are development-only. No API key or paid runtime is used.
