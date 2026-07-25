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
- `src/hammerdb_scale/chart/` — the bundled Helm chart, the single source of truth
- `templates/`, `scripts/`, `Chart.yaml`, `values.yaml` — symlinks into the chart above
- `src/hammerdb_scale/runtime/` — execution backends (Kubernetes and container)
- `entrypoint.sh` — the in-container dispatcher that selects and runs a TCL script
- `Dockerfile`, `Dockerfile.oracle` — base image and Oracle Instant Client extension
- `hack/build-images.sh` — builds and verifies both images

### Things worth knowing

- The repo-root chart paths are symlinks, not copies. They used to be duplicates and
  had already drifted; `get_chart_path()` prefers the packaged copy, so a fix applied
  only at the repo root would never reach anyone installing from PyPI.
- The HammerDB version lives in `ARG HAMMERDB_VERSION` and flows through
  `HAMMERDB_HOME`. `entrypoint.sh` *searches* for its mounted scripts rather than
  requiring the chart's mountPath to match the image, because those are set by
  different artifacts and can always disagree.
- `DEFAULT_HAMMERDB_VERSION` is what this repo builds; `PUBLISHED_HAMMERDB_VERSION`
  is what the published images contain and drives the chart default. Move the latter
  only after pushing new images.
- Database support is gated in five places: the `DatabaseType` enum in
  `config/schema.py`, the `case` blocks in `entrypoint.sh`, the parser registry in
  `results/parsers.py`, the per-database TCL script directories, and the per-database
  ConfigMap template in the chart.
- The base image needs `libpq5` for PostgreSQL: HammerDB bundles Pgtcl but links the
  system libpq at runtime.
- Credentials go through a Kubernetes Secret by default (`kubernetes.use_secrets`),
  so they are not readable via `kubectl describe job`.

## Working preferences

- Do not use `sed` or shell scripts to edit config files. Use the Edit tool per file.
- Run `pytest tests/ -q` before declaring work done. The suite is fast (under a second).
