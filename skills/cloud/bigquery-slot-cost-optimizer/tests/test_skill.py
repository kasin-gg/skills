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

"""Skill validation tests for BigQuery Slot & Cost Optimizer Agent Skill."""

import os
import re
import unittest
import yaml

from scripts.slot_analyzer import create_argument_parser


SKILL_DIR = os.path.dirname(os.path.dirname(__file__))
SKILL_MD_PATH = os.path.join(SKILL_DIR, "SKILL.md")
OPTIMIZATION_RULES_PATH = os.path.join(SKILL_DIR, "references", "optimization_rules.md")


class TestSkillPackage(unittest.TestCase):
    """Test suite validating SKILL.md specification and repository compliance."""

    def test_skill_frontmatter_validity(self):
        """Validates that SKILL.md has valid YAML frontmatter conforming to Google Skill standards."""
        self.assertTrue(os.path.exists(SKILL_MD_PATH), f"SKILL.md not found at {SKILL_MD_PATH}")

        with open(SKILL_MD_PATH, "r", encoding="utf-8") as f:
            content = f.read()

        # Frontmatter must be enclosed in --- markers
        match = re.match(r"^---\n(.*?)\n---", content, re.DOTALL)
        self.assertIsNotNone(match, "SKILL.md missing valid YAML frontmatter delimiters (---)")

        frontmatter_yaml = match.group(1)
        data = yaml.safe_load(frontmatter_yaml)

        self.assertIsInstance(data, dict, "Frontmatter must parse into a dictionary")
        self.assertIn("name", data, "Frontmatter missing mandatory 'name' attribute")
        self.assertEqual(data["name"], "bigquery-slot-cost-optimizer", f"Unexpected skill name: {data['name']}")
        self.assertIn("description", data, "Frontmatter missing mandatory 'description' attribute")
        self.assertLessEqual(len(data["description"]), 1024, "Description exceeds 1024 characters limit")
        self.assertEqual(data.get("license"), "Apache-2.0", "License must be Apache-2.0")

    def test_skill_markdown_structure(self):
        """Validates line count and mandatory procedural sections in SKILL.md."""
        with open(SKILL_MD_PATH, "r", encoding="utf-8") as f:
            lines = f.readlines()

        line_count = len(lines)
        self.assertLess(line_count, 500, f"SKILL.md is {line_count} lines; must be under 500 lines to preserve token context")

        full_text = "".join(lines)
        self.assertIn("Trigger Conditions", full_text)
        self.assertIn("Diagnostic Execution Workflow", full_text)
        self.assertIn("Remediation Playbooks", full_text)
        self.assertIn("Verification & Validation Protocol", full_text)

    def test_references_optimization_rules_structure(self):
        """Verifies that references/optimization_rules.md covers all core architectural pillars."""
        self.assertTrue(os.path.exists(OPTIMIZATION_RULES_PATH), "optimization_rules.md not found")

        with open(OPTIMIZATION_RULES_PATH, "r", encoding="utf-8") as f:
            content = f.read()

        mandatory_pillars = [
            "Partitioning Optimization",
            "Clustering Optimization",
            "BI Engine In-Memory Acceleration",
            "BigQuery Search Indexes",
            "Materialized Views",
            "Join Optimization",
        ]

        for pillar in mandatory_pillars:
            self.assertIn(pillar, content, f"Missing architectural pillar in optimization_rules.md: {pillar}")

    def test_cli_flags_documented_in_skill(self):
        """Verifies that all CLI flags documented in SKILL.md exist in slot_analyzer.py."""
        parser = create_argument_parser()
        valid_flags = set(parser._option_string_actions.keys())

        with open(SKILL_MD_PATH, "r", encoding="utf-8") as f:
            content = f.read()

        documented_flags = [
            "--project-id",
            "--region",
            "--days",
            "--mode",
            "--limit",
            "--format",
            "--threshold-slot-hours",
            "--dry-run",
            "--mock-data-file",
            "--output-file",
        ]

        for flag in documented_flags:
            self.assertIn(flag, valid_flags, f"Documented flag {flag} not supported by slot_analyzer.py parser")

    def test_nda_safe_harbor_sanitization(self):
        """Verifies zero proprietary identifiers exist in source code, docs, or test data."""
        forbidden_patterns = [
            re.compile(r"\bcorp\.google\.com\b", re.IGNORECASE),
            re.compile(r"\bb/[0-9]{7,}\b"),  # Internal buganizer format
            re.compile(r"\bcitc\b", re.IGNORECASE),
            re.compile(r"/google/src/"),
        ]

        files_to_check = [
            SKILL_MD_PATH,
            OPTIMIZATION_RULES_PATH,
            os.path.join(SKILL_DIR, "scripts", "slot_analyzer.py"),
            os.path.join(SKILL_DIR, "tests", "mock_data.json"),
            os.path.join(SKILL_DIR, "tests", "conftest.py"),
        ]

        for file_path in files_to_check:
            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read()
            for pattern in forbidden_patterns:
                matches = pattern.findall(content)
                self.assertFalse(matches, f"Proprietary identifier match '{matches}' found in {file_path}")


if __name__ == "__main__":
    unittest.main()
