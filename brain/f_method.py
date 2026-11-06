"""Candidate F: quoted facts and original speech, with no episode summaries.

All extraction and embedding work belongs to the metered caller. This module
does not load corpora, evaluation cases, API clients, or callback embedders.
"""
from __future__ import annotations

import contextlib
import copy
import hashlib
import json
import os
import re
import struct
import tempfile
from collections import defaultdict
from collections.abc import Mapping
from pathlib import Path

try:
    from ..methods import MemoryMethod, _HISTORICAL, _kind, _stamp, _text, tokenize
except ImportError:
    from methods import MemoryMethod, _HISTORICAL, _kind, _stamp, _text, tokenize
from po_contract import speaker_name, when_phrase

# Assistant label of embedded documents (set by f_bridge.install from "persona_name").
PERSONA_NAME = "Amika"


# ───────────────────────────── the vector sidecar ─────────────────────────────
# A snapshot used to keep every document vector inside state.json as decimal text: at 12,700 vectors
# that was 206 MB of a 218 MB file, re-serialised after every memory job while retrieval waited for
# the lock (a production companion, 2026-10). The vectors now live in a binary sidecar next to the JSON
# ("<stem>.vectors-<digest>.f32": float32 rows, little-endian, in the order of the id list the JSON
# keeps); the JSON holds the events and facts. An id's vector never changes once stored (ingest refuses
# a conflicting one), so rows are only appended: persist() extends a kept buffer and writes it in one
# go. A snapshot without any document vector keeps the plain inline layout, and reload() still reads
# the old inline snapshots.
VECTOR_SUFFIX = ".f32"
VECTOR_TOLERANCE = 1e-6      # float32 storage: a vector read back equals the one ingested up to this


def _same_vector(a, b):
    return len(a) == len(b) and all(abs(float(x) - float(y)) <= VECTOR_TOLERANCE for x, y in zip(a, b))


def _replace_file(target, data):
    """Durable replacement: write beside the target, fsync, rename; never a half-written file."""
    target = Path(target)
    binary = isinstance(data, (bytes, bytearray))
    name = None
    try:
        with tempfile.NamedTemporaryFile(mode="wb" if binary else "w", encoding=None if binary else "utf-8",
                                         dir=target.parent, prefix=target.name + ".", suffix=".tmp",
                                         delete=False) as handle:
            name = handle.name
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(name, target)
        name = None
    finally:
        if name is not None:
            Path(name).unlink(missing_ok=True)


def sidecar_files(state_path):
    """Every vector sidecar beside a snapshot file (one is current; others are left from a failed write)."""
    state_path = Path(state_path)
    return sorted(state_path.parent.glob(f"{state_path.stem}.vectors-*{VECTOR_SUFFIX}"))


class VectorBlob:
    """Document vectors as one float32 row buffer, appended as ids arrive; its sha256 is kept as it grows."""

    def __init__(self, dims):
        self.dims = int(dims)
        self.ids, self.index, self.buf, self._hash = [], {}, bytearray(), hashlib.sha256()

    @classmethod
    def from_bytes(cls, dims, ids, data):
        blob = cls(dims)
        data = bytes(data)
        if len(data) != len(ids) * blob.dims * 4:
            raise ValueError("vector file size does not match its id list")
        blob.ids = [str(ident) for ident in ids]
        blob.index = {ident: row for row, ident in enumerate(blob.ids)}
        if len(blob.index) != len(blob.ids):
            raise ValueError("duplicate ids in vector file")
        blob.buf = bytearray(data)
        blob._hash.update(data)
        return blob

    def append(self, ident, vector):
        if ident in self.index:
            raise ValueError("vector already stored: " + str(ident))
        if len(vector) != self.dims:
            raise ValueError(f"vector of {len(vector)} dimensions in a {self.dims}-dimensional store")
        row = struct.pack(f"<{self.dims}f", *vector)
        self.index[ident] = len(self.ids)
        self.ids.append(ident)
        self.buf += row
        self._hash.update(row)

    def covers(self, documents):
        """True when every stored id is still a document (rows are never removed, only appended)."""
        return all(ident in documents for ident in self.ids)

    def extend(self, documents):
        for ident, vector in documents.items():
            if ident not in self.index:
                self.append(ident, vector)

    def digest(self):
        return self._hash.copy().hexdigest()

    def rows(self):
        """The stored vectors as lists of floats, in id order."""
        return [list(row) for row in struct.iter_unpack(f"<{self.dims}f", self.buf)]

    def __len__(self):
        return len(self.ids)


