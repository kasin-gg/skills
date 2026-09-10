# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Unit tests for BigQuery Slot & Cost Optimizer CLI and diagnostic heuristics."""

from datetime import datetime, timezone
import io
import json
import os
import sys
import tempfile
import types
import unittest
import unittest.mock as mock

# Ensure google cloud modules can be imported/mocked across any python environment
try:
    from google.cloud import bigquery
    from google.auth.exceptions import DefaultCredentialsError
    from google.api_core.exceptions import Forbidden
except ImportError:
    google_mod = types.ModuleType("google")
    cloud_mod = types.ModuleType("google.cloud")
    bigquery_mod = types.ModuleType("google.cloud.bigquery")
    auth_mod = types.ModuleType("google.auth")
    auth_exceptions_mod = types.ModuleType("google.auth.exceptions")
    api_core_mod = types.ModuleType("google.api_core")
    api_core_exceptions_mod = types.ModuleType("google.api_core.exceptions")

    class DefaultCredentialsError(Exception):
        pass

    class Forbidden(Exception):
        pass

    class MockClient:
        def __init__(self, *args, **kwargs):
            pass

    bigquery_mod.Client = MockClient
    auth_exceptions_mod.DefaultCredentialsError = DefaultCredentialsError
    api_core_exceptions_mod.Forbidden = Forbidden

    sys.modules.setdefault("google", google_mod)
    sys.modules.setdefault("google.cloud", cloud_mod)
    sys.modules.setdefault("google.cloud.bigquery", bigquery_mod)
    sys.modules.setdefault("google.auth", auth_mod)
    sys.modules.setdefault("google.auth.exceptions", auth_exceptions_mod)
    sys.modules.setdefault("google.api_core", api_core_mod)
    sys.modules.setdefault("google.api_core.exceptions", api_core_exceptions_mod)

    from google.cloud import bigquery
    from google.auth.exceptions import DefaultCredentialsError
    from google.api_core.exceptions import Forbidden

from scripts.slot_analyzer import (
    AnalysisSummary,
    JobStage,
    PerformanceInsights,
    QueryJobMetrics,
    calculate_avg_slot_concurrency,
    calculate_cost_estimates,
    calculate_slot_hours,
    create_argument_parser,
    detect_cartesian_joins,
    detect_slot_contention,
    detect_unpartitioned_scans,
    fetch_bigquery_jobs,
    format_as_ascii_table,
    generate_information_schema_query,
    load_mock_data,
    normalize_region,
    parse_job_row,
    render_csv_output,
    render_json_output,
    render_table_output,
    run_analysis,
    summarize_analysis,
)


