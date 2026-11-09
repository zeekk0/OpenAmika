"""Prompt assembly through the real brain code (CONTRACT §2, §3.1, §3.2, §3.6, §3.9, §7; R4/R11/R15/R19).

The prompt builders are AST-extracted from payload/webui.py (the technique of
replay/rebuild_prompt_buildf.py, generalised in _po_support.extract_webui) and run
offline against the real prompts/ templates and scenes.json, with fixture memory text,
a fixture history (five finished turns, t2 with a blurt and t4 an open-cue turn, plus
the current turn) and a frozen clock (Friday 21:30 Asia/Tokyo, context_hour=21).

Final layout (CONTRACT §2.1, owner decision 2026-09-27): static prefix | {daily_context}
{current_scene} {current_time} {memories_block} {conversation_history} {pending_mind}
{blurt_block} {say_marker} {deep_instruction} {language_line}.

Asserted:
  - no leftover placeholders in any of the three prompts; system == static + dynamic;
  - parts["system_static"] byte-identical across two turns with different memory/history;
  - the five deep variants (normal, blurt, interrupt, interrupt+blurt, pending-mind) are
    byte-identical through {conversation_history} (the two interrupt variants differ only in
    the history's last line, which is the interrupt sentence) and all differ after it;
  - daily context, scene and time line precede the memory block, which precedes the history;
  - deep history: her speech carries emotion tags, 我心想 only on the last 3 turns;
    surface history: second person, no tags, no thoughts;
  - [Context supplied for this turn] sits before {pending_mind}; the language line stays
    the last non-empty line;
  - surface: no `recall`, {detected_lang} filled, relationship_context from scenes.json
    surface.context;
  - reflection prompt ends with its single closing line;
  - the four deep instruction lines end with 以及你的想法和动作。; USER_CONTENT has no
    `用和对方一样的语种` clause.
"""
import inspect
import json
import re
import sys
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _po_support import PROMPTS, extract_webui, pending_on, prepare_prompt_namespace  # noqa: E402
import po_contract as pc  # noqa: E402

CURRENT_USER = "Do you remember what I said about the Glass Orchard draft?"
INTERRUPT_BODY = '当我说到“Then take me along”的时候，对方说：“Wait, hold on, one thing first.”'
BLURT = "Hmm, the draft…"
PENDING = "他为什么突然问起那份稿子"
ROUND_CONTEXT = "CTX-MARKER: the stream title changed to 'Late night chat'."
MEM_A = "〔记忆A〕三个月前的上午，Alex说：“I finally finished the Glass Orchard draft.”"
MEM_B = "〔记忆B〕两周前的晚上，我回他：“Take me to the café by the river.”"
DEEP_REQUEST = "他问我记不记得那份稿子，我拿不准要不要提他上次的截止日。"
INSTRUCTION_END = "以及你的想法和动作。"
REFLECTION_CLOSING_START = "请按上面约定的格式输出"
DEEP_HISTORY_HEADER = "[之前的对话]"
SURFACE_HISTORY_HEADER = "[最近对话]"


def _t(n, user, deep_raw, surface="", mode="think", **extra):
    turn = {"turn_id": f"t{n}", "turn_num": n, "ts": f"2026-09-25 20:{10 + 3 * n:02d}:00", "user": user,
            "f_user_text": user, "surface_reply": surface, "f_surface_mode": mode, "deep_raw": deep_raw,
            "reply_lang": "en", "reply_lang_reason": "detected"}
    turn.update(extra)
    return turn


TURNS = [
    _t(1, "Hey Amika, are you there?", '[casual_happy]"Yeah, I\'m here. Long day?"\n我心想：THINK-1 他今天来得挺早。'),
    _t(2, "I finally finished the Glass Orchard draft.",
       '[casual_surprise]"You actually finished it?"[casual_playful]"Took you long enough."\n我心想：THINK-2 他终于写完了。',
       surface="Wait, really?", mode="say+think"),
    _t(3, "Mm.", '[casual_neutral]"So what now?"\n我心想：THINK-3 他好像还有话。'),
    _t(4, "", '[casual_smile]"Oh, by the way, did you ever try that café by the river?"\n我心想：THINK-4 突然想起来了。',
       open_cue="（她想起他提过河边那家咖啡店，主动开口。）", mode=""),
    _t(5, "Not yet, maybe this weekend.", '[casual_happy]"Then take me along, at least in a photo."\n我心想：THINK-5 有点期待。'),
]
SPEECH = {t["turn_id"]: [s["text"] for s in pc.extract_deep(t["deep_raw"])["segments"]] for t in TURNS}


