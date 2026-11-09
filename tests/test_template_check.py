"""Template anchor self-check on the real prompt files (CONTRACT §1.4, §1.5, §2, §7; R2).

`po_contract.check_template_dir(prompts/)` must report no problems, and the layout rules of
CONTRACT §2 that the checker does not cover are asserted here directly.
"""
import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _po_support import PROMPTS, pending_on  # noqa: E402
import po_contract as pc  # noqa: E402

FILES = {"deep": "例子.txt", "surface": "表层.txt", "thinking": "思考.txt"}
SCENE_PLACEHOLDERS = {"recent_mood", "current_action", "relationship_context", "communication_style"}
# Anything shaped like a template placeholder ({name}); JSON-ish braces in prose are ignored.
PLACEHOLDER_RE = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")
# CONTRACT §2.3 describes the closing line as `[one closing line: 请按上面约定的格式输出：先写指导，
# [分析] 放最后。]`. The wording inside the bracket is read as a description, so the check is on
# its content (format reminder, guidance first, [分析] last) and on it being one single line.
REFLECTION_CLOSING_START = "请按上面约定的格式输出"


def is_reflection_closing(line):
    line = line.strip()
    return (line.startswith(REFLECTION_CLOSING_START) and "先写指导" in line and "[分析]" in line
            and line.rfind("最后") > line.find("[分析]"))
SFX_BAD_EXAMPLE = '[casual_happy]"哈哈【声效名】"'


def read(name):
    return (PROMPTS / name).read_bytes().decode("utf-8")


def non_empty_lines(text):
    return [ln for ln in text.splitlines() if ln.strip()]


@pending_on("templates")
class TemplateCheckTests(unittest.TestCase):
    def test_check_template_dir_reports_no_problems(self):
        result = pc.check_template_dir(PROMPTS)
        self.assertEqual(set(result), set(FILES.values()))
        problems = {name: p for name, p in result.items() if p}
        self.assertEqual(problems, {}, "po_contract --check-templates problems:\n" + "\n".join(
            f"{name}: {p}" for name, ps in problems.items() for p in ps))

    def test_each_placeholder_appears_once(self):
        for kind, name in FILES.items():
            text = read(name)
            counts = {}
            for n in PLACEHOLDER_RE.findall(text):
                counts[n] = counts.get(n, 0) + 1
            # identity tokens ({user_name}, {city}) are prose, and may be used as often as the story needs
            repeated = {n: c for n, c in counts.items() if c > 1 and n not in pc.IDENTITY_PLACEHOLDERS}
            self.assertEqual(repeated, {}, f"{name}: placeholders repeated")
            required = {"deep": pc.DEEP_REQUIRED, "surface": pc.SURFACE_REQUIRED, "thinking": pc.THINKING_REQUIRED}[kind]
            self.assertEqual([n for n in required if counts.get(n) != 1], [], f"{name}: required placeholders not exactly once")

    def test_tsundere_example_kept_verbatim(self):
        self.assertIn(pc.TSUNDERE_EXAMPLE, read(FILES["deep"]))

    def test_surface_has_no_recall(self):
        text = read(FILES["surface"])
        hits = [ln.strip() for ln in text.splitlines() if re.search(r"recall", ln, re.I)]
        self.assertEqual(hits, [], "表层.txt still mentions recall")

    def test_static_region_has_only_scene_placeholders(self):
        for name in FILES.values():
            text = read(name)
            self.assertIn("{daily_context}", text, f"{name}: no {{daily_context}} split point")
            static, _ = pc.split_static(text)
            # identity tokens ({user_name}, {city}) are prose and belong to the static prefix too
            found = set(PLACEHOLDER_RE.findall(static)) - set(pc.IDENTITY_PLACEHOLDERS)
            self.assertEqual(found - SCENE_PLACEHOLDERS, set(),
                             f"{name}: placeholders before {{daily_context}} other than the four scene ones")
            self.assertEqual(found, SCENE_PLACEHOLDERS, f"{name}: the four scene placeholders belong before {{daily_context}}")


