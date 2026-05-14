# Agentic Data Quality & Observability Platform

A production-grade, enterprise-ready **AI-powered Data Quality and Observability Platform** built with the Claude API, Google Cloud Platform, and modern data engineering tooling.

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────┐
│                     Orchestrator Agent                               │
│  Coordinates stages, manages state, enforces approval checkpoints   │
└─────────┬───────────────────────────────────────────────────────────┘
          │
    ┌─────┴──────────────────────────────────────────────────────┐
    │                Multi-Agent Pipeline                         │
    │                                                             │
    │  [1] Metadata Discovery Agent  →  INFORMATION_SCHEMA +     │
    │                                   Dataplex (fallback)       │
    │  [2] Technical Rule Engine     →  25+ standard DQ rules     │
    │  [3] Business Rule Agent       →  Claude-inferred rules     │
    │  [4] ✅ Human Approval Gate 1  →  Rule set approval         │
    │  [5] SQL Generation Agent      →  Jinja2 + Claude SQL       │
    │  [6] DAG Integration Agent     →  Airflow DAG generation    │
    │  [7] Monitoring Agent          →  SLA + anomaly detection   │
    │  [8] ✅ Human Approval Gate 2  →  Monitoring approval       │
    │  [9] Reporting Agent           →  5 BI-ready BQ views       │
    │  [10] Alerting Agent           →  Slack + Email routing     │
    └─────────────────────────────────────────────────────────────┘
          │
    ┌─────┴──────────────────────────────────────────────────────┐
    │              BigQuery Output Tables                          │
    │  dq_results | dq_workflow_state | dq_rule_config            │
    │  dq_audit_log | dq_execution_log | dq_monitoring_config     │
    └─────────────────────────────────────────────────────────────┘
```

---

## Quick Start

### Prerequisites

- Python 3.11+
- Google Cloud SDK with authentication
- Anthropic API key
- BigQuery dataset for DQ outputs

### Installation

```bash
# Clone the repository
git clone <repo-url>
cd agentic-data-quality-platform

# Create virtual environment
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate

# Install dependencies
pip install -e ".[dev]"

# Configure environment
cp .env.example .env
# Edit .env with your credentials
```

### Run the API Server

```bash
uvicorn api.main:app --reload --host 0.0.0.0 --port 8000
```

API documentation available at: http://localhost:8000/docs

### Docker

```bash
cd docker
docker-compose up --build
```

---

## End-to-End Workflow

### Step 1: Start Metadata Discovery

```bash
curl -X POST http://localhost:8000/api/v1/discovery/start \
  -H "X-API-Key: your-api-key" \
  -H "Content-Type: application/json" \
  -d '{
    "project_id": "my-gcp-project",
    "dataset_id": "my_dataset",
    "table_names": ["customers", "orders", "transactions"]
  }'
```

Response includes `session_id` — save this for all subsequent calls.

### Step 2: Generate DQ Rules

```bash
curl -X POST http://localhost:8000/api/v1/rules/generate \
  -H "X-API-Key: your-api-key" \
  -H "Content-Type: application/json" \
  -d '{"session_id": "<session_id>", "include_technical": true, "include_business": true}'
```

### Step 3: Review Generated Rules

```bash
curl http://localhost:8000/api/v1/rules/<session_id> \
  -H "X-API-Key: your-api-key"
```

### Step 4: Approve Rule Set (Checkpoint 1)

```bash
curl -X POST http://localhost:8000/api/v1/approvals/submit \
  -H "X-API-Key: your-api-key" \
  -H "Content-Type: application/json" \
  -d '{
    "session_id": "<session_id>",
    "stage": "approval_1",
    "status": "APPROVED",
    "approver_id": "data-steward@company.com",
    "comments": "Reviewed and approved all 42 rules"
  }'
```

### Step 5: Generate and Execute DQ SQL

```bash
# Generate SQL
curl -X POST http://localhost:8000/api/v1/sql/generate \
  -H "X-API-Key: your-api-key" \
  -d '{"session_id": "<session_id>"}'

# Execute
curl -X POST http://localhost:8000/api/v1/sql/execute \
  -H "X-API-Key: your-api-key" \
  -d '{"session_id": "<session_id>"}'
```

### Step 6: View Results

```bash
# Executive KPI
curl http://localhost:8000/api/v1/reporting/kpi -H "X-API-Key: your-api-key"

# Table health scores
curl http://localhost:8000/api/v1/reporting/health -H "X-API-Key: your-api-key"

