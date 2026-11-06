"""Offline Korean verification: fake packages only, never install speech dependencies."""
import json
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "korean_voice_probe.py"


@pytest.fixture
def voice(tmp_path):
    packages = tmp_path / "한국어 환경"
    packages.mkdir()
    for name in ("g2pk2", "jamo", "ko_pron", "mecab", "eunjeon", "mecab_ko_dic"):
        p = packages / name
        p.mkdir()
        (p / "__init__.py").write_text("", encoding="utf-8")
    for name, folder in (("eunjeon", "data"), ("mecab_ko_dic", "dicdir")):
        p = packages / name / folder
        p.mkdir()
        for f in ("sys.dic", "unk.dic", "matrix.bin", "char.bin", "mecabrc"):
            (p / f).write_text("fixture", encoding="utf-8")
    (packages / "mecab_ko_dic" / "__init__.py").write_text(
        "from pathlib import Path\ndictionary_path = Path(__file__).parent / 'dicdir'\n")
    (packages / "mecab" / "mecabrc").write_text("")
    nltk = packages / "nltk"
    nltk.mkdir()
    (nltk / "__init__.py").write_text(
        "from . import data, downloader\n"
        "def download(*a, **k): raise AssertionError('real downloader called')\n")
    (nltk / "data.py").write_text("path = []\ndef find(name): return name\n")
    (nltk / "downloader.py").write_text(
        "class Downloader:\n"
        "    def download(self, *a, **k): raise AssertionError('real downloader called')\n"
        "    def incr_download(self, *a, **k): raise AssertionError('real downloader called')\n"
        "download = Downloader().download\n")
    front = tmp_path / "GPT-SoVITS" / "GPT_SoVITS" / "text"
    front.mkdir(parents=True)
    (front / "__init__.py").write_text("")
    (front / "korean.py").write_text("def g2p(text): return ['a', 'n']\n")
    return tmp_path, packages, front


def run_probe(voice, windows=False, timeout=5, gsv_dir=None):
    engine, packages, _ = voice
    code = f"""
import importlib.util, sys, json, subprocess, socket
def forbidden(*a, **k):
    raise AssertionError('reached real process/network backend')
if hasattr(subprocess, '_fork_exec'):
    subprocess._fork_exec = forbidden
if hasattr(subprocess, '_winapi'):
    subprocess._winapi.CreateProcess = forbidden
socket.socket.connect = forbidden
socket.socket.connect_ex = forbidden
sys.path.insert(0, {str(packages)!r})
spec = importlib.util.spec_from_file_location('probe', {str(SCRIPT)!r})
p = importlib.util.module_from_spec(spec)
spec.loader.exec_module(p)
p.install_verification_guard()
print(json.dumps(p.probe({str(engine)!r}, windows={windows!r}, gsv_dir={str(gsv_dir) if gsv_dir else None!r})))
"""
    result = subprocess.run([sys.executable, "-I", "-B", "-c", code],
                            capture_output=True, text=True, timeout=timeout)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout.splitlines()[-1])


@pytest.mark.parametrize("windows,package", [(True, "eunjeon"), (False, "mecab"), (False, "g2pk2")])
def test_missing_package_before_korean_import(voice, windows, package):
    _, packages, front = voice
    (packages / package).rename(packages / (package + "_absent"))
    (front / "korean.py").write_text("raise AssertionError('Korean imported before prerequisites')")
    result = run_probe(voice, windows=windows)
    assert result["ok"] is False
    assert package in result["detail"]
    assert "before prerequisites" not in result["detail"]


@pytest.mark.parametrize("windows,package,folder", [(True, "eunjeon", "data"), (False, "mecab_ko_dic", "dicdir")])
@pytest.mark.parametrize("missing", ["sys.dic", "unk.dic", "matrix.bin", "char.bin", "mecabrc"])
def test_missing_dictionary_before_g2pk_import(voice, windows, package, folder, missing):
    _, packages, _ = voice
    target = packages / package / folder / missing
    if not windows and missing == "mecabrc":
        target = packages / "mecab" / "mecabrc"
    target.unlink()
    (packages / "g2pk2" / "__init__.py").write_text("raise AssertionError('unsafe g2pk2 import')")
    result = run_probe(voice, windows=windows)
    assert not result["ok"] and missing in result["detail"]
    assert "unsafe g2pk2" not in result["detail"]


@pytest.mark.parametrize("windows", [False, True])
def test_missing_nltk_data_before_g2pk_import(voice, windows):
    _, packages, _ = voice
    (packages / "nltk" / "data.py").write_text(
        "path = []\ndef find(name): raise LookupError(name)\n")
    (packages / "g2pk2" / "__init__.py").write_text("raise AssertionError('unsafe g2pk2 import')")
    result = run_probe(voice, windows=windows)
    assert not result["ok"] and "cmudict.zip" in result["detail"]
    assert "unsafe g2pk2" not in result["detail"]


