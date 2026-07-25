"""Container execution backend for podman and docker.

Runs one HammerDB container per database target on the local host, with no
Kubernetes involved. This is the low-friction path: a user needs a container
runtime and a config file rather than a cluster, a kubeconfig, helm, kubectl
and RBAC to create Jobs.

podman and docker expose a compatible CLI for everything used here, so a single
implementation drives both. podman is preferred when present because it is
rootless and daemonless.

Labels carry the same metadata the Kubernetes backend puts in Job labels, which
is what lets test-id resolution, status and log retrieval behave identically on
either backend.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from hammerdb_scale.constants import PHASE_MAP, HammerDBScaleError, get_chart_path
from hammerdb_scale.runtime.base import (
    STATUS_COMPLETED,
    STATUS_FAILED,
    STATUS_RUNNING,
    WorkloadRef,
)

# Label keys, mirroring the Kubernetes label scheme.
LABEL_MANAGED = "hammerdb.io/managed-by"
LABEL_TEST_ID = "hammerdb.io/test-id"
LABEL_PHASE = "hammerdb.io/phase"
LABEL_TARGET = "hammerdb.io/target-name"
LABEL_TARGET_HOST = "hammerdb.io/target-host"
LABEL_DB_TYPE = "hammerdb.io/database-type"
LABEL_INDEX = "hammerdb.io/target-index"

MANAGED_VALUE = "hammerdb-scale"


class ContainerRuntimeError(HammerDBScaleError):
    """The container runtime is missing or a command against it failed."""


def detect_runtime(preferred: str | None = None) -> str:
    """Find an available container runtime.

    Prefers podman (rootless, daemonless) over docker unless told otherwise.
    """
    candidates = [preferred] if preferred else ["podman", "docker"]
    for name in candidates:
        if name and shutil.which(name):
            return name
    raise ContainerRuntimeError(
        "No container runtime found. Install podman "
        "(https://podman.io/getting-started/installation) or docker "
        "(https://docs.docker.com/get-docker/), or set backend: kubernetes."
    )


class ContainerBackend:
    """Runs HammerDB workloads as local containers."""

    def __init__(
        self,
        runtime: str | None = None,
        network: str | None = None,
        scripts_dir: Path | None = None,
    ) -> None:
        self.runtime = detect_runtime(runtime)
        self.name = self.runtime
        self.network = network
        self._scripts_dir = scripts_dir

    # --- internals ---

    def _run(
        self, args: list[str], timeout: int = 300, check: bool = True
    ) -> subprocess.CompletedProcess:
        """Invoke the container runtime CLI."""
        result = subprocess.run(
            [self.runtime] + args,
            capture_output=True,
            text=True,
            timeout=timeout,
            encoding="utf-8",
            errors="replace",
        )
        if check and result.returncode != 0:
            raise ContainerRuntimeError(
                f"{self.runtime} {' '.join(args[:3])} failed:\n{result.stderr.strip()}"
            )
        return result

    def _scripts_path(self, database_type: str) -> Path:
        """Locate the TCL scripts for a database type.

        These are the same files the Helm chart packages into a ConfigMap, so
        both backends execute identical benchmark logic.
        """
        base = self._scripts_dir or (Path(get_chart_path()) / "scripts")
        path = base / database_type
        if not path.is_dir():
            raise ContainerRuntimeError(
                f"No TCL scripts found for database type '{database_type}' at {path}"
            )
        return path

    @staticmethod
    def _normalise_phase(phase: str) -> str:
        """Map the CLI phase onto the label the Kubernetes path records.

        The CLI says "run" but Helm and the entrypoint both record "load".
        Containers must use the same vocabulary or callers that filter by phase
        silently find nothing.
        """
        return PHASE_MAP.get(phase, phase)

    @classmethod
    def _container_name(cls, phase: str, index: int, test_id: str) -> str:
        return f"hdb-{cls._normalise_phase(phase)}-{index:02d}-{test_id}"

    # --- Backend protocol ---

    def preflight(self) -> list[str]:
        """Verify the runtime responds before we try to deploy against it."""
        problems: list[str] = []
        try:
            result = self._run(["version", "--format", "{{.Client.Version}}"],
                               timeout=30, check=False)
            if result.returncode != 0:
                # Older podman/docker may not support that format string.
                result = self._run(["--version"], timeout=30, check=False)
            if result.returncode != 0:
                problems.append(
                    f"{self.runtime} is installed but not responding: "
                    f"{result.stderr.strip()}"
                )
        except Exception as e:
            problems.append(f"Could not run {self.runtime}: {e}")
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
        """Start one detached container per target."""
        if pull_policy == "Always" and not dry_run:
            self._run(["pull", image], timeout=1800, check=False)

        label_phase = self._normalise_phase(phase)
        names: list[str] = []
        for index, (target, env) in enumerate(zip(targets, env_per_target)):
            name = self._container_name(phase, index, test_id)
            scripts = self._scripts_path(target["type"])

            args = [
                "run",
                "--detach",
                "--name",
                name,
                "--label", f"{LABEL_MANAGED}={MANAGED_VALUE}",
                "--label", f"{LABEL_TEST_ID}={test_id}",
                "--label", f"{LABEL_PHASE}={label_phase}",
                "--label", f"{LABEL_TARGET}={target['name']}",
                "--label", f"{LABEL_TARGET_HOST}={target['host']}",
                "--label", f"{LABEL_DB_TYPE}={target['type']}",
                "--label", f"{LABEL_INDEX}={index}",
            ]

            if self.network:
                args.extend(["--network", self.network])

            # Env vars go via a file so that passwords never appear in the
            # process list or the shell history of the calling user.
            env_file = tempfile.NamedTemporaryFile(
                mode="w", suffix=".env", delete=False, encoding="utf-8"
            )
            try:
                for key, value in env.items():
                    env_file.write(f"{key}={value}\n")
                env_file.close()
                args.extend(["--env-file", env_file.name])

                # Mount the TCL scripts where entrypoint.sh expects them. The
                # :ro,z suffix keeps SELinux hosts working; docker ignores z.
                mount_target = self._script_mount_target(image)
                args.extend(["-v", f"{scripts}:{mount_target}:ro,z"])
                args.append(image)

                if dry_run:
                    redacted = [
                        a if not a.startswith("/tmp/") else "<env-file>" for a in args
                    ]
                    print(f"{self.runtime} " + " ".join(redacted))
                    names.append(name)
                    continue

                self._run(args, timeout=120)
                names.append(name)
            finally:
                if not dry_run:
                    Path(env_file.name).unlink(missing_ok=True)

        return names

    def _script_mount_target(self, image: str) -> str:
        """Where inside the container the TCL scripts must appear.

        The image's HAMMERDB_HOME tells us; fall back to the historical 5.0
        path for images built before that variable existed.
        """
        result = self._run(
            ["image", "inspect", image, "--format", "{{range .Config.Env}}{{println .}}{{end}}"],
            timeout=60,
            check=False,
        )
        if result.returncode == 0:
            for line in result.stdout.splitlines():
                if line.startswith("HAMMERDB_HOME="):
                    home = line.split("=", 1)[1].strip()
                    if home:
                        return f"{home}/scripts"
        return "/opt/HammerDB-5.0/scripts"

    def list_workloads(
        self, test_id: str, phase: str | None = None
    ) -> list[WorkloadRef]:
        """Find containers for a test run."""
        filters = [
            "--filter", f"label={LABEL_MANAGED}={MANAGED_VALUE}",
            "--filter", f"label={LABEL_TEST_ID}={test_id}",
        ]
        if phase:
            filters.extend(
                ["--filter", f"label={LABEL_PHASE}={self._normalise_phase(phase)}"]
            )

        result = self._run(
            ["ps", "--all", "--format", "json"] + filters, check=False
        )
        if result.returncode != 0 or not result.stdout.strip():
            return []

        entries = self._parse_ps_json(result.stdout)
        workloads = [self._to_workload(e) for e in entries]
        return sorted(workloads, key=lambda w: w.index)

    @staticmethod
    def _parse_ps_json(stdout: str) -> list[dict]:
        """Parse `ps --format json`.

        podman emits a JSON array; docker emits newline-delimited objects.
        """
        text = stdout.strip()
        try:
            data = json.loads(text)
            return data if isinstance(data, list) else [data]
        except json.JSONDecodeError:
            pass

        entries = []
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return entries

    def _to_workload(self, entry: dict) -> WorkloadRef:
        """Normalise a runtime-specific ps entry into a WorkloadRef."""
        labels = entry.get("Labels") or {}
        if isinstance(labels, str):
            labels = dict(
                pair.split("=", 1) for pair in labels.split(",") if "=" in pair
            )

        name = entry.get("Names") or entry.get("Name") or ""
        if isinstance(name, list):
            name = name[0] if name else ""

        try:
            index = int(labels.get(LABEL_INDEX, 0))
        except (TypeError, ValueError):
            index = 0

        return WorkloadRef(
            name=name,
            target_name=labels.get(LABEL_TARGET, "unknown"),
            target_host=labels.get(LABEL_TARGET_HOST, "unknown"),
            database_type=labels.get(LABEL_DB_TYPE, "unknown"),
            index=index,
            status=self._normalise_status(entry),
            duration_seconds=self._duration(name),
        )

    @staticmethod
    def _normalise_status(entry: dict) -> str:
        """Map runtime state onto the shared status vocabulary."""
        state = str(entry.get("State", "")).lower()
        exit_code = entry.get("ExitCode")

        if state in ("running", "up"):
            return STATUS_RUNNING
        if state in ("created", "paused"):
            return STATUS_RUNNING
        if state in ("exited", "stopped", "dead"):
            # docker sometimes reports status as "Exited (1) 2 minutes ago"
            if exit_code is None:
                status_text = str(entry.get("Status", ""))
                exit_code = 0 if "(0)" in status_text else 1
            return STATUS_COMPLETED if int(exit_code) == 0 else STATUS_FAILED
        return STATUS_RUNNING

    def _duration(self, container_name: str) -> int | None:
        """Wall-clock runtime of a container, in seconds."""
        if not container_name:
            return None
        # Ask for RFC3339 explicitly. podman's default rendering of these
        # fields is Go's native time format ("2026-07-24 23:32:08.69 -0600 MDT"),
        # which is not parseable as ISO 8601.
        result = self._run(
            [
                "inspect",
                container_name,
                "--format",
                "{{.State.StartedAt.Format "
                '"2006-01-02T15:04:05.999999999Z07:00"'
                "}}|{{.State.FinishedAt.Format "
                '"2006-01-02T15:04:05.999999999Z07:00"'
                "}}",
            ],
            timeout=30,
            check=False,
        )
        if result.returncode != 0:
            # docker exposes these as pre-formatted strings, so .Format fails.
            result = self._run(
                [
                    "inspect",
                    container_name,
                    "--format",
                    "{{.State.StartedAt}}|{{.State.FinishedAt}}",
                ],
                timeout=30,
                check=False,
            )
        if result.returncode != 0:
            return None

        raw = result.stdout.strip()
        if "|" not in raw:
            return None
        start_s, end_s = raw.split("|", 1)
        start = _parse_ts(start_s)
        end = _parse_ts(end_s)
        if not start:
            return None
        if not end:
            end = datetime.now(timezone.utc)
        seconds = int((end - start).total_seconds())
        return seconds if seconds >= 0 else None

    def get_logs(self, workload_name: str, tail: int | None = None) -> str:
        """Fetch container logs."""
        args = ["logs"]
        if tail is not None:
            args.extend(["--tail", str(tail)])
        args.append(workload_name)
        result = self._run(args, timeout=120, check=False)
        # HammerDB writes to both streams; callers want the combined output.
        return (result.stdout or "") + (result.stderr or "")

    def remove(self, test_id: str | None = None, everything: bool = False) -> int:
        """Remove containers for a test run, or every managed container."""
        filters = ["--filter", f"label={LABEL_MANAGED}={MANAGED_VALUE}"]
        if test_id and not everything:
            filters.extend(["--filter", f"label={LABEL_TEST_ID}={test_id}"])

        result = self._run(
            ["ps", "--all", "--quiet"] + filters, check=False
        )
        ids = [line.strip() for line in result.stdout.splitlines() if line.strip()]
        if not ids:
            return 0

        self._run(["rm", "--force"] + ids, timeout=180, check=False)
        return len(ids)

    def wait(self, workload_names: list[str], timeout: int) -> None:
        """Block until the given containers exit, or the timeout elapses."""
        if not workload_names:
            return
        self._run(["wait"] + workload_names, timeout=timeout, check=False)

    def find_test_ids(self) -> list[str]:
        """List test IDs that have managed containers, most recent first."""
        result = self._run(
            [
                "ps",
                "--all",
                "--filter",
                f"label={LABEL_MANAGED}={MANAGED_VALUE}",
                "--format",
                "json",
            ],
            check=False,
        )
        if result.returncode != 0 or not result.stdout.strip():
            return []

        seen: list[str] = []
        for entry in self._parse_ps_json(result.stdout):
            labels = entry.get("Labels") or {}
            if isinstance(labels, str):
                labels = dict(
                    pair.split("=", 1) for pair in labels.split(",") if "=" in pair
                )
            test_id = labels.get(LABEL_TEST_ID)
            if test_id and test_id not in seen:
                seen.append(test_id)
        return seen


def _parse_ts(value: str) -> datetime | None:
    """Parse a container runtime timestamp.

    Both runtimes emit RFC3339 with varying sub-second precision, and use a
    zero value for containers that have not finished.
    """
    value = value.strip()
    if not value or value.startswith("0001-01-01"):
        return None

    # Go's native time rendering, e.g. "2026-07-24 23:32:08.6967 -0600 MDT".
    # Drop the trailing timezone abbreviation and keep the numeric offset.
    parts = value.split()
    if len(parts) >= 3 and ":" in parts[1] and (
        parts[2].startswith("+") or parts[2].startswith("-")
    ):
        value = f"{parts[0]}T{parts[1]}{parts[2]}"

    text = value.replace("Z", "+00:00")
    # Trim sub-second precision beyond microseconds, which fromisoformat rejects
    # on older Python versions.
    if "." in text:
        head, _, tail = text.partition(".")
        digits = ""
        rest = ""
        for i, ch in enumerate(tail):
            if ch.isdigit():
                digits += ch
            else:
                rest = tail[i:]
                break
        text = f"{head}.{digits[:6]}{rest}"

    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed
