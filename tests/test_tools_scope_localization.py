"""Offline coverage for the Tools/About/Flow locale contract."""
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("page,path", [("tools", "ui/tools.html"), ("about", "ui/about.html"), ("flow", "speech/static/flow.html")])
def test_tools_scope_catalog_and_script_coverage(page, path):
    html = (ROOT / path).read_text("utf-8")
    scripts = ["/ui/i18n.js", "/ui/locales/common.js", f"/ui/locales/{page}.js", "/ui/common.js"]
    positions = [html.index(f'src="{script}"') for script in scripts]
    assert positions == sorted(positions)
    node = shutil.which("node")
    assert node, "Node is required for locale catalog validation"
    script = "const fs=require('fs'),vm=require('vm');let catalog;vm.runInNewContext(fs.readFileSync(process.argv[1],'utf8'),{window:{OAI18n:{register:c=>catalog=c}}});console.log(JSON.stringify(catalog));"
    catalog = json.loads(subprocess.check_output([node, "-e", script, str(ROOT / f"ui/locales/{page}.js")], text=True))
    assert catalog["en"].keys() == catalog["ko"].keys()
    assert len(catalog["en"]) > 10
    for key, english in catalog["en"].items():
        assert key.startswith(page + ".")
        assert catalog["ko"][key]
        assert sorted(re.findall(r"\{\w+\}", english)) == sorted(re.findall(r"\{\w+\}", catalog["ko"][key]))
    sources = html + ((ROOT / f"ui/{page}.js").read_text("utf-8") if page != "flow" else "")
    keys = re.findall(r'data-i18n(?:-title|-placeholder|-aria-label|-alt)?="(' + page + r'\.[^"]+)"', sources)
    keys += re.findall(r'\bt\("(' + page + r'\.[^"]+)"\s*[,)]', sources)
    assert keys
    assert set(keys) <= catalog["en"].keys()


def test_tools_locale_handler_does_not_reload_forms_or_accept():
    source = (ROOT / "ui/tools.js").read_text("utf-8")
    assert '"oa:localechange"' in source
    assert 'data-lang="ko"' in (ROOT / "ui/tools.html").read_text("utf-8")
    assert 'showStatement(window.OAI18n.getLocale())' in source
