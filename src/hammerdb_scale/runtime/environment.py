"""Build the HammerDB container environment from a v2 config.

This module is the single source of truth for the container's environment
variable contract. Both the Kubernetes backend (via the Helm chart) and the
container backend (via ``podman``/``docker run -e``) must produce the same
variables for the same config, otherwise the two backends silently diverge.

The contract itself is defined by ``entrypoint.sh`` and the TCL scripts it
dispatches to. Previously it was expressed only in Go template syntax inside
``templates/job-hammerdb-worker.yaml``; lifting it here lets a non-Kubernetes
backend reuse it and lets it be unit tested.
"""

from __future__ import annotations

from hammerdb_scale.config.schema import HammerDBScaleConfig, MssqlConfig
from hammerdb_scale.constants import PHASE_MAP

# HammerDB driver name per database type, mirroring the
# "hammerdb-scale-test.dbDriver" helper in _helpers.tpl.
DB_DRIVERS = {
    "mssql": "mssqls",
    "oracle": "oracle",
    "postgres": "pg",
    "mysql": "mysql",
}


def get_db_driver(database_type: str) -> str:
    """Return the HammerDB driver name for a database type."""
    driver = DB_DRIVERS.get(database_type)
    if not driver:
        raise ValueError(f"Unsupported database type: {database_type}")
    return driver


def _bool_str(value: object) -> str:
    """Render a value the way the Helm template's `quote` does for booleans."""
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def build_target_env(
    config: HammerDBScaleConfig,
    target: dict,
    *,
    phase: str,
    benchmark: str,
    test_id: str,
    target_index: int,
) -> dict[str, str]:
    """Build the full environment for one target's HammerDB container.

    Args:
        config: The validated v2 configuration.
        target: One expanded target dict from ``expand_targets()``.
        phase: CLI phase, ``"build"`` or ``"run"``.
        benchmark: ``"tprocc"`` or ``"tproch"``.
        test_id: The test run identifier.
        target_index: Zero-based index of this target within the run.

    Returns:
        A flat ``{name: value}`` mapping with every value already a string,
        matching what the Kubernetes Job spec would set.
    """
    db_type = target["type"]
    run_mode = PHASE_MAP.get(phase, phase)

    env: dict[str, str] = {
        # Test identification
        "TEST_RUN_ID": test_id,
        "TARGET_NAME": target["name"],
        "TARGET_INDEX": str(target_index),
        "RUN_MODE": run_mode,
        "BENCHMARK": benchmark,
        "DATABASE_TYPE": db_type,
        # Database connection
        "USERNAME": target["username"],
        "PASSWORD": target["password"],
        "HOST": target["host"],
        # Global settings
        "TMP": "/tmp",
        "TMPDIR": "/tmp",
    }

    mssql_cfg = config.targets.defaults.mssql or MssqlConfig()
    env["USE_BCP"] = _bool_str(mssql_cfg.tprocc.use_bcp)

    if db_type == "mssql":
        env.update(_mssql_connection_env(target, mssql_cfg))
    elif db_type == "oracle":
        env.update(_oracle_env(target))

    if benchmark == "tprocc":
        env.update(_tprocc_env(config, target, db_type))
    elif benchmark == "tproch":
        env.update(_tproch_env(config, target, db_type, mssql_cfg))

    if config.storage_metrics.enabled:
        env.update(_pure_storage_env(config, target_index))

    return env


def _mssql_connection_env(target: dict, mssql_cfg: MssqlConfig) -> dict[str, str]:
    """SQL Server connection variables."""
    conn = mssql_cfg.connection
    return {
        "SQL_SERVER_HOST": target["host"],
        "MSSQLS_TCP": _bool_str(conn.tcp),
        "MSSQLS_PORT": str(mssql_cfg.port),
        "MSSQLS_AUTHENTICATION": conn.authentication,
        "MSSQLS_AZURE": "false",
        "MSSQLS_LINUX_ODBC": conn.odbc_driver,
        "MSSQLS_ODBC_DRIVER": conn.odbc_driver,
        "MSSQLS_ENCRYPT_CONNECTION": _bool_str(conn.encrypt_connection),
        "MSSQLS_TRUST_SERVER_CERT": _bool_str(conn.trust_server_cert),
    }


