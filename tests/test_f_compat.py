"""An OpenAI-compatible server as a role transport (f_compat + the role manager's generated options). Offline:
the real HTTP in here goes to stand-in servers on the loopback."""
import contextlib
import json
import os
import shutil
import socket
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "brain"))
sys.path.insert(0, str(ROOT / "tests"))
from _llm_stub import LlmStub, unused_url                           # noqa: E402
import f_compat                                                     # noqa: E402
import f_memory                                                     # noqa: E402
from f_compat import (COMPAT, KEY_ENV, CompatClient, ThinkFilter, compat_base_url, compat_role_config, reported_charge,   # noqa: E402
                      discover, load_compat_config, local_address, save_compat_config, save_key, saved_key,
                      strip_thinking)
from f_memory import MemoryRuntime                                   # noqa: E402
from f_openrouter import describe_error                              # noqa: E402
from f_roles import NATIVE_KEYS, ROLES, install_roles                # noqa: E402
from f_usage import UsageMeter                                       # noqa: E402

BASE = "http://127.0.0.1:1234/v1"
SERVER = {"base_url": BASE, "models": [{"name": "local-model"}]}


class Response:
    def __init__(self, lines=None, data=None, status=200):
        self.status_code, self._lines, self._data, self.encoding = status, lines or [], data, None
    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError("http " + str(self.status_code))
    def iter_lines(self, decode_unicode=True):
        return iter(self._lines)
    def json(self):
        return self._data
    def close(self):
        pass


class HTTP:
    def __init__(self):
        self.responses, self.calls = [], []
    def post(self, url, **kwargs):
        self.calls.append((url, json.loads(json.dumps(kwargs.get("json"))), kwargs))
        return self.responses.pop(0)
    def get(self, url, **kwargs):
        self.calls.append((url, None, kwargs))
        return self.responses.pop(0)


def sse(*chunks, usage=None, finish="stop"):
    rows = [{"model": "/models/x.gguf", "choices": [{"delta": {"content": c}, "finish_reason": None}]} for c in chunks]
    rows.append({"model": "/models/x.gguf", "choices": [{"delta": {}, "finish_reason": finish}]})
    if usage:
        rows.append({"choices": [], "usage": usage})
    return ["data: " + json.dumps(r) for r in rows] + ["data: [DONE]"]


def run(role, *chunks):
    think = ThinkFilter(role)
    out = "".join(think.feed(c) for c in chunks)
    return out + think.feed("", final=True)


def resolves_to(*addresses):
    """socket.getaddrinfo as if the name stood for these addresses."""
    return patch.object(f_compat.socket, "getaddrinfo", lambda host, port, **kw: [
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, port)) for address in addresses])


class AddressTests(unittest.TestCase):
    def test_addresses(self):
        self.assertEqual(compat_base_url(""), BASE)
        self.assertEqual(compat_base_url("http://box:8080"), "http://box:8080/v1")
        self.assertEqual(compat_base_url("http://box:8080/api/v1/"), "http://box:8080/api/v1")
        self.assertEqual(compat_base_url("http://box:1234/v1/chat/completions"), "http://box:1234/v1")
        for bad in ("ftp://box", "http://user:pw@box/v1", "http://box/v1?x=1", "http://box:notaport/v1", "box:1234"):
            with self.assertRaises(ValueError):
                compat_base_url(bad)

    def test_this_machine_and_private_networks_are_accepted(self):
        for url in ("http://127.0.0.1:8000/v1", "http://localhost:8000/v1", "http://192.168.1.20:8000/v1",
                    "http://10.0.0.5:8080/v1", "http://100.64.0.7:8000/v1", "http://[::1]:8000/v1"):
            self.assertEqual(compat_base_url(url), url)
        for url in ("http://127.0.0.1:8000/v1", "http://192.168.1.20:8000/v1"):
            self.assertTrue(local_address(url))
        with resolves_to("192.168.1.20"):
            self.assertEqual(local_address("http://box:8000/v1"), ["192.168.1.20"])

    def test_plain_http_is_for_local_servers_and_anything_else_needs_https(self):
        for url in ("http://8.8.8.8:8000/v1", "http://[2001:4860:4860::8888]/v1"):
            with self.assertRaisesRegex(ValueError, "is a public address; plain http is for local servers only: use https"):
                compat_base_url(url)
        for url in ("https://api.example.com/v1", "https://8.8.8.8/v1", "https://127.0.0.1:8000/v1"):
            self.assertEqual(compat_base_url(url), url)
        self.assertEqual(compat_base_url("https://api.example.com"), "https://api.example.com/v1")
        with patch.object(f_compat.socket, "getaddrinfo", side_effect=AssertionError("an https name is not looked up")):
            self.assertEqual(local_address("https://api.example.com/v1"), [])

    def test_a_name_is_judged_by_what_it_stands_for(self):
        self.assertEqual(compat_base_url("http://models.example.com/v1"), "http://models.example.com/v1")
        with resolves_to("192.168.1.20", "8.8.4.4"):            # one public address among them is enough
            with self.assertRaisesRegex(ValueError, r"models\.example\.com is a public address \(8\.8\.4\.4\)"):
                local_address("http://models.example.com/v1")
        with patch.object(f_compat.socket, "getaddrinfo", side_effect=OSError("no such host")):
            with self.assertRaisesRegex(ValueError, "does not resolve"):
                local_address("http://nowhere.invalid/v1")


