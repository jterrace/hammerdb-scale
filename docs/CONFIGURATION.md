# Configuration Reference

HammerDB-Scale uses a YAML config file to define database targets and benchmark parameters.

## Minimal Example

The smallest valid config: two SQL Server targets running TPC-C on a machine with podman.

```yaml
name: my-benchmark
backend: podman
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

Everything else has sensible defaults.

### Running on Kubernetes

Omit `backend` to run on Kubernetes instead; it is the default. The same config works, minus the `backend` line, but the `kubernetes` and `resources` sections now apply:

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

resources:
  requests:
    memory: "4Gi"
    cpu: "4"
  limits:
    memory: "8Gi"
    cpu: "8"

kubernetes:
  namespace: hammerdb
  job_ttl: 86400
```

This needs Helm, kubectl, and a cluster context with permission to create Jobs, ConfigMaps, and Secrets in the target namespace. See the README's [Running on Kubernetes instead](../README.md#running-on-kubernetes-instead) section for the full requirements.

For complete examples covering all database and benchmark combinations, see the [examples/](../examples/) directory.

## Config File Discovery

The CLI looks for the config file in this order:

1. `-f / --file` argument
2. `HAMMERDB_SCALE_CONFIG` environment variable
3. `hammerdb-scale.yaml` in the current directory
4. `hammerdb-scale.yml` in the current directory

## Schema Overview

A config file has seven top-level sections:

| Section | Purpose |
|---------|---------|
| `backend` | Where workers run: `kubernetes` (default), `podman`, `docker`, or `container` to auto-detect podman or docker |
| `targets` | Where to benchmark: database hosts, credentials, and database-specific settings |
| `hammerdb` | How to benchmark: shared benchmark parameters (warehouses, VUs, duration) |
| `resources` | Memory and CPU limits, applied as Kubernetes pod resources or as `--memory`/`--cpus` on the container backend. `requests` is Kubernetes-only |
| `kubernetes` | Namespace and job TTL settings. Ignored for `podman`/`docker`/`container` backends |
| `container` | Runtime selection and network settings for the `podman`/`docker`/`container` backends. Ignored on Kubernetes |
| `storage_metrics` | Optional Pure Storage metrics collection |

All database-specific settings live under `targets.defaults.<type>`, not under `hammerdb`. The `hammerdb` section contains only shared benchmark parameters that apply regardless of database type. This makes every database-specific setting overridable per-host.

## Complete Field Reference

### Top-Level Fields

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `name` | string | yes | | Deployment identifier. Used in job names and test run IDs. |
| `description` | string | no | `""` | Optional description for this benchmark configuration. |
| `default_benchmark` | string | no | `null` | Default benchmark type when not specified on the CLI. Valid values: `tprocc`, `tproch`. |
| `backend` | string | no | `"kubernetes"` | Where workers run. Valid values: `kubernetes`, `podman`, `docker`, `container` (auto-detect podman or docker). |

### `targets`

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `targets.defaults` | object | yes | Default settings inherited by all hosts. |
| `targets.hosts` | list | yes | One or more database hosts to benchmark. Minimum 1 entry. |

### `targets.defaults`

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `type` | string | yes | | Database type: `oracle`, `mssql`, or `postgres`. |
| `username` | string | yes | | Database login username. Typical values: `system` (Oracle), `sa` (MSSQL). |
| `password` | string | yes | | Database login password. |
| `image.repository` | string | no | `"sillidata/hammerdb-scale"` | Container image repository. Use `sillidata/hammerdb-scale-oracle` for Oracle targets. |
| `image.tag` | string | no | `"latest"` | Image tag. |
| `image.pull_policy` | string | no | `"Always"` | K8s image pull policy: `Always`, `IfNotPresent`, or `Never`. |
| `oracle` | object | conditional | | Oracle-specific settings. **Required** when `type: oracle`. |
| `mssql` | object | conditional | | MSSQL-specific settings. **Required** when `type: mssql`. |
| `postgres` | object | conditional | | PostgreSQL-specific settings. **Required** when `type: postgres`. |

### `targets.defaults.oracle`

