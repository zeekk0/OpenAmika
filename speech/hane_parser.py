"""Hane LLM 原始输出的流式抽取（OpenAmika）。

Hane 推回的 surface_chunk / deep_chunk 是 LLM 的**原始**续写，里面带字段标签
（status: / tone: / mode: / reply:）或者情绪标签加引号（[casual_happy]"..."）。
真正要 TTS 的只是其中的 speech 部分——所以在喂给分句器之前，这里做一次流式抽取。

规则来源：共享契约模块 `po_contract`（大脑和发声端装同一个文件）。
  - 表层：`po_contract.parse_surface`（契约 §1.2）
  - 深层：`po_contract.extract_deep`（契约 §1.1 规则 1-6）
本模块是它们的**流式镜像**：同一批正则、同一个 sanitize_speech / dedupe_blurt /
canonical_sfx；逐 chunk 喂进来，按 chunk 吐出 speech 增量。回放校验见
`replay/speech_parity_check.py`：把 1,752 条存档深层输出按随机大小切块喂进来，拼出的
每段文字/语气必须和 extract_deep 完全一致（表层 987 条对 parse_surface 同理）。

Extractor 返回的是一批 `(emotion_key, delta_text)` 二元组：
- emotion_key：已通过 resolve_emotion 兜底后的 TTS key（如 `casual_happy`），缺省 casual_neutral。
- delta_text：本次新增的 speech 文本；或者声效哨兵（tts_sfx.make_sfx_delta）。
  深层每段结束时补一个 `\\n`（分句器据此断句，保证不同 tone 段的 speech 不会被粘进同一句）。

深层流式的几个要点：
  * 带标签的引号段（`[tag]"..."`）边来边吐（和以前一样快），右引号 / 下一个 `[tag]` / 流结束封段；
    “”/"" 互为收尾，「」『』严格配对。
  * `[tag]` 后面同一行没引号的话（`[casual_happy] Hi there`）也是台词：等这一行写完再吐。
  * 没标签的引号：只在「想法边界」（第一个 我心想：/我反思：/我思考：，或在它之前的【想想】）之前、
    行首干净、收尾后同一行没有实质内容时才算台词，语气沿用前面最近一个标签。
    **防想法泄漏**：这种引号在右引号到达、这一行的尾巴判定完之前一个字都不吐；判成想法就整段丢弃。
  * 输出严格按原文位置顺序：前面还有没判定的候选时，后面的段先憋着。
  * 第一段做 blurt 去重（表层已经说出口的开场白，深层又重复一遍）：api 在 surface_done 时
    set_blurt(reply)；第一段的开头先憋住，直到能判定是否以 blurt 开头为止。
"""

import logging
import re
from typing import Dict, List, Optional, Tuple

from po_contract import (
    CONTROL_RE,
    DEFAULT_EMOTION,
    HELP_RE,
    LANG_TAG_RE,
    LANG_LABELS,
    LITERAL_NL_RE,
    MD_SPAN_RE,
    OPEN_QUOTES,
    TAG_RE,
    TAGGED_BARE_RE,
    TAGGED_QUOTE_RE,
    THINK_RE,
    _ANY_SFX_LIKE_RE,
    _FIELD_LINE_RE,
    _PUNCT_ONLY_RE,
    _QUOTE_CLOSE_FOR,
    _line_prefix_is_clear,
    _md_span,
    _LEAD_PUNCT,
    strip_echo_tail,
    _norm_for_match,
    dedupe_blurt,
    match_blurt_prefix,
    resolve_emotion,
    sanitize_speech,
)
from tts_sfx import SfxScanner, make_sfx_delta

Parts = List[Tuple[Optional[str], str]]
_log = logging.getLogger("yumeha")      # api.py's logger

