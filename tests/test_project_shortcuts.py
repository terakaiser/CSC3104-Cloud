"""Check orchestration without starting containers or changing a real cluster."""
from pathlib import Path
import shutil
import subprocess

import pytest


SHELL = shutil.which("powershell.exe")
pytestmark = pytest.mark.skipif(SHELL is None, reason="Windows PowerShell shortcuts")
ROOT = Path(__file__).resolve().parents[1]


def run_shortcut(tmp_path, target, action, mock):
    shutil.copy2(ROOT / "project.ps1", tmp_path / "project.ps1")
    harness = tmp_path / "harness.ps1"
    harness.write_text(mock + f'\n& "$PSScriptRoot/project.ps1" {target} {action}\n', encoding="utf-8")
    return subprocess.run(
        [SHELL, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(harness)],
        capture_output=True, text=True, timeout=30,
    )


def test_docker_start_does_not_submit_training(tmp_path):
    result = run_shortcut(tmp_path, "docker", "start", """
function global:docker { Write-Host "CALL $args"; $global:LASTEXITCODE = 0 }
""")
    assert result.returncode == 0, result.stderr
    assert "CALL compose -f docker/compose.yaml up -d --wait" in result.stdout
    assert "run --rm" not in result.stdout


def test_failed_command_does_not_report_readiness(tmp_path):
    result = run_shortcut(tmp_path, "docker", "start", """
function global:docker { $global:LASTEXITCODE = 7 }
""")
    assert result.returncode != 0
    assert "exit 7" in result.stderr
    assert "Services ready" not in result.stdout


def test_kubernetes_keeps_unfinished_job(tmp_path):
    result = run_shortcut(tmp_path, "k8s", "train", """
function global:kubectl {
    Write-Host "CALL $args"
    $global:LASTEXITCODE = 0
    '{"status":{"active":1}}'
}
""")
    assert result.returncode != 0
    assert "active or failed" in result.stderr
    assert "delete job" not in result.stdout and "create -f" not in result.stdout


def test_kubernetes_replaces_only_completed_job(tmp_path):
    result = run_shortcut(tmp_path, "k8s", "train", """
function global:kubectl {
    Write-Host "CALL $args"
    $global:LASTEXITCODE = 0
    if ($args -contains '--ignore-not-found') {
        '{"status":{"conditions":[{"type":"Complete","status":"True"}]}}'
    }
}
""")
    assert result.returncode == 0, result.stderr
    assert "--context docker-desktop -n crossbank delete job training-run --wait=true" in result.stdout
    assert "create -f k8s/training-job.yaml" in result.stdout
    assert "logs -f job/training-run --pod-running-timeout=180s" in result.stdout
