from __future__ import annotations

import json
import zipfile
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from tabular_harness.core.json import loads_json
from tabular_harness.models.entities import Artifact, ExperimentRun, LineageEdge
from tabular_harness.services.artifacts import artifact_primary_path

PREDICTION_RUNTIME_REQUIRED_FILES = frozenset({"pipeline_manifest.json", "predict.py", "requirements.txt"})
EXPORT_BUNDLE_REQUIRED_FILES = frozenset(
    {*PREDICTION_RUNTIME_REQUIRED_FILES, "train.py", "README.md"}
)
TABLE_OMISSION_POLICY_SCHEMA_VERSION = "prediction_table_omission_policy.v1"


def prediction_table_is_safely_optional(table: dict[str, Any]) -> bool:
    if table.get("optional") is not True:
        return False
    policy = table.get("omission_policy")
    if not isinstance(policy, dict):
        return False
    if policy.get("schema_version") != TABLE_OMISSION_POLICY_SCHEMA_VERSION:
        return False
    if policy.get("status") != "validated" or policy.get("fallback_smoke_status") != "passed":
        return False
    evidence_artifact_id = policy.get("evidence_artifact_id")
    return isinstance(evidence_artifact_id, str) and bool(evidence_artifact_id.strip())


def prediction_pipeline_artifact_for_run(
    db: Session,
    run: ExperimentRun,
    *,
    params: dict[str, Any],
) -> Artifact | None:
    candidate_ids: list[str] = []
    for source in (params, params.get("raw") if isinstance(params.get("raw"), dict) else {}):
        if not isinstance(source, dict):
            continue
        for key in ("pipeline_artifact_id", "prediction_pipeline_artifact_id", "pipeline_bundle_artifact_id"):
            value = source.get(key)
            if isinstance(value, str) and value.strip():
                candidate_ids.append(value.strip())
    for artifact_id in dict.fromkeys(candidate_ids):
        artifact = db.get(Artifact, artifact_id)
        if artifact is not None and artifact.project_id == run.project_id and artifact.asset_type == "prediction_pipeline":
            return artifact

    linked_edges = db.scalars(
        select(LineageEdge)
        .where(
            LineageEdge.project_id == run.project_id,
            LineageEdge.from_asset_type == "experiment_run",
            LineageEdge.from_asset_id == run.id,
            LineageEdge.to_asset_type == "artifact",
            LineageEdge.relation_type.in_(
                ["materializes_prediction_pipeline", "registered_prediction_pipeline", "prediction_pipeline"]
            ),
        )
        .order_by(LineageEdge.created_at.desc())
    ).all()
    for edge in linked_edges:
        artifact = db.get(Artifact, edge.to_asset_id)
        if artifact is not None and artifact.project_id == run.project_id and artifact.asset_type == "prediction_pipeline":
            return artifact

    project_pipelines = db.scalars(
        select(Artifact)
        .where(Artifact.project_id == run.project_id, Artifact.asset_type == "prediction_pipeline")
        .order_by(Artifact.created_at.desc())
    ).all()
    for artifact in project_pipelines:
        metadata = loads_json(artifact.metadata_json, {})
        if metadata.get("experiment_run_id") == run.id or metadata.get("run_id") == run.id:
            return artifact
        run_ids = metadata.get("experiment_run_ids")
        if isinstance(run_ids, list) and run.id in run_ids:
            return artifact
    return None


def leaderboard_ready_pipeline_artifact(
    db: Session,
    run: ExperimentRun,
    *,
    params: dict[str, Any],
) -> Artifact | None:
    """Return the runtime used for Leaderboard prediction.

    The historical name is retained for callers and stored projects. Leaderboard
    readiness means target-free UI inference is smoke-tested; it does not imply
    that the optional local training/export bundle has been built.
    """
    return prediction_enabled_pipeline_artifact(db, run, params=params)


