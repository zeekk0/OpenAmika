"""Shared output contract for OpenAmika.

One module, installed unchanged in both the brain folder (brain/) and the
speech folder (STT), so both sides parse the same model output the same way.

Covers:
  - the emotion-tag vocabulary (69 real TTS keys, aliases, resolution)
  - the sound-effect vocabulary (9 names) and placeholder rejection
  - deep-output extraction (tagged quotes, untagged quotes before 我心想,
    loose tags, sanitiser, blurt-prefix dedupe, thought text)
  - surface-output parsing (status / tone / mode / reply; no recall)
  - per-turn reply language (detect, explicit one-turn switch, Chinese line)
  - template placeholder contract and self-check (CLI: --check-templates DIR)

Pure Python, no third-party imports. Keep it importable from both folders.
"""
from __future__ import annotations

import json
import re
import sys
import unicodedata
from pathlib import Path
from typing import Dict, List, Optional, Tuple

CONTRACT_VERSION = "po-3"

# ---------------------------------------------------------------- emotions
REGISTERS = ("polite", "casual", "serious", "intimate", "whisper")

# The real keys of the Amika_JA_v2 voice. Same table as STT/tts_emotion.py;
# tts_emotion imports these from here and a parity test asserts equality.
EMOTION_SETS: Dict[str, Tuple[str, ...]] = {
    "polite": ("neutral", "smile", "happy", "caring", "sad", "worried",
               "cold", "angry", "embarrassed", "surprise", "fear"),
    "casual": ("neutral", "smile", "happy", "very_happy", "playful", "laughing",
               "relieved", "shy", "embarrassed", "mumbling", "jealous", "caring",
               "surprise", "angry", "frustrated", "sad", "tired", "fear", "worried"),
    "serious": ("neutral", "cold", "disappointed", "surprise", "angry", "very_angry",
                "protective", "worried", "anxious", "sad", "fear"),
    "intimate": ("neutral", "happy", "very_happy", "smile", "playful", "shy",
                 "very_shy", "caring", "very_caring", "jealous", "mumbling",
                 "relieved", "tearful", "sad", "very_sad", "sleepy", "tired", "worried"),
    "whisper": ("neutral", "happy", "smile", "caring", "relieved", "shy",
                "sad", "worried", "tearful", "sleepy"),
}
VALID_EMOTIONS = frozenset(f"{r}_{e}" for r, es in EMOTION_SETS.items() for e in es)
DEFAULT_EMOTION = "casual_neutral"       # missing or unusable tag
_DEFAULT_REGISTER = "casual"

EMOTION_ALIASES = {
    "curious": "smile", "friendly": "smile", "warm": "caring", "gentle": "caring",
    "soft": "caring", "tender": "caring", "excited": "very_happy", "amused": "laughing",
    "teasing": "playful", "mischievous": "playful", "proud": "smile", "grateful": "smile",
    "thankful": "smile", "calm": "relieved", "annoyed": "frustrated", "irritated": "frustrated",
    "pout": "frustrated", "sulky": "frustrated", "grumpy": "frustrated", "nervous": "anxious",
    "scared": "fear", "afraid": "fear", "confused": "surprise", "shocked": "surprise",
    "surprised": "surprise", "delighted": "very_happy", "furious": "angry", "mad": "angry",
    "flustered": "embarrassed", "thoughtful": "neutral", "serious": "neutral", "lonely": "sad",
    "hurt": "sad", "upset": "sad", "bored": "tired", "sleepy": "sleepy", "sigh": "tired",
    "giggle": "laughing", "giggling": "laughing", "laugh": "laughing", "smiling": "smile",
    "crying": "tearful", "cry": "tearful", "anger": "angry", "fearful": "fear",
    "embarrased": "embarrassed", "embarassed": "embarrassed", "suprise": "surprise",
    "surprize": "surprise", "worry": "worried", "happiness": "happy", "joy": "happy",
    "joyful": "happy", "sadness": "sad", "relief": "relieved", "tease": "playful",
    "shyness": "shy", "jealousy": "jealous", "mumble": "mumbling", "protect": "protective",
    "disappoint": "disappointed", "disapointed": "disappointed", "anxiety": "anxious",
}
REGISTER_ALIASES = {
    "formal": "polite", "public": "polite", "friendly": "casual", "normal": "casual",
    "relaxed": "casual", "stern": "serious", "firm": "serious", "close": "intimate",
    "soft": "intimate", "private": "intimate", "quiet": "whisper", "whispering": "whisper",
    "whispered": "whisper", "hushed": "whisper",
}
REGISTER_FALLBACK = {
    "polite": {"anxious": "worried", "disappointed": "sad", "protective": "caring",
               "laughing": "happy", "frustrated": "cold", "shy": "embarrassed",
               "relieved": "smile", "playful": "smile", "mumbling": "embarrassed",
               "jealous": "cold", "tearful": "sad", "tired": "neutral", "sleepy": "neutral"},
    "casual": {"anxious": "worried", "disappointed": "sad", "cold": "frustrated",
               "protective": "caring", "tearful": "sad", "sleepy": "tired"},
    "serious": {"caring": "protective", "frustrated": "cold", "jealous": "cold",
                "tearful": "sad", "embarrassed": "neutral", "tired": "neutral"},
    "intimate": {"anxious": "worried", "fear": "worried", "angry": "mumbling",
                 "disappointed": "sad", "cold": "sad", "protective": "caring",
                 "embarrassed": "shy", "laughing": "happy", "frustrated": "mumbling"},
    "whisper": {"anxious": "worried", "fear": "worried", "angry": "worried",
                "disappointed": "sad", "cold": "sad", "protective": "caring",
                "embarrassed": "shy", "laughing": "smile", "frustrated": "worried",
                "playful": "smile", "mumbling": "shy", "jealous": "worried",
                "tired": "sleepy", "very_happy": "happy"},
}


def normalize_tag(raw: Optional[str]) -> str:
    """Loose spelling -> canonical `register_emotion` shape (not yet validated)."""
    t = (raw or "").strip().lower().strip("[]【】 \t")
    t = t.replace("-", "_").replace(" ", "_").replace("/", "_").replace(".", "_")
    t = t.split(",")[0].split("，")[0]
    t = re.sub(r"_?\d+(?:_\d+)?$", "", t)       # intensity numbers: shy 0.4 -> shy
    t = re.sub(r"_+", "_", t).strip("_")
    return t


def _canon_emotion(emotion: str) -> str:
    if emotion in EMOTION_ALIASES:
        return EMOTION_ALIASES[emotion]
    if emotion.startswith("very_"):
        base = emotion[len("very_"):]
        if base in EMOTION_ALIASES:
            return "very_" + EMOTION_ALIASES[base]
    return emotion


