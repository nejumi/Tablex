from __future__ import annotations

import importlib.metadata as importlib_metadata
import json
import os
import shutil
import subprocess
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any

RESOURCE_SNAPSHOT_SCHEMA_VERSION = "compute_resource_snapshot.v1"
MANAGED_RESOURCE_SNAPSHOT_RELATIVE_PATH = Path("runtime") / "compute-resources.json"


@lru_cache(maxsize=2)
def detect_compute_resources(*, probe_libraries: bool = False) -> dict[str, Any]:
    nvidia_smi = shutil.which("nvidia-smi")
    gpu = detect_nvidia_gpus(nvidia_smi)
    libraries = {
        name: library_capability(name, gpu_available=gpu["status"] == "available", probe=probe_libraries)
        for name in ("xgboost", "lightgbm", "catboost", "torch")
    }
    gpu_ready_libraries = [
        name for name, capability in libraries.items() if capability["gpu_support"] == "available"
    ]
    return {
        "schema_version": RESOURCE_SNAPSHOT_SCHEMA_VERSION,
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "runtime_location": os.getenv("TABLEX_RUNTIME_LOCATION", "host"),
        "device_mode": os.getenv("TABLEX_COMPUTE_DEVICE_MODE", "auto"),
        "cpu": {
            "logical_count": os.cpu_count(),
            "memory_total_bytes": system_memory_total_bytes(),
        },
        "gpu": {
            **gpu,
            "visible_devices": os.getenv("CUDA_VISIBLE_DEVICES"),
            "gpu_ready_libraries": gpu_ready_libraries,
            "usable_for_compute": gpu["status"] == "available" and bool(gpu_ready_libraries),
        },
        "libraries": libraries,
    }


def load_managed_compute_resources(data_dir: Path | None = None) -> dict[str, Any] | None:
    root = data_dir or Path(os.getenv("HARNESS_DATA_DIR", "/data"))
    path = root / MANAGED_RESOURCE_SNAPSHOT_RELATIVE_PATH
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict) or payload.get("schema_version") != RESOURCE_SNAPSHOT_SCHEMA_VERSION:
        return None
    return payload


def select_compute_device(
    resources: dict[str, Any],
    *,
    requested: str,
    fallback_policy: str,
) -> tuple[str | None, str | None]:
    gpu = resources.get("gpu") if isinstance(resources.get("gpu"), dict) else {}
    gpu_usable = gpu.get("usable_for_compute") is True
    if requested == "cpu":
        return "cpu", None
    if gpu_usable:
        return "gpu", None
    reason = str(gpu.get("reason") or "No probed GPU-capable library is usable in this compute runtime.")
    if requested == "gpu" and fallback_policy == "fail":
        return None, reason
    return "cpu", reason


def detect_nvidia_gpus(nvidia_smi: str | None) -> dict[str, Any]:
    if not nvidia_smi:
        return {
            "provider": "nvidia",
            "status": "unavailable",
            "nvidia_smi_available": False,
            "devices": [],
            "driver_version": None,
            "cuda_driver_max_version": None,
            "reason": "nvidia-smi is not available in this runtime.",
        }
    fields = ["index", "uuid", "name", "memory.total", "compute_cap", "driver_version"]
    completed = run_command(
        [nvidia_smi, f"--query-gpu={','.join(fields)}", "--format=csv,noheader,nounits"],
        timeout=10,
    )
    if completed.returncode != 0:
        return {
            "provider": "nvidia",
            "status": "error",
            "nvidia_smi_available": True,
            "devices": [],
            "driver_version": None,
            "cuda_driver_max_version": None,
            "reason": compact_error(completed.stderr or completed.stdout),
        }
    devices: list[dict[str, Any]] = []
    for line in completed.stdout.splitlines():
        values = [value.strip() for value in line.split(",")]
        if len(values) != len(fields):
            continue
        devices.append(
            {
                "index": int_or_text(values[0]),
                "uuid": values[1],
                "name": values[2],
                "memory_total_mb": int_or_none(values[3]),
                "compute_capability": values[4] or None,
            }
        )
    driver_version = None
    if devices:
        first_line = next((line for line in completed.stdout.splitlines() if line.strip()), "")
        first_values = [value.strip() for value in first_line.split(",")]
        driver_version = first_values[5] if len(first_values) == len(fields) else None
    cuda_version = nvidia_cuda_driver_max_version(nvidia_smi)
    return {
        "provider": "nvidia",
        "status": "available" if devices else "unavailable",
        "nvidia_smi_available": True,
        "devices": devices,
        "device_count": len(devices),
        "driver_version": driver_version,
        "cuda_driver_max_version": cuda_version,
        "reason": None if devices else "nvidia-smi did not report a visible GPU.",
    }


