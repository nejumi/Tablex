from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from tabular_harness.core import runtime_resources


def test_nvidia_snapshot_records_compute_capability_and_memory(monkeypatch: Any) -> None:
    def fake_run(command: list[str], *, timeout: int) -> subprocess.CompletedProcess[str]:
        del timeout
        if any(item.startswith("--query-gpu=") for item in command):
            return subprocess.CompletedProcess(
                command,
                0,
                "0, GPU-0, Tesla V100-SXM2-16GB, 16384, 7.0, 550.54.15\n",
                "",
            )
        return subprocess.CompletedProcess(
            command,
            0,
            "| NVIDIA-SMI 550.54.15 Driver Version: 550.54.15 CUDA Version: 12.4 |\n",
            "",
        )

    monkeypatch.setattr(runtime_resources, "run_command", fake_run)
    detected = runtime_resources.detect_nvidia_gpus("/usr/bin/nvidia-smi")

    assert detected["status"] == "available"
    assert detected["device_count"] == 1
    assert detected["devices"][0] == {
        "index": 0,
        "uuid": "GPU-0",
        "name": "Tesla V100-SXM2-16GB",
        "memory_total_mb": 16384,
        "compute_capability": "7.0",
    }
    assert detected["driver_version"] == "550.54.15"
    assert detected["cuda_driver_max_version"] == "12.4"


def test_compute_snapshot_keeps_gpu_library_support_unverified_without_probe(
    monkeypatch: Any,
) -> None:
    runtime_resources.detect_compute_resources.cache_clear()
    monkeypatch.setattr(runtime_resources.shutil, "which", lambda name: "/usr/bin/nvidia-smi")
    monkeypatch.setattr(
        runtime_resources,
        "detect_nvidia_gpus",
        lambda path: {
            "provider": "nvidia",
            "status": "available",
            "nvidia_smi_available": True,
            "devices": [{"index": 0}],
            "driver_version": "550",
            "cuda_driver_max_version": "12.4",
            "reason": None,
        },
    )
    monkeypatch.setattr(
        runtime_resources,
        "package_version_or_none",
        lambda name: "1.0" if name == "xgboost" else None,
    )

    snapshot = runtime_resources.detect_compute_resources(probe_libraries=False)

    assert snapshot["gpu"]["status"] == "available"
    assert snapshot["libraries"]["xgboost"]["gpu_support"] == "unverified"
    assert snapshot["gpu"]["usable_for_compute"] is False
    runtime_resources.detect_compute_resources.cache_clear()


def test_load_managed_compute_resources_accepts_only_snapshot_schema(tmp_path: Path) -> None:
    runtime_dir = tmp_path / "runtime"
    runtime_dir.mkdir()
    snapshot_path = runtime_dir / "compute-resources.json"
    snapshot_path.write_text(
        '{"schema_version":"compute_resource_snapshot.v1","gpu":{"status":"available"}}',
        encoding="utf-8",
    )

    assert runtime_resources.load_managed_compute_resources(tmp_path)["gpu"]["status"] == "available"

    snapshot_path.write_text('{"schema_version":"unknown"}', encoding="utf-8")
    assert runtime_resources.load_managed_compute_resources(tmp_path) is None


def test_catboost_probe_does_not_write_runtime_files(monkeypatch: Any) -> None:
    captured: list[str] = []

    def fake_run(command: list[str], *, timeout: int) -> subprocess.CompletedProcess[str]:
        del timeout
        captured.extend(command)
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(runtime_resources, "run_command", fake_run)

    assert runtime_resources.probe_library_gpu("catboost")["ok"] is True
    assert "allow_writing_files=False" in captured[-1]
