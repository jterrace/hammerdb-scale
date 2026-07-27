# Usage Guide

## Installation

```bash
pip install hammerdb-scale
```

This installs the `hammerdb-scale` CLI globally, including the bundled Helm chart. You can run it from any directory.

Requires Python 3.10 or later, and one of the two backends:

- Container backend (recommended): podman or docker on the machine that will run the workers. No cluster, Helm, or kubectl needed.
- Kubernetes backend: Helm 3.x and kubectl on your `PATH`, plus a cluster accessible via your current `kubectl` context. Set `backend: kubernetes` in your config to use this path; see [CONFIGURATION.md](CONFIGURATION.md#running-on-kubernetes) for the full requirements.

For isolated installations, use [pipx](https://pipx.pypa.io/):

```bash
pipx install hammerdb-scale
```

For development:

```bash
git clone https://github.com/PureStorage-OpenConnect/hammerdb-scale.git
cd hammerdb-scale
pip install -e ".[dev]"
```

## Quick Start

```bash
# 1. Generate a config file (or use -i for a guided wizard)
hammerdb-scale init

# 2. Validate configuration and connectivity
hammerdb-scale validate

# 3. Build schema and run benchmark in one step
hammerdb-scale run --build --wait

# 4. Collect and view results
hammerdb-scale results

# 5. Generate HTML scorecard
hammerdb-scale report --open
```

## Commands

### `hammerdb-scale version`

Prints the CLI and Python versions, plus whichever backend tooling it finds installed: Helm and kubectl with the current Kubernetes context, and podman or docker if present.

### `hammerdb-scale init`

Interactive config generator. Prompts for deployment name, database type, benchmark, targets, and credentials. Writes a v2 YAML config file.

```bash
hammerdb-scale init                    # Default: hammerdb-scale.yaml
hammerdb-scale init -o my-config.yaml  # Custom output path
hammerdb-scale init --force            # Overwrite existing file
hammerdb-scale init -i                 # Guided wizard mode
```

#### Wizard Mode (`--interactive` / `-i`)

The `--interactive` flag launches a step-by-step guided wizard with a polished terminal UI:

```bash
hammerdb-scale init -i
```

The wizard walks through 6 steps:

1. **Deployment**: name your benchmark and choose where the workers run (podman, docker, or Kubernetes; it leads with whatever runtime it finds installed)
2. **Database & Benchmark**: select Oracle, SQL Server, or PostgreSQL, and TPC-C or TPC-H
3. **Database Targets**: enter hostnames or IPs, with auto-generated names like `db-01`
4. **Credentials**: database username and password, plus Oracle's service name and schema password where relevant
5. **Benchmark Parameters**: warehouses for TPC-C, or scale factor for TPC-H
6. **Infrastructure**: Kubernetes namespace, only asked if you chose that backend, and Pure Storage metrics

After the core steps, an optional Advanced Options prompt lets you configure virtual users, rampup and duration, and (on Kubernetes) pod resources. If declined, sensible defaults are used.

A Configuration Summary table is shown before writing, giving you a chance to review all values, with passwords masked, and confirm or cancel.

Both `init` and `init -i` produce identical YAML output. The wizard is purely a UX enhancement for the input experience.

### `hammerdb-scale validate`

Validates configuration through several layers: YAML syntax, schema validation, image and database type consistency, and database connectivity, an actual login test against every target. The remaining layers depend on `backend`. On Kubernetes, it also checks that Helm and kubectl are installed and that the current context can create Jobs, ConfigMaps, and Secrets in the target namespace. On the container backend, it checks that podman or docker is installed instead, and there is no cluster-access layer.

```bash
hammerdb-scale validate                     # Full validation
hammerdb-scale validate --skip-connectivity # Skip DB login test
hammerdb-scale validate -f config.yaml      # Explicit config
```

### `hammerdb-scale build`

Creates benchmark schema (tables, indexes) on all database targets. Starts one worker per target, either a local container or a Kubernetes Job depending on `backend`.

```bash
hammerdb-scale build --benchmark tprocc
hammerdb-scale build --benchmark tprocc --id my-test-001
hammerdb-scale build --wait              # Poll until all jobs complete
hammerdb-scale build --dry-run           # Render without deploying
```

`--benchmark` is optional if `default_benchmark` is set in your config.

### `hammerdb-scale run`

Executes the benchmark workload against all targets.

```bash
hammerdb-scale run --benchmark tprocc
hammerdb-scale run --build               # Build schema first, then run
hammerdb-scale run --wait                # Poll until completion
hammerdb-scale run --dry-run
```

With `--build`, the build phase must fully succeed before the run begins. This is the recommended workflow for new benchmarks.

### `hammerdb-scale status`

Shows current job status across all targets.

```bash
hammerdb-scale status                    # Most recent test
hammerdb-scale status --id <test-id>
hammerdb-scale status --watch            # Auto-refresh every 10s
hammerdb-scale status --json             # Machine-readable output
```

### `hammerdb-scale logs`

View HammerDB output logs from benchmark jobs.

```bash
hammerdb-scale logs                      # All targets, most recent test
hammerdb-scale logs --target ora-01      # Specific target
hammerdb-scale logs --follow             # Stream logs live
hammerdb-scale logs --tail 50            # Last 50 lines
```

### `hammerdb-scale results`

Aggregates results from worker logs, parses benchmark metrics, and saves to a local directory.

```bash
hammerdb-scale results
hammerdb-scale results --id <test-id>
hammerdb-scale results --json            # Machine-readable output
```

### `hammerdb-scale report`

Generates a self-contained HTML scorecard with charts and tables. All CSS and JavaScript are embedded, so the file can be opened in any browser, shared, or viewed offline.

```bash
hammerdb-scale report                    # Default: results/{test-id}/scorecard.html
hammerdb-scale report --open             # Open in browser
hammerdb-scale report -o report.html     # Custom output path
```

### `hammerdb-scale clean`

Removes benchmark resources.

```bash
# Remove workers: containers on the container backend, Helm releases and jobs on Kubernetes
hammerdb-scale clean --resources --id <test-id>
hammerdb-scale clean --resources --everything

# Drop database tables
hammerdb-scale clean --database --benchmark tprocc
hammerdb-scale clean --database --benchmark tprocc --target ora-01
hammerdb-scale clean --database --benchmark tprocc --dry-run

# Both
hammerdb-scale clean --resources --database --benchmark tprocc --id <test-id>

# Skip confirmation
hammerdb-scale clean --resources --everything --force
```

## Understanding Results

### Benchmark Metrics

**TPC-C** (Online Transaction Processing):

| Metric | What It Measures |
|--------|-----------------|
| **TPM** (Transactions Per Minute) | Total transaction throughput including all transaction types. Higher is better. |
| **NOPM** (New Orders Per Minute) | Throughput of the "New Order" transaction only. This is the TPC-C primary metric. Higher is better. |

**TPC-H** (Decision Support / Analytics):

| Metric | What It Measures |
|--------|-----------------|
| **QphH** (Queries Per Hour) | Composite metric reflecting how quickly the 22 standard TPC-H queries execute. Higher is better. |

### What to Expect

- TPM/NOPM scale roughly linearly with the number of database targets when storage is not the bottleneck.
- When storage saturates, adding more databases shows diminishing returns. That is the point of scale testing: finding where the curve bends.
- Per-target metrics should be roughly equal. Large variance suggests a configuration or resource imbalance.

### Output Directory

After running `results`, a directory is created at `./results/<test-id>/`:

```
results/my-benchmark-20250304-1200/
├── summary.json          # Aggregated metrics (TPM, NOPM, per-target breakdown)
├── ora-01.log            # HammerDB output log for target ora-01
├── ora-02.log            # HammerDB output log for target ora-02
├── ...                   # One log file per target
├── pure_metrics.json     # Pure Storage metrics (if enabled)
└── scorecard.html        # HTML report (after running `report`)
```

- **summary.json**: machine-readable results, containing per-target metrics, aggregate totals, and the config snapshot used for the test.
- **Target logs**: raw HammerDB output, useful for debugging failed targets or verifying benchmark parameters.
- **pure_metrics.json**: time-series storage metrics from the Pure Storage FlashArray (IOPS, latency, bandwidth).
- **scorecard.html**: self-contained HTML report that opens in any browser without a web server.

### Reading the Scorecard

The TPC-C scorecard opens with summary cards for total TPM, total NOPM, and the average TPM and NOPM per target, followed by a per-target table showing status, duration, TPM, and NOPM for each database. Distribution charts show TPM and NOPM per target as horizontal bars: even bars indicate balanced load, uneven bars suggest an issue with specific targets.

With `time_profile` enabled, which is the default, the scorecard also includes a transaction response time section: p50, p95, and p99 latency per transaction type, drawn from HammerDB's own reservoir sampling rather than bucketed estimates. If Pure Storage metrics are enabled, a storage performance section shows latency, IOPS, and bandwidth as time series over the course of the benchmark.

The TPC-H scorecard leads with the QphH summary, the composite query throughput metric, followed by a per-query timing table with average, minimum, and maximum execution time for each of the 22 TPC-H queries across targets, and a chart comparing query execution times.

## Pure Storage Metrics

When `storage_metrics.enabled: true` in your config, HammerDB-Scale collects performance metrics from a Pure Storage FlashArray during the benchmark run phase.

### Setup

1. Obtain an API token from your FlashArray (Settings > Users > API Tokens)
2. Add to your config:

```yaml
storage_metrics:
  enabled: true
  pure:
    host: "10.0.0.100"           # FlashArray management IP
    api_token: "your-api-token"  # REST API token
    volume: ""                   # Leave empty for array-level metrics
    poll_interval: 5             # Collection interval in seconds
    verify_ssl: false
```

### What's Collected

It collects read and write IOPS, read and write latency (average, P95, P99, in microseconds), read and write bandwidth (bytes per second), and queue depth (outstanding I/O requests).

Metrics come from the first target's worker only, to avoid duplicate API calls, and run as a background process for the duration of the benchmark.

### In the Report

The storage performance section of the scorecard shows summary cards with peak and average values, plus time-series line charts for latency, IOPS, and bandwidth over the duration of the test. Look for latency spikes or IOPS plateaus that correlate with benchmark load; those are where storage is the bottleneck rather than the database or the driver.

## Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Success |
| 1 | Fatal error |
| 2 | Partial failure (some targets failed) |

## Global Options

| Option | Description |
|--------|-------------|
| `-f, --file PATH` | Config file path |
| `-v, --verbose` | Verbose output |

## Troubleshooting

### `helm not found` or `kubectl not found`

These only matter on the Kubernetes backend. If you meant to use the container backend, check that `backend` in your config is set to `podman`, `docker`, or `container`, not left as the `kubernetes` default. Otherwise, install [Helm](https://helm.sh/docs/intro/install/) and [kubectl](https://kubernetes.io/docs/tasks/tools/), then ensure they're on your `PATH`. Run `hammerdb-scale version` to verify.

### No container runtime found

This is the container-backend equivalent of the error above. Install podman or docker, or switch `backend` to `kubernetes` if that's what you meant to use.

### SELinux denies the script mount (container backend)

On a host running SELinux, podman needs a `:z` relabel on the read-only script mount, which the CLI applies automatically when it detects SELinux is active. If detection is wrong for your setup, the container fails immediately with a permission-denied mount error. Confirm SELinux mode with `getenforce`, and file an issue if the automatic handling did not match it.

### Namespace doesn't exist (Kubernetes backend)

Create the namespace before running:

```bash
kubectl create namespace hammerdb
```

Or change the namespace in your config (`kubernetes.namespace`).

### Database connectivity failures during `validate`

- Verify the database host is reachable from where the workers actually run. From your workstation, `telnet <host> <port>` is a quick check, but on Kubernetes the workers may sit on a different network path; use `hammerdb-scale validate --from-cluster` to check from there instead.
- Check credentials are correct.
- For Oracle, ensure the listener is running and the service name matches your config.
- For MSSQL, if using `encrypt_connection: true`, the server must support TLS.

### Jobs stuck in Pending (Kubernetes backend)

Check pod events:

```bash
kubectl describe pod -n hammerdb -l hammerdb.io/test-id=<test-id>
```

Common causes: `ImagePullBackOff`, meaning the container image can't be pulled, so check the image name and registry access; or insufficient resources, in which case reduce `resources.requests` in your config or free up capacity on the cluster.

### Build jobs fail

```bash
hammerdb-scale logs --id <test-id>
```

Common causes: wrong credentials, so check `targets.defaults.username` and `password`; the database not reachable from where the worker actually runs, which on Kubernetes can differ from your workstation; for Oracle, a tablespace that doesn't exist, which needs creating before building; for MSSQL, a database name conflict, which `clean --database` resolves.

### Results show 0 TPM

- Ensure `driver: timed`, not `test`, in your TPC-C config.
- Ensure `duration` is long enough. Five minutes or more is a reasonable minimum.
- Check logs for errors: `hammerdb-scale logs --target <name>`.

### Partial failures (exit code 2)

Some targets completed but others failed. Run `hammerdb-scale results` to see which targets succeeded, then check logs for the failed ones individually:

```bash
hammerdb-scale logs --target <failed-target-name>
```
