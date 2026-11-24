"""Launcher helpers: which launch.py a command line runs, local-only role detection, relative interpreter paths, what
ships in settings.example.json and config/, and when the page opens.

Offline; imports launch.py without running it.
"""
import importlib.util
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _shipped import shipped_bytes  # noqa: E402  (what ships, not what onboarding wrote: see tests/_shipped.py)
from _llm_stub import LlmStub, unused_url  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("openamika_launch", ROOT / "launch.py")
launch = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(launch)


class LauncherTargetTests(unittest.TestCase):
    def test_relative_launcher_is_unknown(self):
        self.assertEqual(launch.launcher_target(r"C:\envs\brain\python.exe -X utf8 launch.py"), "")

    def test_own_launcher_by_absolute_path(self):
        own = os.path.normcase(str(ROOT / "launch.py"))
        cmd = f'"C:\\envs\\brain\\python.exe" -X utf8 "{ROOT / "launch.py"}" --no-browser'
        self.assertEqual(launch.launcher_target(cmd), own)

    def test_other_checkout_is_recognised(self):
        other = ROOT.parent / "SomeOtherCheckout" / "launch.py"
        cmd = f'"C:\\envs\\brain\\python.exe" -X utf8 "{other}"'
        target = launch.launcher_target(cmd)
        self.assertTrue(target)
        self.assertNotEqual(target, os.path.normcase(str(ROOT / "launch.py")))

    def test_unbalanced_quotes_do_not_raise(self):
        self.assertEqual(launch.launcher_target('python "launch.py'), "")


class LocalRolesTests(unittest.TestCase):
    def _with_roles(self, selections):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        (Path(tmp.name) / "config").mkdir()
        (Path(tmp.name) / "config" / "llm_roles.json").write_text(json.dumps({"selections": selections}), "utf-8")
        old = launch.ROOT
        launch.ROOT = Path(tmp.name)
        self.addCleanup(setattr, launch, "ROOT", old)

    def test_compat_checks_look_at_each_server_a_role_uses(self):
        up = LlmStub(["served-name"])
        self.addCleanup(up.close)
        down = unused_url()
        self._with_roles({"surface": "surface:compat:plain", "deep": "deep:compat:alias",
                          "reflection": "reflection:compat:other"})
        (launch.ROOT / "config" / "openai_compat.json").write_text(json.dumps({"base_url": down, "models": [
            {"name": "plain"}, {"name": "alias", "served_name": "served-name", "base_url": up.host},
            {"name": "other", "served_name": "missing", "base_url": up.host}]}), "utf-8")
        got = launch.compat_checks()
        self.assertIn(("ok", "LLM server", f"answers at {up.url}"), got)
        self.assertIn(("ok", "LLM model alias", "deep"), got)
        self.assertIn(("err", "LLM model other", "not listed by the server (reflection need it)"), got)
        self.assertTrue(any(c[0] == "err" and c[1] == "LLM server" and down in c[2] for c in got))

    def test_compat_checks_for_one_server_and_its_model(self):
        up = LlmStub(["only"])
        self.addCleanup(up.close)
        self._with_roles({"deep": "deep:compat:only"})
        (launch.ROOT / "config" / "openai_compat.json").write_text(json.dumps({"base_url": up.url, "models": [{"name": "only"}]}), "utf-8")
        self.assertEqual(launch.compat_checks(), [("ok", "LLM server", f"answers at {up.url}"), ("ok", "LLM model only", "deep")])

    def test_compat_checks_say_why_a_server_will_not_do(self):
        keyed = LlmStub(["only"], refuse=401)
        self.addCleanup(keyed.close)
        tls = unused_url().replace("http://", "https://")
        self._with_roles({"deep": "deep:compat:keyed", "surface": "surface:compat:far", "reflection": "reflection:compat:tls"})
        (launch.ROOT / "config" / "openai_compat.json").write_text(json.dumps({"base_url": keyed.url, "models": [
            {"name": "keyed"}, {"name": "far", "base_url": "http://8.8.8.8:8000/v1"}, {"name": "tls", "base_url": tls}]}), "utf-8")
        got = {detail for level, name, detail in launch.compat_checks() if (level, name) == ("err", "LLM server")}
        self.assertEqual(len(got), 3, got)
        self.assertTrue(any("asks for an API key (HTTP 401) and none is saved for it: enter it on Setup" in d for d in got))
        self.assertTrue(any("http://8.8.8.8:8000/v1 is a public address (8.8.8.8): plain http is for" in d for d in got))
        self.assertIn(f"not answering at {tls} — start it (or fix its address on Setup → Brain)", got)   # https is tried
        self.assertEqual(keyed.requests[0]["auth"], None)

    def test_a_server_whose_key_is_saved_is_not_sent_it_by_the_pre_flight(self):
        keyed = LlmStub(["only"], refuse=401)
        self.addCleanup(keyed.close)
        self._with_roles({"deep": "deep:compat:keyed"})
        (launch.ROOT / "brain").mkdir()
        (launch.ROOT / "brain" / ".env").write_text("OPENAI_COMPAT_API_KEY=sk-secret\n", "utf-8")
        doc = {"base_url": keyed.url, "key_base_url": keyed.url, "models": [{"name": "keyed"}]}
        (launch.ROOT / "config" / "openai_compat.json").write_text(json.dumps(doc), "utf-8")
        self.assertEqual(launch.compat_checks(), [("ok", "LLM server", f"answers at {keyed.url} (it asks for its key, which "
                                                   "this check does not send); its models cannot be listed from here")])
        self.assertEqual([r["auth"] for r in keyed.requests], [None])
        doc["key_base_url"] = "http://127.0.0.1:1/v1"                 # the key belongs to another address
        (launch.ROOT / "config" / "openai_compat.json").write_text(json.dumps(doc), "utf-8")
        self.assertEqual([c[0] for c in launch.compat_checks()], ["err"])

    def test_a_role_on_a_local_server_needs_no_openrouter_key(self):
        self._with_roles({r: f"{r}:compat:m" for r in ("deep", "surface", "reflection", "memory_write")})
        self.assertTrue(launch.roles_all_local())
        self._with_roles({"deep": "deep:compat:m", "surface": "surface:ollama:qwen3:8b", "reflection": "reflection:ollama:qwen3:8b",
                          "memory_write": "memory_write:compat:m"})
        self.assertTrue(launch.roles_all_local())
        self._with_roles({"deep": "deep:compat:m", "surface": "grok"})
        self.assertFalse(launch.roles_all_local())

    def test_all_ollama(self):
        self._with_roles({r: f"{r}:ollama:qwen3:8b" for r in ("deep", "surface", "reflection", "memory_write")})
        self.assertTrue(launch.roles_all_local())

    def test_mixed_roles_need_the_key(self):
        self._with_roles({"deep": "deep:z-ai/glm-5#no-reasoning", "surface": "surface:ollama:qwen3:8b",
                          "reflection": "reflection:ollama:qwen3:8b", "memory_write": "memory_write:ollama:qwen3:8b"})
        self.assertFalse(launch.roles_all_local())

    def test_shipped_defaults_use_openrouter(self):
        shipped = json.loads(shipped_bytes("config/llm_roles.json").decode("utf-8-sig"))
        self._with_roles(shipped.get("selections") or {})
        self.assertTrue(shipped.get("selections"))
        self.assertFalse(launch.roles_all_local())

    def test_missing_tools_json_is_not_a_problem(self):
        self._with_roles({})
        self.assertEqual(launch.load_tools(), (None, None))
        (launch.ROOT / "config" / "tools.json").write_text("{not json", "utf-8")
        tools, error = launch.load_tools()
        self.assertIsNone(tools)
        self.assertIn("not valid JSON", error)


