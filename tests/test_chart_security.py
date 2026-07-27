"""Tests for credential handling and pod security in the rendered chart.

These render the real chart with `helm template` and assert on the output, so
they catch template regressions that unit tests on the values dict cannot.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

from hammerdb_scale.config.loader import load_config
from hammerdb_scale.helm.values import generate_helm_values

REPO_ROOT = Path(__file__).resolve().parent.parent
CHART = REPO_ROOT / "src/hammerdb_scale/chart"

PASSWORD = "sup3rs3cret"

CONFIG = f"""
name: sectest
default_benchmark: tprocc
targets:
  defaults:
    type: oracle
    username: system
    password: "{PASSWORD}"
    oracle:
      service: TPCC
      tprocc:
        user: TPCC
        password: "{PASSWORD}"
  hosts:
    - name: t1
      host: "10.0.0.1"
    - name: t2
      host: "10.0.0.2"
"""

pytestmark = pytest.mark.skipif(
    shutil.which("helm") is None, reason="helm not installed"
)


def _render(tmp_path, **overrides) -> list[dict]:
    """Render the chart and return the parsed manifests."""
    config_file = tmp_path / "config.yaml"
    config_file.write_text(CONFIG)
    config = load_config(config_file)
    for key, value in overrides.items():
        setattr(config.kubernetes, key, value)

    values = generate_helm_values(config, "run", "tprocc", "t1")
    values_file = tmp_path / "values.yaml"
    values_file.write_text(yaml.dump(values, sort_keys=False))

    result = subprocess.run(
        ["helm", "template", "t", str(CHART), "-f", str(values_file)],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stderr
    return [d for d in yaml.safe_load_all(result.stdout) if d]


def _job(docs: list[dict]) -> dict:
    return sorted(
        (d for d in docs if d["kind"] == "Job"), key=lambda d: d["metadata"]["name"]
    )[0]


class TestCredentialsUseSecrets:
    def test_no_password_anywhere_in_job_spec(self, tmp_path):
        """`kubectl describe job` must not reveal database credentials."""
        docs = _render(tmp_path)
        for job in (d for d in docs if d["kind"] == "Job"):
            assert PASSWORD not in yaml.dump(job)

    def test_credentials_come_from_secret_refs(self, tmp_path):
        job = _job(_render(tmp_path))
        env = job["spec"]["template"]["spec"]["containers"][0]["env"]
        by_ref = {e["name"] for e in env if "valueFrom" in e}
        assert {"USERNAME", "PASSWORD", "TPROCC_PASSWORD"} <= by_ref

    def test_secret_holds_every_target(self, tmp_path):
        docs = _render(tmp_path)
        secrets = [d for d in docs if d["kind"] == "Secret"]
        assert len(secrets) == 1
        keys = secrets[0]["stringData"]
        assert keys["target-0-password"] == PASSWORD
        assert keys["target-1-password"] == PASSWORD

    def test_can_be_disabled(self, tmp_path):
        """Opting out restores inline values, for restricted RBAC setups."""
        docs = _render(tmp_path, use_secrets=False)
        assert not [d for d in docs if d["kind"] == "Secret"]
        job = _job(docs)
        env = job["spec"]["template"]["spec"]["containers"][0]["env"]
        inline = {e["name"]: e.get("value") for e in env if "value" in e}
        assert inline["PASSWORD"] == PASSWORD


class TestPodSecurity:
    def test_satisfies_restricted_standard(self, tmp_path):
        """Required for plain Kubernetes enforcing restricted PodSecurity."""
        spec = _job(_render(tmp_path))["spec"]["template"]["spec"]
        assert spec["securityContext"]["runAsNonRoot"] is True
        assert spec["securityContext"]["seccompProfile"]["type"] == "RuntimeDefault"

        container = spec["containers"][0]["securityContext"]
        assert container["allowPrivilegeEscalation"] is False
        assert container["capabilities"]["drop"] == ["ALL"]

    def test_does_not_pin_runasuser(self, tmp_path):
        """OpenShift's SCC assigns a UID from the namespace range.

        Hardcoding one conflicts with that assignment, so the chart must leave
        runAsUser unset and let the platform choose.
        """
        spec = _job(_render(tmp_path))["spec"]["template"]["spec"]
        assert "runAsUser" not in spec.get("securityContext", {})
        assert "runAsUser" not in spec["containers"][0].get("securityContext", {})

    def test_can_be_disabled(self, tmp_path):
        spec = _job(_render(tmp_path, security_context=False))["spec"]["template"][
            "spec"
        ]
        assert "securityContext" not in spec