def _split_register(tag: str) -> Tuple[Optional[str], str]:
    for register in REGISTERS:
        if tag.startswith(register + "_"):
            return register, tag[len(register) + 1:]
        if tag == register:
            return register, "neutral"
    head, _, rest = tag.partition("_")
    if head in REGISTER_ALIASES and rest:
        return REGISTER_ALIASES[head], rest
    return None, tag


def resolve_emotion(tag: Optional[str], default: str = DEFAULT_EMOTION) -> str:
    """Any tag text -> a real key. Empty/unusable -> `default` (casual_neutral)."""
    t = normalize_tag(tag)
    if not t:
        return default
    register, emotion = _split_register(t)
    if register is None:
        register, emotion = _DEFAULT_REGISTER, t
    avail = EMOTION_SETS[register]
    emotion = _canon_emotion(emotion)
    if emotion in avail:
        return f"{register}_{emotion}"
    if emotion.startswith("very_"):
        base = emotion[len("very_"):]
        if base in avail:
            return f"{register}_{base}"
        emotion = base
    sub = REGISTER_FALLBACK.get(register, {}).get(emotion)
    if sub and sub in avail:
        return f"{register}_{sub}"
    return f"{register}_neutral"


def emotion_vocab_lines() -> List[str]:
    """Canonical machine-readable vocabulary lines for the templates
    (`register: e1 e2 ...`). check_template() parses these back."""
    return [f"{r}: {' '.join(EMOTION_SETS[r])}" for r in REGISTERS]


# ------------------------------------------------------------------- sfx
SFX_NAMES = ("Laugh", "Can_t_help_laughing", "Soft_hmph", "Sigh", "Deep_breath",
             "Yawn", "Sniff", "Light_cough", "Throat_clear")
_SFX_LOWER = {n.lower(): n for n in SFX_NAMES}
SFX_ALIAS = {"laughs": "Laugh", "laughing": "Laugh", "chuckle": "Laugh", "giggle": "Laugh",
             "cant_help_laughing": "Can_t_help_laughing", "can_t_help_laugh": "Can_t_help_laughing",
             "hmph": "Soft_hmph", "soft_humph": "Soft_hmph", "sighs": "Sigh", "sigh_": "Sigh",
             "breath": "Deep_breath", "deep_breathe": "Deep_breath", "yawns": "Yawn",
             "sniffle": "Sniff", "sniffs": "Sniff", "cough": "Light_cough", "coughs": "Light_cough",
             "clear_throat": "Throat_clear", "throat_clearing": "Throat_clear", "ahem": "Throat_clear"}
SFX_PLACEHOLDERS = frozenset({"声效名", "声效", "sfx", "sfx_name", "register_emotion", "tag",
                              "emotion", "语气", "语气标签", "name", "声效标签"})
SFX_TAG_RE = re.compile(r"【\s*([A-Za-z][A-Za-z_ \-]*)\s*】")
CONTROL_RE = re.compile(r"【\s*(?:想想|接着说)\s*】")
HELP_RE = re.compile(r"【\s*想想\s*】")
CONTINUE_RE = re.compile(r"【\s*接着说\s*】")
_ANY_SFX_LIKE_RE = re.compile(r"【\s*([^】\n]{1,24})\s*】")


def canonical_sfx(name: Optional[str]) -> Optional[str]:
    """Closed vocabulary: the 9 names (case-insensitive, a few aliases). Placeholders
    the model copied from the rule text (【声效名】, 【register_emotion】) -> None."""
    n = (name or "").strip().lower().replace(" ", "_").replace("-", "_")
    if not n or n in SFX_PLACEHOLDERS:
        return None
    if n in _SFX_LOWER:
        return _SFX_LOWER[n]
    return SFX_ALIAS.get(n)


def strip_sfx(text: str) -> str:
    """Remove every 【...】 sound-effect or placeholder tag (not the Chinese control
    markers, which are stripped by strip_controls)."""
    out = _ANY_SFX_LIKE_RE.sub(lambda m: " " if not re.fullmatch(r"(?:想想|接着说)", m.group(1).strip()) else m.group(0), text)
    return re.sub(r"[ \t]{2,}", " ", out)


def strip_controls(text: str) -> str:
    return CONTROL_RE.sub("", text)


# --------------------------------------------------------------- deep text
OPEN_QUOTES = "“\"「『"
CLOSE_QUOTES = "”\"」』"
_QUOTE_CLOSE_FOR = {"“": "”\"", "\"": "”\"", "「": "」", "『": "』"}
_TAG_TOKEN = r"\[\s*([A-Za-z][A-Za-z_\- ,]*?)\s*(?:\d+(?:\.\d+)?\s*)?\]"
TAG_RE = re.compile(_TAG_TOKEN)
# A tagged quote closes at its matching close quote, or at the next tag (the model
# forgot to close), or at the end of the text. Corner brackets pair strictly, so
# 『...』 inside a "..." segment stays inside it.
_NESTED_TAG_AHEAD = r"(?=\s*\[[A-Za-z][A-Za-z_\- ,]*?\s*(?:\d+(?:\.\d+)?\s*)?\])"
TAGGED_QUOTE_RE = re.compile(
    _TAG_TOKEN + r"\s*[:：]?\s*(?:"
    r"[“\"](?P<b1>.*?)(?:[”\"]|" + _NESTED_TAG_AHEAD + r"|\Z)|"
    r"「(?P<b2>.*?)(?:」|" + _NESTED_TAG_AHEAD + r"|\Z)|"
    r"『(?P<b3>.*?)(?:』|" + _NESTED_TAG_AHEAD + r"|\Z))", re.S)
# `[tag]` followed by unquoted text on the same line: speech with missing quotes.
# Not when the text is a parenthesis (that is a thought written after a tag).
TAGGED_BARE_RE = re.compile(_TAG_TOKEN + r"[ \t]*[:：]?[ \t]*([^\n“\"「『\[【（(][^\n]*)")
THINK_RE = re.compile(r"我(?:心想|反思|思考)[:：]")
SAY_RE = re.compile(r"我(?:接着)?[说說][:：]")
LANG_LABELS = ("中文", "日本語", "日语", "English", "英文", "英语",
               "Korean", "한국어", "韩语", "韓語", "韓国語")
LANG_TAG_RE = re.compile(r"^\s*[（(]\s*(?:" + "|".join(LANG_LABELS) + r")\s*[）)]\s*", re.I)
MD_SPAN_RE = re.compile(r"[*＊]{1,2}([^*＊\n]{1,120})[*＊]{1,2}")
LITERAL_NL_RE = re.compile(r"\\n")
_SEPARATOR_RE = re.compile(r"^[\s\-—–_=~·]*$")
_PUNCT_ONLY_RE = re.compile(r"^[\s,，.。、!！?？…—\-~～:：;；]*$")


