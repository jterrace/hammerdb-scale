# Container Images

HammerDB-Scale runs one container per database target, using pre-built container images. Each container connects to a single database target, executes the benchmark, and writes its results to log output. Depending on `backend` in your config, that container runs as a plain podman or docker container on a local host, or as a Kubernetes Job.

## Pre-Built Images

| Image | Covers | Source |
|-------|--------|--------|
| `sillidata/hammerdb-scale:latest` | SQL Server, PostgreSQL | [Dockerfile](../Dockerfile) |
| `sillidata/hammerdb-scale-oracle:latest` | Oracle | [Dockerfile.oracle](../Dockerfile.oracle) |

These images are hosted on Docker Hub and can be pulled without authentication.

## What's Inside

Both images include:

- Ubuntu 24.04 base
- HammerDB 6.0, the benchmark engine
- Python 3, for the Pure Storage metrics collector
- `entrypoint.sh`, an orchestration script that receives configuration via environment variables, runs HammerDB, and manages metrics collection

The base image (`sillidata/hammerdb-scale`) covers SQL Server and PostgreSQL targets. It includes Microsoft ODBC Driver 18 for SQL Server, `mssql-tools18` (including `bcp` for bulk data loading), and `libpq5` with `postgresql-client` for PostgreSQL. HammerDB bundles Pgtcl but links the system `libpq` at runtime, so `libpq5` has to be present even though HammerDB never calls `psql` directly.

The Oracle image extends the base image and adds Oracle Instant Client 21.11 (Basic and SQL*Plus) and the shared libraries HammerDB's Oratcl interface needs.

## Building Your Own Images

The Oracle image extends the base image, and `Dockerfile.oracle` defaults to pulling the published base from Docker Hub rather than the one you just built locally. `hack/build-images.sh` builds both in the correct order, wires the base image explicitly, and verifies the result:

```bash
git clone https://github.com/PureStorage-OpenConnect/hammerdb-scale
cd hammerdb-scale
./hack/build-images.sh
```

To build manually instead, build the base image first, then pass it to the Oracle build explicitly:

```bash
docker build -f Dockerfile -t my-org/hammerdb-scale:latest .
docker build -f Dockerfile.oracle -t my-org/hammerdb-scale-oracle:latest \
  --build-arg BASE_IMAGE=my-org/hammerdb-scale:latest .
```

Building the Oracle image downloads Oracle Instant Client from Oracle's servers. By building and using this image, you accept the [Oracle Technology Network License Agreement](https://www.oracle.com/downloads/licenses/instant-client-lic.html).

### Using Custom Images

Update `targets.defaults.image` in your config to point to your image:

```yaml
targets:
  defaults:
    image:
      repository: my-org/hammerdb-scale-oracle
      tag: v2.0.0
      pull_policy: Always
```

On Kubernetes, make sure the cluster can pull from your registry (configure `imagePullSecrets` if needed). On the container backend, make sure the local podman or docker daemon can pull from it, or has the image already loaded.

## Image Architecture

```
entrypoint.sh (container startup)
     │
     ├── Validates environment variables
     ├── Selects TCL script based on DATABASE_TYPE + BENCHMARK + PHASE
     ├── Runs: hammerdbcli auto <script>
     ├── [If Pure Storage enabled] Spawns collect_pure_metrics.py as background process
     └── Writes metadata.json with results and timing
```

This is the same for both backends. The CLI never connects to the container directly; all configuration passes through environment variables, and results are read back from the container's log output, either with `kubectl logs` on Kubernetes or the container runtime's own log command on the container backend.

## Environment Variables

These environment variables are set on each container, either by the Helm chart (Kubernetes backend) or directly by the CLI (container backend). You don't need to set them manually; they're populated from your config file automatically.

| Variable | Description |
|----------|-------------|
| `RUN_MODE` | `build` or `load` |
| `BENCHMARK` | `tprocc` or `tproch` |
| `DATABASE_TYPE` | `mssql`, `postgres`, or `oracle` |
| `HOST` | Database hostname |
| `USERNAME` | Database admin user |
| `PASSWORD` | Database admin password |
| `TARGET_NAME` | Target identifier from config |
| `TARGET_INDEX` | 0-based index of this target |
| `TEST_RUN_ID` | Test run identifier |

Additional database-specific and benchmark-specific variables are documented in the [Helm template](../templates/job-hammerdb-worker.yaml), which both backends draw from for the variable set.
