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
# The rule-based honeypot serves the real app in the BaxBench image.
RULE_BASED = ("FASTAPI_BAXBENCH_DOCKERFILE",)

# NLP RESEARCH EXTENSION: the BaxBench image is based on Debian bullseye, whose
# security updates moved from deb.debian.org to archive.debian.org after its end
# of life (August 2026); upstream's `apt-get install sqlite3` then fails with a
# 404. Point apt at the archive before upstream's steps. Same packages and
# versions; the Dockerfile is otherwise unchanged.
BULLSEYE_ARCHIVE_FIX = (
    "RUN sed -i 's|deb.debian.org/debian-security|archive.debian.org/debian-security|' "
    "/etc/apt/sources.list "
    "&& echo 'Acquire::Check-Valid-Until \"false\";' > /etc/apt/apt.conf.d/99archive\n"
)


def patch_dockerfile(name: str, dockerfile: str) -> str:
    if name != "FASTAPI_BAXBENCH_DOCKERFILE":
        return dockerfile
    if "WORKDIR /app\n" not in dockerfile:
        raise ValueError("BaxBench Dockerfile changed upstream; review the bullseye archive fix")
    return dockerfile.replace("WORKDIR /app\n", "WORKDIR /app\n" + BULLSEYE_ARCHIVE_FIX, 1)


def image_definitions(
    source: Path = CONSTANTS, names: tuple[str, ...] = REQUIRED
) -> list[tuple[str, str]]:
    """Extract literal (Dockerfile, image-tag) tuples without importing Honeyval."""
    tree = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
    found: dict[str, tuple[str, str]] = {}
    for statement in tree.body:
        if not isinstance(statement, ast.Assign):
            continue
        for target in statement.targets:
            if isinstance(target, ast.Name) and target.id in names:
                definition = ast.literal_eval(statement.value)
                if (
                    not isinstance(definition, tuple)
                    or len(definition) != 2
                    or not all(isinstance(value, str) and value for value in definition)
                ):
                    raise ValueError(f"Invalid {target.id} definition in {source}")
                found[target.id] = definition
    missing = set(names) - set(found)
    if missing:
        raise ValueError(f"Missing Docker image definitions: {sorted(missing)}")
    return [(found[name][1], patch_dockerfile(name, found[name][0])) for name in names]


def ensure_images(rule_based: bool = False) -> None:
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

    names = REQUIRED + (RULE_BASED if rule_based else ())
    for tag, dockerfile in image_definitions(names=names):
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
        ensure_images(rule_based="--rule-based" in sys.argv[1:])
    except (OSError, RuntimeError, ValueError, SyntaxError) as error:
        print(f"[Honeyval preflight] ERROR: {error}", file=sys.stderr)
        sys.exit(1)