def _read_sidecar(state_path, stored):
    """The vectors a snapshot keeps beside it, verified: (VectorBlob, {"documents", "queries"})."""
    meta = stored["sidecar"]
    name = str(meta.get("file") or "")
    if not name or Path(name).name != name or not name.endswith(VECTOR_SUFFIX):
        raise ValueError("Unsupported vector file name in snapshot: " + name)
    file = Path(state_path).with_name(name)
    if not file.exists():
        raise ValueError(f"The memory snapshot's vector file {name} is missing beside {Path(state_path).name}: "
                         "restore it from a backup or re-embed with migrate_embeddings.py")
    data = file.read_bytes()
    if hashlib.sha256(data).hexdigest() != meta.get("sha256"):
        raise ValueError("The memory snapshot's vector file " + name + " does not match its recorded digest")
    ids = list(meta.get("ids") or [])
    if len(ids) != int(meta.get("count", len(ids))):
        raise ValueError("The memory snapshot's vector id list does not match its recorded count")
    blob = VectorBlob.from_bytes(int(meta.get("dimensions") or 0), ids, data)
    documents = dict(zip(blob.ids, blob.rows()))
    return blob, {"documents": documents, "queries": dict(stored.get("queries") or {})}


class CandidateF(MemoryMethod):
    """Same retrieve result schema as A–E; episodes are never indexed or used."""

    format_version = 1
    method_name = "Source-backed facts plus hybrid original-event retrieval"
    extraction_requirements = ("facts",)
    embedding_requirements = ("events", "facts")
    preparation_layers = ("facts", "embedding_events", "embedding_facts")
    _SELF_SUBJECTS = {"user", "assistant", "amika"}
    _UNUSABLE = {"invalid", "deleted", "rejected"}

    def __init__(self, events, records, vectors=None, *, _trusted=False):
        # _trusted: the caller hands over fresh objects it never touches again (reload, ingest), so the
        # defensive deep copies are skipped: at 12,000 vectors they cost seconds per ingest (2026-10).
        if vectors is not None and not isinstance(vectors, Mapping):
            raise TypeError("F requires precomputed vector mappings, not callbacks")
        if isinstance(records, list):
            facts = [r for r in records if _kind(r.get("record_type", r.get("type"))) != "episode"]
        elif isinstance(records, Mapping):
            facts = records.get("facts", [])
        else:
            raise TypeError("records must contain a facts list")
        keep = (lambda value: value) if _trusted else copy.deepcopy
        source_records = {"facts": keep(list(facts)), "episodes": []}
        if isinstance(records, Mapping) and "metadata" in records:
            source_records["metadata"] = keep(records["metadata"])
        super().__init__("D", keep(events), source_records, keep(vectors) if vectors is not None else None)
        self.method_id = "F"
        self._vector_blob = None       # persist()'s sidecar buffer, carried across ingest()
        self.loaded_layout = None      # reload(): "inline" (old all-in-one JSON) or "sidecar"
        self._positions = {event["id"]: i for i, event in enumerate(self.events)}
        self._fact_by_id = {item["id"]: item for item in self.fact_items}
        self._older = defaultdict(set)
        self._newer = defaultdict(set)
        self._ambiguous_replacements = defaultdict(set)
        self._build_corrections()

    def _normalise_records(self, records):
        _, facts = super()._normalise_records(records)
        accepted = []
        for fact in facts:
            reason = self._provenance_error(fact)
            if reason:
                self.excluded_records.append({"id": fact["id"], "reason": reason})
            else:
                accepted.append(fact)
        return [], accepted

    @staticmethod
    def _lexical_text(item):
        # Writer summaries/entities can be translated even when the literal
        # source names are not. Index validated speech as well, without changing
        # the stored record, its provenance, or existing document vectors.
        text = MemoryMethod._lexical_text(item)
        if item.get("kind") == "fact":
            text += " " + " ".join(q["quote"] for q in item.get("quotes", []))
        return text

    def _provenance_error(self, fact):
        quotes = fact.get("quotes")
        if not isinstance(quotes, list) or not quotes:
            return "F requires literal speaker-attributed quotation evidence"
        speakers = set()
        for quote in quotes:
            if not isinstance(quote, dict):
                return "invalid quote object"
            source_id, speaker, text = (quote.get(k) for k in ("source_id", "speaker", "quote"))
            if source_id not in fact["source_ids"] or speaker not in {"user", "assistant"}:
                return "unknown or non-dialogue quote provenance"
            source = self.event_by_id[source_id]
            if not isinstance(text, str) or not text.strip() or text not in _text(source.get(speaker)):
                return "quote is not literal text from the attributed source speaker"
            speakers.add(speaker)
        kind = _kind(fact.get("fact_type", "user_fact"))
        if kind == "user_fact" and ("user" not in speakers or fact.get("source_kind") not in {"user", "mixed"}):
            return "an assistant assertion cannot establish a user fact"
        if kind == "assistant_commitment" and "assistant" not in speakers:
            return "assistant commitment lacks assistant speech evidence"
        if _kind(fact.get("status")) in self._UNUSABLE:
            return "invalid or deleted fact"
        for key in ("subject", "predicate", "value"):
            if not isinstance(fact.get(key), str) or not fact[key].strip():
                return "missing structured fact " + key
        return None

    def _order(self, fact):
        return (max((_stamp(self.event_by_id[i].get("time")) for i in fact["source_ids"]), default=0),
                max((self._positions[i] for i in fact["source_ids"]), default=-1),
                _stamp(fact.get("date")))

    @staticmethod
    def _relation(fact):
        # Never equate aliases, first names, shared friends, or matching values.
        return (_text(fact.get("subject")).casefold(), _kind(fact.get("predicate")))

    def _link(self, older, newer):
        if older["id"] == newer["id"] or self._relation(older) != self._relation(newer):
            return
        if self._order(older) > self._order(newer):
            return
        self._older[newer["id"]].add(older["id"])
        self._newer[older["id"]].add(newer["id"])

    def _build_corrections(self):
        ordered = sorted(self.fact_items, key=lambda item: (self._order(item), item["id"]))
        prior = defaultdict(list)
        for fact in ordered:
            links = fact.get("supersedes", [])
            if isinstance(links, str):
                links = [links]
            for fact_id in links:
                old = self._fact_by_id.get(fact_id)
                if old:
                    self._link(old, fact)
            subject, predicate = self._relation(fact)
            # "replaces_prior" is extraction evidence of correction, not an
            # excuse to collapse every property to its newest observed value.
            # Named third parties require explicit fact-ID links: a repeated
            # display name is insufficient proof that two people are identical.
            if fact.get("replaces_prior") is True and subject in self._SELF_SUBJECTS:
                for old in prior[(subject, predicate)]:
                    if self._order(old) < self._order(fact):
                        self._link(old, fact)
            elif fact.get("replaces_prior") is True and not self._older[fact["id"]]:
                # The shared schema has no reliable person/entity type. A
                # named object's correction may be real, but a repeated person
                # name may identify somebody else. Retain competing evidence
                # and surface uncertainty instead of silently treating both as
                # settled current facts or guessing identity.
                for old in prior[(subject, predicate)]:
                    if self._order(old) < self._order(fact):
                        self._ambiguous_replacements[fact["id"]].add(old["id"])
                        self._ambiguous_replacements[old["id"]].add(fact["id"])
            prior[(subject, predicate)].append(fact)

    def _component(self, fact_id):
        seen, pending = set(), [fact_id]
        while pending:
            current = pending.pop()
            if current in seen:
                continue
            seen.add(current)
            pending.extend(self._older[current] | self._newer[current])
        return seen

    def _evidence_ids(self, fact_id):
        seen, pending = set(), [fact_id]
        while pending:
            current = pending.pop()
            if current in seen:
                continue
            seen.add(current)
            pending.extend(self._older[current] | self._newer[current]
                           | self._ambiguous_replacements[current])
        return seen

    # ---- Prompt rendering (natural language; owner request 2026-09-27, CONTRACT §3.7) ----
    # Selection and packing are unchanged. What reaches the prompt is plain speech:
    # perceived times (po_contract.when_phrase against the caller's clock), the
    # configured user name / 我, the literal quotes and short correction notes. Ids,
    # source lists and state labels stay in the diagnostics only.
    _STATUS_NOTES = {
        "zh": {"retracted": "（这条后来被收回了，不算数）", "uncertain": "（这条当时就说得不确定）",
               "superseded": "（这条后来被更正了）", "other": "（这条已经不算数了）"},
        "en": {"retracted": " (later taken back; it does not count)", "uncertain": " (uncertain even then)",
               "superseded": " (later corrected)", "other": " (no longer counts)"},
    }

    @staticmethod
    def _lang(lang):
        return "en" if str(lang or "").lower().startswith("en") else "zh"

    @staticmethod
    def _when(value, now, lang):
        text = str(value or "").strip()
        # A bare date carries no clock time: never attach a time of day to it.
        return when_phrase(text, now, lang, date_only=len(text) <= 10)

    @staticmethod
    def _quoted(text):
        return '"' + _text(text) + '"'

    def _state_note(self, fact, lang):
        zh = lang == "zh"
        if self._newer[fact["id"]]:
            return "（这条后来被更正了，现在的说法见下）" if zh else " (later corrected; the current version follows)"
        status = _kind(fact.get("status", "active"))
        if status != "active":
            notes = self._STATUS_NOTES[lang]
            return notes.get(status, notes["other"])
        if fact.get("valid_to"):
            return "（当时的情况，现在可能已经变了）" if zh else " (how it was then; it may have changed)"
        if fact.get("replaces_prior") is True and not self._older[fact["id"]]:
            return ("（说话者明确作了更正；与旧记录的对应关系尚未确认。按原话中的对象和属性理解，不要推断其他记录已失效）"
                    if zh else " (explicit correction by the speaker; its link to an earlier record is not verified. "
                    "Use the subject and property in the quotation, without assuming other records are superseded)")
        if self._ambiguous_replacements[fact["id"]]:
            return "（有一条可能是更正，还没确认）" if zh else " (one of these may be a correction; not confirmed)"
        return ""

    def _fact_lines(self, fact, now, user_name, lang):
        zh = lang == "zh"
        quotes = [q for q in fact.get("quotes") or [] if isinstance(q, dict)]
        first = self.event_by_id.get(quotes[0].get("source_id")) if quotes else None
        when = self._when(first.get("time") if first else fact.get("date"), now, lang)
        sep = "、" if zh else ", "
        heard = [self._quoted(q.get("quote")) for q in quotes if q.get("speaker") == "user"]
        mine = [self._quoted(q.get("quote")) for q in quotes if q.get("speaker") == "assistant"]
        name = speaker_name("user", user_name, lang)
        gist = _text(fact.get("text")) or " | ".join(_text(fact.get(k)) for k in ("subject", "predicate", "value"))
        if heard:
            head = (f"{when}，{name}说过：" if zh else f"{when}, {name} said: ") + sep.join(heard)
            if mine:
                head += ("；我说过：" if zh else "; I said: ") + sep.join(mine)
        elif mine:
            head = ((f"{when}，我自己说过：" if zh else f"{when}, I said myself: ") + sep.join(mine)
                    + ("（这是我说的，不代表他的事实）" if zh else " (my own words, not a fact about him)"))
        else:
            head = None
        if head is None:
            lines = [(f"{when}，记下的要点：" if zh else f"{when}, noted: ") + gist]
        else:
            lines = [head, f"　（要点：{gist}）" if zh else f"  (gist: {gist})"]
        lines[-1] += self._state_note(fact, lang)
        return lines

    def _fact_packet(self, seed, historical, now=None, user_name="User", lang="zh"):
        ids = self._evidence_ids(seed["id"])
        facts = [self._fact_by_id[i] for i in ids]
        # Chronological, so a corrected claim is always followed by its correction.
        facts.sort(key=lambda item: (self._order(item), item["id"]))
        sources = list(dict.fromkeys(i for fact in facts for i in fact["source_ids"]))
        lines = [line for fact in facts for line in self._fact_lines(fact, now, user_name, lang)]
        return {"id": seed["id"], "member_ids": [f["id"] for f in facts],
                "kind": "quoted_fact_evidence", "date": seed.get("date", ""),
                "source_ids": sources, "text": "\n".join(lines)}

    @staticmethod
    def _excerpt(text, query, limit=1000, marker="[节选]"):
        """Return an exact contiguous speaker excerpt, with explicit cut markers."""
        text = _text(text)
        if len(text) <= limit:
            return text
        terms = set(tokenize(query))
        # Sentence/paragraph starts avoid chopping an opening negation whenever
        # possible. Never synthesize or paraphrase a source utterance.
        boundaries = [0] + [m.end() for m in re.finditer(r"[\n。！？.!?]\s*", text)]
        candidates = []
        for start in boundaries:
            fragment = text[start:start + limit]
            score = len(terms.intersection(tokenize(fragment)))
            candidates.append((score, -start, start))
        start = max(candidates)[2]
        end = min(len(text), start + limit)
        return (marker if start else "") + text[start:end] + (marker if end < len(text) else "")

    def _event_packet(self, event_item, query, now=None, user_name="User", lang="zh"):
        event = self.event_by_id[event_item["id"]]
        zh = lang == "zh"
        marker = "[节选]" if zh else "[excerpt]"
        when = self._when(event.get("time"), now, lang)
        name = speaker_name("user", user_name, lang)
        # The internal interrupt marker never belongs in speech shown to the model.
        heard = _text(event.get("user")).lstrip("&")
        said = _text(event.get("assistant"))
        lines = []
        if heard:
            lines.append((f"{when}，{name}说：" if zh else f"{when}, {name} said: ")
                         + self._quoted(self._excerpt(heard, query, marker=marker)))
            if said:
                lines.append(("我回他：" if zh else "I replied: ")
                             + self._quoted(self._excerpt(said, query, marker=marker)))
        elif said:
            lines.append((f"{when}，我说：" if zh else f"{when}, I said: ")
                         + self._quoted(self._excerpt(said, query, marker=marker)))
        # When an original turn contains an explicitly superseded fact, retrieve
        # its corrective evidence with it even if the query names only old data.
        correction_ids = set()
        for fact in self.fact_items:
            if event["id"] in fact["source_ids"] and (self._newer[fact["id"]]
                                                      or self._ambiguous_replacements[fact["id"]]):
                correction_ids.update(self._evidence_ids(fact["id"]))
        sources = [event["id"]]
        for ident in sorted(correction_ids, key=lambda i: (self._order(self._fact_by_id[i]), i)):
            fact = self._fact_by_id[ident]
            lines.extend(self._fact_lines(fact, now, user_name, lang))
            sources.extend(fact["source_ids"])
        return dict(event_item, text="\n".join(lines), source_ids=list(dict.fromkeys(sources)),
                    member_ids=[event["id"], *sorted(correction_ids)])

    @staticmethod
    def _pack_complete(packets, budget):
        chunks, sources, selected, skipped = [], [], [], []
        remaining = budget
        for packet in packets:
            block = ("\n\n" if chunks else "") + packet["text"]
            # A claim must never squeeze out its evidence or its correction.
            # Skip an oversized packet; later compact packets may still fit.
            if len(block) > remaining:
                skipped.append(packet["id"])
                continue
            chunks.append(block)
            remaining -= len(block)
            sources.extend(packet["source_ids"])
            selected.extend(packet.get("member_ids", [packet["id"]]))
        return "".join(chunks), list(dict.fromkeys(sources)), list(dict.fromkeys(selected)), skipped

    @classmethod
    def render(cls, packets, budget_chars):
        """Pack already-rendered candidate packets into one block of at most
        budget_chars characters. Same rule as retrieve(): half the budget is reserved
        for original speech first, then fact groups not already covered, then the
        remaining original speech. Lets a caller render one retrieval twice (deep and
        surface budgets) without a second query."""
        budget = max(0, int(budget_chars))
        packets = packets or {}
        event_packets = list(packets.get("events", []))
        text, sources, selected, skipped = cls._pack_complete(event_packets, budget // 2)
        fact_packets = [p for p in packets.get("facts", []) if not set(p["member_ids"]).issubset(selected)]
        fact_group_count = len(fact_packets)

        def append_packets(candidates):
            nonlocal text, sources, selected, skipped
            available = max(0, budget - len(text) - (2 if text else 0))
            extra, new_sources, new_selected, new_skipped = cls._pack_complete(candidates, available)
            if extra:
                text += ("\n\n" if text else "") + extra
            sources = list(dict.fromkeys(sources + new_sources))
            selected = list(dict.fromkeys(selected + new_selected))
            skipped.extend(new_skipped)
        append_packets(fact_packets)
        append_packets([p for p in event_packets if p["id"] not in selected])
        skipped = list(dict.fromkeys(ident for ident in skipped if ident not in selected))
        return {"text": text, "source_ids": sources, "selected_record_ids": selected,
                "skipped_oversize_packet_ids": skipped, "fact_group_count": fact_group_count,
                "budget_chars": budget, "returned_chars": len(text)}

    def retrieve(self, query, budget_chars=8000, now=None, user_name="User", lang="zh", exclude_ids=None,
                 fact_packets=6, event_candidates=8):
        """Hybrid retrieval (unchanged selection) rendered as natural language.

        now: the caller's clock (naive or aware local datetime) for the perceived-time
        phrases; user_name / lang: how the user is named and which phrase table is used.
        exclude_ids: event ids still visible in the recent conversation window; they are
        dropped from the original-event candidates without backfilling from lower ranks.
        The result keeps the A-E schema (text, source_ids, diagnostics) and adds
        `packets` so the caller can render the same retrieval at a second budget.
        fact_packets / event_candidates: how many fact groups and original-event
        candidates are considered (TELEMETRY_SPEC §4; the live config sets 4 / 5)."""
        if not isinstance(query, str):
            raise TypeError("query must be text")
        budget = max(0, int(budget_chars))
        fact_limit = max(0, int(fact_packets))
        event_limit = max(0, int(event_candidates))
        lang = self._lang(lang)
        excluded_ids = set(exclude_ids or ())
        self._query_vector = self._get_query_vector(query)
        historical = bool(_HISTORICAL.search(query))
        fact_packets, seen = [], set()
        for fact, _ in self._rank(self.fact_items, query, hybrid=True) if fact_limit else ():
            if fact["id"] in seen:
                continue
            packet = self._fact_packet(fact, historical, now, user_name, lang)
            seen.update(packet["member_ids"])
            fact_packets.append(packet)
            if len(fact_packets) >= fact_limit:
                break
        ranked_events = [item for item, _ in self._rank(self.event_items, query, hybrid=True)[:event_limit]]
        excluded = [item["id"] for item in ranked_events if item["id"] in excluded_ids]
        event_packets = [self._event_packet(item, query, now, user_name, lang)
                         for item in ranked_events if item["id"] not in excluded_ids]
        packets = {"events": event_packets, "facts": fact_packets}
        # Reserve half the prompt capacity for original speech before any
        # derived claim. Unused capacity can be borrowed, so tiny corpora do not
        # waste half the budget. Each packet still includes its corrections.
        rendered = self.render(packets, budget)
        return {"text": rendered["text"], "source_ids": rendered["source_ids"], "packets": packets, "diagnostics": {
            "method_id": "F", "method_name": self.method_name, "custom_prototype": True,
            "extraction_requirements": list(self.extraction_requirements),
            "budget_chars": budget, "returned_chars": len(rendered["text"]),
            "selected_record_ids": rendered["selected_record_ids"], "truncated_record_ids": [],
            "skipped_oversize_packet_ids": rendered["skipped_oversize_packet_ids"],
            "event_count": len(self.safe_events), "excluded_event_count": len(self.events) - len(self.safe_events),
            "facts_available": len(self.facts), "episodes_available": 0,
            "excluded_records": self.excluded_records,
            "semantic_query_available": self._query_vector is not None,
            "retrieval_mode": "BM25+vector_RRF" if self._query_vector is not None else "BM25",
            "semantic_backend": self._last_semantic_backend if self._query_vector is not None else None,
            "historical_query": historical, "fact_group_count": rendered["fact_group_count"],
            "original_event_candidates": len(event_packets),
            "fact_packets_limit": fact_limit, "event_candidates_limit": event_limit,
            "excluded_in_window_event_ids": excluded,
            "selected_episode_count": 0,
            "original_evidence_reserved_chars": budget // 2,
            "correction_links": sum(map(len, self._newer.values())),
            "unresolved_replacement_pairs": sum(map(len, self._ambiguous_replacements.values())) // 2,
            "person_alias_merges": 0,
            "render": {"style": "natural", "language": lang, "user_name": user_name},
        }}

    def embedding_items(self):
        # Match build_index.py's shared document representation exactly.
        output = {}
        for event in self.safe_events:
            pieces = [f"Date: {event['time']}"]
            if event.get("user"):
                pieces.append("User: " + event["user"])
            if event.get("assistant"):
                pieces.append(PERSONA_NAME + ": " + event["assistant"])
            if event.get("cue"):
                pieces.append("Operator cue (not user speech): " + event["cue"])
            output[event["id"]] = "\n".join(pieces)
        for fact in self.facts:
            output[fact["id"]] = (f"Date: {fact['date']}\nSource speakers: {fact['source_kind']}\n{fact['text']}\n"
                                  + "Entities: " + ", ".join(fact.get("entities", [])))
        return output

    def ingest(self, events, records, vectors=None):
        """Merge caller-extracted facts/vectors, atomically in memory; no APIs.

        Repeated identical IDs are idempotent. Conflicts require a new versioned
        ID, not overwriting source evidence. The caller must assign unique chunk
        IDs to the shared extractor before ingestion. Returns ingestion counts.
        """
        if not isinstance(records, Mapping):
            raise TypeError("incremental records must be a facts mapping")
        def merge(old, new, label):
            output = {item["id"]: item for item in old}      # this model's own items: read, never changed
            added = 0
            for item in new:
                ident = item.get("id")
                if not ident:
                    raise ValueError(label + " needs a nonempty id")
                if ident in output and output[ident] != item:
                    raise ValueError("Conflicting " + label + " id: " + ident)
                if ident not in output:
                    output[ident] = copy.deepcopy(item)
                    added += 1
            return list(output.values()), added
        merged_events, event_count = merge(self.events, events, "event")
        merged_facts, fact_count = merge(self.records["facts"], records.get("facts", []), "fact")
        current = self._vector_payload(self.vectors)
        incoming = self._vector_payload(vectors)
        for kind in ("documents", "queries"):
            for ident, value in incoming[kind].items():
                if ident in current[kind]:
                    if not _same_vector(current[kind][ident], value):
                        raise ValueError("Conflicting vector for " + ident)
                    continue
                current[kind][ident] = [float(v) for v in value]
        replacement = type(self)(merged_events, {"facts": merged_facts, "episodes": []}, current, _trusted=True)
        replacement._vector_blob = self._vector_blob
        # E: the recall indexes (vector matrix, lexical counters) extend themselves with the new items
        replacement._vector_index, replacement._lexical_cache = self._vector_index, self._lexical_cache
        self.__dict__.clear()
        self.__dict__.update(replacement.__dict__)
        return {"events_added": event_count, "facts_added": fact_count, "episodes_added": 0}

    @staticmethod
    def _vector_payload(vectors):
        """{"documents": {id: vector}, "queries": {query: vector}} as new dicts over the same vectors
        (nothing mutates a stored vector; a deep copy here cost seconds per call at scale)."""
        if vectors is None:
            return {"documents": {}, "queries": {}}
        if not isinstance(vectors, Mapping):
            raise TypeError("F requires precomputed vector mappings")
        documents = vectors.get("documents", vectors.get("vectors"))
        if documents is None:
            documents = {k: v for k, v in vectors.items() if k not in {"queries", "__queries__"}}
        queries = vectors.get("__queries__", vectors.get("queries", {}))
        return {"documents": dict(documents), "queries": dict(queries)}

    def persist(self, path, inline=False):
        """Write the snapshot: events and facts as JSON, the document vectors in the binary sidecar beside it
        (see VectorBlob). inline=True writes the old all-in-one JSON layout: a self-contained backup."""
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        vectors = self._vector_payload(self.vectors)
        documents = vectors["documents"]
        stale = {file.name: file for file in sidecar_files(target)}
        if inline or not documents:
            stored = vectors
            if not documents:
                self._vector_blob = None
        else:
            dims = len(next(iter(documents.values())))
            blob = self._vector_blob
            if blob is None or blob.dims != dims or not blob.covers(documents):
                blob = VectorBlob(dims)
            blob.extend(documents)                   # only the rows not stored yet
            self._vector_blob = blob
            digest = blob.digest()
            sidecar = target.with_name(f"{target.stem}.vectors-{digest[:16]}{VECTOR_SUFFIX}")
            if sidecar.name not in stale:            # unchanged vectors: the file on disk is already this one
                _replace_file(sidecar, bytes(blob.buf))
            stale.pop(sidecar.name, None)
            stored = {"queries": vectors["queries"],
                      "sidecar": {"file": sidecar.name, "sha256": digest, "dimensions": blob.dims,
                                  "count": len(blob), "ids": list(blob.ids)}}
        payload = {"format_version": self.format_version, "method_id": "F", "events": self.events,
                   "records": self.records, "vectors": stored}
        # R21(a): serialise once, then write the whole text (json.dump streams many small writes).
        _replace_file(target, json.dumps(payload, ensure_ascii=False, sort_keys=True, allow_nan=False))
        for file in stale.values():                  # sidecars no snapshot names any more
            with contextlib.suppress(OSError):
                file.unlink()

    @classmethod
    def reload(cls, path, vectors=None):
        path = Path(path)
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
        if payload.get("format_version") != cls.format_version or payload.get("method_id") != "F":
            raise ValueError("Unsupported candidate F artifact")
        stored, blob, layout = payload.get("vectors"), None, "inline"
        if vectors is None and isinstance(stored, Mapping) and isinstance(stored.get("sidecar"), Mapping):
            blob, stored = _read_sidecar(path, stored)
            layout = "sidecar"
        model = cls(payload["events"], payload["records"], vectors if vectors is not None else stored,
                    _trusted=vectors is None)
        model._vector_blob = blob
        model.loaded_layout = layout
        return model

    save = persist
    load = reload