class ThinkingTests(unittest.TestCase):
    def test_a_normal_answer_streams_at_once(self):
        think = ThinkFilter("deep")
        self.assertEqual(think.feed('[casual_happy]"He'), '[casual_happy]"He')
        self.assertEqual(think.feed('llo."'), 'llo."')

    def test_a_leading_block_is_removed_even_split_across_chunks(self):
        self.assertEqual(run("deep", "<th", "ink>plan the", " reply</th", 'ink>\n', '\n[casual_happy]"Hi"'), '[casual_happy]"Hi"')

    def test_reasoning_whose_opening_tag_was_in_the_prompt_is_never_released(self):
        think = ThinkFilter("surface")
        self.assertEqual(think.feed("Okay, the user said hi. "), "")
        self.assertEqual(think.feed("I should reply.</think>\nstatus: ok"), "status: ok")

    def test_an_odd_answer_with_no_tags_still_arrives_whole_at_the_end(self):
        self.assertEqual(run("deep", "just some ", "plain text"), "just some plain text")

    def test_thinking_that_never_ended_says_nothing(self):
        self.assertEqual(run("deep", "<think>still going"), "")

    def test_whole_replies(self):
        self.assertEqual(strip_thinking("<think>x</think>\nanswer"), "answer")
        self.assertEqual(strip_thinking("x</think>answer"), "answer")
        self.assertEqual(strip_thinking("<think>never closed"), "")
        quoted = '{"facts": [{"quote": "she typed </think> here"}]}'
        self.assertEqual(strip_thinking(quoted), quoted)


