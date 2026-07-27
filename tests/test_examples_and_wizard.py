"""Tests for shipped example configs and the init wizard's generated YAML.

Examples are the entry path for anyone who would rather read a file than
answer prompts, so a stale example is a support burden. These tests fail if
one stops loading or drifts from the documented backend guidance.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from hammerdb_scale.cli import _build_config_yaml
from hammerdb_scale.config.defaults import expand_targets
from hammerdb_scale.config.loader import load_config

REPO_ROOT = Path(__file__).resolve().parent.parent
EXAMPLES = sorted((REPO_ROOT / "examples").glob("*.yaml"))

ORACLE_BLOCK = {
    "service": "ORCLPDB",
    "port": 1521,
    "tablespace": "TPCC",
    "temp_tablespace": "TEMP",
    "tprocc": {"user": "TPCC", "password": "p"},
    "tproch": {"user": "tpch", "password": "p"},
}


def _load_yaml_string(text: str):
    with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False) as handle:
        handle.write(text)
        path = handle.name
    try:
        return load_config(Path(path))
    finally:
        Path(path).unlink(missing_ok=True)


class TestShippedExamples:
    @pytest.mark.parametrize("path", EXAMPLES, ids=lambda p: p.name)
    def test_example_loads(self, path):
        config = load_config(path)
        assert expand_targets(config), f"{path.name} expands to no targets"

    def test_container_examples_exist(self):
        """The README points people at the container path first."""
        names = {p.name for p in EXAMPLES}
        assert "container-mssql-tprocc.yaml" in names
        assert "container-postgres-tprocc.yaml" in names

    @pytest.mark.parametrize(
        "name", ["container-mssql-tprocc.yaml", "container-postgres-tprocc.yaml"]
    )
    def test_container_examples_do_not_need_a_cluster(self, name):
        config = load_config(REPO_ROOT / "examples" / name)
        assert config.backend.value in ("podman", "docker")


class TestWizardOutput:
    """init must emit a config that loads, for every backend and database."""

    @pytest.mark.parametrize("backend", ["podman", "docker", "kubernetes"])
    @pytest.mark.parametrize("db_type", ["mssql", "postgres", "oracle"])
    def test_generated_config_round_trips(self, backend, db_type):
        yaml_text = _build_config_yaml(
            name="t",
            db_type_str=db_type,
            benchmark_str="tprocc",
            hosts=[{"name": "a", "host": "10.0.0.1"}],
            username="u",
            password="p",
            oracle_config=ORACLE_BLOCK if db_type == "oracle" else None,
            backend_str=backend,
            namespace="hammerdb" if backend == "kubernetes" else None,
        )
        config = _load_yaml_string(yaml_text)
        assert config.backend.value == backend
        assert expand_targets(config)[0]["type"] == db_type

    def test_container_config_has_no_kubernetes_block(self):
        """A cluster block implies a cluster is needed. It is not."""
        yaml_text = _build_config_yaml(
            name="t",
            db_type_str="mssql",
            benchmark_str="tprocc",
            hosts=[{"name": "a", "host": "10.0.0.1"}],
            username="u",
            password="p",
            oracle_config=None,
            backend_str="podman",
            namespace=None,
        )
        assert "kubernetes:" not in yaml_text
        assert "container:" in yaml_text

    def test_kubernetes_config_keeps_its_namespace(self):
        yaml_text = _build_config_yaml(
            name="t",
            db_type_str="mssql",
            benchmark_str="tprocc",
            hosts=[{"name": "a", "host": "10.0.0.1"}],
            username="u",
            password="p",
            oracle_config=None,
            backend_str="kubernetes",
            namespace="my-ns",
        )
        assert "kubernetes:" in yaml_text
        assert "my-ns" in yaml_text
        assert "container:" not in yaml_text

    def test_postgres_does_not_emit_mssql_settings(self):
        """Regression: postgres fell into the mssql branch of the template."""
        yaml_text = _build_config_yaml(
            name="t",
            db_type_str="postgres",
            benchmark_str="tprocc",
            hosts=[{"name": "a", "host": "10.0.0.1"}],
            username="u",
            password="p",
            oracle_config=None,
            backend_str="podman",
            namespace=None,
        )
        assert "postgres:" in yaml_text
        assert "odbc_driver" not in yaml_text
