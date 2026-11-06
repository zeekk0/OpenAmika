"""E (2026-10): numpy recall ranks exactly like the per-item Python cosine, and the recall indexes extend
across ingest instead of being rebuilt."""
import random
import sys
import tempfile
import unittest
import unicodedata
from pathlib import Path
from unittest.mock import patch

PAYLOAD = Path(__file__).resolve().parents[1] / "brain"
if str(PAYLOAD) not in sys.path:
    sys.path.insert(0, str(PAYLOAD))
import methods
from f_memory import DIMENSIONS, MemoryRuntime
from f_method import CandidateF


def unit(seed):
    rng = random.Random(seed)
    vector = [rng.uniform(-1, 1) for _ in range(DIMENSIONS)]
    norm = sum(x * x for x in vector) ** 0.5
    return [x / norm for x in vector]


def event(i):
    return {"id": f"e{i}", "time": f"2026-01-{1 + i % 28:02d}T12:00:00Z", "user": f"I said thing {i} about topic {i % 9}.",
            "assistant": "Noted.", "source_kind": "conversation"}


def fact(i):
    source = event(i)
    return {"id": f"f{i}", "text": f"User likes thing {i} of topic {i % 9}", "subject": "user", "predicate": f"likes_{i % 5}",
            "value": f"thing {i}", "source_ids": [source["id"]], "date": source["time"][:10], "source_kind": "user",
            "fact_type": "user_fact", "status": "active", "entities": [f"topic {i % 9}"], "supersedes": [],
            "replaces_prior": False, "quotes": [{"source_id": source["id"], "speaker": "user", "quote": source["user"]}]}


def build(n=120):
    events, facts = [event(i) for i in range(n)], [fact(i) for i in range(n)]
    documents = {e["id"]: unit(i) for i, e in enumerate(events)}
    documents.update({f["id"]: unit(10_000 + i) for i, f in enumerate(facts)})
    return CandidateF(events, {"facts": facts}, {"documents": documents, "queries": {}})


KW = dict(budget_chars=3000, fact_packets=4, event_candidates=5, lang="en")


class RecallTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(methods._np, "numpy is part of the brain environment")
        self.flag = methods.NUMPY_RECALL

    def tearDown(self):
        methods.NUMPY_RECALL = self.flag

    def both(self, model, query):
        out = {}
        for backend in ("python", "numpy"):
            methods.NUMPY_RECALL = backend == "numpy"
            result = model.retrieve(query, **KW)
            self.assertEqual(result["diagnostics"]["semantic_backend"], backend)
            ranks = ([i["id"] for i, _ in model._rank(model.fact_items, query, hybrid=True)],
                     [i["id"] for i, _ in model._rank(model.event_items, query, hybrid=True)])
            out[backend] = (result["source_ids"], result["text"], ranks)
        return out

    def test_numpy_recall_ranks_exactly_like_the_python_cosine(self):
        model = build()
        for i in range(25):
            query = f"thing {i * 3 % 120} topic {i % 9}"
            model.vectors["queries"][query] = unit(1000 + i)
            out = self.both(model, query)
            self.assertEqual(out["numpy"], out["python"], query)
        self.assertEqual(model._vector_index.count, 240)
        # without a query vector the ranking is lexical and no backend is involved
        methods.NUMPY_RECALL = True
        self.assertIsNone(model.retrieve("no vector for this one", **KW)["diagnostics"]["semantic_backend"])

    def test_indexes_extend_across_ingest_instead_of_rebuilding(self):
        model = build(60)
        query = "thing 5 topic 5"
        model.vectors["queries"][query] = unit(5)
        methods.NUMPY_RECALL = True
        model.retrieve(query, **KW)
        index = model._vector_index
        self.assertEqual(index.count, 120)
        probe = unit(99)
        new = {"id": "e-new", "time": "2026-02-01T12:00:00Z", "user": "something about tea", "assistant": "ok",
               "source_kind": "conversation"}
        calls, real = [], methods.tokenize

        def counting(text):
            calls.append(text)
            return real(text)
        with patch.object(methods, "tokenize", counting):
            model.ingest([new], {"facts": []}, {"documents": {"e-new": probe}, "queries": {}})
            model.vectors["queries"]["tea?"] = probe
            model.retrieve("tea?", **KW)
            first = model._rank(model.event_items, "tea?", hybrid=True)[0][0]["id"]
        self.assertIs(model._vector_index, index)                       # extended, not rebuilt
        self.assertEqual(index.count, 121)
        self.assertEqual(first, "e-new")                                # its vector is the query vector
        tokenized = [text for text in calls if text != "tea?"]
        self.assertEqual(len(tokenized), 1)                             # only the new item; 120 counters reused
        self.assertIn("tea", tokenized[0])

    def test_index_is_seeded_from_the_sidecar_after_reload(self):
        model = build(40)
        query = "thing 7 topic 7"
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "state.json"
            model.persist(path)
            reloaded = CandidateF.reload(path)
            reloaded.vectors["queries"][query] = model.vectors["queries"][query] = unit(7)
            out = self.both(reloaded, query)
            self.assertEqual(out["numpy"], out["python"])
            self.assertEqual(reloaded._vector_index.count, 80)
            methods.NUMPY_RECALL = True
            self.assertEqual(model.retrieve(query, **KW)["source_ids"], reloaded.retrieve(query, **KW)["source_ids"])

    def test_korean_decomposed_lookup_tokens_match_without_rewriting_evidence(self):
        original = "민수는 부산에서 살아요."
        decomposed = unicodedata.normalize("NFD", original)
        self.assertEqual(methods.tokenize(decomposed), methods.tokenize(original))
        source = dict(event(0), user=decomposed)
        model = CandidateF([source], {"facts": []}, {"documents": {}, "queries": {}})
        result = model.retrieve("부산", **KW)
        self.assertIn(source["id"], result["source_ids"])
        self.assertEqual(model.events[0]["user"], decomposed)

    def test_korean_fact_correction_round_trip_keeps_exact_quotes(self):
        originals = ["나는 부산에 살고 있어.", "정정할게. 지금은 부산이 아니라 서울에 살고 있어."]

        def extract(events, chunk_id):
            source = events[0]
            corrected = source["user"] == originals[1]
            city = "서울" if corrected else "부산"
            return [{"id": "fact-" + source["id"], "text": "사용자는 " + city + "에 산다.",
                     "subject": "user", "predicate": "lives_in", "value": city,
                     "source_ids": [source["id"]], "date": source["time"][:10],
                     "source_kind": "user", "fact_type": "user_fact", "status": "active",
                     "entities": [city], "supersedes": [], "replaces_prior": corrected,
                     "quotes": [{"source_id": source["id"], "speaker": "user", "quote": source["user"]}]}]

        def embed(texts, task_type):
            return [[1.0] + [0.0] * (DIMENSIONS - 1) for text in texts]

        with tempfile.TemporaryDirectory() as folder:
            memory = MemoryRuntime(folder, extract, embed)
            for i, original in enumerate(originals):
                source = dict(event(i), user=original, assistant="알겠어.")
                memory.archive(source)
                self.assertEqual(memory.flush_pending()["completed"], 1)
            reloaded = MemoryRuntime(folder, extract, embed)
            result = reloaded.retrieve("부산에서 어디로 이사했어?")
            self.assertEqual(result["diagnostics"]["correction_links"], 1)
            for original in originals:
                self.assertIn(original, result["text"])
            self.assertEqual([e["user"] for e in reloaded.model.events], originals)


if __name__ == "__main__":
    unittest.main()
