# 03. データモデル仕様

## 1. 設計原則

1. すべての成果物はArtifactとして登録する。
2. すべてのArtifactはcontent hashを持つ。
3. すべての実験runは、入力Artifact versionと出力Artifact versionを記録する。
4. 横断アセットはAssetVersionとして管理し、ProjectからAssetReferenceで参照する。
5. EvaluationSpecとSplitManifestはモデルより強い一級オブジェクトとして扱う。
6. ユーザー回答、仮定、承認履歴も再現性の一部として扱う。
7. 未回答事項はAssumptionとして保持し、confidence、risk、evidence、fallback policyを持たせる。
8. EvaluationSpecを固定する前に、EvaluationCandidateとEvaluationScenarioを保持する。

## 2. エンティティ一覧

### 2.1 Identity

- User
- Organization
- Team
- Membership
- Role
- Permission

### 2.2 Project

- Project
- ProjectMember
- ProjectSettings
- ProjectPhaseHistory

### 2.3 Data

- DataSource
- DatasetSnapshot
- DatasetColumn
- SemanticCatalog
- DataQualityFinding
- LeakageCandidate

### 2.4 Understanding

- UnderstandingReport
- QuestionSet
- Question
- Answer
- AssumptionSet
- Assumption
- Evidence
- AssumptionEvidenceLink

### 2.5 Evaluation

- EvaluationCandidate
- EvaluationScenario
- EvaluationSpec
- MetricSpec
- SplitManifest
- SplitSummary
- EvaluationApproval
- PushbackRecord

### 2.6 Experiment

- ExperimentRun
- RunMetric
- RunParameter
- FeatureSet
- FeatureRecipe
- ModelVersion
- PredictionSet
- ErrorAnalysis
- SliceMetric
- LeaderboardEntry

### 2.7 Knowledge

- Insight
- ImprovementIdea
- ResearchNote
- DecisionRecord

### 2.8 Cross-project Assets

- Asset
- AssetVersion
- AssetReference
- Skill
- PromptTemplate
- VisualizationTemplate
- EvaluationPattern
- DomainTaxonomy
- DataQualityRule

### 2.9 Operations

- Deployment
- BatchPredictionJob
- MonitoringRun
- DriftFinding
- ActualsIngestion
- ForwardValidationResult
- ReflectionEvent
- EvaluationReflection

### 2.10 Platform

- Artifact
- ArtifactFile
- LineageEdge
- Job
- ApprovalRequest
- AuditLog
- SecretReference
- Connector

## 3. 主要テーブル詳細

### 3.1 projects

```sql
CREATE TABLE projects (
  id TEXT PRIMARY KEY,
  org_id TEXT NOT NULL,
  name TEXT NOT NULL,
  description TEXT,
  task_type TEXT,
  target_column TEXT,
  current_phase TEXT NOT NULL,
  status TEXT NOT NULL,
  created_by TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
```

### 3.2 artifacts

```sql
CREATE TABLE artifacts (
  id TEXT PRIMARY KEY,
  org_id TEXT NOT NULL,
  project_id TEXT,
  asset_type TEXT NOT NULL,
  name TEXT NOT NULL,
  version INTEGER NOT NULL,
  uri TEXT NOT NULL,
  content_hash TEXT NOT NULL,
  size_bytes INTEGER,
  metadata_json TEXT NOT NULL,
  created_by TEXT,
  created_at TEXT NOT NULL,
  UNIQUE(project_id, asset_type, name, version)
);
```

### 3.3 dataset_snapshots

```sql
CREATE TABLE dataset_snapshots (
  id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL,
  artifact_id TEXT NOT NULL,
  source_type TEXT NOT NULL,
  source_ref TEXT,
  row_count INTEGER,
  column_count INTEGER,
  schema_hash TEXT NOT NULL,
  data_hash TEXT,
  parent_snapshot_id TEXT,
  created_at TEXT NOT NULL
);
```

### 3.4 semantic_catalog_columns

