"""Read-only evidence transcribed from the 2026-11-06 paid Korean UI run.

These are actual stored user quotes and writer fields, not idealized schema
output. Tests use private temporary snapshots, never the validation memory.
"""
import copy
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "brain"))
from f_method import CandidateF


# event ID, time, exact user speech, fact ID suffix, subject, predicate, value,
# writer gist, entities, exact writer quotation, correction flag
EVIDENCE = [
    ("live-20261106-163117-1", "23:31:17", "가상 인물 나루가 좋아하는 색은 파란색이에요. 연습용 사실로 기억해 주세요.",
     "a9ce74b62f9823c6e13126bc", "나루", "favorite_color", "파란색",
     "User's favorite color is blue", ["나루"], "가상 인물 나루가 좋아하는 색은 파란색이에요.", False),
    ("live-20261106-163507-9", "23:35:07", "정정할게요. 나루가 좋아하는 색은 파란색이 아니라 초록색이에요.",
     "c8b54e354f7d3e25a6c3d9e5", "Naru", "favorite_color", "green, not blue",
     "User corrected that Naru's favorite color is green, not blue.", ["Naru"], "나루가 좋아하는 색은 파란색이 아니라 초록색이에요.", True),
    ("live-20261106-163119-2", "23:31:19", "가상 인물 다온이의 단골 음료는 보리차예요. 연습용 사실이에요.",
     "f233308d6b4d253269e8dcf4", "user", "statements_about", "가상 인물 다온이의 단골 음료는 보리차라고 말했다; 연습용 사실임",
     "사용자가 가상 인물 다온이의 단골 음료는 보리차라고 말했다고 연습용 사실임.", ["다온", "보리차"], None, False),
    ("live-20261106-163511-10", "23:35:11", "다온이의 단골 음료를 옥수수차로 정정해 주세요. 보리차가 아니에요.",
     "1482d892013392a3ced90af0", "user", "correct_daon_i_regular_drink", "옥수수차 (corn tea), not barley tea",
     "User corrected Daon-i's regular drink to corn tea instead of barley tea.", ["다온이", "옥수수차", "보리차"], None, True),
    ("live-20261106-163122-3", "23:31:22", "가상 인물 소담이의 취미는 종이접기예요.",
     "f07825ef59984aeacf0c85b7", "사용자", "virtual_character_sodam_hobby", "종이접기",
     "사용자는 가상 인물 소담이의 취미는 종이접기라고 말했다.", ["가상 인물 소담이", "종이접기"], None, False),
    ("live-20261106-163514-11", "23:35:14", "소담이의 취미는 수채화예요. 종이접기라는 이전 사실을 정정해 주세요.",
     "57e182b2a77e6d087348ed46", "소담이", "hobby", "수채화",
     "소담이의 취미는 이전 주장과 달리 수채화이다.", ["소담이", "수채화", "종이접기"], None, True),
    ("live-20261106-163127-6", "23:31:27", "가상 정원 별뜰의 가운데 나무는 느티나무예요.",
     "5104a98b9e929fd64969e952", "user", "virtual_garden_center_tree", "느티나무",
     "The middle tree in the virtual garden 별뜰 is a Zelkova tree.", ["가상 정원 별뜰", "느티나무"], None, False),
    ("live-20261106-163525-14", "23:35:25", "별뜰 가운데 나무는 은행나무예요. 느티나무라는 설명은 잘못됐어요.",
     "f66b89eba39b330d36477335", "tree in the middle of the star field", "species_correction", "ginkgo tree, not zelkova tree",
     "The tree in the middle of the star field is a ginkgo tree, not a zelkova tree as previously described.",
     ["ginkgo tree", "zelkova tree", "tree in the middle of the star field"], None, True),
]


def corpus():
    events, facts = [], []
    for eid, time, user, fid, subject, predicate, value, text, entities, quote, correction in EVIDENCE:
        events.append(dict(id=eid, time="2026-11-05 " + time, user=user,
                           assistant="", source_kind="conversation"))
        facts.append(dict(id="fact-chunk-live-" + fid + "-001", subject=subject,
                          predicate=predicate, value=value, text=text, entities=entities,
                          source_ids=[eid], source_kind="user", fact_type="user_fact",
                          status="active", date="2026-11-05 " + time, supersedes=[],
                          replaces_prior=correction,
                          quotes=[dict(source_id=eid, speaker="user", quote=quote or user)]))
    # The fixture isolates user evidence. M03's additional assistant quote is not
    # needed to reproduce the lexical failure and is intentionally not invented.
    return sorted(events, key=lambda e: e["time"]), {"facts": facts}


