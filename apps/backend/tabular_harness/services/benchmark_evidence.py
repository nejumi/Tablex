from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from tabular_harness.core.config import Settings
from tabular_harness.core.ids import new_id
from tabular_harness.core.json import dumps_json, loads_json
from tabular_harness.models.entities import (
    Artifact,
    DatasetSnapshot,
    Evidence,
    ExperimentRun,
    Job,
    Project,
    Report,
    VisualizationSpec,
    utc_now,
)
from tabular_harness.services.approach import (
    first_sentence,
    store_json_artifact,
    store_text_artifact,
)
from tabular_harness.services.artifacts import LocalArtifactStore, create_lineage_edge
from tabular_harness.services.benchmarks import (
    benchmark_access,
    benchmark_source_card,
    compact_local_status,
    default_benchmark_root,
    inspect_benchmark_local_files,
    raw_benchmark_dataset,
)
from tabular_harness.services.reporting import persist_visualization_spec

BENCHMARK_ARTIFACT_TYPES = {
    "benchmark_import_manifest",
    "benchmark_public_download_manifest",
    "benchmark_scenario_pack",
    "benchmark_scenario_report",
    "benchmark_supporting_table",
    "data_quality_gate",
    "data_quality_report",
    "relational_catalog",
    "baseline_strategy_plan",
    "baseline_report",
    "baseline_metrics",
    "evaluation_diagnostics",
    "evaluation_diagnostics_report",
    "run_report",
    "decision_dashboard",
    "decision_report",
    "agent_task_contract",
    "agent_task_readiness_review",
    "agent_task_readiness_report",
    "agent_result",
    "agent_task_report",
}

BENCHMARK_JOB_TYPES = {
    "download_public_benchmark_archive",
    "import_benchmark_dataset",
    "create_benchmark_scenario_pack",
    "run_benchmark_fixture_smoke",
    "run_public_benchmark_workflow",
    "plan_baseline_strategy",
    "run_baseline",
    "analyze_evaluation_diagnostics",
    "draft_run_report",
    "generate_decision_dashboard",
    "plan_agent_task",
    "prepare_planned_agent_workspace",
    "review_agent_task_readiness",
    "run_planned_agent_task_stub",
}


@dataclass(frozen=True)
class BenchmarkEvidencePackResult:
    pack: dict[str, Any]
    report: Report
    evidence: Evidence
    visualization: VisualizationSpec
    pack_artifact: Artifact
    report_artifact: Artifact
    visualization_artifact: Artifact
    artifact_ids: list[str]