```sql
CREATE TABLE semantic_catalog_columns (
  id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL,
  dataset_snapshot_id TEXT NOT NULL,
  column_name TEXT NOT NULL,
  physical_type TEXT NOT NULL,
  semantic_type TEXT,
  role TEXT,
  available_at_prediction_time TEXT,
  pii_level TEXT NOT NULL DEFAULT 'unknown',
  is_leakage_suspect INTEGER NOT NULL DEFAULT 0,
  description TEXT,
  confidence REAL,
  evidence_json TEXT NOT NULL
);
```

`available_at_prediction_time` は `yes`, `no`, `unknown`, `conditional` のいずれか。

### 3.5 questions

```sql
CREATE TABLE questions (
  id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL,
  question_set_id TEXT NOT NULL,
  topic TEXT,
  question TEXT NOT NULL,
  why_it_matters TEXT NOT NULL,
  default_assumption TEXT,
  impact_if_wrong TEXT,
  choices_json TEXT NOT NULL,
  status TEXT NOT NULL,
  priority INTEGER NOT NULL,
  risk_level TEXT NOT NULL DEFAULT 'medium',
  value_of_answer TEXT NOT NULL DEFAULT 'medium',
  can_proceed_without_answer INTEGER NOT NULL DEFAULT 1,
  fallback_policy TEXT NOT NULL DEFAULT 'conservative_default',
  related_assumption_id TEXT,
  blocks_next_phase INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL
);
```

### 3.6 answers

```sql
CREATE TABLE answers (
  id TEXT PRIMARY KEY,
  question_id TEXT NOT NULL,
  answered_by TEXT NOT NULL,
  answer_value TEXT NOT NULL,
  answer_text TEXT,
  created_at TEXT NOT NULL
);
```


### 3.6.1 assumptions

```sql
CREATE TABLE assumptions (
  id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL,
  topic TEXT NOT NULL,
  subject_type TEXT,
  subject_ref TEXT,
  statement TEXT NOT NULL,
  status TEXT NOT NULL,
  confidence REAL NOT NULL,
  risk_level TEXT NOT NULL,
  fallback_policy TEXT NOT NULL,
  requires_user_confirmation INTEGER NOT NULL DEFAULT 0,
  created_by_type TEXT NOT NULL,
  created_by TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
```

`status` は `unknown`, `inferred`, `adopted`, `confirmed`, `challenged`, `revised`, `deprecated` のいずれか。

### 3.6.2 evidence

```sql
CREATE TABLE evidence (
  id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL,
  evidence_type TEXT NOT NULL,
  summary TEXT NOT NULL,
  strength TEXT NOT NULL,
  source_artifact_id TEXT,
  source_run_id TEXT,
  metadata_json TEXT NOT NULL,
  created_at TEXT NOT NULL
);
```

### 3.6.3 assumption_evidence_links

```sql
CREATE TABLE assumption_evidence_links (
  id TEXT PRIMARY KEY,
  assumption_id TEXT NOT NULL,
  evidence_id TEXT NOT NULL,
  effect TEXT NOT NULL,
  weight REAL NOT NULL,
  created_at TEXT NOT NULL,
  UNIQUE(assumption_id, evidence_id)
);
```

### 3.6.4 question_assumption_links

```sql
CREATE TABLE question_assumption_links (
  id TEXT PRIMARY KEY,
  question_id TEXT NOT NULL,
  assumption_id TEXT NOT NULL,
  relation_type TEXT NOT NULL,
  created_at TEXT NOT NULL
);
```

### 3.7 evaluation_candidates

```sql
CREATE TABLE evaluation_candidates (
  id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL,
  dataset_snapshot_id TEXT NOT NULL,
  name TEXT NOT NULL,
  scenario_id TEXT,
  split_type TEXT NOT NULL,
  primary_metric TEXT NOT NULL,
  secondary_metrics_json TEXT NOT NULL,
  time_column TEXT,
  group_column TEXT,
  stratify_column TEXT,
  excluded_columns_json TEXT NOT NULL,
  assumption_ids_json TEXT NOT NULL,
  rationale_md TEXT NOT NULL,
  confidence REAL NOT NULL,
  risk_level TEXT NOT NULL,
  status TEXT NOT NULL,
  created_by TEXT,
  created_at TEXT NOT NULL
);
```

### 3.7.1 evaluation_scenarios

