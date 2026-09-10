# BigQuery Query & Architecture Optimization Heuristics

This reference catalog documents concrete optimization heuristics, architectural rules, and SQL rewrite patterns for Google Cloud BigQuery workloads. It is used by both automated diagnostic engines and human practitioners to resolve compute bottlenecks and reduce query costs.

---

## 1. Partitioning Optimization

Table partitioning divides large tables into smaller segments, significantly reducing bytes scanned and slot consumption by pruning unneeded partitions at query planning time.

### 1.1 Partitioning Types
1. **Time-Unit Column Partitioning**:
   - Partitioned on `DATE`, `DATETIME`, or `TIMESTAMP` columns.
   - Granularities: Hour, Day, Month, Year.
   - Example DDL:
     ```sql
     CREATE OR REPLACE TABLE `acme-analytics-prod.ecommerce.orders`
     (
       order_id STRING,
       customer_id STRING,
       order_timestamp TIMESTAMP,
       total_amount NUMERIC
     )
     PARTITION BY TIMESTAMP_TRUNC(order_timestamp, DAY)
     OPTIONS (
       require_partition_filter = TRUE,
       partition_expiration_days = 730
     );
     ```
2. **Ingestion-Time Partitioning**:
   - Uses pseudo-columns `_PARTITIONTIME` or `_PARTITIONDATE`.
   - Useful when tables lack natural timestamp fields.
3. **Integer Range Partitioning**:
   - Partitioned on an `INT64` column using `GENERATE_ARRAY(start, end, interval)`.
   - Example: Customer ID ranges or account segment IDs.

### 1.2 Architectural Guardrails
- **Max Partitions**: A table cannot exceed 4,000 partitions. Daily partitioning supports ~10 years of historical data; hourly partitioning supports ~5.5 months.
- **Enforcing Filters**: Always set `OPTIONS (require_partition_filter = TRUE)` on high-volume tables (>100 GB) to prevent inadvertent full-table scans by ad-hoc queries.

### 1.3 SQL Antipatterns & Rewrites
- **Antipattern: Function on Partition Column**:
  Applying a conversion function to a partitioned column invalidates partition pruning.
  ```sql
  -- BAD: Prevents partition pruning, scans entire table!
  SELECT COUNT(*)
  FROM `acme-analytics-prod.ecommerce.orders`
  WHERE DATE(order_timestamp) = '2026-03-01';

  -- GOOD: Prunes partitions deterministically using timestamp bounds
  SELECT COUNT(*)
  FROM `acme-analytics-prod.ecommerce.orders`
  WHERE order_timestamp >= '2026-03-01 00:00:00 UTC'
    AND order_timestamp < '2026-03-02 00:00:00 UTC';
  ```

---

## 2. Multi-Column Clustering Optimization

Clustering sorts data based on the contents of up to four columns, co-locating related data within storage blocks. BigQuery utilizes metadata min/max values to skip unneeded storage blocks during scans.

### 2.1 Column Ordering Hierarchy
When defining clustered columns, ordering matters:
1. **Primary Key / Frequent Equality Filter**: Place the most commonly filtered column first.
2. **High-Cardinality Dimension**: Place dimensions frequently filtered together or used in inequality filters.
3. **Grouping or Joining Key**: Place columns frequently used in `GROUP BY` or `JOIN` conditions.

Example DDL:
```sql
CREATE OR REPLACE TABLE `acme-analytics-prod.ecommerce.orders_clustered`
(
  order_id STRING,
  customer_id STRING,
  region_id STRING,
  order_timestamp TIMESTAMP,
  total_amount NUMERIC
)
PARTITION BY DATE(order_timestamp)
CLUSTER BY customer_id, region_id;
```

### 2.2 Synergistic Partitioning and Clustering
- BigQuery evaluates partition bounds first, pruning entire partition storage directories.
- Within matching partitions, BigQuery evaluates clustering min/max block metadata, scanning only matching 100MB-1GB blocks.
- This combination regularly yields 90-99% reductions in scanned bytes and slot execution time.

---

## 3. BI Engine In-Memory Acceleration

Google Cloud BigQuery BI Engine is a built-in, distributed in-memory analysis service that accelerates SQL queries in real time with sub-second latency and zero slot usage from reservations.

### 3.1 Qualifying Queries for In-Memory Execution
- Suitable for repetitive analytical dashboards (Looker, Looker Studio, Tableau) and interactive SQL aggregations.
- Inspect execution plans in `INFORMATION_SCHEMA.JOBS_BY_*` for:
  - `query_info.bi_engine_statistics.bi_engine_mode = 'FULL'` (Fully accelerated).
  - `query_info.bi_engine_statistics.bi_engine_mode = 'PARTIAL'` (Partially accelerated; some stages ran in slots).
  - `query_info.bi_engine_statistics.bi_engine_mode = 'DISABLED'` (BI Engine skipped).

### 3.2 Unsupported BI Engine Constructs
If queries fall back from BI Engine to standard slot compute, inspect `bi_engine_reasons`:
- Queries containing non-deterministic functions (e.g., `CURRENT_TIMESTAMP()`, `RAND()`).
- Complex JavaScript User-Defined Functions (UDFs).
- Non-equi joins (`ON a.val > b.val`).
- Tables exceeding BI Engine reservation memory capacity without partitioning.