def create_benchmark_evidence_pack(
    db: Session,
    *,
    store: LocalArtifactStore,
    project: Project,
    settings: Settings,
    job: Job | None = None,
) -> BenchmarkEvidencePackResult:
    artifacts = list(
        db.scalars(
            select(Artifact)
            .where(Artifact.project_id == project.id)
            .order_by(Artifact.created_at.desc())
        ).all()
    )
    jobs = list(
        db.scalars(select(Job).where(Job.project_id == project.id).order_by(Job.created_at.desc())).all()
    )
    datasets = list(
        db.scalars(
            select(DatasetSnapshot)
            .where(DatasetSnapshot.project_id == project.id)
            .order_by(DatasetSnapshot.created_at.desc())
        ).all()
    )
    runs = list(
        db.scalars(
            select(ExperimentRun)
            .where(ExperimentRun.project_id == project.id)
            .order_by(ExperimentRun.started_at.desc())
        ).all()
    )
    reports = list(
        db.scalars(select(Report).where(Report.project_id == project.id).order_by(Report.created_at.desc())).all()
    )
    visualizations = list(
        db.scalars(
            select(VisualizationSpec)
            .where(VisualizationSpec.project_id == project.id)
            .order_by(VisualizationSpec.created_at.desc())
        ).all()
    )

    benchmark_ids = discover_benchmark_ids(artifacts=artifacts, jobs=jobs, datasets=datasets)
    entries = [
        build_benchmark_entry(
            db,
            project=project,
            settings=settings,
            benchmark_id=benchmark_id,
            artifacts=artifacts,
            jobs=jobs,
            datasets=datasets,
            runs=runs,
            reports=reports,
            visualizations=visualizations,
        )
        for benchmark_id in benchmark_ids
    ]
    pack = {
        "schema_version": "benchmark_evidence_pack.v1",
        "project": {
            "id": project.id,
            "name": project.name,
            "task_type": project.task_type,
            "target_column": project.target_column,
            "current_phase": project.current_phase,
        },
        "generated_at": utc_now().isoformat(),
        "benchmark_count": len(entries),
        "benchmarks": entries,
        "summary": benchmark_pack_summary(entries),
        "next_actions": benchmark_pack_next_actions(entries),
        "policy": {
            "agent_receives_credentials": False,
            "external_dashboards_required": False,
            "credentialed_sources": "user_managed_outside_tablex",
            "network_downloads": "only catalog credential-free public sources when explicitly requested",
        },
    }
    pack_artifact = store_json_artifact(
        db,
        store,
        project_id=project.id,
        asset_type="benchmark_evidence_pack",
        name=f"benchmark_evidence_pack_{new_id('bep')}",
        filename="benchmark_evidence_pack.json",
        payload=pack,
        metadata={
            "project_id": project.id,
            "job_id": job.id if job else None,
            "benchmark_count": len(entries),
            "benchmark_ids": benchmark_ids,
            "ready_benchmark_count": sum(1 for entry in entries if entry["overall_status"] == "ready"),
        },
    )
    report_md = render_benchmark_evidence_report(pack)
    report_artifact = store_text_artifact(
        db,
        store,
        project_id=project.id,
        asset_type="benchmark_evidence_report",
        name=f"benchmark_evidence_report_{new_id('ber')}",
        filename="benchmark_evidence_report.md",
        text=report_md,
        metadata={
            "project_id": project.id,
            "job_id": job.id if job else None,
            "benchmark_count": len(entries),
            "benchmark_ids": benchmark_ids,
            "pack_artifact_id": pack_artifact.id,
            "report_type": "benchmark_evidence_report",
        },
    )
    report = Report(
        id=new_id("rpt"),
        project_id=project.id,
        report_type="benchmark_evidence_report",
        title="Benchmark Evidence Pack",
        summary=first_sentence(report_md),
        artifact_id=report_artifact.id,
        source_asset_ids_json=dumps_json(build_source_assets(entries, pack_artifact)),
        status="draft",
        created_by_type="system",
    )
    db.add(report)
    evidence = Evidence(
        id=new_id("ev"),
        project_id=project.id,
        evidence_type="benchmark_evidence_pack",
        summary=(
            f"Benchmark Evidence Pack summarizes {len(entries)} benchmark context(s), "
            f"{sum(len(entry['artifacts']) for entry in entries)} artifacts, and "
            f"{sum(len(entry['jobs']) for entry in entries)} jobs."
        ),
        strength="medium" if entries else "weak",
        source_artifact_id=pack_artifact.id,
        metadata_json=dumps_json(
            {
                "job_id": job.id if job else None,
                "benchmark_ids": benchmark_ids,
                "report_artifact_id": report_artifact.id,
            }
        ),
    )
    db.add(evidence)
    visualization, visualization_artifact = persist_visualization_spec(
        db,
        store=store,
        project=project,
        spec=build_benchmark_evidence_visualization(pack),
        source_artifact_id=pack_artifact.id,
    )
    db.flush()
    create_benchmark_evidence_lineage(
        db,
        project=project,
        job=job,
        pack_artifact=pack_artifact,
        report=report,
        report_artifact=report_artifact,
        evidence=evidence,
        visualization=visualization,
        entries=entries,
    )
    artifact_ids = list(dict.fromkeys([pack_artifact.id, report_artifact.id, visualization_artifact.id]))
    return BenchmarkEvidencePackResult(
        pack=pack,
        report=report,
        evidence=evidence,
        visualization=visualization,
        pack_artifact=pack_artifact,
        report_artifact=report_artifact,
        visualization_artifact=visualization_artifact,
        artifact_ids=artifact_ids,
    )