def _md_span(m: "re.Match") -> str:
    inner = m.group(1).strip()
    han, kana, latin = lang_counts(inner)
    if han and not latin and not hangul_count(inner) and len(inner) <= 12:  # *笑了一下*: action
        return " "
    return inner                                     # *The Glass Orchard* : emphasis


def sanitize_speech(text: str) -> str:
    """Text that will be spoken. Keeps 【SFX】 tags (the speech layer plays them),
    removes what must never reach TTS: leaked tags, control markers, markdown
    asterisks (a short CJK action span is dropped whole), literal backslash-n,
    language labels, stray quote marks."""
    t = LANG_TAG_RE.sub("", text or "")
    t = strip_controls(t)
    t = MD_SPAN_RE.sub(_md_span, t)
    t = LITERAL_NL_RE.sub(" ", t)
    t = TAG_RE.sub(" ", t)
    t = re.sub(r"[“”\"「」『』]", "", t)
    t = " ".join(t.split())
    return t.strip()


def _norm_for_match(s: str) -> str:
    return "".join(ch for ch in (s or "").lower()
                   if not unicodedata.category(ch).startswith(("P", "S", "Z")))


_CJK_RE = re.compile(r"[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\uff66-\uff9f]")
_LEAD_PUNCT = " \t,，.。…、;；:：!！?？-—–"
# Blurt strip (owner request 2026-10-05): the deep often repeats only the first sentence or the first
# words of the surface's blurt, not the whole line. A repeated prefix is stripped when it ends on a word
# boundary on both sides, is at least BLURT_MIN_* normalised characters long, and either stops where the
# blurt has sentence-final punctuation (its first sentence was repeated) or covers BLURT_MIN_SHARE of the
# blurt, or when the whole blurt was repeated. A shared opener that diverges mid-clause ("Wait— you have
# all that?" vs "Wait— you have salmon…") stays, so no sentence is cut into a fragment (125 live turns
# reviewed: 29 whole-line repeats, 2 first-clause repeats, 2 shared openers kept).
BLURT_MIN_LATIN = 6
BLURT_MIN_CJK = 3
BLURT_MIN_SHARE = 0.7
_CLAUSE_PUNCT_RE = re.compile(r"[.!?。！？…]")   # sentence-final only: "Okay, so—" is a shared opener, not a repeated clause


def _match_units(s: str) -> list:
    """Letters/digits/CJK of `s` in order as (lower char, raw index, boundary after it). Punctuation, symbols
    and spaces are skipped; a boundary is the end, a following space/punctuation, or a CJK character on
    either side (every CJK character is a word of its own)."""
    units = []
    n = len(s or "")
    for i, ch in enumerate(s or ""):
        if ch.isspace() or unicodedata.category(ch).startswith(("P", "S", "Z", "C")):
            continue
        nxt = s[i + 1] if i + 1 < n else ""
        boundary = (not nxt or nxt.isspace() or unicodedata.category(nxt).startswith(("P", "S", "Z", "C"))
                    or bool(_CJK_RE.match(ch)) or bool(_CJK_RE.match(nxt)))
        folded = unicodedata.normalize("NFKC", ch)      # full-width letters/digits (ＯＫ) compare as plain ones
        units.append(((folded if len(folded) == 1 else ch).lower(), i, boundary))
    return units


def blurt_threshold(blurt: Optional[str]) -> int:
    """Minimum normalised characters a repeated prefix must have (6 for spaced scripts, 3 for CJK)."""
    units = _match_units(blurt or "")
    if not units:
        return 0
    cjk = sum(1 for u in units if _CJK_RE.match(u[0])) * 2 > len(units)
    return BLURT_MIN_CJK if cjk else BLURT_MIN_LATIN


def _repeat_counts(blurt: str, bu: list, matched: int) -> bool:
    """A prefix of `matched` units counts as a repeat when the blurt has clause punctuation right after it
    (the deep repeated a whole sentence/clause) or when it covers BLURT_MIN_SHARE of the blurt."""
    if matched <= 0:
        return False
    if matched >= len(bu):
        return True
    if matched / len(bu) >= BLURT_MIN_SHARE:
        return True
    span = blurt[bu[matched - 1][1] + 1:bu[matched][1]]
    return bool(_CLAUSE_PUNCT_RE.search(span))


# C19, widened 2026-11-02 from 147 real turns (the prefix rule caught 77 echoes and missed 6): the deep may
# put a short lead-in before the echo ("Wait— 'turn your lights right out'?", "...Yeah. Your sleep schedule."),
# and may repeat a later clause of the blurt instead of its start ("Let me have Hermes pull some up for you"
# for "Photos, huh… Okay, let me have Hermes pull some up for you"). A lead-in of at most BLURT_MAX_LEAD
# letters is skipped and dropped together with the echo (it only ever introduces the repeat).
BLURT_MAX_LEAD = 12
# A repeated later clause must begin right after punctuation in the blurt, end at the blurt's end or before a
# sentence-final mark, and cover this share of the blurt (the shortest real miss covered 0.69; "Let's go" of
# "Okay. Let's go." covers 0.60 and stays).
BLURT_MIN_CLAUSE_SHARE = 0.65
_LEAD_BOUNDARY_RE = re.compile(r"[,，、;；:：.!?。！？…—–\-]")   # where a later clause may begin inside the blurt
_ECHO_TAIL = _LEAD_PUNCT + "'\"’”」』)）"                       # what an echo drags along after its last word
# A lead-in is only ever an interjection ("Wait, hold on—", "...Yeah.", "哈哈，"): a lead-in made of anything
# else ("Hermes, what's 17 times 23?" before the surface's "17 times 23? Hold on—") is her own sentence, kept.
BLURT_LEAD_WORDS = frozenset((
    "wait", "hold", "on", "hang", "yeah", "yes", "yep", "yup", "no", "nope", "nah", "hmm", "hm", "mm", "mmm",
    "huh", "hah", "ha", "haha", "hahaha", "heh", "oh", "ah", "aw", "ooh", "okay", "ok", "well", "right", "so",
    "um", "uh", "hey", "wow", "whoa", "ugh", "oops", "see", "look", "geez", "god", "man", "dude", "honestly",
    "嗯", "哦", "啊", "呃", "诶", "欸", "呀", "哈", "哈哈", "等", "等等", "等一下", "等下", "好", "好吧", "好的",
    "是", "是的", "对", "对了", "行", "哇", "啧", "噢", "唔", "嘛", "那", "那个", "不", "不是",
    "え", "えっ", "ええ", "うん", "ううん", "ああ", "あ", "まあ", "はい", "いや", "ちょっと", "待って", "えー", "へえ", "ふーん",
))


