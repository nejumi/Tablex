from __future__ import annotations

from datetime import timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from tabular_harness.core.ids import new_id
from tabular_harness.core.json import dumps_json, loads_json
from tabular_harness.models.entities import (
    AgentSession,
    DeliverableExpectation,
    ExperimentRun,
    Project,
    utc_now,
)
from tabular_harness.services.agent_inbox import write_inbox_entry

DELIVERABLE_EXPECTATION_KINDS = {
    "model_diagnostics_notebook",
    "pipeline_bundle",
    "validation_audit",
    "research_findings",
}
DELIVERABLE_EXPECTATION_STATUSES = {"open", "fulfilled", "waived"}
RUN_SUBJECT_PREFIX = "experiment_run:"
OPEN_EXPECTATION_NOTIFICATION_AFTER = timedelta(minutes=30)


def run_subject_ref(run_id: str) -> str:
    return f"{RUN_SUBJECT_PREFIX}{run_id}"


def run_id_from_subject_ref(subject_ref: str) -> str | None:
    if not subject_ref.startswith(RUN_SUBJECT_PREFIX):
        return None
    value = subject_ref[len(RUN_SUBJECT_PREFIX) :].strip()
    return value or None


def expectation_to_dict(expectation: DeliverableExpectation) -> dict[str, Any]:
    return {
        "id": expectation.id,
        "project_id": expectation.project_id,
        "kind": expectation.kind,
        "subject_ref": expectation.subject_ref,
        "status": expectation.status,
        "created_from": expectation.created_from,
        "fulfilled_by_artifact_id": expectation.fulfilled_by_artifact_id,
        "fulfilled_at": expectation.fulfilled_at.isoformat() if expectation.fulfilled_at is not None else None,
        "waived_rationale": expectation.waived_rationale,
        "notification_sent_at": (
            expectation.notification_sent_at.isoformat() if expectation.notification_sent_at is not None else None
        ),
        "metadata": loads_json(expectation.metadata_json, {}),
        "created_at": expectation.created_at.isoformat(),
        "updated_at": expectation.updated_at.isoformat(),
    }


def upsert_deliverable_expectation(
    db: Session,
    *,
    project_id: str,
    kind: str,
    subject_ref: str,
    created_from: str,
    metadata: dict[str, Any] | None = None,
    status: str = "open",
    fulfilled_by_artifact_id: str | None = None,
) -> DeliverableExpectation:
    if kind not in DELIVERABLE_EXPECTATION_KINDS:
        raise ValueError(f"Unsupported deliverable expectation kind: {kind}")
    if status not in DELIVERABLE_EXPECTATION_STATUSES:
        raise ValueError(f"Unsupported deliverable expectation status: {status}")
    subject_ref = subject_ref.strip()
    if not subject_ref:
        raise ValueError("subject_ref is required")
    expectation = db.scalar(
        select(DeliverableExpectation).where(
            DeliverableExpectation.project_id == project_id,
            DeliverableExpectation.kind == kind,
            DeliverableExpectation.subject_ref == subject_ref,
        )
    )
    now = utc_now()
    if expectation is None:
        expectation = DeliverableExpectation(
            id=new_id("deliv"),
            project_id=project_id,
            kind=kind,
            subject_ref=subject_ref,
            status=status,
            created_from=created_from,
            metadata_json=dumps_json(metadata or {}),
        )
        db.add(expectation)
    else:
        if expectation.status == "waived" and status != "fulfilled":
            return expectation
        if metadata:
            current = loads_json(expectation.metadata_json, {})
            expectation.metadata_json = dumps_json({**current, **metadata})
        if created_from and created_from not in expectation.created_from.split(","):
            expectation.created_from = ",".join([part for part in [expectation.created_from, created_from] if part])
    if status == "fulfilled":
        expectation.status = "fulfilled"
        expectation.fulfilled_by_artifact_id = fulfilled_by_artifact_id
        expectation.fulfilled_at = now
    elif expectation.status != "fulfilled":
        expectation.status = status
    expectation.updated_at = now
    return expectation


def create_run_model_diagnostics_notebook_expectations(
    db: Session,
    *,
    project: Project,
    runs: list[ExperimentRun],
    created_from: str,
) -> list[DeliverableExpectation]:
    expectations: list[DeliverableExpectation] = []
    for run in runs:
        if run.project_id != project.id:
            continue
        expectations.append(
            upsert_deliverable_expectation(
                db,
                project_id=project.id,
                kind="model_diagnostics_notebook",
                subject_ref=run_subject_ref(run.id),
                created_from=created_from,
                metadata={"run_id": run.id},
            )
        )
    return expectations