```sql
CREATE TABLE evaluation_scenarios (
  id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL,
  name TEXT NOT NULL,
  purpose TEXT NOT NULL,
  primary_candidate_id TEXT,
  status TEXT NOT NULL,
  assumptions_json TEXT NOT NULL,
  comparison_summary_json TEXT NOT NULL,
  created_at TEXT NOT NULL
);
```

### 3.7.2 evaluation_specs

```sql
CREATE TABLE evaluation_specs (
  id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL,
  dataset_snapshot_id TEXT NOT NULL,
  source_evaluation_candidate_id TEXT,
  name TEXT NOT NULL,
  split_type TEXT NOT NULL,
  primary_metric TEXT NOT NULL,
  secondary_metrics_json TEXT NOT NULL,
  time_column TEXT,
  group_column TEXT,
  stratify_column TEXT,
  excluded_columns_json TEXT NOT NULL,
  assumption_ids_json TEXT NOT NULL DEFAULT '[]',
  rationale_md TEXT NOT NULL,
  risk_level TEXT NOT NULL,
  status TEXT NOT NULL,
  created_by TEXT,
  created_at TEXT NOT NULL
);
```

### 3.8 split_manifests

```sql
CREATE TABLE split_manifests (
  id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL,
  evaluation_spec_id TEXT NOT NULL,
  artifact_id TEXT NOT NULL,
  train_count INTEGER NOT NULL,
  valid_count INTEGER NOT NULL,
  test_count INTEGER,
  summary_json TEXT NOT NULL,
  created_at TEXT NOT NULL
);
```

### 3.9 experiment_runs

```sql
CREATE TABLE experiment_runs (
  id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL,
  idea_id TEXT,
  dataset_snapshot_id TEXT NOT NULL,
  evaluation_spec_id TEXT NOT NULL,
  evaluation_candidate_id TEXT,
  split_manifest_id TEXT NOT NULL,
  feature_set_id TEXT,
  model_version_id TEXT,
  runner_type TEXT NOT NULL,
  status TEXT NOT NULL,
  started_at TEXT,
  ended_at TEXT,
  params_json TEXT NOT NULL,
  metrics_json TEXT NOT NULL,
  summary_md TEXT,
  failure_reason TEXT,
  created_by TEXT
);
```

### 3.10 leaderboard_entries

```sql
CREATE TABLE leaderboard_entries (
  id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL,
  experiment_run_id TEXT NOT NULL,
  evaluation_candidate_id TEXT,
  model_version_id TEXT,
  primary_metric_name TEXT NOT NULL,
  primary_metric_value REAL NOT NULL,
  rank INTEGER,
  is_candidate INTEGER NOT NULL DEFAULT 0,
  decision_status TEXT NOT NULL,
  created_at TEXT NOT NULL
);
```

### 3.11 assets

```sql
CREATE TABLE assets (
  id TEXT PRIMARY KEY,
  org_id TEXT NOT NULL,
  asset_type TEXT NOT NULL,
  name TEXT NOT NULL,
  description TEXT,
  scope TEXT NOT NULL,
  owner_user_id TEXT,
  tags_json TEXT NOT NULL,
  semantic_tags_json TEXT NOT NULL,
  latest_version_id TEXT,
  visibility TEXT NOT NULL,
  status TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
```

### 3.12 asset_versions

```sql
CREATE TABLE asset_versions (
  id TEXT PRIMARY KEY,
  asset_id TEXT NOT NULL,
  version TEXT NOT NULL,
  artifact_id TEXT NOT NULL,
  digest TEXT NOT NULL,
  inputs_schema_json TEXT NOT NULL,
  outputs_schema_json TEXT NOT NULL,
  runtime_requirements_json TEXT NOT NULL,
  created_from_project_id TEXT,
  created_from_run_id TEXT,
  status TEXT NOT NULL,
  created_by TEXT,
  created_at TEXT NOT NULL
);
```

### 3.13 asset_references

```sql
CREATE TABLE asset_references (
  id TEXT PRIMARY KEY,
  source_type TEXT NOT NULL,
  source_id TEXT NOT NULL,
  target_asset_id TEXT NOT NULL,
  target_asset_version_id TEXT NOT NULL,
  relation_type TEXT NOT NULL,
  locked INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL
);
```

### 3.14 lineage_edges

