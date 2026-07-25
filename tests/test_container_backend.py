"""Tests for the container backend's runtime-neutral parsing logic.

podman and docker differ in how they render `ps --format json`, timestamps and
container state. These tests pin down the normalisation so a change in either
runtime's output surfaces here rather than as a wrong benchmark report.
"""

from __future__ import annotations

import json

import pytest

from hammerdb_scale.runtime.base import (
    STATUS_COMPLETED,
    STATUS_FAILED,
    STATUS_RUNNING,
)
from hammerdb_scale.runtime.container import (
    LABEL_DB_TYPE,
    LABEL_INDEX,
    LABEL_TARGET,
    LABEL_TARGET_HOST,
    ContainerBackend,
    _parse_ts,
)


@pytest.fixture
def backend(monkeypatch):
    """A backend with runtime detection stubbed out."""
    monkeypatch.setattr(
        "hammerdb_scale.runtime.container.detect_runtime", lambda preferred=None: "podman"
    )
    return ContainerBackend()


class TestTimestampParsing:
    def test_podman_native_go_format(self):
        """podman renders Go's native time, not RFC3339."""
        parsed = _parse_ts("2026-07-24 23:32:08.696753997 -0600 MDT")
        assert parsed is not None
        assert parsed.year == 2026
        assert parsed.hour == 23

    def test_rfc3339_with_offset(self):
        parsed = _parse_ts("2026-07-24T23:32:08.696753997-06:00")
        assert parsed is not None
        assert parsed.minute == 32

    def test_rfc3339_zulu(self):
        parsed = _parse_ts("2026-07-24T05:21:54.123456789Z")
        assert parsed is not None
        assert parsed.hour == 5

    def test_zero_value_means_not_finished(self):
        """Both runtimes use year 1 for a container that has not exited."""
        assert _parse_ts("0001-01-01T00:00:00Z") is None

    def test_empty_and_garbage(self):
        assert _parse_ts("") is None
        assert _parse_ts("not a timestamp") is None


class TestPsJsonParsing:
    def test_podman_emits_json_array(self):
        stdout = json.dumps([{"Names": ["a"]}, {"Names": ["b"]}])
        assert len(ContainerBackend._parse_ps_json(stdout)) == 2

    def test_docker_emits_newline_delimited_objects(self):
        stdout = '{"Names":"a"}\n{"Names":"b"}\n'
        assert len(ContainerBackend._parse_ps_json(stdout)) == 2

    def test_single_object(self):
        assert len(ContainerBackend._parse_ps_json('{"Names":"a"}')) == 1

    def test_empty_and_malformed(self):
        assert ContainerBackend._parse_ps_json("") == []
        assert ContainerBackend._parse_ps_json("not json") == []

    def test_skips_malformed_lines_but_keeps_valid_ones(self):
        stdout = '{"Names":"a"}\ngarbage\n{"Names":"b"}'
        assert len(ContainerBackend._parse_ps_json(stdout)) == 2


class TestStatusNormalisation:
    def test_running(self):
        assert ContainerBackend._normalise_status({"State": "running"}) == STATUS_RUNNING

    def test_exited_zero_is_completed(self):
        entry = {"State": "exited", "ExitCode": 0}
        assert ContainerBackend._normalise_status(entry) == STATUS_COMPLETED

    def test_exited_nonzero_is_failed(self):
        entry = {"State": "exited", "ExitCode": 1}
        assert ContainerBackend._normalise_status(entry) == STATUS_FAILED

    def test_docker_status_string_fallback(self):
        """docker may omit ExitCode and encode it in the status text."""
        assert (
            ContainerBackend._normalise_status(
                {"State": "exited", "Status": "Exited (0) 2 minutes ago"}
            )
            == STATUS_COMPLETED
        )
        assert (
            ContainerBackend._normalise_status(
                {"State": "exited", "Status": "Exited (137) 1 minute ago"}
            )
            == STATUS_FAILED
        )

    def test_created_counts_as_running(self):
        """A created-but-not-started container has not failed."""
        assert ContainerBackend._normalise_status({"State": "created"}) == STATUS_RUNNING


class TestWorkloadMapping:
    def _entry(self, **labels):
        base = {
            LABEL_TARGET: "ora-01",
            LABEL_TARGET_HOST: "10.0.0.1",
            LABEL_DB_TYPE: "oracle",
            LABEL_INDEX: "3",
        }
        base.update(labels)
        return {
            "Names": ["hdb-run-03-t1"],
            "State": "exited",
            "ExitCode": 0,
            "Labels": base,
        }

    def test_maps_labels_onto_workload(self, backend, monkeypatch):
        monkeypatch.setattr(backend, "_duration", lambda name: 42)
        workload = backend._to_workload(self._entry())
        assert workload.name == "hdb-run-03-t1"
        assert workload.target_name == "ora-01"
        assert workload.target_host == "10.0.0.1"
        assert workload.database_type == "oracle"
        assert workload.index == 3
        assert workload.status == STATUS_COMPLETED
        assert workload.duration_seconds == 42

    def test_docker_string_labels(self, backend, monkeypatch):
        """docker may return Labels as a comma-separated string."""
        monkeypatch.setattr(backend, "_duration", lambda name: None)
        entry = {
            "Names": "hdb-run-01-t1",
            "State": "running",
            "Labels": f"{LABEL_TARGET}=sql-02,{LABEL_INDEX}=1",
        }
        workload = backend._to_workload(entry)
        assert workload.target_name == "sql-02"
        assert workload.index == 1

    def test_missing_labels_do_not_crash(self, backend, monkeypatch):
        monkeypatch.setattr(backend, "_duration", lambda name: None)
        workload = backend._to_workload({"Names": ["x"], "State": "running"})
        assert workload.target_name == "unknown"
        assert workload.index == 0

    def test_non_numeric_index_defaults_to_zero(self, backend, monkeypatch):
        monkeypatch.setattr(backend, "_duration", lambda name: None)
        workload = backend._to_workload(self._entry(**{LABEL_INDEX: "abc"}))
        assert workload.index == 0


class TestNaming:
    def test_matches_kubernetes_job_naming(self):
        """Names must line up with the Helm chart's job names."""
        assert ContainerBackend._container_name("run", 0, "abc") == "hdb-run-00-abc"
        assert ContainerBackend._container_name("build", 11, "abc") == "hdb-build-11-abc"