def fixture_turns(done=5, interrupt=False):
    turns = [dict(t) for t in TURNS[:done]]
    user = "&" + INTERRUPT_BODY if interrupt else CURRENT_USER
    turns.append({"turn_id": "now", "turn_num": done + 1, "ts": "2026-09-25 21:30:00", "user": user,
                  "f_user_text": INTERRUPT_BODY if interrupt else CURRENT_USER})
    return turns


def non_empty_lines(text):
    return [ln for ln in (text or "").splitlines() if ln.strip()]


def turns_in(text):
    """Fixture turn ids whose first spoken segment appears in `text`."""
    return [tid for tid, segs in SPEECH.items() if segs and segs[0] in text]


def line_end(text, pos):
    nl = text.find("\n", pos)
    return len(text) if nl == -1 else nl


@pending_on("brain")
class PromptAssemblyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        ns = prepare_prompt_namespace(extract_webui())
        cls.ns = ns
        cls.state = {"memory": MEM_A, "turns": fixture_turns()}
        cls.interrupt_marker = ns.get("INTERRUPT_MARKER", "&")
        orig_fill = ns.get("_fill_deep_defaults")

        def fill(template, *args, **kw):
            if kw.get("memories_override") is None:
                kw["memories_override"] = cls.state["memory"]
            try:
                params = inspect.signature(orig_fill).parameters
            except (TypeError, ValueError):
                params = {}
            if kw.get("context_hour") is None and "context_hour" in params:
                kw["context_hour"] = 21
            return orig_fill(template, *args, **kw)
        if orig_fill is not None:
            ns["_fill_deep_defaults"] = fill
        ns["build_memories_block"] = lambda *a, **k: cls.state["memory"]
        ns["_unconsolidated_turns"] = lambda *a, **k: list(cls.state["turns"])
        ns["THINKING_LOG"].extend([
            {"id": "think-1", "after_turn_num": 2, "deep_request": "他写完稿子了，我该怎么接？",
             "analysis": "轻松接住。", "channels": ["提示"], "提示": "夸他一句再逗他。", "计划": "", "开口": ""},
        ])

    def setUp(self):
        self._set()

    # ------------------------------------------------------------------ helpers
    def _set(self, memory=MEM_A, done=5, interrupt=False, pending=None):
        self.state["memory"] = memory
        self.state["turns"] = fixture_turns(done=done, interrupt=interrupt)
        self.ns["CONVERSATION_HISTORY"][:] = self.state["turns"]
        self.ns["_pending_think"] = pending

    def _lang_kwargs(self, lang="en", reason="detected"):
        params = inspect.signature(self.ns["build_messages"]).parameters
        if "reply_lang" in params:
            kw = {"reply_lang": lang}
            if "reply_lang_reason" in params:
                kw["reply_lang_reason"] = reason
            return kw
        if "lang_line" in params:
            return {"lang_line": pc.language_line(lang, reason)}
        return {}

    def deep(self, memory=MEM_A, blurt=None, interrupt=False, done=5, pending=None):
        self._set(memory, done, interrupt, pending)
        user = self.interrupt_marker + INTERRUPT_BODY if interrupt else CURRENT_USER
        return self.ns["build_messages"](user, blurted_reply=blurt, **self._lang_kwargs())

    def surface(self, memory=MEM_A, done=5):
        self._set(memory, done)
        return self.ns["build_surface_messages"](CURRENT_USER)

    def reflection(self, memory=MEM_A, done=5):
        self._set(memory, done)
        return self.ns["build_thinking_messages"](DEEP_REQUEST)

    def variants(self):
        return {"normal": self.deep(), "blurt": self.deep(blurt=BLURT), "interrupt": self.deep(interrupt=True),
                "interrupt+blurt": self.deep(blurt=BLURT, interrupt=True), "pending-mind": self.deep(pending=PENDING)}

    def history_region(self, system, memory, current=CURRENT_USER):
        """History block text. cache_p1p2 layout (2026-10): the history — ending with the
        current user line — comes BEFORE the memory block; the region starts after the
        time line and stops at the current line."""
        end = system.index(memory)
        starts = [system.index(c) + len(c) for c in self._time_lines() if c and c in system[:end]]
        start = max(starts) if starts else 0
        return system[start:line_end(system, system.rindex(current, 0, end))]

    # -------------------------------------------------------------------- tests
    def test_extraction_found_the_builders(self):
        for name in ("build_messages", "build_surface_messages", "build_thinking_messages", "_fill_deep_defaults",
                     "build_deep_history", "build_surface_history", "_with_round_context"):
            self.assertIn(name, self.ns, f"{name} not extracted from webui.py")

    def test_no_leftover_placeholders(self):
        prompts = dict(self.variants())
        prompts["surface"] = self.surface()
        prompts["reflection"] = self.reflection()
        for label, parts in prompts.items():
            self.assertEqual(pc.leftover_placeholders(parts["system"]), [], f"{label}: system has leftovers")
            self.assertEqual(pc.leftover_placeholders(parts.get("user_content", "")), [], f"{label}: user_content")

    def test_parts_split_for_all_roles(self):
        for label, parts in (("deep", self.deep()), ("surface", self.surface()), ("reflection", self.reflection())):
            for key in ("system_static", "system_dynamic", "system", "user_content"):
                self.assertIn(key, parts, f"{label}: parts[{key!r}] missing (CONTRACT §3.2)")
            self.assertEqual(parts["system"], parts["system_static"] + parts["system_dynamic"], label)
            self.assertNotIn(MEM_A, parts["system_static"], f"{label}: memory inside the static prefix")
            self.assertIn(MEM_A, parts["system_dynamic"], f"{label}: fixture memory not in the prompt")

    def test_static_prefix_identical_across_turns(self):
        pairs = {
            "deep": (self.deep(memory=MEM_A, done=5), self.deep(memory=MEM_B, done=2)),
            "surface": (self.surface(memory=MEM_A, done=5), self.surface(memory=MEM_B, done=2)),
            "reflection": (self.reflection(memory=MEM_A, done=5), self.reflection(memory=MEM_B, done=2)),
        }
        for label, (a, b) in pairs.items():
            self.assertIn(MEM_A, a["system"], label)
            self.assertIn(MEM_B, b["system"], label)
            self.assertNotEqual(a["system_dynamic"], b["system_dynamic"], label)
            self.assertEqual(a["system_static"], b["system_static"], f"{label}: static prefix changed between turns")
            for marker in ("THINK-", "Glass Orchard", "〔记忆", "Long day?"):
                self.assertNotIn(marker, a["system_static"], f"{label}: per-turn text {marker!r} in the static prefix")

    def test_dynamic_order_time_memory_history(self):
        scenes = json.loads(pc.read_text_bom(PROMPTS / "scenes.json"))
        scene = scenes["deep"]["current_scene"]["weekday/晚上"].strip()
        for label, parts in (("deep", self.deep()), ("surface", self.surface()), ("reflection", self.reflection())):
            system = parts["system"]
            time_candidates = [c for c in self._time_lines() if c and c in system]
            self.assertTrue(time_candidates, f"{label}: no time line found")
            t_pos = system.index(time_candidates[0])
            m_pos = system.index(MEM_A)
            self.assertLess(t_pos, m_pos, f"{label}: the time line must precede the memory block")
            if label != "surface":
                self.assertIn(scene[:30], system, f"{label}: current scene (weekday/晚上) missing")
                self.assertLess(system.index(scene[:30]), t_pos, f"{label}: scene must precede the time line")
            if label != "reflection":
                first_turn = system.index(SPEECH["t5"][0])
                self.assertLess(first_turn, m_pos,
                                f"{label}: history must precede the memory block (cache_p1p2 layout)")
            self.assertGreaterEqual(t_pos, len(parts.get("system_static", "")), f"{label}: time line in the static prefix")

    def _time_lines(self):
        out = []
        if "_local_time_str" in self.ns:
            out.append(self.ns["_local_time_str"]())
        if "_display_hour" in self.ns:
            period, dh = self.ns["_display_hour"](21)
            out.append(f"大约是{period}{dh}点左右。")
        return out

    def test_five_deep_variants_differ_only_after_history(self):
        v = self.variants()
        ends = {}
        for label, parts in v.items():
            system = parts["system"]
            current = INTERRUPT_BODY if "interrupt" in label else CURRENT_USER
            cur_pos = system.rindex(current)
            line_start = system.rfind("\n", 0, cur_pos) + 1
            ends[label] = (line_start, line_end(system, cur_pos))
        normal = v["normal"]["system"]
        base_hist = normal[:ends["normal"][1]]
        base_before_current = normal[:ends["normal"][0]]
        for label in ("blurt", "pending-mind"):
            system = v[label]["system"]
            self.assertEqual(system[:ends[label][1]], base_hist,
                             f"{label}: differs from normal before the end of {{conversation_history}}")
        for label in ("interrupt", "interrupt+blurt"):
            system = v[label]["system"]
            self.assertEqual(system[:ends[label][0]], base_before_current,
                             f"{label}: differs from normal before the current (interrupt) line")
        self.assertEqual(v["interrupt"]["system"][:ends["interrupt"][1]],
                         v["interrupt+blurt"]["system"][:ends["interrupt+blurt"][1]],
                         "interrupt variants differ inside {conversation_history}")
        suffixes = {label: parts["system"][ends[label][1]:] for label, parts in v.items()}
        labels = list(suffixes)
        for i, a in enumerate(labels):
            for b in labels[i + 1:]:
                if {a, b} == {"normal", "interrupt"} or {a, b} == {"blurt", "interrupt+blurt"}:
                    self.assertNotEqual(v[a]["system"], v[b]["system"], f"variants {a} and {b} are identical")
                    continue
                self.assertNotEqual(suffixes[a], suffixes[b], f"variants {a} and {b} have the same tail")
        for label in ("blurt", "interrupt+blurt"):
            self.assertIn(BLURT, suffixes[label], f"{label}: blurt paragraph missing")
            self.assertIn("我接着说：\n我心想：", suffixes[label], label)
        for label in ("normal", "interrupt", "pending-mind"):
            self.assertIn("我说：\n我心想：", suffixes[label], label)
            self.assertNotIn("我接着说：\n我心想：", suffixes[label], label)
            self.assertNotIn(BLURT, suffixes[label], label)
        self.assertIn(PENDING, suffixes["pending-mind"])
        self.assertNotIn(PENDING, suffixes["normal"])

    def test_instruction_lines(self):
        v = self.variants()
        instr = {}
        for label in ("normal", "blurt", "interrupt", "interrupt+blurt"):
            system = v[label]["system"]
            self.assertNotIn("[模版]", system, label)
            lines = non_empty_lines(system)
            # {deep_instruction} is the line right before {language_line} (CONTRACT §2.1)
            self.assertTrue(lines[-2].strip().endswith(INSTRUCTION_END), f"{label}: instruction line {lines[-2]!r}")
            instr[label] = lines[-2].strip()
        self.assertEqual(len(set(instr.values())), 4, f"the four instruction variants are not distinct: {instr}")

    def test_user_content_has_no_language_clause(self):
        for label, parts in self.variants().items():
            self.assertNotIn("用和对方一样的语种", parts["user_content"], label)

    def test_language_line_is_last(self):
        want = pc.language_line("en", "detected")
        for label, parts in self.variants().items():
            self.assertEqual(non_empty_lines(parts["system"])[-1].strip(), want, f"{label}: last line is not the language line")
            self.assertEqual(parts["system"].count(want), 1, label)

    def test_round_context_sits_before_pending_mind(self):
        want = pc.language_line("en", "detected")
        wrap = self.ns["_with_round_context"]
        for label, parts, anchor in (("pending-mind", self.deep(pending=PENDING), PENDING),
                                     ("blurt", self.deep(blurt=BLURT), BLURT),
                                     ("normal", self.deep(), "我说：\n我心想：")):
            out = wrap(parts, ROUND_CONTEXT)
            system = out["system"]
            self.assertIn("[Context supplied for this turn]", system, label)
            self.assertIn(ROUND_CONTEXT, system, label)
            ctx = system.index("[Context supplied for this turn]")
            self.assertLess(ctx, system.rindex(anchor), f"{label}: round context after the per-turn tail")
            self.assertGreater(ctx, system.rindex(CURRENT_USER), f"{label}: round context before the current line")
            self.assertEqual(non_empty_lines(system)[-1].strip(), want, f"{label}: language line no longer last")
            if "system_dynamic" in out:
                self.assertEqual(system, out["system_static"] + out["system_dynamic"], label)
                self.assertEqual(out["system_static"], parts["system_static"], label)
        plain = self.deep()
        self.assertNotIn("[Context supplied for this turn]", wrap(plain, "")["system"], "empty context adds a block")

    def test_deep_history_tags_and_recent_thoughts(self):
        parts = self.deep()
        system = parts["system"]
        region = self.history_region(system, MEM_A)
        completed = [t["turn_id"] for t in TURNS]
        self.assertEqual(turns_in(region), completed, "every finished turn in the history block, in order")
        for t in TURNS:
            for seg in pc.extract_deep(t["deep_raw"])["segments"]:
                # telemetry_history update: history speech renders as 我说："…" without
                # per-segment tone tags (the tag rules live in the static prefix).
                self.assertIn(seg["text"], region, f"{t['turn_id']}: speech missing from the history")
        shown = [tid for tid in completed if f"THINK-{tid[1:]}" in region]
        self.assertNotIn("t1", shown, "我心想 of an old turn (t1) rendered")
        self.assertNotIn("t2", shown, "我心想 of an old turn (t2) rendered")
        self.assertIn("t5", shown, "我心想 of the most recent turn missing")
        self.assertIn(len(shown), (2, 3), f"我心想 shown for {shown}")
        self.assertEqual(shown, completed[-len(shown):], "我心想 only on the last turns")
        self.assertLessEqual(region.count("我心想"), 3)
        self.assertIn(CURRENT_USER, region.splitlines()[-1], "the history ends with the current line")
        self.assertEqual(system.count(DEEP_HISTORY_HEADER), 1, "deep history header once")
        self.assertNotRegex(region, r"对方说：\s*\n", "the open-cue turn rendered an empty 对方说 line")

    def test_surface_prompt(self):
        parts = self.surface()
        blob = parts["system"] + "\n" + parts.get("user_content", "")
        self.assertIsNone(re.search(r"recall", blob, re.I), "surface prompt mentions recall")
        self.assertIn("对方说的语言是ENGLISH", parts["system"])
        self.assertIn(MEM_A, parts["system"])
        # R17 / CONTRACT §2.4: the surface {relationship_context} comes from scenes.json surface.context
        scenes = json.loads(pc.read_text_bom(PROMPTS / "scenes.json"))
        # persona files may use the {user_name} / {city} tokens; the brain substitutes them at load
        city = self.ns["_city_text"]() if "_city_text" in self.ns else (self.ns.get("CITY") or "这座城市")
        surface_ctx = scenes["surface"]["context"].replace(
            "{user_name}", self.ns.get("USER_NAME") or "User").replace("{city}", city).strip()
        self.assertIn(surface_ctx, parts.get("system_static", parts["system"]))

    def test_korean_resolved_target_agrees_across_tiers(self):
        for text, lang, reason in (("Please reply in Korean", "ko", "switch"),
                                   ("…", "ko", "inherited"),
                                   ("한국어로 이야기하자", "ko", "detected"),
                                   ("Please continue", "en", "detected")):
            surface = self.ns["build_surface_messages"](text, reply_lang=lang)
            deep = self.ns["build_messages"](text, reply_lang=lang, reply_lang_reason=reason)
            self.assertIn("对方说的语言是" + {"ko": "KOREAN", "en": "ENGLISH"}[lang], surface["system"])
            self.assertEqual(non_empty_lines(deep["system"])[-1], pc.language_line(lang, reason))

    def test_korean_previous_turn_skips_one_turn_switch(self):
        self.ns["CONVERSATION_HISTORY"][:] = [
            _t(1, "한국어로 이야기하자", "", protected=True, reply_lang="ko"),
            _t(2, "영어로 말해 줘", "", protected=True, reply_lang="en", reply_lang_reason="switch")]
        self.assertEqual(self.ns["_prev_reply_lang"](), "ko")
        self.assertEqual(self.ns["_inherited_reply_lang"](), ("ko", "inherited"))

    def test_korean_actual_generation_target_and_metadata(self):
        ns, prompts, emitted = self.ns, [], []
        self.state["turns"] = []
        ns["CONVERSATION_HISTORY"][:] = []

        def create(tid, user):
            turn = _t(len(self.state["turns"]) + 1, user, "", turn_id=tid, protected=True)
            self.state["turns"].append(turn)
            ns["CONVERSATION_HISTORY"].append(turn)
            return turn

        def stream(parts, config):
            prompts.append((config, parts["system"]))
            if config == "surface":
                return iter(["status: ok\ntone: casual_smile\nmode: say+think\nreply: 응."])
            return iter(['[casual_smile]"여기 있어."我心想：他在和我说话。'])

        noop = lambda *a, **k: None
        socket = SimpleNamespace(emit=lambda event, data, **kw: emitted.append((event, data)),
                                 start_background_task=lambda fn, *args: fn(*args))
        overrides = {"socketio": socket, "AVAILABLE_MODELS": {"surface": "surface", "deep": "deep"},
                     "DEFAULT_SURFACE_MODEL": "surface", "DEFAULT_DEEP_MODEL": "deep",
                     "_ws_active": {}, "_ws_active_lock": threading.RLock(),
                     "create_turn": create, "_save_history": noop, "_prune_unprotected": noop,
                     "_pick_stream": stream, "_with_capabilities": lambda parts: parts,
                     "update_turn_surface": noop, "update_turn_deep": noop,
                     "f_mark_complete": noop, "_mark_activity": noop, "_tools_after_turn": noop}
        with patch.dict(ns, overrides):
            steps = [("Please reply in Korean", "ko", "switch"),
                     ("Please continue", "en", "detected"),
                     ("오늘 날씨가 따뜻해서 산책하고 싶어", "ko", "detected"),
                     (None, "ko", "inherited"),
                     ("Please reply in English", "en", "switch"),
                     (None, "ko", "inherited"),
                     ("오늘 날씨가 정말 좋다", "ko", "detected"),
                     ("relay", "ko", "tools")]
            for i, (text, lang, reason) in enumerate(steps):
                prompts.clear()
                emitted.clear()
                if text is None:
                    ns["_start_open_gen"]("sid", "（我想起刚才的话题）", turn_id=str(i))
                elif text == "relay":
                    ns["_start_inject_gen"]("sid", "助手的结果来了", turn_id=str(i), reply_lang="ko")
                else:
                    ns["_start_message_gen"]("sid", text, "", "surface", "deep", turn_id=str(i))
                self.assertFalse([p for e, p in emitted if e == "error"], emitted)
                begin = next(p for e, p in emitted if e == "begin")
                self.assertEqual((begin["reply_lang"], begin["reply_lang_reason"]), (lang, reason))
                self.assertEqual(prompts[-1][0], "deep")
                self.assertEqual(non_empty_lines(prompts[-1][1])[-1], pc.language_line(lang, reason))
                if text not in (None, "relay"):
                    self.assertIn("对方说的语言是" + {"ko": "KOREAN", "en": "ENGLISH"}[lang], prompts[0][1])
                    surface = next(p for e, p in emitted if e == "surface_done")
                    self.assertEqual((surface["reply_lang"], surface["reply_lang_reason"]), (lang, reason))
                else:
                    self.assertEqual(len(prompts), 1)

    def test_surface_history_has_no_tags_or_thoughts(self):
        system = self.surface()["system"]
        self.assertNotIn("THINK-", system)
        for t in TURNS:
            for seg in pc.extract_deep(t["deep_raw"])["segments"]:
                self.assertNotIn(f"[{seg['tone']}]\"{seg['text']}", system)
                self.assertNotIn(f"[{seg['tone']}]“{seg['text']}", system)
        region = self.history_region(system, MEM_A)
        self.assertEqual(turns_in(region), [t["turn_id"] for t in TURNS], "surface history lost her speech")
        self.assertEqual(system.count(SURFACE_HISTORY_HEADER), 1, "surface history header once")

    def test_reflection_prompt_ends_with_closing_line(self):
        parts = self.reflection()
        last = non_empty_lines(parts["system"])[-1].strip()
        self.assertTrue(last.startswith(REFLECTION_CLOSING_START) and "[分析]" in last, f"last line {last!r}")
        self.assertEqual(parts["system"].count(REFLECTION_CLOSING_START), 1)
        self.assertIn(DEEP_REQUEST, parts["system"])
        self.assertLess(parts["system"].index(DEEP_REQUEST), parts["system"].rindex(REFLECTION_CLOSING_START))


if __name__ == "__main__":
    unittest.main()
