# Architecture Decision Records

## ADR-001: Multi-Agent Architecture with LangGraph

**Decision:** Use a modular multi-agent architecture with LangGraph for workflow state management.

**Rationale:** Each agent has a single responsibility, making the system testable, maintainable, and extensible. LangGraph provides a stateful graph execution model with conditional edges that maps naturally to the approval-gated workflow.

**Alternatives considered:** Monolithic pipeline, Prefect/Dagster, plain asyncio

---

## ADR-002: Claude API for Rule Inference

**Decision:** Use `claude-sonnet-4-6` (default) with upgrade path to Opus for semantic inference and business rule generation.

**Rationale:** Claude's reasoning capabilities excel at inferring business semantics from column statistics and generating justified rule recommendations with chain-of-thought explanations. Sonnet provides the best cost/quality balance for production DQ workloads.

---

## ADR-003: BigQuery as State Store

**Decision:** Persist all workflow state, rules, audit logs, and results to BigQuery tables.

**Rationale:** BigQuery provides durable, queryable state that supports workflow resume, audit compliance, and BI reporting without additional infrastructure. The dq_workflow_state table enables session resume across restarts.

---

## ADR-004: Jinja2 + Claude SQL Generation Hybrid

**Decision:** Use Jinja2 templates as the primary SQL generation path with Claude as a fallback for complex rules.

**Rationale:** Template-based SQL is deterministic, testable, and fast. Claude fallback handles complex business rules that don't fit standard templates. This hybrid approach maximizes correctness while minimizing API costs.

---

## ADR-005: Two Human Approval Checkpoints

**Decision:** Enforce two mandatory approval gates — one before SQL generation, one before monitoring activation.

**Rationale:** Enterprise data governance requires human oversight at critical transitions. Checkpoint 1 ensures rule quality before automated execution. Checkpoint 2 ensures alert configurations are appropriate before they fire in production.

---

## ADR-006: Dataplex Graceful Fallback

**Decision:** Implement Dataplex as optional enhancement with automatic fallback to INFORMATION_SCHEMA.

**Rationale:** Not all GCP environments have Dataplex enabled. The platform must function fully with INFORMATION_SCHEMA alone. Dataplex adds enrichment (PII tags, lineage) but is never required.

---

## ADR-007: Async-First Design

**Decision:** All I/O operations (BigQuery, Claude API, Slack, email) are async with concurrent execution where independent.

**Rationale:** DQ rule execution across large tables is I/O-bound. Async parallel execution with a configurable semaphore (default: 10 concurrent queries) provides 5-10x throughput improvement over sequential execution.
