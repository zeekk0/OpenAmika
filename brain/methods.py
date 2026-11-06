"""Five deterministic memory prototypes; no model calls or network operations.

These are custom research baselines, not implementations of third-party packages.
The caller owns extraction, embedding generation, metering, and answer generation.
"""

from __future__ import annotations

import json
import math
import re
import unicodedata
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

try:
    import numpy as _np
except Exception:          # numpy is optional: without it the per-item Python cosine below is used
    _np = None
# E (2026-10): recall scores every stored vector with one matrix-vector product instead of a Python loop
# (1.6 s for 12,700 vectors, held under the memory lock, became about a millisecond). f_bridge switches it
# off with build_f.json "memory_numpy_recall": false; ranking is identical either way except exact ties.
NUMPY_RECALL = _np is not None


METHOD_NAMES = {
    "A": "Pinned profile plus keyword journals",
    "B": "Episodic diary summaries",
    "C": "Hybrid original-event retrieval",
    "D": "Structured facts plus hybrid episodes and original evidence",
    "E": "Temporal relationship graph plus hybrid episodes",
}
EXTRACTION_REQUIREMENTS = {
    "A": ["facts"], "B": ["episodes"], "C": [],
    "D": ["facts", "episodes"], "E": ["facts", "episodes"],
}
_REJECTED_SOURCES = {
    "operator", "operator_cue", "cue", "injection", "inject", "context_inject",
    "context_injection", "reflection", "thinking", "speculation", "system",
    "system_prompt", "recalled_memory", "memory", "persona", "canon",
}
_REJECTED_FACT_TYPES = _REJECTED_SOURCES | {
    "hypothesis", "assistant_speculation", "fiction", "character_canon",
}
_INACTIVE = {"superseded", "retracted", "uncertain", "invalid", "deleted", "rejected"}
_PROFILE_PREDICATES = {
    "name", "named", "is_named", "preferred_name", "age", "birthday", "birthdate",
    "lives_in", "location", "timezone", "occupation", "works_as", "works_at",
    "prefers", "preference", "likes", "dislikes", "allergy", "allergic_to",
    "pronouns", "language", "speaks", "relationship", "identity",
}
_HISTORICAL = re.compile(
    r"\b(before|previous(?:ly)?|earlier|original(?:ly)?|used to|back then|"
    r"history|historical|changed|change|old|past|when did|timeline|first)\b"
    r"|以前|之前|当时|當時|原来|原來|最初|曾经|曾經|過去|昔|変更|変わ",
    re.IGNORECASE,
)
_CJK = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\u3040-\u30ff\uac00-\ud7af]+")
_WORDS = re.compile(r"[a-z0-9]+(?:'[a-z]+)?", re.IGNORECASE)
_STOP = {
    "a", "an", "and", "are", "as", "at", "be", "been", "by", "did", "do",
    "does", "for", "from", "had", "has", "have", "how", "i", "in", "is",
    "it", "me", "my", "of", "on", "or", "s", "that", "the", "their", "this",
    "to", "was", "were", "what", "when", "where", "which", "who", "with", "you",
    "your", "remember", "recall", "tell", "about", "we", "our", "said",
}


def tokenize(text: str) -> list[str]:
    """English words plus overlapping CJK unigrams/bigrams; no external tokenizer."""
    value = unicodedata.normalize("NFC", str(text)).casefold()
    tokens = [word for word in _WORDS.findall(value) if word not in _STOP]
    for run in _CJK.findall(value):
        tokens.extend(run)
        tokens.extend(run[index:index + 2] for index in range(len(run) - 1))
    return tokens


def _stamp(value: Any) -> float:
    if not value:
        return 0.0
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.timestamp()
    except (TypeError, ValueError, OverflowError):
        return 0.0


