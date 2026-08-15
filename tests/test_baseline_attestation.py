from __future__ import annotations

import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from krcn_core.baseline_attestation import (  # noqa: E402
    ATTESTED_BASELINES,
    CLI_BASELINE_REF,
    COVERAGE_BASELINE_REF,
    commits_match,
    main,
    normalize_commit,
    resolve_baseline_attestations,
    validate_baseline_attestation,
    validate_coverage_threshold,
)
from krcn_core.doctor import run_doctor  # noqa: E402


def _write_repo(root: Path, coverage: dict, cli: dict) -> None:
    (root / ".ai").mkdir(parents=True, exist_ok=True)
    (root / ".ai" / "coverage-baseline.json").write_text(
        json.dumps(coverage, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (root / ".ai" / "cli-baseline.json").write_text(
        json.dumps(cli, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


class BaselineAttestationTests(unittest.TestCase):
    def test_versioned_baselines_name_their_measurement_commit(self) -> None:
        attestations, errors = resolve_baseline_attestations(REPO_ROOT)
        self.assertEqual([], errors)
        self.assertEqual(
            set(ATTESTED_BASELINES),
            {item.baseline_ref for item in attestations},
        )
        for attestation in attestations:
            self.assertIsNone(attestation.matches_requested_commit)

    def test_normalize_commit_rejects_unusable_values(self) -> None:
        self.assertEqual("2e4d23a", normalize_commit("2E4D23A"))
        self.assertIsNone(normalize_commit(""))
        self.assertIsNone(normalize_commit("main"))
        self.assertIsNone(normalize_commit("2e4d23"))
        self.assertIsNone(normalize_commit(None))

    def test_short_and_full_commits_compare_by_shared_prefix(self) -> None:
        self.assertTrue(commits_match("2e4d23a", "2e4d23a9b5d65644e64c9177317364e6"))
        self.assertFalse(commits_match("2e4d23a", "b383e2f"))

    def test_missing_source_commit_is_reported(self) -> None:
        errors = validate_baseline_attestation({"schema_version": 1}, CLI_BASELINE_REF)
        self.assertEqual([f"{CLI_BASELINE_REF} source_commit is missing or invalid"], errors)

    def test_coverage_below_minimum_is_reported(self) -> None:
        errors = validate_coverage_threshold(
            {"line_coverage_percent": 41.0, "minimum_line_coverage_percent": 60.0}
        )
        self.assertEqual(
            [f"{COVERAGE_BASELINE_REF} coverage is below the recorded minimum"], errors
        )

    def test_requested_commit_marks_a_stale_baseline(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _write_repo(
                root,
                {
                    "source_commit": "b383e2f",
                    "line_coverage_percent": 64.0,
                    "minimum_line_coverage_percent": 60.0,
                },
                {"source_commit": "abc1234"},
            )
            attestations, errors = resolve_baseline_attestations(root, "abc1234")
        self.assertEqual([], errors)
        by_ref = {item.baseline_ref: item for item in attestations}
        self.assertFalse(by_ref[COVERAGE_BASELINE_REF].matches_requested_commit)
        self.assertTrue(by_ref[CLI_BASELINE_REF].matches_requested_commit)

    def test_stale_baseline_only_fails_when_current_is_required(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _write_repo(
                root,
                {
                    "source_commit": "b383e2f",
                    "line_coverage_percent": 64.0,
                    "minimum_line_coverage_percent": 60.0,
                },
                {"source_commit": "b383e2f"},
            )
            output = io.StringIO()
            with redirect_stdout(output):
                reported = main(["--repo", str(root), "--commit", "abc1234"])
            error = io.StringIO()
            with redirect_stdout(io.StringIO()), redirect_stderr(error):
                required = main(
                    ["--repo", str(root), "--commit", "abc1234", "--require-current"]
                )
        self.assertEqual(0, reported)
        self.assertIn("measured on an earlier commit", output.getvalue())
        self.assertEqual(1, required)
        self.assertIn("b383e2f", error.getvalue())

    def test_invalid_baseline_fails_verification(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _write_repo(
                root,
                {
                    "line_coverage_percent": 64.0,
                    "minimum_line_coverage_percent": 60.0,
                },
                {"source_commit": "abc1234"},
            )
            error = io.StringIO()
            with redirect_stdout(io.StringIO()), redirect_stderr(error):
                result = main(["--repo", str(root)])
        self.assertEqual(1, result)
        self.assertIn("source_commit is missing or invalid", error.getvalue())

    def test_json_output_lists_stale_baselines(self) -> None:
        output = io.StringIO()
        with redirect_stdout(output):
            result = main(["--repo", str(REPO_ROOT), "--format", "json"])
        payload = json.loads(output.getvalue())
        self.assertEqual(0, result)
        self.assertIsNone(payload["requested_commit"])
        self.assertEqual([], payload["stale_baselines"])
        self.assertEqual(len(ATTESTED_BASELINES), len(payload["baselines"]))

    def test_doctor_reports_baseline_attestation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            checks = run_doctor(REPO_ROOT, Path(directory))
        by_id = {item.check_id: item for item in checks}
        self.assertTrue(by_id["baseline-attestation"].passed)


class RequiredQualityGateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.workflow = (REPO_ROOT / ".github" / "workflows" / "quality.yml").read_text(
            encoding="utf-8"
        )

    def test_pull_requests_and_branch_pushes_run_the_required_gate(self) -> None:
        self.assertIn("pull_request:", self.workflow)
        self.assertIn("push:", self.workflow)
        self.assertIn("workflow_dispatch:", self.workflow)
        self.assertIn("fast-gate:", self.workflow)

    def test_full_matrix_stays_on_demand(self) -> None:
        self.assertIn("cross-platform:", self.workflow)
        self.assertIn("github.event_name == 'workflow_dispatch'", self.workflow)
        self.assertIn("refs/tags/", self.workflow)

    def test_coverage_job_reports_the_measured_commit(self) -> None:
        self.assertIn("measure_coverage.py --minimum 60", self.workflow)
        self.assertIn("verify_baseline_attestation.py", self.workflow)
        self.assertTrue((REPO_ROOT / "tools" / "verify_baseline_attestation.py").is_file())


if __name__ == "__main__":
    unittest.main()