def fulfill_run_model_diagnostics_notebook_expectations(
    db: Session,
    *,
    project: Project,
    run_ids: list[str],
    notebook_artifact_id: str,
) -> list[DeliverableExpectation]:
    return [
        upsert_deliverable_expectation(
            db,
            project_id=project.id,
            kind="model_diagnostics_notebook",
            subject_ref=run_subject_ref(run_id),
            created_from="register_notebook",
            metadata={"run_id": run_id, "notebook_artifact_id": notebook_artifact_id},
            status="fulfilled",
            fulfilled_by_artifact_id=notebook_artifact_id,
        )
        for run_id in unique_strings(run_ids)
    ]


def fulfill_run_pipeline_bundle_expectations(
    db: Session,
    *,
    project: Project,
    run_ids: list[str],
    pipeline_artifact_id: str,
) -> list[DeliverableExpectation]:
    return [
        upsert_deliverable_expectation(
            db,
            project_id=project.id,
            kind="pipeline_bundle",
            subject_ref=run_subject_ref(run_id),
            created_from="register_prediction_pipeline",
            metadata={"run_id": run_id, "pipeline_artifact_id": pipeline_artifact_id},
            status="fulfilled",
            fulfilled_by_artifact_id=pipeline_artifact_id,
        )
        for run_id in unique_strings(run_ids)
    ]


def deliverable_expectations_for_run_ids(
    db: Session,
    *,
    project_id: str,
    run_ids: list[str],
) -> dict[str, list[dict[str, Any]]]:
    refs = [run_subject_ref(run_id) for run_id in unique_strings(run_ids)]
    if not refs:
        return {}
    expectations = list(
        db.scalars(
            select(DeliverableExpectation)
            .where(DeliverableExpectation.project_id == project_id, DeliverableExpectation.subject_ref.in_(refs))
            .order_by(DeliverableExpectation.created_at.asc())
        ).all()
    )
    by_run: dict[str, list[dict[str, Any]]] = {}
    for expectation in expectations:
        run_id = run_id_from_subject_ref(expectation.subject_ref)
        if run_id is None:
            continue
        by_run.setdefault(run_id, []).append(expectation_to_dict(expectation))
    return by_run


def waive_deliverable_expectation(
    db: Session,
    *,
    project: Project,
    expectation_id: str | None = None,
    kind: str | None = None,
    subject_ref: str | None = None,
    rationale: str | None = None,
) -> DeliverableExpectation:
    rationale_text = str(rationale or "").strip()
    if not rationale_text:
        raise ValueError("payload.rationale is required for waive_deliverable")
    expectation: DeliverableExpectation | None = None
    if expectation_id:
        expectation = db.get(DeliverableExpectation, expectation_id.strip())
        if expectation is None or expectation.project_id != project.id:
            raise ValueError("payload.expectation_id does not belong to this project")
    else:
        if not kind or not subject_ref:
            raise ValueError("payload.expectation_id or payload.kind + payload.subject_ref is required")
        expectation = db.scalar(
            select(DeliverableExpectation).where(
                DeliverableExpectation.project_id == project.id,
                DeliverableExpectation.kind == kind,
                DeliverableExpectation.subject_ref == subject_ref,
            )
        )
        if expectation is None:
            expectation = upsert_deliverable_expectation(
                db,
                project_id=project.id,
                kind=kind,
                subject_ref=subject_ref,
                created_from="waive_deliverable",
                metadata={},
            )
    expectation.status = "waived"
    expectation.waived_rationale = rationale_text
    expectation.updated_at = utc_now()
    return expectation


def maybe_write_open_deliverable_expectation_observation(
    db: Session,
    *,
    project: Project,
    session: AgentSession,
    workspace: Path,
    now: Any | None = None,
) -> list[DeliverableExpectation]:
    observed_at = now or utc_now()
    threshold = observed_at - OPEN_EXPECTATION_NOTIFICATION_AFTER
    expectations = list(
        db.scalars(
            select(DeliverableExpectation)
            .where(
                DeliverableExpectation.project_id == project.id,
                DeliverableExpectation.status == "open",
                DeliverableExpectation.notification_sent_at.is_(None),
                DeliverableExpectation.created_at <= threshold,
            )
            .order_by(DeliverableExpectation.created_at.asc())
            .limit(20)
        ).all()
    )
    if not expectations:
        return []
    payload = {
        "schema_version": "deliverable_expectation_observation.v1",
        "project_id": project.id,
        "agent_session_id": session.id,
        "observed_at": observed_at.isoformat(),
        "open_expectations": [expectation_to_dict(expectation) for expectation in expectations],
        "instruction": (
            "These are accepted deliverables that remain unsubmitted. Continue only if they are no longer needed; "
            "otherwise register the missing output or submit waive_deliverable with a rationale."
        ),
    }
    write_inbox_entry(
        workspace,
        entry_type="deliverable_expectations_open",
        kind="observation",
        payload=payload,
    )
    for expectation in expectations:
        expectation.notification_sent_at = observed_at
        expectation.updated_at = observed_at
    db.flush()
    return expectations


def unique_strings(values: list[str]) -> list[str]:
    output: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        output.append(text)
    return output
