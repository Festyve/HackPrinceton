# The integration owner's declared matrix

`protocol.json` was committed at `30d8375` as `benchmarks/worker-lab-v1/protocol.json` and run once at that commit (`20261114t212052z/`). It was moved here afterwards, unchanged, so that Daniel's independent protocol keeps the path `benchmarks/worker-lab-v1/protocol.json` and its digest.

Two things inside these files are wrong and are left as committed, because changing them would change the hashes the report cites:

- the suite name `worker-lab-v1`: this is not Daniel's `worker-lab-v1` protocol and uses different cases;
- the sentence that an independent protocol "had not arrived": Daniel pushed his to his own branch at 15:56 ET on November 14, twenty minutes before this one was declared. This session had not fetched it.

Read the results in [`docs/worker-lab-eric-matrix.md`](../../docs/worker-lab-eric-matrix.md). Re-check them with `uv run python scripts/read_lab_matrix.py`.