def discover_benchmark_ids(
    *,
    artifacts: list[Artifact],
    jobs: list[Job],
    datasets: list[DatasetSnapshot],
) -> list[str]:
    ids: list[str] = []
    for artifact in artifacts:
        metadata = loads_json(artifact.metadata_json, {})
        add_benchmark_id(ids, metadata.get("benchmark_id"))
        add_benchmark_ids(ids, metadata.get("benchmark_ids"))
    for job in jobs:
        add_benchmark_id(ids, loads_json(job.input_json, {}).get("benchmark_id"))
        add_benchmark_id(ids, loads_json(job.output_json, {}).get("benchmark_id"))
    for dataset in datasets:
        if dataset.source_type == "benchmark_catalog" and dataset.source_ref:
            add_benchmark_id(ids, dataset.source_ref.split(":", 1)[0])
    return ids


def add_benchmark_id(ids: list[str], value: Any) -> None:
    if isinstance(value, str) and value and value not in ids:
        ids.append(value)


def add_benchmark_ids(ids: list[str], value: Any) -> None:
    if not isinstance(value, list):
        return
    for item in value:
        add_benchmark_id(ids, item)


def build_benchmark_entry(
    db: Session,
    *,
    project: Project,
    settings: Settings,
    benchmark_id: str,
    artifacts: list[Artifact],
    jobs: list[Job],
    datasets: list[DatasetSnapshot],
    runs: list[ExperimentRun],
    reports: list[Report],
    visualizations: list[VisualizationSpec],
) -> dict[str, Any]:
    benchmark = safe_raw_benchmark(benchmark_id)
    local_status: dict[str, Any] = {}
    source_card: dict[str, Any] = {
        "status": "catalog_entry_missing",
        "benchmark_id": benchmark_id,
        "access": {"agent_receives_credentials": False},
    }
    if benchmark is not None:
        root = default_benchmark_root(settings, benchmark_id)
        inspected = inspect_benchmark_local_files(benchmark, root)
        local_status = compact_local_status(inspected)
        source_card = benchmark_source_card(
            benchmark,
            settings=settings,
            local_path=None,
            local_status=inspected,
        )

    benchmark_artifacts = relevant_artifacts(artifacts, benchmark_id)
    benchmark_jobs = relevant_jobs(jobs, benchmark_id)
    benchmark_datasets = relevant_datasets(datasets, benchmark_id)
    benchmark_runs = relevant_runs(runs, benchmark_datasets)
    benchmark_reports = relevant_reports(reports, benchmark_artifacts, benchmark_runs)
    benchmark_visualizations = relevant_visualizations(visualizations, benchmark_artifacts)
    benchmark_agent_tasks = build_agent_task_summary(db, benchmark_id, benchmark_artifacts)
    stages = benchmark_stages(
        source_card=source_card,
        local_status=local_status,
        datasets=benchmark_datasets,
        artifacts=benchmark_artifacts,
        jobs=benchmark_jobs,
        runs=benchmark_runs,
        agent_tasks=benchmark_agent_tasks,
    )
    return {
        "benchmark_id": benchmark_id,
        "name": str(benchmark.get("name")) if benchmark else benchmark_id,
        "source_kind": str(benchmark.get("source_kind")) if benchmark else "unknown",
        "source_url": str(benchmark.get("source_url")) if benchmark else None,
        "access": benchmark_access(benchmark) if benchmark else source_card["access"],
        "scenario_kind": (benchmark.get("scenario") or {}).get("kind") if benchmark else None,
        "modality_tags": list(benchmark.get("modality_tags", [])) if benchmark else [],
        "local_status": local_status,
        "source_card_summary": source_card_summary(source_card),
        "datasets": [dataset_ref(dataset) for dataset in benchmark_datasets],
        "artifacts": [artifact_ref(artifact) for artifact in benchmark_artifacts[:30]],
        "artifact_counts": count_by([artifact.asset_type for artifact in benchmark_artifacts]),
        "jobs": [job_ref(job) for job in benchmark_jobs[:20]],
        "job_counts": count_by([job.job_type for job in benchmark_jobs]),
        "runs": [run_ref(run) for run in benchmark_runs[:10]],
        "reports": [report_ref(report) for report in benchmark_reports[:10]],
        "visualizations": [visualization_ref(visualization) for visualization in benchmark_visualizations[:10]],
        "agent_tasks": benchmark_agent_tasks,
        "stages": stages,
        "overall_status": "ready" if all(stage["status"] == "ready" for stage in stages[:6]) else "needs_attention",
        "next_actions": entry_next_actions(stages, benchmark, source_card),
    }