class ClientTests(unittest.TestCase):
    def setUp(self):
        self.http, self.handles, self.receipts = HTTP(), [], []
        f_compat._QUIRKS.clear()
        self.client = self.make(BASE)

    def make(self, base_url, api_key=""):
        return CompatClient(self.http, lambda request: self.handles.append(request) or "h1",
                            lambda handle, receipt: self.receipts.append((handle, receipt)), base_url=base_url,
                            api_key=api_key)

    def test_stream_settles_complete_despite_another_model_name(self):
        cfg = compat_role_config(SERVER, "local-model", "deep")
        self.http.responses = [Response(lines=sse('[casual_happy]"Hel', 'lo."', usage={"prompt_tokens": 80, "completion_tokens": 9}))]
        text = "".join(self.client.stream(cfg, [{"role": "user", "content": "u"}], metadata={"phase": "deep"}))
        self.assertEqual(text, '[casual_happy]"Hello."')
        url, body, kwargs = self.http.calls[0]
        self.assertEqual(url, BASE + "/chat/completions")
        self.assertNotIn("Authorization", kwargs["headers"])
        self.assertFalse(kwargs["allow_redirects"])
        self.assertEqual(body["stream_options"], {"include_usage": True})
        self.assertNotIn("response_format", body)
        receipt = self.receipts[0][1]
        self.assertEqual((receipt["status"], receipt["cost_usd"], receipt["actual_model"]), ("complete", 0.0, "/models/x.gguf"))
        self.assertEqual(receipt["usage"]["tokens"]["total_input_tokens"], 80)
        json.dumps(receipt)                                  # the archive must be able to write it

    def test_a_server_without_usage_still_completes(self):
        cfg = compat_role_config(SERVER, "local-model", "surface")
        self.http.responses = [Response(lines=sse("status: ok"))]
        self.assertEqual("".join(self.client.stream(cfg, [{"role": "user", "content": "u"}])), "status: ok")
        self.assertEqual(self.receipts[0][1]["status"], "complete")

    def test_thinking_stays_out_of_the_text_and_the_receipt(self):
        cfg = compat_role_config(SERVER, "local-model", "deep")
        self.http.responses = [Response(lines=sse("<think>secret</think>", '[casual_happy]"Hi"'))]
        self.assertEqual("".join(self.client.stream(cfg, [{"role": "user", "content": "u"}])), '[casual_happy]"Hi"')
        self.assertNotIn("secret", self.receipts[0][1]["content"])

    def test_answer_budget_used_up_by_thinking_is_marked(self):
        cfg = compat_role_config(SERVER, "local-model", "deep")
        self.http.responses = [Response(lines=sse("<think>long", finish="length"))]
        with contextlib.redirect_stdout(None):
            self.assertEqual("".join(self.client.stream(cfg, [{"role": "user", "content": "u"}])), "")
        self.assertTrue(self.receipts[0][1]["reasoning_unfinished"])

    def test_refused_parameter_is_adapted_and_remembered(self):
        cfg = compat_role_config(SERVER, "local-model", "memory_write")
        data = {"choices": [{"message": {"content": "<think>x</think>{\"facts\": []}"}, "finish_reason": "stop"}]}
        self.http.responses = [Response(status=400, data={"error": {"message": "Use 'max_completion_tokens' instead."}}), Response(data=data)]
        self.assertEqual(self.client.complete(cfg, [{"role": "user", "content": "u"}])["text"], '{"facts": []}')
        self.assertIn("max_tokens", self.http.calls[0][1])
        self.assertIn("max_completion_tokens", self.http.calls[1][1])
        self.assertNotIn("max_tokens", self.http.calls[1][1])
        self.http.responses = [Response(data=data)]
        self.client.complete(cfg, [{"role": "user", "content": "u"}])
        self.assertEqual(len(self.http.calls), 3)            # no second refusal: the server's rule was remembered

    def test_an_error_wrapped_in_a_list_still_explains_itself(self):
        cfg = compat_role_config(SERVER, "local-model", "surface")
        self.http.responses = [Response(status=404, data=[{"error": {"code": 404, "message": "This model is gone"}}])]
        with self.assertRaises(Exception) as caught:
            list(self.client.stream(cfg, [{"role": "user", "content": "u"}]))
        self.assertIn("HTTP 404: This model is gone", str(caught.exception))

    def test_other_errors_explain_themselves(self):
        cfg = compat_role_config(SERVER, "local-model", "surface")
        self.http.responses = [Response(status=400, data={"error": {"message": "context too long"}})]
        with self.assertRaises(Exception) as caught:
            list(self.client.stream(cfg, [{"role": "user", "content": "u"}]))
        self.assertIn("HTTP 400: context too long", str(caught.exception))
        self.assertEqual(describe_error(caught.exception), "Your model server: HTTP 400: context too long")

    def test_a_server_that_wants_a_key_tells_the_person_so_in_her_chat(self):
        cfg = compat_role_config(SERVER, "local-model", "surface")
        self.http.responses = [Response(status=401, data={"error": {"message": "Unauthorized"}})]
        with self.assertRaises(Exception) as caught:
            list(self.client.stream(cfg, [{"role": "user", "content": "u"}]))
        self.assertEqual(describe_error(caught.exception),
                         "Your model server: HTTP 401: it asks for an API key: enter it on Setup → Brain")
        keyed = self.make(BASE, api_key="sk-secret")
        self.http.responses = [Response(status=401, data={"error": {"message": "bad key sk-secret"}})]
        with self.assertRaises(Exception) as caught:
            list(keyed.stream(cfg, [{"role": "user", "content": "u"}]))
        self.assertEqual(describe_error(caught.exception),
                         "Your model server: HTTP 401: it refused the API key: enter a new one on Setup → Brain")
        self.assertNotIn("sk-secret", str(caught.exception))     # a server that echoes the key does not get it logged

    def test_a_key_echoed_in_an_error_inside_an_answer_is_cut_out_too(self):
        cfg = compat_role_config(SERVER, "local-model", "surface")
        keyed = self.make("https://api.example.com/v1", api_key="sk-secret")
        echo = {"error": {"message": "upstream rejected key sk-secret"}}
        for response, call in ((Response(lines=["data: " + json.dumps(echo)]), lambda: list(keyed.stream(cfg, [{"role": "user", "content": "u"}]))),
                               (Response(data=echo), lambda: keyed.complete(cfg, [{"role": "user", "content": "u"}]))):
            self.http.responses = [response]                     # HTTP 200 both times: the error is in the body
            with self.assertRaises(Exception) as caught:
                call()
            self.assertEqual(describe_error(caught.exception), "Your model server: upstream rejected key …")
            self.assertNotIn("sk-secret", str(caught.exception))
        self.assertNotIn("sk-secret", json.dumps([receipt for _, receipt in self.receipts]))

    def test_a_key_is_sent_only_by_a_client_that_was_given_one(self):
        cfg = compat_role_config(SERVER, "local-model", "surface")
        self.http.responses = [Response(lines=sse("status: ok")), Response(data={"data": [{"id": "m"}]}),
                               Response(lines=sse("status: ok"))]
        with patch.dict("os.environ", {"OPENAI_API_KEY": "sk-from-the-environment", KEY_ENV: "sk-other"}):
            list(self.client.stream(cfg, [{"role": "user", "content": "u"}]))
            discover(self.http, BASE)
            list(self.make(BASE, api_key="sk-secret").stream(cfg, [{"role": "user", "content": "u"}]))
        sent = [kwargs["headers"].get("Authorization") for _, _, kwargs in self.http.calls]
        self.assertEqual(sent, [None, None, "Bearer sk-secret"])   # a key in the environment alone goes nowhere
        self.assertFalse(self.http.calls[2][2]["allow_redirects"])

    def test_a_name_that_has_come_to_stand_for_a_public_address_is_not_called(self):
        client = self.make("http://models.example.com/v1")
        cfg = compat_role_config(SERVER, "local-model", "surface")
        with resolves_to("192.168.1.20"):
            self.http.responses = [Response(lines=sse("status: ok"))]
            self.assertEqual("".join(client.stream(cfg, [{"role": "user", "content": "u"}])), "status: ok")
        with resolves_to("8.8.4.4"):
            with self.assertRaisesRegex(Exception, "is a public address"):
                list(client.stream(cfg, [{"role": "user", "content": "u"}]))
        self.assertEqual(len(self.http.calls), 1)            # the second turn never left this machine
        self.assertNotEqual(self.receipts[1][1]["status"], "complete")

    def test_an_https_server_is_booked_at_zero_and_marked_unreported(self):
        cfg = compat_role_config(SERVER, "local-model", "surface")
        self.http.responses = [Response(lines=sse("status: ok")), Response(lines=sse("status: ok"))]
        list(self.client.stream(cfg, [{"role": "user", "content": "u"}]))
        list(self.make("https://api.example.com/v1", "sk-secret").stream(cfg, [{"role": "user", "content": "u"}]))
        self.assertEqual([(r["cost_usd"], r["usage"]["cost_source"]) for _, r in self.receipts],
                         [(0.0, "local"), (0.0, "unreported")])
        self.assertEqual(self.http.calls[1][0], "https://api.example.com/v1/chat/completions")

    def test_a_charge_the_server_reports_is_the_cost(self):
        cfg = compat_role_config(SERVER, "local-model", "surface")
        ticks = {"prompt_tokens": 187, "completion_tokens": 2, "cost_in_usd_ticks": 1043500}     # xAI's form
        dollars = {"prompt_tokens": 9, "completion_tokens": 3, "cost": 0.0021}                   # OpenRouter's form
        self.http.responses = [Response(lines=sse("status: ok", usage=ticks)), Response(lines=sse("status: ok", usage=dollars)),
                               Response(lines=sse("status: ok", usage=ticks))]
        hosted = self.make("https://api.example.com/v1", "sk-secret")
        list(hosted.stream(cfg, [{"role": "user", "content": "u"}]))
        list(hosted.stream(cfg, [{"role": "user", "content": "u"}]))
        list(self.client.stream(cfg, [{"role": "user", "content": "u"}]))                      # a local server
        self.assertEqual([(r["status"], r["cost_usd"], r["usage"]["cost_source"]) for _, r in self.receipts],
                         [("complete", 0.00010435, "provider"), ("complete", 0.0021, "provider"), ("complete", 0.0, "local")])
        self.assertNotIn("reported_charge_exceeds_reservation", self.receipts[0][1]["issues"])

    def test_only_a_well_formed_charge_counts(self):
        self.assertEqual(reported_charge({"cost_in_usd_ticks": 10 ** 10}), 1.0)
        self.assertEqual(reported_charge({"cost_in_usd_ticks": 0}), 0.0)
        self.assertEqual(reported_charge({"cost": 2}), 2.0)
        self.assertEqual(reported_charge({"cost_in_usd_ticks": 37756000, "cost": 9.9}), 0.0037756)    # ticks first
        for usage in (None, {}, {"cost": -1}, {"cost": True}, {"cost": "0.1"}, {"cost": float("nan")},
                      {"cost_in_usd_ticks": -5}, {"cost_in_usd_ticks": 1.5}, {"cost_in_usd_ticks": True},
                      {"cost_in_usd_ticks": 10 ** 400}, {"cost": 10 ** 400}):
            self.assertIsNone(reported_charge(usage), usage)

    def test_a_redirect_is_an_error(self):
        cfg = compat_role_config(SERVER, "local-model", "surface")
        self.http.responses = [Response(status=302, data={})]
        with self.assertRaises(Exception):
            list(self.client.stream(cfg, [{"role": "user", "content": "u"}]))


