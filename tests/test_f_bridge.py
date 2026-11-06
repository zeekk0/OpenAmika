"""Offline integration tests: real F runtime/meter with fake app and providers."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

PAYLOAD = Path(__file__).resolve().parents[1] / "payload"
if not PAYLOAD.is_dir():
    PAYLOAD = Path(__file__).resolve().parents[1] / "brain"   # repo layout
sys.path.insert(0, str(PAYLOAD))
import f_bridge
from f_method import CandidateF


class FakeApp:
    def __init__(self):
        self.view_functions = {}

    def route(self, path, **kwargs):
        def register(fn):
            self.view_functions[path] = fn
            return fn
        return register


class FakeSocket:
    def __init__(self):
        self.handlers = {}
        self.emits = []

    def emit(self, name, payload, **kwargs):
        self.emits.append((name, payload, kwargs))

    def on_event(self, name, fn):
        self.handlers[name] = fn


class Response:
    def __init__(self, data):
        self.data = data

    def raise_for_status(self):
        pass

    def json(self):
        return copy.deepcopy(self.data)

    def close(self):
        pass


class FakeHTTP:
    def __init__(self):
        self.calls = []

    def post(self, url, **kwargs):
        body = kwargs["json"]
        self.calls.append((url, copy.deepcopy(body)))
        if "batchEmbedContents" in url:
            return Response({"embeddings": [{"values": [1.0] + [0.0] * 767}
                                             for _ in body["requests"]],
                             "usageMetadata": {"promptTokenCount": 20}})
        sources = json.loads(body["messages"][0]["content"])
        source = sources[0]
        record = {"id": "f1", "text": "The user lives in Alder Bay.", "subject": "user",
                  "predicate": "lives_in", "value": "Alder Bay", "source_ids": [source["source_id"]],
                  "date": source["date"][:10], "source_kind": "user", "fact_type": "user_fact",
                  "status": "active", "entities": ["Alder Bay"], "supersedes": [],
                  "replaces_prior": False, "valid_from": None, "valid_to": None,
                  "quotes": [{"source_id": source["source_id"], "speaker": "user",
                              "quote": source["speakers"]["user"]}]}
        return Response({"content": [{"type": "text", "text": json.dumps({"facts": [record]})}],
                         "usage": {"input_tokens": 100, "output_tokens": 80}})


class InlineThread:
    def __init__(self, target, **kwargs):
        self.target = target

    def start(self):
        self.target()


class BridgeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / "config").mkdir()
        (self.root / "brain").mkdir()
        config = {"memory_budget_chars": 8000, "recent_turns": 12, "recent_chars": 16000,
                  "test_budget_usd": 20, "budget_scope": "fake-test"}
        # Include both labels while the integration settles; the receipt must
        # still normalize the provider and recognize actual token usage.
        prices = {"models": {
            "anthropic:claude-sonnet-5": {"input": 2, "output": 10,
                                          "cache_read": .2, "cache_write_5m": 2.5, "cache_write_1h": 4},
            "gemini:gemini-embedding-2": {"input": .2, "output": 0},
            "gemini_embedding:gemini-embedding-2": {"input": .2, "output": 0},
        }}
        for name, value in (("build_f.json", config), ("pricing.json", prices)):
            (self.root / "config" / name).write_text(json.dumps(value), encoding="utf-8")
        self.history = []
        self.http = FakeHTTP()
        self.socket = FakeSocket()
        self.captured = []
        self.g = {"__file__": str(self.root / "brain/webui.py"), "http_requests": self.http,
                  "app": FakeApp(), "socketio": self.socket, "jsonify": lambda value: value,
                  "_hist_lock": threading.RLock(), "_ws_active_lock": threading.RLock(),
                  "CONVERSATION_HISTORY": self.history, "_ws_active": {},
                  "ANTHROPIC_BASE": "https://invalid.example/anthropic", "GEMINI_KEY": "fake-key",
                  "_anthropic_headers": lambda *a: {"x-api-key": "fake-key"},
                  "_anthropic_body": lambda *a, **k: {},
                  "_openai_headers": lambda *a, **k: ("https://invalid.example/openai", {}),
                  "_openai_messages": lambda *a, **k: [],
                  "_save_history": lambda: None,
                  "_parsed_deep": lambda raw: (raw.split("PRIVATE")[0], ""),
                  "_find_turn": lambda tid: next((t for t in self.history if t["turn_id"] == tid), None)}
        self.g["discard_turn"] = lambda tid: self.history.__setitem__(slice(None), [t for t in self.history if t["turn_id"] != tid])

        def fill(template, memories_override=None, **kwargs):
            return template.replace("{memories_block}", memories_override if memories_override is not None else "LEGACY")
        self.g["_fill_deep_defaults"] = fill
        for name in ("build_surface_messages", "build_messages", "build_thinking_messages"):
            self.g[name] = lambda *a, **k: {"system": self.g["_fill_deep_defaults"]("MEMORY: {memories_block}"), "user_content": "hello"}
        self.g["run_thinking_once"] = lambda *a: self.g["build_thinking_messages"]()

        def run(*args):
            self.captured.extend([self.g["build_surface_messages"]("hello"), self.g["build_messages"]("hello")])
            return "done"
        self.g["_ws_run_generation"] = run

        def protect():
            if not self.history:
                return False
            self.history[-1]["protected"] = True
            return True
        self.g["_protect_latest"] = protect

    def tearDown(self):
        self.temp.cleanup()

    def install(self, seeded=False):
        if seeded:
            source = {"id": "seed-e1", "time": "2026-01-01T12:00:00Z", "user": "I live in Alder Bay.",
                      "assistant": "Thank you.", "source_kind": "conversation"}
            CandidateF([source], {"facts": []}, {"documents": {"seed-e1": [1.0] + [0.0] * 767}}).persist(self.root / "config/seed.json")
        f_bridge.install(self.g)

    def turn(self, **overrides):
        value = {"turn_id": "live-test-1", "ts": "2026-01-02 12:00:00", "user": "I live in Alder Bay.",
                 "f_user_text": "I live in Alder Bay.", "surface_reply": "Oh?", "deep_raw": "I see.PRIVATE internal",
                 "f_surface_mode": "say+think", "protected": True, "f_generation_complete": True,
                 "f_speech_done": True}
        value.update(overrides)
        self.history.append(value)
        return value

    def test_install_and_status_are_offline(self):
        self.install(seeded=True)
        result = self.g["app"].view_functions["/api/build_f/status"]()
        self.assertEqual(result["memory"]["events"], 1)
        self.assertEqual(self.http.calls, [])

    def test_completed_public_turn_archives_and_enriches(self):
        self.install()
        turn = self.turn()
        with patch.object(f_bridge.threading, "Thread", InlineThread):
            self.g["f_archive_turn"](turn["turn_id"])
            self.g["f_archive_turn"](turn["turn_id"])
        memory = self.g["F_MEMORY"]
        self.assertEqual(memory.status()["events"], 1)
        self.assertEqual(memory.status()["facts"], 1)
        self.assertEqual(memory.status()["pending"], 0)
        stored = memory.model.events[0]
        self.assertEqual(stored["source_kind"], "conversation")
        self.assertEqual(stored["assistant"], "Oh?\nI see.")
        self.assertNotIn("PRIVATE", json.dumps(stored))
        self.assertEqual(len(self.http.calls), 2)

    def test_interrupted_operator_and_unplayed_turns_are_not_archived(self):
        self.install()
        for i, extra in enumerate(({"interrupted": True}, {"inject_cue": "operator"},
                                   {"f_generation_complete": False}, {"f_speech_done": False})):
            turn = self.turn(turn_id=f"turn-{i}", **extra)
            self.g["f_archive_turn"](turn["turn_id"])
        self.assertEqual(self.g["F_MEMORY"].status()["events"], 0)
        self.assertEqual(self.http.calls, [])

    def test_retrieved_memory_reaches_surface_deep_and_reflection(self):
        self.install(seeded=True)
        turn = self.turn(f_user_text="Where do I live?", f_generation_complete=False)
        entry = {"cancel": threading.Event()}
        self.g["_ws_active"][turn["turn_id"]] = entry
        result = self.g["_ws_run_generation"]("sid", turn["turn_id"], turn["f_user_text"], "surface", "deep", entry)
        self.assertEqual(result, "done")
        reflected = self.g["run_thinking_once"]("check", target_turn_id=turn["turn_id"])
        for parts in [*self.captured, reflected]:
            self.assertIn("Alder Bay", parts["system"])
            self.assertNotIn("LEGACY", parts["system"])
        self.assertEqual({p["_f_phase"] for p in self.captured}, {"surface", "deep"})
        self.assertEqual(reflected["_f_phase"], "reflection")
        self.assertNotIn(turn["turn_id"], self.g["_ws_active"])

    def test_memory_block_carries_heading_only_when_evidence_exists(self):
        self.install(seeded=True)
        turn = self.turn(f_user_text="Where do I live?", f_generation_complete=False)
        entry = {"cancel": threading.Event()}
        self.g["_ws_active"][turn["turn_id"]] = entry
        self.g["_ws_run_generation"]("sid", turn["turn_id"], turn["f_user_text"], "surface", "deep", entry)
        by_phase = {p["_f_phase"]: p for p in self.captured}
        self.assertEqual(set(by_phase), {"surface", "deep"})
        # Deep and reflection get the heading above the evidence; the surface gets the bare block.
        self.assertIn("【记忆记录】", by_phase["deep"]["system"])
        self.assertLess(by_phase["deep"]["system"].index("【记忆记录】"), by_phase["deep"]["system"].index("Alder Bay"))
        self.assertEqual(by_phase["deep"]["system"].count("【记忆记录】"), 1)
        self.assertNotIn("【记忆记录】", by_phase["surface"]["system"])
        self.assertIn("Alder Bay", by_phase["surface"]["system"])
        reflected = self.g["run_thinking_once"]("check", target_turn_id=turn["turn_id"])
        self.assertIn("【记忆记录】", reflected["system"])
        # The stored evidence text stays raw; the heading is added only at prompt time.
        self.assertNotIn("【记忆记录】", turn["f_memory_text"])
        self.assertFalse(hasattr(f_bridge, "_local_role_leak"))
        # No evidence, no heading: outside a retrieval scope the block is empty.
        self.assertEqual(self.g["build_memories_block"](), "")
        self.assertEqual(self.g["_fill_deep_defaults"]("MEMORY: {memories_block}"), "MEMORY: ")
        self.assertEqual(self.g["_fill_deep_defaults"]("MEMORY: {memories_block}", memories_override=""), "MEMORY: ")

    def _query_texts(self):
        return [body["requests"][0]["content"]["parts"][0]["text"]
                for url, body in self.http.calls if "batchEmbedContents" in url
                and body["requests"][0]["content"]["parts"][0]["text"].startswith("task: search result")]

    def test_short_follow_up_anchors_on_last_substantive_user_turn(self):
        self.install(seeded=True)
        substantive = "My batteries came from an agriculture drone project and they cost four thousand dollars each."
        self.turn(turn_id="t-long", f_user_text=substantive)
        self.turn(turn_id="t-short-1", f_user_text="OkayOkay.")
        self.turn(turn_id="t-short-2", f_user_text="Yeah, I told you.")
        turn = self.turn(turn_id="t-now", f_user_text="Do you not remember?", f_generation_complete=False)
        entry = {"cancel": threading.Event()}
        self.g["_ws_active"][turn["turn_id"]] = entry
        self.g["_ws_run_generation"]("sid", turn["turn_id"], turn["f_user_text"], "surface", "deep", entry)
        query = self._query_texts()[-1]
        self.assertIn(substantive, query)
        self.assertIn("Yeah, I told you.", query)
        self.assertIn("Do you not remember?", query)
        self.assertNotIn("OkayOkay.", query)

    def test_heading_can_be_switched_off_by_config(self):
        config = json.loads((self.root / "config" / "build_f.json").read_text(encoding="utf-8"))
        config["memory_block_header"] = ""
        (self.root / "config" / "build_f.json").write_text(json.dumps(config), encoding="utf-8")
        self.install(seeded=True)
        turn = self.turn(f_user_text="Where do I live?", f_generation_complete=False)
        entry = {"cancel": threading.Event()}
        self.g["_ws_active"][turn["turn_id"]] = entry
        self.g["_ws_run_generation"]("sid", turn["turn_id"], turn["f_user_text"], "surface", "deep", entry)
        for parts in self.captured:
            self.assertNotIn("【记忆记录】", parts["system"])
            self.assertIn("Alder Bay", parts["system"])

    def test_korean_recall_cues_reach_substantive_topic_only(self):
        self.install(seeded=True)
        substantive = "지난주에 농업용 드론 프로젝트에서 배터리 네 개를 샀는데 각각 사백만 원이 들었어."
        for cue, recall in (("기억 안 나?", True), ("내가 말했잖아.", True),
                            ("오늘 저녁 뭐 먹을까?", False), ("새로운 영화 이야기하자.", False)):
            with self.subTest(cue=cue):
                self.history.clear()
                self.turn(turn_id="topic", f_user_text=substantive)
                self.turn(turn_id="ack1", f_user_text="응응.")
                self.turn(turn_id="ack2", f_user_text="그래.")
                turn = self.turn(turn_id="now", f_user_text=cue, f_generation_complete=False)
                entry = {"cancel": threading.Event()}
                self.g["_ws_active"]["now"] = entry
                self.g["_ws_run_generation"]("sid", "now", cue, "surface", "deep", entry)
                query = self._query_texts()[-1]
                self.assertEqual(substantive in query, recall)
                if recall:
                    self.assertIn("그래.\n" + cue, query)
                else:
                    self.assertEqual(query, "task: search result | query: " + cue)
                self.assertNotIn("응응.", query)

    def test_self_contained_short_input_does_not_inherit_previous_topic(self):
        self.install(seeded=True)
        self.turn(turn_id="t-long", f_user_text="My batteries came from an agriculture drone project and they cost four thousand dollars each.")
        self.turn(turn_id="t-short", f_user_text="Haha, yeah.")
        turn = self.turn(turn_id="t-now", f_user_text="Where did my sister move?", f_generation_complete=False)
        entry = {"cancel": threading.Event()}
        self.g["_ws_active"][turn["turn_id"]] = entry
        self.g["_ws_run_generation"]("sid", turn["turn_id"], turn["f_user_text"], "surface", "deep", entry)
        query = self._query_texts()[-1]
        self.assertEqual(query, "task: search result | query: Where did my sister move?")

    def test_actual_korean_corrected_recall_questions_do_not_blend_topics(self):
        self.install(seeded=True)
        questions = ["정정한 뒤 나루가 좋아하는 색은 무엇인가요?",
                     "지금 기억하는 다온이의 단골 음료는 무엇인가요?",
                     "정정된 소담이의 취미를 알려 주세요.",
                     "달빛회의 바뀐 모임 요일은 언제인가요?",
                     "정정한 구름방의 연필 수는 몇 개인가요?",
                     "별뜰 가운데 나무의 정정된 종류를 말해 주세요.",
                     "정정된 솔바람의 개점 시각을 알려 주세요.",
                     "여울이의 그림 제목을 정정한 대로 말해 주세요.",
                     "해뜰함의 정정된 리본 색을 말해 주세요.",
                     "정정 후 작은달의 대표 빵은 무엇인가요?"]
        self.turn(turn_id="corpus-last", f_user_text="문구는 hello예요. 이 인사가 주는 느낌을 우리말로 짧게 설명해 주세요.")
        for index, question in enumerate(questions):
            with self.subTest(question=question):
                ident = "recall-" + str(index)
                turn = self.turn(turn_id=ident, f_user_text=question, f_generation_complete=False)
                entry = {"cancel": threading.Event()}
                self.g["_ws_active"][ident] = entry
                self.g["_ws_run_generation"]("sid", ident, question, "surface", "deep", entry)
                self.assertEqual(self._query_texts()[-1], "task: search result | query: " + question)

    def test_multilingual_generic_followups_keep_context_but_named_questions_do_not(self):
        self.install(seeded=True)
        topic = "We discussed the fictional character's favorite color during our last long conversation."
        for question, followup in [("Do you remember?", True), ("你还记得吗？", True),
                                   ("覚えてる？", True), ("기억 안 나?", True),
                                   ("What did I say?", True), ("Did I tell you?", True),
                                   ("Do you remember where my sister moved?", False),
                                   ("你记得小明喜欢什么颜色吗？", False),
                                   ("ナオの好きな色を覚えてる？", False),
                                   ("민수가 좋아하는 색 기억나?", False)]:
            with self.subTest(question=question):
                self.history.clear()
                self.turn(turn_id="topic", f_user_text=topic)
                self.turn(turn_id="ack", f_user_text="Okay.")
                self.turn(turn_id="now", f_user_text=question, f_generation_complete=False)
                entry = {"cancel": threading.Event()}
                self.g["_ws_active"]["now"] = entry
                self.g["_ws_run_generation"]("sid", "now", question, "surface", "deep", entry)
                query = self._query_texts()[-1]
                self.assertEqual(topic in query, followup)
                if not followup:
                    self.assertEqual(query, "task: search result | query: " + question)

    def test_long_input_is_its_own_query_and_lookback_is_bounded(self):
        self.install(seeded=True)
        self.turn(turn_id="t-old", f_user_text="An old substantive topic about the museum trip with my cousin on Sunday afternoon.")
        for i in range(7):
            self.turn(turn_id=f"t-s{i}", f_user_text="Mm.")
        turn = self.turn(turn_id="t-now", f_user_text="Really?", f_generation_complete=False)
        entry = {"cancel": threading.Event()}
        self.g["_ws_active"][turn["turn_id"]] = entry
        self.g["_ws_run_generation"]("sid", turn["turn_id"], turn["f_user_text"], "surface", "deep", entry)
        query = self._query_texts()[-1]
        self.assertNotIn("museum", query)  # beyond the six-turn lookback
        self.assertEqual(query.count("Mm."), 1)
        self.history.clear()
        self.captured.clear()
        long_input = ("I bought a DC to AC inverter and connected it to four drone batteries to run an induction stove "
                      "for noodles at home, and each battery can put out sixteen kilowatts so the four together reach sixty-four.")
        self.turn(turn_id="t-prev", f_user_text="Something short.")
        turn = self.turn(turn_id="t-now2", f_user_text=long_input, f_generation_complete=False)
        entry = {"cancel": threading.Event()}
        self.g["_ws_active"][turn["turn_id"]] = entry
        self.g["_ws_run_generation"]("sid", turn["turn_id"], turn["f_user_text"], "surface", "deep", entry)
        self.assertEqual(self._query_texts()[-1], "task: search result | query: " + long_input)

    def test_embedding_meter_recognizes_usage(self):
        self.install(seeded=True)
        self.g["F_MEMORY"].retrieve("Alder Bay")
        receipt = self.g["F_METER"].summary()["recent_requests"][0]
        self.assertTrue(receipt["usage_complete"], receipt)
        self.assertEqual(receipt["tokens"]["total_input_tokens"], 20)
        self.assertGreater(receipt["cost_usd"], 0)

    def test_cancelled_turn_does_not_start_query_or_generation(self):
        self.install(seeded=True)
        turn = self.turn(f_user_text="Where do I live?", f_generation_complete=False)
        cancel = threading.Event()
        cancel.set()
        self.g["_ws_run_generation"]("sid", turn["turn_id"], turn["f_user_text"], "surface", "deep", {"cancel": cancel})
        self.assertEqual(self.http.calls, [])
        self.assertEqual(self.captured, [])

    def test_cancel_during_query_stops_before_generation(self):
        self.install(seeded=True)
        turn = self.turn(f_user_text="Where do I live?", f_generation_complete=False)
        cancel = threading.Event()
        original_post = self.http.post
        def cancel_after_post(*args, **kwargs):
            response = original_post(*args, **kwargs)
            cancel.set()
            return response
        self.http.post = cancel_after_post
        self.g["_ws_run_generation"]("sid", turn["turn_id"], turn["f_user_text"], "surface", "deep", {"cancel": cancel})
        self.assertEqual(len(self.http.calls), 1)
        self.assertEqual(self.captured, [])

    def test_recent_history_bound_and_reflection_endpoint(self):
        self.install()
        for number in range(20):
            self.turn(turn_id=f"turn-{number}")
        # The reflected target should see its own bounded historical prefix,
        # excluding user messages that arrived while reflection was queued.
        self.g["build_thinking_messages"] = lambda: {"ids": [t["turn_id"] for t in self.g["_unconsolidated_turns"]()]}
        result = self.g["run_thinking_once"]("check", target_turn_id="turn-15")
        # telemetry_history/cache_p1p2 updates: reflection sees the full unconsolidated
        # prefix up to its target turn; the window bound now applies at prompt build.
        self.assertEqual(result["ids"], [f"turn-{n}" for n in range(16)])
        self.assertEqual(result["ids"][-1], "turn-15")
        self.assertNotIn("turn-16", result["ids"])


if __name__ == "__main__":
    unittest.main()