# ---------------------------------------------------------------- helpers
# sanitize_speech 的"去引号"那一步（同一组字符）
_QUOTE_MARK_RE = re.compile(r"[“”\"「」『』]")
_LANG_WORDS = tuple(word.casefold() for word in LANG_LABELS)
_LANG_OPEN = "（("
_LANG_CLOSE = "）)"
_STARS = "*＊"
# 还没写完、以后可能补成 【想想】/【接着说】 的尾巴（整段 fullmatch 到结尾）
_CONTROL_PARTIAL_RE = re.compile(r"【\s*(?:想(?:想\s*)?|接(?:着(?:说\s*)?)?)?")
# 还没写完、以后可能补成 TAG_RE（`[ tag 0.5]`）的尾巴
_TAG_PARTIAL_RE = re.compile(r"\[\s*(?:[A-Za-z][A-Za-z_\- ,]*\s*(?:\d+(?:\.\d*)?\s*)?)?")
# 引号段内"下一个标签"前瞻（po_contract._NESTED_TAG_AHEAD，`[` 后不允许空白）的未完成尾巴
_AHEAD_PARTIAL_RE = re.compile(r"\[(?:[A-Za-z][A-Za-z_\- ,]*\s*(?:\d+(?:\.\d*)?\s*)?)?")
# 未完成的 TAGGED_QUOTE_RE 开头（`[tag]` + 空白/冒号，引号还没到）
_PENDING_OPEN_RE = re.compile(
    r"\[\s*(?:[A-Za-z][A-Za-z_\- ,]*\s*(?:\d+(?:\.\d*)?\s*)?(?:\]\s*(?:[:：]\s*)?)?)?")
# 表层字段行开头（与 po_contract._FIELD_LINE_RE 的前半一致）
_REPLY_HEAD_RE = re.compile(r"^\s*reply\s*[:：]", re.I)
# str.splitlines() 认的全部换行符
_LINE_BREAKS = "\n\r\x0b\x0c\x1c\x1d\x1e\x85  "
_LINE_BREAK_RE = re.compile("[" + re.escape(_LINE_BREAKS) + "]")


def _lang_label_undecided(buf: str) -> bool:
    """buf 以 `（`/`(` 开头（前面可有空白），还判断不了是不是 `（English）` 这种语言标签。"""
    s = buf.lstrip()
    if not s or s[0] not in _LANG_OPEN:
        return False
    if LANG_TAG_RE.match(buf) or any(c in s for c in _LANG_CLOSE):
        return False
    r = s[1:].lstrip().casefold()
    return any(w.startswith(r) or (r.startswith(w) and not r[len(w):].strip()) for w in _LANG_WORDS)


def _md_undecided(line: str) -> Optional[int]:
    """最后一行里第一个"还说不准"的星号位置（MD_SPAN_RE 的判定要看后面的字）；都定了返回 None。"""
    pos = 0
    n = len(line)
    while True:
        q = min((i for i in (line.find(s, pos) for s in _STARS) if i != -1), default=-1)
        if q == -1:
            return None
        m = MD_SPAN_RE.match(line, q)
        if m:
            if m.end() == n and m.end() - m.end(1) == 1:
                return q                      # 收尾只有一个星号，后面可能还有第二个
            pos = m.end()
            continue
        if MD_SPAN_RE.match(line + "*", q) or MD_SPAN_RE.match(line + "x*", q):
            return q                          # 再来几个字就可能成对
        pos = q + 1


class _Stage:
    """sanitize_speech 的一步，流式：缓冲 → 找安全切点 → 切点前的部分整段做这一步。
    安全切点 = 这一步的任何匹配都不会跨过它（后面的字不会改变切点前的结果）。"""

    def __init__(self):
        self.buf = ""

    def feed(self, s: str) -> str:
        if s:
            self.buf += s
        if not self.buf:
            return ""
        c = self.cut(self.buf)
        if c <= 0:
            return ""
        piece, self.buf = self.buf[:c], self.buf[c:]
        return self.apply(piece)

    def flush(self) -> str:
        piece, self.buf = self.buf, ""
        return self.apply(piece) if piece else ""

    def cut(self, b: str) -> int:
        return len(b)

    def apply(self, piece: str) -> str:
        return piece