class ActualKoreanCorrectionTests(unittest.TestCase):
    def test_translated_record_is_retrievable_by_literal_source_after_reload(self):
        events, records = corpus()
        originals = copy.deepcopy(records)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            CandidateF(events, records).persist(path)
            model = CandidateF.reload(path)
            for query, expected in [("나루", "c8b54e354f7d3e25a6c3d9e5"),
                                    ("별뜰", "f66b89eba39b330d36477335")]:
                with self.subTest(query=query):
                    result = model.retrieve(query, fact_packets=4, event_candidates=0, lang="en")
                    self.assertIn("fact-chunk-live-" + expected + "-001",
                                  result["diagnostics"]["selected_record_ids"])
                    self.assertEqual(result["diagnostics"]["correction_links"], 0,
                                     "Lexical relevance must not invent cross-entity supersession")
            self.assertEqual(records, originals)

    def test_unlinked_explicit_correction_is_not_rendered_as_an_unqualified_fact(self):
        events, records = corpus()
        model = CandidateF(events, records)
        correction = records["facts"][-1]
        result = model.retrieve("ginkgo", fact_packets=1, event_candidates=0, lang="en")
        self.assertIn(correction["quotes"][0]["quote"], result["text"])
        self.assertIn("explicit correction", result["text"])
        self.assertIn("not verified", result["text"])
        self.assertEqual(result["diagnostics"]["correction_links"], 0)

    def test_correction_hint_does_not_erase_uncertainty_or_retraction(self):
        for status, expected in [("uncertain", "uncertain even then"),
                                 ("retracted", "later taken back")]:
            with self.subTest(status=status):
                events, records = corpus()
                records["facts"][-1]["status"] = status
                result = CandidateF(events, records).retrieve(
                    "ginkgo", fact_packets=1, event_candidates=0, lang="en")
                self.assertIn(expected, result["text"])

    def test_same_day_unlinked_correction_keeps_explicit_evidence_and_status(self):
        for status in ("active", "uncertain", "retracted"):
            with self.subTest(status=status):
                events, records = corpus()
                records["facts"] = records["facts"][:2]
                original, correction = records["facts"]
                correction["subject"] = original["subject"]
                for fact in records["facts"]:
                    fact["valid_from"] = "2026-11-05"
                correction["status"] = status
                result = CandidateF(events, records).retrieve(
                    "나루", fact_packets=4, event_candidates=0, lang="en")
                self.assertEqual(result["diagnostics"]["correction_links"], 0)
                self.assertIn(correction["quotes"][0]["quote"], result["text"])
                if status == "active":
                    self.assertIn("explicit correction", result["text"])
                    self.assertIn("not verified", result["text"])
                else:
                    self.assertIn("uncertain even then" if status == "uncertain"
                                  else "later taken back", result["text"])
                    self.assertNotIn("explicit correction", result["text"])

    def test_all_four_actual_corrections_fit_both_runtime_budgets(self):
        events, records = corpus()
        model = CandidateF(events, records)
        queries = ["정정한 뒤 나루가 좋아하는 색은 무엇인가요?",
                   "지금 기억하는 다온이의 단골 음료는 무엇인가요?",
                   "정정된 소담이의 취미를 알려 주세요.",
                   "별뜰 가운데 나무의 정정된 종류를 말해 주세요."]
        for query, correction in zip(queries, records["facts"][1::2]):
            result = model.retrieve(query, budget_chars=3600, fact_packets=4,
                                    event_candidates=5, lang="zh")
            for budget in (2000, 3600):
                with self.subTest(query=query, budget=budget):
                    rendered = model.render(result["packets"], budget)
                    self.assertIn(correction["quotes"][0]["quote"], rendered["text"])
                    self.assertIn(correction["source_ids"][0], rendered["source_ids"])
                    self.assertLessEqual(len(rendered["text"]), budget)


if __name__ == "__main__":
    unittest.main()
