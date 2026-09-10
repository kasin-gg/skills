---
name: bigquery-slot-cost-optimizer
description: >-
  Analyzes Google Cloud BigQuery slot consumption, compute costs, and execution
  bottlenecks using INFORMATION_SCHEMA. Detects slot contention, unpartitioned
  table scans, and Cartesian join explosions, providing concrete SQL rewrite
  and architecture optimization recommendations.
license: Apache-2.0
metadata:
  version: 1.0.0
  publisher: google
  category: BigDataAndAnalytics
  tags:
    - bigquery
    - performance
    - cost-optimization
    - slot-analysis
    - sql
---

# BigQuery Slot & Cost Optimizer Agent Skill

This skill equips AI agents and cloud engineers with procedural heuristics to analyze BigQuery resource consumption, compute slot-hours, identify slot starvation, eliminate Cartesian join explosions, and resolve unpartitioned table scans.

## 1. Trigger Conditions & Intent Mapping

Activate this skill whenever the user asks to:
- "Optimize BigQuery query performance or reduce slot usage"
- "Find the most expensive queries in BigQuery"
- "Diagnose BigQuery slot contention or queueing"
- "Fix slow running BigQuery jobs or memory spillage"
- "Detect Cartesian joins or row count explosions in BigQuery"
- "Identify unpartitioned table scans or missing partition filters"

---

## 2. Diagnostic Execution Workflow

### Step 1: Execute Automated Telemetry Extraction
Run `scripts/slot_analyzer.py` to pull and analyze historical query telemetry from `INFORMATION_SCHEMA.JOBS_BY_PROJECT`:

```bash
# General analysis for the last 7 days
python3 scripts/slot_analyzer.py --project-id <PROJECT_ID> --days 7 --format table

# Output structured JSON for programmatically parsing recommendations
python3 scripts/slot_analyzer.py --project-id <PROJECT_ID> --days 7 --format json

# Offline verification mode using synthetic telemetry
python3 scripts/slot_analyzer.py --mock-data-file tests/mock_data.json --format table

# Dry-run mode to inspect regional SQL query
python3 scripts/slot_analyzer.py --project-id <PROJECT_ID> --region region-us --dry-run
```

#### Supported CLI Flags
- `--project` / `--project-id`: Target Google Cloud project identifier.
- `--region`: Regional qualifier (e.g. `region-us`, `region-eu`, `us-central1`).
- `--days`: Lookback interval in days (1 to 30, default: 7).
- `--mode`: Analysis focus (`slots`, `cost`, `bottlenecks`, `all`).
- `--limit`: Maximum number of queries displayed (default: 10).
- `--format`: Output format (`table`, `json`, `csv`).
- `--threshold-slot-hours`: Minimum slot-hours threshold to flag query (default: 0.5).
- `--dry-run`: Display regional SQL without contacting BigQuery.
- `--mock-data-file`: Path to local JSON file for offline execution.
- `--output-file`: File path to save output.

---

## 3. Metric Interpretation & Decision Tree

Evaluate the telemetry output using the following decision rules:

```
[Query Telemetry Analyzed]
       |
       +---> If wait_ratio_avg > 0.40 OR slot_contention == TRUE
       |     --> Classify as SLOT STARVATION (Rule SLOT-001)
       |     --> Jump to Remediation 4.1
       |
       +---> If shuffle_output_bytes_spilled > 0 OR records_written > 10 * records_read
       |     --> Classify as CARTESIAN EXPLOSION (Rule JOIN-001)
       |     --> Jump to Remediation 4.2
       |
       +---> If total_bytes_billed > 10 GB AND no date/partition filters
       |     --> Classify as UNPARTITIONED SCAN (Rule PART-001)
       |     --> Jump to Remediation 4.3
       |
       +---> Otherwise
             --> Check BI Engine or Clustering opportunities
             --> See references/optimization_rules.md
```

---

