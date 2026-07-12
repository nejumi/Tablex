from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from tabular_harness.core.ids import new_id
from tabular_harness.core.json import dumps_json, loads_json
from tabular_harness.models.entities import Asset, AssetReference, AssetVersion
from tabular_harness.services.approach import store_json_artifact
from tabular_harness.services.artifacts import LocalArtifactStore, create_lineage_edge

DEFAULT_PROJECT_SKILL_NAMES = {
    "tablex_grandmaster_eda",
    "tablex_modeling_strategy",
    "tablex_onodera_deep_dive",
    "tabular_approach_research",
    "tabular_gradient_boosting_strategy",
    "evaluation_diagnostics_interpreter",
}

DEFAULT_LIBRARY_ASSETS: list[dict[str, Any]] = [
    {
        "asset_type": "skill",
        "name": "tabular_approach_research",
        "description": "Guides an agent to research tabular modeling approaches while preserving harness-owned evaluation.",
        "tags": ["agent", "research", "tabular"],
        "semantic_tags": ["approach_studio", "controlled_research"],
        "content": {
            "instructions": [
                "Use project artifacts and approved EvaluationSpec first.",
                "Use controlled web or literature search only when allowed by AgentTaskContract.",
                "Return citations as Evidence or artifact-backed sources.",
            ]
        },
    },
    {
        "asset_type": "skill",
        "name": "tablex_grandmaster_eda",
        "description": (
            "Guides Codex to perform Kaggle Grandmaster-inspired tabular EDA, hypothesis extraction, "
            "multi-table deep dives, and marimo reporting without constraining approach choice."
        ),
        "tags": ["agent", "eda", "marimo", "kaggle", "hypothesis"],
        "semantic_tags": [
            "data_understanding",
            "grandmaster_eda",
            "hypothesis_extraction",
            "multi_table_eda",
            "marimo_notebook",
            "visual_story",
            "skill",
        ],
        "content": {
            "skill_path": "skills/tablex-grandmaster-eda/SKILL.md",
            "reference_paths": [
                "skills/tablex-grandmaster-eda/references/grandmaster_eda_patterns.md",
                "skills/tablex-grandmaster-eda/references/tablex_marimo_outputs.md",
            ],
            "instructions": [
                "Use this as craft context for deep data understanding, not as deterministic harness logic.",
                "Let Codex infer objectives, choose analyses, generate hypotheses, and write marimo notebooks from evidence.",
                "Build a domain model of the people, organizations, machines, markets, policies, physical processes, incentives, constraints, and decisions that generated the records and surround the prediction-time decision.",
                "Use imaginative mechanisms to find hypotheses generic AutoML would miss, while labeling measured facts, external evidence, hypotheses, and assumptions separately and seeking disconfirming evidence.",
                "Move between macro profiling and representative raw entity histories, cohorts, edge cases, and model errors so feature ideas reflect observed mechanisms rather than column availability alone.",
                "Translate domain and data hypotheses into prediction-time-safe feature families, then validate their incremental value with fold-consistent ablations and use the result to choose the next investigation.",
                "Register hypotheses, visual story cards, evidence bundles, notebook source, reports, and next-analysis queues as artifacts.",
                "Ask useful questions, but in Full Auto continue with explicit assumptions and fallback policies when safe.",
            ],
            "expected_outputs": [
                "notebooks/grandmaster_eda.py",
                "reports/eda_story.md",
                "artifacts/eda_hypotheses.json",
                "artifacts/visual_story_cards.json",
                "artifacts/research_source_notes.json",
                "artifacts/notebook_figure_manifest.json",
                "artifacts/notebook_evidence_bundle.json",
                "artifacts/next_analysis_queue.json",
            ],
            "source_inspirations": [
                {
                    "title": "Kaggle EDA for tabular data: Advanced Techniques",
                    "url": "https://www.kaggle.com/code/vbmokin/eda-for-tabular-data-advanced-techniques",
                    "use": "Index of strong public tabular EDA examples.",
                },
                {
                    "title": "Kaggle Data Science for tabular data: Advanced Techniques",
                    "url": "https://www.kaggle.com/code/vbmokin/data-science-for-tabular-data-advanced-techniques",
                    "use": "Index of advanced tabular data-science workflows.",
                },
                {
                    "title": "The Kaggle Grandmasters Playbook: 7 Battle-Tested Modeling Techniques for Tabular Data",
                    "url": "https://developer.nvidia.com/blog/the-kaggle-grandmasters-playbook-7-battle-tested-modeling-techniques-for-tabular-data/",
                    "use": "Grandmaster workflow principles: smarter EDA, validation, baselines, feature generation, fast feedback.",
                },
                {
                    "title": "Kaggle Grandmasters Unveil Winning Strategies for Data Science Superpowers",
                    "url": "https://developer.nvidia.com/blog/kaggle-grandmasters-unveil-winning-strategies-for-data-science-superpowers/",
                    "use": "Problem formulation, data storytelling, validation, train/test difference, and iterative intuition.",
                },
                {
                    "title": "M5 competition methods and results",
                    "url": "https://github.com/Mcompetitions/M5-methods",
                    "use": "Forecasting evidence on evaluation windows, hierarchy-aware pooling, recursive versus direct horizons, and combining complementary estimates.",
                },
                {
                    "title": "Using Big Data to Enhance the Bosch Production Line Performance",
                    "url": "https://arxiv.org/abs/1701.00705",
                    "use": "Manufacturing example of recovering process structure and validating features from high-dimensional production records.",
                },
                {
                    "title": "ASHRAE Great Energy Predictor III competition: overview and results",
                    "url": "https://arxiv.org/abs/2007.06933",
                    "use": "Cross-domain evidence on validation, reproducible workflows, domain-informed preprocessing, and complementary model diversity.",
                },
                {
                    "title": "The Kaggle Book code repository",
                    "url": "https://github.com/PacktPublishing/The-Kaggle-Book",
                    "use": "Grandmaster-authored, cross-domain examples of validation, adversarial checks, feature engineering, and ensembling craft.",
                },
                {
                    "title": "marimo as reusable Python notebooks",
                    "url": "https://docs.marimo.io/",
                    "use": "Native interactive notebook authoring, review, and reusable Python source artifacts.",
                },
            ],
            "guardrails": [
                "Do not read secrets or connector credentials.",
                "Do not use validation/test targets in feature generation prompts, encoders, joins, or imputers.",
                "Do not destructively modify EvaluationSpec or SplitManifest.",
                "Do not copy public notebook prose, code, images, or section order.",
                "Treat Give Up as a last resort after preserving useful partial artifacts.",
            ],
        },
    },
    {
        "asset_type": "skill",
        "name": "tabular_gradient_boosting_strategy",
        "description": "Guides runner-side selection of mixed-type tabular gradient boosting approaches under harness evaluation.",
        "tags": ["agent", "modeling", "tabular", "xgboost"],
        "semantic_tags": ["tabular_modeling", "gradient_boosting", "baseline_strategy", "xgboost"],
        "content": {
            "instructions": [
                "Treat dummy and linear models as sanity floors, not the final baseline when richer features are justified.",
                "Consider XGBoost or another tree boosting family for numeric, categorical, datetime, and text-derived features.",
                "Justify preprocessing choices from project artifacts, ResearchPlan, and SplitManifest constraints.",
            ],
            "expected_outputs": ["feature_recipe", "metrics", "run_report", "visualization_spec"],
        },
    },
    {
        "asset_type": "skill",
        "name": "tablex_modeling_strategy",
        "description": (
            "Equips Codex with evaluation-first tabular modeling craft: sanity floors, linear models, tree ensembles, "
            "calibration, ensembling, foundation tabular models, diagnostics, and prediction pipeline packaging."
        ),
        "tags": ["agent", "modeling", "tabular", "ensemble", "diagnostics"],
        "semantic_tags": [
            "tabular_modeling",
            "modeling_strategy",
            "ensemble",
            "calibration",
            "model_diagnostics",
            "foundation_tabular_model",
            "prediction_pipeline",
            "skill",
        ],
        "content": {
            "skill_path": "skills/tablex-modeling-strategy/SKILL.md",
            "instructions": [
                "Use this as craft context for choosing and explaining modeling strategies, not as a fixed recipe.",
                "Compare models only under the same EvaluationSpec and SplitManifest; label provisional results plainly.",
                "Treat a generic merged-table boosted model as an initial reference, not an automatic stopping point. Pursue project-specific feature and model hypotheses while reversible work has material expected value.",
                "Use out-of-fold ablations, subgroup stability, calibration, worst-error review, and residual structure to distinguish feature gains from estimator gains and to generate the next hypothesis.",
                "Run feature-hypothesis iterations autonomously on unchanged folds: mechanism, minimal coherent feature family, out-of-fold delta and uncertainty, affected slices/errors, conclusion, then evidence-driven next hypothesis.",
                "Keep disposable probes in an experiment ledger and promote serious distinct candidates to registered, fully packaged runs so reproducibility work does not replace investigation.",
                "Consider baselines, linear models, tree ensembles, calibration, ensembling, TabPFN/TabICL-style options, and target-free methods when the project evidence supports them.",
                "Register serious candidates with diagnostics, reports, and reproducible prediction pipelines.",
            ],
            "expected_outputs": [
                "experiment_runs",
                "model_diagnostics_notebook",
                "model_report",
                "prediction_pipeline_bundle",
            ],
            "guardrails": [
                "Do not read secrets or connector credentials.",
                "Do not use validation/test targets in feature generation or prompts.",
                "Do not destructively modify EvaluationSpec or SplitManifest.",
                "Do not force a model-family sequence or harness-side diversity gate.",
            ],
        },
    },
    {
        "asset_type": "skill",
        "name": "tablex_llm_feature_augmentation",
        "description": (
            "Guides Codex when it considers LLM-generated row-level or text-normalization features, with leakage "
            "discipline, deterministic caching, provenance, cost awareness, and pipeline packaging."
        ),
        "tags": ["agent", "feature_engineering", "llm", "tabular"],
        "semantic_tags": [
            "llm_feature_augmentation",
            "feature_engineering",
            "leakage_control",
            "deterministic_cache",
            "prediction_pipeline",
            "skill",
        ],
        "content": {
            "skill_path": "skills/tablex-llm-feature-augmentation/SKILL.md",
            "instructions": [
                "Use this only when project evidence suggests LLM-derived features may help and the cost/safety tradeoff is acceptable.",
                "Never include target values or validation/test labels in generation prompts, examples, cache keys, or summaries.",
                "Cache generated features deterministically and record prompt/model/cache provenance as artifact metadata.",
                "Package prompt files and generation code with any prediction pipeline that depends on generated features.",
            ],
            "expected_outputs": [
                "generated_feature_artifact",
                "feature_generation_report",
                "experiment_run_comparison",
                "prediction_pipeline_bundle",
            ],
            "guardrails": [
                "No new harness-owned generation workflow is implied by this Skill.",
                "External API use must follow existing Tablex network and credential approval policy.",
                "Generated-feature models remain exploratory unless the prediction pipeline can reproduce the features for new data.",
            ],
        },
    },
    {
        "asset_type": "skill",
        "name": "tablex_onodera_deep_dive",
        "description": (
            "Equips Codex to inspect representative raw entity trajectories, derive behavioral feature hypotheses, "
            "and validate micro observations with macro evidence."
        ),
        "tags": ["agent", "eda", "feature_engineering", "kaggle", "trajectory"],
        "semantic_tags": [
            "data_understanding",
            "feature_engineering",
            "entity_trajectory",
            "micro_case_study",
            "hypothesis_extraction",
            "model_diagnostics",
            "skill",
        ],
        "content": {
            "skill_path": "skills/tablex-onodera-deep-dive/SKILL.md",
            "instructions": [
                "Use this as craft context when repeated entity, item, session, order, account, or event histories are available.",
                "Inspect raw micro trajectories across target classes, target bins, important categories, edge cases, and model errors.",
                "Recover domain event semantics before aggregating: identify starts, ends, intervals, ordering, overlap or concurrency, transitions, recurrence, and behavior changes that are observable at prediction time.",
                "Use reconstructed timelines to ask mechanism-level questions that generic group-by statistics cannot express, then encode those mechanisms as auditable feature families.",
                "Treat count/mean/min/max plus a flat merge as a lossy baseline. Preserve conditional distributions, tails, recency windows, period deltas, trends, change points, spacing, duration, sequence, nested-history, or cross-table consistency only where a semantic hypothesis justifies them.",
                "Turn observed mechanisms into feature families, then validate them with fold-safe macro evidence and ablations.",
                "Tie notebook/report narrative back to raw trajectory observations, feature intent, validation evidence, and model effect.",
            ],
            "expected_outputs": [
                "micro_casebook_notebook_section",
                "feature_hypothesis_records",
                "macro_validation_plots",
                "model_effect_ablation_notes",
            ],
            "guardrails": [
                "Do not inspect validation or test labels to invent features.",
                "Do not overfit memorable anecdotes; micro cases generate hypotheses and macro validation decides.",
                "Do not copy external solution text, code, figures, or section order.",
                "Respect EvaluationSpec, SplitManifest, and prediction-time availability.",
            ],
        },
    },
    {
        "asset_type": "feature_recipe",
        "name": "xgboost_mixed_type_baseline",
        "description": "Feature recipe outline for numeric imputation, ordinal categoricals, optional TF-IDF text blocks, datetime parts, and XGBoost.",
        "tags": ["features", "baseline", "xgboost"],
        "semantic_tags": [
            "tabular_modeling",
            "gradient_boosting",
            "xgboost",
            "mixed_type",
            "categorical_encoding",
            "text_features",
            "datetime_features",
            "split_manifest",
        ],
        "content": {
            "numeric": "median imputation fitted on train split",
            "categorical": "ordinal encoding with unknown handling fitted on train split",
            "text": "TF-IDF or hashing only for prediction-time available text columns",
            "datetime": "calendar parts and elapsed-time features when deployment timing is valid",
            "model_family": "xgboost with sklearn fallback when unavailable",
            "guardrails": ["no validation/test target in prompts or encoders", "respect SplitManifest"],
        },
    },
    {
        "asset_type": "feature_recipe",
        "name": "text_tfidf_train_fold_recipe",
        "description": "Train-fold-only text feature recipe for tabular text columns.",
        "tags": ["features", "text", "tfidf"],
        "semantic_tags": ["text_features", "tfidf", "split_manifest", "leakage_control"],
        "content": {
            "fit_scope": "train_split_only",
            "transforms": ["tfidf_word_ngrams", "tfidf_char_ngrams_optional", "sparse_dimensionality_cap"],
            "scenario_compare": ["without_text", "with_text"],
            "guardrails": ["exclude target-derived text", "document prediction-time availability"],
        },
    },
    {
        "asset_type": "feature_recipe",
        "name": "causal_time_lag_rolling_features",
        "description": "Causal lag, rolling, and calendar feature recipe for time-aware tabular or forecasting tasks.",
        "tags": ["features", "time", "forecasting"],
        "semantic_tags": ["time_features", "lag_features", "rolling_statistics", "datetime_features", "split_manifest"],
        "content": {
            "features": ["day_of_week", "month", "lag_by_group", "rolling_mean_by_group", "rolling_std_by_group"],
            "fit_scope": "history_available_before_prediction_time",
            "required_controls": ["time_split_or_explicit_justification", "no future rows in rolling windows"],
        },
    },
    {
        "asset_type": "feature_recipe",
        "name": "relational_aggregation_recipe",
        "description": "Multi-table representation recipe for repeated entity, event, interval, or state-history tables.",
        "tags": ["features", "relational", "multi_table"],
        "semantic_tags": ["relational_features", "multi_table", "aggregation", "split_manifest", "leakage_control"],
        "content": {
            "join_policy": "use RelationalCatalog key candidates, then require semantic confirmation",
            "aggregations": ["count", "mean", "max", "min", "recent_window_count", "time_since_last_event"],
            "guardrails": ["aggregate within train folds", "exclude holdout/test tables", "verify prediction-time availability"],
        },
    },
    {
        "asset_type": "evaluation_pattern",
        "name": "time_series_forward_validation",
        "description": "Evaluation pattern for time split or rolling-origin validation before accepting temporal features.",
        "tags": ["evaluation", "time", "forecasting"],
        "semantic_tags": ["time_features", "time_split", "forward_validation", "split_manifest"],
        "content": {
            "candidate_splits": ["time_split", "rolling_origin_future_work"],
            "checks": ["no train rows after validation rows", "stable horizon definition", "known-future covariates only"],
        },
    },
    {
        "asset_type": "evaluation_pattern",
        "name": "relational_entity_split_review",
        "description": "Evaluation pattern for reviewing entity leakage in multi-table tabular tasks.",
        "tags": ["evaluation", "relational", "leakage"],
        "semantic_tags": ["relational_features", "group_split", "leakage_control", "split_manifest"],
        "content": {
            "checks": ["entity overlap by split", "supporting table event time", "target leakage by joined columns"],
            "candidate_splits": ["group_split", "time_split", "stratified_split_with_leakage_review"],
        },
    },
    {
        "asset_type": "skill",
        "name": "evaluation_diagnostics_interpreter",
        "description": "Guides interpretation of diagnostics, slices, calibration, worst examples, and sanity checks.",
        "tags": ["agent", "diagnostics", "reporting"],
        "semantic_tags": ["evaluation_diagnostics", "slice_metrics", "reporting", "decision_dashboard"],
        "content": {
            "instructions": [
                "Compare run metrics to sanity floors and baseline strategy expectations.",
                "Summarize slice, bin, calibration, and worst-example diagnostics as reportable Insights.",
                "Separate metric movement from deployment readiness.",
            ]
        },
    },
    {
        "asset_type": "prompt_template",
        "name": "decision_report_prompt",
        "description": "Prompt template for decision-oriented reports that summarize readiness, risks, evidence, and next actions.",
        "tags": ["report", "decision"],
        "semantic_tags": ["decision_reporting", "decision_dashboard", "reports", "reporting"],
        "content": {
            "sections": ["Readiness", "Evaluation", "Model Evidence", "Risks", "Benchmark Caveats", "Next Actions"],
            "requirements": ["cite Tablex artifact ids", "avoid external dashboard dependency", "call out unresolved assumptions"],
        },
    },
    {
        "asset_type": "visualization_template",
        "name": "decision_readiness_dashboard",
        "description": "Visualization template for readiness stages, artifact completeness, risk counts, and next actions.",
        "tags": ["visualization", "decision", "readiness"],
        "semantic_tags": ["decision_dashboard", "readiness", "reports", "visualization"],
        "content": {
            "chart_types": ["stage_status", "category_bars", "metric_cards"],
            "panels": ["readiness_stages", "artifact_completeness", "risk_summary", "next_actions"],
        },
    },
    {
        "asset_type": "evaluation_pattern",
        "name": "scenario_compare_text_features",
        "description": "Compare no-text and text-enhanced scenarios under the same SplitManifest.",
        "tags": ["evaluation", "scenario_compare", "text"],
        "semantic_tags": ["text_features", "split_manifest"],
        "content": {
            "scenarios": ["without_text", "with_text"],
            "required_controls": ["same_split_manifest", "train_fold_only_vectorizer"],
        },
    },
    {
        "asset_type": "prompt_template",
        "name": "agent_result_report_prompt",
        "description": "Template for concise agent run reports with metrics, assumptions, risks, and next steps.",
        "tags": ["report", "prompt"],
        "semantic_tags": ["agent_result", "reporting"],
        "content": {
            "sections": ["Objective", "Data/Evaluation Context", "Implementation", "Results", "Risks", "Next Steps"]
        },
    },
    {
        "asset_type": "visualization_template",
        "name": "leaderboard_primary_metric",
        "description": "Portable visualization template for comparing primary metrics across runs.",
        "tags": ["visualization", "leaderboard"],
        "semantic_tags": ["metrics", "reports"],
        "content": {
            "chart_type": "leaderboard_bar",
            "encoding": {"x": "run_id", "y": "primary_metric_value", "color": "runner_type"},
        },
    },
    {
        "asset_type": "feature_recipe",
        "name": "prediction_time_safe_features",
        "description": "Checklist for feature recipes that avoid target leakage and respect prediction-time availability.",
        "tags": ["features", "safety"],
        "semantic_tags": ["leakage_control", "prediction_time"],
        "content": {
            "checks": [
                "exclude target and validation/test labels",
                "exclude unconfirmed leakage-suspect columns",
                "fit encoders on train split only",
            ]
        },
    },
]