def _is_lead_in(letters: str) -> bool:
    """True when `letters` (a lead-in with spaces and punctuation removed) is made only of interjections."""
    n = len(letters)
    if not n:
        return True
    ok = [True] + [False] * n
    for i in range(1, n + 1):
        ok[i] = any(ok[j] and letters[j:i] in BLURT_LEAD_WORDS for j in range(max(0, i - 8), i))
    return ok[n]


def strip_echo_tail(rest: str) -> str:
    """What follows a stripped echo: its closing quote/bracket and punctuation go with it."""
    return (rest or "").lstrip(_ECHO_TAIL)


def _run_counts(blurt: str, bu: list, start: int, run: int) -> bool:
    """A run of `run` units matching the blurt from unit `start` counts as a repeat. From the blurt's start:
    the prefix rule (_repeat_counts). From a later clause: it must begin right after punctuation, end at the
    blurt's end or before a sentence-final mark, and cover BLURT_MIN_CLAUSE_SHARE of the blurt."""
    if run <= 0:
        return False
    if start == 0:
        return _repeat_counts(blurt, bu, run)
    if run / len(bu) < BLURT_MIN_CLAUSE_SHARE:
        return False
    if not _LEAD_BOUNDARY_RE.search(blurt[bu[start - 1][1] + 1:bu[start][1]]):
        return False
    end = start + run
    if end >= len(bu):
        return True
    return bool(_CLAUSE_PUNCT_RE.search(blurt[bu[end - 1][1] + 1:bu[end][1]]))


def _align(tu: list, bu: list, ts: int, bs: int) -> tuple:
    """Match tu[ts:] against bu[bs:] unit by unit: (units compared, units matched at the last common word
    boundary, raw cut index in the text right after that boundary)."""
    i = last_boundary = cut = 0
    n = min(len(tu) - ts, len(bu) - bs)
    while i < n and tu[ts + i][0] == bu[bs + i][0]:
        if tu[ts + i][2] and bu[bs + i][2]:
            last_boundary, cut = i + 1, tu[ts + i][1] + 1
        i += 1
    return i, last_boundary, cut


def _blurt_alignment(text: str, blurt: Optional[str]) -> tuple:
    """How the start of `text` repeats `blurt`, trying every lead-in boundary of the text (within
    BLURT_MAX_LEAD letters) against every word boundary of the blurt. Returns
    (state, cut, matched, full, threshold, start) — see match_blurt_prefix; start = the blurt unit the echo
    begins at. The longest counting repeat wins; otherwise an alignment the text ran out inside is "pending"."""
    bu = _match_units(blurt or "")
    tu = _match_units(text or "")
    threshold = blurt_threshold(blurt)
    if not bu:
        return ("no", 0, 0, False, 0, 0)
    if not tu:
        return ("pending", 0, 0, False, threshold, 0)
    blurt_starts = [0] + [k + 1 for k in range(len(bu) - 1) if bu[k][2]]
    text_starts = [0]
    for k in range(min(len(tu) - 1, BLURT_MAX_LEAD)):      # lead-in boundaries, as long as it stays an interjection
        if tu[k][2]:
            if not _is_lead_in("".join(u[0] for u in tu[:k + 1])):
                break
            text_starts.append(k + 1)
    best = pending = None
    for ts in text_starts:
        for bs in blurt_starts:
            i, last_boundary, cut = _align(tu, bu, ts, bs)
            if i == 0:
                continue
            whole = bs == 0 and i == len(bu) and last_boundary == i
            # the whole blurt repeated counts however short it is ("Tacos?", "I know."); anything shorter
            # than the whole must reach the threshold and pass the clause/share rules
            if whole or (last_boundary >= threshold and _run_counts(blurt or "", bu, bs, last_boundary)):
                if best is None or cut > best[0]:
                    best = (cut, last_boundary, whole, bs)
            elif ts + i == len(tu) and bs + i < len(bu):           # text ran out while still matching
                if pending is None or last_boundary > pending[0]:
                    pending = (last_boundary, bs)
    if best is not None:
        return ("strip", best[0], best[1], best[2], threshold, best[3])
    if pending is not None:
        return ("pending", 0, pending[0], False, threshold, pending[1])
    return ("no", 0, 0, False, threshold, 0)


def match_blurt_prefix(text: str, blurt: Optional[str]) -> tuple:
    """Compare the start of `text` with `blurt` ignoring case, punctuation, symbols and spaces.

    Returns (state, cut, matched, full, threshold):
      state    "no"      — nothing to strip (diverged before a countable repeat, or no blurt / no letters yet)
               "strip"   — a repeat: drop text[:cut] (cut sits after a word boundary in `text`; a short
                           lead-in before the echo goes with it)
               "pending" — `text` ran out while still matching the blurt; the streaming gate holds it and
                           the final decision (dedupe_blurt) strips it all if the matched part counts
      matched  normalised characters matched at the last common word boundary; full = whole blurt matched;
      threshold = blurt_threshold(blurt). A repeat counts when matched ≥ threshold and _run_counts()."""
    return _blurt_alignment(text, blurt)[:5]


def dedupe_blurt(text: str, blurt: Optional[str]) -> str:
    """The deep often repeats the surface's blurted opener (the whole line, its first sentence, its first
    words, a later clause of it, or any of those behind a short lead-in); drop that. A first segment that is
    nothing but such a repeat becomes empty."""
    state, cut, matched, full, threshold, start = _blurt_alignment(text, blurt)
    if state == "strip":
        return strip_echo_tail(text[cut:])
    if state == "pending" and matched >= threshold and _run_counts(blurt or "", _match_units(blurt or ""), start, matched):
        return ""
    return text


def _line_prefix_is_clear(masked: str, line_start: int, i: int) -> bool:
    """True when nothing but whitespace, punctuation, masked spans, 【SFX】 tags or a
    我说：/我接着说： label precedes position i on its line."""
    prefix = masked[line_start:i]
    prefix = SAY_RE.sub("", prefix)
    prefix = _ANY_SFX_LIKE_RE.sub("", prefix)
    return bool(_PUNCT_ONLY_RE.match(prefix))