## 4. Concrete Remediation Playbooks

### 4.1 Rule SLOT-001: Slot Contention & Queueing
- **Symptoms**: Stages have high `wait_ratio_avg` (> 40%), `total_slot_ms` is high, but wall-clock time is disproportionately prolonged.
- **Root Cause**: The query is competing for slots in an oversubscribed on-demand pool or undersized capacity reservation.
- **Remediation**:
  1. **Slot Sizing**: In Editions (Standard, Enterprise, Enterprise Plus), configure baseline slots with an autoscaling ceiling to accommodate burst workloads.
  2. **Stagger Scheduled Queries**: Stagger batch ETL jobs that launch simultaneously at midnight UTC.
  3. **Stage Optimization**: Optimize stages with massive row shuffles to reduce concurrent slot holding time.

### 4.2 Rule JOIN-001: Cartesian & Exploding Joins
- **Symptoms**: Output records exceed input records by orders of magnitude; `shuffle_output_bytes_spilled` > 0.
- **Root Cause**: `CROSS JOIN` or non-unique join keys causing duplicate row generation ($M \times N$ expansion).
- **Remediation**:
  - **Antipattern**:
    ```sql
    SELECT *
    FROM `orders` o
    CROSS JOIN `web_events` e
    WHERE o.customer_id = e.customer_id;
    ```
  - **Optimized SQL**:
    ```sql
    -- Replace with qualified inner or left equi-join
    SELECT o.order_id, o.total_amount, e.event_name
    FROM `orders` o
    INNER JOIN `web_events` e
      ON o.customer_id = e.customer_id;
    ```
  - **Pre-Aggregation Pattern**:
    When joining two child tables on a shared parent key, aggregate dimensions before joining:
    ```sql
    WITH agg_events AS (
      SELECT customer_id, COUNT(*) AS event_count
      FROM `web_events`
      GROUP BY customer_id
    )
    SELECT o.order_id, o.customer_id, e.event_count
    FROM `orders` o
    LEFT JOIN agg_events e ON o.customer_id = e.customer_id;
    ```

### 4.3 Rule PART-001: Unpartitioned Scans & Partition Pruning
- **Symptoms**: `total_bytes_billed` > 10 GB scanning historical logs or transaction history.
- **Root Cause**: Table is unpartitioned or query applies functions that prevent partition pruning.
- **Remediation**:
  - **Partition Table DDL**:
    ```sql
    ALTER TABLE `ecommerce.orders`
    SET OPTIONS (require_partition_filter = TRUE);
    ```
  - **Avoid Function Wrappers in Predicates**:
    ```sql
    -- BAD: Scans entire table because function wraps partitioned column
    WHERE DATE(order_timestamp) = '2026-03-01';

    -- GOOD: Enables constant partition pruning
    WHERE order_timestamp >= '2026-03-01 00:00:00 UTC'
      AND order_timestamp < '2026-03-02 00:00:00 UTC';
    ```

---

## 5. Architectural Reference Links

For deep architectural patterns, DDL examples, and index design:
- Table Partitioning, Clustering, BI Engine: `references/optimization_rules.md`
- BigQuery Search Indexes & Materialized Views: `references/optimization_rules.md`

---

## 6. Verification & Validation Protocol

Before finalizing query rewrites:
1. **Dry-Run Validation**:
   Validate query syntax and calculate estimated bytes scanned without incurring cost:
   ```python
   from google.cloud import bigquery
   client = bigquery.Client()
   job_config = bigquery.QueryJobConfig(dry_run=True, use_query_cache=False)
   query_job = client.query(optimized_sql, job_config=job_config)
   print(f"Scanned bytes: {query_job.total_bytes_processed / (1024**3):.2f} GB")
   ```
2. **Offline Unit Testing**:
   Run the pytest suite to verify parser and heuristic fidelity:
   ```bash
   pytest tests/ -v
   ```
