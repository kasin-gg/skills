---
name: bigquery-slot-cost-optimizer
description: >-
  Analyzes Google Cloud BigQuery slot consumption, query costs, and execution
  bottlenecks using INFORMATION_SCHEMA. Use when diagnosing slow BigQuery queries,
  slot starvation, high on-demand query costs, unpartitioned table scans, or join
  performance issues. Don't use for generic BigQuery administration (use
  bigquery-basics), BigQuery ML (use bigquery-ai-ml), or DataFrame operations
  (use bigquery-bigframes).
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

# BigQuery slot and cost optimizer

This skill equips AI agents and cloud engineers with procedural heuristics to analyze BigQuery resource consumption, calculate slot hours, identify slot contention and queueing, mitigate Cartesian joins, and optimize unpartitioned table scans.

## Trigger conditions and intent mapping

Activate this skill whenever the user asks to:
- "Optimize BigQuery query performance or reduce slot usage"
- "Find the most expensive queries in BigQuery"
- "Diagnose BigQuery slot contention or queueing"
- "Fix slow running BigQuery jobs or memory spillage"
- "Detect Cartesian joins or row count explosions in BigQuery"
- "Identify unpartitioned table scans or missing partition filters"

## Prerequisites and environment setup

Before executing this skill, ensure the environment is configured with the necessary SDKs, permissions, and billing:

