# HammerDB-Scale

[![PyPI version](https://img.shields.io/pypi/v/hammerdb-scale)](https://pypi.org/project/hammerdb-scale/)
[![Python versions](https://img.shields.io/pypi/pyversions/hammerdb-scale)](https://pypi.org/project/hammerdb-scale/)
[![License](https://img.shields.io/pypi/l/hammerdb-scale)](https://github.com/PureStorage-OpenConnect/hammerdb-scale/blob/main/LICENSE)

A Python CLI for orchestrating parallel HammerDB database benchmarks at scale.

## What is HammerDB-Scale?

HammerDB-Scale runs **synchronized database performance tests across multiple database instances simultaneously**, making it ideal for:

- **Storage Platform Testing**: Validate storage array performance under realistic multi-database workloads
- **Scale Testing**: Test how storage performs when serving 2, 4, 8+ databases concurrently
- **Capacity Planning**: Understand how many database workloads your storage can support

It runs one HammerDB container per database target. Those containers can run
on a single machine with podman or docker, or as Jobs on a Kubernetes cluster.
Most people should start with containers: there is nothing to install beyond a
container runtime, and the driver is light enough that one host comfortably
saturates a large fleet of databases.

## How It Works

```
hammerdb-scale CLI          +-----------+    +--------------+
 (your machine, or a        | HammerDB  |--->| Database 1   |
  host near the databases)  | worker 1  |    +--------------+
       |                    +-----------+
       |  deploy            +-----------+    +--------------+
       |------------------->| HammerDB  |--->| Database 2   |
       |                    | worker 2  |    +--------------+
       |  collect logs      +-----------+
       |<-------------------+-----------+    +--------------+
       |                    | HammerDB  |--->| Database N   |
       |  results/report    | worker N  |    +--------------+
       v                    +-----------+
   scorecard.html
```

1. You define your database targets and benchmark parameters in a YAML config file
2. The CLI starts one HammerDB worker per database target, as a local container or a Kubernetes Job
3. Each worker connects to its assigned database and executes the benchmark
4. All workers run in parallel, producing synchronized load across all targets
5. The CLI collects results, aggregates metrics (TPM/NOPM for TPC-C, QphH for TPC-H), and generates an HTML scorecard

### Where to run the workers

Put the driver host close to the databases. Driver-to-database latency counts
against your benchmark numbers, so running from a laptop over a VPN will make
your storage look slower than it is.

| You have | Use | Notes |
|---|---|---|
| A Linux host near the databases | `backend: podman` | Recommended. No cluster needed. |
| A laptop with Docker Desktop | `backend: docker` | Fine for smaller runs; mind the network path. |
| An existing Kubernetes cluster | `backend: kubernetes` | Schedules workers across nodes. |
| Databases spread across sites | `backend: kubernetes` | The container backend drives from one host only. |

A worker is a TCL process issuing SQL and waiting on the network, so it costs
very little: measured at roughly 57 MB and a fifth of a CPU core while driving
8 virtual users at ~100,000 TPM. Eight concurrent targets on one host used
under 500 MB in total.

## Quick Start

```bash
# Install
pip install hammerdb-scale

# Generate config interactively (asks where to run the workers)
hammerdb-scale init

# Check the config and that every database answers
hammerdb-scale validate

# Build schemas, run the benchmark, collect results
hammerdb-scale run --build --wait
hammerdb-scale results
hammerdb-scale report --open
```

A minimal config for two SQL Server targets on a machine with podman:

```yaml
name: storage-validation
backend: podman

targets:
  defaults:
    type: mssql
    username: sa
    password: "your-password"
  hosts:
    - name: sql-01
      host: 10.0.0.11
    - name: sql-02
      host: 10.0.0.12

hammerdb:
  tprocc:
    warehouses: 1000
    load_virtual_users: 8
    duration: 10
```

See [examples/](examples/) for complete configs per database.

**Budget time for the schema build.** It is a separate phase and it dominates
the wall clock: 100 warehouses takes minutes, 10,000 warehouses takes hours.
Build once, then run as many benchmarks against that schema as you like.

## Supported Databases

| Database | Benchmarks | Container Image |
|----------|-----------|-----------------|
| **SQL Server** | TPC-C, TPC-H | `sillidata/hammerdb-scale:latest` |
| **PostgreSQL** | TPC-C, TPC-H | `sillidata/hammerdb-scale:latest` |
| **Oracle** | TPC-C, TPC-H | build locally, see [Platform support](#platform-support) |

## Workflow

```
init  →  validate  →  run --build  →  results  →  report
 │          │             │              │           │
 │          │             │              │           └─ HTML scorecard
 │          │             │              └─ aggregate TPM/NOPM/QphH
 │          │             └─ build schema + run benchmark (one worker per target)
 │          └─ check config, tooling, DB connectivity
 └─ generate config interactively
```

## Commands

| Command | Description |
|---------|-------------|
| `version` | Show CLI, Python, helm, kubectl versions |
| `init` | Generate config file interactively |
| `validate` | Validate config, prerequisites, and connectivity |
| `build` | Create benchmark schema on database targets |
| `run` | Execute benchmark workload (`--build` for combined) |
| `status` | Show job status with `--watch` for live updates |
| `logs` | View HammerDB output logs |
| `results` | Aggregate and display benchmark results |
| `report` | Generate self-contained HTML scorecard |
| `clean` | Remove workers (containers or K8s jobs) and/or database tables |

## Documentation

- [Configuration Reference](https://github.com/PureStorage-OpenConnect/hammerdb-scale/blob/main/docs/CONFIGURATION.md) — YAML schema, target defaults, examples
- [Usage Guide](https://github.com/PureStorage-OpenConnect/hammerdb-scale/blob/main/docs/USAGE-GUIDE.md) — Command reference, results interpretation, troubleshooting
- [Container Images](https://github.com/PureStorage-OpenConnect/hammerdb-scale/blob/main/docs/CONTAINER-IMAGES.md) — Pre-built images, building your own, architecture
- [Migration Guide (v1 to v2)](https://github.com/PureStorage-OpenConnect/hammerdb-scale/blob/main/docs/MIGRATION.md) — Upgrading from shell-script version
- [Security](https://github.com/PureStorage-OpenConnect/hammerdb-scale/blob/main/docs/SECURITY.md) — Credential handling and network considerations
- [Changelog](https://github.com/PureStorage-OpenConnect/hammerdb-scale/blob/main/CHANGELOG.md)

## Requirements

- **Python 3.10+**
- **podman or docker**, either one. podman is preferred when both are present.
- **Database targets**, one or more Oracle, SQL Server or PostgreSQL instances reachable from the machine running the workers

That is the whole list for the default container backend. No cluster, no Helm,
no kubectl.

### Running on Kubernetes instead

Set `backend: kubernetes` in your config and add:

- **Helm 3.x**, used to template and deploy the Jobs
- **kubectl**, configured with a context that has access to your cluster
- **A cluster** with permissions to create Jobs, ConfigMaps and Secrets in your namespace
- Databases reachable **from the cluster**, which is not always the same as reachable from your workstation. `hammerdb-scale validate --from-cluster` checks from where the workers actually run.

### Platform support

| Platform | SQL Server | PostgreSQL | Oracle |
|---|---|---|---|
| Linux x86_64 (podman or docker) | Yes | Yes | Yes |
| Kubernetes on x86_64 nodes | Yes | Yes | Yes |
| macOS, Intel | Yes | Yes | Yes |
| macOS, Apple Silicon | Yes | Yes | **No** |
| Windows via WSL2 | Yes | Yes | Yes |

Oracle support requires Oracle Instant Client, which Oracle publishes for
linux.x64 only. There is no ARM64 build, so Oracle benchmarks cannot run on
Apple Silicon. SQL Server and PostgreSQL are unaffected.

Oracle also ships as a **separate image you build yourself**, because Oracle's
licence does not permit redistributing Instant Client:

```bash
git clone https://github.com/PureStorage-OpenConnect/hammerdb-scale
cd hammerdb-scale
./hack/build-images.sh          # builds base + Oracle, verifies both
```

By building it you accept [Oracle's licence terms](https://www.oracle.com/downloads/licenses/instant-client-lic.html).

### Optional

- [pipx](https://pipx.pypa.io/) — recommended for installing CLI tools in isolated environments: `pipx install hammerdb-scale`

## Configuration

See the [Configuration Reference](https://github.com/PureStorage-OpenConnect/hammerdb-scale/blob/main/docs/CONFIGURATION.md) for the full schema. Minimal example:

```yaml
name: my-benchmark
default_benchmark: tprocc

targets:
  defaults:
    type: mssql
    username: sa
    password: "YourPassword"
    mssql: {}
  hosts:
    - name: sql-01
      host: sql-01.example.com
    - name: sql-02
      host: sql-02.example.com

hammerdb:
  tprocc:
    warehouses: 100
    load_virtual_users: 4
    driver: timed
    rampup: 2
    duration: 5
```

Complete examples for all database/benchmark combinations are in the [examples/](https://github.com/PureStorage-OpenConnect/hammerdb-scale/tree/main/examples) directory.

## Contributing

Contributions are welcome! Please [open an issue](https://github.com/PureStorage-OpenConnect/hammerdb-scale/issues) to report bugs or request features.

## License

[Apache 2.0](https://github.com/PureStorage-OpenConnect/hammerdb-scale/blob/main/LICENSE)