def extract_deep(raw: str, blurt: Optional[str] = None) -> dict:
    """Non-streaming extraction (brain side). Returns
    {segments: [{text, tone}], speech, thought, needs_help, wants_continue}.

    Rules (mirrored by the speech layer's streaming extractor):
      1. `[tag]"..."` anywhere is speech; tag resolved through resolve_emotion.
         The segment ends at the matching close quote, at the next `[tag]`, or at
         the end of the text.
      2. `[tag]` followed by unquoted text on the same line is speech (missing
         quotes tolerated), unless that text is a （parenthesis）.
      3. Before the thought boundary (first 我心想/我反思/我思考 marker, or a
         【想想】 that precedes it), an untagged quote whose line prefix is empty
         (or only 我说：, 【SFX】, punctuation) and whose close is followed by
         nothing substantial on that line is speech; tone = the last tag seen
         before it, else casual_neutral. A quotation inside narration is not.
      4. Quotes after the boundary are thought, unless tagged.
      5. Everything else after the boundary is thought; before it, unquoted
         lines are thought (kept for the archive, never spoken).
    """
    raw = raw or ""
    think_m = THINK_RE.search(raw)
    think_pos = think_m.start() if think_m else len(raw)
    help_m = HELP_RE.search(raw)
    if help_m and help_m.start() < think_pos and raw[help_m.end():].strip():
        think_pos = help_m.start()
    found: List[dict] = []
    mask = list(raw)

    def take(start: int, end: int) -> None:
        for i in range(start, end):
            if mask[i] != "\n":
                mask[i] = " "

    for m in TAGGED_QUOTE_RE.finditer(raw):
        body = m.group("b1") or m.group("b2") or m.group("b3") or ""
        found.append({"start": m.start(), "text": sanitize_speech(body),
                      "tone": resolve_emotion(m.group(1)), "tagged": True})
        take(m.start(), m.end())
    masked = "".join(mask)
    for m in TAGGED_BARE_RE.finditer(masked):
        body = m.group(2)
        if THINK_RE.search(body) or not body.strip():
            continue
        found.append({"start": m.start(), "text": sanitize_speech(body),
                      "tone": resolve_emotion(m.group(1)), "tagged": True})
        take(m.start(), m.end())
    masked = "".join(mask)
    i = 0
    line_start = 0
    while i < think_pos:
        ch = masked[i]
        if ch == "\n":
            line_start = i + 1
            i += 1
            continue
        if ch in OPEN_QUOTES and _line_prefix_is_clear(masked, line_start, i):
            closers = _QUOTE_CLOSE_FOR[ch]
            close = next((j for j in range(i + 1, len(masked)) if masked[j] in closers), None)
            if close is not None and close <= think_pos:
                nl2 = masked.find("\n", close + 1)
                tail = masked[close + 1:nl2 if nl2 != -1 else len(masked)]
                tail = _ANY_SFX_LIKE_RE.sub("", tail).lstrip()
                if _PUNCT_ONLY_RE.match(tail) or tail[:1] in OPEN_QUOTES or tail.startswith("["):
                    last = max((f for f in found if f["start"] < i), key=lambda f: f["start"], default=None)
                    found.append({"start": i, "text": sanitize_speech(masked[i + 1:close]),
                                  "tone": last["tone"] if last else DEFAULT_EMOTION, "tagged": False})
                    take(i, close + 1)
                    masked = "".join(mask)
                    i = close + 1
                    continue
        i += 1
    masked = "".join(mask)
    found.sort(key=lambda x: x["start"])
    segments = []
    for k, f in enumerate(found):
        text = f["text"]
        if k == 0 and blurt:
            text = dedupe_blurt(text, blurt)
        if text:
            segments.append({"text": text, "tone": f["tone"]})
    speech = " ".join(strip_sfx(s["text"]).strip() for s in segments).strip()
    speech = " ".join(speech.split())
    after = masked[think_m.end():] if think_m else masked
    thought_lines = []
    for ln in after.splitlines():
        ln = SAY_RE.sub("", ln)
        ln = TAG_RE.sub("", ln)
        ln = strip_sfx(strip_controls(ln)).strip().lstrip("，。、 ")
        if ln and not _SEPARATOR_RE.match(ln):
            thought_lines.append(ln)
    thought = "\n".join(thought_lines).strip()
    return {"segments": segments, "speech": speech, "thought": thought,
            "needs_help": bool(HELP_RE.search(raw)), "wants_continue": bool(CONTINUE_RE.search(raw))}


# ------------------------------------------------------------- surface text
SURFACE_FIELDS = ("status", "tone", "mode", "reply")
_FIELD_LINE_RE = re.compile(r"^\s*(status|tone|mode|reply|recall)\s*[:：][ \t]*(.*?)\s*$", re.I)


def norm_status(s: str) -> str:
    t = (s or "").strip().lower()
    if not t:
        return "ok"
    if "unfin" in t or "没说完" in t or "half" in t:
        return "unfinished"
    if ("not" in t and "me" in t) or "不是" in t or "别人" in t or "杂音" in t:
        return "not-for-me"
    return "ok"


def norm_mode(s: str, reply: str, status: str = "ok") -> str:
    """say / say+think / think. An empty reply in say mode becomes think (let the
    deep speak) only when the turn is addressed to her (status ok); for
    unfinished / not-for-me turns an empty say reply stays silent."""
    t = re.sub(r"[\s_]+", "", (s or "").lower())
    if "think" in t and "say" in t:
        mode = "say+think"
    elif "think" in t:
        mode = "think"
    elif "say" in t:
        mode = "say"
    else:
        mode = "say" if reply else ("think" if status == "ok" else "say")
    if mode == "say" and not reply and status == "ok":
        mode = "think"
    return mode


def parse_surface(raw: str) -> dict:
    """status / tone / mode / reply. `reply` is one line. `speak_filler` is True
    whenever there is a reply line to speak (also in think mode: it is spoken and
    passed to the deep as the blurt)."""
    fields: Dict[str, str] = {}
    first_free_line = ""
    for line in (raw or "").splitlines():
        m = _FIELD_LINE_RE.match(line)
        if m:
            key = m.group(1).lower()
            if key not in fields:
                fields[key] = m.group(2).strip()
        elif not first_free_line and line.strip() and not TAG_RE.fullmatch(line.strip()):
            first_free_line = line.strip()
    reply = fields.get("reply", "")
    if "reply" not in fields and first_free_line:
        reply = first_free_line
    reply = sanitize_speech(reply)
    tone_raw = fields.get("tone", "")
    status = norm_status(fields.get("status", ""))
    return {"status": status, "tone_raw": tone_raw,
            "tone": resolve_emotion(tone_raw), "mode": norm_mode(fields.get("mode", ""), reply, status),
            "reply": reply, "speak_filler": bool(reply)}


# --------------------------------------------------------------- language
_HAN = re.compile(r"[一-鿿㐀-䶿]")
_KANA = re.compile(r"[぀-ヿㇰ-ㇿ]")
_LATIN = re.compile(r"[A-Za-z]")
_HANGUL = re.compile(r"[\u1100-\u11ff\u3130-\u318f\ua960-\ua97f\uac00-\ud7a3\ud7b0-\ud7ff]")
LANG_NAMES_ZH = {"zh": "中文", "en": "英语", "ja": "日语", "ko": "韩语"}
LANG_TO_TTS = {"zh": "Chinese", "en": "English", "ja": "Japanese", "ko": "Korean"}


def hangul_count(text: str) -> int:
    """Count Hangul syllables/jamo after NFC analysis, without changing stored text."""
    return len(_HANGUL.findall(unicodedata.normalize("NFC", text or "")))