1. **Cloud SDK and client library installation**:
   - Install the Google Cloud CLI: [Google Cloud SDK installation guide](https://docs.cloud.google.com/sdk/docs/install-sdk.md.txt)
   - Install the BigQuery Python client:

     ```bash
     pip install google-cloud-bigquery
     ```

1. **Project, billing, and regional selection**:
   - Set the active project:

     ```bash
     gcloud config set project <PROJECT_ID>
     ```

   - **Important**: the target Google Cloud project must have an active Cloud Billing account attached.
   - **Regional selection**: specify the target BigQuery dataset location or execution region, as BigQuery `INFORMATION_SCHEMA` views are strictly region-scoped (for example, multi-regions like `region-us` or `region-eu`, or single regions like `region-us-central1`). Querying the wrong region returns empty job telemetry. Pass the matching region via `--region` (the script automatically normalizes location names like `us-central1` to `region-us-central1`). For valid location identifiers, see [BigQuery locations](https://docs.cloud.google.com/bigquery/docs/locations.md.txt).

1. **API enablement**:
   - Enable the BigQuery API on the project:

     ```bash
     gcloud services enable bigquery.googleapis.com
     ```

1. **Authentication setup**:
   - Authenticate the local gcloud environment and configure Application Default Credentials (ADC):

     ```bash
     gcloud auth login
     gcloud auth application-default login
     ```

1. **IAM roles and permissions**:
   - The executing principal requires the following minimum IAM roles:
     - `roles/bigquery.jobUser`: grants permission to run queries and analyze telemetry.
     - `roles/bigquery.resourceViewer`: grants read-only access to query metadata in `INFORMATION_SCHEMA.JOBS_BY_PROJECT` and capacity reservations.

1. **Pricing reference**:
   - Cost estimates in this skill are for planning purposes. Before running `scripts/slot_analyzer.py`, retrieve live BigQuery billing rates at runtime from official [Google Cloud BigQuery Pricing](https://cloud.google.com/bigquery/pricing) (and consult [BigQuery editions introduction](https://docs.cloud.google.com/bigquery/docs/editions-intro.md.txt) for edition capabilities) after considering user-specific parameters such as target region, chosen edition (`Standard`, `Enterprise`, `Enterprise Plus`), and commitment tier (`Pay-as-you-go`, `1-year`, `3-year`). Pass these runtime-fetched rates explicitly via `--ondemand-rate <USD_PER_TIB>` and `--slot-hour-rate <USD_PER_SLOT_HOUR>`.

## Diagnostic execution workflow

### Execute automated telemetry extraction

Run `scripts/slot_analyzer.py` to pull and analyze historical query telemetry from `INFORMATION_SCHEMA.JOBS_BY_PROJECT`, passing the runtime-retrieved pricing rates for your specific region, edition, and commitment tier:

```bash
# General analysis passing live regional pricing rates fetched from BigQuery pricing
python3 scripts/slot_analyzer.py --project-id <PROJECT_ID> --days 7 \
  --ondemand-rate <USD_PER_TIB> --slot-hour-rate <USD_PER_SLOT_HOUR> --format table

# Output structured JSON for programmatically parsing recommendations
python3 scripts/slot_analyzer.py --project-id <PROJECT_ID> --days 7 \
  --ondemand-rate <USD_PER_TIB> --slot-hour-rate <USD_PER_SLOT_HOUR> --format json

# Offline verification mode using synthetic or extracted telemetry
python3 scripts/slot_analyzer.py --mock-data-file path/to/extracted_telemetry.json \
  --ondemand-rate <USD_PER_TIB> --slot-hour-rate <USD_PER_SLOT_HOUR> --format table

# Dry-run mode to inspect regional SQL query
python3 scripts/slot_analyzer.py --project-id <PROJECT_ID> --region region-us --dry-run
```

Run `python3 scripts/slot_analyzer.py --help` to inspect all supported CLI flags, focus modes (`--mode`), and required pricing rate arguments (`--ondemand-rate` per TiB and `--slot-hour-rate` per slot-hour).

## Metric interpretation and decision tree

Evaluate the telemetry output using the following decision rules:

```
[Query Telemetry Analyzed]
       |
       +---> If wait_ratio_avg > 0.40 OR slot_contention == TRUE
       |     --> Classify as slot contention and queueing (Rule SLOT-001)
       |     --> Jump to Rule SLOT-001
       |
       +---> If shuffle_output_bytes_spilled > 0 OR records_written > 10 * records_read
       |     --> Classify as Cartesian join (Rule JOIN-001)
       |     --> Jump to Rule JOIN-001
       |
       +---> If total_bytes_billed > 10 GB AND no date/partition filters
       |     --> Classify as unpartitioned scan (Rule PART-001)
       |     --> Jump to Rule PART-001
       |
       +---> Otherwise
             --> Check BI Engine or clustering opportunities
             --> See references/optimization_rules.md
```

## Concrete remediation playbooks

### Rule SLOT-001: slot contention and queueing

- **Symptoms**: stages have high `wait_ratio_avg` (> 40%), `total_slot_ms` is high, but wall-clock time is disproportionately prolonged.
- **Root cause**: the query is competing for slots in an oversubscribed on-demand pool or undersized capacity reservation.
- **Remediation**:
  1. **Slot sizing**: in Editions (Standard, Enterprise, Enterprise Plus), configure baseline slots with an autoscaling ceiling to accommodate burst workloads.
  1. **Stagger scheduled queries**: stagger batch ETL jobs that launch simultaneously at midnight UTC.
  1. **Stage optimization**: optimize stages with massive row shuffles to reduce concurrent slot holding time.

### Rule JOIN-001: Cartesian and exploding joins

- **Symptoms**: query execution stage telemetry shows massive row count explosions where `records_written` drastically exceeds `records_read` by orders of magnitude, accompanied by memory spillage to persistent storage (`shuffle_output_bytes_spilled` > 0).
- **Root cause**: missing or non-selective join predicates (such as unintentional `CROSS JOIN`, missing `ON` conditions, or tautological `ON 1=1` predicates) or non-unique many-to-many join keys causing duplicate row generation ($M \times N$ expansion).
- **Mandatory diagnostic and remediation workflow (include all 4 steps in your analysis)**:
  1. **Check stage telemetry for row count explosions**: query `INFORMATION_SCHEMA.JOBS_BY_PROJECT` (`job_stages`) or inspect the execution graph to identify stages where output rows (`records_written`) drastically exceed input rows (`records_read`).
  2. **Check for missing or non-selective join predicates**: explicitly inspect every `JOIN` clause in the SQL query text for missing `ON` conditions, unintentional `CROSS JOIN` syntax, or non-selective join predicates (such as `ON 1=1`), in addition to checking for duplicate keys across joined tables.
  3. **Check for memory spillage to persistent storage**: check stage telemetry for `shuffle_output_bytes_spilled > 0` (shuffle disk spillage caused by intermediate join state exceeding slot memory buffers).
  4. **Pre-aggregate dimensional data or enforce distinct keys**: pre-aggregate dimensional/activity tables down to unique join keys in CTEs before joining, or enforce `DISTINCT` key constraints to eliminate row multiplication:

  - **Diagnostic SQL for stage row explosion and shuffle spillage**:

    ```sql
    SELECT
      job_id,
      stage.name AS stage_name,
      stage.records_read,
      stage.records_written,
      SAFE_DIVIDE(stage.records_written, NULLIF(stage.records_read, 0)) AS row_expansion_ratio,
      stage.shuffle_output_bytes_spilled
    FROM `region-us`.INFORMATION_SCHEMA.JOBS_BY_PROJECT,
    UNNEST(job_stages) AS stage
    WHERE creation_time >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 7 DAY)
      AND (stage.records_written > stage.records_read * 10 OR stage.shuffle_output_bytes_spilled > 0)
    ORDER BY stage.shuffle_output_bytes_spilled DESC;
    ```

  - **Antipattern (unintentional CROSS JOIN / missing ON condition)**:

    ```sql
    SELECT *
    FROM `orders` o
    CROSS JOIN `web_events` e
    WHERE o.customer_id = e.customer_id;
    ```

  - **Optimized SQL (qualified equi-join + pre-aggregation CTE)**:

    ```sql
    WITH agg_events AS (
      SELECT customer_id, COUNT(*) AS event_count
      FROM `web_events`
      GROUP BY customer_id
    )
    SELECT o.order_id, o.customer_id, e.event_count
    FROM `orders` o
    INNER JOIN agg_events e
      ON o.customer_id = e.customer_id;
    ```

### Rule PART-001: unpartitioned scans and partition pruning

- **Symptoms**: high `total_bytes_billed` and `total_bytes_processed` (> 10 GB) in `INFORMATION_SCHEMA.JOBS_BY_PROJECT` when scanning historical logs or transaction history.
- **Root cause**: table lacks partitioning, query omits partition filter predicates, or query wraps partitioned columns in functions that prevent partition pruning.
- **Mandatory diagnostic and remediation workflow (include all 4 steps in your analysis)**:
  1. **Inspect both `total_bytes_billed` and `total_bytes_processed` in `INFORMATION_SCHEMA.JOBS_BY_PROJECT`**: run a diagnostic query selecting **both** `total_bytes_billed` and `total_bytes_processed` to identify expensive full table scans:

     ```sql
     SELECT
       job_id,
       user_email,
       total_bytes_processed,
       total_bytes_billed,
       query
     FROM `region-us`.INFORMATION_SCHEMA.JOBS_BY_PROJECT
     WHERE creation_time >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 7 DAY)
       AND total_bytes_processed > 10 * 1024 * 1024 * 1024
     ORDER BY total_bytes_billed DESC;
     ```

  2. **Verify date, timestamp, or integer-range partitioning on referenced tables**: query `INFORMATION_SCHEMA.COLUMNS` (checking `is_partitioning_column = 'YES'` and `data_type` for `DATE`, `TIMESTAMP`, `DATETIME`, or `INT64` integer-range partitioning) and `INFORMATION_SCHEMA.PARTITIONS` to verify whether referenced tables are partitioned and inspect their partition scheme:

     ```sql
     SELECT
       table_name,
       column_name,
       data_type AS partition_type,
       is_partitioning_column,
       clustering_ordinal_position
     FROM `project.dataset`.INFORMATION_SCHEMA.COLUMNS
     WHERE is_partitioning_column = 'YES'
        OR clustering_ordinal_position IS NOT NULL;
     ```

  3. **Enforce partition filters (`require_partition_filter = TRUE`)**: enable `require_partition_filter = TRUE` on large partitioned tables via `ALTER TABLE` or `CREATE TABLE` DDL to block accidental full table scans:

     ```sql
     ALTER TABLE `project.dataset.orders`
     SET OPTIONS (require_partition_filter = TRUE);
     ```

  4. **Recommend clustering on high-cardinality filtering and grouping columns**: always combine partitioning with multi-column clustering (`CLUSTER BY`) on high-cardinality columns frequently used in `WHERE` filters, `JOIN` keys, and `GROUP BY` clauses (up to 4 columns):

     ```sql
     CREATE OR REPLACE TABLE `project.dataset.orders_optimized`
     PARTITION BY DATE(order_timestamp)
     CLUSTER BY customer_id, region_id
     OPTIONS (require_partition_filter = TRUE)
     AS SELECT * FROM `project.dataset.orders`;
     ```

  - **Avoid function wrappers on partition columns**:

    ```sql
    -- BAD: Scans entire table because function wraps partitioned column
    WHERE DATE(order_timestamp) = '2026-03-01';

    -- GOOD: Enables constant partition pruning
    WHERE order_timestamp >= '2026-03-01 00:00:00 UTC'
      AND order_timestamp < '2026-03-02 00:00:00 UTC';
    ```

## Architectural reference links

For deep architectural patterns, DDL examples, and index design:
- Table partitioning, clustering, BI Engine: [optimization rules](references/optimization_rules.md)
- BigQuery search indexes and materialized views: [optimization rules](references/optimization_rules.md)

## Verification and validation protocol

Before finalizing query rewrites:

### Dry-run validation

Validate query syntax and calculate estimated bytes scanned without incurring cost:

```python
from google.cloud import bigquery
client = bigquery.Client()
job_config = bigquery.QueryJobConfig(dry_run=True, use_query_cache=False)
query_job = client.query(optimized_sql, job_config=job_config)
print(f"Scanned bytes: {query_job.total_bytes_processed / (1024**3):.2f} GB")
```

### Offline and dry-run validation

- **Offline mock telemetry verification**: validate heuristic classification, slot contention detection, Cartesian join identification, and cost estimation offline using synthetic or extracted JSON telemetry payloads (`--mock-data-file`):

  ```bash
  python3 scripts/slot_analyzer.py --mock-data-file path/to/extracted_telemetry.json \
    --ondemand-rate <USD_PER_TIB> --slot-hour-rate <USD_PER_SLOT_HOUR> --format table
  ```

- **CLI dry-run inspection**: verify regional SQL query formation and script execution without contacting BigQuery or incurring costs:

  ```bash
  python3 scripts/slot_analyzer.py --project-id <PROJECT_ID> --region region-us --dry-run
  ```
