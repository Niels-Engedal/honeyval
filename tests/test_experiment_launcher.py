"""Dry-run checks for the interactive NLP experiment launcher (no Docker/API)."""

import os
from pathlib import Path
import subprocess
import unittest


ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = ROOT / "scripts/nlp/experiment.sh"

# The thirteen answers in the order manual setup requests them.
DEFAULT_ANSWERS = [
    "nlp-launcher-unit-test",
    "all",
    "openai/gpt-6-luna-python-curl",
    "openai/gpt-6-luna",
    "exploit",
    "mislead vulnerable",
    "10",
    "20",
    "4",
    "medium",
    "medium",
    "5",
    "2",
]


def dry_run(**overrides):
    names = [
        "name", "apps", "attacker", "defender", "pentest",
        "defender_conditions", "samples", "steps", "workers", "attacker_effort",
        "defender_effort", "attacker_limit", "defender_limit",
    ]
    answers = dict(zip(names, DEFAULT_ANSWERS))
    answers.update(overrides)
    env = os.environ.copy()
    env["HONEYVAL_DRY_RUN"] = "1"
    return subprocess.run(
        ["bash", str(LAUNCHER), "manual"],
        cwd=ROOT,
        input="\n".join(answers[k] for k in names) + "\n",
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )


class ExperimentLauncherTests(unittest.TestCase):
    def test_all_apps_both_conditions_are_separate_runs(self):
        result = dry_run()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("up to 320 trajectories total", result.stdout)
        self.assertEqual(result.stdout.count("DRY RUN: nothing started."), 2)
        self.assertIn("--benchmark_apps all", result.stdout)
        self.assertIn("Parallel workers per condition: 4", result.stdout)
        self.assertEqual(result.stdout.count("--max_workers 4"), 2)
        self.assertIn("--honeypot_additional_instructions mislead", result.stdout)
        self.assertIn("--honeypot_additional_instructions vulnerable", result.stdout)
        self.assertIn("attacker USD 5 and defender USD 2", result.stdout)

    def test_explicit_apps_and_comma_conditions(self):
        result = dry_run(apps="Login Wiki", defender_conditions="mislead,vulnerable", samples="2")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("up to 8 trajectories total", result.stdout)
        self.assertEqual(result.stdout.count("DRY RUN: nothing started."), 2)
        self.assertIn("--benchmark_apps Login Wiki", result.stdout)

    def test_single_condition_still_supported(self):
        result = dry_run(apps="Login", defender_conditions="mislead", samples="1")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("up to 1 trajectories total", result.stdout)
        self.assertEqual(result.stdout.count("DRY RUN: nothing started."), 1)

    def test_workers_can_be_one(self):
        result = dry_run(apps="Login", defender_conditions="mislead", workers="1")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("--max_workers 1", result.stdout)

    def test_invalid_workers_rejected(self):
        for workers in ("0", "-1", "four", "1.5"):
            with self.subTest(workers=workers):
                result = dry_run(workers=workers)
                self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
                self.assertIn("Samples, steps and workers must be positive integers", result.stderr)
                self.assertNotIn("DRY RUN: nothing started.", result.stdout)

    def test_duplicate_condition_rejected(self):
        result = dry_run(defender_conditions="mislead mislead")
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn("Duplicate defender instruction type", result.stderr)
        self.assertNotIn("DRY RUN: nothing started.", result.stdout)

    def test_all_must_stand_alone(self):
        result = dry_run(apps="all Wiki")
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn("'all' must be entered alone", result.stderr)


if __name__ == "__main__":
    unittest.main()
