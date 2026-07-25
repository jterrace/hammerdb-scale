"""Command-level tests driving the Typer app with the backend mocked.

The orchestration layer had no tests, and that is exactly where the bugs have
been: the two most recent upstream fixes ("test ID resolution filtering by
deployment name", "YAML scientific notation in run hash generation") were both
here, as were the phase-label and boolean-default bugs found during this work.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from hammerdb_scale.cli import app
from hammerdb_scale.runtime.base import (
    STATUS_COMPLETED,
    STATUS_FAILED,
    WorkloadRef,
)

runner = CliRunner()

CONFIG = """
name: clitest
default_benchmark: tprocc
backend: podman
targets:
  defaults:
    type: oracle
    username: system
    password: "pw"
    oracle:
      service: TPCC
  hosts:
    - name: t1
      host: "10.0.0.1"
hammerdb:
  tprocc:
    warehouses: 10
    load_virtual_users: 2
    rampup: 0
    duration: 1
"""


@pytest.fixture
def config_file(tmp_path):
    path = tmp_path / "hammerdb-scale.yaml"
    path.write_text(CONFIG)
    return path


@pytest.fixture
def fake_backend():
    """A backend that deploys cleanly and reports one completed workload."""
    backend = MagicMock()
    backend.name = "podman"
    backend.preflight.return_value = []
    backend.deploy.return_value = ["hdb-load-00-clitest-1"]
    backend.list_workloads.return_value = [
        WorkloadRef(
            name="hdb-load-00-clitest-1",
            target_name="t1",
            target_host="10.0.0.1",
            database_type="oracle",
            index=0,
            status=STATUS_COMPLETED,
            duration_seconds=65,
        )
    ]
    backend.get_logs.return_value = (
        "TEST RESULT : System achieved 9108 NOPM from 18882 Oracle TPM"
    )
    backend.find_test_ids.return_value = ["clitest-1"]
    return backend


class TestVersion:
    def test_reports_a_version(self):
        result = runner.invoke(app, ["version"])
        assert result.exit_code == 0
        assert "hammerdb-scale" in result.stdout

    def test_does_not_use_removed_kubectl_flag(self):
        """kubectl dropped --short in 1.28, so it must not be the only attempt."""
        result = runner.invoke(app, ["version"])
        assert "unknown flag" not in result.stdout


class TestRun:
    def test_deploys_via_the_configured_backend(self, config_file, fake_backend):
        with patch("hammerdb_scale.runtime.get_backend", return_value=fake_backend):
            result = runner.invoke(app, ["-f", str(config_file), "run"])
        assert result.exit_code == 0, result.stdout
        assert fake_backend.deploy.called
        assert "podman" in result.stdout

    def test_passes_run_phase_to_the_backend(self, config_file, fake_backend):
        with patch("hammerdb_scale.runtime.get_backend", return_value=fake_backend):
            runner.invoke(app, ["-f", str(config_file), "run"])
        assert fake_backend.deploy.call_args.kwargs["phase"] == "run"

    def test_aborts_when_preflight_fails(self, config_file, fake_backend):
        fake_backend.preflight.return_value = ["no container runtime found"]
        with patch("hammerdb_scale.runtime.get_backend", return_value=fake_backend):
            result = runner.invoke(app, ["-f", str(config_file), "run"])
        assert result.exit_code == 1
        assert "no container runtime" in result.stdout
        assert not fake_backend.deploy.called

    def test_wait_reports_failure_and_exits_nonzero(self, config_file, fake_backend):
        """A failed benchmark must not look like success to a CI pipeline."""
        fake_backend.list_workloads.return_value = [
            WorkloadRef(
                name="hdb-load-00-x",
                target_name="t1",
                target_host="10.0.0.1",
                database_type="oracle",
                index=0,
                status=STATUS_FAILED,
                duration_seconds=5,
            )
        ]
        fake_backend.get_logs.return_value = "ORA-01017: invalid username/password"
        with patch("hammerdb_scale.runtime.get_backend", return_value=fake_backend):
            result = runner.invoke(app, ["-f", str(config_file), "run", "--wait"])
        assert result.exit_code == 1

    def test_wait_surfaces_the_database_error(self, config_file, fake_backend):
        """The reason should be inline, not something to go hunting for."""
        fake_backend.list_workloads.return_value = [
            WorkloadRef(
                name="hdb-load-00-x",
                target_name="t1",
                target_host="10.0.0.1",
                database_type="oracle",
                index=0,
                status=STATUS_FAILED,
                duration_seconds=5,
            )
        ]
        fake_backend.get_logs.return_value = "ORA-01017: invalid username/password"
        with patch("hammerdb_scale.runtime.get_backend", return_value=fake_backend):
            result = runner.invoke(app, ["-f", str(config_file), "run", "--wait"])
        assert "ORA-01017" in result.stdout


class TestStatus:
    def test_shows_parsed_metrics_for_completed_work(self, config_file, fake_backend):
        with patch("hammerdb_scale.runtime.get_backend", return_value=fake_backend):
            result = runner.invoke(app, ["-f", str(config_file), "status"])
        assert result.exit_code == 0, result.stdout
        assert "18,882" in result.stdout

    def test_json_output_is_machine_readable(self, config_file, fake_backend):
        import json

        with patch("hammerdb_scale.runtime.get_backend", return_value=fake_backend):
            result = runner.invoke(app, ["-f", str(config_file), "status", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert data[0]["target"] == "t1"
        assert data[0]["status"] == STATUS_COMPLETED

    def test_errors_when_no_workloads_exist(self, config_file, fake_backend):
        fake_backend.list_workloads.return_value = []
        with patch("hammerdb_scale.runtime.get_backend", return_value=fake_backend):
            result = runner.invoke(app, ["-f", str(config_file), "status"])
        assert result.exit_code == 1


class TestLogs:
    def test_prefixes_each_line_with_its_target(self, config_file, fake_backend):
        with patch("hammerdb_scale.runtime.get_backend", return_value=fake_backend):
            result = runner.invoke(app, ["-f", str(config_file), "logs"])
        assert result.exit_code == 0
        assert "t1" in result.stdout

    def test_unknown_target_is_an_error(self, config_file, fake_backend):
        with patch("hammerdb_scale.runtime.get_backend", return_value=fake_backend):
            result = runner.invoke(
                app, ["-f", str(config_file), "logs", "--target", "nope"]
            )
        assert result.exit_code == 1


class TestClean:
    def test_requires_a_scope_flag(self, config_file):
        result = runner.invoke(app, ["-f", str(config_file), "clean"])
        assert result.exit_code == 1
        assert "scope flag" in result.stdout

    def test_database_scope_requires_a_benchmark(self, config_file):
        """Dropping the wrong benchmark's tables is destructive and silent."""
        result = runner.invoke(app, ["-f", str(config_file), "clean", "--database"])
        assert result.exit_code == 1
        assert "--benchmark" in result.stdout

    def test_rejects_an_invalid_benchmark(self, config_file):
        result = runner.invoke(
            app,
            ["-f", str(config_file), "clean", "--database", "--benchmark", "tpcx"],
        )
        assert result.exit_code == 1

    def test_resources_scope_requires_id_or_everything(self, config_file):
        result = runner.invoke(app, ["-f", str(config_file), "clean", "--resources"])
        assert result.exit_code == 1


class TestConfigDiscovery:
    def test_missing_config_is_a_clear_error(self, tmp_path):
        result = runner.invoke(app, ["-f", str(tmp_path / "nope.yaml"), "run"])
        assert result.exit_code != 0

    def test_invalid_yaml_is_reported(self, tmp_path):
        bad = tmp_path / "bad.yaml"
        bad.write_text("name: [unclosed\n")
        result = runner.invoke(app, ["-f", str(bad), "validate"])
        assert result.exit_code == 1