All fields are per-host overridable.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `service` | string | `"ORCLPDB"` | Oracle service name (PDB name for multitenant). |
| `port` | int | `1521` | Oracle listener port. Range: 1-65535. |
| `tablespace` | string | `"TPCC"` | Tablespace for benchmark schema objects. |
| `temp_tablespace` | string | `"TEMP"` | Temporary tablespace for sort/hash operations. |
| `tprocc.user` | string | `"TPCC"` | Schema owner for TPC-C benchmark objects. |
| `tprocc.password` | string | `""` | Password for the TPC-C schema user. |
| `tproch.user` | string | `"tpch"` | Schema owner for TPC-H benchmark objects. |
| `tproch.password` | string | `""` | Password for the TPC-H schema user. |
| `tproch.degree_of_parallel` | int | `8` | Oracle parallel query degree for TPC-H queries. Min: 1. |

### `targets.defaults.mssql`

All fields are per-host overridable.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `port` | int | `1433` | SQL Server listener port. Range: 1-65535. |
| `connection.tcp` | bool | `true` | Use TCP/IP connection protocol. |
| `connection.authentication` | string | `"sql"` | Authentication mode: `sql` or `windows`. |
| `connection.odbc_driver` | string | `"ODBC Driver 18 for SQL Server"` | ODBC driver name used by HammerDB. |
| `connection.encrypt_connection` | bool | `true` | Enable TLS encryption for the connection. |
| `connection.trust_server_cert` | bool | `true` | Trust the server certificate without validation. Set to `false` in production with proper CA certificates. |
| `tprocc.database_name` | string | `"tpcc"` | Database name for TPC-C benchmark. |
| `tprocc.use_bcp` | bool | `false` | Use SQL Server Bulk Copy Program for data loading. Faster but requires BCP utility in the container. |
| `tproch.database_name` | string | `"tpch"` | Database name for TPC-H benchmark. |
| `tproch.maxdop` | int | `2` | Maximum degree of parallelism for TPC-H queries. Min: 1. |
| `tproch.use_clustered_columnstore` | bool | `false` | Use clustered columnstore indexes for TPC-H tables. Improves analytical query performance at the cost of longer build times. |

### `targets.defaults.postgres`

All fields are per-host overridable.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `port` | int | `5432` | PostgreSQL listener port. Range: 1-65535. |
| `sslmode` | string | `"prefer"` | TLS mode: `prefer`, `require`, or `disable`. |
| `tablespace` | string | `""` | Tablespace for benchmark schema objects. Empty uses the default tablespace. |
| `tprocc.database_name` | string | `"tpcc"` | Database created during the schema build. |
| `tprocc.user` | string | `"tpcc"` | Schema owner, created during the schema build. |
| `tprocc.password` | string | `"tpcc"` | Password for the TPC-C schema user. |
| `tprocc.stored_procedures` | bool | `true` | Use stored procedures for the TPC-C driver. HammerDB's recommended setting; must match between build and run, since the driver calls procedures that only exist if the schema was built with them. |
| `tprocc.partition` | bool | `false` | Partition TPC-C tables during the schema build. |
| `tprocc.vacuum` | bool | `false` | Run `VACUUM` after the schema build. |
| `tproch.database_name` | string | `"tpch"` | Database created during the schema build. |
| `tproch.user` | string | `"tpch"` | Schema owner, created during the schema build. |
| `tproch.password` | string | `"tpch"` | Password for the TPC-H schema user. |
| `tproch.max_parallel_workers` | int | `8` | Degree of parallelism for the TPC-H query phase. Min: 1. |

### `targets.hosts[]`

Each host inherits all fields from `targets.defaults`. Any field can be overridden per-host, including nested fields under `oracle`, `mssql`, or `postgres`.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | string | yes | Unique identifier for this host. Used in job names. |
| `host` | string | yes | Hostname or IP address of the database server. |
| All `targets.defaults` fields | | no | Any field from defaults can be overridden here. |

### `hammerdb`

Shared benchmark parameters. These apply to all database types. **No database-specific settings belong here.**