@pending_on("templates")
class TemplateLayoutTests(unittest.TestCase):
    """CONTRACT §1.5 / §2 details that check_template() does not look at."""

    def test_deep_language_line_is_last(self):
        self.assertEqual(non_empty_lines(read(FILES["deep"]))[-1].strip(), "{language_line}")

    def test_dynamic_order(self):
        """CONTRACT §2.1-2.3 (owner layout decision 2026-09-27, final): after the static region
        daily context, scene, time line, memory block, history, then the per-turn tail."""
        orders = {
            "deep": ["daily_context", "current_scene", "current_time", "conversation_history", "memories_block",
                     "pending_mind", "blurt_block", "say_marker", "deep_instruction", "language_line"],
            "surface": ["daily_context", "current_scene", "current_time", "conversation_history", "memories_block",
                        "detected_lang"],
            "thinking": ["daily_context", "current_scene", "current_time", "thinking_history", "memories_block",
                         "deep_request"],
        }
        for kind, order in orders.items():
            text = read(FILES[kind])
            pos = [text.find("{" + n + "}") for n in order]
            self.assertEqual([n for n, p in zip(order, pos) if p == -1], [], f"{FILES[kind]}: missing placeholders")
            self.assertEqual(pos, sorted(pos), f"{FILES[kind]}: dynamic placeholders out of the CONTRACT §2 order")

    def test_deep_has_no_template_literal_or_action_ban(self):
        text = read(FILES["deep"])
        self.assertNotIn("[模版]", text)
        # B5: actions are allowed in 我心想; the old ban sentence must be gone.
        self.assertNotIn("不写动作或场景旁白", text)

    def test_sfx_placeholder_only_in_the_single_bad_example(self):
        deep = read(FILES["deep"])
        self.assertEqual(deep.count(SFX_BAD_EXAMPLE), 1, "例子.txt: the one ❌ SFX example (CONTRACT §1.5)")
        for name in (FILES["deep"], FILES["surface"]):
            for ln in read(name).splitlines():
                if "【声效名】" in ln:
                    self.assertIn("❌", ln, f"{name}: 【声效名】 outside a ❌ example: {ln.strip()}")

    def test_surface_closing_is_short(self):
        lines = non_empty_lines(read(FILES["surface"]))
        idx = next(i for i, ln in enumerate(lines) if "{detected_lang}" in ln)
        self.assertIn("对方说的语言是{detected_lang}", lines[idx])
        self.assertLessEqual(len(lines) - idx - 1, 2, "表层.txt: at most a two-line reminder after the language line")

    def test_reflection_closing_line(self):
        text = read(FILES["thinking"])
        last = non_empty_lines(text)[-1]
        self.assertTrue(is_reflection_closing(last), f"思考.txt last line is not the closing line: {last!r}")
        self.assertEqual(text.count(REFLECTION_CLOSING_START), 1, "the closing line appears once")
        self.assertLess(text.find("{deep_request}"), text.find(REFLECTION_CLOSING_START))

    def test_scenes_json_contract(self):
        scenes = pc.read_text_bom(PROMPTS / "scenes.json")
        import json
        data = json.loads(scenes)
        # deep.* blocks address her in the second person (her own output stays 我说/我心想)
        style = data["deep"]["static"]["communication_style"]
        self.assertIn("你会中日英韩四种语言", style)
        self.assertNotIn("我会", style)
        self.assertTrue(data["surface"]["context"].strip())
        # every time slot offers 1-5 possibilities (the brain lives one of them per day), and the two scene
        # tables (at home / on the phone) cover the same slots
        daily = {k: v for k, v in data["deep"]["daily_context"].items() if not k.startswith("_")}
        for key, options in daily.items():
            self.assertIsInstance(options, list, key)
            self.assertTrue(1 <= len(options) <= 5, key)
            self.assertTrue(all(isinstance(o, str) and o.strip() for o in options), key)
        slots = {k for k in data["deep"]["current_scene"] if not k.startswith("_")}
        self.assertEqual(slots, set(daily))
        self.assertEqual({k for k in data["deep"]["text_scene"] if not k.startswith("_")}, slots)

    def test_example_tags_are_real_keys(self):
        """C16/R14: examples advertise only the 69 real keys (❌ counter-examples and the
        `[register_emotion]` format placeholder excepted)."""
        for name in (FILES["deep"], FILES["surface"]):
            bad = []
            for ln in read(name).splitlines():
                if "❌" in ln:
                    continue
                tags = re.findall(r"\[([a-z]+_[a-z_]+)\]", ln) + re.findall(r"^\s*tone\s*[:：]\s*([a-z_]+)", ln)
                bad += [t for t in tags if t not in pc.VALID_EMOTIONS and t != "register_emotion"]
            self.assertEqual(bad, [], f"{name}: example tags that are not real TTS keys")

    def test_no_bom(self):
        for name in list(FILES.values()) + ["scenes.json"]:
            self.assertFalse((PROMPTS / name).read_bytes().startswith(b"\xef\xbb\xbf"), name)


if __name__ == "__main__":
    unittest.main()
