from __future__ import annotations

from typing import Any

from tabular_harness.core.json import loads_json
from tabular_harness.models.entities import Artifact
from tabular_harness.services.agent_requests.model_diagnostics import (
    MODEL_DIAGNOSTIC_CHECK_NAMES,
    MODEL_DIAGNOSTIC_CHECK_STATUSES,
    MODEL_DIAGNOSTICS_MANIFEST_SCHEMA_VERSION,
)
from tabular_harness.services.analysis_notebooks import (
    marimo_notebook_runtime_preflight_for_artifact,
    marimo_notebook_source_validation_for_artifact,
)

NOTEBOOK_QUALITY_MANIFEST_SCHEMA_VERSION = "tablex_notebook_quality_manifest.v1"
NOTEBOOK_MIN_HUMAN_FACING_FIGURES = 3


class NotebookToolValidationError(ValueError):
    def __init__(self, message: str, *, issues: list[dict[str, Any]]) -> None:
        super().__init__(message)
        self.issues = issues


def notebook_tool_issue(pointer: str, message: str, **extra: Any) -> dict[str, Any]:
    issue = {"pointer": pointer, "message": message}
    issue.update({key: value for key, value in extra.items() if value is not None})
    return issue


def assert_human_facing_notebook_quality(
    *,
    notebook_artifact: Artifact,
    notebook_kind: str | None,
    quality_manifest: dict[str, Any] | None,
) -> None:
    if quality_manifest is None:
        raise NotebookToolValidationError(
            "payload.quality_manifest is required for human-facing marimo notebooks. "
            "Declare figure_count, table_count, key_findings, read_order, data_sources_used, and limitations.",
            issues=[
                notebook_tool_issue(
                    "payload.quality_manifest",
                    "Human-facing marimo notebooks must include the fixed quality manifest.",
                    code="missing_quality_manifest",
                    fix=(
                        "Add payload.quality_manifest with figure_count, table_count, key_findings, "
                        "read_order, data_sources_used, and limitations."
                    ),
                )
            ],
        )
    feedback = notebook_quality_feedback_from_manifest(quality_manifest)
    status = str(feedback.get("status") or "")
    if status != "manifest_provided":
        raise NotebookToolValidationError(
            str(feedback.get("message") or "Notebook quality_manifest is incomplete."),
            issues=[
                notebook_tool_issue(
                    "payload.quality_manifest",
                    str(feedback.get("message") or "Notebook quality_manifest is incomplete."),
                    code="incomplete_quality_manifest",
                    fix="Fill the missing quality_manifest arrays and counts, then resubmit the notebook request.",
                )
            ],
        )
    figure_count = int(quality_manifest.get("figure_count") or 0)
    if figure_count < NOTEBOOK_MIN_HUMAN_FACING_FIGURES:
        raise NotebookToolValidationError(
            f"payload.quality_manifest.figure_count must be at least {NOTEBOOK_MIN_HUMAN_FACING_FIGURES} "
            "for a human-facing Tablex notebook. Use meaningful distribution, relationship, diagnostic, "
            "or model-comparison figures instead of text/table-only output.",
            issues=[
                notebook_tool_issue(
                    "payload.quality_manifest.figure_count",
                    f"must be at least {NOTEBOOK_MIN_HUMAN_FACING_FIGURES}",
                    code="not_enough_figures",
                    actual=figure_count,
                    minimum=NOTEBOOK_MIN_HUMAN_FACING_FIGURES,
                    fix=(
                        "Add meaningful distribution, relationship, diagnostic, or model-comparison figures "
                        "and update figure_count."
                    ),
                )
            ],
        )
    validation = marimo_notebook_source_validation_for_artifact(notebook_artifact)
    if validation.get("is_valid_marimo_notebook") is not True:
        errors = validation.get("errors") if isinstance(validation.get("errors"), list) else []
        message = "; ".join(str(item) for item in errors if str(item).strip())
        raise NotebookToolValidationError(
            "Referenced notebook artifact is not a valid native marimo source"
            + (f": {message}" if message else "."),
            issues=notebook_source_validation_issues(validation),
        )
    checks = validation.get("checks") if isinstance(validation.get("checks"), dict) else {}
    visual_call_count = int(checks.get("visual_call_count") or 0)
    if visual_call_count <= 0:
        raise NotebookToolValidationError(
            "Notebook quality_manifest declares figures, but the marimo source does not contain recognized "
            "visualization calls. Add Plotly, matplotlib, seaborn, Altair, or pandas plotting code and resubmit.",
            issues=[
                notebook_tool_issue(
                    "notebook.source.visualization_calls",
                    "No recognized visualization calls were found in the native marimo source.",
                    code="missing_visualization_calls",
                    fix="Add Plotly, matplotlib, seaborn, Altair, or pandas plotting code and resubmit.",
                )
            ],
        )
    if notebook_kind in {"model_diagnostics", "model_comparison"}:
        assert_model_diagnostics_manifest(quality_manifest)
    runtime_preflight = marimo_notebook_runtime_preflight_for_artifact(notebook_artifact)
    if runtime_preflight.get("ok") is True:
        return
    runtime_error_summary = str(
        runtime_preflight.get("error_summary")
        or runtime_preflight.get("stderr")
        or runtime_preflight.get("stdout")
        or "unknown runtime error"
    )
    if notebook_runtime_preflight_environment_boundary(runtime_preflight):
        return
    raise NotebookToolValidationError(
        "Referenced notebook artifact failed native marimo runtime preflight: " + runtime_error_summary,
        issues=[
            notebook_tool_issue(
                "notebook.runtime_preflight",
                "Referenced notebook artifact failed native marimo runtime preflight: " + runtime_error_summary,
                code="native_marimo_runtime_preflight_failed",
                fix="Repair the notebook source so native marimo can execute it, then resubmit.",
            )
        ],
    )


