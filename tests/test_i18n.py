"""Run the real localization modules in an offline Node DOM harness."""
import shutil
import subprocess
from pathlib import Path

import pytest


def test_i18n_production_modules():
    node = shutil.which("node")
    if not node:
        pytest.fail("Node is required to verify the localization production modules")
    result = subprocess.run(
        [node, "--test", "tests/i18n.test.js"],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