def safe_raw_benchmark(benchmark_id: str) -> dict[str, Any] | None:
    try:
        return raw_benchmark_dataset(benchmark_id)
    except KeyError:
        return None


def relevant_artifacts(artifacts: list[Artifact], benchmark_id: str) -> list[Artifact]:
    contract_ids = {
        artifact.id
        for artifact in artifacts
        if artifact.asset_type == "agent_task_contract"
        and loads_json(artifact.metadata_json, {}).get("benchmark_id") == benchmark_id
    }
    selected: list[Artifact] = []
    for artifact in artifacts:
        metadata = loads_json(artifact.metadata_json, {})
        if metadata.get("benchmark_id") == benchmark_id:
            selected.append(artifact)
            continue
        if metadata.get("source_contract_artifact_id") in contract_ids:
            selected.append(artifact)
            continue
        if artifact.asset_type in BENCHMARK_ARTIFACT_TYPES and benchmark_id in artifact.name:
            selected.append(artifact)
    return selected


def relevant_jobs(jobs: list[Job], benchmark_id: str) -> list[Job]:
    selected = []
    for job in jobs:
        input_payload = loads_json(job.input_json, {})
        output_payload = loads_json(job.output_json, {})
        if input_payload.get("benchmark_id") == benchmark_id or output_payload.get("benchmark_id") == benchmark_id:
            selected.append(job)
        elif job.job_type in BENCHMARK_JOB_TYPES and benchmark_id in job.output_json:
            selected.append(job)
    return selected


def relevant_datasets(datasets: list[DatasetSnapshot], benchmark_id: str) -> list[DatasetSnapshot]:
    return [
        dataset
        for dataset in datasets
        if dataset.source_type == "benchmark_catalog"
        and dataset.source_ref is not None
        and dataset.source_ref.split(":", 1)[0] == benchmark_id
    ]


def relevant_runs(runs: list[ExperimentRun], datasets: list[DatasetSnapshot]) -> list[ExperimentRun]:
    dataset_ids = {dataset.id for dataset in datasets}
    return [run for run in runs if run.dataset_snapshot_id in dataset_ids]


def relevant_reports(
    reports: list[Report],
    artifacts: list[Artifact],
    runs: list[ExperimentRun],
) -> list[Report]:
    artifact_ids = {artifact.id for artifact in artifacts}
    run_ids = {run.id for run in runs}
    selected = []
    for report in reports:
        if report.artifact_id in artifact_ids:
            selected.append(report)
            continue
        sources = loads_json(report.source_asset_ids_json, [])
        if any(
            isinstance(source, dict)
            and source.get("asset_type") == "experiment_run"
            and source.get("asset_id") in run_ids
            for source in sources
        ):
            selected.append(report)
    return selected


def relevant_visualizations(visualizations: list[VisualizationSpec], artifacts: list[Artifact]) -> list[VisualizationSpec]:
    artifact_ids = {artifact.id for artifact in artifacts}
    return [
        visualization
        for visualization in visualizations
        if visualization.source_artifact_id in artifact_ids or visualization.artifact_id in artifact_ids
    ]