### `hammerdb.tprocc`

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `warehouses` | int | `100` | Number of TPC-C warehouses. Primary scale factor. Each warehouse is approximately 100 MB of data. Min: 1. |
| `build_virtual_users` | int | `4` | Number of virtual users for the schema build phase. Min: 1. |
| `load_virtual_users` | int | `4` | Number of virtual users for the benchmark run phase. Min: 1. |
| `driver` | string | `"timed"` | Test driver mode. `timed` runs for a fixed duration. `test` runs for a fixed iteration count. |
| `rampup` | int | `5` | Ramp-up time in minutes before measurement begins. Min: 0. |
| `duration` | int | `10` | Test duration in minutes (when driver is `timed`). Min: 1. |
| `total_iterations` | int | `10000000` | Maximum transactions per virtual user (when driver is `test`). Min: 1. |
| `all_warehouses` | bool | `true` | When `true`, each virtual user accesses all warehouses. When `false`, warehouses are partitioned across virtual users. |
| `checkpoint` | bool | `true` | Execute a database checkpoint before the timed test begins. Ensures a clean buffer state. |
| `time_profile` | bool | `false` | Enable per-transaction timing breakdown. Adds overhead; use for diagnostics only. |

### `hammerdb.tproch`

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `scale_factor` | int | `1` | TPC-H scale factor in GB. Determines data volume (1 = 1 GB, 10 = 10 GB, etc.). Min: 1. |
| `build_threads` | int | `4` | Number of threads for parallel data generation during build. Min: 1. |
| `build_virtual_users` | int | `1` | Number of virtual users for the build phase. Min: 1. |
| `load_virtual_users` | int | `1` | Number of virtual users for the query execution phase. Min: 1. |
| `total_querysets` | int | `1` | Number of complete TPC-H query set iterations to execute. Min: 1. |

### `container`

Only used when `backend` is `podman`, `docker`, or `container`. Ignored on Kubernetes.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `runtime` | string | `"auto"` | Which container runtime to use: `auto` (prefers podman if both are present), `podman`, or `docker`. Only meaningful when `backend: container`; the `podman` and `docker` backend values already pick the runtime directly. |
| `network` | string | `null` | Container network name. `null` uses the runtime's default network. |

### `resources`

`limits` applies to both backends: Kubernetes pod resource limits, or `--memory`/`--cpus` on the podman/docker container. `requests` only has a Kubernetes equivalent and is ignored on the container backend.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `requests.memory` | string | `"4Gi"` | Minimum memory reservation. Kubernetes only. |
| `requests.cpu` | string | `"4"` | Minimum CPU reservation. Kubernetes only. |
| `limits.memory` | string | `"8Gi"` | Maximum memory limit. Both backends. |
| `limits.cpu` | string | `"8"` | Maximum CPU limit. Both backends. |

### `kubernetes`

Only used when `backend` is `kubernetes`. Ignored for `podman`, `docker`, and `container` backends.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `namespace` | string | `"hammerdb"` | Kubernetes namespace for benchmark jobs. |
| `job_ttl` | int | `86400` | Time-to-live in seconds for completed jobs. Default is 24 hours. Min: 0. |
| `security_context` | bool | `true` | Emit a restricted-compliant `securityContext` on the job pods. Needed on clusters enforcing the restricted Pod Security Standard. OpenShift applies an equivalent context on its own either way. |
| `use_secrets` | bool | `true` | Pass database credentials through a Kubernetes Secret rather than plain environment values on the Job spec, where `kubectl describe job` would expose them. |

### `storage_metrics`

Optional Pure Storage metrics collection during benchmark runs. When enabled, collects array-level performance data (IOPS, throughput, latency) alongside HammerDB results.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `enabled` | bool | `false` | Enable Pure Storage metrics collection. |
| `pure.host` | string | `""` | FlashArray management IP or hostname. |
| `pure.api_token` | string | `""` | Pure Storage REST API token. |
| `pure.volume` | string | `""` | Volume name to monitor. Leave empty for array-level metrics. |
| `pure.poll_interval` | int | `5` | Metrics polling interval in seconds. Min: 1. |
| `pure.verify_ssl` | bool | `false` | Verify SSL certificate on the Pure Storage management interface. |
| `pure.api_version` | string | `"2.4"` | Pure Storage REST API version. |

## Target Expansion and Per-Host Overrides

The `targets.defaults` block is deep-merged into each host entry. Per-host values override defaults at any nesting depth. This eliminates repetition when all targets share the same credentials and database settings.

