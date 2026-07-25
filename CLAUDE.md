# CLAUDE.md — HammerDB-Scale

## Communication style

Andrew is the director on this project. Communicate at that level.

- Write in proper prose with correct punctuation. Full sentences, not fragments.
- Do not use em dashes. Use commas, colons, semicolons, or separate sentences instead.
- Lead with the answer or the recommendation, then supply the reasoning. Do not build up to a conclusion.
- Do not dump raw information. Synthesise it. If there are five findings, say which two matter and why.
- Give a clear recommendation when asked a decision question. Do not present a neutral menu of options and leave the choice hanging.
- Quantify effort and risk in concrete terms (days of work, files touched, what breaks) rather than vague labels.
- Flag genuine trade-offs and things that will bite later, but keep it brief and do not editorialise.
- Skip filler openings and closings. No "Great question", no "Let me know if you need anything else".
- Avoid heavy bold-and-bullet formatting where a short paragraph reads better.

## Project overview

HammerDB-Scale orchestrates parallel HammerDB database benchmarks across multiple
database instances at once. It is used mainly for storage platform validation:
proving how a Pure Storage FlashArray behaves when serving N database workloads
concurrently.

Current shape: a Python CLI (`hammerdb_scale`) that generates Helm values, deploys
one Kubernetes Job per database target, then collects and parses the job logs into
aggregated results and a self-contained HTML scorecard.

- `src/hammerdb_scale/` — the CLI package (see MEMORY.md for the module map)
- `src/hammerdb_scale/chart/` — the bundled Helm chart shipped inside the wheel
- `templates/`, `scripts/`, `Chart.yaml`, `values.yaml` — repo-root copies of the same chart
- `entrypoint.sh` — the in-container dispatcher that selects and runs a TCL script
- `dockerfile`, `Dockerfile.oracle` — base image and Oracle Instant Client extension

### Things worth knowing

- The repo-root chart files and `src/hammerdb_scale/chart/` are duplicates. Changes to
  TCL scripts or templates must be applied to both, or the packaged wheel drifts from
  the repo.
- HammerDB version is hardcoded as the path `/opt/HammerDB-5.0` in `entrypoint.sh`,
  the Dockerfiles, and the Helm job template `volumeMounts.mountPath`. All three must
  change together for a version bump.
- Database support is gated in four places: the `DatabaseType` enum in
  `config/schema.py`, the `case` blocks in `entrypoint.sh`, the parser registry in
  `results/parsers.py`, and the per-database TCL script directories.
- Credentials are currently passed as plain environment variables in the Job spec and
  are visible via `kubectl describe job`.

## Working preferences

- Do not use `sed` or shell scripts to edit config files. Use the Edit tool per file.
- Run `pytest tests/ -q` before declaring work done. The suite is fast (under a second).