class VectorIndex:
    """Document vectors as one float64 matrix for recall. Rows are appended as ids arrive (an id's vector
    never changes) into a buffer that doubles its capacity, so extending it after an ingest is cheap."""

    def __init__(self, dims: int, capacity: int = 1024):
        self.dims = int(dims)
        self.ids: list[str] = []
        self.index: dict[str, int] = {}
        self.count = 0
        self.matrix = _np.empty((max(1, int(capacity)), self.dims), dtype=_np.float64)
        self.norms = _np.empty((max(1, int(capacity)),), dtype=_np.float64)

    def _reserve(self, extra: int) -> None:
        need = self.count + extra
        if need > len(self.matrix):
            size = max(need, 2 * len(self.matrix))
            matrix = _np.empty((size, self.dims), dtype=_np.float64)
            matrix[:self.count] = self.matrix[:self.count]
            norms = _np.empty((size,), dtype=_np.float64)
            norms[:self.count] = self.norms[:self.count]
            self.matrix, self.norms = matrix, norms

    def append_rows(self, ids: list[str], rows) -> None:
        rows = _np.asarray(rows, dtype=_np.float64).reshape(len(ids), self.dims)
        self._reserve(len(ids))
        self.matrix[self.count:self.count + len(ids)] = rows
        self.norms[self.count:self.count + len(ids)] = _np.linalg.norm(rows, axis=1)
        for ident in ids:
            self.index[ident] = self.count
            self.ids.append(ident)
            self.count += 1

    def extend(self, documents: Mapping) -> None:
        missing = [ident for ident in documents if ident not in self.index]
        if missing:
            self.append_rows(missing, [documents[ident] for ident in missing])

    def covers(self, documents: Mapping) -> bool:
        return all(ident in documents for ident in self.ids)

    def scores(self, query) -> list[float] | None:
        """Cosine of every stored row with the query, in row order (0 where a norm is 0)."""
        vector = _np.asarray(query, dtype=_np.float64)
        if vector.shape != (self.dims,) or not self.count:
            return None
        query_norm = float(_np.linalg.norm(vector))
        if not query_norm:
            return None
        norms = self.norms[:self.count]
        dots = self.matrix[:self.count] @ vector
        with _np.errstate(divide="ignore", invalid="ignore"):
            out = _np.where(norms > 0, dots / (norms * query_norm), 0.0)
        return out.tolist()


def _cosine(left: Iterable[float], right: Iterable[float]) -> float:
    a, b = list(left), list(right)
    if not a or len(a) != len(b):
        return 0.0
    product = sum(float(x) * float(y) for x, y in zip(a, b))
    norm = math.sqrt(sum(float(x) ** 2 for x in a) * sum(float(y) ** 2 for y in b))
    return product / norm if norm else 0.0


def _kind(value: Any) -> str:
    return str(value or "conversation").casefold().replace("-", "_").replace(" ", "_")


