<!--
Copyright 2026 Google LLC

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
-->

# BigQuery Slot & Cost Optimizer Agent Skill

A production-grade Google Agent Skill and FinOps diagnostic utility that enables AI agents and data engineers to analyze BigQuery slot consumption, compute costs, and execution bottlenecks using `INFORMATION_SCHEMA`.

## Key Capabilities

1. **Telemetry Mining**: Extracts top compute-intensive queries from `INFORMATION_SCHEMA.JOBS_BY_PROJECT` or regional views.
2. **Bottleneck Detection**:
   - **Slot Contention**: Identifies starved query stages where wait ratios exceed 40% or performance insights flag slot saturation.
   - **Cartesian Explosions**: Detects join blowups where output rows exponentially exceed input rows or shuffle spills to disk.
   - **Unpartitioned Scans**: Pinpoints high-cost scans (>10 GB) scanning unpartitioned datasets without date or partition filtering.
3. **Dual Cost Modeling**:
   - On-Demand ($6.25 per TB scanned).
   - Enterprise Edition equivalence ($0.06 per slot-hour).
4. **Structured Remediation**: Provides actionable recommendations mapped to concrete architectural heuristics in `references/optimization_rules.md`.
5. **Offline Mock Pipeline**: Full testing and verification capability without live GCP credentials via `--mock-data-file`.

## Quick Start

### Installation

```bash
pip install -r requirements.txt
```

### Usage

```bash
# Analyze slot consumption across the last 7 days
python3 scripts/slot_analyzer.py --project acme-analytics-prod --days 7 --format table

# Output structured JSON for automation or agent integration
python3 scripts/slot_analyzer.py --project acme-analytics-prod --days 7 --format json

# Run offline diagnostic with synthetic telemetry
python3 scripts/slot_analyzer.py --mock-data-file tests/mock_data.json --format table

# Dry-run query inspection (prints regional INFORMATION_SCHEMA SQL without execution)
python3 scripts/slot_analyzer.py --project acme-analytics-prod --region region-us --dry-run
```

## Repository Structure

```
targets/01_google_skills_bigquery_optimizer/
├── LICENSE                         # Apache 2.0 full text license
├── README.md                        # User and agent orientation guide
├── pyproject.toml                   # Packaging and test configuration
├── requirements.txt                 # Runtime and test dependencies
├── SKILL.md                         # Agent skill definition with YAML frontmatter
├── scripts/
│   ├── __init__.py                  # Package marker
│   └── slot_analyzer.py             # Main CLI slot and cost analysis utility
├── references/
│   ├── __init__.py                  # Package marker
│   └── optimization_rules.md        # Deep-dive optimization heuristics
└── tests/
    ├── __init__.py                  # Package marker
    ├── conftest.py                  # Pytest fixtures and mock BigQuery data
    ├── mock_data.json               # De-identified synthetic telemetry dataset
    ├── test_slot_analyzer.py        # Unit tests for CLI, math, and heuristics
    └── test_skill.py                # Skill validation and structural tests
```

## Running Tests

```bash
pytest tests/ -v
```

## License

Apache License, Version 2.0. See [LICENSE](LICENSE) for details.
