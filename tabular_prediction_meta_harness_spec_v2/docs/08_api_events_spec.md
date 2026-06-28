# 08. API、イベント、ジョブ仕様

## 1. API設計原則

- REST API first
- JSON request/response
- large filesはmultipart upload
- long running taskはJobとして扱う
- job statusはpollingとSSEに対応
- すべての変更操作はaudit logを残す
- project scopeを必ず検査する

## 2. API一覧

### 2.1 Auth

```text
POST /api/auth/login
POST /api/auth/logout
GET  /api/auth/me
GET  /api/auth/google/start
GET  /api/auth/google/callback
```

### 2.2 Projects

```text
GET    /api/projects
POST   /api/projects
GET    /api/projects/{project_id}
PATCH  /api/projects/{project_id}
POST   /api/projects/{project_id}/archive
GET    /api/projects/{project_id}/overview
```

### 2.3 Datasets

```text
POST /api/projects/{project_id}/datasets/upload
GET  /api/projects/{project_id}/datasets
GET  /api/datasets/{dataset_id}
GET  /api/datasets/{dataset_id}/schema
GET  /api/datasets/{dataset_id}/sample
POST /api/datasets/{dataset_id}/profile
```

### 2.4 Understanding

```text
POST /api/projects/{project_id}/understanding/run
GET  /api/projects/{project_id}/understanding/latest
GET  /api/projects/{project_id}/questions
POST /api/questions/{question_id}/answer
GET  /api/projects/{project_id}/assumptions
PATCH /api/projects/{project_id}/assumptions
POST /api/projects/{project_id}/assumptions/infer
POST /api/assumptions/{assumption_id}/confirm
POST /api/assumptions/{assumption_id}/reject
GET  /api/assumptions/{assumption_id}/evidence
POST /api/projects/{project_id}/evidence
```

### 2.5 Evaluation

```text
POST /api/projects/{project_id}/evaluation/design
POST /api/projects/{project_id}/evaluation/scenarios/design
GET  /api/projects/{project_id}/evaluation/candidates
POST /api/evaluation-candidates/{candidate_id}/promote
GET  /api/projects/{project_id}/evaluation/specs
GET  /api/evaluation-specs/{spec_id}
POST /api/evaluation-specs/{spec_id}/approve
POST /api/evaluation-specs/{spec_id}/generate-split
GET  /api/split-manifests/{split_id}
```

### 2.6 Baseline and Experiments

```text
POST /api/projects/{project_id}/baseline/run
GET  /api/projects/{project_id}/runs
GET  /api/runs/{run_id}
POST /api/runs/{run_id}/repair
GET  /api/projects/{project_id}/leaderboard
POST /api/projects/{project_id}/experiments/run
```

### 2.7 Ideas and Insights

```text
GET  /api/projects/{project_id}/insights
POST /api/projects/{project_id}/insights
GET  /api/projects/{project_id}/ideas
POST /api/projects/{project_id}/ideas
PATCH /api/ideas/{idea_id}
POST /api/ideas/{idea_id}/run
```

### 2.8 Artifacts and Lineage

```text
GET /api/projects/{project_id}/artifacts
GET /api/artifacts/{artifact_id}
GET /api/artifacts/{artifact_id}/download
GET /api/projects/{project_id}/lineage
```

### 2.9 Asset Library

```text
GET  /api/assets
POST /api/assets
GET  /api/assets/{asset_id}
POST /api/assets/{asset_id}/versions
POST /api/projects/{project_id}/asset-references
DELETE /api/asset-references/{reference_id}
```

### 2.10 Jobs

```text
GET  /api/jobs/{job_id}
POST /api/jobs/{job_id}/cancel
GET  /api/jobs/{job_id}/events
GET  /api/projects/{project_id}/jobs
```

### 2.11 Connectors

```text
GET  /api/connectors
POST /api/connectors
POST /api/connectors/{connector_id}/test
POST /api/connectors/{connector_id}/materialize-sample
```

### 2.12 Deployment and Monitoring

