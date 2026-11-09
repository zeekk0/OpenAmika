"""每句台词播完后的"句后停顿"时长表（按 实际情绪 × 语言）。

需求：每段台词说完后空一小段静音再接下一段，停顿长短由**前一句的情绪**决定，
且和**语言**相关。所以每个真实情绪 key（如 casual_happy）对应三个值：
(中文, 日语, 英文)，单位秒。默认全是 0.2，**逐个手动改即可**。

用法（api 侧）：pause_after(emotion_key, lang) -> 秒数；随 tts 段下发给前端，
前端把这段静音加进无缝播放时间轴。语言取 _detect_lang 的结果
（CHINESE / JAPANESE / ENGLISH / KOREAN / MIXED），MIXED 归到中文档。
KOREAN 显式使用 DEFAULT_PAUSE，不借用中文调参。

声效段不在此表内（声效不是"一句话"），其句后停顿固定为 0。

换角色时如果语速/风格变了，直接在 PAUSE_TABLE 里改值即可，逻辑不用动。
"""

from typing import Tuple

# 语言档位顺序：(中文, 日语, 英文)
_LANG_INDEX = {"CHINESE": 0, "JAPANESE": 1, "ENGLISH": 2}

DEFAULT_PAUSE = 0.2

# 实际情绪 → (中文停顿, 日语停顿, 英文停顿)，单位秒。手动改具体值。
# 按语气域分组（polite / casual / serious / intimate / whisper），合计 69 个。
PAUSE_TABLE = {
    # —— polite（11）——
    "polite_neutral":     (0.2, 0.2, 0.2),
    "polite_smile":       (0.2, 0.2, 0.2),
    "polite_happy":       (0.2, 0.2, 0.2),
    "polite_caring":      (0.2, 0.2, 0.2),
    "polite_sad":         (0.2, 0.2, 0.2),
    "polite_worried":     (0.2, 0.2, 0.2),
    "polite_cold":        (0.2, 0.2, 0.2),
    "polite_angry":       (0.2, 0.2, 0.2),
    "polite_embarrassed": (0.2, 0.2, 0.2),
    "polite_surprise":    (0.2, 0.2, 0.2),
    "polite_fear":        (0.2, 0.2, 0.2),

    # —— casual（19）——
    "casual_neutral":     (0.2, 0.2, 0.2),
    "casual_smile":       (0.2, 0.2, 0.2),
    "casual_happy":       (0.2, 0.2, 0.2),
    "casual_very_happy":  (0.2, 0.2, 0.2),
    "casual_playful":     (0.2, 0.2, 0.2),
    "casual_laughing":    (0.2, 0.2, 0.2),
    "casual_relieved":    (0.2, 0.2, 0.2),
    "casual_shy":         (0.2, 0.2, 0.2),
    "casual_embarrassed": (0.2, 0.2, 0.2),
    "casual_mumbling":    (0.2, 0.2, 0.2),
    "casual_jealous":     (0.2, 0.2, 0.2),
    "casual_caring":      (0.2, 0.2, 0.2),
    "casual_surprise":    (0.2, 0.2, 0.2),
    "casual_angry":       (0.2, 0.2, 0.2),
    "casual_frustrated":  (0.2, 0.2, 0.2),
    "casual_sad":         (0.2, 0.2, 0.2),
    "casual_tired":       (0.2, 0.2, 0.2),
    "casual_fear":        (0.2, 0.2, 0.2),
    "casual_worried":     (0.2, 0.2, 0.2),

    # —— serious（11）——
    "serious_neutral":      (0.2, 0.2, 0.2),
    "serious_cold":         (0.2, 0.2, 0.2),
    "serious_disappointed": (0.2, 0.2, 0.2),
    "serious_surprise":     (0.2, 0.2, 0.2),
    "serious_angry":        (0.2, 0.2, 0.2),
    "serious_very_angry":   (0.2, 0.2, 0.2),
    "serious_protective":   (0.2, 0.2, 0.2),
    "serious_worried":      (0.2, 0.2, 0.2),
    "serious_anxious":      (0.2, 0.2, 0.2),
    "serious_sad":          (0.2, 0.2, 0.2),
    "serious_fear":         (0.2, 0.2, 0.2),

    # —— intimate（18）——
    "intimate_neutral":     (0.2, 0.2, 0.2),
    "intimate_happy":       (0.2, 0.2, 0.2),
    "intimate_very_happy":  (0.2, 0.2, 0.2),
    "intimate_smile":       (0.2, 0.2, 0.2),
    "intimate_playful":     (0.2, 0.2, 0.2),
    "intimate_shy":         (0.2, 0.2, 0.2),
    "intimate_very_shy":    (0.2, 0.2, 0.2),
    "intimate_caring":      (0.2, 0.2, 0.2),
    "intimate_very_caring": (0.2, 0.2, 0.2),
    "intimate_jealous":     (0.2, 0.2, 0.2),
    "intimate_mumbling":    (0.2, 0.2, 0.2),
    "intimate_relieved":    (0.2, 0.2, 0.2),
    "intimate_tearful":     (0.2, 0.2, 0.2),
    "intimate_sad":         (0.2, 0.2, 0.2),
    "intimate_very_sad":    (0.2, 0.2, 0.2),
    "intimate_sleepy":      (0.2, 0.2, 0.2),
    "intimate_tired":       (0.2, 0.2, 0.2),
    "intimate_worried":     (0.2, 0.2, 0.2),

    # —— whisper（10）——
    "whisper_neutral":  (0.2, 0.2, 0.2),
    "whisper_happy":    (0.2, 0.2, 0.2),
    "whisper_smile":    (0.2, 0.2, 0.2),
    "whisper_caring":   (0.2, 0.2, 0.2),
    "whisper_relieved": (0.2, 0.2, 0.2),
    "whisper_shy":      (0.2, 0.2, 0.2),
    "whisper_sad":      (0.2, 0.2, 0.2),
    "whisper_worried":  (0.2, 0.2, 0.2),
    "whisper_tearful":  (0.2, 0.2, 0.2),
    "whisper_sleepy":   (0.2, 0.2, 0.2),
}


