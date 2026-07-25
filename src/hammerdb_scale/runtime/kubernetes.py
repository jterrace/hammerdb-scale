"""Kubernetes execution backend.

A thin adapter over the existing helm and kubectl code paths. It exists so the
CLI can treat Kubernetes and local containers uniformly; the underlying
behaviour is unchanged from before the backend abstraction was introduced.
"""

from __future__ import annotations

import shutil

from hammerdb_scale.constants import get_chart_path
from hammerdb_scale.helm.deployer import helm_install, helm_list, helm_uninstall
from hammerdb_scale.k8s.jobs import (
    discover_jobs,
    get_job_database_type,
    get_job_duration,
    get_job_logs,
    get_job_status,
    get_job_target_host,
    get_job_target_name,
)
from hammerdb_scale.k8s.naming import generate_release_name, generate_run_hash
from hammerdb_scale.runtime.base import WorkloadRef


class KubernetesBackend:
    """Runs HammerDB workloads as Kubernetes Jobs via Helm."""

    name = "kubernetes"

    def __init__(self, namespace: str, config=None) -> None:
        self.namespace = namespace
        self.config = config

    def preflight(self) -> list[str]:
        """Check that helm and kubectl are present and a cluster is reachable."""
        problems: list[str] = []
        for tool, url in (
            ("helm", "https://helm.sh/docs/intro/install/"),
            ("kubectl", "https://kubernetes.io/docs/tasks/tools/"),
        ):
            if not shutil.which(tool):
                problems.append(f"{tool} not found. Install from {url}")
        return problems

    def deploy(
        self,
        targets: list[dict],
        env_per_target: list[dict[str, str]],
        *,
        test_id: str,
        phase: str,
        benchmark: str,
        image: str,
        pull_policy: str = "Always",
        dry_run: bool = False,
    ) -> list[str]:
        """Install a Helm release that creates one Job per target.

        The Helm chart derives the container environment from values, so
        ``env_per_target`` is unused here. It stays in the signature because the
        container backend needs it and both must satisfy one protocol.
        """
        from hammerdb_scale.helm.values import generate_helm_values

        if self.config is None:
            raise ValueError("KubernetesBackend requires a config to render values")

        run_hash = generate_run_hash(self.config.name, test_id)
        release = generate_release_name(phase, run_hash)
        values = generate_helm_values(self.config, phase, benchmark, test_id)

        helm_install(release, get_chart_path(), self.namespace, values, dry_run=dry_run)

        helm_phase = "load" if phase == "run" else phase
        return [
            f"hdb-{helm_phase}-{i:02d}-{run_hash}" for i in range(len(targets))
        ]

    def list_workloads(
        self, test_id: str, phase: str | None = None
    ) -> list[WorkloadRef]:
        """Find Jobs belonging to a test run."""
        jobs = discover_jobs(self.namespace, test_id, phase=phase)
        workloads = []
        for job in jobs:
            annotations = job.get("metadata", {}).get("annotations", {})
            try:
                index = int(annotations.get("hammerdb.io/target-index", 0))
            except (TypeError, ValueError):
                index = 0
            workloads.append(
                WorkloadRef(
                    name=job.get("metadata", {}).get("name", ""),
                    target_name=get_job_target_name(job),
                    target_host=get_job_target_host(job),
                    database_type=get_job_database_type(job),
                    index=index,
                    status=get_job_status(job),
                    duration_seconds=get_job_duration(job),
                )
            )
        return sorted(workloads, key=lambda w: w.index)

    def get_logs(self, workload_name: str, tail: int | None = None) -> str:
        """Fetch logs from a Job's pod."""
        return get_job_logs(self.namespace, workload_name, tail=tail)

    def remove(self, test_id: str | None = None, everything: bool = False) -> int:
        """Uninstall Helm releases for a test run, or all managed releases."""
        releases = helm_list(self.namespace)
        removed = 0
        for release in releases:
            name = release.get("name", "")
            if not name.startswith("hdb-"):
                continue
            if not everything and test_id:
                jobs = discover_jobs(self.namespace, test_id)
                job_names = {j.get("metadata", {}).get("name", "") for j in jobs}
                if not any(name in jn for jn in job_names):
                    continue
            try:
                helm_uninstall(name, self.namespace)
                removed += 1
            except Exception:
                continue
        return removed
