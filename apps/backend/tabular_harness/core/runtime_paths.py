from __future__ import annotations

from pathlib import Path

LOGICAL_DATA_ROOT = Path("/data")
_RELOCATABLE_DATA_CHILDREN = frozenset({"artifacts", "benchmarks", "metadata"})


def resolve_runtime_data_path(path: Path | str, *, data_dir: Path | None = None) -> Path:
    candidate = Path(path)
    if data_dir is None:
        from tabular_harness.core.config import get_settings

        data_dir = get_settings().data_dir
    try:
        return data_dir / candidate.relative_to(LOGICAL_DATA_ROOT)
    except ValueError:
        pass

    if not candidate.is_absolute() or candidate.exists():
        return candidate

    # Host workers and the Docker API share this volume at different roots.
    # Recover legacy absolute records at the stable data-root boundary.
    parts = candidate.parts
    for index in range(len(parts) - 1, 0, -1):
        if parts[index] != LOGICAL_DATA_ROOT.name or index + 1 >= len(parts):
            continue
        if parts[index + 1] not in _RELOCATABLE_DATA_CHILDREN:
            continue
        return data_dir.joinpath(*parts[index + 1 :])
    return candidate