def build_agent_task_summary(
    db: Session,
    benchmark_id: str,
    artifacts: list[Artifact],
) -> dict[str, Any]:
    contract_ids = [
        artifact.id
        for artifact in artifacts
        if artifact.asset_type == "agent_task_contract"
        and loads_json(artifact.metadata_json, {}).get("benchmark_id") == benchmark_id
    ]
    readiness_reviews = [
        artifact for artifact in artifacts if artifact.asset_type == "agent_task_readiness_review"
    ]
    agent_results = [artifact for artifact in artifacts if artifact.asset_type == "agent_result"]
    readiness_statuses = [
        str(loads_json(artifact.metadata_json, {}).get("readiness_status") or "unknown")
        for artifact in readiness_reviews
    ]
    latest_evidence = []
    if agent_results:
        result_ids = [artifact.id for artifact in agent_results]
        latest_evidence = list(
            db.scalars(
                select(Evidence)
                .where(Evidence.source_artifact_id.in_(result_ids))
                .order_by(Evidence.created_at.desc())
            ).all()
        )
    return {
        "contract_count": len(contract_ids),
        "contract_artifact_ids": contract_ids[:8],
        "readiness_review_count": len(readiness_reviews),
        "readiness_statuses": readiness_statuses[:8],
        "agent_result_count": len(agent_results),
        "agent_result_artifact_ids": [artifact.id for artifact in agent_results[:8]],
        "evidence_ids": [evidence.id for evidence in latest_evidence[:8]],
    }


def benchmark_stages(
    *,
    source_card: dict[str, Any],
    local_status: dict[str, Any],
    datasets: list[DatasetSnapshot],
    artifacts: list[Artifact],
    jobs: list[Job],
    runs: list[ExperimentRun],
    agent_tasks: dict[str, Any],
) -> list[dict[str, Any]]:
    artifact_counts = count_by([artifact.asset_type for artifact in artifacts])
    successful_jobs = [job for job in jobs if job.status == "succeeded"]
    successful_workflows = [
        job for job in successful_jobs if job.job_type in {"run_public_benchmark_workflow", "run_benchmark_fixture_smoke"}
    ]
    return [
        stage("Source card", bool(source_card.get("source_url") or source_card.get("official_sources")), 1, "Catalog/source policy is recorded."),
        stage("Local files", bool(local_status.get("ready")), 1 if local_status.get("ready") else 0, "Required benchmark files are locally ready."),
        stage("Dataset import", bool(datasets), len(datasets), "Benchmark primary table has a DatasetSnapshot."),
        stage(
            "Relational catalog",
            artifact_counts.get("relational_catalog", 0) > 0,
            artifact_counts.get("relational_catalog", 0),
            "Table bundle profile and inferred join context are available.",
        ),
        stage(
            "Scenario pack",
            artifact_counts.get("benchmark_scenario_pack", 0) > 0,
            artifact_counts.get("benchmark_scenario_pack", 0),
            "Benchmark scenario and reporting expectations are materialized.",
        ),
        stage("Workflow result", bool(successful_workflows or runs), len(successful_workflows) + len(runs), "Smoke or public workflow results exist."),
        stage(
            "AgentTask handoff",
            int(agent_tasks["contract_count"]) > 0,
            int(agent_tasks["contract_count"]),
            "Planner-generated AgentTaskContract is available for flexible runner work.",
        ),
        stage(
            "Runner result",
            int(agent_tasks["agent_result_count"]) > 0,
            int(agent_tasks["agent_result_count"]),
            "AgentResult artifacts have been ingested from a controlled runner.",
        ),
    ]


def stage(name: str, ready: bool, count: int, detail: str) -> dict[str, Any]:
    return {
        "stage": name,
        "status": "ready" if ready else "needs_attention",
        "count": count,
        "detail": detail,
    }


def source_card_summary(source_card: dict[str, Any]) -> dict[str, Any]:
    raw_verification = source_card.get("source_verification")
    raw_access = source_card.get("access")
    raw_table_bundle = source_card.get("table_bundle")
    verification = raw_verification if isinstance(raw_verification, dict) else {}
    access = raw_access if isinstance(raw_access, dict) else {}
    table_bundle = raw_table_bundle if isinstance(raw_table_bundle, dict) else {}
    return {
        "verification_status": verification.get("status"),
        "verified_at": verification.get("verified_at"),
        "source_count": verification.get("source_count"),
        "access_kind": access.get("kind"),
        "requires_account": access.get("requires_account"),
        "supports_direct_download": access.get("supports_direct_download"),
        "agent_receives_credentials": access.get("agent_receives_credentials", False),
        "table_bundle_kind": table_bundle.get("kind"),
        "supporting_table_count": table_bundle.get("supporting_table_count"),
    }


