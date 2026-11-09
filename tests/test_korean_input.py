"""Run production UI input-handler tests without browsers, packages, or a server."""
import shutil
import subprocess
from pathlib import Path

import pytest


def test_korean_input_handlers():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is required for the synthetic UI input-handler tests")
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [node, "--test", "tests/korean_input.test.js"],
        cwd=root, capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