class DiscoverTests(unittest.TestCase):
    def test_discover_keeps_chat_models(self):
        http = HTTP()
        http.responses = [Response(data={"data": [{"id": "z-model"}, {"id": "text-embedding-3"}, {"id": "a-model"}]})]
        self.assertEqual(discover(http, BASE), [{"name": "a-model"}, {"name": "z-model"}])
        self.assertEqual(http.calls[0][2]["headers"], {})

    def test_a_server_that_wants_a_key_is_told_apart_from_one_that_is_down(self):
        http = HTTP()
        http.responses = [Response(status=401, data={})]
        with self.assertRaisesRegex(Exception, "asks for an API key: enter it with the address"):
            discover(http, BASE)
        http.responses = [Response(status=401, data={})]
        with self.assertRaisesRegex(Exception, "refused the API key"):
            discover(http, BASE, "k")

    def test_a_public_address_is_not_asked_over_plain_http(self):
        http = HTTP()
        with resolves_to("8.8.4.4"):
            with self.assertRaisesRegex(Exception, "plain http is for local servers only"):
                discover(http, "http://models.example.com/v1", "sk-secret")
        self.assertEqual(http.calls, [])

    def test_the_key_goes_only_to_the_address_it_was_entered_for(self):
        self.addCleanup(os.environ.pop, KEY_ENV, None)
        with tempfile.TemporaryDirectory() as tmp:
            env = Path(tmp) / ".env"
            env.write_text("OPENROUTER_API_KEY=keep\n", encoding="utf-8")
            save_key(env, "first")
            save_key(env, "second")
            self.assertEqual(env.read_text(encoding="utf-8").splitlines(), ["OPENROUTER_API_KEY=keep", KEY_ENV + "=second"])
        self.assertEqual(saved_key({"base_url": BASE, "key_base_url": BASE}), "second")
        self.assertEqual(saved_key({"base_url": "https://elsewhere.example/v1", "key_base_url": BASE}), "")
        self.assertEqual(saved_key({"base_url": BASE, "key_base_url": None}), "")
        self.assertEqual(saved_key({"base_url": BASE, "key_base_url": BASE}, "http://box:8610/v1"), "")   # an entry's own server

    def test_config_defaults_and_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "config").mkdir()
            self.assertEqual((load_compat_config(root)["base_url"], load_compat_config(root)["models"]), (BASE, []))
            save_compat_config(root, dict(SERVER, detected_at="t"))
            self.assertEqual(load_compat_config(root)["models"], [{"name": "local-model"}])
            save_compat_config(root, dict(SERVER, base_url="http://8.8.8.8/v1"))
            self.assertEqual(load_compat_config(root)["base_url"], BASE)      # a hand-written public address over plain http


