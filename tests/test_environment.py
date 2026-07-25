"""Tests for the shared container environment builder.

These lock down the env-var contract that both backends depend on. If the
Kubernetes backend and the container backend disagree about a variable, the two
execution paths silently produce different benchmarks.
"""

from __future__ import annotations

import pytest

from hammerdb_scale.config.defaults import expand_targets
from hammerdb_scale.config.schema import (
    HammerDBScaleConfig,
    HammerDBConfig,
    MssqlConfig,
    MssqlTproccConfig,
    OracleConfig,
    OracleTproccConfig,
    PureStorageConfig,
    StorageMetricsConfig,
    TargetDefaults,
    TargetHost,
    TargetsConfig,
    TproccConfig,
    TprochConfig,
)
from hammerdb_scale.runtime.environment import build_target_env, get_db_driver


def _oracle_config(**overrides) -> HammerDBScaleConfig:
    base = dict(
        name="ora",
        targets=TargetsConfig(
            defaults=TargetDefaults(
                type="oracle",
                username="system",
                password="secret",
                oracle=OracleConfig(
                    service="TPCC",
                    port=1521,
                    tprocc=OracleTproccConfig(user="TPCC", password="schemapw"),
                ),
            ),
            hosts=[TargetHost(name="ora-01", host="10.0.0.1")],
        ),
    )
    base.update(overrides)
    return HammerDBScaleConfig(**base)


def _mssql_config(**overrides) -> HammerDBScaleConfig:
    base = dict(
        name="sql",
        targets=TargetsConfig(
            defaults=TargetDefaults(
                type="mssql",
                username="sa",
                password="secret",
                mssql=MssqlConfig(
                    port=1433,
                    tprocc=MssqlTproccConfig(database_name="TPCC", use_bcp=True),
                ),
            ),
            hosts=[TargetHost(name="sql-01", host="10.0.0.2")],
        ),
    )
    base.update(overrides)
    return HammerDBScaleConfig(**base)


def _env_for(config, benchmark="tprocc", phase="run", index=0):
    target = expand_targets(config)[index]
    return build_target_env(
        config,
        target,
        phase=phase,
        benchmark=benchmark,
        test_id="t1",
        target_index=index,
    )


class TestDriverMapping:
    def test_known_drivers(self):
        assert get_db_driver("mssql") == "mssqls"
        assert get_db_driver("oracle") == "oracle"
        assert get_db_driver("postgres") == "pg"

    def test_unknown_driver_raises(self):
        with pytest.raises(ValueError, match="Unsupported database type"):
            get_db_driver("cassandra")


class TestPhaseMapping:
    def test_run_phase_becomes_load(self):
        """The CLI says "run"; entrypoint.sh expects "load"."""
        assert _env_for(_oracle_config(), phase="run")["RUN_MODE"] == "load"

    def test_build_phase_unchanged(self):
        assert _env_for(_oracle_config(), phase="build")["RUN_MODE"] == "build"


class TestOracleEnv:
    def test_connection_vars(self):
        env = _env_for(_oracle_config())
        assert env["HOST"] == "10.0.0.1"
        assert env["ORACLE_SERVICE"] == "TPCC"
        assert env["ORACLE_PORT"] == "1521"
        assert env["DATABASE_TYPE"] == "oracle"
        assert env["TPROCC_DRIVER"] == "oracle"

    def test_schema_credentials(self):
        env = _env_for(_oracle_config())
        assert env["TPROCC_USER"] == "TPCC"
        assert env["TPROCC_PASSWORD"] == "schemapw"

    def test_schema_password_falls_back_to_target_password(self):
        """An unset schema password inherits the target's password."""
        config = _oracle_config()
        config.targets.defaults.oracle.tprocc.password = ""
        assert _env_for(config)["TPROCC_PASSWORD"] == "secret"

    def test_no_mssql_vars_leak_in(self):
        env = _env_for(_oracle_config())
        assert "MSSQLS_PORT" not in env
        assert "SQL_SERVER_HOST" not in env


class TestMssqlEnv:
    def test_connection_vars(self):
        env = _env_for(_mssql_config())
        assert env["SQL_SERVER_HOST"] == "10.0.0.2"
        assert env["MSSQLS_PORT"] == "1433"
        assert env["TPROCC_DRIVER"] == "mssqls"
        assert env["TPROCC_DATABASE_NAME"] == "TPCC"

    def test_booleans_render_lowercase(self):
        """TCL compares against the literal strings "true"/"false"."""
        env = _env_for(_mssql_config())
        assert env["MSSQLS_ENCRYPT_CONNECTION"] == "true"
        assert env["USE_BCP"] == "true"

    def test_no_oracle_vars_leak_in(self):
        env = _env_for(_mssql_config())
        assert "ORACLE_SERVICE" not in env
        assert "TPROCC_USER" not in env


class TestBenchmarkSelection:
    def test_tprocc_excludes_tproch_vars(self):
        env = _env_for(_oracle_config(), benchmark="tprocc")
        assert "WAREHOUSES" in env
        assert "TPROCH_SCALE_FACTOR" not in env

    def test_tproch_excludes_tprocc_vars(self):
        env = _env_for(_oracle_config(), benchmark="tproch")
        assert "TPROCH_SCALE_FACTOR" in env
        assert "WAREHOUSES" not in env

    def test_large_integers_never_use_scientific_notation(self):
        """Regression: Helm rendered 10000000 as "1e+07", which TCL rejects."""
        config = _oracle_config(
            hammerdb=HammerDBConfig(tprocc=TproccConfig(total_iterations=10_000_000))
        )
        value = _env_for(config)["TOTAL_ITERATIONS"]
        assert value == "10000000"
        assert "e" not in value.lower()

    def test_all_values_are_strings(self):
        """Container runtimes and K8s env both require string values."""
        for benchmark in ("tprocc", "tproch"):
            env = _env_for(_oracle_config(), benchmark=benchmark)
            assert all(isinstance(v, str) for v in env.values())


class TestPureStorageEnv:
    def _config(self):
        return _oracle_config(
            storage_metrics=StorageMetricsConfig(
                enabled=True,
                pure=PureStorageConfig(host="10.1.1.1", api_token="tok"),
            )
        )

    def test_disabled_by_default(self):
        assert "PURE_ENABLED" not in _env_for(_oracle_config())

    def test_only_first_target_collects(self):
        """N targets must not each poll the array's REST API."""
        config = self._config()
        config.targets.hosts.append(TargetHost(name="ora-02", host="10.0.0.9"))
        assert _env_for(config, index=0)["PURE_COLLECT_METRICS"] == "true"
        assert _env_for(config, index=1)["PURE_COLLECT_METRICS"] == "false"

    def test_verify_ssl_is_inverted_for_the_collector(self):
        """The collector takes PURE_NO_VERIFY_SSL, the inverse of verify_ssl."""
        config = self._config()
        config.storage_metrics.pure.verify_ssl = False
        assert _env_for(config)["PURE_NO_VERIFY_SSL"] == "true"


class TestTprochEnv:
    def test_mssql_only_vars_are_gated(self):
        oracle_env = _env_for(_oracle_config(), benchmark="tproch")
        assert "TPROCH_MAXDOP" not in oracle_env

        mssql_env = _env_for(_mssql_config(), benchmark="tproch")
        assert mssql_env["TPROCH_MAXDOP"] == "2"

    def test_scale_factor_propagates(self):
        config = _oracle_config(
            hammerdb=HammerDBConfig(tproch=TprochConfig(scale_factor=100))
        )
        assert _env_for(config, benchmark="tproch")["TPROCH_SCALE_FACTOR"] == "100"