```text
POST /api/projects/{project_id}/deployments
POST /api/deployments/{deployment_id}/approve
POST /api/deployments/{deployment_id}/run
GET  /api/deployments/{deployment_id}/runs
POST /api/deployments/{deployment_id}/monitor
GET  /api/projects/{project_id}/monitoring
POST /api/projects/{project_id}/forward-validation/reconcile
GET  /api/projects/{project_id}/forward-validation
GET  /api/projects/{project_id}/reflection-events
```

## 3. Job Payloads

### 3.1 Data Understanding Job

```json
{
  "job_type": "run_data_understanding",
  "project_id": "p_001",
  "dataset_snapshot_id": "ds_001",
  "options": {
    "max_rows_profile": 100000,
    "generate_html_report": true,
    "generate_questions": true
  }
}
```

### 3.2 Evaluation Design Job

```json
{
  "job_type": "design_evaluation",
  "project_id": "p_001",
  "dataset_snapshot_id": "ds_001",
  "understanding_id": "u_001",
  "assumption_set_id": "as_001"
}
```


### 3.2.1 Assumption Inference Job

```json
{
  "job_type": "infer_assumptions",
  "project_id": "p_001",
  "dataset_snapshot_id": "ds_001",
  "understanding_id": "u_001",
  "question_set_id": "qs_001",
  "options": {
    "apply_unanswered_fallbacks": true,
    "autonomy_level": 2
  }
}
```

### 3.2.2 Evaluation Scenario Design Job

```json
{
  "job_type": "design_evaluation_scenarios",
  "project_id": "p_001",
  "dataset_snapshot_id": "ds_001",
  "assumption_set_id": "as_001",
  "options": {
    "include_reference_random_split": true,
    "max_candidates": 5
  }
}
```

### 3.3 Baseline Job

```json
{
  "job_type": "run_baseline",
  "project_id": "p_001",
  "dataset_snapshot_id": "ds_001",
  "evaluation_spec_id": "eval_001",
  "split_manifest_id": "split_001"
}
```

### 3.4 Agent Task Job

```json
{
  "job_type": "invoke_agent_task",
  "project_id": "p_001",
  "runner": "codex_cli",
  "task_contract_id": "task_001",
  "execution_policy": {
    "sandbox": "workspace_write",
    "network": "disabled",
    "timeout_seconds": 1800
  }
}
```


### 3.5 Forward Validation Reconciliation Job

```json
{
  "job_type": "reconcile_forward_validation",
  "project_id": "p_001",
  "prediction_set_id": "pred_001",
  "actuals_ingestion_id": "act_001",
  "model_version_id": "model_001",
  "evaluation_spec_id": "eval_001",
  "options": {
    "update_assumption_confidence": true,
    "create_reflection_events": true
  }
}
```

## 4. Events

### 4.1 Event envelope

```json
{
  "id": "evt_001",
  "type": "job.progress",
  "project_id": "p_001",
  "job_id": "job_001",
  "created_at": "2026-06-28T00:00:00Z",
  "payload": {}
}
```

### 4.2 Event types

```text
job.queued
job.started
job.progress
job.warning
job.needs_approval
job.succeeded
job.failed
artifact.created
lineage.created
question.created
question.answered
evaluation.created
evaluation.approved
run.metric_logged
run.succeeded
leaderboard.updated
agent.task_started
agent.patch_created
agent.output_validated
approval.requested
approval.approved
approval.rejected
assumption.inferred
```

## 5. Artifact Manifest

```json
{
  "artifact_id": "art_001",
  "asset_type": "baseline_report",
  "name": "baseline_report",
  "version": 1,
  "files": [
    {
      "path": "baseline_report.md",
      "sha256": "abc",
      "size_bytes": 1000
    }
  ],
  "metadata": {
    "project_id": "p_001",
    "run_id": "run_001"
  }
}
```

## 6. Error Response

```json
{
  "error": {
    "code": "EVALUATION_SPEC_NOT_APPROVED",
    "message": "Baseline cannot run before evaluation approval.",
    "details": {
      "project_id": "p_001"
    }
  }
}
```

## 7. Idempotency

POST APIは `Idempotency-Key` を受け付ける。job作成時は同一keyで重複jobを作らない。

## 8. API Versioning

初期は `/api` のみ。v1公開時に `/api/v1` へ固定する。

## 9. OpenAPI

FastAPIからOpenAPIを生成する。schemaはUIとAgent contractで再利用する。