class _LabelControlStage(_Stage):
    """① 开头的语言标签 `（English）`（只在整段最前面）② 【想想】/【接着说】。"""

    def __init__(self):
        super().__init__()
        self.first = True

    def cut(self, b: str) -> int:
        if self.first and (not b.strip() or _lang_label_undecided(b)):
            return 0
        c = len(b)
        i = b.rfind("【")
        if i != -1 and _CONTROL_PARTIAL_RE.fullmatch(b, i):
            c = i
        if self.first:
            m = LANG_TAG_RE.match(b)
            if m and c < m.end():
                return 0
        return c

    def apply(self, piece: str) -> str:
        if self.first:
            piece = LANG_TAG_RE.sub("", piece)
            self.first = False
        return CONTROL_RE.sub("", piece)


class _MarkdownStage(_Stage):
    """③ markdown 星号（*动作* 整段丢，*强调* 留字）。匹配不跨行，只看最后一行里没判定的星号。"""

    def cut(self, b: str) -> int:
        ls = b.rfind("\n") + 1
        q = _md_undecided(b[ls:])
        return len(b) if q is None else ls + q

    def apply(self, piece: str) -> str:
        return MD_SPAN_RE.sub(_md_span, piece)


class _LiteralNewlineStage(_Stage):
    """④ 字面的 `\\n` → 空格。结尾的 `\\` 先憋着。"""

    def cut(self, b: str) -> int:
        return len(b) - 1 if b.endswith("\\") else len(b)

    def apply(self, piece: str) -> str:
        return LITERAL_NL_RE.sub(" ", piece)


class _TagStage(_Stage):
    """⑤ 残留的 `[tag]` → 空格。没写完的 `[tag…` 先憋着。"""

    def cut(self, b: str) -> int:
        i = b.rfind("[")
        return i if (i != -1 and _TAG_PARTIAL_RE.fullmatch(b, i)) else len(b)

    def apply(self, piece: str) -> str:
        return TAG_RE.sub(" ", piece)


class _StreamSanitizer:
    """sanitize_speech 的流式版：喂原文片段，吐"已经确定"的净化文字增量。

    sanitize_speech 是依次整段跑的几步（语言标签 → 控制标记 → markdown 星号 → 字面 \\n →
    残留 [tag] → 引号 → 空白折叠）；前一步删字可能让后一步出现新的匹配（`[*x*]` 去掉星号后
    成了 `[x]`），所以这里把每一步做成一个流式阶段串起来：每个阶段只在自己的安全切点处
    处理、再把结果交给下一阶段；空白折叠跨片段按状态做。拼起来 == sanitize_speech(全文)。
    """

    def __init__(self):
        self._stages = (_LabelControlStage(), _MarkdownStage(), _LiteralNewlineStage(), _TagStage())
        self._ws = False        # 上次吐出的非空白之后有没有空白
        self._any = False       # 是否已经吐过非空白

    def feed(self, text: str) -> str:
        t = text
        for st in self._stages:
            t = st.feed(t)
        return self._collapse(t)

    def flush(self) -> str:
        t = ""
        for st in self._stages:
            t = st.feed(t) + st.flush()
        return self._collapse(t)

    def _collapse(self, t: str) -> str:
        if not t:
            return ""
        t = _QUOTE_MARK_RE.sub("", t)
        words = t.split()
        if not words:
            if t:
                self._ws = True
            return ""
        out = []
        if self._any and (self._ws or t[0].isspace()):
            out.append(" ")
        out.append(" ".join(words))
        self._any = True
        self._ws = t[-1].isspace()
        return "".join(out)


class _BlurtGate:
    """第一段的 blurt 前缀去重（po_contract.dedupe_blurt 的流式版，2026-10-05 起也切「只重复了前半句/前几个词」）。
    憋住开头，直到能确定：和 blurt 分叉了（重复够长就切掉前缀，否则全放）/ 整条 blurt 都重复了（切掉再放）。
    还没分叉就一直憋；段落结束时由 flush 决定（全是重复就整段丢掉）。"""

    def __init__(self, blurt: str):
        self._blurt = blurt
        self._acc = ""
        self._open = not (blurt or "").strip()

    def feed(self, s: str) -> str:
        if self._open or not s:
            return s
        self._acc += s
        state, cut, matched, full, threshold = match_blurt_prefix(self._acc, self._blurt)
        if state == "pending":
            return ""                         # 还在和 blurt 逐字对上，继续憋
        if state == "strip":
            rest = strip_echo_tail(self._acc[cut:])   # the echo's closing quote and punctuation go with it
            if not rest:
                return ""                     # 目前全是重复（和它后面的标点），继续憋
            self._open, self._acc = True, ""
            return rest
        out, self._acc, self._open = self._acc, "", True
        return out

    def flush(self) -> str:
        if self._open:
            return ""
        out = dedupe_blurt(self._acc, self._blurt)
        self._acc, self._open = "", True
        return out