class RouteTests(unittest.TestCase):
    """The page's detect route: plain http only for a local address; a key is saved, never returned, and follows
    the address it was entered for."""
    def setUp(self):
        from flask import Flask, jsonify, request
        self.addCleanup(os.environ.pop, KEY_ENV, None)
        os.environ.pop(KEY_ENV, None)
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        (self.root / "brain").mkdir()
        (self.root / "config").mkdir()
        self.http = HTTP()
        app = Flask("test")
        with contextlib.redirect_stdout(None):
            f_compat.install_compat({"app": app, "request": request, "jsonify": jsonify, "http_requests": self.http,
                                     "__file__": str(self.root / "brain" / "webui.py")})
        self.web = app.test_client()

    def detect(self, base, **extra):
        self.http.responses = [Response(data={"data": [{"id": "m1"}]})]
        return self.web.post("/api/build_f/compat/detect", json=dict(extra, base_url=base),
                             headers={"X-Build-F-Action": "compat-detect"})

    def sent(self):
        return self.http.calls[-1][2]["headers"].get("Authorization")

    def test_a_detect_without_a_key_saves_the_address_and_its_models_and_no_key(self):
        reply = self.detect(BASE)
        self.assertEqual(reply.status_code, 200)
        self.assertFalse(reply.get_json()["key_saved"])
        saved = json.loads((self.root / "config" / f_compat.CONFIG_NAME).read_text(encoding="utf-8"))
        self.assertEqual((saved["base_url"], saved["key_base_url"], saved["models"]), (BASE, None, [{"name": "m1"}]))
        self.assertFalse((self.root / "brain" / ".env").exists())
        self.assertEqual(self.http.calls[-1][2]["headers"], {})

    def test_the_key_follows_its_address(self):
        reply = self.detect(BASE, api_key="sk-secret")
        self.assertTrue(reply.get_json()["key_saved"])
        self.assertNotIn("sk-secret", reply.get_data(as_text=True))
        self.assertNotIn("sk-secret", (self.root / "config" / f_compat.CONFIG_NAME).read_text(encoding="utf-8"))
        self.assertIn(KEY_ENV + "=sk-secret", (self.root / "brain" / ".env").read_text(encoding="utf-8"))
        self.assertEqual(self.sent(), "Bearer sk-secret")
        self.assertFalse(self.detect("https://other.example/v1").get_json()["key_saved"])
        self.assertIsNone(self.sent())                                   # another address: the saved key stays home
        self.assertNotIn("sk-secret", self.web.get("/api/build_f/compat").get_data(as_text=True))
        self.assertTrue(self.detect(BASE).get_json()["key_saved"])       # back at its own address
        self.assertEqual(self.sent(), "Bearer sk-secret")

    def test_a_key_the_server_refuses_is_not_saved(self):
        self.http.responses = [Response(status=401, data={"error": {"message": "bad key sk-wrong"}})]
        reply = self.web.post("/api/build_f/compat/detect", json={"base_url": BASE, "api_key": "sk-wrong"},
                              headers={"X-Build-F-Action": "compat-detect"})
        self.assertEqual(reply.status_code, 503)
        self.assertIn("refused the API key", reply.get_json()["error"])
        self.assertNotIn("sk-wrong", reply.get_data(as_text=True))
        self.assertFalse((self.root / "brain" / ".env").exists())
        self.assertFalse((self.root / "config" / f_compat.CONFIG_NAME).exists())
        self.assertEqual(self.detect(BASE, api_key="has space").status_code, 400)

    def test_a_key_that_the_env_file_would_not_give_back_unchanged_is_refused_before_it_is_sent(self):
        env = self.root / "brain" / ".env"
        env.write_text("OPENROUTER_API_KEY=sk-or-another-providers-key\n", encoding="utf-8")
        for key in ("${OPENROUTER_API_KEY}", "sk-${OPENROUTER_API_KEY}", "$HOME", '"sk-quoted"', "'sk-quoted'",
                    "sk-`x`", "sk-back\\slash", "sk-#comment", "sk-ключ", "sk-“quoted”", "k" * 1025):
            reply = self.detect(BASE, api_key=key)
            self.assertEqual(reply.status_code, 400, key)
            self.assertIn("a key cannot contain", reply.get_json()["error"])
            with self.assertRaises(ValueError):
                save_key(env, key)
        self.assertEqual(self.http.calls, [])                    # nothing was asked of any server
        self.assertEqual(env.read_text(encoding="utf-8"), "OPENROUTER_API_KEY=sk-or-another-providers-key\n")
        self.assertFalse((self.root / "config" / f_compat.CONFIG_NAME).exists())
        self.assertIsNone(os.environ.get(KEY_ENV))

    def test_a_saved_key_is_the_same_key_when_the_brain_next_starts(self):
        from dotenv import dotenv_values                         # what the brain reads brain/.env with at its start
        env = self.root / "brain" / ".env"
        env.write_text("OPENROUTER_API_KEY=sk-or-another-providers-key\n", encoding="utf-8")
        key = "".join(chr(code) for code in range(0x21, 0x7f) if chr(code) not in "\"#$'\\`")    # all a key may have
        self.assertEqual(len(key), 88)
        self.assertEqual(self.detect(BASE, api_key=key).status_code, 200)
        self.assertEqual(self.sent(), "Bearer " + key)
        self.assertEqual(dict(dotenv_values(env)), {"OPENROUTER_API_KEY": "sk-or-another-providers-key", KEY_ENV: key})

    def test_a_new_key_is_never_paired_with_the_address_of_the_old_one(self):
        other = "https://other.example/v1"
        self.detect(BASE, api_key="sk-first")
        held = load_compat_config(self.root)                     # what a call or the page's poll read before the change
        seen = []

        def watching(write):
            def watched(*args, **kwargs):
                write(*args, **kwargs)
                fresh = load_compat_config(self.root)            # what a call reads from here on
                seen.append((saved_key(held, BASE), saved_key(held, other), saved_key(fresh, BASE), saved_key(fresh, other)))
            return watched
        with patch.object(f_compat, "save_key", watching(f_compat.save_key)), \
                patch.object(f_compat, "save_compat_config", watching(f_compat.save_compat_config)):
            self.assertEqual(self.detect(other, api_key="sk-second").status_code, 200)
        self.assertEqual(seen, [("sk-first", "", "", ""),        # the old address is unbound on disk,
                                ("", "", "", ""),                # the key is replaced: it is bound to no address,
                                ("", "", "", "sk-second")])      # the new address is bound
        self.assertEqual(self.sent(), "Bearer sk-second")
        self.detect(BASE)
        self.assertIsNone(self.sent())                           # the old address gets neither key from now on

    def test_a_write_that_fails_while_the_key_changes_leaves_it_bound_to_no_address(self):
        other = "https://other.example/v1"
        self.detect(BASE, api_key="sk-first")
        write, writes = f_compat.save_compat_config, []

        def failing_on_the_second(root, doc):
            writes.append(doc)
            if len(writes) == 2:
                raise OSError("no space left on device")
            write(root, doc)
        with patch.object(f_compat, "save_compat_config", failing_on_the_second), self.assertLogs("test", "ERROR"):
            self.assertEqual(self.detect(other, api_key="sk-second").status_code, 500)
        self.assertIn(KEY_ENV + "=sk-second", (self.root / "brain" / ".env").read_text(encoding="utf-8"))
        config = load_compat_config(self.root)
        self.assertEqual((config["key_base_url"], saved_key(config, BASE), saved_key(config, other)), (None, "", ""))
        self.assertFalse(self.web.get("/api/build_f/compat").get_json()["key_saved"])

    def test_a_new_key_for_the_same_address_keeps_it_bound(self):
        self.detect(BASE, api_key="sk-first")
        held = load_compat_config(self.root)
        self.assertTrue(self.detect(BASE, api_key="sk-second").get_json()["key_saved"])
        self.assertEqual(saved_key(held, BASE), "")              # read before the change: no key until read again
        self.assertEqual(saved_key(load_compat_config(self.root), BASE), "sk-second")

    def test_a_public_address_over_plain_http_is_refused_before_anything_is_asked_or_saved(self):
        reply = self.detect("http://8.8.8.8:8000/v1", api_key="sk-secret")
        self.assertEqual(reply.status_code, 400)
        with resolves_to("8.8.4.4"):
            reply = self.detect("http://models.example.com/v1", api_key="sk-secret")
        self.assertEqual(reply.status_code, 400)
        self.assertIn("plain http is for local servers only: use https", reply.get_json()["error"])
        self.assertEqual(self.http.calls, [])
        self.assertFalse((self.root / "config" / f_compat.CONFIG_NAME).exists())
        self.assertFalse((self.root / "brain" / ".env").exists())
        self.assertEqual(self.detect("https://api.example.com/v1").status_code, 200)      # https may be anywhere

    def test_a_detect_keeps_hand_written_entries_and_refreshes_the_rest(self):
        save_compat_config(self.root, {"base_url": BASE, "models": [
            {"name": "gone"},
            {"name": "think", "served_name": "m1", "base_url": "http://box:8610/v1", "chat_template_kwargs": {"enable_thinking": True}}]})
        self.detect(BASE)
        models = load_compat_config(self.root)["models"]
        self.assertEqual([m["name"] for m in models], ["m1", "think"])
        self.assertEqual(models[1], {"name": "think", "served_name": "m1", "base_url": "http://box:8610/v1",
                                     "chat_template_kwargs": {"enable_thinking": True}})

    def test_only_the_page_may_detect(self):
        self.assertEqual(self.web.post("/api/build_f/compat/detect", json={}, headers={
            "X-Build-F-Action": "compat-detect", "Origin": "http://elsewhere"}).status_code, 403)
        self.assertEqual(self.web.post("/api/build_f/compat/detect", json={"base_url": BASE}).status_code, 403)

    def test_a_server_that_does_not_answer_is_a_503_with_the_reason(self):
        self.http.responses = [Response(status=401, data={})]
        reply = self.web.post("/api/build_f/compat/detect", json={"base_url": BASE}, headers={"X-Build-F-Action": "compat-detect"})
        self.assertEqual(reply.status_code, 503)
        self.assertIn("asks for an API key: enter it with the address", reply.get_json()["error"])
        self.http.responses = []                                 # the fake raises: nothing is listening
        reply = self.web.post("/api/build_f/compat/detect", json={"base_url": BASE}, headers={"X-Build-F-Action": "compat-detect"})
        self.assertEqual((reply.status_code, reply.get_json()["error"]),
                         (503, f"Nothing answers at {BASE} — is the model server running?"))
        status = self.web.get("/api/build_f/compat").get_json()
        self.assertEqual((status["reachable"], status["error"]), (False, None))


class RoleManagerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "config").mkdir()
        shutil.copyfile(ROOT / "config/openrouter_models.json", self.root / "config/openrouter_models.json")
        document = {"version": 1, "options": {}, "selections": {}, "fallback_preset": "cloud", "presets": [
            {"name": "cloud", "provider": "openrouter", "selections": {role: "or:" + role for role in ROLES}}]}
        for role in ROLES:
            document["options"][role] = [
                {"key": "native:" + NATIVE_KEYS[role], "native_key": NATIVE_KEYS[role], "name": "Native"},
                {"key": "or:" + role, "model_id": "deepseek/deepseek-v4-flash-0731", "name": "Reviewed " + role}]
            document["selections"][role] = "or:" + role
        (self.root / "config/llm_roles.json").write_text(json.dumps(document), encoding="utf-8")
        save_compat_config(self.root, dict(SERVER, detected_at="t"))
        self.memory = MemoryRuntime(self.root / "memory_f/live", lambda events, chunk: {"native": True},
                                    lambda texts, task: [[1.] + [0.] * 767 for t in texts])
        self.meter = UsageMeter(self.root / "memory_f/usage.sqlite", {"models": {}}, budget_usd=1)
        self.g = {"AVAILABLE_MODELS": {key: {"name": key, "provider": "native", "model": key} for key in NATIVE_KEYS.values()},
                  "_ws_active_lock": threading.RLock(), "_ws_active": {}, "_thinking_inflight": 0,
                  "http_requests": HTTP(), "OPENROUTER_KEY": "fake-key",
                  "_pick_stream": lambda p, c, **kw: iter(["native"]),
                  "_openai_messages": lambda p, **kw: [{"role": "user", "content": p["user_content"]}]}
        @contextlib.contextmanager
        def scope(phase, turn_id="", **kwargs):
            yield
        self.manager = install_roles(self.g, self.root, self.memory, self.meter, scope, threading.local(), {})

    def tearDown(self):
        self.memory.close()
        self.tmp.cleanup()

    def test_a_turn_reaches_the_server_and_the_ledger(self):
        http = self.g["http_requests"]
        http.responses = [Response(lines=sse("status: ok", usage={"prompt_tokens": 12, "completion_tokens": 3}))]
        parts = {"user_content": "u", "_f_phase": "surface"}
        text = "".join(self.g["_pick_stream"](parts, self.g["AVAILABLE_MODELS"]["surface:compat:local-model"]))
        self.assertEqual(text, "status: ok")
        self.assertEqual(http.calls[-1][0], BASE + "/chat/completions")
        self.assertEqual(self.meter.summary()["active_requests"], 0)
        self.assertTrue(list((self.root / "memory_f/compat_receipts").glob("*.json")))

    def test_selection_and_a_vanished_model(self):
        result = self.manager.set({role: f"{role}:compat:local-model" for role in ROLES})
        self.assertEqual(result["transport"], COMPAT)
        save_compat_config(self.root, {"base_url": BASE, "models": [{"name": "other"}], "detected_at": "t2"})
        result = self.manager.reload_compat()
        self.assertNotIn("deep:compat:local-model", self.manager.options["deep"])
        self.assertIn("deep:compat:other", self.manager.options["deep"])
        self.assertEqual(result["selections"]["deep"], "or:deep")


