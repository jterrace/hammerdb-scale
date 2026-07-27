# Security Considerations

## Credentials

HammerDB-Scale stores database credentials in plaintext YAML config files. This is consistent with Helm values.yaml patterns but should be handled carefully.

Recommendations:

- Do not commit config files containing passwords to version control.
- Use file permissions to restrict access to config files (`chmod 600`).
- Consider using environment variable substitution in CI/CD pipelines.

On the Kubernetes backend, credentials also pass through a Kubernetes Secret by default (`kubernetes.use_secrets: true`), so they do not appear in plain environment values on the Job spec, where `kubectl describe job` would expose them. Set `use_secrets: false` only if your cluster policy requires it; there is no equivalent protection on the container backend, since podman and docker containers run as plain local processes.

## Database Connectivity

- MSSQL connections use encrypted connections by default (`encrypt_connection: true`).
- The `validate` and `clean` commands connect to Oracle using `oracledb` in thin mode, so they need no Oracle client installed on the machine running the CLI. The benchmark itself is a separate matter: HammerDB's Oratcl interface links against Oracle Instant Client's native libraries, which is why the Oracle container image bundles Instant Client even though the CLI does not need it locally.
- The `validate` command tests connectivity as the admin user only, not the schema users the benchmark itself connects as.

## Container Images

- Default images are pulled from `sillidata/hammerdb-scale` (SQL Server, PostgreSQL) and `sillidata/hammerdb-scale-oracle` (Oracle).
- Images embed HammerDB 6.0 and database client libraries.
- Use `pull_policy: Always` in production to ensure the latest patches, on Kubernetes. The container backend pulls once and reuses the local image unless you remove it.

## Kubernetes

Applies only when `backend: kubernetes`.

- Jobs run in the configured namespace (default: `hammerdb`).
- Resource limits are enforced via the `resources` config section.
- Jobs have a configurable TTL (`job_ttl`) after which Kubernetes garbage-collects them.

## Container Backend

Applies only when `backend` is `podman`, `docker`, or `container`.

- Containers run as plain local processes under whichever user runs the CLI, with no cluster boundary between them and the rest of that host.
- Credentials pass through environment variables on the container directly. Anyone able to run `podman inspect` or `docker inspect` against a running or recently-stopped container on that host can read them.
- This backend is meant for a trusted single host close to the databases, not for multi-tenant or shared infrastructure.

## Network

- The CLI communicates with databases directly during `validate` and `clean` operations.
- On the Kubernetes backend, Helm and kubectl commands use the current kubeconfig context. `validate --from-cluster` checks database reachability from where the workers actually run, which is not always the same as reachable from your workstation.
- Pure Storage API calls, if enabled, use the configured API token and endpoint.
