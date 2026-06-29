from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from tabular_harness.core.json import loads_json
from tabular_harness.models.entities import (
    Assumption,
    AssumptionEvidenceLink,
    Evidence,
    Project,
    Question,
    utc_now,
)

REVIEWED_ASSUMPTION_STATUSES = {"confirmed", "challenged", "rejected", "resolved"}


def build_assumption_review_queue(db: Session, project: Project, *, limit: int = 8) -> dict[str, Any]:
    assumptions = db.scalars(
        select(Assumption).where(Assumption.project_id == project.id).order_by(Assumption.created_at)
    ).all()
    questions = db.scalars(
        select(Question).where(Question.project_id == project.id).order_by(Question.priority.desc(), Question.created_at)
    ).all()
    reviewable_assumptions = [
        assumption for assumption in assumptions if assumption.status not in REVIEWED_ASSUMPTION_STATUSES
    ]
    open_questions = [question for question in questions if question.status != "answered"]
    items = [_assumption_item(db, assumption) for assumption in reviewable_assumptions]
    items.extend(_question_item(question) for question in open_questions)
    items.sort(key=lambda item: (-float(item["priority_score"]), item["item_type"], item["id"]))
    queue = items[:limit]
    return {
        "schema_version": "assumption_review_queue.v1",
        "project_id": project.id,
        "generated_at": utc_now().isoformat(),
        "next_item": queue[0] if queue else None,
        "queue": queue,
        "counts": {
            "total_assumptions": len(assumptions),
            "reviewable_assumptions": len(reviewable_assumptions),
            "high_risk_reviewable_assumptions": sum(
                1
                for assumption in reviewable_assumptions
                if assumption.risk_level in {"high", "blocking", "deployment_blocking"}
            ),
            "confirmed_assumptions": sum(1 for assumption in assumptions if assumption.status == "confirmed"),
            "challenged_assumptions": sum(
                1 for assumption in assumptions if assumption.status in {"challenged", "rejected"}
            ),
            "open_questions": len(open_questions),
            "blocking_questions": sum(
                1
                for question in open_questions
                if question.blocks_next_phase or question.fallback_policy == "block_until_answered"
            ),
        },
        "guidance": [
            "Review one high-value assumption or question at a time.",
            "Confirm only when the evidence is sufficient; otherwise challenge it or answer the related question.",
            "Fallback policies remain active until the assumption or question is resolved.",
        ],
    }


def _assumption_item(db: Session, assumption: Assumption) -> dict[str, Any]:
    evidence = _assumption_evidence(db, assumption.id)
    return {
        "item_type": "assumption",
        "id": assumption.id,
        "title": _title_from_topic(assumption.topic),
        "body": assumption.statement,
        "why_it_matters": _assumption_reason(assumption),
        "status": assumption.status,
        "risk_level": assumption.risk_level,
        "fallback_policy": assumption.fallback_policy,
        "confidence": assumption.confidence,
        "priority_score": _assumption_priority(assumption),
        "evidence": evidence,
        "choices": [],
        "primary_actions": [
            {
                "id": "confirm_assumption",
                "label": "Confirm",
                "action_type": "confirm_assumption",
                "method": "POST",
                "endpoint": f"/api/assumptions/{assumption.id}/confirm",
                "request_body": {},
            },
            {
                "id": "challenge_assumption",
                "label": "Challenge",
                "action_type": "challenge_assumption",
                "method": "POST",
                "endpoint": f"/api/assumptions/{assumption.id}/reject",
                "request_body": {},
            },
        ],
    }


def _question_item(question: Question) -> dict[str, Any]:
    return {
        "item_type": "question",
        "id": question.id,
        "title": _title_from_topic(question.topic or "question"),
        "body": question.question,
        "why_it_matters": question.why_it_matters,
        "status": question.status,
        "risk_level": question.risk_level,
        "fallback_policy": question.fallback_policy,
        "confidence": None,
        "priority_score": _question_priority(question),
        "evidence": [],
        "choices": loads_json(question.choices_json, []),
        "primary_actions": [
            {
                "id": "answer_question",
                "label": "Answer",
                "action_type": "answer_question",
                "method": "POST",
                "endpoint": f"/api/questions/{question.id}/answer",
                "request_body": None,
            }
        ],
    }


def _assumption_priority(assumption: Assumption) -> float:
    score = _risk_weight(assumption.risk_level) + _fallback_weight(assumption.fallback_policy)
    if assumption.requires_user_confirmation:
        score += 30
    if assumption.status in {"inferred", "adopted"}:
        score += 12
    score += max(0.0, 1.0 - assumption.confidence) * 20.0
    return round(score, 3)


def _question_priority(question: Question) -> float:
    score = float(question.priority) + _risk_weight(question.risk_level) + _fallback_weight(question.fallback_policy)
    if question.blocks_next_phase:
        score += 45
    if not question.can_proceed_without_answer:
        score += 25
    return round(score, 3)


def _risk_weight(risk_level: str) -> float:
    return {
        "deployment_blocking": 125.0,
        "blocking": 120.0,
        "high": 100.0,
        "medium": 60.0,
        "low": 25.0,
    }.get(risk_level, 40.0)


def _fallback_weight(fallback_policy: str) -> float:
    return {
        "block_until_answered": 55.0,
        "require_before_deployment": 45.0,
        "exclude_until_confirmed": 35.0,
        "scenario_compare": 25.0,
        "conservative_default": 15.0,
        "infer_and_continue": 5.0,
    }.get(fallback_policy, 10.0)


def _assumption_evidence(db: Session, assumption_id: str) -> list[dict[str, Any]]:
    links = db.scalars(select(AssumptionEvidenceLink).where(AssumptionEvidenceLink.assumption_id == assumption_id)).all()
    if not links:
        return []
    evidence = db.scalars(select(Evidence).where(Evidence.id.in_([link.evidence_id for link in links]))).all()
    return [
        {
            "id": item.id,
            "evidence_type": item.evidence_type,
            "summary": item.summary,
            "strength": item.strength,
            "source_artifact_id": item.source_artifact_id,
        }
        for item in evidence
    ]


def _assumption_reason(assumption: Assumption) -> str:
    if assumption.fallback_policy == "exclude_until_confirmed":
        return "If wrong, downstream features or evaluation may use information that is unavailable at prediction time."
    if assumption.fallback_policy == "scenario_compare":
        return "If wrong, compare scenarios before treating the assumption as a modeling constraint."
    if assumption.fallback_policy == "block_until_answered":
        return "This must be resolved before the next phase can be trusted."
    return "This affects evaluation trust, feature design, or deployment readiness."


def _title_from_topic(topic: str) -> str:
    return topic.replace("_", " ").strip().title() or "Review Item"