def dataset_ref(dataset: DatasetSnapshot) -> dict[str, Any]:
    return {
        "dataset_snapshot_id": dataset.id,
        "artifact_id": dataset.artifact_id,
        "source_ref": dataset.source_ref,
        "row_count": dataset.row_count,
        "column_count": dataset.column_count,
        "schema_hash": dataset.schema_hash,
        "created_at": dataset.created_at.isoformat(),
    }


def artifact_ref(artifact: Artifact) -> dict[str, Any]:
    metadata = loads_json(artifact.metadata_json, {})
    return {
        "artifact_id": artifact.id,
        "asset_type": artifact.asset_type,
        "name": artifact.name,
        "version": artifact.version,
        "created_at": artifact.created_at.isoformat(),
        "metadata": {
            key: metadata.get(key)
            for key in [
                "benchmark_id",
                "dataset_snapshot_id",
                "evaluation_spec_id",
                "split_manifest_id",
                "experiment_run_id",
                "report_type",
                "scenario_kind",
                "table_count",
                "relationship_count",
                "readiness_status",
                "task_id",
            ]
            if key in metadata
        },
    }


def job_ref(job: Job) -> dict[str, Any]:
    output = loads_json(job.output_json, {})
    return {
        "job_id": job.id,
        "job_type": job.job_type,
        "status": job.status,
        "artifact_count": len(output.get("artifact_ids", [])) if isinstance(output.get("artifact_ids"), list) else 0,
        "created_at": job.created_at.isoformat(),
        "ended_at": job.ended_at.isoformat() if job.ended_at else None,
    }


def run_ref(run: ExperimentRun) -> dict[str, Any]:
    metrics = loads_json(run.metrics_json, {})
    return {
        "experiment_run_id": run.id,
        "runner_type": run.runner_type,
        "status": run.status,
        "dataset_snapshot_id": run.dataset_snapshot_id,
        "evaluation_spec_id": run.evaluation_spec_id,
        "split_manifest_id": run.split_manifest_id,
        "model_version_id": run.model_version_id,
        "primary_metric_name": metrics.get("primary_metric_name"),
        "primary_metric_value": metrics.get("primary_metric_value"),
    }


def report_ref(report: Report) -> dict[str, Any]:
    return {
        "report_id": report.id,
        "report_type": report.report_type,
        "title": report.title,
        "artifact_id": report.artifact_id,
        "status": report.status,
        "created_at": report.created_at.isoformat(),
    }


def visualization_ref(visualization: VisualizationSpec) -> dict[str, Any]:
    return {
        "visualization_id": visualization.id,
        "title": visualization.title,
        "chart_type": visualization.chart_type,
        "artifact_id": visualization.artifact_id,
        "source_artifact_id": visualization.source_artifact_id,
        "status": visualization.status,
    }


