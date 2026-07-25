"""Tests that the HammerDB version stays consistent across image and chart.

The version appears in three coupled places: ARG HAMMERDB_VERSION in the
Dockerfile, the chart's script mountPath, and DEFAULT_HAMMERDB_HOME. If the
image installs to one path and the chart mounts scripts at another, containers
start and then fail to find their TCL scripts, which is a confusing runtime
failure rather than a build error.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from hammerdb_scale.constants import (
    DEFAULT_HAMMERDB_HOME,
    DEFAULT_HAMMERDB_VERSION,
    PUBLISHED_HAMMERDB_VERSION,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
CHART_TEMPLATE = "templates/job-hammerdb-worker.yaml"


def _dockerfile_version() -> str:
    text = (REPO_ROOT / "Dockerfile").read_text()
    match = re.search(r"^ARG HAMMERDB_VERSION=(\S+)", text, re.MULTILINE)
    assert match, "Dockerfile must declare ARG HAMMERDB_VERSION"
    return match.group(1)


class TestVersionConsistency:
    def test_dockerfile_matches_constants(self):
        assert _dockerfile_version() == DEFAULT_HAMMERDB_VERSION

    def test_home_tracks_the_published_image(self):
        """The chart default must point at a path the published image has.

        Regression: the default moved to 6.0 while the published image was
        still 5.0, so every out-of-the-box Kubernetes run mounted scripts into
        a directory the entrypoint never looked in and failed with
        "script not found".
        """
        assert DEFAULT_HAMMERDB_HOME == f"/opt/HammerDB-{PUBLISHED_HAMMERDB_VERSION}"

    def test_chart_fallback_matches_constants(self):
        """The chart's default mountPath must match where the image installs."""
        for chart_dir in ("", "src/hammerdb_scale/chart/"):
            template = (REPO_ROOT / chart_dir / CHART_TEMPLATE).read_text()
            match = re.search(r'default "(/opt/HammerDB-[^"]+)"', template)
            assert match, f"{chart_dir}{CHART_TEMPLATE} must have a mountPath default"
            assert match.group(1) == DEFAULT_HAMMERDB_HOME


class TestNoHardcodedPaths:
    """A hardcoded version defeats the point of the indirection."""

    @pytest.mark.parametrize(
        "relative_path",
        ["entrypoint.sh", "Dockerfile", "Dockerfile.oracle"],
    )
    def test_no_versioned_hammerdb_paths(self, relative_path):
        text = (REPO_ROOT / relative_path).read_text()
        offenders = [
            line.strip()
            for line in text.splitlines()
            # Comments may legitimately mention a version by way of example.
            if "/opt/HammerDB-5" in line and not line.strip().startswith("#")
        ]
        assert not offenders, f"{relative_path} has hardcoded paths: {offenders}"

    def test_entrypoint_uses_hammerdb_home(self):
        text = (REPO_ROOT / "entrypoint.sh").read_text()
        assert "HAMMERDB_HOME" in text
        assert '"$HAMMERDB_HOME/hammerdbcli"' in text
        assert "$SCRIPT_DIR/" in text

    def test_entrypoint_falls_back_when_home_unset(self):
        """Older images have no HAMMERDB_HOME, so a glob probe is required."""
        text = (REPO_ROOT / "entrypoint.sh").read_text()
        assert "for candidate in /opt/HammerDB-*" in text

    def test_entrypoint_searches_for_mounted_scripts(self):
        """The script mount path and HAMMERDB_HOME are set independently.

        The chart chooses the mount path; the image bakes in HAMMERDB_HOME.
        Requiring them to agree means a chart/image version skew produces a
        confusing "script not found" at runtime, so the entrypoint searches.
        """
        text = (REPO_ROOT / "entrypoint.sh").read_text()
        assert 'for candidate in "$HAMMERDB_HOME/scripts" /opt/HammerDB-*/scripts' in text
        assert "HAMMERDB_SCRIPT_DIR" in text

    def test_oracle_client_check_is_version_agnostic(self):
        """A client upgrade must not require editing the entrypoint."""
        text = (REPO_ROOT / "entrypoint.sh").read_text()
        assert "instantclient_21_11" not in text
        assert "/opt/oracle/instantclient_*" in text


class TestChartIsNotDuplicated:
    """The repo-root chart paths must be symlinks into the packaged chart.

    They used to be real duplicates, and they had already drifted:
    collect_pure_metrics.py differed between the two copies. Because
    get_chart_path() prefers the packaged copy, a fix applied only at the repo
    root would never reach anyone installing from PyPI. Symlinks make the
    packaged chart the single source of truth while keeping `helm ... .`
    working from the repo root.
    """

    @pytest.mark.parametrize(
        "entry", ["templates", "scripts", "Chart.yaml", "values.yaml"]
    )
    def test_repo_root_entry_is_a_symlink(self, entry):
        path = REPO_ROOT / entry
        assert path.is_symlink(), (
            f"{entry} should be a symlink into src/hammerdb_scale/chart/, "
            f"not a second copy that can drift"
        )
        assert path.resolve() == (REPO_ROOT / "src/hammerdb_scale/chart" / entry).resolve()

    def test_both_paths_reach_the_same_template(self):
        root = (REPO_ROOT / CHART_TEMPLATE).read_text()
        packaged = (REPO_ROOT / "src/hammerdb_scale/chart" / CHART_TEMPLATE).read_text()
        assert root == packaged
