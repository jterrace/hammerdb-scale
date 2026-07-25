"""Backend protocol shared by the Kubernetes and container execution paths.

A backend is responsible for turning a set of expanded targets into running
HammerDB workloads and for reporting on them afterwards. Everything above this
layer (config parsing, result parsing, aggregation, reporting) is transport
agnostic and must not import backend-specific modules.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


# Job lifecycle states, normalised across backends. The Kubernetes backend maps
# Job conditions onto these; the container backend maps exit codes.
STATUS_PENDING = "Pending"
STATUS_RUNNING = "Running"
STATUS_COMPLETED = "Completed"
STATUS_FAILED = "Failed"


@dataclass
class WorkloadRef:
    """A single running or completed HammerDB workload.

    This is the backend-neutral view of what Kubernetes calls a Job and what
    the container backend calls a container.
    """

    name: str
    target_name: str
    target_host: str
    database_type: str
    index: int
    status: str
    duration_seconds: int | None = None


@runtime_checkable
class Backend(Protocol):
    """Execution backend for HammerDB workloads."""

    name: str

    def deploy(
        self,
        targets: list[dict],
        env_per_target: list[dict[str, str]],
        *,
        test_id: str,
        phase: str,
        benchmark: str,
        image: str,
        pull_policy: str,
        dry_run: bool = False,
    ) -> list[str]:
        """Start one workload per target. Returns the workload names created."""
        ...

    def list_workloads(
        self, test_id: str, phase: str | None = None
    ) -> list[WorkloadRef]:
        """Find all workloads belonging to a test run, newest phase first."""
        ...

    def get_logs(self, workload_name: str, tail: int | None = None) -> str:
        """Fetch the full stdout/stderr of a workload."""
        ...

    def remove(self, test_id: str | None = None, everything: bool = False) -> int:
        """Remove workloads for a test run. Returns the count removed."""
        ...

    def preflight(self) -> list[str]:
        """Check that this backend can run. Returns a list of problems, empty if OK."""
        ...