def nvidia_cuda_driver_max_version(nvidia_smi: str) -> str | None:
    completed = run_command([nvidia_smi], timeout=10)
    if completed.returncode != 0:
        return None
    marker = "CUDA Version:"
    for line in completed.stdout.splitlines():
        if marker not in line:
            continue
        value = line.split(marker, 1)[1].split("|", 1)[0].strip()
        return value or None
    return None


def library_capability(name: str, *, gpu_available: bool, probe: bool) -> dict[str, Any]:
    version = package_version_or_none(name)
    if version is None:
        return {
            "installed": False,
            "version": None,
            "gpu_support": "unavailable",
            "probe_status": "not_installed",
            "reason": f"{name} is not installed in this runtime.",
        }
    if not gpu_available:
        return {
            "installed": True,
            "version": version,
            "gpu_support": "unavailable",
            "probe_status": "not_run",
            "reason": "No NVIDIA GPU is visible in this runtime.",
        }
    if not probe:
        return {
            "installed": True,
            "version": version,
            "gpu_support": "unverified",
            "probe_status": "not_run",
            "reason": "A GPU is visible, but the library probe was not requested.",
        }
    probe_result = probe_library_gpu(name)
    return {
        "installed": True,
        "version": version,
        "gpu_support": "available" if probe_result["ok"] else "unavailable",
        "probe_status": "passed" if probe_result["ok"] else "failed",
        "reason": probe_result.get("reason"),
    }


def probe_library_gpu(name: str) -> dict[str, Any]:
    scripts = {
        "xgboost": (
            "import xgboost as xgb; "
            "d=xgb.DMatrix([[0.0],[1.0],[2.0],[3.0]],label=[0,0,1,1]); "
            "xgb.train({'device':'cuda','tree_method':'hist','max_depth':1},d,num_boost_round=1)"
        ),
        "lightgbm": (
            "import lightgbm as lgb; "
            "d=lgb.Dataset([[0.0],[1.0],[2.0],[3.0]],label=[0,0,1,1]); "
            "lgb.train({'device_type':'gpu','verbosity':-1,'min_data_in_leaf':1},d,num_boost_round=1)"
        ),
        "catboost": (
            "from catboost import CatBoostClassifier; "
            "CatBoostClassifier(iterations=1,task_type='GPU',verbose=False,allow_writing_files=False)"
            ".fit([[0.0],[1.0],[2.0],[3.0]],[0,0,1,1])"
        ),
        "torch": (
            "import torch; assert torch.cuda.is_available(); "
            "x=torch.ones(1,device='cuda'); assert float(x.cpu()[0]) == 1.0"
        ),
    }
    script = scripts.get(name)
    if script is None:
        return {"ok": False, "reason": "No GPU probe is implemented for this library."}
    completed = run_command([os.sys.executable, "-c", script], timeout=45)
    return {
        "ok": completed.returncode == 0,
        "reason": None if completed.returncode == 0 else compact_error(completed.stderr or completed.stdout),
    }


def run_command(command: list[str], *, timeout: int) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(command, capture_output=True, text=True, timeout=timeout, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return subprocess.CompletedProcess(command, 1, "", str(exc))


def package_version_or_none(package_name: str) -> str | None:
    try:
        return importlib_metadata.version(package_name)
    except importlib_metadata.PackageNotFoundError:
        return None


def system_memory_total_bytes() -> int | None:
    path = Path("/proc/meminfo")
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.startswith("MemTotal:"):
                return int(line.split()[1]) * 1024
    except (OSError, ValueError, IndexError):
        return None
    return None


def compact_error(value: str, *, limit: int = 500) -> str:
    compact = " ".join(value.strip().split())
    return compact[:limit] or "The runtime probe failed without diagnostic output."


def int_or_none(value: str) -> int | None:
    try:
        return int(value)
    except ValueError:
        return None


def int_or_text(value: str) -> int | str:
    parsed = int_or_none(value)
    return parsed if parsed is not None else value


def main() -> None:
    print(json.dumps(detect_compute_resources(probe_libraries=True), ensure_ascii=True))


if __name__ == "__main__":
    main()
