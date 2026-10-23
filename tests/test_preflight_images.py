"""Docker-image preflight tests; no Docker daemon or network calls required."""

import importlib.util
import subprocess
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "honeyval_image_preflight", ROOT / "scripts/nlp/preflight_images.py"
)
preflight = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(preflight)


def ok(*args):
    return subprocess.CompletedProcess(args, 0, stdout="", stderr="")


def failed(*args):
    return subprocess.CompletedProcess(args, 1, stdout="", stderr="No such image")


class PreflightImageTests(unittest.TestCase):
    def test_images_match_canonical_honeyval_definitions(self):
        images = preflight.image_definitions()
        self.assertEqual(
            [tag for tag, _ in images],
            ["fastapi-webapp-base", "sandbox"],
        )
        self.assertIn("pip install fastapi uvicorn httpx", images[0][1])
        self.assertIn("apk add curl bash", images[1][1])
        self.assertIn("pip3 install requests", images[1][1])

    @mock.patch.object(preflight.subprocess, "run")
    def test_existing_images_skip_all_builds(self, run):
        run.return_value = ok()
        preflight.ensure_images()
        self.assertEqual(run.call_count, 3)
        self.assertFalse(
            any("build" in call.args[0] for call in run.call_args_list)
        )

    @mock.patch.object(preflight.subprocess, "run")
    def test_missing_images_built_once_from_canonical_dockerfiles(self, run):
        run.side_effect = [ok(), failed(), ok(), ok(), failed(), ok(), ok()]
        preflight.ensure_images()
        builds = [
            call for call in run.call_args_list
            if call.args[0][:2] == ["docker", "build"]
        ]
        self.assertEqual(len(builds), 2)
        canonical = dict(preflight.image_definitions())
        for call in builds:
            args = call.args[0]
            self.assertEqual(args[2], "--network=host")
            self.assertEqual(args[-1], "-")
            self.assertEqual(call.kwargs["input"], canonical[args[4]])

    @mock.patch.object(preflight.subprocess, "run")
    def test_build_failure_aborts_before_second_image(self, run):
        run.side_effect = [ok(), failed(), failed()]
        with self.assertRaisesRegex(RuntimeError, "No experiment workers"):
            preflight.ensure_images()
        self.assertEqual(run.call_count, 3)

    @mock.patch.object(preflight.subprocess, "run")
    def test_docker_permission_error_is_reported(self, run):
        run.return_value = subprocess.CompletedProcess(
            [], 1, stdout="", stderr="permission denied"
        )
        with self.assertRaisesRegex(RuntimeError, "permission denied"):
            preflight.ensure_images()
        self.assertEqual(run.call_count, 1)


if __name__ == "__main__":
    unittest.main()
