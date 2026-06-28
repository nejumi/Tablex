# 05. AgentとCodex統合仕様

## 1. 基本方針

Codexは、ハーネスの中核ではなく、制御されたworkspaceでコード作成、コード修正、実験実装、レポート生成を担当する実行エンジンである。

ハーネスが保持するもの:

- project state
- auth
- RBAC
- metadata
- artifacts
- lineage
- evaluation spec
- approval
- data access policy
- connector secret
- UI state

Codexが担当するもの:

- EDA補助コード生成
- feature recipe実装
- baseline script修正
- experiment script実装
- failed run repair
- report draft生成
- test生成
- code review補助

## 2. Codex統合方式

### 2.1 v0.2: Codex CLI Runner

`codex exec` をsubprocessで呼ぶ。

```text
Harness Worker
  -> prepare workspace
  -> write task_contract.json
  -> write output_schema.json
  -> run codex exec
  -> collect outputs/result.json
  -> validate schema
  -> register artifacts
```

### 2.2 v0.4: Codex App ServerまたはSDK Runner

Codex app-serverはJSON-RPC風のmessage schemaでthreadとturnを扱い、CLIからschema生成もできる。長いセッションやUIへの進捗反映が必要になった時点で採用する。

### 2.3 v0.5: Codex MCP Runner

CodexをMCP serverまたはMCP client連携で使い、ハーネスのMCP toolsを提供する。

### 2.4 fork方針

初期はforkしない。CLIまたはapp-server境界で利用する。以下が必要になった時だけforkを検討する。

- 内部イベントをUIに細かく流したい
- 独自sandboxを深く統合したい
- agent memoryを独自化したい
- provider差し替えが必要
- Codex prompt policyを完全制御したい

## 3. AgentRunner Interface

```python
from pydantic import BaseModel
from typing import Any, Literal

class WorkspaceRef(BaseModel):
    project_id: str
    path: str
    git_commit: str | None = None

class ExecutionPolicy(BaseModel):
    sandbox: Literal["read_only", "workspace_write", "full_access"]
    network: Literal["disabled", "harness_only", "restricted", "full"]
    timeout_seconds: int
    max_retries: int
    allow_secret_access: bool = False
    require_approval_for_external_network: bool = True
    require_approval_for_production_write: bool = True

class AgentTaskContract(BaseModel):
    task_id: str
    task_type: str
    project_id: str
    objective: str
    inputs: dict[str, Any]
    required_outputs: list[dict[str, Any]]
    quality_checks: list[str]
    forbidden_actions: list[str]
    context_files: list[str]
    output_schema_path: str

class AgentResult(BaseModel):
    task_id: str
    status: Literal["succeeded", "failed", "needs_approval"]
    final_message: str
    outputs: dict[str, Any]
    artifacts: list[dict[str, Any]]
    warnings: list[str]
    failure_reason: str | None = None
    patch_summary: str | None = None
    raw_log_path: str | None = None
```

## 4. Task Contract

Agentに自然文だけを投げない。必ずcontract化する。

```yaml
task_id: task_exp_001
task_type: implement_feature_idea
objective: idea_023を実装し、指定splitで評価する
inputs:
  project_context: .harness/project_context.json
  evaluation_spec: data/evaluation_spec.yaml
  split_manifest: data/split_manifest.parquet
  idea: data/idea_023.yaml
required_outputs:
  - path: outputs/result.json
    schema: task_contracts/experiment_result.schema.json
  - path: reports/experiment_report.md
quality_checks:
  - split_manifestを必ず使う
  - evaluation_specを変更しない
  - target encodingはOOFで行う
forbidden_actions:
  - connector secretを読む
  - validation/test targetをpromptに入れる
  - production outputへ書く
```

## 5. Workspace Template

```text
project_workspace/
  AGENTS.md
  harness.yaml
  .codex/config.toml
  task_contracts/
  data/
  src/
  outputs/
  reports/
  artifacts/
  tests/
  .harness/
```

## 6. AGENTS.md要件

必須記載:

- Project context
- Never rules
- Always rules
- Data leakage rules
- Artifact output rules
- Testing rules
- Evaluation rules
- Security rules

## 7. Codex設定

初期の推奨:

```toml
approval_policy = "on-request"
sandbox_mode = "workspace-write"

[features]
web_search = false
```

non-interactiveでは、ハーネス側が外部sandboxを強くしたうえで `approval_policy = "never"` を使う選択肢もある。ただし初期は `on-request` を維持し、approval要求はハーネス側jobに変換する。