The deep merge is recursive: overriding a nested field (e.g., `oracle.tprocc.password`) does **not** clear sibling fields (e.g., `oracle.tprocc.user` is preserved from defaults).

### Basic example: different credentials per host

```yaml
targets:
  defaults:
    type: oracle
    username: system
    password: secret123
    oracle:
      service: "ORCLPDB"
  hosts:
    - name: db-01
      host: db-01.local
    - name: db-02
      host: db-02.local
      password: different-pw     # Overrides default
```

### Oracle: different PDBs and schema passwords per host

```yaml
targets:
  defaults:
    type: oracle
    username: system
    password: "default_pass"
    oracle:
      service: "ORCLPDB"
      port: 1521
      tablespace: "TPCC"
      temp_tablespace: "TEMP"
      tprocc:
        user: "TPCC"
        password: "default_tpcc_pass"

  hosts:
    - name: ora-prod
      host: ora-prod.example.com
      password: "prod_system_pass"
      oracle:
        service: "PRODPDB"
        tprocc:
          password: "prod_tpcc_pass"

    - name: ora-dev
      host: ora-dev.example.com
      password: "dev_system_pass"
      oracle:
        service: "DEVPDB"
        tablespace: "TPCC_DEV"
        tprocc:
          password: "dev_tpcc_pass"
```

After expansion, `ora-prod` inherits `port: 1521`, `tablespace: "TPCC"`, `temp_tablespace: "TEMP"`, and `tprocc.user: "TPCC"` from defaults, but uses its own `service`, `password`, and `tprocc.password`. `ora-dev` additionally overrides `tablespace`.

### MSSQL: different encryption and database names per host

```yaml
targets:
  defaults:
    type: mssql
    username: sa
    password: "default_pass"
    mssql:
      port: 1433
      connection:
        encrypt_connection: true
        trust_server_cert: true
      tprocc:
        database_name: tpcc

  hosts:
    - name: sql-secure
      host: sql-secure.example.com
      password: "secure_pass"
      mssql:
        connection:
          trust_server_cert: false    # Use proper CA certs

    - name: sql-legacy
      host: sql-legacy.example.com
      password: "legacy_pass"
      mssql:
        connection:
          encrypt_connection: false   # No TLS
        tprocc:
          database_name: legacy_tpcc  # Different database
```

`sql-secure` inherits `encrypt_connection: true` from defaults but disables certificate trust. `sql-legacy` disables encryption entirely and uses a different database name.

## Complete Examples

Ready-to-use config files for every database and benchmark combination:

**Kubernetes backend:**

- [examples/values-oracle.yaml](../examples/values-oracle.yaml): Oracle reference config, all fields
- [examples/values-mssql.yaml](../examples/values-mssql.yaml): MSSQL reference config, all fields
- [examples/oracle-tprocc.yaml](../examples/oracle-tprocc.yaml): Oracle TPC-C, 4 targets
- [examples/oracle-tproch.yaml](../examples/oracle-tproch.yaml): Oracle TPC-H, 4 targets
- [examples/mssql-tprocc.yaml](../examples/mssql-tprocc.yaml): SQL Server TPC-C, 4 targets
- [examples/mssql-tproch.yaml](../examples/mssql-tproch.yaml): SQL Server TPC-H, 4 targets
- [examples/scale-tests/](../examples/scale-tests/): progressive 1 to 8 target configs for Oracle and MSSQL, used to build a scale curve

**Container backend (podman or docker):**

- [examples/container-mssql-tprocc.yaml](../examples/container-mssql-tprocc.yaml): SQL Server TPC-C, single host
- [examples/container-postgres-tprocc.yaml](../examples/container-postgres-tprocc.yaml): PostgreSQL TPC-C, single host
- [examples/postgres-setup/provision_postgres.sh](../examples/postgres-setup/provision_postgres.sh): reference script for configuring `pg_hba.conf` and `listen_addresses` so PostgreSQL accepts connections from the worker host

## v1 Config Auto-Migration

HammerDB-Scale automatically detects v1.x config files (by the presence of a `testRun` key) and migrates them to v2 format at load time. See [MIGRATION.md](MIGRATION.md) for field mapping details.
