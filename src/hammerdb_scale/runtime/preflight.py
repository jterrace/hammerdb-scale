"""In-cluster connectivity checking.

``validate`` normally tests database reachability from the workstation, but the
benchmark runs from inside a pod or container. Those are different network
positions: a config can pass validation cleanly and then have every job fail on
connectivity, which is the worst kind of failure because it arrives late and
points nowhere useful.

This module runs the same reachability test from where the workload will
actually run.
"""

from __future__ import annotations

import json
import subprocess

# Plain TCP connect, no database client needed, so this works with any image.
_PROBE = r"""
import json, socket, sys
results = []
for name, host, port in json.loads(sys.argv[1]):
    try:
        s = socket.create_connection((host, int(port)), timeout=8)
        s.close()
        results.append({"name": name, "ok": True, "error": ""})
    except Exception as exc:
        results.append({"name": name, "ok": False, "error": str(exc)})
print("PROBE_RESULT:" + json.dumps(results))
"""


# Fallback listening port per database type, used only when the config does
# not carry one. Probing the wrong port reports a healthy fleet as unreachable,
# which reads as "the tool is broken" rather than "the check is wrong".
_DEFAULT_PORTS = {"oracle": 1521, "mssql": 1433, "postgres": 5432}


def _target_endpoints(config) -> list[tuple[str, str, int]]:
    """Build (name, host, port) for every target."""
    from hammerdb_scale.config.defaults import expand_targets

    defaults = config.targets.defaults
    endpoints = []
    for target in expand_targets(config):
        db_type = target["type"]
        fallback = _DEFAULT_PORTS.get(db_type, 1433)

        # The per-target block wins; then the shared defaults block for that
        # database; then the well-known port.
        port = (target.get(db_type) or {}).get("port")
        if port is None:
            block = getattr(defaults, db_type, None)
            port = getattr(block, "port", None) if block else None
        endpoints.append((target["name"], target["host"], int(port or fallback)))
    return endpoints


def _parse_probe_output(stdout: str) -> list[dict] | None:
    """Pull the JSON result line out of pod or container output."""
    for line in stdout.splitlines():
        line = line.strip()
        if line.startswith("PROBE_RESULT:"):
            try:
                return json.loads(line[len("PROBE_RESULT:") :])
            except json.JSONDecodeError:
                return None
    return None


def check_from_kubernetes(config, namespace: str, image: str) -> list[dict]:
    """Run the probe as a one-shot pod in the target namespace.

    Uses the benchmark image so the test traverses the same network path,
    namespace and policies the real jobs will.
    """
    endpoints = _target_endpoints(config)
    payload = json.dumps([[n, h, p] for n, h, p in endpoints])

    overrides = json.dumps(
        {
            "spec": {
                "securityContext": {
                    "runAsNonRoot": True,
                    "seccompProfile": {"type": "RuntimeDefault"},
                },
                "containers": [
                    {
                        "name": "preflight",
                        "image": image,
                        "command": ["python3", "-c", _PROBE, payload],
                        "securityContext": {
                            "allowPrivilegeEscalation": False,
                            "capabilities": {"drop": ["ALL"]},
                        },
                    }
                ],
            }
        }
    )

    result = subprocess.run(
        [
            "kubectl",
            "run",
            "hammerdb-preflight",
            "-n",
            namespace,
            "--rm",
            "--attach",
            "--restart=Never",
            "--quiet",
            f"--image={image}",
            "--override-type=strategic",
            f"--overrides={overrides}",
            "--command",
            "--",
            "python3",
            "-c",
            _PROBE,
            payload,
        ],
        capture_output=True,
        text=True,
        timeout=300,
    )

    parsed = _parse_probe_output(result.stdout)
    if parsed is None:
        detail = (result.stderr or result.stdout or "no output").strip()
        raise RuntimeError(f"In-cluster probe produced no result: {detail[:400]}")
    return parsed


def check_from_container(config, runtime: str, image: str) -> list[dict]:
    """Run the probe in a local container using the benchmark image."""
    endpoints = _target_endpoints(config)
    payload = json.dumps([[n, h, p] for n, h, p in endpoints])

    result = subprocess.run(
        [
            runtime,
            "run",
            "--rm",
            "--entrypoint",
            "python3",
            image,
            "-c",
            _PROBE,
            payload,
        ],
        capture_output=True,
        text=True,
        timeout=300,
    )

    parsed = _parse_probe_output(result.stdout)
    if parsed is None:
        detail = (result.stderr or result.stdout or "no output").strip()
        raise RuntimeError(f"Container probe produced no result: {detail[:400]}")
    return parsed