def _text(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if value is None:
        return ""
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


class MemoryMethod:
    """Shared artifacts and deterministic selection for method IDs A through E.

    ``vectors`` can be a dict of item IDs to vectors with an optional
    ``__queries__`` dict of exact query strings to vectors. Alternatively use
    ``{"documents": {...}, "queries": {...}}`` or an object implementing
    ``get(item_id)`` and ``embed_query(query)``. Any callback is invoked by the
    caller's explicit configuration; this module never creates an API client.
    """

    format_version = 1

    def __init__(self, method_id: str, events: list[dict], records: Any, vectors: Any = None):
        method_id = str(method_id).upper()
        if method_id not in METHOD_NAMES:
            raise ValueError(f"Unknown method {method_id!r}; choose A, B, C, D, or E")
        self.method_id = method_id
        self.events = [dict(event) for event in events]
        self.records = records or {}
        self.vectors = vectors
        self.event_by_id: dict[str, dict] = {}
        for event in self.events:
            event_id = str(event.get("id", ""))
            if not event_id or event_id in self.event_by_id:
                raise ValueError("Every event needs a unique, nonempty id")
            event["id"] = event_id
            self.event_by_id[event_id] = event
        self.safe_events = [event for event in self.events if self._safe_event(event)]
        self.safe_event_ids = {event["id"] for event in self.safe_events}
        self.excluded_records: list[dict] = []
        self.episodes, self.facts = self._normalise_records(self.records)
        self.event_items = [self._event_item(event) for event in self.safe_events]
        self.episode_items = [self._record_item(record, "episode") for record in self.episodes]
        self.fact_items = [self._record_item(record, "fact") for record in self.facts]
        self._query_vector = None
        # (per-item token counts, document frequency, total length) per exact id tuple; a set that grew by
        # ingest extends its entry instead of re-tokenizing everything (E). Carried across ingest.
        self._lexical_cache: dict[tuple[str, ...], tuple[list[Counter], Counter, int]] = {}
        self._vector_index: VectorIndex | None = None       # E: built on first recall, carried across ingest
        self._last_semantic_backend: str | None = None       # "numpy" | "python" for the last hybrid ranking

    @staticmethod
    def _safe_event(event: dict) -> bool:
        return _kind(event.get("source_kind")) not in _REJECTED_SOURCES

    def _normalise_records(self, records: Any) -> tuple[list[dict], list[dict]]:
        if isinstance(records, list):
            episodes = [r for r in records if _kind(r.get("record_type", r.get("type"))) == "episode"]
            facts = [r for r in records if r not in episodes]
        elif isinstance(records, dict):
            episodes, facts = records.get("episodes", []), records.get("facts", [])
        else:
            raise TypeError("records must be a dict with facts/episodes lists or a flat list")
        output: dict[str, list] = {"episode": [], "fact": []}
        seen = set(self.event_by_id)
        for record_type, inputs in (("episode", episodes), ("fact", facts)):
            for index, source in enumerate(inputs):
                record = dict(source)
                record_id = str(record.get("id") or f"{record_type}_{index:06d}")
                if record_id in seen:
                    raise ValueError(f"Duplicate event/record id: {record_id}")
                seen.add(record_id)
                ids = record.get("source_ids", [])
                if isinstance(ids, str):
                    ids = [ids]
                ids = list(dict.fromkeys(str(value) for value in ids))
                reason = None
                if not ids or any(value not in self.safe_event_ids for value in ids):
                    reason = "missing, unknown, or excluded source evidence"
                elif _kind(record.get("source_kind")) in _REJECTED_SOURCES:
                    reason = "excluded source kind"
                elif record_type == "fact" and _kind(record.get("fact_type", "user_fact")) in _REJECTED_FACT_TYPES:
                    reason = "speculation, persona, or operator cue is not an observed fact"
                if reason:
                    self.excluded_records.append({"id": record_id, "reason": reason})
                    continue
                record["id"] = record_id
                record["source_ids"] = ids
                record.setdefault("status", "active")
                record.setdefault("date", record.get("timestamp") or record.get("event_time") or
                                  max((self.event_by_id[value].get("time", "") for value in ids), key=_stamp))
                record.setdefault("source_kind", "conversation")
                record.setdefault("entities", [])
                output[record_type].append(record)
        return output["episode"], output["fact"]

    def _event_item(self, event: dict) -> dict:
        user, assistant = _text(event.get("user")), _text(event.get("assistant"))
        body = f"User: {user}"
        if assistant:
            body += f"\nAssistant: {assistant}"
        return {
            "id": event["id"], "text": body, "source_ids": [event["id"]],
            "date": event.get("time", ""), "kind": "original_event", "entities": [],
            "source_kind": event.get("source_kind", "conversation"),
        }

    @staticmethod
    def _record_item(record: dict, record_type: str) -> dict:
        item = dict(record)
        if not item.get("text"):
            item["text"] = " ".join(_text(item.get(key)) for key in ("subject", "predicate", "value")).strip()
        item["text"] = _text(item["text"])
        item["kind"] = record_type
        entities = item.get("entities", [])
        if isinstance(entities, str):
            entities = [entities]
        item["entities"] = list(dict.fromkeys(_text(entity).casefold() for entity in entities if _text(entity)))
        if record_type == "fact":
            for key in ("subject", "value"):
                value = _text(item.get(key)).casefold()
                if value and value not in item["entities"]:
                    item["entities"].append(value)
        return item

    @staticmethod
    def _lexical_text(item: dict) -> str:
        return item["text"] + " " + " ".join(item.get("entities", []))

    def _bm25(self, items: list[dict], query: str) -> dict[str, float]:
        if not items:
            return {}
        key = tuple(item["id"] for item in items)
        entry = self._lexical_cache.get(key)
        if entry is None:
            # A set that grew (ingest appends) extends its earlier entry: the counters already made are reused.
            base = next((k for k in self._lexical_cache if len(k) < len(key) and key[:len(k)] == k), None)
            if base is not None:
                counts, frequency, total = self._lexical_cache.pop(base)
                counts, frequency, start = list(counts), Counter(frequency), len(base)
            else:
                counts, frequency, total, start = [], Counter(), 0, 0
            for item in items[start:]:
                count = Counter(tokenize(self._lexical_text(item)))
                counts.append(count)
                frequency.update(count.keys())
                total += sum(count.values())
            entry = self._lexical_cache[key] = (counts, frequency, total)
        counts, frequency, total = entry
        average = total / len(items) or 1.0
        result = {}
        terms = set(tokenize(query))
        for item, count in zip(items, counts):
            size = sum(count.values())
            score = 0.0
            for term in terms:
                term_count = count.get(term, 0)
                if not term_count:
                    continue
                inverse = math.log(1 + (len(items) - frequency[term] + 0.5) / (frequency[term] + 0.5))
                score += inverse * term_count * 2.2 / (term_count + 1.2 * (0.25 + 0.75 * size / average))
            if score > 0:
                result[item["id"]] = score
        return result

    def _get_document_vector(self, item_id: str):
        if self.vectors is None:
            return None
        if isinstance(self.vectors, Mapping):
            documents = self.vectors.get("documents", self.vectors.get("vectors", self.vectors))
            return documents.get(item_id)
        return self.vectors.get(item_id)

    def _get_query_vector(self, query: str):
        if self.vectors is None:
            return None
        if isinstance(self.vectors, Mapping):
            queries = self.vectors.get("__queries__", self.vectors.get("queries", {}))
            return queries.get(query)
        callback = getattr(self.vectors, "embed_query", None)
        return callback(query) if callback else None

    def _vector_scores(self):
        """(VectorIndex, cosine per row) for the query vector over every stored document vector (E), or None
        when the per-item Python path must be used: no numpy, switched off, or vectors not a mapping."""
        if not NUMPY_RECALL or _np is None or self._query_vector is None or not isinstance(self.vectors, Mapping):
            return None
        documents = self.vectors.get("documents", self.vectors.get("vectors", self.vectors))
        if not isinstance(documents, Mapping) or not documents:
            return None
        index = self._vector_index
        if index is None or not index.covers(documents):
            index = None
            seed = getattr(self, "_vector_blob", None)      # the persisted float32 rows (f_method.VectorBlob)
            if seed is not None and seed.ids and all(ident in documents for ident in seed.ids):
                index = VectorIndex(seed.dims, capacity=len(seed.ids) + 256)
                index.append_rows(list(seed.ids), _np.frombuffer(bytes(seed.buf), dtype="<f4").reshape(len(seed.ids), seed.dims))
            else:
                index = VectorIndex(len(next(iter(documents.values()))), capacity=len(documents) + 256)
        try:
            index.extend(documents)
        except (TypeError, ValueError):
            return None                                     # a malformed vector: the Python path skips it
        self._vector_index = index
        scores = index.scores(self._query_vector)
        return None if scores is None else (index, scores)

    def _rank(self, items: list[dict], query: str, hybrid: bool = False) -> list[tuple[dict, float]]:
        lexical = self._bm25(items, query)
        if not hybrid or self._query_vector is None:
            scored = [(item, lexical.get(item["id"], 0.0)) for item in items]
        else:
            semantic = {}
            fast = self._vector_scores()
            if fast is not None:
                index, scores = fast
                self._last_semantic_backend = "numpy"
                for item in items:
                    row = index.index.get(item["id"])
                    if row is not None and scores[row] > 0:
                        semantic[item["id"]] = scores[row]
            else:
                self._last_semantic_backend = "python"
                for item in items:
                    vector = self._get_document_vector(item["id"])
                    if vector is not None:
                        score = _cosine(vector, self._query_vector)
                        if score > 0:
                            semantic[item["id"]] = score
            fused: dict[str, float] = defaultdict(float)
            for scores in (lexical, semantic):
                for rank, (item_id, _) in enumerate(sorted(scores.items(), key=lambda pair: (-pair[1], pair[0])), 1):
                    fused[item_id] += 1.0 / (60 + rank)
            scored = [(item, fused.get(item["id"], 0.0)) for item in items]
        return sorted((pair for pair in scored if pair[1] > 0), key=lambda pair: (-pair[1], pair[0]["id"]))

    @staticmethod
    def _active(item: dict) -> bool:
        return _kind(item.get("status", "active")) not in _INACTIVE and not item.get("valid_to")

    def _source_items(self, items: list[dict]) -> list[dict]:
        seen, output = set(), []
        for item in items:
            for event_id in item["source_ids"]:
                if event_id not in seen:
                    seen.add(event_id)
                    output.append(self._event_item(self.event_by_id[event_id]))
        return output

    def _pinned(self) -> list[dict]:
        # A profile is intentionally query-independent and has a fixed capacity.
        candidates = [item for item in self.fact_items if self._active(item)
                      and _kind(item.get("fact_type", "user_fact")) == "user_fact"]
        latest: dict[tuple[str, str], dict] = {}
        for item in sorted(candidates, key=lambda value: (_stamp(value.get("date")), value["id"])):
            predicate = _kind(item.get("predicate", ""))
            subject = _text(item.get("subject")).casefold()
            if predicate in _PROFILE_PREDICATES:
                latest[(subject, predicate)] = item
        return sorted(latest.values(), key=lambda value: (-_stamp(value.get("date")), value["id"]))[:12]

    def _method_a(self, query: str) -> tuple[list[dict], dict]:
        pinned = [dict(item, kind="pinned_profile") for item in self._pinned()]
        journals = [item for item, _ in self._rank(self.event_items, query)[:8]]
        return pinned + journals, {"profile_count": len(pinned), "keyword_journal_count": len(journals)}

    def _method_b(self, query: str) -> tuple[list[dict], dict]:
        seeds = [item for item, _ in self._rank(self.episode_items, query)[:5]]
        ordered = sorted(self.episode_items, key=lambda item: (_stamp(item.get("date")), item["id"]))
        positions = {item["id"]: index for index, item in enumerate(ordered)}
        selected, seen = [], set()
        for seed in seeds:
            position = positions[seed["id"]]
            for index in (position, position - 1, position + 1):
                if 0 <= index < len(ordered) and ordered[index]["id"] not in seen and len(selected) < 10:
                    selected.append(ordered[index])
                    seen.add(ordered[index]["id"])
        return selected, {"episode_count": len(selected), "episode_seed_count": len(seeds),
                          "chronological_neighbors": True, "original_evidence_in_prompt": False}

    def _method_c(self, query: str) -> tuple[list[dict], dict]:
        selected = [item for item, _ in self._rank(self.event_items, query, hybrid=True)[:12]]
        return selected, {"original_event_count": len(selected), "derived_extraction_used": False}

    def _method_d(self, query: str) -> tuple[list[dict], dict]:
        facts = [item for item in self.fact_items if self._active(item)]
        selected_facts = [item for item, _ in self._rank(facts, query, hybrid=True)[:6]]
        episodes = [item for item, _ in self._rank(self.episode_items, query, hybrid=True)[:4]]
        originals = [item for item, _ in self._rank(self.event_items, query, hybrid=True)[:3]]
        # Pair every derived entry with its source before moving on to another entry.
        selected = []
        for item in selected_facts + episodes:
            selected.extend([item, *self._source_items([item])])
        selected.extend(originals)
        return selected, {"selected_fact_count": len(selected_facts), "selected_episode_count": len(episodes),
                          "original_evidence_in_prompt": True}

    def _temporal_facts(self, historical: bool) -> list[dict]:
        valid = [item for item in self.fact_items if _kind(item.get("status", "active"))
                 not in {"uncertain", "invalid", "deleted", "rejected", "retracted"}]
        if historical:
            return valid
        # Explicit supersession is authoritative; later non-superseding facts can coexist.
        retired = set()
        for item in valid:
            supersedes = item.get("supersedes", [])
            if isinstance(supersedes, str):
                supersedes = [supersedes]
            retired.update(supersedes)
            if item.get("replaces_prior") is True:
                subject = _text(item.get("subject")).casefold()
                predicate = _kind(item.get("predicate", ""))
                if subject and predicate:
                    retired.update(other["id"] for other in valid
                                   if _text(other.get("subject")).casefold() == subject
                                   and _kind(other.get("predicate", "")) == predicate
                                   and _stamp(other.get("date")) < _stamp(item.get("date")))
        return [item for item in valid if item["id"] not in retired and self._active(item)]

    def _method_e(self, query: str) -> tuple[list[dict], dict]:
        historical = bool(_HISTORICAL.search(query))
        facts = self._temporal_facts(historical)
        ranking = self._rank(facts, query, hybrid=True)
        seeds = [item for item, _ in ranking[:4]]
        adjacency: dict[str, list[dict]] = defaultdict(list)
        for item in facts:
            for entity in item.get("entities", []):
                adjacency[entity].append(item)
        # Seed with queried entity names, then expand a maximum of two relationship hops.
        query_entities = {entity for entity in adjacency if entity and entity in query.casefold()}
        seed_entities = query_entities | {entity for item in seeds for entity in item.get("entities", [])}
        generic = {"user", "assistant", "amika", "i", "me", "用户", "用戶", "私"}
        frontier = seed_entities - generic
        seen = {item["id"] for item in seeds}
        expanded = []
        query_scores = dict((item["id"], score) for item, score in ranking)
        for _ in range(2):
            neighbors = {item["id"]: item for entity in sorted(frontier) for item in adjacency[entity]
                         if item["id"] not in seen}
            ordered = sorted(neighbors.values(), key=lambda item: (-query_scores.get(item["id"], 0),
                              -_stamp(item.get("date")), item["id"]))
            frontier = set()
            for item in ordered[:max(0, 10 - len(seeds) - len(expanded))]:
                seen.add(item["id"])
                expanded.append(item)
                frontier.update(set(item.get("entities", [])) - generic)
        selected_facts = seeds + expanded
        if historical:
            selected_facts.sort(key=lambda item: (_stamp(item.get("valid_from") or item.get("date")), item["id"]))
        episodes = [item for item, _ in self._rank(self.episode_items, query, hybrid=True)[:3]]
        originals = [item for item, _ in self._rank(self.event_items, query, hybrid=True)[:2]]
        selected = []
        for item in selected_facts:
            edge = dict(item)
            relation = " -> ".join(_text(item.get(key)) for key in ("subject", "predicate", "value"))
            edge["text"] = relation + "\n" + item["text"]
            edge["kind"] = "temporal_relationship"
            selected.extend([edge, *self._source_items([item])])
        selected.extend(episodes + originals)
        return selected, {"historical_query": historical, "graph_seed_count": len(seeds),
                          "graph_expanded_count": len(expanded), "graph_entities": len(adjacency),
                          "selected_episode_count": len(episodes)}

    @staticmethod
    def _pack(items: list[dict], budget: int) -> tuple[str, list[str], list[str], list[str]]:
        chunks, sources, selected, truncated = [], [], [], []
        seen = set()
        remaining = max(0, int(budget))
        for item in items:
            if item["id"] in seen:
                continue
            seen.add(item["id"])
            labels = [item["kind"], f"id={item['id']}", f"sources={','.join(item['source_ids'])}"]
            if item.get("date"):
                labels.append(f"date={item['date']}")
            if item.get("status"):
                labels.append(f"status={item['status']}")
            if item.get("valid_from"):
                labels.append(f"valid_from={item['valid_from']}")
            if item.get("valid_to"):
                labels.append(f"valid_to={item['valid_to']}")
            header = "[" + " | ".join(labels) + "]\n"
            separator = "\n\n" if chunks else ""
            body = item["text"]
            capacity = remaining - len(header) - len(separator)
            if capacity <= 0 or not body:
                continue
            if len(body) > capacity:
                marker = " ...[truncated]"
                if capacity <= len(marker):
                    continue
                body = body[:capacity - len(marker)] + marker
                truncated.append(item["id"])
            chunk = separator + header + body
            chunks.append(chunk)
            remaining -= len(chunk)
            selected.append(item["id"])
            for source_id in item["source_ids"]:
                if source_id not in sources:
                    sources.append(source_id)
        return "".join(chunks), sources, selected, truncated

    def retrieve(self, query: str, budget_chars: int = 8000) -> dict:
        """Retrieve without modifying memory or accepting gold answers/queries at build time."""
        if not isinstance(query, str):
            raise TypeError("query must be text")
        budget_chars = max(0, int(budget_chars))
        self._query_vector = self._get_query_vector(query) if self.method_id in "CDE" else None
        selected, details = getattr(self, f"_method_{self.method_id.lower()}")(query)
        memory, sources, ids, truncated = self._pack(selected, budget_chars)
        diagnostics = {
            "method_id": self.method_id, "method_name": METHOD_NAMES[self.method_id],
            "custom_prototype": True, "extraction_requirements": EXTRACTION_REQUIREMENTS[self.method_id],
            "budget_chars": budget_chars, "returned_chars": len(memory),
            "selected_record_ids": ids, "truncated_record_ids": truncated,
            "event_count": len(self.safe_events), "excluded_event_count": len(self.events) - len(self.safe_events),
            "facts_available": len(self.facts), "episodes_available": len(self.episodes),
            "excluded_records": self.excluded_records,
            "semantic_query_available": self._query_vector is not None,
            "retrieval_mode": "BM25+vector_RRF" if self._query_vector is not None else "BM25",
            **details,
        }
        return {"text": memory, "source_ids": sources, "diagnostics": diagnostics}

    def embedding_items(self) -> dict[str, str]:
        """Expose exact document text for a centrally metered embedding batch."""
        if self.method_id in "AB":
            return {}
        items = self.event_items if self.method_id == "C" else self.event_items + self.episode_items + self.fact_items
        return {item["id"]: item["text"] + ("\nEntities: " + ", ".join(item["entities"])
                if item.get("entities") else "") for item in items}

    def persist(self, path: str | Path) -> None:
        """Save corpus and artifacts; vector callbacks intentionally cannot be serialized."""
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        vectors = self.vectors if isinstance(self.vectors, Mapping) else None
        payload = {"format_version": self.format_version, "method_id": self.method_id,
                   "events": self.events, "records": self.records, "vectors": vectors}
        temporary = target.with_name(target.name + ".tmp")
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
        temporary.replace(target)

    @classmethod
    def reload(cls, path: str | Path, vectors: Any = None) -> "MemoryMethod":
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        if payload.get("format_version") != cls.format_version:
            raise ValueError("Unsupported memory prototype format_version")
        return cls(payload["method_id"], payload["events"], payload["records"],
                   vectors if vectors is not None else payload.get("vectors"))

    save = persist
    load = reload