@pytest.mark.parametrize("windows", [False, True])
def test_success_runs_fixture_frontend_function(voice, windows):
    _, _, front = voice
    (front / "korean.py").write_text(
        "def g2p(text):\n    assert text == '안녕하세요'\n    return ['a', 'n']\n", encoding="utf-8")
    assert run_probe(voice, windows=windows)["ok"] is True


@pytest.mark.parametrize("body", ["raise RuntimeError('bad initialization')", "def g2p(text): return []"])
def test_bad_initialization_or_empty_phones(voice, body):
    voice[2].joinpath("korean.py").write_text(body)
    assert not run_probe(voice)["ok"]


@pytest.mark.parametrize("action", [
    "import subprocess; subprocess.Popen(['pip', 'install', 'eunjeon'])",
    "import subprocess; subprocess.run([__import__('sys').executable, '-m', 'pip', 'install', 'python-mecab-ko'])",
    "import os; os.system('echo unsafe')",
    "import socket; socket.create_connection(('127.0.0.1', 9))",
    "import urllib.request; urllib.request.urlopen('https://example.invalid/')",
    "import nltk; nltk.download('cmudict')",
    "from nltk.downloader import Downloader; Downloader().download('cmudict')",
    "from nltk import downloader; downloader.download('cmudict')",
    "from nltk.downloader import Downloader; list(Downloader().incr_download('cmudict'))",
    "open('must-not-write', 'w')",
])
def test_side_effect_attempts_denied(voice, action):
    voice[2].joinpath("korean.py").write_text(action + "\ndef g2p(text): return ['a']\n")
    result = run_probe(voice)
    assert not result["ok"]
    assert "prohibited" in result["detail"]


def test_swallowed_denial_cannot_report_success(voice):
    voice[2].joinpath("korean.py").write_text(
        "import nltk\ntry: nltk.download('cmudict')\nexcept Exception: pass\ndef g2p(text): return ['a']\n")
    assert not run_probe(voice)["ok"]


def test_active_g2p_child_is_killed_on_timeout(voice):
    voice[2].joinpath("korean.py").write_text(
        "import time\ndef g2p(text):\n    time.sleep(10)\n    return ['a']\n")
    with pytest.raises(subprocess.TimeoutExpired):
        run_probe(voice, timeout=0.3)


def test_probe_custom_checkout_path(voice):
    engine = voice[0]
    custom = engine / "custom-checkout"
    (engine / "GPT-SoVITS").rename(custom)
    assert run_probe(voice, gsv_dir=custom)["ok"]


@pytest.fixture
def vendor(monkeypatch):
    import importlib.util
    path = SCRIPT.parents[1] / "vendor" / "tts-engine" / "main.py"
    spec = importlib.util.spec_from_file_location("korean_test_vendor", path)
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, module)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("lang,text", [
    ("ko", "hello"), ("all_ko", "hello"), ("en", "hello 안녕"),
    ("auto", "안녕"), ("auto_yue", "안녕"), ("auto", "한"), ("auto", "ㅎㅇ"),
])
def test_runtime_rejects_korean_before_upstream(vendor, monkeypatch, tmp_path, lang, text):
    from types import SimpleNamespace
    engine = vendor.VoiceEngine(SimpleNamespace(gpt_sovits_dir=tmp_path), {}, None)
    engine.tts = object()
    engine.speaker = SimpleNamespace(prompt_lang="ja")
    def reject(path):
        raise RuntimeError("Korean voice unavailable: missing eunjeon; Korean text remains available")
    monkeypatch.setattr(vendor, "require_korean_voice", reject)
    with pytest.raises(RuntimeError, match="Korean voice unavailable"):
        engine.synth(text, None, lang)


@pytest.mark.parametrize("lang,text", [("en", "Hello"), ("ja", "おはよう"), ("zh", "你好"),
                                       ("auto", "hello おはよう"), ("en", "hello アミカ")])
def test_runtime_existing_languages_skip_korean_gate(vendor, monkeypatch, tmp_path, lang, text):
    from types import SimpleNamespace
    class ReachedReference(Exception):
        pass
    def resolve(tag):
        raise ReachedReference
    engine = vendor.VoiceEngine(SimpleNamespace(gpt_sovits_dir=tmp_path), {}, None)
    engine.tts = object()
    engine.speaker = SimpleNamespace(prompt_lang="ja", resolve=resolve)
    monkeypatch.setattr(vendor, "require_korean_voice", lambda *a: pytest.fail("Korean preflight for other language"))
    with pytest.raises(ReachedReference):
        engine.synth(text, None, lang)