def notebook_runtime_preflight_environment_boundary(runtime_preflight: dict[str, Any]) -> bool:
    error_type = str(runtime_preflight.get("error_type") or "")
    error_summary = str(runtime_preflight.get("error_summary") or runtime_preflight.get("stderr") or "")
    if error_type == "MarimoUnavailable":
        return True
    environment_markers = (
        "PermissionError: [Errno 1] Operation not permitted",
        "socket.socket",
        "multiprocessing.connection",
    )
    return any(marker in error_summary for marker in environment_markers)


def assert_model_diagnostics_manifest(quality_manifest: dict[str, Any]) -> None:
    diagnostics = quality_manifest.get("model_diagnostics")
    if not isinstance(diagnostics, dict):
        raise NotebookToolValidationError(
            "payload.quality_manifest.model_diagnostics is required for model-diagnostics notebooks.",
            issues=[
                notebook_tool_issue(
                    "payload.quality_manifest.model_diagnostics",
                    "Declare the model diagnostics coverage using fixed check statuses.",
                    code="missing_model_diagnostics_manifest",
                    fix=(
                        "Add model_diagnostics.checks entries for permutation_importance, native_feature_importance, "
                        "partial_dependence, and shap. Mark each one included, not_applicable, needs_model_artifact, "
                        "needs_dependency, or deferred, with evidence or a reason."
                    ),
                )
            ],
        )
    checks = diagnostics.get("checks")
    if not isinstance(checks, list):
        raise NotebookToolValidationError(
            "payload.quality_manifest.model_diagnostics.checks must be an array.",
            issues=[
                notebook_tool_issue(
                    "payload.quality_manifest.model_diagnostics.checks",
                    "must be an array",
                    code="invalid_model_diagnostics_checks",
                    fix="Submit one check object for each required model diagnostic.",
                )
            ],
        )
    by_name = {str(item.get("name") or "").strip(): item for item in checks if isinstance(item, dict)}
    missing = [name for name in MODEL_DIAGNOSTIC_CHECK_NAMES if name not in by_name]
    if missing:
        raise NotebookToolValidationError(
            "payload.quality_manifest.model_diagnostics.checks is missing required checks: " + ", ".join(missing),
            issues=[
                notebook_tool_issue(
                    "payload.quality_manifest.model_diagnostics.checks",
                    "missing required model diagnostic checks",
                    code="missing_model_diagnostics_checks",
                    missing=missing,
                    fix="Add all required model diagnostic checks, using not_applicable/deferred when a check cannot be run yet.",
                )
            ],
        )


