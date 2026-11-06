"""Setup localization contracts, runnable without services or browser packages."""
from html.parser import HTMLParser
from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]


class SetupMarkup(HTMLParser):
    def __init__(self):
        super().__init__()
        self.stack = []
        self.nodes = []
        self.untagged = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        self.nodes.append((tag, attrs))
        if tag not in {"meta", "link", "input", "br", "hr"}:
            self.stack.append((tag, attrs))

    def handle_endtag(self, tag):
        if self.stack:
            assert self.stack[-1][0] == tag, (self.stack[-1][0], tag)
            self.stack.pop()

    def handle_data(self, data):
        text = data.strip()
        if not text or not self.stack:
            return
        if any(tag in {"script", "code"} or "data-i18n" in attrs for tag, attrs in self.stack):
            return
        if text in {"OpenRouter", "Ollama", "Discord", "Telegram", "@BotFather", "ollama.com", "—"}:
            return
        self.untagged.append(text)


def markup():
    parser = SetupMarkup()
    parser.feed((ROOT / "ui/setup.html").read_text())
    return parser


def test_setup_static_text_has_explicit_translation_tags():
    page = markup()
    assert not page.stack
    assert not page.untagged
    ids = [attrs["id"] for _, attrs in page.nodes if "id" in attrs]
    assert len(ids) == len(set(ids)), "duplicate control IDs"


def test_setup_controls_have_localized_accessible_labels():
    page = markup()
    labels = {attrs["for"] for tag, attrs in page.nodes if tag == "label" and "for" in attrs}
    wrapped_switches = {"vmapEnabled", "msgDiscordOn", "msgTelegramOn"}
    for tag, attrs in page.nodes:
        if tag not in {"input", "select", "textarea"}:
            continue
        assert attrs["id"] in labels | wrapped_switches or "data-i18n-aria-label" in attrs, attrs
    confirmations = {attrs["id"]: attrs for _, attrs in page.nodes if attrs.get("id") in {"wipeConfirm", "resetConfirm"}}
    assert confirmations["wipeConfirm"]["placeholder"] == "WIPE"
    assert confirmations["resetConfirm"]["placeholder"] == "RESET"
    assert not any("data-i18n" in attrs for tag, attrs in page.nodes if tag in {"input", "select", "textarea"})


def test_setup_locale_node_suite():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is required for frontend behavioral tests")
    result = subprocess.run([node, "--test", "tests/setup_locale.test.js"], cwd=ROOT, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
