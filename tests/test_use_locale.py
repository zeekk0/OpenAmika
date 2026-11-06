"""Offline Use page localization contracts and actual JS rendering checks."""
import re
import shutil
import subprocess
from html.parser import HTMLParser
from pathlib import Path

import pytest


def test_use_locale():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is required for Use localization tests")
    result = subprocess.run(
        [node, "--test", "tests/use_locale.test.js"],
        cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_use_static_copy_is_explicitly_localized():
    """New visible copy must be tagged, not caught by arbitrary DOM replacement."""
    dynamic_ids = {
        "powerState", "powerDetail", "statCostAmikaSub", "statCostAgentsSub",
        "statCacheSub",
    }
    brands = {"Amika", "MekaHime"}
    void = {"meta", "link", "input", "img", "br", "hr", "source"}

    class CopyParser(HTMLParser):
        def __init__(self):
            super().__init__()
            self.stack = []
            self.missing = []

        def handle_starttag(self, tag, attrs):
            attrs = dict(attrs)
            if tag in {"input", "select", "textarea"}:
                assert not any("data-i18n" in parent for _, parent in self.stack), (
                    "Translation must never replace an ancestor of an editable control"
                )
            if tag not in void:
                self.stack.append((tag, attrs))

        def handle_endtag(self, tag):
            for index in range(len(self.stack) - 1, -1, -1):
                if self.stack[index][0] == tag:
                    del self.stack[index:]
                    break

        def handle_data(self, data):
            text = data.strip()
            if not text or text in brands or not re.search(r"[A-Za-z가-힣一-龥]", text):
                return
            if any(tag in {"script", "style"} for tag, _ in self.stack):
                return
            if any("data-i18n" in attrs or attrs.get("id") in dynamic_ids for _, attrs in self.stack):
                return
            if re.fullmatch(r"\d+px", text):
                return
            self.missing.append(text)

    parser = CopyParser()
    parser.feed((Path(__file__).resolve().parents[1] / "ui/use.html").read_text())
    assert not parser.missing, parser.missing