def notebook_source_validation_issues(validation: dict[str, Any]) -> list[dict[str, Any]]:
    checks = validation.get("checks") if isinstance(validation.get("checks"), dict) else {}
    issues: list[dict[str, Any]] = []
    parse_error = checks.get("parse_error")
    if isinstance(parse_error, str) and parse_error.strip():
        issues.append(
            notebook_tool_issue(
                "notebook.source",
                f"source did not parse as Python: {parse_error}",
                code="python_parse_error",
                fix="Fix the Python syntax error in the notebook source and resubmit.",
            )
        )
    if checks.get("imports_marimo") is not True:
        issues.append(
            notebook_tool_issue(
                "notebook.source.imports_marimo",
                "source does not import marimo",
                code="missing_marimo_import",
                fix="Import marimo in the native notebook source.",
            )
        )
    if checks.get("defines_marimo_app") is not True:
        issues.append(
            notebook_tool_issue(
                "notebook.source.defines_marimo_app",
                "source does not define a marimo App",
                code="missing_marimo_app",
                fix="Define a marimo.App instance in the native notebook source.",
            )
        )
    duplicate_definitions = checks.get("duplicate_public_cell_definitions")
    if isinstance(duplicate_definitions, list):
        for item in duplicate_definitions:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "").strip()
            lines = item.get("lines")
            if not name:
                continue
            issues.append(
                notebook_tool_issue(
                    f"notebook.source.public_variables.{name}",
                    f"marimo public variable `{name}` is defined in multiple cells at lines {lines}",
                    code="duplicate_public_marimo_variable",
                    variable=name,
                    lines=lines,
                    fix=(
                        f"Rename repeated cell-local temporaries named `{name}` to `_{name}`, or give each "
                        "public output a unique semantic name."
                    ),
                )
            )
    if issues:
        return issues
    errors = validation.get("errors") if isinstance(validation.get("errors"), list) else []
    return [
        notebook_tool_issue(
            "notebook.source",
            str(error),
            code="invalid_native_marimo_source",
            fix="Repair the native marimo notebook source and resubmit.",
        )
        for error in errors
        if str(error).strip()
    ]


