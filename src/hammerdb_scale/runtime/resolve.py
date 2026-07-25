"""Backend-agnostic test-run resolution and completion waiting.

The Kubernetes path resolves a test ID by inspecting Helm releases; the
container path inspects container labels. Both then fall back to the local
results directory. Keeping that logic here means CLI commands do not branch on
backend type.
"""

from __future__ import annotations

import time
from pathlib import Path

from hammerdb_scale.constants import POLL_INTERVAL, NoResultsError
from hammerdb_scale.output import console, print_error, print_success, print_warning
from hammerdb_scale.runtime.base import STATUS_COMPLETED, STATUS_FAILED


def resolve_test_id(
    backend,
    cli_id: str | None,
    *,
    results_dir: Path = Path("./results"),
    deployment_name: str | None = None,
) -> str:
    """Decide which test run a command should act on.

    Order of precedence: an explicit --id, then the most recent run the backend
    knows about, then the most recent locally stored results.
    """
    if cli_id:
        return cli_id

    backend_id = _find_backend_test_id(backend, deployment_name)
    if backend_id:
        return backend_id

    local_ids = _find_local_test_ids(results_dir)
    if deployment_name and len(local_ids) > 1:
        filtered = [t for t in local_ids if t.startswith(deployment_name + "-")]
        if filtered:
            local_ids = filtered

    if local_ids:
        return sorted(local_ids)[-1]

    raise NoResultsError(
        "No test runs found. Run a benchmark first, or pass --id explicitly."
    )


def _find_backend_test_id(backend, deployment_name: str | None) -> str | None:
    """Ask the backend for its most recent test ID.

    A backend that cannot be queried is not the same as a backend with no
    runs, so the reason is surfaced as a warning rather than swallowed. The
    caller still falls back to locally stored results.
    """
    finder = getattr(backend, "find_test_ids", None)
    if finder is not None:
        try:
            for test_id in finder():
                if deployment_name and not test_id.startswith(deployment_name + "-"):
                    continue
                return test_id
        except Exception as e:
            print_warning(f"Could not list runs from {backend.name}: {e}")
        return None

    # Kubernetes backend: reuse the existing Helm-release-based lookup.
    try:
        from hammerdb_scale.k8s.jobs import _find_most_recent_k8s_test_id

        return _find_most_recent_k8s_test_id(backend.namespace, deployment_name)
    except Exception as e:
        print_warning(f"Could not list runs from Kubernetes: {e}")
        return None


def _find_local_test_ids(results_dir: Path) -> list[str]:
    """Scan the results directory for previously stored runs."""
    if not results_dir.exists():
        return []
    return [
        d.name
        for d in results_dir.iterdir()
        if d.is_dir() and (d / "summary.json").exists()
    ]


def wait_for_completion(
    backend,
    test_id: str,
    phase: str,
    timeout: int,
    *,
    show_errors: bool = True,
) -> bool:
    """Poll until every workload finishes or the timeout elapses.

    Returns True only if all workloads completed successfully. On failure the
    error extracted from each failing workload's log is printed, so the user
    does not have to go and read logs to find out what went wrong.
    """
    start = time.time()
    while time.time() - start < timeout:
        workloads = backend.list_workloads(test_id, phase=phase)
        if not workloads:
            time.sleep(POLL_INTERVAL)
            continue

        completed = sum(1 for w in workloads if w.status == STATUS_COMPLETED)
        failed = sum(1 for w in workloads if w.status == STATUS_FAILED)
        total = len(workloads)

        console.print(
            f"  [{completed}/{total}] completed, {failed} failed", end="\r"
        )

        if completed + failed >= total:
            console.print()
            for w in workloads:
                if w.status == STATUS_FAILED:
                    print_error(f"{w.target_name} Failed")
                    if show_errors:
                        _print_failure_reason(backend, w)
                else:
                    print_success(f"{w.target_name} {w.status}")
            return failed == 0

        time.sleep(POLL_INTERVAL)

    console.print(f"\n[yellow]Timeout ({timeout}s) reached.[/yellow]")
    return False


def _print_failure_reason(backend, workload) -> None:
    """Surface the database error inline instead of making the user dig."""
    try:
        from hammerdb_scale.results.parsers import get_parser

        log_text = backend.get_logs(workload.name, tail=200)
        if not log_text:
            return
        try:
            error = get_parser(workload.database_type).detect_error(log_text)
        except ValueError:
            error = None
        if error:
            console.print(f"      [red]{error.strip()}[/red]")
        console.print(
            f"      [dim]Full log: hammerdb-scale logs --target {workload.target_name}[/dim]"
        )
    except Exception:
        return