def _oracle_env(target: dict) -> dict[str, str]:
    """Oracle connection and schema variables."""
    oracle = target.get("oracle", {})
    tprocc = oracle.get("tprocc", {})
    tproch = oracle.get("tproch", {})
    password = target["password"]

    env = {
        "ORACLE_SERVICE": oracle.get("service", "ORCL"),
        "ORACLE_PORT": str(oracle.get("port", 1521)),
        "ORACLE_TABLESPACE": oracle.get("tablespace", "USERS"),
        "ORACLE_TEMP_TABLESPACE": oracle.get("temp_tablespace", "TEMP"),
        "TPROCC_USER": tprocc.get("user") or "tpcc",
        "TPROCC_PASSWORD": tprocc.get("password") or password,
        "TPROCH_USER": tproch.get("user") or "tpch",
        "TPROCH_PASSWORD": tproch.get("password") or password,
        "TPROCH_DEGREE_OF_PARALLEL": str(tproch.get("degree_of_parallel", 8)),
    }
    if oracle.get("sid"):
        env["ORACLE_SID"] = oracle["sid"]
    return env


def _tprocc_env(
    config: HammerDBScaleConfig, target: dict, db_type: str
) -> dict[str, str]:
    """TPC-C benchmark variables."""
    tc = config.hammerdb.tprocc
    env = {
        "TPROCC_DRIVER": get_db_driver(db_type),
        "TPROCC_BUILD_VIRTUAL_USERS": str(tc.build_virtual_users),
        "WAREHOUSES": str(tc.warehouses),
        "TPROCC_DRIVER_TYPE": tc.driver,
        "TPROCC_ALLWAREHOUSE": _bool_str(tc.all_warehouses),
        "VIRTUAL_USERS": str(tc.load_virtual_users),
        "RAMPUP": str(tc.rampup),
        "DURATION": str(tc.duration),
        "TOTAL_ITERATIONS": str(tc.total_iterations),
        "TPROCC_LOG_TO_TEMP": "0",
        "TPROCC_USE_TRANSACTION_COUNTER": "true",
        "TPROCC_CHECKPOINT": _bool_str(tc.checkpoint),
        "TPROCC_TIMEPROFILE": _bool_str(tc.time_profile),
    }
    if db_type == "mssql":
        env["TPROCC_DATABASE_NAME"] = target.get("tprocc", {}).get(
            "databaseName", "tpcc"
        )
    return env


def _tproch_env(
    config: HammerDBScaleConfig,
    target: dict,
    db_type: str,
    mssql_cfg: MssqlConfig,
) -> dict[str, str]:
    """TPC-H benchmark variables."""
    th = config.hammerdb.tproch
    env = {
        "TPROCH_DRIVER": get_db_driver(db_type),
        "TPROCH_SCALE_FACTOR": str(th.scale_factor),
        "TPROCH_BUILD_THREADS": str(th.build_threads),
        "TPROCH_BUILD_VIRTUAL_USERS": str(th.build_virtual_users),
        "TPROCH_VIRTUAL_USERS": str(th.load_virtual_users),
        "TPROCH_TOTAL_QUERYSETS": str(th.total_querysets),
        "TPROCH_LOG_TO_TEMP": "1",
    }
    if db_type == "mssql":
        env["TPROCH_DATABASE_NAME"] = target.get("tproch", {}).get(
            "databaseName", "tpch"
        )
        env["TPROCH_USE_CLUSTERED_COLUMNSTORE"] = _bool_str(
            mssql_cfg.tproch.use_clustered_columnstore
        )
        env["TPROCH_MAXDOP"] = str(mssql_cfg.tproch.maxdop)
    return env


def _pure_storage_env(config: HammerDBScaleConfig, target_index: int) -> dict[str, str]:
    """Pure Storage metrics collection variables.

    Only the first target collects metrics, matching the Helm template, so that
    N targets do not each hammer the array's REST API with identical queries.
    """
    pure = config.storage_metrics.pure
    env = {
        "PURE_ENABLED": "true",
        "PURE_COLLECT_METRICS": "true" if target_index == 0 else "false",
        "PURE_HOST": pure.host,
        "PURE_API_TOKEN": pure.api_token,
        "PURE_INTERVAL": str(pure.poll_interval),
        "PURE_NO_VERIFY_SSL": "false" if pure.verify_ssl else "true",
        "PURE_API_VERSION": pure.api_version,
        "PURE_OUTPUT": "/tmp/pure_metrics.json",
    }
    if pure.volume:
        env["PURE_VOLUME"] = pure.volume
    if pure.duration is not None:
        env["PURE_DURATION"] = str(pure.duration)
    return env