def seed_default_assets(db: Session, store: LocalArtifactStore) -> list[Asset]:
    created_or_existing: list[Asset] = []
    for definition in DEFAULT_LIBRARY_ASSETS:
        existing = db.scalar(
            select(Asset).where(Asset.asset_type == definition["asset_type"], Asset.name == definition["name"])
        )
        if existing is not None:
            created_or_existing.append(existing)
            continue
        created_or_existing.append(create_library_asset(db, store=store, payload=definition))
    return created_or_existing


def equip_default_project_skills(db: Session, store: LocalArtifactStore, *, project_id: str) -> list[AssetReference]:
    assets = seed_default_assets(db, store)
    references: list[AssetReference] = []
    for asset in assets:
        if asset.asset_type != "skill" or asset.name not in DEFAULT_PROJECT_SKILL_NAMES or not asset.latest_version_id:
            continue
        existed = db.scalar(
            select(AssetReference).where(
                AssetReference.source_type == "project",
                AssetReference.source_id == project_id,
                AssetReference.target_asset_id == asset.id,
                AssetReference.relation_type == "equipped_for_agent_context",
            )
        )
        reference = create_asset_reference(
            db,
            source_type="project",
            source_id=project_id,
            target_asset_id=asset.id,
            target_asset_version_id=asset.latest_version_id,
            relation_type="equipped_for_agent_context",
        )
        references.append(reference)
        if existed is None:
            create_lineage_edge(
                db,
                project_id=project_id,
                from_asset_type="project",
                from_asset_id=project_id,
                to_asset_type="library_asset",
                to_asset_id=asset.id,
                relation_type="equipped_for_agent_context",
            )
    return references