def _tail_decision(tail: str, complete: bool) -> Optional[bool]:
    """没标签引号收尾后、同一行剩下的部分（extract_deep 的判定）：True=台词，False=不是，None=还说不准。"""
    t = _ANY_SFX_LIKE_RE.sub("", tail).lstrip()
    if complete:
        return bool(_PUNCT_ONLY_RE.match(t) or t[:1] in OPEN_QUOTES or t.startswith("["))
    if not t:
        return None
    if t[0] in OPEN_QUOTES:
        return True
    if t[0] in "【[":
        return None
    if not _PUNCT_ONLY_RE.match(t.split("【", 1)[0]):
        return False
    return None


# ---------------- surface ---------------- #
class SurfaceSpeechExtractor:
    """表层格式（契约 §1.2，没有 recall）：

        status: ok
        tone: casual_neutral
        mode: think
        reply: 我想想……

    - reply 就是 `reply:` 后面那**一行**（第一个 reply 行）；换行之后的东西一律不是 speech。
      mode 不影响朗读：think 模式的 filler 一样念（契约 §4.6）。
    - 完全没有 reply 字段时，第一条"自由行"（不是字段、不是空行、不只是一个 [tag]）就是 reply；
      这种情况要等表层写完才能确定，所以在 flush() 时才吐。
    - tone 用第一个 tone 行（resolve_emotion 兜底，缺省 casual_neutral），在 reply 开始吐时定下来，
      本轮不再变。格式里 tone 行在 reply 行前面；reply 一出现就开始流式吐，不等可能迟到的 tone 行
      （迟到的 tone 行改不了已经送出去的音频；存档 987+1,051 条里没有这种情况）。
    - reply 文字过 sanitize_speech（流式），【声效】过 canonical_sfx（占位符丢弃）。
    结果与 po_contract.parse_surface(raw)["reply"] / ["tone"] 一致。
    """

    def __init__(self):
        self.reset()

    def reset(self) -> None:
        self._raw = ""
        self._line_start = 0
        self._fields: Dict[str, str] = {}
        self._free_line: Optional[str] = None
        self._reply_fed: Optional[int] = None     # reply 正文在 raw 里已喂到的位置；None=还没看到 reply 行
        self._reply_done = False
        self._san = _StreamSanitizer()
        self._sfx = SfxScanner()
        self._reply_parts: List[str] = []
        self._reply_tone: Optional[str] = None    # reply 开始吐时定下的 tone（本轮不再变）
        self._finished = False

    @property
    def current_emotion_key(self) -> Optional[str]:
        if self._reply_tone is not None:
            return self._reply_tone
        return resolve_emotion(self._fields.get("tone", ""))

    @property
    def reply_text(self) -> str:
        """已确定的 reply（净化后、【声效】标签保留，= parse_surface 的 reply）。"""
        return "".join(self._reply_parts)

    def feed(self, chunk: str) -> Parts:
        if not chunk or self._finished:
            return []
        self._raw += chunk
        out: Parts = []
        try:
            while True:
                m = _LINE_BREAK_RE.search(self._raw, self._line_start)
                if not m:
                    break
                self._complete_line(self._line_start, m.start(), out)
                self._line_start = m.end()
            self._partial_line(out)
        except Exception:
            return out + self._fail()
        return out

    def flush(self) -> Parts:
        """流结束：最后一行（没换行）也算完整一行；没有 reply 字段时退到第一条自由行。"""
        if self._finished:
            return []
        out: Parts = []
        try:
            if self._line_start < len(self._raw):
                self._complete_line(self._line_start, len(self._raw), out)
                self._line_start = len(self._raw)
            if "reply" not in self._fields and self._free_line:
                self._reply_tone = self.current_emotion_key
                self._speak(sanitize_speech(self._free_line), out)
            self._emit_sfx(self._sfx.flush(), out)
        except Exception:
            return out + self._fail()
        self._finished = True
        return out

    def _fail(self) -> Parts:
        """保险丝：内部出错只记一次日志，本轮表层不再出声。"""
        _log.exception(f"[surface extractor] failed at {len(self._raw)} chars; rest of this turn's reply dropped")
        self._finished = True
        return []

    # -- internals --
    def _complete_line(self, start: int, end: int, out: Parts) -> None:
        line = self._raw[start:end]
        m = _FIELD_LINE_RE.match(line)
        if m:
            key = m.group(1).lower()
            if key in self._fields:
                return
            self._fields[key] = m.group(2).strip()
            if key == "reply":
                if self._reply_fed is None:
                    self._reply_fed = start + _REPLY_HEAD_RE.match(line).end()
                    self._reply_tone = self.current_emotion_key
                self._speak(self._san.feed(self._raw[self._reply_fed:end]) + self._san.flush(), out)
                self._reply_fed = end
                self._reply_done = True
                self._emit_sfx(self._sfx.flush(), out)
        elif self._free_line is None and line.strip() and not TAG_RE.fullmatch(line.strip()):
            self._free_line = line.strip()

    def _partial_line(self, out: Parts) -> None:
        if self._reply_done or "reply" in self._fields:
            return
        if self._reply_fed is None:
            m = _REPLY_HEAD_RE.match(self._raw[self._line_start:])   # `^` 不认 pos 参数，切片再匹配
            if not m:
                return
            self._reply_fed = self._line_start + m.end()
            self._reply_tone = self.current_emotion_key
        text = self._raw[self._reply_fed:]
        self._reply_fed = len(self._raw)
        self._speak(self._san.feed(text), out)

    def _speak(self, text: str, out: Parts) -> None:
        if not text:
            return
        self._reply_parts.append(text)
        self._emit_sfx(self._sfx.feed(text), out)

    def _emit_sfx(self, events, out: Parts) -> None:
        key = self.current_emotion_key
        for kind, val in events:
            if kind == "text":
                out.append((key, val))
            else:  # sfx
                out.append((key, make_sfx_delta(val)))


