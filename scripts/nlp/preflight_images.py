#!/usr/bin/env python3
"""Prebuild the Docker images used by Honeyval's LLM HTTP-app research runs.

Read the Dockerfile definitions from Honeyval's existing constants.py so this
preflight cannot silently drift from the images used by the benchmark. Run
before starting parallel workers; a failed build aborts the entire batch.
Requires only Python's standard library, Docker CLI and a running Docker daemon.
"""

from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CONSTANTS = ROOT / "src/utils/constants.py"
REQUIRED = ("FRONT_WEBAPP_DOCKERFILE", "SANDBOX_DOCKERFILE")


def image_definitions(source: Path = CONSTANTS) -> list[tuple[str, str]]:
    """Extract literal (Dockerfile, image-tag) tuples without importing Honeyval."""
    tree = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
    found: dict[str, tuple[str, str]] = {}
    for statement in tree.body:
        if not isinstance(statement, ast.Assign):
            continue
        for target in statement.targets:
            if isinstance(target, ast.Name) and target.id in REQUIRED:
                definition = ast.literal_eval(statement.value)
                if (
                    not isinstance(definition, tuple)
                    or len(definition) != 2
                    or not all(isinstance(value, str) and value for value in definition)
                ):
                    raise ValueError(f"Invalid {target.id} definition in {source}")
                found[target.id] = definition
    missing = set(REQUIRED) - set(found)
    if missing:
        raise ValueError(f"Missing Docker image definitions: {sorted(missing)}")
    return [(found[name][1], found[name][0]) for name in REQUIRED]


def ensure_images() -> None:
    daemon = subprocess.run(
        ["docker", "info", "--format", "{{.ServerVersion}}"],
        text=True,
        capture_output=True,
        check=False,
    )
    if daemon.returncode:
        raise RuntimeError(
            "Cannot access the Docker daemon. Reconnect after Docker-group setup "
            "or use 'newgrp docker'. Details: " + daemon.stderr.strip()
        )

    for tag, dockerfile in image_definitions():
        existing = subprocess.run(
            ["docker", "image", "inspect", tag],
            text=True,
            capture_output=True,
            check=False,
        )
        if existing.returncode == 0:
            print(f"[Honeyval preflight] Image '{tag}' already exists.", flush=True)
            continue

        print(
            f"[Honeyval preflight] Building missing image '{tag}' "
            "once (Docker build --network=host).",
            flush=True,
        )
        result = subprocess.run(
            ["docker", "build", "--network=host", "--tag", tag, "-"],
            input=dockerfile,
            text=True,
            check=False,
        )
        if result.returncode:
            raise RuntimeError(
                f"Docker build for '{tag}' failed (exit {result.returncode}). "
                "No experiment workers will be started. "
                "Inspect the build output above, including any PyPI/Alpine errors."
            )

        verify = subprocess.run(
            ["docker", "image", "inspect", tag],
            text=True,
            capture_output=True,
            check=False,
        )
        if verify.returncode:
            raise RuntimeError(f"Image '{tag}' was not found after a successful build.")

    print("[Honeyval preflight] Required HTTP-honeypot images are ready.", flush=True)


if __name__ == "__main__":
    try:
        ensure_images()
    except (OSError, RuntimeError, ValueError, SyntaxError) as error:
        print(f"[Honeyval preflight] ERROR: {error}", file=sys.stderr)
        sys.exit(1)
