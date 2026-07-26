"""Tests for run isolation, mount options, and per-database preflight ports.

These cover three defects that all produced confidently wrong output rather
than an error, which is the failure mode most likely to mislead a user.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest
import yaml

from hammerdb_scale.config.loader import load_config
from hammerdb_scale.runtime.container import (
    LABEL_DEPLOYMENT,
    LABEL_MANAGED,
    ContainerBackend,
    mount_suffix,
    selinux_is_enforcing,
)
from hammerdb_scale.runtime.preflight import _target_endpoints


def _config(db_type: str, extra: dict | None = None):
    raw = {
        "name": "t",
        "targets": {
            "defaults": {"type": db_type, "username": "u", "password": "p",
                         **(extra or {})},
            "hosts": [{"name": "a", "host": "10.0.0.1"}],
        },
    }
    with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False) as handle:
        yaml.safe_dump(raw, handle)
        path = handle.name
    try:
        return load_config(Path(path))
    finally:
        Path(path).unlink(missing_ok=True)


class TestPreflightPorts:
    """Probing the wrong port reports a healthy fleet as unreachable."""

    @pytest.mark.parametrize(
        "db_type,expected", [("oracle", 1521), ("mssql", 1433), ("postgres", 5432)]
    )
    def test_default_port_per_database(self, db_type, expected):
        assert _target_endpoints(_config(db_type))[0][2] == expected

    def test_postgres_is_not_probed_on_the_mssql_port(self):
        """Regression: postgres fell through to the mssql branch."""
        assert _target_endpoints(_config("postgres"))[0][2] != 1433

    @pytest.mark.parametrize(
        "db_type,block,expected",
        [
            ("postgres", {"postgres": {"port": 5433}}, 5433),
            ("mssql", {"mssql": {"port": 1435}}, 1435),
            ("oracle", {"oracle": {"port": 1522}}, 1522),
        ],
    )
    def test_configured_port_wins(self, db_type, block, expected):
        assert _target_endpoints(_config(db_type, block))[0][2] == expected


class TestMountSuffix:
    """Docker Desktop mishandles the :z relabel, so it must be conditional."""

    def test_enforcing_host_gets_relabel(self, monkeypatch):
        monkeypatch.setattr(
            "hammerdb_scale.runtime.container.selinux_is_enforcing", lambda: True
        )
        assert mount_suffix() == "ro,z"

    def test_non_selinux_host_gets_plain_readonly(self, monkeypatch):
        monkeypatch.setattr(
            "hammerdb_scale.runtime.container.selinux_is_enforcing", lambda: False
        )
        assert mount_suffix() == "ro"

    def test_detection_survives_missing_sysfs(self, monkeypatch):
        """macOS and WSL2 have no /sys/fs/selinux at all."""
        monkeypatch.setattr(Path, "exists", lambda self: False)
        assert selinux_is_enforcing() is False


class TestDeploymentScoping:
    """Two runs on one host must not see each other's containers."""

    @pytest.fixture
    def backend(self, monkeypatch):
        monkeypatch.setattr(
            "hammerdb_scale.runtime.container.detect_runtime",
            lambda preferred=None: "podman",
        )
        return ContainerBackend(deployment_name="alpha")

    def test_scope_filters_include_deployment(self, backend):
        filters = backend._scope_filters()
        assert f"label={LABEL_DEPLOYMENT}=alpha" in filters
        assert any(LABEL_MANAGED in f for f in filters)

    def test_unnamed_backend_filters_on_managed_only(self, monkeypatch):
        monkeypatch.setattr(
            "hammerdb_scale.runtime.container.detect_runtime",
            lambda preferred=None: "podman",
        )
        filters = ContainerBackend()._scope_filters()
        assert not any(LABEL_DEPLOYMENT in f for f in filters)

    def test_remove_is_scoped_to_this_config(self, backend, monkeypatch):
        """`clean --all` must not delete a colleague's run."""
        seen = {}

        def fake_run(args, **kwargs):
            seen["args"] = args
            class R:
                returncode = 0
                stdout = ""
                stderr = ""
            return R()

        monkeypatch.setattr(backend, "_run", fake_run)
        backend.remove(everything=True)
        assert f"label={LABEL_DEPLOYMENT}=alpha" in seen["args"]