def prediction_enabled_pipeline_artifact(
    db: Session,
    run: ExperimentRun,
    *,
    params: dict[str, Any],
) -> Artifact | None:
    artifact = prediction_pipeline_artifact_for_run(db, run, params=params)
    if artifact is None:
        return None
    metadata = loads_json(artifact.metadata_json, {})
    manifest = metadata.get("pipeline_manifest")
    smoke = metadata.get("smoke_validation")
    if not isinstance(manifest, dict) or manifest.get("schema_version") != "pipeline_manifest.v1":
        return None
    if not all(isinstance(manifest.get(key), dict) for key in ("input_contract", "output_contract", "runtime")):
        return None
    if not isinstance(smoke, dict) or smoke.get("status") != "passed" or smoke.get("runtime_isolated") is not True:
        return None
    try:
        path = artifact_primary_path(artifact)
        if not path.is_file() or not zipfile.is_zipfile(path):
            return None
        with zipfile.ZipFile(path) as archive:
            names = {name.rstrip("/") for name in archive.namelist() if name and not name.endswith("/")}
            if not PREDICTION_RUNTIME_REQUIRED_FILES.issubset(names):
                return None
            bundled_manifest = json.loads(archive.read("pipeline_manifest.json").decode("utf-8"))
            if not isinstance(bundled_manifest, dict) or bundled_manifest.get("schema_version") != "pipeline_manifest.v1":
                return None
            compile(archive.read("predict.py").decode("utf-8"), "predict.py", "exec")
    except (OSError, KeyError, UnicodeDecodeError, json.JSONDecodeError, SyntaxError, zipfile.BadZipFile):
        return None
    return artifact


def export_ready_pipeline_artifact(
    db: Session,
    run: ExperimentRun,
    *,
    params: dict[str, Any],
) -> Artifact | None:
    artifact = prediction_enabled_pipeline_artifact(db, run, params=params)
    if artifact is None:
        return None
    metadata = loads_json(artifact.metadata_json, {})
    consistency = metric_claim_consistency_from_metadata(metadata)
    if not isinstance(consistency, dict) or consistency.get("claims_match") is not True:
        return None
    if not pipeline_claim_matches_run_primary_metric(consistency, run):
        return None
    try:
        path = artifact_primary_path(artifact)
        with zipfile.ZipFile(path) as archive:
            names = {name.rstrip("/") for name in archive.namelist() if name and not name.endswith("/")}
            if not EXPORT_BUNDLE_REQUIRED_FILES.issubset(names):
                return None
            compile(archive.read("train.py").decode("utf-8"), "train.py", "exec")
            if not archive.read("README.md").strip():
                return None
    except (OSError, KeyError, UnicodeDecodeError, SyntaxError, zipfile.BadZipFile):
        return None
    return artifact


def metric_claim_consistency_from_metadata(metadata: dict[str, Any]) -> dict[str, Any] | None:
    current = metadata.get("metric_claim_consistency")
    if isinstance(current, dict):
        return current
    legacy = metadata.get("metric_reproduction")
    if not isinstance(legacy, dict):
        return None
    migrated = dict(legacy)
    migrated["schema_version"] = "prediction_pipeline_metric_claim_consistency.v1"
    migrated.setdefault("claims_match", legacy.get("metric_reproduced"))
    return migrated


def pipeline_claim_matches_run_primary_metric(
    metric_claim_consistency: dict[str, Any],
    run: ExperimentRun,
) -> bool:
    metrics = loads_json(run.metrics_json, {})
    metric_name = metrics.get("primary_metric_name")
    observed_value = metrics.get(metric_name) if isinstance(metric_name, str) else None
    if not isinstance(observed_value, (int, float)):
        observed_value = metrics.get("primary_metric_value")
    if not isinstance(metric_name, str) or not metric_name.strip() or not isinstance(observed_value, (int, float)):
        return False
    comparisons = metric_claim_consistency.get("comparisons")
    if not isinstance(comparisons, list):
        return False
    for comparison in comparisons:
        if not isinstance(comparison, dict) or comparison.get("metric") != metric_name:
            continue
        compared_run_id = comparison.get("run_id")
        if isinstance(compared_run_id, str) and compared_run_id != run.id:
            continue
        comparison_value = comparison.get("observed")
        if not isinstance(comparison_value, (int, float)) or comparison.get("matched") is not True:
            continue
        absolute_delta = abs(float(comparison_value) - float(observed_value))
        if absolute_delta <= max(abs(float(observed_value)) * 1e-6, 1e-9):
            return True
    return False


def pipeline_reproduces_run_primary_metric(
    metric_reproduction: dict[str, Any],
    run: ExperimentRun,
) -> bool:
    """Compatibility alias for persisted v1 metadata and external callers."""
    return pipeline_claim_matches_run_primary_metric(metric_reproduction, run)