class TestSlotAnalyzer(unittest.TestCase):
    """Exhaustive test suite covering slot analyzer CLI, math, and heuristics."""

    def setUp(self):
        """Set up test fixtures and paths."""
        self.mock_data_path = os.path.join(os.path.dirname(__file__), "mock_data.json")
        self.sample_healthy_job_dict = {
            "project_id": "acme-analytics-prod",
            "job_id": "job_sample_healthy",
            "user_email": "analyst@example.com",
            "start_time": "2026-03-01T12:00:00Z",
            "end_time": "2026-03-01T12:01:00Z",
            "query": "SELECT id, name FROM `acme-analytics-prod.sales.customers` WHERE _PARTITIONDATE = '2026-03-01'",
            "total_slot_ms": 3600000,
            "total_bytes_processed": 104857600,
            "total_bytes_billed": 104857600,
            "cache_hit": False,
            "referenced_tables": [],
            "job_stages": [
                {
                    "stage_id": 0,
                    "name": "Stage 0",
                    "records_read": 10000,
                    "records_written": 1000,
                    "shuffle_output_bytes": 50000,
                    "shuffle_output_bytes_spilled": 0,
                    "wait_ratio_avg": 0.05,
                    "slot_ms": 3600000,
                }
            ],
            "performance_insights": None,
        }
        self.sample_cartesian_job_dict = {
            "project_id": "acme-analytics-prod",
            "job_id": "job_sample_cartesian",
            "user_email": "dev@example.com",
            "start_time": "2026-03-01T13:00:00Z",
            "end_time": "2026-03-01T13:10:00Z",
            "query": "SELECT * FROM t1 CROSS JOIN t2",
            "total_slot_ms": 72000000,
            "total_bytes_processed": 5368709120,
            "total_bytes_billed": 5368709120,
            "cache_hit": False,
            "referenced_tables": [],
            "job_stages": [
                {
                    "stage_id": 1,
                    "name": "Explosion Stage",
                    "records_read": 2000,
                    "records_written": 5000000,
                    "shuffle_output_bytes": 100000000,
                    "shuffle_output_bytes_spilled": 20971520,
                    "wait_ratio_avg": 0.1,
                    "slot_ms": 72000000,
                }
            ],
            "performance_insights": None,
        }

    # --------------------------------------------------------------------------
    # CLI Argument Parsing Tests
    # --------------------------------------------------------------------------

    def test_cli_parser_defaults(self):
        """Verifies default values in CLI argument parser."""
        parser = create_argument_parser()
        args = parser.parse_args([])
        self.assertEqual(args.region, "region-us")
        self.assertEqual(args.days, 7)
        self.assertEqual(args.mode, "all")
        self.assertEqual(args.limit, 10)
        self.assertEqual(args.format, "table")
        self.assertEqual(args.threshold_slot_hours, 0.5)
        self.assertFalse(args.dry_run)
        self.assertIsNone(args.mock_data_file)
        self.assertIsNone(args.output_file)

    def test_cli_parser_custom_args(self):
        """Verifies custom arguments in CLI parser."""
        parser = create_argument_parser()
        args = parser.parse_args([
            "--project-id", "test-project-123",
            "--region", "eu",
            "--days", "14",
            "--mode", "bottlenecks",
            "--limit", "25",
            "--format", "json",
            "--threshold-slot-hours", "1.5",
            "--dry-run",
        ])
        self.assertEqual(args.project_id, "test-project-123")
        self.assertEqual(args.region, "eu")
        self.assertEqual(args.days, 14)
        self.assertEqual(args.mode, "bottlenecks")
        self.assertEqual(args.limit, 25)
        self.assertEqual(args.format, "json")
        self.assertEqual(args.threshold_slot_hours, 1.5)
        self.assertTrue(args.dry_run)

    def test_cli_region_normalization(self):
        """Tests regional prefix normalizer."""
        self.assertEqual(normalize_region("us"), "region-us")
        self.assertEqual(normalize_region("eu"), "region-eu")
        self.assertEqual(normalize_region("us-central1"), "region-us-central1")
        self.assertEqual(normalize_region("region-us"), "region-us")
        self.assertEqual(normalize_region("REGION-EU"), "region-eu")

    # --------------------------------------------------------------------------
    # Mathematical Calculations
    # --------------------------------------------------------------------------

    def test_calculate_slot_hours(self):
        """Tests conversion of slot milliseconds into slot-hours."""
        self.assertEqual(calculate_slot_hours(3_600_000), 1.0)
        self.assertEqual(calculate_slot_hours(1_800_000), 0.5)
        self.assertEqual(calculate_slot_hours(900_000), 0.25)
        self.assertEqual(calculate_slot_hours(0), 0.0)
        self.assertEqual(calculate_slot_hours(-1000), 0.0)

    def test_calculate_avg_slot_concurrency(self):
        """Tests calculation of average slot concurrency."""
        start = datetime(2026, 3, 1, 10, 0, 0, tzinfo=timezone.utc)
        end = datetime(2026, 3, 1, 11, 0, 0, tzinfo=timezone.utc)  # 3600 seconds = 3,600,000 ms
        total_slot_ms = 7_200_000  # 2 hours of slot time over 1 hour elapsed

        concurrency = calculate_avg_slot_concurrency(total_slot_ms, start, end)
        self.assertEqual(concurrency, 2.0)

        # Sub-second elapsed time check (protect against division by zero)
        same_time = datetime(2026, 3, 1, 10, 0, 0, tzinfo=timezone.utc)
        zero_elapsed_concurrency = calculate_avg_slot_concurrency(1000, same_time, same_time)
        self.assertGreater(zero_elapsed_concurrency, 0)

        # Zero slot ms check
        self.assertEqual(calculate_avg_slot_concurrency(0, start, end), 0.0)

    def test_calculate_cost_estimates(self):
        """Tests dollar cost estimation for On-Demand and Editions tiers."""
        one_tb_bytes = 1_099_511_627_776
        slot_hours = 10.0

        cost_od, cost_ed = calculate_cost_estimates(one_tb_bytes, slot_hours)
        self.assertEqual(cost_od, 6.25)
        self.assertEqual(cost_ed, 0.60)

        # Zero bytes / zero slot hours
        cost_od_zero, cost_ed_zero = calculate_cost_estimates(0, 0.0)
        self.assertEqual(cost_od_zero, 0.0)
        self.assertEqual(cost_ed_zero, 0.0)

    # --------------------------------------------------------------------------
    # Heuristic Detections
    # --------------------------------------------------------------------------

    def test_detect_cartesian_joins_row_explosion(self):
        """Tests Cartesian explosion detection via records_written vs records_read."""
        stage_exploding = JobStage(
            stage_id=0,
            name="JoinStage",
            records_read=1_500,
            records_written=150_000,  # 100x explosion
            shuffle_output_bytes=1000,
            shuffle_output_bytes_spilled=0,
            wait_ratio_avg=0.05,
            slot_ms=1000,
        )
        is_cartesian, reasons = detect_cartesian_joins([stage_exploding], "SELECT * FROM t1 JOIN t2 ON t1.id = t2.id")
        self.assertTrue(is_cartesian)
        self.assertTrue(any("row explosion" in r for r in reasons))

    def test_detect_cartesian_joins_spill_to_disk(self):
        """Tests Cartesian detection via shuffle spilling to persistent disk."""
        stage_spilling = JobStage(
            stage_id=1,
            name="SpillStage",
            records_read=500,
            records_written=500,
            shuffle_output_bytes=1000,
            shuffle_output_bytes_spilled=104_857_600,  # 100MB spilled
            wait_ratio_avg=0.05,
            slot_ms=1000,
        )
        is_cartesian, reasons = detect_cartesian_joins([stage_spilling], "SELECT * FROM t")
        self.assertTrue(is_cartesian)
        self.assertTrue(any("spilled" in r for r in reasons))

    def test_detect_cartesian_joins_syntax(self):
        """Tests Cartesian detection via explicit SQL keywords."""
        stage_normal = JobStage(
            stage_id=0,
            name="Scan",
            records_read=100,
            records_written=100,
            shuffle_output_bytes=100,
            shuffle_output_bytes_spilled=0,
            wait_ratio_avg=0.01,
            slot_ms=100,
        )
        # CROSS JOIN
        is_cartesian, reasons = detect_cartesian_joins([stage_normal], "SELECT * FROM t1 CROSS JOIN t2")
        self.assertTrue(is_cartesian)
        self.assertTrue(any("CROSS JOIN" in r for r in reasons))

        # JOIN ON 1=1
        is_cartesian_tautology, reasons_t = detect_cartesian_joins([stage_normal], "SELECT * FROM t1 JOIN t2 ON 1 = 1")
        self.assertTrue(is_cartesian_tautology)
        self.assertTrue(any("unconditional join" in r for r in reasons_t))

    def test_detect_cartesian_joins_normal(self):
        """Tests normal stage is not falsely flagged as Cartesian."""
        stage_healthy = JobStage(
            stage_id=0,
            name="Scan",
            records_read=100_000,
            records_written=10_000,
            shuffle_output_bytes=100,
            shuffle_output_bytes_spilled=0,
            wait_ratio_avg=0.01,
            slot_ms=100,
        )
        is_cartesian, reasons = detect_cartesian_joins([stage_healthy], "SELECT * FROM t1 WHERE id = 10")
        self.assertFalse(is_cartesian)
        self.assertEqual(len(reasons), 0)

    def test_detect_slot_contention(self):
        """Tests slot contention detection."""
        insights_contention = PerformanceInsights(slot_contention=True)
        is_contended, reasons = detect_slot_contention(insights_contention, [], 1000)
        self.assertTrue(is_contended)
        self.assertTrue(any("slot contention" in r for r in reasons))

        # Contention via stage wait ratio > 0.40 and slot_ms > 60,000
        stage_waiting = JobStage(
            stage_id=0,
            name="QueueStage",
            records_read=100,
            records_written=100,
            shuffle_output_bytes=100,
            shuffle_output_bytes_spilled=0,
            wait_ratio_avg=0.55,
            slot_ms=120_000,
        )
        is_contended_wait, reasons_w = detect_slot_contention(PerformanceInsights(), [stage_waiting], 120_000)
        self.assertTrue(is_contended_wait)
        self.assertTrue(any("waiting for available slots" in r for r in reasons_w))

        # Normal stage
        stage_normal = JobStage(
            stage_id=0,
            name="NormalStage",
            records_read=100,
            records_written=100,
            shuffle_output_bytes=100,
            shuffle_output_bytes_spilled=0,
            wait_ratio_avg=0.05,
            slot_ms=120_000,
        )
        is_normal, reasons_n = detect_slot_contention(PerformanceInsights(), [stage_normal], 120_000)
        self.assertFalse(is_normal)
        self.assertEqual(len(reasons_n), 0)

    def test_detect_unpartitioned_scans(self):
        """Tests unpartitioned scan heuristic."""
        twenty_gb = 20 * 1024 * 1024 * 1024
        unpartitioned_query = "SELECT user_id, action FROM logs_table"
        is_unpart, reasons = detect_unpartitioned_scans(twenty_gb, unpartitioned_query)
        self.assertTrue(is_unpart)
        self.assertTrue(any("without detectable partition filter" in r for r in reasons))

        # Scanned with _PARTITIONDATE filter
        partitioned_query = "SELECT user_id, action FROM logs_table WHERE _PARTITIONDATE = '2026-03-01'"
        is_unpart_pruned, reasons_p = detect_unpartitioned_scans(twenty_gb, partitioned_query)
        self.assertFalse(is_unpart_pruned)
        self.assertEqual(len(reasons_p), 0)

        # Low bytes billed (<10GB) is not flagged even without partition filter
        one_gb = 1024 * 1024 * 1024
        is_low_scanned, _ = detect_unpartitioned_scans(one_gb, unpartitioned_query)
        self.assertFalse(is_low_scanned)

    # --------------------------------------------------------------------------
    # Pipeline & Data Model Parsing Tests
    # --------------------------------------------------------------------------

    def test_parse_job_row(self):
        """Tests parsing a complete job row dictionary into QueryJobMetrics."""
        metrics = parse_job_row(self.sample_healthy_job_dict)
        self.assertEqual(metrics.job_id, "job_sample_healthy")
        self.assertEqual(metrics.project_id, "acme-analytics-prod")
        self.assertEqual(metrics.slot_hours, 1.0)
        self.assertEqual(metrics.estimated_cost_usd_editions, 0.06)
        self.assertEqual(len(metrics.stages), 1)
        self.assertEqual(len(metrics.bottlenecks), 0)

    def test_summarize_analysis(self):
        """Tests aggregation in AnalysisSummary."""
        jobs = [parse_job_row(self.sample_healthy_job_dict), parse_job_row(self.sample_cartesian_job_dict)]
        summary = summarize_analysis(
            jobs=jobs,
            project_id="acme-analytics-prod",
            region="region-us",
            lookback_days=7,
            threshold_slot_hours=0.5,
        )
        self.assertEqual(summary.total_jobs_analyzed, 2)
        self.assertGreater(summary.total_slot_hours_consumed, 0)
        self.assertGreaterEqual(summary.cartesian_job_count, 1)
        self.assertGreaterEqual(len(summary.all_recommendations), 1)

    def test_generate_information_schema_query(self):
        """Tests SQL query template generation."""
        sql = generate_information_schema_query("test-proj", "us", 7, 20)
        self.assertIn("test-proj", sql)
        self.assertIn("region-us", sql)
        self.assertIn("INTERVAL 7 DAY", sql)
        self.assertIn("LIMIT 20", sql)

    # --------------------------------------------------------------------------
    # Output Formatters
    # --------------------------------------------------------------------------

    def test_format_as_ascii_table(self):
        """Tests ASCII table column alignment."""
        headers = ["ColA", "ColB"]
        rows = [["Val1", "LongerVal2"], ["A", "B"]]
        table_str = format_as_ascii_table(headers, rows)
        self.assertIn("ColA", table_str)
        self.assertIn("LongerVal2", table_str)
        self.assertIn("-+-", table_str)

    def test_render_outputs(self):
        """Tests table, JSON, and CSV rendering functions."""
        jobs = [parse_job_row(self.sample_healthy_job_dict), parse_job_row(self.sample_cartesian_job_dict)]
        summary = summarize_analysis(jobs, "acme-test", "region-us", 7)

        # Table output
        table_out = render_table_output(summary)
        self.assertIn("BIGQUERY SLOT & COST OPTIMIZER REPORT", table_out)
        self.assertIn("job_sample_cartesian", table_out)

        # JSON output
        json_out = render_json_output(summary)
        parsed_json = json.loads(json_out)
        self.assertIn("summary", parsed_json)
        self.assertIn("recommendations", parsed_json)
        self.assertIn("top_heavy_jobs", parsed_json)
        self.assertEqual(parsed_json["summary"]["total_queries_analyzed"], 2)

        # CSV output
        csv_out = render_csv_output(summary)
        self.assertIn("job_id,project_id,user_email", csv_out)
        self.assertIn("job_sample_cartesian", csv_out)

    # --------------------------------------------------------------------------
    # Mock Ingestion & End-to-End CLI Tests
    # --------------------------------------------------------------------------

    def test_load_mock_data(self):
        """Tests loading synthetic mock data file."""
        rows = load_mock_data(self.mock_data_path)
        self.assertIsInstance(rows, list)
        self.assertGreaterEqual(len(rows), 4)

    def test_load_mock_data_nonexistent(self):
        """Tests error on nonexistent mock file."""
        with self.assertRaises(FileNotFoundError):
            load_mock_data("nonexistent_path_xyz.json")

    def test_run_analysis_dry_run(self):
        """Tests --dry-run option."""
        parser = create_argument_parser()
        args = parser.parse_args(["--project-id", "dry-proj", "--dry-run"])
        captured_output = io.StringIO()
        with mock.patch("sys.stdout", new=captured_output):
            exit_code = run_analysis(args)
        self.assertEqual(exit_code, 0)
        self.assertIn("DRY-RUN: Regional BigQuery INFORMATION_SCHEMA Query:", captured_output.getvalue())
        self.assertIn("dry-proj", captured_output.getvalue())

    def test_run_analysis_with_mock_data(self):
        """Tests full CLI pipeline using mock data file."""
        parser = create_argument_parser()
        args = parser.parse_args(["--mock-data-file", self.mock_data_path, "--format", "json"])
        captured_output = io.StringIO()
        with mock.patch("sys.stdout", new=captured_output):
            exit_code = run_analysis(args)
        self.assertEqual(exit_code, 0)
        payload = json.loads(captured_output.getvalue())
        self.assertGreaterEqual(payload["summary"]["total_queries_analyzed"], 4)
        self.assertGreater(len(payload["recommendations"]), 0)

    def test_run_analysis_output_file(self):
        """Tests writing results to --output-file."""
        with tempfile.NamedTemporaryFile(mode="w", delete=False) as tmp:
            tmp_path = tmp.name
        try:
            parser = create_argument_parser()
            args = parser.parse_args(["--mock-data-file", self.mock_data_path, "--output-file", tmp_path])
            exit_code = run_analysis(args)
            self.assertEqual(exit_code, 0)
            self.assertTrue(os.path.exists(tmp_path))
            with open(tmp_path, "r", encoding="utf-8") as f:
                content = f.read()
            self.assertIn("BIGQUERY SLOT & COST OPTIMIZER REPORT", content)
        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)

    def test_run_analysis_invalid_days(self):
        """Tests validation error on invalid days argument."""
        parser = create_argument_parser()
        args = parser.parse_args(["--days", "0"])
        self.assertEqual(run_analysis(args), 2)

        args_too_high = parser.parse_args(["--days", "35"])
        self.assertEqual(run_analysis(args_too_high), 2)

    # --------------------------------------------------------------------------
    # Live Client Mocking & Error Handling Tests
    # --------------------------------------------------------------------------

    def test_fetch_bigquery_jobs_mocked(self):
        """Tests fetch_bigquery_jobs with mocked BigQuery client."""
        mock_row = mock.MagicMock()
        mock_row.items.return_value = [("job_id", "mock_job_1"), ("total_slot_ms", 5000)]

        mock_client_instance = mock.MagicMock()
        mock_query_job = mock.MagicMock()
        mock_query_job.result.return_value = [mock_row]
        mock_client_instance.query.return_value = mock_query_job

        with mock.patch("google.cloud.bigquery.Client", return_value=mock_client_instance):
            jobs = fetch_bigquery_jobs("acme-test", "region-us", 7, 10)
            self.assertEqual(len(jobs), 1)
            self.assertEqual(jobs[0]["job_id"], "mock_job_1")

    def test_error_handling_missing_adc(self):
        """Tests exit code 2 when Application Default Credentials are missing."""
        with mock.patch("google.cloud.bigquery.Client", side_effect=DefaultCredentialsError("No ADC")):
            with self.assertRaises(SystemExit) as cm:
                fetch_bigquery_jobs("acme-test", "region-us", 7, 10)
            self.assertEqual(cm.exception.code, 2)

    def test_error_handling_forbidden_iam(self):
        """Tests exit code 3 when caller lacks IAM permissions."""
        with mock.patch("google.cloud.bigquery.Client", side_effect=Forbidden("Access Denied")):
            with self.assertRaises(SystemExit) as cm:
                fetch_bigquery_jobs("acme-test", "region-us", 7, 10)
            self.assertEqual(cm.exception.code, 3)


if __name__ == "__main__":
    unittest.main()