def lang_counts(text: str) -> Tuple[int, int, int]:
    t = text or ""
    return len(_HAN.findall(t)), len(_KANA.findall(t)), len(_LATIN.findall(t))


def detect_lang(text: str) -> Optional[str]:
    """'zh' | 'en' | 'ja' | 'ko' | 'mixed' | None (no letters at all).

    Romanized Korean is ambiguous and is not automatically classified as Korean.
    """
    han, kana, latin = lang_counts(text)
    hangul = hangul_count(text)
    if hangul:
        # Keep the legacy no-Hangul heuristics intact. With Korean present,
        # require the same 60% dominance rather than kana's legacy shortcut.
        counts = {"zh": han, "en": latin, "ja": kana, "ko": hangul}
        top = max(counts, key=counts.get)
        return top if counts[top] / sum(counts.values()) >= 0.6 else "mixed"
    total = han + kana + latin
    if total == 0:
        return None
    if kana and kana / total > 0.15:
        return "ja"
    if kana and han and latin == 0:
        return "ja"
    ratios = {"zh": han / total, "en": latin / total, "ja": kana / total}
    top = max(ratios, key=ratios.get)
    if ratios[top] < 0.6:
        return "mixed"
    return top


def is_kanji_only(text: str) -> bool:
    han, kana, latin = lang_counts(text)
    return han > 0 and kana == 0 and latin == 0 and hangul_count(text) == 0


_SWITCH_PATTERNS = [
    (re.compile(r"\b(?:in|into|speak|use|using|switch(?:ing)? to|try|answer in|reply in|say (?:it|this|that)? ?in)\s+(japanese|english|chinese|mandarin|cantonese)\b", re.I), None),
    (re.compile(r"(?:用|说|講|讲|换成?|改用|试试|教我|来点|来句|说句)\s*(日语|日文|日本語|英语|英文|中文|汉语|国语|普通话)"), None),
    (re.compile(r"(日本語|英語|中国語)で"), None),
]
_LANG_WORD = {"japanese": "ja", "english": "en", "chinese": "zh", "mandarin": "zh", "cantonese": "zh",
              "日语": "ja", "日文": "ja", "日本語": "ja", "英语": "en", "英文": "en", "英語": "en",
              "中文": "zh", "汉语": "zh", "国语": "zh", "普通话": "zh", "中国語": "zh",
              "korean": "ko", "韩语": "ko", "韓語": "ko", "韓国語": "ko",
              "한국어": "ko", "영어": "en", "일본어": "ja", "중국어": "zh"}

# New request forms are intentionally narrower than the legacy switch rules:
# mentioning a Korean book or a Korean-speaking friend is not an instruction.
_KOREAN_SWITCH_PATTERNS = (
    re.compile(r"(?:^|[.!?]\s*)(?:(?:can|could|would) you\s+)?(?:please\s+)?(?:reply|answer|respond|speak|say|use|switch|translate)(?:\s+(?:it|this|that))?(?:\s+(?:in|into|to))?\s+(korean)\b", re.I),
    re.compile(r"\bhow (?:do|would|can) (?:I|you|we) say\b[^.!?\n]*\bin\s+(korean)\b", re.I),
    re.compile(r"(?:^|[。！？!?，,]\s*)(?:请|請|麻烦|麻煩)?(?:用|说|講|讲|换成?|改用|试试|教我|来点|来句|说句)\s*(韩语|韓語)"),
    re.compile(r"(韓国語)で(?:答えて|話して|言って|お願い|返事|返答)"),
    re.compile(r"(한국어|영어|일본어|중국어)로\s*(?:(?:짧게|간단히|간단하게)\s+)?(?:말해|답해|대답해|답변해|이야기해|번역해|인사해)\s*(?:줘|주세요|줄래|줄래요)?[.!?。？！~ ]*$"),
)


def explicit_switch(text: str) -> Optional[str]:
    """An explicit request to answer in a language, valid for this turn only."""
    for pat in _KOREAN_SWITCH_PATTERNS:
        m = pat.search(unicodedata.normalize("NFC", text or ""))
        if m:
            return _LANG_WORD[m.group(1).lower()]
    for pat, _ in _SWITCH_PATTERNS:
        m = pat.search(text or "")
        if m:
            return _LANG_WORD.get(m.group(1).lower())
    return None


def reply_lang(user_text: str, prev_lang: Optional[str]) -> Tuple[Optional[str], str]:
    """(lang, reason). reason in {'switch','detected','inherited','unknown'}."""
    sw = explicit_switch(user_text)
    if sw:
        return sw, "switch"
    d = detect_lang(user_text)
    if d == "ko" or (d in ("zh", "en", "ja") and len((user_text or "").strip()) >= 2):
        return d, "detected"
    if prev_lang in LANG_NAMES_ZH:
        return prev_lang, "inherited"
    return None, "unknown"


EXCEPTION_CLAUSE = ("除非对方刚刚有特别的约定或要求（比如让我用日语回答、问我某句话用日语怎么说、"
                    "让我翻译或者念一遍），那就照对方要的来。")
# Owner's rule (2026-10-24): her spoken language follows the person, whole turn, every turn. Two allowances:
# an explicit request (switch / translate / repeat), and a one-or-two-phrase stylistic touch — telling him how
# a line goes in Japanese, a quick 「ご主人様？」 — after which she returns to his language at once.
STYLE_CLAUSE = ("点到为止的一两句外语可以有——告诉他某句话用日语或中文怎么讲、顺口翻译一句、或者一句撒娇式的日语短句"
                "（「ご主人様？」这种）——说完立刻回到{name}。")
# Proactive turns taught us this: the coach's cue and the bracketed reactions are written in Chinese for her
# eyes; without this guard she answered the cue in Chinese mid-English-conversation (2026-10-24).
GUARD_CLAUSE = ("系统给我的提示、括号里的反应、思考层的话都是中文写的，那是我自己看的，绝不能因此改用中文开口。")


def language_line(lang: Optional[str], reason: str = "detected") -> str:
    """The per-turn Chinese language instruction placed last in the deep prompt."""
    if reason == "switch" and lang:
        name = LANG_NAMES_ZH[lang]
        return (f"对方刚刚要求这句用{name}说，那这一句我说出口的话就用{name}；"
                f"下一句再照对方自己说的语言来。我心想照常用中文。")
    if lang:
        name = LANG_NAMES_ZH[lang]
        # "inherited": no new words from him this turn (a proactive turn, noise) — the conversation's language rules
        who = f"对方这句说的是{name}" if reason == "detected" else f"对方这段对话一直在用{name}"
        return (f"【语言】{who}，我说出口的每一句都用{name}，整段都是，不半路换语言。{EXCEPTION_CLAUSE}"
                f"{STYLE_CLAUSE.format(name=name)}{GUARD_CLAUSE}我心想照常用中文。")
    return (f"【语言】对方这句听不出是什么语言，我说出口的话就用对方最近在用的语言，整段都是；"
            f"{EXCEPTION_CLAUSE}{GUARD_CLAUSE}我心想照常用中文。")