class PerEntryTests(unittest.TestCase):
    TWO = {"base_url": BASE, "models": [
        {"name": "fast"},
        {"name": "big-on", "served_name": "big", "base_url": "http://box:8610", "chat_template_kwargs": {"enable_thinking": True},
         "thinking_tokens": 2048},
        {"name": "big-off", "served_name": "big", "base_url": "http://box:8610/v1", "chat_template_kwargs": {"enable_thinking": False}}]}

    def loaded(self, doc=None):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "config").mkdir()
            save_compat_config(root, doc or self.TWO)
            return load_compat_config(root)

    def body(self, compat, name):
        return f_compat.make_compat_body(compat_role_config(compat, name, "deep"), [{"role": "user", "content": "u"}])

    def test_two_entries_reach_two_addresses_as_their_served_names(self):
        compat = self.loaded()
        self.assertEqual(compat_role_config(compat, "fast", "deep")["base_url"], BASE)
        self.assertEqual(compat_role_config(compat, "big-off", "deep")["base_url"], "http://box:8610/v1")
        self.assertEqual(self.body(compat, "big-on")["model"], "big")
        self.assertEqual(self.body(compat, "fast")["model"], "fast")

    def test_a_plain_config_is_one_server_and_its_models(self):
        old = {"base_url": BASE, "detected_at": "t", "models": [{"name": "local-model"}]}
        self.assertEqual(self.loaded(old), dict(old, key_base_url=None))
        cfg = compat_role_config(old, "local-model", "reflection")
        self.assertEqual((cfg["api_model"], cfg["base_url"]), ("local-model", BASE))
        self.assertNotIn("chat_template_kwargs", cfg)
        self.assertEqual(sorted(self.body(old, "local-model")), ["max_tokens", "messages", "model", "stream", "stream_options"])

    def test_template_options_go_only_with_their_own_entry(self):
        compat = self.loaded()
        self.assertEqual(self.body(compat, "big-on")["chat_template_kwargs"], {"enable_thinking": True})
        self.assertEqual(self.body(compat, "big-off")["chat_template_kwargs"], {"enable_thinking": False})
        self.assertNotIn("chat_template_kwargs", self.body(compat, "fast"))

    def test_only_the_thinking_entry_gets_more_budget(self):
        compat = self.loaded()
        answer = f_compat.ANSWER_TOKENS["reflection"]
        self.assertEqual(compat_role_config(compat, "big-on", "reflection")["max_tokens"], answer + 2048)
        self.assertEqual(compat_role_config(compat, "big-off", "reflection")["max_tokens"], answer)

    def test_a_malformed_entry_is_not_offered(self):
        doc = dict(self.TWO, models=[{"name": "ok"}, {"name": "bad-url", "base_url": "ftp://x"},
                                     {"name": "bad-kwargs", "chat_template_kwargs": "on"},
                                     {"name": "empty", "base_url": ""}])
        with contextlib.redirect_stdout(None):
            self.assertEqual([m["name"] for m in self.loaded(doc)["models"]], ["ok"])

    def test_a_saved_config_keeps_every_field(self):
        models = self.loaded()["models"]
        self.assertEqual(models[1], {"name": "big-on", "served_name": "big", "base_url": "http://box:8610/v1",
                                     "chat_template_kwargs": {"enable_thinking": True}, "thinking_tokens": 2048})
        self.assertEqual(models[0], {"name": "fast"})


