"""K8s/Helm resource cleanup (--resources scope)."""

from __future__ import annotations

import typer

from hammerdb_scale.helm.deployer import helm_list, helm_uninstall
from hammerdb_scale.output import console, print_error, print_success, print_warning
from hammerdb_scale.results.storage import results_exist


def clean_container_resources(
    backend,
    test_id: str | None = None,
    everything: bool = False,
    force: bool = False,
    results_dir=None,
) -> None:
    """Remove containers created by the container backend."""
    from pathlib import Path

    if results_dir is None:
        results_dir = Path("./results")

    workloads = backend.list_workloads(test_id) if test_id else []
    if everything:
        console.print("\nRemoving all hammerdb-scale containers.")
    elif not workloads:
        console.print("No containers found to clean.")
        return
    else:
        console.print(f"\nFound {len(workloads)} container(s):")
        for w in workloads:
            console.print(f"  {w.name} ({w.status})")

    if test_id and not results_exist(test_id, results_dir) and not force:
        print_warning(
            f"Results for test '{test_id}' have not been aggregated.\n"
            f"      Run 'hammerdb-scale results --id {test_id}' first,\n"
            f"      or use --force to proceed without aggregating."
        )
        if not typer.confirm("\nProceed anyway?"):
            raise typer.Abort()

    if not force:
        if not typer.confirm("\nRemove these containers?"):
            raise typer.Abort()

    removed = backend.remove(test_id=test_id, everything=everything)
    print_success(f"Removed {removed} container(s)")
    console.print("\nContainers cleaned. Local results preserved in ./results/")


def clean_resources(
    namespace: str,
    test_id: str | None = None,
    everything: bool = False,
    force: bool = False,
    results_dir=None,
) -> None:
    """Remove K8s Helm releases and jobs."""
    from pathlib import Path

    if results_dir is None:
        results_dir = Path("./results")

    if everything:
        releases = helm_list(namespace)
    elif test_id:
        # Find releases matching the test ID
        all_releases = helm_list(namespace)
        releases = [
            r
            for r in all_releases
            if test_id in r.get("name", "") or test_id in str(r.get("app_version", ""))
        ]
        # Also try by hash pattern
        if not releases:
            releases = all_releases  # Fall back to showing all
    else:
        console.print(
            "[red]Specify --id or --everything to indicate which releases to remove.[/red]"
        )
        raise typer.Exit(1)

    if not releases:
        console.print("No Helm releases found to clean.")
        return

    # Show what will be removed
    console.print(f"\nFound {len(releases)} release(s):")
    for r in releases:
        console.print(f"  {r.get('name', 'unknown')} ({r.get('status', 'unknown')})")

    if test_id and not results_exist(test_id, results_dir) and not force:
        print_warning(
            f"Results for test '{test_id}' have not been aggregated.\n"
            f"      Run 'hammerdb-scale results --id {test_id}' first,\n"
            f"      or use --force to proceed without aggregating."
        )
        if not typer.confirm("\nProceed anyway?"):
            raise typer.Abort()

    # Confirm
    if not force:
        if not typer.confirm("\nRemove these releases?"):
            raise typer.Abort()

    # Uninstall each release
    for r in releases:
        release_name = r.get("name", "")
        try:
            helm_uninstall(release_name, namespace)
            print_success(f"Uninstalled {release_name}")
        except Exception as e:
            print_error(f"Failed to uninstall {release_name}: {e}")

    console.print("\nK8s resources cleaned. Local results preserved in ./results/")