```sql
CREATE TABLE lineage_edges (
  id TEXT PRIMARY KEY,
  org_id TEXT NOT NULL,
  project_id TEXT,
  from_asset_type TEXT NOT NULL,
  from_asset_id TEXT NOT NULL,
  to_asset_type TEXT NOT NULL,
  to_asset_id TEXT NOT NULL,
  relation_type TEXT NOT NULL,
  metadata_json TEXT NOT NULL,
  created_at TEXT NOT NULL
);
```


### 3.15 forward_validation_results

```sql
CREATE TABLE forward_validation_results (
  id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL,
  deployment_id TEXT,
  model_version_id TEXT NOT NULL,
  prediction_set_id TEXT NOT NULL,
  actuals_ingestion_id TEXT NOT NULL,
  evaluation_candidate_id TEXT,
  evaluation_spec_id TEXT,
  local_metrics_json TEXT NOT NULL,
  forward_metrics_json TEXT NOT NULL,
  metric_gap_json TEXT NOT NULL,
  rank_consistency REAL,
  slice_consistency_json TEXT NOT NULL,
  calibration_gap_json TEXT NOT NULL,
  conclusion TEXT NOT NULL,
  created_at TEXT NOT NULL
);
```

### 3.16 reflection_events

```sql
CREATE TABLE reflection_events (
  id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL,
  event_type TEXT NOT NULL,
  severity TEXT NOT NULL,
  summary TEXT NOT NULL,
  recommended_actions_json TEXT NOT NULL,
  affected_asset_refs_json TEXT NOT NULL,
  requires_approval INTEGER NOT NULL DEFAULT 0,
  status TEXT NOT NULL,
  created_at TEXT NOT NULL,
  resolved_at TEXT
);
```

## 4. Asset Type一覧

```text
dataset_snapshot
semantic_catalog
eda_profile
understanding_report
question_set
assumption_set
evidence_set
evaluation_candidate
evaluation_scenario
forward_validation_result
reflection_event
evaluation_spec
metric_spec
split_manifest
baseline_report
feature_set
feature_recipe
prompt_template
llm_feature_cache
insight_set
improvement_idea
experiment_bundle
model
prediction_output
monitoring_report
skill
visualization_template
report_template
domain_taxonomy
data_quality_rule
connector_template
```

## 5. Lineage relation type

```text
uses
produces
derived_from
evaluates_with
trained_on
predicts_with
generated_by
visualizes_with
promoted_from
supersedes
approved_by
deployed_as
monitored_by
reflects_on
supports_assumption
```

## 6. 状態定義

### 6.1 Asset status

```text
draft
active
deprecated
archived
blocked
```

### 6.2 Job status

```text
queued
claimed
running
needs_approval
succeeded
failed
cancelled
timed_out
```

### 6.3 Approval status

```text
pending
approved
rejected
expired
auto_approved
```

### 6.4 Experiment status

```text
created
running
succeeded
failed
invalidated
excluded_from_leaderboard
candidate
promoted
```


### 6.5 Assumption status

```text
unknown
inferred
adopted
confirmed
challenged
revised
deprecated
```

### 6.6 Evaluation candidate status

```text
candidate
primary_candidate
alternative
promoted_to_spec
rejected
deprecated
proposed_after_reflection
```

### 6.7 Reflection event status

```text
open
acknowledged
actioned
dismissed
resolved
```

## 7. Content hash

Artifactのcontent hashは、ファイル内容とmanifest metadataを対象にする。

```text
hash_input = sorted(file_hashes) + artifact_manifest_json
content_hash = sha256(hash_input)
```

## 8. 再現性要件

ExperimentRunは以下を必ず保持する。

- dataset_snapshot_id
- evaluation_spec_id
- split_manifest_id
- feature_set_id
- code commit
- runner_type
- Python package lock hash
- random seed
- params_json
- input asset references
- output artifacts
- metric values

## 9. 論理削除

projectやartifactは初期MVPでは物理削除しない。UI上はarchivedにする。v1でretention policyを追加する。

## 10. Migration方針

- Alembicでschema migrationする。
- Artifact manifestはJSON Schemaでversion管理する。
- 後方互換性がない変更ではmigration jobを提供する。