## 8. セキュリティ境界

Codexに渡してよいもの:

- sample data
- schema
- profile
- semantic catalog
- split manifest
- evaluation spec
- code
- sanitized logs

Codexに渡してはいけないもの:

- DB password
- OAuth refresh token
- connector secret
- unmasked PII
- production write credential
- user Codex auth token
- full production data unless approved

## 9. Harness MCP Server

将来、Codexからハーネスの安全なtoolsを呼べるようにする。

tools:

- `get_project_context`
- `search_assets`
- `read_asset_version`
- `get_dataset_schema`
- `get_dataset_sample`
- `get_evaluation_spec`
- `get_split_manifest`
- `write_artifact`
- `register_experiment_result`
- `run_standard_evaluation`
- `request_approval`

## 10. Agent Friendly CLI

MCPと並行して `harnessctl` を提供する。

```bash
harnessctl project context --project-id p_123 --json
harnessctl dataset schema --dataset-id ds_456 --json
harnessctl artifacts register outputs/result.json --type experiment_result
harnessctl evaluation run --experiment-dir .
```

AgentはこのCLIを使う。CLIは標準出力でJSONを返し、secretは返さない。

## 11. Agent出力検証

すべてのAgent taskは以下を通す。

1. file existence check
2. JSON Schema validation
3. forbidden path check
4. artifact manifest check
5. metric sanity check
6. lineage completeness check
7. security policy check
8. optional deterministic re-run

## 12. 失敗修正ループ

Codex taskが失敗した場合:

```text
failure captured
  -> summarize failure
  -> create repair task
  -> pass traceback and relevant files
  -> run repair
  -> run tests
  -> validate outputs
```

最大2回まで自動repairする。以降はhuman review。

## 13. Agent Task種別

- `draft_data_understanding`
- `generate_eda_code`
- `repair_eda_code`
- `draft_evaluation_rationale`
- `implement_baseline`
- `repair_failed_run`
- `implement_feature_idea`
- `generate_experiment_report`
- `review_leakage_risk`
- `generate_visualization`
- `promote_skill_candidate`
- `draft_monitoring_report`

## 14. Codex利用上の前提

Codex CLIはローカルで動くcoding agentとして利用でき、CLI flagでsandboxやapproval policyを制御できる。Codexのsandboxはspawned commandsにも適用され、sandboxとapprovalは異なるが連携する制御として扱われる。ハーネスではCodexの制御に加えて、Data Access Brokerとworkspace隔離を必須とする。

## 15. 実装メモ

### 15.1 CodexCliRunner疑似コード

```python
def run_task(workspace, contract, schema, policy):
    write_json(workspace / ".harness/task_contract.json", contract)
    write_json(workspace / ".harness/output_schema.json", schema)

    prompt = render_prompt(contract)
    cmd = [
        "codex", "exec",
        "--cd", workspace.path,
        "--sandbox", "workspace-write",
        "--output-schema", str(workspace / ".harness/output_schema.json"),
        "--skip-git-repo-check",
        "-"
    ]

    result = subprocess.run(
        cmd,
        input=prompt,
        text=True,
        capture_output=True,
        timeout=policy.timeout_seconds,
        env=safe_env(),
    )

    return validate_and_import(result)
```

### 15.2 safe_env

- OPENAI_API_KEYは実行モードによって渡す。
- DB secretsは渡さない。
- HTTP_PROXYはData Access Broker経由に限定する場合のみ渡す。
- HOMEはworkspace専用の一時HOMEにする。
- CODEX_HOMEはworkspace外の専用隔離領域にする。


## 12. Assumption-aware Agent Tasks

Codex Runnerへ渡すtask contractには、必要に応じて以下を含める。

```json
{
  "assumption_context": {
    "active_assumptions_path": "data/assumptions.yaml",
    "evidence_path": "data/evidence.json",
    "unanswered_questions_path": "data/unanswered_questions.json",
    "fallback_policy_path": "data/fallback_policies.json"
  }
}
```

CodexはAssumptionを勝手にconfirmedへ変更してはならない。疑義がある場合は `outputs/result.json` の `proposed_assumption_updates` と `warnings` に返す。

禁止:

- high-risk Assumptionを無視して特徴量を使う
- 予測時点可用性がunknownの列をprimary featureへ入れる
- EvaluationSpecを直接変更する

許可:

- 新しいEvidence候補を提案する
- 追加質問を提案する
- alternative scenarioの必要性を提案する
- leakage suspectをwarningとして返す