def normalize_notebook_quality_manifest(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValueError("payload.quality_manifest must be an object when provided")
    schema_version = str(value.get("schema_version") or NOTEBOOK_QUALITY_MANIFEST_SCHEMA_VERSION)
    if schema_version != NOTEBOOK_QUALITY_MANIFEST_SCHEMA_VERSION:
        raise ValueError(
            f"Unsupported payload.quality_manifest.schema_version: {schema_version or '<missing>'}"
        )
    figure_count = non_negative_int_field(value, "figure_count")
    table_count = non_negative_int_field(value, "table_count")
    key_findings = bounded_string_list_field(value, "key_findings", required=True, limit=16)
    data_sources_used = bounded_string_list_field(value, "data_sources_used", required=True, limit=24)
    limitations = bounded_string_list_field(value, "limitations", required=True, limit=12)
    read_order = notebook_read_order_field(value.get("read_order"), required=True)
    visual_summary = optional_quality_text_field(value, "visual_summary")
    notebook_purpose = optional_quality_text_field(value, "notebook_purpose")
    model_diagnostics = model_diagnostics_quality_manifest_field(value.get("model_diagnostics"))
    return {
        "schema_version": NOTEBOOK_QUALITY_MANIFEST_SCHEMA_VERSION,
        "figure_count": figure_count,
        "table_count": table_count,
        "key_findings": key_findings,
        "read_order": read_order,
        "data_sources_used": data_sources_used,
        "limitations": limitations,
        **({"visual_summary": visual_summary} if visual_summary else {}),
        **({"notebook_purpose": notebook_purpose} if notebook_purpose else {}),
        **({"model_diagnostics": model_diagnostics} if model_diagnostics else {}),
    }


def model_diagnostics_quality_manifest_field(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValueError("payload.quality_manifest.model_diagnostics must be an object when provided")
    schema_version = str(value.get("schema_version") or MODEL_DIAGNOSTICS_MANIFEST_SCHEMA_VERSION)
    if schema_version != MODEL_DIAGNOSTICS_MANIFEST_SCHEMA_VERSION:
        raise ValueError(
            f"Unsupported payload.quality_manifest.model_diagnostics.schema_version: {schema_version or '<missing>'}"
        )
    raw_checks = value.get("checks")
    if not isinstance(raw_checks, list):
        raise ValueError("payload.quality_manifest.model_diagnostics.checks must be an array")
    checks: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, raw_check in enumerate(raw_checks[:24]):
        if not isinstance(raw_check, dict):
            raise ValueError(f"payload.quality_manifest.model_diagnostics.checks[{index}] must be an object")
        name = str(raw_check.get("name") or "").strip()
        if name not in MODEL_DIAGNOSTIC_CHECK_NAMES:
            raise ValueError(
                "payload.quality_manifest.model_diagnostics.checks"
                f"[{index}].name must be one of {', '.join(MODEL_DIAGNOSTIC_CHECK_NAMES)}"
            )
        if name in seen:
            raise ValueError(f"payload.quality_manifest.model_diagnostics.checks[{index}].name duplicates {name}")
        seen.add(name)
        status = str(raw_check.get("status") or "").strip()
        if status not in MODEL_DIAGNOSTIC_CHECK_STATUSES:
            raise ValueError(
                "payload.quality_manifest.model_diagnostics.checks"
                f"[{index}].status must be one of {', '.join(MODEL_DIAGNOSTIC_CHECK_STATUSES)}"
            )
        reason = optional_quality_text_field(raw_check, "reason")
        evidence = model_diagnostics_evidence_field(raw_check.get("evidence"), index)
        if status == "included" and not evidence:
            raise ValueError(
                "payload.quality_manifest.model_diagnostics.checks"
                f"[{index}].evidence must be a non-empty array when status is included"
            )
        if status != "included" and not reason:
            raise ValueError(
                "payload.quality_manifest.model_diagnostics.checks"
                f"[{index}].reason is required when status is {status}"
            )
        checks.append(
            {
                "name": name,
                "status": status,
                **({"evidence": evidence} if evidence else {}),
                **({"reason": reason} if reason else {}),
            }
        )
    return {
        "schema_version": MODEL_DIAGNOSTICS_MANIFEST_SCHEMA_VERSION,
        "checks": checks,
    }


def model_diagnostics_evidence_field(value: Any, check_index: int) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError(
            "payload.quality_manifest.model_diagnostics.checks"
            f"[{check_index}].evidence must be an array"
        )
    items: list[str] = []
    for evidence_index, item in enumerate(value[:12]):
        text: str | None = None
        if isinstance(item, str):
            text = item
        elif isinstance(item, dict):
            for key in ("workspace_path", "artifact_id", "path", "uri"):
                raw = item.get(key)
                if isinstance(raw, str) and raw.strip():
                    text = raw
                    break
        if not isinstance(text, str) or not text.strip():
            raise ValueError(
                "payload.quality_manifest.model_diagnostics.checks"
                f"[{check_index}].evidence[{evidence_index}] must be a non-empty string "
                "or an object with workspace_path, artifact_id, path, or uri"
            )
        normalized = text.strip()[:1200]
        if normalized not in items:
            items.append(normalized)
    return items


def non_negative_int_field(value: dict[str, Any], key: str) -> int:
    raw_value = value.get(key)
    if isinstance(raw_value, bool) or not isinstance(raw_value, int):
        raise ValueError(f"payload.quality_manifest.{key} must be a non-negative integer")
    if raw_value < 0:
        raise ValueError(f"payload.quality_manifest.{key} must be a non-negative integer")
    return raw_value


def bounded_string_list_field(value: dict[str, Any], key: str, *, required: bool, limit: int) -> list[str]:
    raw_value = value.get(key)
    if raw_value is None and not required:
        return []
    if not isinstance(raw_value, list):
        required_text = "required and " if required else ""
        raise ValueError(f"payload.quality_manifest.{key} is {required_text}must be an array")
    items: list[str] = []
    for index, item in enumerate(raw_value[:limit]):
        if not isinstance(item, str) or not item.strip():
            raise ValueError(f"payload.quality_manifest.{key}[{index}] must be a non-empty string")
        items.append(item.strip()[:1200])
    return items


def notebook_read_order_field(value: Any, *, required: bool) -> list[dict[str, str]]:
    if value is None and not required:
        return []
    if not isinstance(value, list):
        required_text = "is required and " if required else ""
        raise ValueError(f"payload.quality_manifest.read_order {required_text}must be an array")
    items: list[dict[str, str]] = []
    for index, item in enumerate(value[:20]):
        if isinstance(item, str):
            label = item
            item = {"label": label}
        if not isinstance(item, dict):
            raise ValueError(f"payload.quality_manifest.read_order[{index}] must be an object")
        label = item.get("label")
        if not isinstance(label, str) or not label.strip():
            raise ValueError(f"payload.quality_manifest.read_order[{index}].label must be a non-empty string")
        anchor = item.get("anchor")
        detail = item.get("detail")
        entry = {"label": label.strip()[:400]}
        if isinstance(anchor, str) and anchor.strip():
            entry["anchor"] = anchor.strip()[:200]
        if isinstance(detail, str) and detail.strip():
            entry["detail"] = detail.strip()[:800]
        items.append(entry)
    return items


def optional_quality_text_field(value: dict[str, Any], key: str) -> str | None:
    raw_value = value.get(key)
    if raw_value is None:
        return None
    if not isinstance(raw_value, str):
        raise ValueError(f"payload.quality_manifest.{key} must be a string when provided")
    stripped = raw_value.strip()
    return stripped[:1200] if stripped else None


def notebook_quality_feedback_from_manifest(manifest: dict[str, Any]) -> dict[str, Any]:
    figure_count = int(manifest.get("figure_count") or 0)
    table_count = int(manifest.get("table_count") or 0)
    key_finding_count = len(manifest.get("key_findings", [])) if isinstance(manifest.get("key_findings"), list) else 0
    read_order_count = len(manifest.get("read_order", [])) if isinstance(manifest.get("read_order"), list) else 0
    feedback = {
        "schema_version": NOTEBOOK_QUALITY_MANIFEST_SCHEMA_VERSION,
        "figure_count": figure_count,
        "table_count": table_count,
        "key_finding_count": key_finding_count,
        "read_order_count": read_order_count,
        "model_diagnostics_check_count": (
            len(manifest.get("model_diagnostics", {}).get("checks", []))
            if isinstance(manifest.get("model_diagnostics"), dict)
            and isinstance(manifest.get("model_diagnostics", {}).get("checks"), list)
            else 0
        ),
    }
    if figure_count <= 0:
        return {
            **feedback,
            "status": "needs_figures",
            "message": (
                "The notebook is registered as source, but its quality_manifest declares zero figures. "
                "Add useful plots or visual diagnostics and resubmit the notebook request."
            ),
        }
    if key_finding_count <= 0 or read_order_count <= 0:
        return {
            **feedback,
            "status": "needs_manifest_detail",
            "message": (
                "The notebook is registered as source, but its quality_manifest needs key_findings and read_order "
                "so Tablex can route it and explain it to humans."
            ),
        }
    return {**feedback, "status": "manifest_provided"}


def notebook_quality_feedback_from_metadata(notebook_artifact: Artifact) -> dict[str, Any]:
    metadata = loads_json(notebook_artifact.metadata_json, {})
    manifest = metadata.get("notebook_quality_manifest")
    if isinstance(manifest, dict):
        feedback = notebook_quality_feedback_from_manifest(manifest)
        message = metadata.get("notebook_quality_message")
        if isinstance(message, str) and message.strip() and feedback["status"] != "manifest_provided":
            feedback["message"] = message.strip()
        return feedback
    return {
        "status": "needs_manifest",
        "schema_version": NOTEBOOK_QUALITY_MANIFEST_SCHEMA_VERSION,
        "message": (
            "Register a quality_manifest with figure_count, table_count, key_findings, read_order, "
            "data_sources_used, and limitations so Tablex can explain and route the notebook without guessing."
        ),
        "required_fields": [
            "figure_count",
            "table_count",
            "key_findings",
            "read_order",
            "data_sources_used",
            "limitations",
        ],
    }