@pytest.mark.parametrize("outcome", ["ok", "missing", "timeout", "crash", "invalid"])
def test_runtime_check_is_bounded_child_only(vendor, monkeypatch, tmp_path, outcome):
    from types import SimpleNamespace
    calls = []
    def run(cmd, **kwargs):
        calls.append((cmd, kwargs))
        if outcome == "timeout":
            raise subprocess.TimeoutExpired(cmd, kwargs["timeout"])
        return SimpleNamespace(returncode=1 if outcome == "crash" else 0,
                               stdout="bad" if outcome == "invalid" else json.dumps(
                                   {"ok": outcome == "ok", "detail": "missing eunjeon"}))
    monkeypatch.setattr(vendor.subprocess, "run", run)
    monkeypatch.setattr(sys, "addaudithook", lambda *a: pytest.fail("installed irreversible server guard"))
    before = sys.modules.get("text.korean")
    if outcome == "ok":
        vendor.require_korean_voice(tmp_path)
    else:
        with pytest.raises(RuntimeError, match="Korean voice unavailable"):
            vendor.require_korean_voice(tmp_path)
    cmd, kw = calls[0]
    assert cmd[0] == sys.executable and "-I" in cmd and "-B" in cmd
    assert cmd[-1] == str(tmp_path) and kw["cwd"] == str(tmp_path)
    assert 0 < kw["timeout"] <= 30
    assert sys.modules.get("text.korean") is before


def test_runtime_korean_reference_also_checked(vendor, monkeypatch, tmp_path):
    from types import SimpleNamespace
    engine = vendor.VoiceEngine(SimpleNamespace(gpt_sovits_dir=tmp_path), {}, None)
    engine.tts = object()
    engine.speaker = SimpleNamespace(prompt_lang="ko")
    def reject(*a):
        raise RuntimeError("Korean voice unavailable")
    monkeypatch.setattr(vendor, "require_korean_voice", reject)
    with pytest.raises(RuntimeError, match="Korean voice unavailable"):
        engine.synth("Hello", None, "en")


def test_runtime_ready_korean_continues_to_reference(vendor, monkeypatch, tmp_path):
    from types import SimpleNamespace
    calls = []
    class ReachedReference(Exception):
        pass
    def resolve(tag):
        raise ReachedReference
    engine = vendor.VoiceEngine(SimpleNamespace(gpt_sovits_dir=tmp_path), {}, None)
    engine.tts = object()
    engine.speaker = SimpleNamespace(prompt_lang="ja", resolve=resolve)
    monkeypatch.setattr(vendor, "require_korean_voice", lambda path: calls.append(path))
    with pytest.raises(ReachedReference):
        engine.synth("안녕하세요", None, "ko")
    assert calls == [tmp_path]


def test_runtime_missing_helper_is_korean_only(vendor, monkeypatch, tmp_path):
    monkeypatch.setattr(vendor, "ENGINE_DIR", tmp_path / "vendor" / "tts-engine")
    monkeypatch.setattr(vendor, "__file__", str(tmp_path / "vendor" / "tts-engine" / "main.py"))
    monkeypatch.setattr(vendor.subprocess, "run", lambda *a, **k: pytest.fail("spawn without helper"))
    with pytest.raises(RuntimeError, match="Korean voice unavailable: verification helper missing"):
        vendor.require_korean_voice(tmp_path)


def test_runtime_success_cached_per_resolved_checkout(vendor, monkeypatch, tmp_path):
    from types import SimpleNamespace
    calls = []
    def run(cmd, **kw):
        calls.append(cmd)
        return SimpleNamespace(returncode=0, stdout=json.dumps({"ok": True, "detail": "ok"}))
    monkeypatch.setattr(vendor.subprocess, "run", run)
    vendor.require_korean_voice(tmp_path)
    vendor.require_korean_voice(tmp_path / "child" / "..")
    assert len(calls) == 1
    vendor.require_korean_voice(tmp_path / "other")
    assert len(calls) == 2


def test_runtime_failure_retried_then_success_cached(vendor, monkeypatch, tmp_path):
    from types import SimpleNamespace
    calls = []
    def run(cmd, **kw):
        calls.append(cmd)
        return SimpleNamespace(returncode=0, stdout=json.dumps({"ok": len(calls) > 1, "detail": "missing eunjeon"}))
    monkeypatch.setattr(vendor.subprocess, "run", run)
    with pytest.raises(RuntimeError, match="Korean voice unavailable"):
        vendor.require_korean_voice(tmp_path)
    vendor.require_korean_voice(tmp_path)
    vendor.require_korean_voice(tmp_path)
    assert len(calls) == 2


def test_runtime_shallow_custom_path_has_diagnostic(vendor, monkeypatch, tmp_path):
    monkeypatch.setattr(vendor, "ENGINE_DIR", tmp_path)
    monkeypatch.setattr(vendor, "__file__", str(Path(tmp_path.anchor) / "main.py"))
    monkeypatch.setattr(vendor.subprocess, "run", lambda *a, **k: pytest.fail("spawn without helper"))
    with pytest.raises(RuntimeError, match="Korean voice unavailable: verification helper missing"):
        vendor.require_korean_voice(tmp_path)


def test_korean_failure_has_stable_type_for_public_error(vendor, monkeypatch, tmp_path):
    monkeypatch.setattr(vendor, 'ENGINE_DIR', tmp_path)
    monkeypatch.setattr(vendor, '__file__', str(tmp_path / 'main.py'))
    with pytest.raises(RuntimeError) as error:
        vendor.require_korean_voice(tmp_path)
    assert getattr(error.value, 'code', None) == 'korean_voice_unavailable'