# --------------------------------------------------------- perceived time
# Natural-language rendering of memory records (owner request 2026-09-27): every
# timestamp becomes a perceived relative phrase plus the time of day, computed by
# code at render time, never a raw date. The buckets are perceptual, not exact.
from datetime import datetime, timedelta

_REL_BUCKETS = [  # (upper bound in minutes, zh, en)
    (20, "几分钟前", "a few minutes ago"),
    (45, "半小时前", "half an hour ago"),
    (90, "一小时前", "an hour ago"),
    (150, "两小时前", "two hours ago"),
    (210, "三小时前", "three hours ago"),
    (510, "几小时前", "a few hours ago"),
    (990, "半天前", "half a day ago"),
    (36 * 60, "一天前", "a day ago"),
    (60 * 60, "两天前", "two days ago"),
    (84 * 60, "三天前", "three days ago"),
    (6.5 * 24 * 60, "几天前", "a few days ago"),
    (10.5 * 24 * 60, "一周前", "a week ago"),
    (17.5 * 24 * 60, "两周前", "two weeks ago"),
    (22 * 24 * 60, "三周前", "three weeks ago"),
    (27 * 24 * 60, "几周前", "a few weeks ago"),
    (45 * 24 * 60, "一个月前", "a month ago"),
    (75 * 24 * 60, "两个月前", "two months ago"),
    (105 * 24 * 60, "三个月前", "three months ago"),
    (150 * 24 * 60, "几个月前", "a few months ago"),
    (270 * 24 * 60, "半年前", "half a year ago"),
    (450 * 24 * 60, "一年前", "a year ago"),
]
_REL_BEYOND = ("一年多前", "more than a year ago")
_REL_UNKNOWN = ("之前", "a while back")
_REL_FUTURE = ("刚刚", "just now")
# Time of day uses the persona's own period names (same boundaries as webui._get_period).
_PERIODS = [  # (start hour inclusive, end hour exclusive, zh, en)
    (5, 8, "清晨", "early morning"), (8, 12, "上午", "morning"), (12, 14, "中午", "noon"),
    (14, 17, "下午", "afternoon"), (17, 19, "傍晚", "evening"), (19, 22, "晚上", "night"),
]
_LATE_NIGHT = ("深夜", "late night")
_PERIOD_FROM_MINUTES = 90         # attach the time of day from "two hours ago" onwards


def parse_when(value) -> Optional[datetime]:
    """'2026-07-01 20:37:40' | '2026-07-01' | ISO 8601 | datetime -> naive local datetime (None if unusable)."""
    if isinstance(value, datetime):
        return value.replace(tzinfo=None) if value.tzinfo else value
    s = str(value or "").strip()
    if not s:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        return None


def time_of_day(dt: Optional[datetime], lang: str = "zh") -> str:
    if dt is None:
        return ""
    for start, end, zh, en in _PERIODS:
        if start <= dt.hour < end:
            return zh if lang == "zh" else en
    return _LATE_NIGHT[0] if lang == "zh" else _LATE_NIGHT[1]


def perceived_ago(when, now, lang: str = "zh") -> str:
    """Perceived distance between `when` and `now` (both naive local datetimes)."""
    dt = parse_when(when)
    if dt is None or now is None:
        return _REL_UNKNOWN[0] if lang == "zh" else _REL_UNKNOWN[1]
    minutes = (parse_when(now) - dt).total_seconds() / 60.0
    if minutes < -5:
        return _REL_FUTURE[0] if lang == "zh" else _REL_FUTURE[1]
    for bound, zh, en in _REL_BUCKETS:
        if minutes < bound:
            return zh if lang == "zh" else en
    return _REL_BEYOND[0] if lang == "zh" else _REL_BEYOND[1]


_SPAN_NEUTRAL = ("一段时间", "a while")


def perceived_span(minutes, lang: str = "zh") -> str:
    """Perceived length of a gap of `minutes` (TELEMETRY_SPEC §3 history separators):
    the perceived_ago buckets without 前 / ' ago' (几分钟 / 半小时 / 一小时 / … / 半天 / 一天 /
    两天 / …, beyond the last bucket 一年多). None, non-numbers and negative values give a
    neutral 一段时间 / 'a while' (nothing is invented)."""
    zh = lang == "zh"
    try:
        value = float(minutes)
    except (TypeError, ValueError):
        value = None
    if value is None or value != value or value < 0:
        return _SPAN_NEUTRAL[0] if zh else _SPAN_NEUTRAL[1]
    for bound, zh_text, en_text in _REL_BUCKETS:
        if value < bound:
            return zh_text[:-1] if zh else en_text[:-len(" ago")]
    return _REL_BEYOND[0][:-1] if zh else _REL_BEYOND[1][:-len(" ago")]


def when_phrase(when, now, lang: str = "zh", date_only: bool = False) -> str:
    """'三个月前的上午' / 'three months ago in the morning'. Below ~3.5 hours the time
    of day is omitted (it is implied); `date_only` records (no clock) never get one."""
    dt = parse_when(when)
    ago = perceived_ago(dt, now, lang)
    if dt is None or date_only:
        return ago
    minutes = (parse_when(now) - dt).total_seconds() / 60.0 if now is not None else 0
    if minutes < _PERIOD_FROM_MINUTES:
        return ago
    period = time_of_day(dt, lang)
    return f"{ago}的{period}" if lang == "zh" else f"{ago} in the {period}"


# The character this brain plays (f_bridge.install sets it from config/build_f.json "persona_name").
PERSONA_NAME = "Amika"


def speaker_name(speaker: str, user_name: str, lang: str = "zh") -> str:
    """speaker=user -> the configured user name; speaker=assistant -> 我 / I."""
    s = (speaker or "").strip().lower()
    if s in ("user", "human"):
        return user_name
    if s in ("assistant", "amika", "ai", "me") or s == PERSONA_NAME.lower():
        return "我" if lang == "zh" else "I"
    return speaker or user_name


# --------------------------------------------------------------- templates
DEEP_REQUIRED = ("recent_mood", "current_action", "relationship_context", "communication_style",
                 "daily_context", "current_scene", "current_time", "memories_block", "conversation_history",
                 "pending_mind", "blurt_block", "say_marker", "deep_instruction", "language_line")
# Identity tokens any template may use in its prose: who she lives with and where (build_f.json user_name / city).
IDENTITY_PLACEHOLDERS = ("user_name", "city")
DEEP_OPTIONAL = ("danmaku_picks", "video_view") + IDENTITY_PLACEHOLDERS
SURFACE_REQUIRED = ("recent_mood", "current_action", "relationship_context", "communication_style",
                    "daily_context", "current_scene", "current_time", "memories_block", "conversation_history",
                    "detected_lang")
