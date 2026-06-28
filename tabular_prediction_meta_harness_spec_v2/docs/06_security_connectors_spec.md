# 06. セキュリティとコネクター仕様

## 1. セキュリティ原則

1. Agentにsecretを渡さない。
2. Agentに本番DBへの直接接続を許可しない。
3. 外部データアクセスはData Access Brokerを経由する。
4. 本番書き込みはapproval必須にする。
5. workspace外のファイルアクセスを制限する。
6. PIIはmask、redact、blockのいずれかを選べるようにする。
7. すべてのdata accessとproduction writeをaudit logに残す。
8. EvaluationSpecやSplitManifestを勝手に変更できないようにする。

## 2. Auth

### 2.1 v0.1

local auth:

- email/password
- local admin
- session cookie
- CSRF protection

### 2.2 v1.0

Google OIDC login:

- authorization code flow
- server side token exchange
- ID token validation
- domain allowlist
- organization mapping
- optional email domain policy

GoogleのOAuth 2.0 APIは認証と認可に使え、OpenID Connect実装はOpenID Certifiedである。Web server application flowではclient secretを安全に保持できるサーバー側アプリを想定する。

## 3. RBAC

Role:

| Role | 権限 |
|---|---|
| owner | 全操作 |
| admin | メンバー、connector、secret管理 |
| editor | dataset、EDA、実験、モデル |
| reviewer | evaluation、deployment承認 |
| viewer | 閲覧 |
| service_account | job実行 |

Permission:

- project.read
- project.write
- dataset.upload
- dataset.read
- evaluation.create
- evaluation.approve
- experiment.run
- model.promote
- deployment.create
- deployment.approve
- connector.create
- connector.read
- connector.use
- secret.manage
- audit.read
- asset.publish
- asset.use

## 4. Data Access Broker

### 4.1 概要

```text
Agent or Worker
  -> Data Access Broker API
  -> Policy Engine
  -> Connector
  -> External Data Source
```

### 4.2 機能

- connector credentialをsecret storeから取得
- callerのRBACを検査
- project policyを検査
- SQLをparseし、危険操作を拒否
- row limitを適用
- column maskingを適用
- data sampleをmaterialize
- audit logを書く

### 4.3 SQL Policy

初期はread-only。

許可:

- SELECT
- WITH
- LIMIT
- simple aggregation

拒否:

- INSERT
- UPDATE
- DELETE
- DROP
- ALTER
- TRUNCATE
- COPY TO arbitrary path
- external function
- network function

### 4.4 Sample Materialization

AgentにはDB接続を渡さず、sample fileを渡す。

```text
broker.materialize_sample(dataset_source_id, columns, filters, max_rows)
  -> /data/workspaces/{project}/data/sample.parquet
```

### 4.5 Masking

PII policy:

| level | 処理 |
|---|---|
| none | そのまま |
| low | project policyに従う |
| medium | hashまたは部分mask |
| high | redact |
| restricted | Agent利用禁止 |

## 5. Secret Management

v0.1:

- local encrypted file
- master key via environment variable

v1:

- cloud secret manager
- HashiCorp Vault optional
- KMS envelope encryption

SecretReferenceだけDBに保存し、secret本体はMetadata DBに保存しない。

## 6. Connectors

### 6.1 v0.1

- file upload
- local directory
- DuckDB file

### 6.2 v0.4

- PostgreSQL read-only
- S3 compatible read
- S3 compatible write with approval

### 6.3 v1

- BigQuery
- Snowflake
- Google Sheets
- GCS
- Azure Blob

## 7. Connector定義

```yaml
connector_id:
name:
type:
auth_type:
secret_ref:
allowed_projects:
read_policy:
write_policy:
masking_policy:
created_by:
created_at:
```

## 8. Production Write Approval

本番書き込み前に表示する。

- destination
- schema
- row count
- sample rows
- overwrite or append
- rollback plan
- model version
- input dataset snapshot
- output hash

承認後に一度だけ使えるwrite tokenを発行する。

## 9. Audit Log

必須項目:

```yaml
audit_id:
actor_type:
actor_id:
action:
resource_type:
resource_id:
project_id:
ip_address:
user_agent:
status:
metadata:
created_at:
```

audit対象:

- login
- dataset upload
- connector test
- sample materialization
- secret access by broker
- job started
- artifact registered
- evaluation approved
- deployment approved
- production write
- asset published
- permission changed

## 10. Agent Sandbox

### 10.1 初期

- workspace-write
- network disabled
- no direct secret env
- separate temp HOME
- max runtime
- max output file size
- max artifact count

### 10.2 将来

- sandbox-runner container
- seccomp
- read-only root filesystem
- resource limits
- egress proxy
- MCP tool approval

## 11. ネットワーク

原則:

- Agentの直接外部ネットワークは禁止
- 外部検索はハーネスのSearch Tool経由
- package installはsetup phaseまたは承認制
- production connectorはBroker経由

## 12. Compliance Checklist

v1までに満たす。

- secret never logged
- PII masking
- audit retention
- role based access
- asset visibility
- project export
- project deletion request
- connector least privilege
- production approval
- dependency vulnerability scan

## 13. Threat Model

### 13.1 Agent Prompt Injection

リスク:

- データ内テキストがAgentに命令する
- レポート生成時にsecret読み取りを誘導する

対策:

- data is data policy
- AGENTS.mdに明記
- Tool call policy
- schema validation
- forbidden action check

### 13.2 Leakage through Logs

対策:

- PII redaction before log
- stdout size cap
- secret pattern scanner
- raw logs access restricted

### 13.3 Connector Misuse

対策:

- read-only first
- SQL AST inspection
- row limits
- write approval
- audit

### 13.4 Evaluation Tampering

対策:

- EvaluationSpecは承認後immutable
- 新version作成のみ許可
- runはspec versionを固定
- lineage記録