---

## 4. BigQuery Search Indexes

Search indexing provides sub-second point lookups and substring search across high-volume log, telemetry, and unstructured JSON datasets without scanning billions of rows.

### 4.1 Index Creation
Create search indexes across all columns or targeted string/JSON columns:
```sql
-- Index all text columns in audit log table
CREATE SEARCH INDEX IF NOT EXISTS logs_search_idx
ON `acme-analytics-prod.telemetry.application_logs`(ALL COLUMNS);

-- Index targeted JSON payload column
CREATE SEARCH INDEX IF NOT EXISTS payload_search_idx
ON `acme-analytics-prod.telemetry.events`(payload);
```

### 4.2 Query Patterns & Rewrites
- Use the built-in `SEARCH()` function to leverage the inverted B-tree index.
```sql
-- BAD: Full table scan scanning hundreds of gigabytes
SELECT timestamp, log_level, message
FROM `acme-analytics-prod.telemetry.application_logs`
WHERE REGEXP_CONTAINS(message, r'FATAL_EXCEPTION_500');

-- GOOD: Search index lookup scanning near zero bytes
SELECT timestamp, log_level, message
FROM `acme-analytics-prod.telemetry.application_logs`
WHERE SEARCH(message, '`FATAL_EXCEPTION_500`');
```

---

## 5. Materialized Views & Transparent Query Rewriting

Materialized views periodically pre-compute and store aggregated result sets with automatic incremental maintenance and zero administrative pipeline overhead.

### 5.1 Automatic Query Rewrite Engine
A major architectural advantage in BigQuery is transparent query rewriting:
- Even if a user query targets the raw base table, the BigQuery optimizer inspects matching materialized views.
- If the view covers the requested dimensions and metrics, BigQuery automatically reroutes the query to scan the pre-computed materialized view!

Example DDL:
```sql
CREATE MATERIALIZED VIEW `acme-analytics-prod.ecommerce.mv_daily_sales_by_region`
PARTITION BY order_date
CLUSTER BY region_id
AS
SELECT
  DATE(order_timestamp) AS order_date,
  region_id,
  COUNT(order_id) AS total_orders,
  SUM(total_amount) AS total_revenue
FROM `acme-analytics-prod.ecommerce.orders`
GROUP BY 1, 2;
```

---

## 6. Join Optimization & Data Skew Mitigation

Inefficient joins are the primary cause of memory exhaustion, shuffle disk spillage, and explosive slot-hour consumption.

### 6.1 Hash Join vs. Broadcast Join
- In a **Broadcast Join**, BigQuery sends the entire right table to each slot processing the left table.
- Best practice: Always place the largest table on the LEFT side of the `JOIN` keyword and the smaller dimension table on the RIGHT side.
- BigQuery automatically chooses broadcast join when the right table is under ~50MB.

### 6.2 Cartesian Join Elimination
- A Cartesian product (`CROSS JOIN` or unqualified join condition) multiplies row counts exponentially ($M \times N$), causing shuffle spilling to persistent disk.
- **Remediation**:
  1. Replace `CROSS JOIN` with filtered equi-joins.
  2. If matching many-to-many relationships, pre-aggregate one side before joining.

```sql
-- BAD: Exploding Cartesian join due to multiple transactions per customer per day
SELECT
  c.customer_id,
  t.transaction_amount,
  e.event_name
FROM `acme-analytics-prod.ecommerce.customers` c
JOIN `acme-analytics-prod.ecommerce.transactions` t ON c.customer_id = t.customer_id
JOIN `acme-analytics-prod.ecommerce.web_events` e ON c.customer_id = e.customer_id;

-- GOOD: Pre-aggregated metrics joined cleanly without row multiplication
WITH txn_summary AS (
  SELECT customer_id, SUM(transaction_amount) AS total_spent
  FROM `acme-analytics-prod.ecommerce.transactions`
  GROUP BY customer_id
),
event_summary AS (
  SELECT customer_id, COUNT(*) AS total_events
  FROM `acme-analytics-prod.ecommerce.web_events`
  GROUP BY customer_id
)
SELECT
  c.customer_id,
  COALESCE(t.total_spent, 0) AS total_spent,
  COALESCE(e.total_events, 0) AS total_events
FROM `acme-analytics-prod.ecommerce.customers` c
LEFT JOIN txn_summary t ON c.customer_id = t.customer_id
LEFT JOIN event_summary e ON c.customer_id = e.customer_id;
```

### 6.3 Mitigating Data Skew
When a join key has heavy key concentration (e.g. `customer_id IS NULL` or `customer_id = 'DEFAULT'`), a single slot receives millions of rows while other slots remain idle.
- Filter out dummy/NULL keys before joining:
  ```sql
  WHERE customer_id IS NOT NULL AND customer_id != 'GUEST'
  ```
- Salting: For skewed non-null keys, append a random integer hash `MOD(FARM_FINGERPRINT(id), 10)` to distribute across slots.
