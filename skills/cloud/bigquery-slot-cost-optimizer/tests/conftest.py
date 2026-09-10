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

"""Pytest fixtures and mock telemetry generator for BigQuery Slot Optimizer."""

from datetime import datetime, timezone
import os
import pytest
from typing import Any, Dict, List

from scripts.slot_analyzer import JobStage, PerformanceInsights, QueryJobMetrics


@pytest.fixture
def mock_data_file_path() -> str:
    """Returns the absolute path to tests/mock_data.json."""
    return os.path.join(os.path.dirname(__file__), "mock_data.json")


@pytest.fixture
def sample_healthy_job_dict() -> Dict[str, Any]:
    """Provides a synthetic dictionary representing a healthy query job."""
    return {
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


@pytest.fixture
def sample_cartesian_job_dict() -> Dict[str, Any]:
    """Provides a synthetic dictionary representing a query with Cartesian explosion."""
    return {
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


@pytest.fixture
def sample_contention_job_dict() -> Dict[str, Any]:
    """Provides a synthetic dictionary representing a query experiencing slot contention."""
    return {
        "project_id": "acme-analytics-prod",
        "job_id": "job_sample_contention",
        "user_email": "pipeline@example.com",
        "start_time": "2026-03-01T14:00:00Z",
        "end_time": "2026-03-01T14:20:00Z",
        "query": "SELECT count(*) FROM big_table GROUP BY category",
        "total_slot_ms": 180000000,
        "total_bytes_processed": 10737418240,
        "total_bytes_billed": 10737418240,
        "cache_hit": False,
        "referenced_tables": [],
        "job_stages": [
            {
                "stage_id": 0,
                "name": "Contended Stage",
                "records_read": 5000000,
                "records_written": 5000000,
                "shuffle_output_bytes": 50000000,
                "shuffle_output_bytes_spilled": 0,
                "wait_ratio_avg": 0.58,
                "slot_ms": 180000000,
            }
        ],
        "performance_insights": {
            "stage_performance_standalone_insights": [
                {
                    "stage_id": 0,
                    "slot_contention": True,
                    "insufficient_shuffle_quota": False,
                }
            ]
        },
    }
