"""Pydantic models for HammerDB-Scale v2 YAML configuration schema."""

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, model_validator


# --- Enums ---


class DatabaseType(str, Enum):
    oracle = "oracle"
    mssql = "mssql"
    postgres = "postgres"


class BenchmarkType(str, Enum):
    tprocc = "tprocc"
    tproch = "tproch"


class Phase(str, Enum):
    build = "build"
    run = "run"  # "run" in CLI maps to "load" in Helm/entrypoint


class ImagePullPolicy(str, Enum):
    always = "Always"
    if_not_present = "IfNotPresent"
    never = "Never"


class BackendType(str, Enum):
    """Where benchmark workloads execute."""

    kubernetes = "kubernetes"
    container = "container"  # auto-detect podman or docker
    podman = "podman"
    docker = "docker"


class ContainerRuntimeName(str, Enum):
    auto = "auto"
    podman = "podman"
    docker = "docker"


# --- Oracle Config Models ---


class OracleTproccConfig(BaseModel):
    user: str = "TPCC"
    password: str = ""


class OracleTprochConfig(BaseModel):
    user: str = "tpch"
    password: str = ""
    degree_of_parallel: int = Field(default=8, ge=1)


class OracleConfig(BaseModel):
    service: str = "ORCLPDB"
    port: int = Field(default=1521, ge=1, le=65535)
    tablespace: str = "TPCC"
    temp_tablespace: str = "TEMP"
    tprocc: OracleTproccConfig = OracleTproccConfig()
    tproch: OracleTprochConfig = OracleTprochConfig()


# --- MSSQL Config Models ---


class MssqlTproccConfig(BaseModel):
    database_name: str = "tpcc"
    use_bcp: bool = False


class MssqlTprochConfig(BaseModel):
    database_name: str = "tpch"
    maxdop: int = Field(default=2, ge=1)
    use_clustered_columnstore: bool = False


class MssqlConnectionConfig(BaseModel):
    tcp: bool = True
    authentication: str = "sql"
    odbc_driver: str = "ODBC Driver 18 for SQL Server"
    encrypt_connection: bool = True
    trust_server_cert: bool = True


class MssqlConfig(BaseModel):
    port: int = Field(default=1433, ge=1, le=65535)
    tprocc: MssqlTproccConfig = MssqlTproccConfig()
    tproch: MssqlTprochConfig = MssqlTprochConfig()
    connection: MssqlConnectionConfig = MssqlConnectionConfig()


# --- PostgreSQL Config Models ---


class PostgresTproccConfig(BaseModel):
    database_name: str = "tpcc"
    user: str = "tpcc"
    password: str = "tpcc"
    # HammerDB's recommended default for PostgreSQL TPROC-C, and generally the
    # higher-throughput form. Must match between build and run: the driver
    # calls procedures that only exist if the schema was built with them.
    stored_procedures: bool = True
    partition: bool = False
    vacuum: bool = False


class PostgresTprochConfig(BaseModel):
    database_name: str = "tpch"
    user: str = "tpch"
    password: str = "tpch"
    # Degree of parallelism for the query phase.
    max_parallel_workers: int = Field(default=8, ge=1)


class PostgresConfig(BaseModel):
    port: int = Field(default=5432, ge=1, le=65535)
    # PostgreSQL defaults to "prefer": TLS when the server offers it.
    sslmode: str = "prefer"
    # Empty means pg_default, which is the volume the data directory lives on.
    tablespace: str = ""
    tprocc: PostgresTproccConfig = PostgresTproccConfig()
    tproch: PostgresTprochConfig = PostgresTprochConfig()


# --- Image Config ---


class ImageConfig(BaseModel):
    repository: str = "sillidata/hammerdb-scale"
    tag: str = "latest"
    pull_policy: ImagePullPolicy = ImagePullPolicy.always
    # Where HammerDB lives inside the image. Only needs setting for a custom
    # image built with a non-default HAMMERDB_VERSION; the container backend
    # otherwise reads HAMMERDB_HOME from the image itself.
    hammerdb_home: Optional[str] = None


# --- Target Models ---


class TargetHost(BaseModel):
    name: str
    host: str
    type: Optional[DatabaseType] = None
    username: Optional[str] = None
    password: Optional[str] = None
    image: Optional[ImageConfig] = None
    oracle: Optional[OracleConfig] = None
    mssql: Optional[MssqlConfig] = None
    postgres: Optional[PostgresConfig] = None


class TargetDefaults(BaseModel):
    type: Optional[DatabaseType] = None
    username: Optional[str] = None
    password: Optional[str] = None
    image: ImageConfig = ImageConfig()
    oracle: Optional[OracleConfig] = None
    mssql: Optional[MssqlConfig] = None
    postgres: Optional[PostgresConfig] = None


class TargetsConfig(BaseModel):
    defaults: TargetDefaults = TargetDefaults()
    hosts: list[TargetHost] = Field(..., min_length=1)


# --- Benchmark Config ---


class TproccConfig(BaseModel):
    warehouses: int = Field(default=100, ge=1)
    build_virtual_users: int = Field(default=4, ge=1)
    load_virtual_users: int = Field(default=4, ge=1)
    driver: str = "timed"
    rampup: int = Field(default=5, ge=0)  # minutes
    duration: int = Field(default=10, ge=1)  # minutes
    total_iterations: int = Field(default=10000000, ge=1)
    all_warehouses: bool = True
    checkpoint: bool = True
    time_profile: bool = False


