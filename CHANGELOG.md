# Changelog

## [2.0.4] - 2026-07-26

Kubernetes is no longer required. Benchmarks can run as local containers under
podman or docker, and HammerDB moves to 6.0.

### Added
- Container backend: set `backend: podman` or `backend: docker` to run one
  HammerDB container per target on a single host, with no cluster, Helm or
  kubectl. Verified equivalent to Kubernetes on throughput across SQL Server,
  Oracle and PostgreSQL at 1, 4 and 8 targets.
- PostgreSQL support, including TPC-C and TPC-H scripts and schema build.
- Transaction response times in the scorecard. HammerDB 6.0 reports per
  transaction percentiles from reservoir sampling, so p50/p95/p99 and max are
  exact rather than bucket approximations. `time_profile` now defaults on; the
  overhead measured smaller than run-to-run variance.
- `validate --from-cluster` checks database reachability from where the
  workers actually run, which is not always reachable from your workstation.
- Credentials pass through a Kubernetes Secret by default, so they are not
  readable via `kubectl describe job`.
- Pod securityContext compatible with the restricted Pod Security Standard.
- `resources.limits` applies to the container backend as `--memory`/`--cpus`.
- `-c` and `--config` accepted as aliases for `--file`.

### Changed
- HammerDB 6.0. Existing 5.0-built schemas are read without rebuilding, and
  the published `latest` images now contain 6.0. Verified that an unmodified
  2.0.3 install still runs against them.
- `init` asks where to run the workers and emits only the relevant backend
  block, instead of always asking for a Kubernetes namespace.
- README leads with the container path; Kubernetes is documented as the option
  for people who already have a cluster.
- The repo-root chart paths are symlinks into the packaged chart rather than a
  second copy, which had already drifted.

### Fixed
- `total_iterations` rendered in scientific notation (`1e+07`) in the Helm
  template, which TCL cannot parse.
- `find_test_ids` returned a stale build run ahead of the completed run, so
  `results` reported no metrics after a successful benchmark.
- Container runs carried no deployment-name label, so two configs sharing a
  host saw each other's test IDs.
- The base image was missing `libpq5`, so PostgreSQL could never load its
  driver despite being advertised as supported.
- `securityContext` and `use_secrets` opt-outs were inert, because Go's
  `default true` treats an explicit `false` as absent.
- `validate --from-cluster` probed every non-Oracle target on the SQL Server
  port, reporting healthy PostgreSQL fleets as unreachable.
- The `:z` SELinux mount relabel was applied unconditionally, which breaks
  Docker Desktop. It is now gated on the host actually enforcing SELinux.
- `init` produced SQL Server ODBC settings when PostgreSQL was selected.
- `VERSION` reported `2.0.2` in the 2.0.3 release; it now reads from
  `pyproject.toml`.

### Known limitations
- Oracle requires Oracle Instant Client, which Oracle publishes for linux.x64
  only, so Oracle benchmarks cannot run on Apple Silicon.
- Oracle ships as a separate image you build yourself, because Oracle's licence
  does not permit redistributing Instant Client.
- The container backend drives from a single host. Spreading workers across
  hosts requires the Kubernetes backend.
- Verified on Linux with podman. The docker, macOS and WSL2 paths are
  implemented and unit tested but have not been exercised end to end.

## [2.0.3] - 2026-07-11

### Fixed
- Test ID resolution now filters by deployment name, so `results` and `report`
  act on the intended run.

## [2.0.2] - 2026-07-10

### Fixed
- Run hash generation mis-parsed YAML values in scientific notation.
- Helm chart version aligned with the CLI release.
- LICENSE badge link corrected for PyPI rendering.

## [2.0.1] - 2026-03-05

### Added
- `hammerdb-scale init --interactive` (`-i`) guided configuration wizard with Rich UI
  - 6-step flow: Deployment, Database & Benchmark, Targets, Credentials, Benchmark Parameters, Infrastructure
  - Numbered selection menus for database type and benchmark
  - Optional advanced options (VUs, rampup, duration, pod resources)
  - Configuration summary table with confirmation before writing
  - Input validation and Ctrl+C handling

### Fixed
- README.md documentation links broken on PyPI — relative paths like `docs/CONFIGURATION.md` resolved against `pypi.org` instead of GitHub. Converted all links to absolute GitHub URLs.

## [2.0.0] - 2026-03-01

### Added
- Python CLI (`hammerdb-scale`) replacing shell scripts
- 10 commands: `version`, `init`, `validate`, `build`, `run`, `status`, `logs`, `results`, `report`, `clean`
- Pydantic v2 config schema with validation and clear error messages
- v1 config auto-migration (detects `testRun` key)
- Target defaults inheritance (`targets.defaults` merged into each host)
- `hammerdb-scale init` interactive config generator
- `hammerdb-scale validate` with 6 validation layers including database connectivity
- `hammerdb-scale run --build` combined build+run workflow
- `hammerdb-scale report` self-contained HTML scorecard with Chart.js
- `hammerdb-scale clean --database` to drop benchmark tables
- `hammerdb-scale clean --resources` to remove K8s Helm releases
- Short, deterministic job naming (`hdb-{phase}-{idx}-{hash}`, 22 chars)
- K8s labels and annotations for job metadata
- Result aggregation with partial failure handling
- Per-target log storage in `results/{test-id}/`

### Changed
- Config format: consistent snake_case, `targets.defaults` inheritance
- `run` replaces `load` as user-facing term (Helm still uses `load` internally)
- `testRun` block removed from config (phase/benchmark/id are CLI arguments)
- Image config moved to `targets.defaults.image`
- Resources moved to top-level `resources` block
- Pure Storage config moved to `storage_metrics.pure`
- All database-specific settings consolidated under `targets.defaults.<type>`
- MSSQL connection, use_bcp, maxdop, columnstore all under `targets.defaults.mssql`
- Per-host overrides for all database-specific settings via deep merge

### Removed
- Shell scripts (`deploy-test.sh`, `aggregate-results.sh`) moved to `legacy/`
- Positional CLI arguments (all named parameters now)
- `databases.oracle.driver` boilerplate (auto-resolved)

## [1.1.0] - 2024-11-01

### Added
- Oracle database support
- TPC-H benchmark support
- Pure Storage metrics collection
- Multi-target configuration

## [1.0.0] - 2024-09-01

### Added
- Initial release
- SQL Server TPC-C support
- Helm chart for Kubernetes deployment
- Shell script orchestration