def create_library_asset(db: Session, *, store: LocalArtifactStore, payload: dict[str, Any]) -> Asset:
    asset_id = new_id("asset")
    owner_user_id = payload.get("owner_user_id")
    artifact = store_json_artifact(
        db,
        store,
        project_id=None,
        asset_type=f"library_{payload['asset_type']}",
        name=str(payload["name"]),
        filename="asset_version.json",
        payload={
            "schema_version": "asset_version.v1",
            "asset_type": payload["asset_type"],
            "name": payload["name"],
            "description": payload.get("description"),
            "content": payload.get("content") or {},
            "tags": payload.get("tags") or [],
            "semantic_tags": payload.get("semantic_tags") or [],
        },
        metadata={"asset_id": asset_id, "scope": "organization"},
        created_by=str(owner_user_id) if owner_user_id else "local-user",
    )
    asset = Asset(
        id=asset_id,
        asset_type=str(payload["asset_type"]),
        name=str(payload["name"]),
        description=payload.get("description"),
        scope="organization",
        owner_user_id=str(owner_user_id) if owner_user_id else None,
        tags_json=dumps_json(payload.get("tags") or []),
        semantic_tags_json=dumps_json(payload.get("semantic_tags") or []),
        visibility=str(payload.get("visibility") or "private"),
        status="active",
    )
    db.add(asset)
    db.flush()
    version = AssetVersion(
        id=new_id("av"),
        asset_id=asset.id,
        version="1.0.0",
        artifact_id=artifact.id,
        digest=artifact.content_hash,
        inputs_schema_json=dumps_json(payload.get("inputs_schema") or {}),
        outputs_schema_json=dumps_json(payload.get("outputs_schema") or {}),
        runtime_requirements_json=dumps_json(payload.get("runtime_requirements") or {}),
        created_from_project_id=payload.get("created_from_project_id"),
        created_from_run_id=payload.get("created_from_run_id"),
        status="active",
        created_by=str(owner_user_id) if owner_user_id else "local-user",
    )
    db.add(version)
    db.flush()
    asset.latest_version_id = version.id
    return asset