# ---------------- deep ---------------- #
class _Segment:
    """extract_deep 的一个 found 条目（按原文起点排序后就是 segments 的顺序）。"""

    __slots__ = ("start", "kind", "tone", "closed", "body_start", "body_end", "fed", "text",
                 "done", "started", "san", "gate", "sfx", "emitted_text", "spoken")

    def __init__(self, start: int, kind: str, tone: str):
        self.start = start
        self.kind = kind                  # tagged / bare / untagged
        self.tone = tone
        self.closed = False
        self.body_start = 0
        self.body_end = 0
        self.fed = 0                      # tagged：raw 里已喂给净化器的位置
        self.text = ""                    # bare / untagged：整段净化后的文字
        self.done = False
        self.started = False
        self.san = _StreamSanitizer()
        self.gate: Optional[_BlurtGate] = None
        self.sfx = SfxScanner()
        self.emitted_text = False
        self.spoken: List[str] = []       # 过了 blurt 去重、进声效扫描器之前的文字（= 契约 segment text）


class DeepSpeechExtractor:
    """深层原始流 → speech 增量（契约 §1.1 规则 1-6 的流式镜像）。

    内部把 extract_deep 的三步拆成可以增量推进的三层，每层只处理"已经确定"的那部分原文：
      1) 带标签的引号段（TAGGED_QUOTE_RE，原文上找）——开着的那段按安全前缀边来边吐；
      2) `[tag]` + 同行无引号文字（TAGGED_BARE_RE，在遮掉第 1 层后的文本上，一行写完才判）；
      3) 边界之前的无标签引号（右引号到达 + 同行尾巴判定完才判，判定前一个字不吐）。
    输出按原文起点顺序：某位置之前还可能冒出新段时，后面的段先憋着。
    """

    def __init__(self):
        self.reset()

    def reset(self) -> None:
        self._raw = ""
        self._m: List[str] = []            # 遮罩后的文本（与 extract_deep 的 mask 同步）
        self._p1 = 0                       # 第 1 层搜索起点
        self._open: Optional[_Segment] = None
        self._open_masked = 0
        self._p2 = 0                       # 第 2 层：下一行的行首
        self._p3 = 0                       # 第 3 层扫描位置
        self._p3_ls = 0                    # 第 3 层当前行首
        self._boundary: Optional[int] = None
        self._bscan = 0
        self._segments: List[_Segment] = []
        self._blurt: Optional[str] = None
        self._first_claimed = False
        self._last_emotion_key: Optional[str] = None
        self._finished = False

    @property
    def current_emotion_key(self) -> Optional[str]:
        return self._last_emotion_key

    @property
    def segments(self) -> List[dict]:
        """到目前为止已吐出的段（净化 + blurt 去重后，【声效】标签保留）。流结束后
        == po_contract.extract_deep(raw, blurt)["segments"]。"""
        out = []
        for s in sorted(self._segments, key=lambda x: x.start):
            text = "".join(s.spoken)
            if text:
                out.append({"text": text, "tone": s.tone})
        return out

    def set_blurt(self, blurt: Optional[str]) -> bool:
        """表层已经说出口的那句（surface_done.reply）。第一段开始吐之前设才有效；返回是否生效。"""
        if self._first_claimed:
            return False
        self._blurt = (blurt or "").strip() or None
        return True

    def feed(self, chunk: str) -> Parts:
        if not chunk or self._finished:
            return []
        self._raw += chunk
        self._m.extend(chunk)
        try:
            self._advance(final=False)
            return self._emit(final=False)
        except Exception:
            return self._fail()

    def flush(self) -> Parts:
        """流结束。没闭合的引号段按现状封口，段末补 \\n；还没判定的候选按全文判定。"""
        if self._finished:
            return []
        try:
            self._advance(final=True)
            out = self._emit(final=True)
        except Exception:
            return self._fail()
        self._finished = True
        return out

    def _fail(self) -> Parts:
        """保险丝：抽取器内部出错时只记一次日志，本轮剩下的深层不再出声（不会每个 chunk 刷一遍 traceback）。"""
        _log.exception(f"[deep extractor] failed at {len(self._raw)} chars; rest of this turn's deep speech dropped")
        self._finished = True
        return []

    # ------------------------------------------------------------ analysis
    def _mask(self, a: int, b: int) -> None:
        m = self._m
        for i in range(a, b):
            if m[i] != "\n":
                m[i] = " "

    def _advance(self, final: bool) -> None:
        raw = self._raw
        n = len(raw)

        # --- thought boundary (first 我心想/我反思/我思考, or a 【想想】 before it)
        if final:
            think_m = THINK_RE.search(raw)
            b = think_m.start() if think_m else n
            help_m = HELP_RE.search(raw)
            if help_m and help_m.start() < b and raw[help_m.end():].strip():
                b = help_m.start()
            boundary: Optional[int] = b
        else:
            if self._boundary is None:
                cands = [x.start() for x in (THINK_RE.search(raw, self._bscan), HELP_RE.search(raw, self._bscan)) if x]
                if cands:
                    self._boundary = min(cands)
                else:
                    scan = max(0, n - 3)
                    k = raw.rfind("【", 0, n)
                    if k != -1 and "】" not in raw[k:]:
                        scan = min(scan, k)
                    self._bscan = scan
            boundary = self._boundary

        # --- layer 1: tagged quotes on the raw text
        while True:
            m = TAGGED_QUOTE_RE.search(raw, self._p1)
            if not m:
                k = raw.rfind("[", self._p1)
                self._p1 = k if (k != -1 and not final and _PENDING_OPEN_RE.fullmatch(raw, k)) else n
                break
            g = "b1" if m.group("b1") is not None else ("b2" if m.group("b2") is not None else "b3")
            bs, be = m.span(g)
            seg = self._open if (self._open is not None and self._open.start == m.start()) else None
            if seg is None:
                seg = _Segment(m.start(), "tagged", resolve_emotion(m.group(1)))
                seg.body_start = seg.fed = bs
                self._segments.append(seg)
                self._open_masked = m.start()
            if be == n and not final:
                self._open = seg
                self._p1 = m.start()
                break
            seg.closed = True
            seg.body_end = be
            self._mask(max(self._open_masked, m.start()) if seg is self._open else m.start(), m.end())
            self._open = None
            self._p1 = m.end()

        if self._open is not None:
            seg = self._open
            k = raw.rfind("[", seg.body_start)
            j = k if (k != -1 and _AHEAD_PARTIAL_RE.fullmatch(raw, k)) else n
            while j > seg.body_start and raw[j - 1].isspace():
                j -= 1
            seg.body_end = j                               # safe end of the open body
            self._mask(max(self._open_masked, seg.start), j)
            self._open_masked = max(self._open_masked, j)
            f1 = j
        else:
            f1 = self._p1 if self._p1 < n else n

        # --- layer 2: `[tag]` + same-line unquoted text, complete lines only
        mm = self._m
        ls = n if final else raw.rfind("\n", 0, f1) + 1
        if not final and ls > self._p2:
            # TAG_RE 的 \s* 能跨行（`[ tag\n]`）：还没收口的 `[tag…` 所在行不算写完
            k = raw.rfind("[", self._p2, ls)
            while k != -1 and mm[k] != "[":
                k = raw.rfind("[", self._p2, k)
            if k != -1 and _TAG_PARTIAL_RE.fullmatch("".join(mm[k:ls])):
                ls = raw.rfind("\n", 0, k) + 1
        if ls > self._p2:
            off = self._p2
            win = "".join(mm[off:ls])
            for bm in TAGGED_BARE_RE.finditer(win):
                body = bm.group(2)
                if THINK_RE.search(body) or not body.strip():
                    continue
                seg = _Segment(off + bm.start(), "bare", resolve_emotion(bm.group(1)))
                seg.text = sanitize_speech(body)
                seg.closed = True
                self._segments.append(seg)
                self._mask(off + bm.start(), off + bm.end())
            self._p2 = ls
        if final:
            f2 = n
        else:
            f2 = f1
            k = raw.find("[", ls, f1)
            while k != -1:
                if mm[k] == "[":
                    f2 = k
                    break
                k = raw.find("[", k + 1, f1)

        # --- layer 3: untagged quotes before the boundary
        limit = f2 if boundary is None else min(f2, boundary)
        if self._p3 < limit:
            base = self._p3_ls
            win = "".join(mm[base:f2])
            i = self._p3 - base
            ls_rel = 0
            lim = limit - base
            while i < lim:
                ch = win[i]
                if ch == "\n":
                    ls_rel = i + 1
                    i += 1
                    continue
                if ch in OPEN_QUOTES and _line_prefix_is_clear(win, ls_rel, i):
                    closers = _QUOTE_CLOSE_FOR[ch]
                    close = next((j for j in range(i + 1, len(win)) if win[j] in closers), None)
                    if close is None:
                        if final:
                            i += 1
                            continue
                        break                                   # pending: close not here yet
                    if boundary is not None and base + close > boundary:
                        i += 1
                        continue
                    nl = win.find("\n", close + 1)
                    if nl == -1:
                        decision = _tail_decision(win[close + 1:], final)
                    else:
                        decision = _tail_decision(win[close + 1:nl], True)
                    if decision is None:
                        break                                   # pending: tail of the line unknown
                    if decision:
                        start = base + i
                        prev = max((s for s in self._segments if s.start < start),
                                   key=lambda s: s.start, default=None)
                        seg = _Segment(start, "untagged", prev.tone if prev else DEFAULT_EMOTION)
                        seg.text = sanitize_speech(win[i + 1:close])
                        seg.closed = True
                        self._segments.append(seg)
                        self._mask(start, base + close + 1)
                        win = win[:i] + "".join(mm[start:base + close + 1]) + win[close + 1:]
                        i = close + 1
                        continue
                i += 1
            self._p3 = base + i
            self._p3_ls = base + ls_rel
        phase3_active = self._p3 < limit
        self._frontier = n if final else (self._p3 if phase3_active else f2)

    # ------------------------------------------------------------ emission
    def _emit(self, final: bool) -> Parts:
        out: Parts = []
        for seg in sorted((s for s in self._segments if not s.done), key=lambda s: s.start):
            if not final and seg.start >= self._frontier:
                break
            if not seg.started:
                seg.started = True
                if not self._first_claimed:
                    self._first_claimed = True
                    if self._blurt:
                        seg.gate = _BlurtGate(self._blurt)
                self._last_emotion_key = seg.tone
            if seg.kind == "tagged":
                end = seg.body_end
                if end > seg.fed:
                    self._say(seg, seg.san.feed(self._raw[seg.fed:end]), out)
                    seg.fed = end
                if not seg.closed:
                    break                                       # still streaming
                self._say(seg, seg.san.flush(), out)
            else:
                self._say(seg, seg.text, out)
            self._close_segment(seg, out)
        return out

    def _say(self, seg: _Segment, text: str, out: Parts) -> None:
        if seg.gate is not None:
            text = seg.gate.feed(text)
        if text:
            seg.spoken.append(text)
            self._emit_sfx(seg, seg.sfx.feed(text), out)

    def _close_segment(self, seg: _Segment, out: Parts) -> None:
        if seg.gate is not None:
            rest = seg.gate.flush()
            if rest:
                seg.spoken.append(rest)
                self._emit_sfx(seg, seg.sfx.feed(rest), out)
        self._emit_sfx(seg, seg.sfx.flush(), out)
        if seg.emitted_text:
            out.append((seg.tone, "\n"))          # 段封闭哨兵：分句器据此把本段残留归给本段 tone
        seg.done = True

    @staticmethod
    def _emit_sfx(seg: _Segment, events, out: Parts) -> None:
        for kind, val in events:
            if kind == "text":
                out.append((seg.tone, val))
                seg.emitted_text = True
            else:  # sfx：标签从台词里切走，作为独立声效哨兵
                out.append((seg.tone, make_sfx_delta(val)))