SURFACE_OPTIONAL = ("video_view",) + IDENTITY_PLACEHOLDERS
THINKING_REQUIRED = ("recent_mood", "current_action", "relationship_context", "communication_style",
                     "daily_context", "current_scene", "current_time", "memories_block",
                     "thinking_history", "deep_request")
THINKING_OPTIONAL = IDENTITY_PLACEHOLDERS
# The cache-static region ends at this placeholder in all three templates.
DYNAMIC_START = "daily_context"
# Order constraints (owner layout decision 2026-09-27, final): static blocks first; then daily context,
# current scene, time line, memory block, the recent history (15 turns, ending with the user line),
# and the short per-turn closing lines.
_STATIC_FOUR = ("recent_mood", "current_action", "relationship_context", "communication_style")
_ORDER = {
    "deep": [(a, "daily_context") for a in _STATIC_FOUR] + [
        ("daily_context", "current_scene"), ("current_scene", "current_time"),
        ("current_time", "conversation_history"), ("conversation_history", "memories_block"),
        ("memories_block", "pending_mind"), ("pending_mind", "blurt_block"),
        ("blurt_block", "say_marker"), ("say_marker", "deep_instruction"),
        ("deep_instruction", "language_line")],
    "surface": [(a, "daily_context") for a in _STATIC_FOUR] + [
        ("daily_context", "current_scene"), ("current_scene", "current_time"),
        ("current_time", "conversation_history"), ("conversation_history", "memories_block"),
        ("memories_block", "detected_lang")],
    "thinking": [(a, "daily_context") for a in _STATIC_FOUR] + [
        ("daily_context", "current_scene"), ("current_scene", "current_time"),
        ("current_time", "thinking_history"), ("thinking_history", "memories_block"),
        ("memories_block", "deep_request")],
}
TSUNDERE_EXAMPLE = '[casual_shy]"才、才没有在意你说的话。"'
_PLACEHOLDER_RE = re.compile(r"\{([a-z_]+)\}")
_VOCAB_LINE_RE = re.compile(r"^\s*(polite|casual|serious|intimate|whisper)\s*[:：]\s*([a-z_ ]+?)\s*$", re.M)
KNOWN_PLACEHOLDERS = frozenset(DEEP_REQUIRED + DEEP_OPTIONAL + SURFACE_REQUIRED + SURFACE_OPTIONAL
                               + THINKING_REQUIRED + ("weekday", "weekday_yesterday", "local_time"))


def check_template(kind: str, text: str) -> List[str]:
    """Problems with a template file (empty list = OK)."""
    req, opt = {"deep": (DEEP_REQUIRED, DEEP_OPTIONAL), "surface": (SURFACE_REQUIRED, SURFACE_OPTIONAL),
                "thinking": (THINKING_REQUIRED, THINKING_OPTIONAL)}[kind]
    problems: List[str] = []
    if text.startswith("﻿"):
        problems.append("file starts with a UTF-8 BOM")
    names = _PLACEHOLDER_RE.findall(text)
    counts: Dict[str, int] = {}
    for n in names:
        counts[n] = counts.get(n, 0) + 1
    for n in req:
        if counts.get(n, 0) == 0:
            problems.append(f"missing placeholder {{{n}}}")
        elif counts[n] > 1:
            problems.append(f"placeholder {{{n}}} appears {counts[n]} times")
    for n in counts:
        if n not in req and n not in opt:
            problems.append(f"unknown placeholder {{{n}}}")
    pos = {n: text.find("{" + n + "}") for n in counts}
    for a, b in _ORDER[kind]:
        if a in pos and b in pos and pos[a] > pos[b]:
            problems.append(f"{{{a}}} must come before {{{b}}}")
    if kind in ("deep", "surface"):
        vocab = {m.group(1): set(m.group(2).split()) for m in _VOCAB_LINE_RE.finditer(text)}
        for r in REGISTERS:
            if r not in vocab:
                problems.append(f"no emotion vocabulary line for register {r} (expected `{r}: ...`)")
            elif vocab[r] != set(EMOTION_SETS[r]):
                extra = sorted(vocab[r] - set(EMOTION_SETS[r]))
                missing = sorted(set(EMOTION_SETS[r]) - vocab[r])
                problems.append(f"emotion vocabulary for {r} differs: extra={extra} missing={missing}")
        for n in SFX_NAMES:
            if n not in text:
                problems.append(f"sound effect {n} not listed")
    if kind == "deep" and TSUNDERE_EXAMPLE not in text:
        problems.append("tsundere format example missing (must stay as in the original)")
    if kind == "surface" and re.search(r"\brecall\b", text, re.I):
        problems.append("surface template still mentions recall")
    if kind == "deep" and "[模版]" in text:
        problems.append("deep template still contains a literal [模版] line (use {deep_instruction})")
    return problems


def leftover_placeholders(filled: str) -> List[str]:
    """Known placeholder names still present after filling."""
    return sorted({n for n in _PLACEHOLDER_RE.findall(filled) if n in KNOWN_PLACEHOLDERS})


def split_static(template: str) -> Tuple[str, str]:
    """(cache-static prefix, dynamic remainder) at {daily_context}."""
    idx = template.find("{" + DYNAMIC_START + "}")
    if idx == -1:
        return template, ""
    return template[:idx], template[idx:]


def check_template_dir(folder: Path) -> Dict[str, List[str]]:
    files = {"deep": "例子.txt", "surface": "表层.txt", "thinking": "思考.txt"}
    out = {}
    for kind, name in files.items():
        p = Path(folder) / name
        if not p.is_file():
            out[name] = [f"missing file {p}"]
            continue
        out[name] = check_template(kind, p.read_bytes().decode("utf-8"))
    return out


def read_text_bom(path) -> str:
    """UTF-8 text with an optional BOM stripped (templates, scenes, config)."""
    return Path(path).read_bytes().decode("utf-8-sig")


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    if len(sys.argv) >= 3 and sys.argv[1] == "--check-templates":
        result = check_template_dir(Path(sys.argv[2]))
        bad = 0
        for name, problems in result.items():
            print(f"{name}: {'OK' if not problems else ''}")
            for p in problems:
                bad += 1
                print(f"  - {p}")
        sys.exit(1 if bad else 0)
    if len(sys.argv) >= 2 and sys.argv[1] == "--vocab":
        print("\n".join(emotion_vocab_lines()))
        sys.exit(0)
    print(json.dumps({"version": CONTRACT_VERSION, "emotions": len(VALID_EMOTIONS), "sfx": SFX_NAMES}, ensure_ascii=False))
