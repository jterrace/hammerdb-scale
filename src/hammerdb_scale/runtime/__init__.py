"""Execution backends for HammerDB workloads.

``get_backend()`` is the single entry point the CLI uses to obtain a backend.
"""

from __future__ import annotations

from hammerdb_scale.runtime.base import (
    STATUS_COMPLETED,
    STATUS_FAILED,
    STATUS_PENDING,
    STATUS_RUNNING,
    Backend,
    WorkloadRef,
)

__all__ = [
    "Backend",
    "WorkloadRef",
    "STATUS_PENDING",
    "STATUS_RUNNING",
    "STATUS_COMPLETED",
    "STATUS_FAILED",
    "get_backend",
]


def get_backend(config, namespace: str | None = None) -> Backend:
    """Build the backend selected by the config.

    Kubernetes remains the default so that existing configs behave exactly as
    they did before backends were introduced.
    """
    backend_name = getattr(config, "backend", "kubernetes")
    backend_name = getattr(backend_name, "value", backend_name)

    if backend_name in ("container", "docker", "podman"):
        from hammerdb_scale.runtime.container import ContainerBackend

        container_cfg = getattr(config, "container", None)
        runtime = getattr(container_cfg, "runtime", None)
        runtime = getattr(runtime, "value", runtime)
        if runtime == "auto":
            runtime = None
        # An explicit `backend: docker` or `backend: podman` names the runtime.
        if backend_name in ("docker", "podman"):
            runtime = backend_name

        return ContainerBackend(
            runtime=runtime,
            network=getattr(container_cfg, "network", None),
            hammerdb_home=config.targets.defaults.image.hammerdb_home,
        )

    from hammerdb_scale.runtime.kubernetes import KubernetesBackend

    ns = namespace or config.kubernetes.namespace
    return KubernetesBackend(namespace=ns, config=config)