def count_by(values: list[str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in values:
        counts[value] = counts.get(value, 0) + 1
    return counts


def entry_next_actions(
    stages: list[dict[str, Any]],
    benchmark: dict[str, Any] | None,
    source_card: dict[str, Any],
) -> list[str]:
    actions: list[str] = []
    for stage_item in stages:
        if stage_item["status"] == "ready":
            continue
        name = str(stage_item["stage"])
        if name == "Local files":
            raw_access = source_card.get("access")
            access = raw_access if isinstance(raw_access, dict) else {}
            if access.get("requires_account"):
                actions.append("Download credentialed benchmark files outside Tablex, then import from HARNESS_DATA_DIR/benchmarks.")
            elif access.get("supports_direct_download"):
                actions.append("Run the credential-free public benchmark download or public workflow.")
            elif benchmark and benchmark.get("id"):
                actions.append("Generate a fixture or copy benchmark files under the configured benchmark data root.")
        elif name == "Dataset import":
            actions.append("Import the benchmark primary table to create a DatasetSnapshot.")
        elif name == "Relational catalog":
            actions.append("Import benchmark data so the table bundle and join hints are profiled.")
        elif name == "Scenario pack":
            actions.append("Generate a BenchmarkScenarioPack before runner handoff or reporting.")
        elif name == "Workflow result":
            actions.append("Run fixture smoke, public workflow, or a controlled experiment against the approved SplitManifest.")
        elif name == "AgentTask handoff":
            actions.append("Plan an AgentTaskContract so flexible feature/model choices are captured for a runner.")
        elif name == "Runner result":
            actions.append("Run the readiness-gated LocalStub or future controlled runner and ingest AgentResult artifacts.")
    return list(dict.fromkeys(actions))[:8]


def benchmark_pack_summary(entries: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "ready_benchmark_count": sum(1 for entry in entries if entry["overall_status"] == "ready"),
        "needs_attention_count": sum(1 for entry in entries if entry["overall_status"] != "ready"),
        "artifact_count": sum(len(entry["artifacts"]) for entry in entries),
        "job_count": sum(len(entry["jobs"]) for entry in entries),
        "run_count": sum(len(entry["runs"]) for entry in entries),
        "agent_task_contract_count": sum(int(entry["agent_tasks"]["contract_count"]) for entry in entries),
        "agent_result_count": sum(int(entry["agent_tasks"]["agent_result_count"]) for entry in entries),
    }


def benchmark_pack_next_actions(entries: list[dict[str, Any]]) -> list[str]:
    if not entries:
        return [
            "Run a benchmark fixture smoke, public workflow, or local benchmark import to populate benchmark evidence.",
            "Use Home Credit fixture smoke for multi-table product validation without storing external credentials.",
        ]
    actions: list[str] = []
    for entry in entries:
        for action in entry["next_actions"]:
            actions.append(f"{entry['benchmark_id']}: {action}")
    return actions[:10]


def build_benchmark_evidence_visualization(pack: dict[str, Any]) -> dict[str, Any]:
    rows = []
    for entry in pack["benchmarks"]:
        for stage_item in entry["stages"]:
            rows.append(
                {
                    "stage": f"{entry['benchmark_id']} / {stage_item['stage']}",
                    "status": stage_item["status"],
                    "count": stage_item["count"],
                    "detail": stage_item["detail"],
                }
            )
    return {
        "schema_version": "visualization_spec.v1",
        "title": "Benchmark Evidence Readiness",
        "chart_type": "stage_status",
        "data": rows,
        "encoding": {"stage": "stage", "status": "status", "count": "count", "detail": "detail"},
        "empty_state": "Run a benchmark fixture smoke, public workflow, or local import to populate benchmark evidence.",
    }


def render_benchmark_evidence_report(pack: dict[str, Any]) -> str:
    lines = [
        "# Benchmark Evidence Pack",
        "",
        f"Project: {pack['project']['name']} (`{pack['project']['id']}`)",
        f"Generated at: {pack['generated_at']}",
        "",
        "## Summary",
        "",
        f"- Benchmarks: {pack['benchmark_count']}",
        f"- Ready benchmarks: {pack['summary']['ready_benchmark_count']}",
        f"- Artifacts summarized: {pack['summary']['artifact_count']}",
        f"- Jobs summarized: {pack['summary']['job_count']}",
        f"- Experiment runs summarized: {pack['summary']['run_count']}",
        f"- AgentTaskContracts: {pack['summary']['agent_task_contract_count']}",
        f"- AgentResults: {pack['summary']['agent_result_count']}",
        "",
    ]
    if not pack["benchmarks"]:
        lines.extend(
            [
                "No benchmark evidence exists yet.",
                "",
                "Recommended starting points:",
                "- Run Home Credit fixture smoke for a multi-table credit-risk product smoke test.",
                "- Run a credential-free public benchmark workflow for a single-table end-to-end baseline check.",
            ]
        )
    for entry in pack["benchmarks"]:
        lines.extend(
            [
                f"## {entry['name']}",
                "",
                f"- Benchmark id: `{entry['benchmark_id']}`",
                f"- Source kind: {entry['source_kind']}",
                f"- Scenario: {entry.get('scenario_kind') or 'unspecified'}",
                f"- Overall status: {entry['overall_status']}",
                f"- DatasetSnapshots: {len(entry['datasets'])}",
                f"- Artifacts: {len(entry['artifacts'])}",
                f"- Jobs: {len(entry['jobs'])}",
                f"- Runs: {len(entry['runs'])}",
                f"- AgentTaskContracts: {entry['agent_tasks']['contract_count']}",
                f"- AgentResults: {entry['agent_tasks']['agent_result_count']}",
                "",
                "| Stage | Status | Count | Detail |",
                "| --- | --- | ---: | --- |",
            ]
        )
        for stage_item in entry["stages"]:
            lines.append(
                f"| {stage_item['stage']} | {stage_item['status']} | {stage_item['count']} | {stage_item['detail']} |"
            )
        if entry["next_actions"]:
            lines.extend(["", "Next actions:"])
            lines.extend(f"- {action}" for action in entry["next_actions"])
        lines.append("")
    if pack["next_actions"]:
        lines.extend(["## Cross-Benchmark Next Actions", ""])
        lines.extend(f"- {action}" for action in pack["next_actions"])
        lines.append("")
    lines.extend(
        [
            "## Policy",
            "",
            "- Benchmark credentials remain user-managed outside Tablex.",
            "- Agents do not receive connector credentials or Kaggle credentials.",
            "- This pack summarizes in-product artifacts and is not an external leaderboard claim.",
        ]
    )
    return "\n".join(lines)


def build_source_assets(entries: list[dict[str, Any]], pack_artifact: Artifact) -> list[dict[str, str]]:
    source_assets = [{"asset_type": "artifact", "asset_id": pack_artifact.id}]
    for entry in entries:
        for artifact in entry["artifacts"][:20]:
            source_assets.append({"asset_type": "artifact", "asset_id": str(artifact["artifact_id"])})
        for dataset in entry["datasets"][:5]:
            source_assets.append({"asset_type": "dataset_snapshot", "asset_id": str(dataset["dataset_snapshot_id"])})
        for run in entry["runs"][:5]:
            source_assets.append({"asset_type": "experiment_run", "asset_id": str(run["experiment_run_id"])})
    seen: set[tuple[str, str]] = set()
    unique = []
    for source in source_assets:
        key = (source["asset_type"], source["asset_id"])
        if key in seen:
            continue
        seen.add(key)
        unique.append(source)
    return unique[:80]


def create_benchmark_evidence_lineage(
    db: Session,
    *,
    project: Project,
    job: Job | None,
    pack_artifact: Artifact,
    report: Report,
    report_artifact: Artifact,
    evidence: Evidence,
    visualization: VisualizationSpec,
    entries: list[dict[str, Any]],
) -> None:
    if job is not None:
        for artifact in [pack_artifact, report_artifact]:
            create_lineage_edge(
                db,
                project_id=project.id,
                from_asset_type="job",
                from_asset_id=job.id,
                to_asset_type="artifact",
                to_asset_id=artifact.id,
                relation_type="produces",
            )
        create_lineage_edge(
            db,
            project_id=project.id,
            from_asset_type="job",
            from_asset_id=job.id,
            to_asset_type="visualization_spec",
            to_asset_id=visualization.id,
            relation_type="produces",
        )
    for entry in entries:
        for artifact in entry["artifacts"][:80]:
            create_lineage_edge(
                db,
                project_id=project.id,
                from_asset_type="artifact",
                from_asset_id=str(artifact["artifact_id"]),
                to_asset_type="artifact",
                to_asset_id=pack_artifact.id,
                relation_type="informs",
            )
    create_lineage_edge(
        db,
        project_id=project.id,
        from_asset_type="artifact",
        from_asset_id=pack_artifact.id,
        to_asset_type="report",
        to_asset_id=report.id,
        relation_type="summarized_by",
    )
    create_lineage_edge(
        db,
        project_id=project.id,
        from_asset_type="report",
        from_asset_id=report.id,
        to_asset_type="artifact",
        to_asset_id=report_artifact.id,
        relation_type="materializes",
    )
    create_lineage_edge(
        db,
        project_id=project.id,
        from_asset_type="artifact",
        from_asset_id=pack_artifact.id,
        to_asset_type="evidence",
        to_asset_id=evidence.id,
        relation_type="supports",
    )