# Trend analysis
curl "http://localhost:8000/api/v1/reporting/trends?days=30" -H "X-API-Key: your-api-key"
```

---

## Repository Structure

```
agentic-data-quality-platform/
├── agents/                    # 11 specialized AI agents
│   ├── orchestrator/          # Workflow coordination
│   ├── metadata_agent/        # INFORMATION_SCHEMA discovery
│   ├── technical_dq_agent/    # Standard DQ rule generation
│   ├── business_dq_agent/     # Claude-inferred business rules
│   ├── sql_generation_agent/  # BigQuery SQL generation
│   ├── validation_agent/      # DQ SQL execution engine
│   ├── monitoring_agent/      # SLA and anomaly detection
│   ├── reporting_agent/       # BI reporting views
│   ├── alerting_agent/        # Slack/email alert routing
│   └── approval_agent/        # Human-in-the-loop checkpoints
│
├── tools/                     # Reusable tool integrations
│   ├── bigquery/              # BQ client, schema discovery, execution
│   ├── dataplex/              # Catalog, lineage, INFORMATION_SCHEMA fallback
│   ├── sql_tools/             # Jinja2 SQL builder and validator
│   ├── airflow/               # DAG generation and Composer client
│   └── alerts/                # Slack and email connectors
│
├── prompts/                   # Versioned LLM prompt templates
├── sql_templates/             # Jinja2 DQ SQL templates (9 rule types)
├── dq_rules/                  # Rule library (25+ rules) and schemas
├── schemas/                   # Pydantic v2 models and BigQuery schemas
├── configs/                   # Pydantic-settings configuration
├── workflows/                 # LangGraph workflow definitions
├── api/                       # FastAPI REST application
│   ├── routers/               # 6 router modules
│   └── middleware/            # API key authentication
├── tests/
│   ├── unit/                  # 4 test modules, >80% coverage target
│   └── integration/           # API integration tests
├── infra/
│   ├── terraform/             # GCP infrastructure as code
│   └── cloud_build/           # CI/CD pipeline
├── docker/
│   ├── Dockerfile
│   └── docker-compose.yml
└── docs/                      # Architecture decision records
```

---

## Configuration

| Variable | Description | Required |
|---|---|---|
| `ANTHROPIC_API_KEY` | Anthropic/Claude API key | Yes |
| `GCP_PROJECT_ID` | GCP project ID | Yes |
| `GCP_DATASET_ID` | Source BigQuery dataset | Yes |
| `BQ_DQ_DATASET` | DQ output dataset (default: `dq_observability`) | No |
| `GOOGLE_APPLICATION_CREDENTIALS` | Path to GCP service account JSON | Yes |
| `SLACK_WEBHOOK_URL` | Slack webhook for alerts | No |
| `SENDGRID_API_KEY` | SendGrid API key for email alerts | No |
| `API_KEY` | API authentication key | Yes |
| `DATAPLEX_ENABLED` | Enable Dataplex integration (default: false) | No |

---

## DQ Rule Categories

| Category | Rules | SQL Template |
|---|---|---|
| Completeness | Not null, sparse field, low null rate | `completeness_check.sql.j2` |
| Uniqueness | PK uniqueness, composite key, email unique | `uniqueness_check.sql.j2` |
| Validity | Email regex, phone format, status enum, range | `validity_regex_check.sql.j2`, `enum_values_check.sql.j2`, `range_check.sql.j2` |
| Freshness | Daily/hourly SLA, late arrival | `freshness_check.sql.j2` |
| Volume | Min row count, volume anomaly | `volume_check.sql.j2` |
| Schema Drift | Column add/remove, type change | `schema_drift_check.sql.j2` |
| Integrity | FK referential integrity | `referential_integrity_check.sql.j2` |
| Consistency | Date ordering, country codes | Combined templates |

---

## BI Reporting Views

| View | Description |
|---|---|
| `v_dq_executive_kpi` | Overall pass rate, health score, critical failures |
| `v_dq_table_health` | Per-table health score, last run time, open failures |
| `v_dq_trend_analysis` | Daily/weekly pass/fail trends per rule type (30 days) |
| `v_dq_freshness_report` | Freshness lag per table vs. SLA target |
| `v_dq_failed_rules` | All active failures with severity and time-to-resolve |

All views are directly compatible with **Looker, Looker Studio, Power BI, and Tableau**.

---

## Infrastructure

### Provision with Terraform

```bash
cd infra/terraform
terraform init
terraform plan -var="project_id=my-gcp-project"
terraform apply -var="project_id=my-gcp-project"
```

### CI/CD via Cloud Build

Triggers on push to main branch:
1. **Lint** — ruff code quality checks
2. **Unit Tests** — pytest with 80% coverage enforcement
3. **Build** — Docker image build
4. **Security Scan** — Trivy critical vulnerability check
5. **Deploy** — Cloud Run deployment

---

## Running Tests

```bash
# Unit tests only
pytest tests/unit/ -v

# With coverage report
pytest tests/unit/ --cov=. --cov-report=html

# Integration tests (requires GCP credentials)
pytest tests/integration/ -m integration -v
```

---

## Technology Stack

| Component | Technology |
|---|---|
| LLM / Reasoning | Claude API (`claude-sonnet-4-6`) |
| Orchestration | LangGraph |
| Data Warehouse | BigQuery |
| Data Catalog | Dataplex |
| Workflow Scheduling | Airflow / Cloud Composer |
| API | FastAPI + Pydantic v2 |
| SQL Templating | Jinja2 |
| Alerting | Slack SDK + SendGrid |
| Observability | OpenTelemetry + structlog |
| Infrastructure | Terraform + Cloud Build |
| Container | Docker + Cloud Run |
| Testing | pytest + pytest-asyncio |