class TwoServersEndToEnd(unittest.TestCase):
    """The real transport over real HTTP: each role's request reaches its own server with its own options."""
    def setUp(self):
        from flask import Flask, jsonify, request
        self.fast = LlmStub(["fast"], "status: from fast")
        self.big = LlmStub(["big"], "from big")
        self.addCleanup(self.fast.close)
        self.addCleanup(self.big.close)
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        (self.root / "config").mkdir()
        shutil.copyfile(ROOT / "config/openrouter_models.json", self.root / "config/openrouter_models.json")
        document = {"version": 1, "options": {}, "selections": {}, "fallback_preset": "cloud", "presets": [
            {"name": "cloud", "provider": "openrouter", "selections": {role: "or:" + role for role in ROLES}}]}
        for role in ROLES:
            document["options"][role] = [
                {"key": "native:" + NATIVE_KEYS[role], "native_key": NATIVE_KEYS[role], "name": "Native"},
                {"key": "or:" + role, "model_id": "deepseek/deepseek-v4-flash-0731", "name": "Reviewed " + role}]
            document["selections"][role] = "or:" + role
        (self.root / "config/llm_roles.json").write_text(json.dumps(document), encoding="utf-8")
        self.config()
        self.memory = MemoryRuntime(self.root / "memory_f/live", lambda events, chunk: {"native": True},
                                    lambda texts, task: [[1.] + [0.] * 767 for t in texts])
        self.addCleanup(self.memory.close)
        self.meter = UsageMeter(self.root / "memory_f/usage.sqlite", {"models": {}}, budget_usd=1)
        self.g = {"AVAILABLE_MODELS": {key: {"name": key, "provider": "native", "model": key} for key in NATIVE_KEYS.values()},
                  "_ws_active_lock": threading.RLock(), "_ws_active": {}, "_thinking_inflight": 0,
                  "http_requests": requests, "OPENROUTER_KEY": "fake-key", "parse_response": lambda raw: [],
                  "_pick_stream": lambda p, c, **kw: iter(["native"]),
                  "_openai_messages": lambda p, **kw: [{"role": "user", "content": p["user_content"]}],
                  "app": Flask("test"), "request": request, "jsonify": jsonify, "__file__": str(self.root / "brain" / "webui.py")}
        @contextlib.contextmanager
        def scope(phase, turn_id="", **kwargs):
            yield
        self.manager = install_roles(self.g, self.root, self.memory, self.meter, scope, threading.local(), {})
        with contextlib.redirect_stdout(None):
            f_compat.install_compat(self.g)
        self.web = self.g["app"].test_client()
        self.manager.set({"surface": "surface:compat:fast", "deep": "deep:compat:big-off",
                          "reflection": "reflection:compat:big-on", "memory_write": "memory_write:compat:big-on"})

    def config(self, *, big_url=None, key_base_url=None):
        save_compat_config(self.root, {"base_url": self.fast.url, "key_base_url": key_base_url, "detected_at": "t", "models": [
            {"name": "fast"},
            {"name": "big-on", "served_name": "big", "base_url": big_url or self.big.url,
             "chat_template_kwargs": {"enable_thinking": True}, "thinking_tokens": 2048},
            {"name": "big-off", "served_name": "big", "base_url": big_url or self.big.url,
             "chat_template_kwargs": {"enable_thinking": False}}]})

    def turn(self, role, model):
        parts = {"user_content": "u", "_f_phase": role}
        return "".join(self.g["_pick_stream"](parts, self.g["AVAILABLE_MODELS"][f"{role}:compat:{model}"]))

    def test_each_role_reaches_its_own_server_with_its_own_options(self):
        self.assertEqual(self.turn("surface", "fast"), "status: from fast")
        self.assertEqual(self.turn("deep", "big-off"), "from big")
        result = self.g["F_ROLE_COMPLETE"]("reflection", [{"role": "user", "content": "u"}])
        self.assertEqual(result["text"], "from big")
        fast, (deep, reflection) = self.fast.chats(), self.big.chats()
        self.assertEqual(len(fast), 1)
        self.assertEqual(fast[0]["path"], "/v1/chat/completions")
        self.assertEqual(fast[0]["body"]["model"], "fast")
        self.assertNotIn("chat_template_kwargs", fast[0]["body"])
        self.assertEqual((deep["body"]["model"], deep["body"]["chat_template_kwargs"]), ("big", {"enable_thinking": False}))
        self.assertEqual((reflection["body"]["model"], reflection["body"]["chat_template_kwargs"]), ("big", {"enable_thinking": True}))
        self.assertEqual(reflection["body"]["max_tokens"], f_compat.ANSWER_TOKENS["reflection"] + 2048)
        self.assertEqual(self.meter.summary()["active_requests"], 0)

    def test_a_key_that_is_bound_to_no_address_reaches_no_server(self):
        with patch.dict("os.environ", {"OPENAI_API_KEY": "sk-from-the-environment", KEY_ENV: "sk-other"}):
            self.turn("surface", "fast")
            self.turn("deep", "big-off")
            self.g["F_ROLE_COMPLETE"]("reflection", [{"role": "user", "content": "u"}])
            self.web.get("/api/build_f/compat")
        seen = self.fast.requests + self.big.requests
        self.assertGreaterEqual(len(seen), 5)
        self.assertEqual({r["auth"] for r in seen}, {None})

    def test_the_key_reaches_only_its_bound_address(self):
        with patch.dict("os.environ", {KEY_ENV: "sk-secret"}):
            self.config(key_base_url=self.fast.url)
            self.manager.reload_compat()
            self.turn("surface", "fast")
            self.turn("deep", "big-off")
            self.web.get("/api/build_f/compat")
            self.assertEqual({r["auth"] for r in self.fast.requests}, {"Bearer sk-secret"})
            self.assertEqual({r["auth"] for r in self.big.requests}, {None})
            self.config(key_base_url=self.big.url)
            self.manager.reload_compat()
            self.turn("surface", "fast")
            self.turn("deep", "big-off")
            self.assertIsNone(self.fast.chats()[1]["auth"])
            self.assertEqual(self.big.chats()[1]["auth"], "Bearer sk-secret")

    def test_these_calls_cost_nothing_and_the_ledger_says_so(self):
        self.turn("surface", "fast")
        receipt = json.loads(next((self.root / "memory_f/compat_receipts").glob("*.json")).read_text(encoding="utf-8"))
        self.assertEqual((receipt["status"], receipt["cost_usd"], receipt["usage"]["cost_source"]), ("complete", 0.0, "local"))
        self.assertEqual(self.meter.summary()["active_requests"], 0)

    def test_a_reported_charge_reaches_the_usage_meter(self):
        charged = LlmStub(["paid"], "status: paid", usage={"prompt_tokens": 5, "completion_tokens": 1,
                                                          "cost_in_usd_ticks": 2500000})
        self.addCleanup(charged.close)
        self.config(big_url=charged.url)
        self.manager.reload_compat()
        # The stand-in listens on the loopback; it is taken as a hosted server here, as an https one would be.
        with patch.object(f_compat, "is_local", lambda base_url: False):
            self.turn("deep", "big-off")
        receipt = json.loads(next((self.root / "memory_f/compat_receipts").glob("*.json")).read_text(encoding="utf-8"))
        self.assertEqual((receipt["status"], receipt["cost_usd"], receipt["usage"]["cost_source"]), ("complete", 0.00025, "provider"))
        with patch.object(f_compat, "is_local", lambda base_url: False):
            self.turn("surface", "fast")                                    # a hosted server that reports no charge
        self.turn("surface", "fast")                                        # a local one
        with self.meter._connect() as conn:
            rows = conn.execute("SELECT status, cost_usd, cost_source FROM requests ORDER BY rowid").fetchall()
        self.assertEqual([(row["status"], row["cost_usd"], row["cost_source"]) for row in rows],
                         [("complete", 0.00025, "provider_reported"), ("complete", 0.0, "snapshot_rates"),
                          ("complete", 0.0, "snapshot_rates")])
        self.assertEqual(self.meter.summary()["active_requests"], 0)

    def test_a_server_that_is_down_fails_only_its_own_role(self):
        self.config(big_url=unused_url())
        self.manager.reload_compat()
        with self.assertRaises(Exception) as caught:
            self.turn("deep", "big-off")
        down = self.manager.compat["models"][1]["base_url"]
        self.assertEqual(describe_error(caught.exception), f"Your model server: nothing answers at {down} — is it running?")
        self.assertRegex(type(caught.exception).__name__ + ": ", f_memory.TRANSIENT_ERROR)    # memory jobs try again later
        self.assertEqual(self.turn("surface", "fast"), "status: from fast")
        self.assertEqual(self.meter.summary()["active_requests"], 0)

    def test_a_switch_while_she_is_answering_waits_for_unlock(self):
        use = lambda body: self.web.post("/api/build_f/compat/use", json=body, headers={"X-Build-F-Action": "compat-use"})
        self.g["_ws_active"]["t1"] = {}
        reply = use({"model": "fast"})
        self.assertEqual((reply.status_code, reply.get_json()["code"], reply.get_json()["busy"]),
                         (409, "model_busy", ["she is answering"]))
        self.assertEqual(self.manager.selections["deep"], "deep:compat:big-off")
        reply = use({"model": "fast", "force": True})                 # what the page sends after Unlock
        self.assertEqual((reply.status_code, reply.get_json()["in_use"]["deep"]), (200, "fast"))
        self.assertEqual(use({"model": "fast", "force": "yes"}).status_code, 400)

    def test_the_status_route_reports_each_server_the_roles_use(self):
        reply = self.web.get("/api/build_f/compat").get_json()
        self.assertTrue(reply["reachable"])
        self.assertEqual({s["base_url"]: (s["reachable"], sorted(s["roles"])) for s in reply["servers"]},
                         {self.fast.url: (True, ["surface"]), self.big.url: (True, ["deep", "memory_write", "reflection"])})
        self.config(big_url=unused_url())
        self.manager.reload_compat()
        rows = {s["base_url"]: s["reachable"] for s in self.web.get("/api/build_f/compat").get_json()["servers"]}
        self.assertEqual(sorted(rows.values()), [False, True])
        self.assertTrue(rows[self.fast.url])


if __name__ == "__main__":
    unittest.main()