def create_asset_reference(
    db: Session,
    *,
    source_type: str,
    source_id: str,
    target_asset_id: str,
    target_asset_version_id: str,
    relation_type: str,
) -> AssetReference:
    asset = db.get(Asset, target_asset_id)
    version = db.get(AssetVersion, target_asset_version_id)
    if asset is None or version is None or version.asset_id != asset.id:
        raise ValueError("Target asset/version not found")
    existing = db.scalar(
        select(AssetReference).where(
            AssetReference.source_type == source_type,
            AssetReference.source_id == source_id,
            AssetReference.target_asset_id == target_asset_id,
            AssetReference.target_asset_version_id == target_asset_version_id,
        )
    )
    if existing is not None:
        return existing
    reference = AssetReference(
        id=new_id("aref"),
        source_type=source_type,
        source_id=source_id,
        target_asset_id=target_asset_id,
        target_asset_version_id=target_asset_version_id,
        relation_type=relation_type,
        locked=True,
    )
    db.add(reference)
    db.flush()
    return reference


def asset_to_dict(asset: Asset) -> dict[str, Any]:
    return {
        "id": asset.id,
        "asset_type": asset.asset_type,
        "name": asset.name,
        "description": asset.description,
        "scope": asset.scope,
        "tags": loads_json(asset.tags_json, []),
        "semantic_tags": loads_json(asset.semantic_tags_json, []),
        "latest_version_id": asset.latest_version_id,
        "visibility": asset.visibility,
        "status": asset.status,
        "created_at": asset.created_at.isoformat(),
        "updated_at": asset.updated_at.isoformat(),
    }


def asset_version_to_dict(version: AssetVersion) -> dict[str, Any]:
    return {
        "id": version.id,
        "asset_id": version.asset_id,
        "version": version.version,
        "artifact_id": version.artifact_id,
        "digest": version.digest,
        "inputs_schema": loads_json(version.inputs_schema_json, {}),
        "outputs_schema": loads_json(version.outputs_schema_json, {}),
        "runtime_requirements": loads_json(version.runtime_requirements_json, {}),
        "created_from_project_id": version.created_from_project_id,
        "created_from_run_id": version.created_from_run_id,
        "status": version.status,
        "created_at": version.created_at.isoformat(),
    }


def asset_reference_to_dict(
    reference: AssetReference,
    *,
    asset: Asset | None = None,
    version: AssetVersion | None = None,
) -> dict[str, Any]:
    return {
        "id": reference.id,
        "source_type": reference.source_type,
        "source_id": reference.source_id,
        "target_asset_id": reference.target_asset_id,
        "target_asset_version_id": reference.target_asset_version_id,
        "relation_type": reference.relation_type,
        "locked": reference.locked,
        "created_at": reference.created_at.isoformat(),
        "asset": asset_to_dict(asset) if asset else None,
        "version": asset_version_to_dict(version) if version else None,
    }