def pause_after(emotion_key: str, lang: str) -> float:
    """前一句的实际情绪 + 语言 → 句后停顿秒数。
    认不出的情绪/语言一律退默认；MIXED 归中文档。"""
    if (lang or "").upper() == "KOREAN":
        return DEFAULT_PAUSE
    row: Tuple[float, float, float] = PAUSE_TABLE.get(emotion_key or "")
    if not row:
        return DEFAULT_PAUSE
    idx = _LANG_INDEX.get((lang or "").upper(), 0)   # 默认中文档（含 MIXED）
    return row[idx]


if __name__ == "__main__":
    import sys
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    from tts_emotion import VALID_EMOTIONS

    keys = set(PAUSE_TABLE)
    missing = VALID_EMOTIONS - keys
    extra = keys - VALID_EMOTIONS
    assert not missing, f"缺少情绪：{sorted(missing)}"
    assert not extra, f"多余情绪：{sorted(extra)}"
    for k, v in PAUSE_TABLE.items():
        assert isinstance(v, tuple) and len(v) == 3 and all(
            isinstance(x, (int, float)) for x in v), f"{k} 值非法：{v!r}"
    print(f"PAUSE_TABLE 覆盖全部 {len(VALID_EMOTIONS)} 个实际情绪，每个 3 档（中/日/英）。")
    print("抽查：")
    for k, lang in [("casual_happy", "CHINESE"), ("casual_happy", "JAPANESE"),
                    ("casual_happy", "ENGLISH"), ("casual_happy", "MIXED"),
                    ("不存在", "CHINESE")]:
        print(f"  pause_after({k!r}, {lang}) = {pause_after(k, lang)}")