# ---------------- demo ---------------- #
if __name__ == "__main__":
    import sys
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    def demo_surface(label: str, chunks: List[str]):
        print(f"\n=== surface: {label} ===")
        sf = SurfaceSpeechExtractor()
        for i, c in enumerate(chunks):
            parts = sf.feed(c)
            print(f"  feed[{i}]({c!r}) -> {parts}")
        print(f"  flush()          -> {sf.flush()}")
        print(f"  current_emotion_key = {sf.current_emotion_key!r}  reply_text = {sf.reply_text!r}")

    def demo_deep(label: str, chunks: List[str], blurt: Optional[str] = None):
        print(f"\n=== deep: {label} ===")
        de = DeepSpeechExtractor()
        if blurt:
            de.set_blurt(blurt)
        for i, c in enumerate(chunks):
            print(f"  feed[{i}]({c!r}) -> {de.feed(c)}")
        print(f"  flush()          -> {de.flush()}")
        print(f"  segments = {de.segments}")

    demo_surface("标准 casual_happy", ["status: ok\ntone: casual_happy\n", "mode: say\n", "reply: 你好呀，",
                                     "今天天气真好。", "\n"])
    demo_surface("think 模式 filler 照念", ["status: ok\ntone: casual_neutral\nmode: think\nreply: 我想想……"])
    demo_surface("not-for-me reply 空", ["status: not-for-me\ntone: casual_neutral\nmode: say\nreply:", "\n"])
    demo_surface("没字段：第一条自由行", ["Yeah, I can ", "hear you."])
    demo_surface("reply 里的声效和占位符", ["tone: casual_happy\nmode: say\n", "reply: 哈哈，太好笑了。【La",
                                         "ugh】不行【声效名】我缓缓。"])
    demo_deep("多段 tone + 声效", ['[casual_happy]"哈哈，太好笑了。【Laugh】不行', '我缓缓。"[casual_shy]"才、才没有。"\n',
                                   "我心想：他又在逗我。【想想】"])
    demo_deep("无标签引号：收尾前不吐", ['我说："Sure, I can', ' hear you."\n', '我心想："Unlike some loner." 嗯。'])
    demo_deep("blurt 去重", ['[casual_neutral]"Booking every', ' minute, huh… That sounds exhausting."\n我心想：嗯。'],
              blurt="Booking every minute, huh…")
