from pathlib import Path

from tabular_harness.core.runtime_paths import resolve_runtime_data_path


def test_resolve_runtime_data_path_maps_logical_data_root(tmp_path: Path) -> None:
    assert resolve_runtime_data_path("/data/artifacts/example.json", data_dir=tmp_path) == (
        tmp_path / "artifacts" / "example.json"
    )


def test_resolve_runtime_data_path_preserves_unrelated_paths(tmp_path: Path) -> None:
    path = tmp_path / "outside" / "example.json"
    assert resolve_runtime_data_path(path, data_dir=tmp_path / "data") == path


def test_resolve_runtime_data_path_relocates_host_data_volume_path(tmp_path: Path) -> None:
    container_data = tmp_path / "container-data"
    host_path = Path("/home/tablex/project/data/artifacts/project/notebook.py")

    assert resolve_runtime_data_path(host_path, data_dir=container_data) == (
        container_data / "artifacts" / "project" / "notebook.py"
    )


def test_resolve_runtime_data_path_does_not_relocate_arbitrary_data_path(tmp_path: Path) -> None:
    path = Path("/home/tablex/project/data/unrelated/file.txt")

    assert resolve_runtime_data_path(path, data_dir=tmp_path / "container-data") == path