class TprochConfig(BaseModel):
    scale_factor: int = Field(default=1, ge=1)
    build_threads: int = Field(default=4, ge=1)
    build_virtual_users: int = Field(default=1, ge=1)
    load_virtual_users: int = Field(default=1, ge=1)
    total_querysets: int = Field(default=1, ge=1)


class HammerDBConfig(BaseModel):
    tprocc: TproccConfig = TproccConfig()
    tproch: TprochConfig = TprochConfig()


# --- Infrastructure ---


class ResourceSpec(BaseModel):
    memory: str = "4Gi"
    cpu: str = "4"


class ResourcesConfig(BaseModel):
    requests: ResourceSpec = ResourceSpec()
    limits: ResourceSpec = ResourceSpec(memory="8Gi", cpu="8")


class KubernetesConfig(BaseModel):
    namespace: str = "hammerdb"
    job_ttl: int = Field(default=86400, ge=0)
    # Emit a restricted-compliant securityContext on the Job pods. Needed on
    # plain Kubernetes clusters enforcing the restricted Pod Security Standard.
    # OpenShift injects an equivalent context via its SCC either way.
    security_context: bool = True
    # Pass database credentials through a Secret rather than plain env values
    # in the Job spec, where `kubectl describe job` would expose them.
    use_secrets: bool = True


class ContainerConfig(BaseModel):
    """Settings for the local container backend (podman or docker)."""

    runtime: ContainerRuntimeName = ContainerRuntimeName.auto
    network: Optional[str] = None  # None uses the runtime's default network


# --- Storage Metrics ---


class PureStorageConfig(BaseModel):
    host: str = ""
    api_token: str = ""
    volume: str = ""
    poll_interval: int = Field(default=5, ge=1)
    verify_ssl: bool = False
    api_version: str = "2.4"
    duration: Optional[int] = Field(
        default=None, ge=1
    )  # seconds; None = auto-calculate


class StorageMetricsConfig(BaseModel):
    enabled: bool = False
    provider: str = "pure"
    pure: PureStorageConfig = PureStorageConfig()


# --- Root Config Model ---


class HammerDBScaleConfig(BaseModel):
    name: str
    description: str = ""
    default_benchmark: Optional[BenchmarkType] = None
    backend: BackendType = BackendType.kubernetes
    targets: TargetsConfig
    hammerdb: HammerDBConfig = HammerDBConfig()
    resources: ResourcesConfig = ResourcesConfig()
    kubernetes: KubernetesConfig = KubernetesConfig()
    container: ContainerConfig = ContainerConfig()
    storage_metrics: StorageMetricsConfig = StorageMetricsConfig()

    @model_validator(mode="after")
    def apply_database_type_defaults(self) -> "HammerDBScaleConfig":
        """Fill in the database-specific block when it was not supplied.

        Every field in OracleConfig and MssqlConfig has a working default, so
        requiring the block was pure boilerplate: it forced roughly 15 lines of
        config that only restated the defaults. Omitting it now means "use the
        defaults", which is what lets a minimal config be a dozen lines.

        Oracle is the exception worth noting: its schema passwords default to
        empty and fall back to the target password at render time.
        """
        defaults = self.targets.defaults
        if defaults.type == DatabaseType.oracle and defaults.oracle is None:
            defaults.oracle = OracleConfig()
        if defaults.type == DatabaseType.mssql and defaults.mssql is None:
            defaults.mssql = MssqlConfig()
        if defaults.type == DatabaseType.postgres and defaults.postgres is None:
            defaults.postgres = PostgresConfig()
        return self

    @model_validator(mode="after")
    def validate_targets_have_required_fields(self) -> "HammerDBScaleConfig":
        """Every host must have type, username, password after defaults merge."""
        defaults = self.targets.defaults
        for host in self.targets.hosts:
            effective_type = host.type or defaults.type
            effective_user = host.username or defaults.username
            effective_pass = host.password or defaults.password
            if not effective_type:
                raise ValueError(
                    f"Target '{host.name}' has no database type. "
                    f"Set type in targets.defaults or on the host."
                )
            if not effective_user:
                raise ValueError(
                    f"Target '{host.name}' has no username. "
                    f"Set username in targets.defaults or on the host."
                )
            if not effective_pass:
                raise ValueError(
                    f"Target '{host.name}' has no password. "
                    f"Set password in targets.defaults or on the host."
                )
        return self

    def get_image_warnings(self) -> list[str]:
        """Check if Oracle targets use an image without 'oracle' in the name."""
        warnings = []
        defaults = self.targets.defaults
        for host in self.targets.hosts:
            effective_type = host.type or defaults.type
            effective_image = host.image or defaults.image
            if (
                effective_type == DatabaseType.oracle
                and "oracle" not in effective_image.repository
            ):
                warnings.append(
                    f"Image '{effective_image.repository}:{effective_image.tag}' "
                    f"does not contain 'oracle'. "
                    f"Oracle targets may fail without Oracle Instant Client. "
                    f"Consider using 'sillidata/hammerdb-scale-oracle:latest'"
                )
        return warnings