class ShippedSettingsTests(unittest.TestCase):
    def test_example_uses_relative_interpreters(self):
        cfg = json.loads((ROOT / "settings.example.json").read_text("utf-8"))
        for value in (cfg["brain_python"], cfg["speech_python"], cfg["embedder"]["python"], cfg["vision"]["python"]):
            self.assertFalse(Path(value).is_absolute(), value)
            self.assertTrue(str(launch.resolve(value)).startswith(str(ROOT)))

    def test_ports_are_distinct(self):
        cfg = json.loads((ROOT / "settings.example.json").read_text("utf-8"))
        ports = [cfg["brain_port"], cfg["chat_port"], cfg["messengers_port"], cfg["embedder"]["port"], cfg["vision"]["port"]]
        self.assertEqual(len(set(ports)), len(ports))

    def test_shipped_identity_is_neutral(self):
        cfg = json.loads(shipped_bytes("config/build_f.json").decode("utf-8-sig"))
        self.assertEqual(cfg["user_name"], "User")
        self.assertEqual(cfg["city"], "")
        self.assertFalse(cfg["onboarded"])


class PageOpenerTests(unittest.TestCase):
    """The browser opens once, when speech answers. A first start after the setup can take longer than speech's 90 s
    start timeout (new environments spend a minute or more on their first imports): the page still opens then."""

    def test_the_page_opens_once_when_speech_answers_even_after_its_timeout(self):
        speech, opened = SimpleNamespace(state="timeout"), []
        page = launch.PageOpener("http://localhost:53000", speech, opener=opened.append)
        self.assertFalse(page.check())                       # yellow row: still starting, nothing to open yet
        speech.state = "up"
        self.assertTrue(page.check())
        self.assertFalse(page.check())
        self.assertEqual(opened, ["http://localhost:53000"])

    def test_no_browser_never_opens_it(self):
        opened = []
        page = launch.PageOpener("http://localhost:53000", SimpleNamespace(state="up"), enabled=False,
                                 opener=opened.append)
        self.assertFalse(page.check())
        self.assertEqual(opened, [])


if __name__ == "__main__":
    unittest.main()
