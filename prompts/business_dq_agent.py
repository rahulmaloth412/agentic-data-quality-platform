"""Versioned prompt templates for the Business Rule Recommendation Agent."""

BUSINESS_RULE_SYSTEM_PROMPT_V1 = """You are a Senior Data Quality Engineer with expertise in enterprise data governance, regulatory compliance, and business rule formulation.

Your responsibilities:
1. Analyze table metadata, column profiles, and semantic inferences to generate intelligent business DQ rules
2. Use chain-of-thought reasoning to justify every rule recommendation
3. Assign appropriate severity levels based on business impact
4. Generate executable BigQuery SQL for each rule
5. Recommend anomaly detection strategies for numerical and temporal columns

Produce structured, machine-parseable JSON output. Every rule must have a clear business justification.
Rules must be:
- Actionable: executable SQL that writes to the dq_results table
- Proportional: severity matches actual business risk
- Specific: tied to a concrete column or relationship
- Measurable: threshold defined in quantitative terms
"""

RULE_INFERENCE_PROMPT_V1 = """Based on the following table metadata, column profiles, and semantic inferences, generate business DQ rules.

Table: `{project_id}.{dataset_id}.{table_name}`

Table Metadata:
{metadata_json}

Column Profiles:
{profiles_json}

Semantic Inferences:
{semantics_json}

Generate a comprehensive list of business DQ rules. For each rule, provide:

{{
  "rules": [
    {{
      "rule_id": "<unique_id like BRUL_001>",
      "rule_name": "<descriptive name>",
      "rule_category": "<completeness|uniqueness|validity|integrity|freshness|volume|schema_drift|consistency>",
      "description": "<clear description of what is being validated>",
      "rationale": "<chain-of-thought explaining why this rule matters for this specific table/column>",
      "column_name": "<column or null for table-level rules>",
      "severity": "<INFO|WARN|FAIL>",
      "threshold": <0.0-1.0 for rate-based rules>,
      "execution_frequency": "<hourly|daily|weekly>",
      "sql_template": "<template_name.sql.j2 or null>",
      "parameters": {{
        "<param_key>": "<param_value>"
      }},
      "anomaly_strategy": "<statistical|threshold|percentile|zscore|null for non-numeric>"
    }}
  ]
}}

Apply these domain rules:
- email columns → RFC 5322 regex validation (WARN severity)
- status/flag columns → enum allowed-values check (FAIL severity)
- amount/revenue/price columns → range check min=0 (FAIL), outlier z-score detection (WARN)
- date columns → future date constraint, past boundary check (WARN)
- id columns → uniqueness check (FAIL), not-null check (FAIL)
- country/state columns → reference lookup suggestion (INFO)
- phone columns → format regex (WARN), PII flag
- high null_rate columns → completeness alert only if not_null business requirement
- timestamp columns → freshness check with 24h default SLA
"""

SEVERITY_CLASSIFICATION_PROMPT_V1 = """Classify the appropriate severity for the following DQ rule.

Rule Description: {rule_description}
Column: {column_name}
Business Context: {business_context}
Table: {table_name}

Available severities:
- FAIL: Critical business rule. Data consumers cannot trust this data if it fails. Pipeline should halt.
- WARN: Important quality signal. Data may be used but the issue should be investigated.
- INFO: Informational metric. Useful for trending but not blocking.

Respond with JSON:
{{
  "severity": "<FAIL|WARN|INFO>",
  "justification": "<one sentence explaining why>",
  "escalation_recommended": <true|false>
}}
"""

ANOMALY_STRATEGY_PROMPT_V1 = """Recommend an anomaly detection strategy for the following column.

Column: {column_name}
Data Type: {data_type}
Business Type: {business_type}
Statistics:
- Min: {min_value}
- Max: {max_value}
- Average: {avg_value}
- Null Rate: {null_rate}
- Distinct Count: {distinct_count}
- Sample Values: {sample_values}

Available strategies:
- zscore: Flag values > N standard deviations from mean (numeric columns)
- iqr: Interquartile range outlier detection (numeric with skew)
- percentile: Flag values outside P5-P95 range
- threshold: Simple min/max bounds
- statistical: Moving average comparison for time-series
- none: No anomaly detection needed

Respond with JSON:
{{
  "strategy": "<strategy_name>",
  "parameters": {{
    "threshold": <numeric value if applicable>
  }},
  "rationale": "<brief explanation>"
}}
"""
