"""Korean contract regressions through the production batch and streaming APIs."""
import importlib.util
from pathlib import Path
import unicodedata

import pytest
import po_contract as pc
from hane_parser import DeepSpeechExtractor, SurfaceSpeechExtractor


@pytest.mark.parametrize("text,want", [
    ("안녕하세요", "ko"), ("내 이름은 민수야", "ko"), ("네", "ko"),
    (unicodedata.normalize("NFD", "안녕하세요"), "ko"), ("ㅋㅋㅋ", "ko"),
    ("한국어 hello", "en"), ("한국어 abcd", "mixed"),
    ("안녕하세요 hello", "mixed"), ("韓國 문학이 좋아요", "ko"),
    ("안녕하세요 こんにちは", "mixed"), ("네 hello world", "en"),
    ("안녕 漢字", "mixed"), ("안녕하세요 123 😊", "ko"),
    ("... 123 😊", None), ("annyeonghaseyo", "en"),
])
def test_korean_detection(text, want):
    assert pc.detect_lang(text) == want


def test_hangul_analysis_preserves_legacy_tuple():
    assert pc.lang_counts("韓國 한국어 abc あ") == (2, 1, 3)
    assert pc.hangul_count("한국어") == 3
    assert pc.hangul_count(unicodedata.normalize("NFD", "한국어")) == 3
    assert pc.hangul_count("ㄱㅋㅏ가") == 4
    assert pc.hangul_count("\ua960\ud7b0") == 2
    assert pc.hangul_count("English 東京") == 0
    assert not pc.is_kanji_only("한국어 漢字")
    assert pc.reply_lang("네", "en") == ("ko", "detected")
    assert pc.reply_lang("...", "ko") == ("ko", "inherited")
    assert pc.LANG_TO_TTS["ko"] == "Korean"
    for reason in ("detected", "inherited", "switch"):
        line = pc.language_line("ko", reason)
        assert "韩语" in line
        assert "我心想照常用中文" in line


@pytest.mark.parametrize("text,want", [
    ("How do I say hello in Korean?", "ko"),
    ("Can you please reply in Korean?", "ko"),
    ("한국어로 말해주세요", "ko"), ("영어로 번역해 주세요", "en"),
    ("Please reply in Korean", "ko"), ("Speak Korean", "ko"),
    ("用韩语回答", "ko"), ("請用韓語回答", "ko"),
    ("韓国語で答えて", "ko"), ("한국어로 말해 줘", "ko"),
    ("영어로 답해 줘", "en"), ("일본어로 말해 주세요", "ja"),
    ("중국어로 대답해 줘", "zh"), ("한국어로 답변해 주세요", "ko"),
    ("이번 답변만 영어로 짧게 인사해 줘.", "en"),
    ("이제 다시 한국어로 짧게 인사해 줘.", "ko"),
    ("일본어로 간단히 답해 주세요", "ja"),
    ("중국어로 간단하게 대답해 줘", "zh"),
])
def test_explicit_korean_switch(text, want):
    assert pc.explicit_switch(text) == want
    assert pc.reply_lang(text, "en") == (want, "switch")


@pytest.mark.parametrize("text", [
    "I enjoy Korean food", "I read a book in Korean", "She can speak Korean",
    "한국어를 공부하고 있어요", "영어로 된 책을 읽었어요", "한국어로 말하는 친구가 있어요",
    "我喜欢韩语", "我会说韩语", "我用韩语写日记", "韓国語が好きです", "Don't reply in Korean",
    "한국어로 말하지 마", "한국어로 말해 주지 마",
    "영어로 짧게 인사하지 마", "영어로 짧게 인사해 주지 마",
    "'영어로 짧게 인사해 줘'라는 요청을 받았어",
    "영어로 짧게 인사하는 친구가 있어요",
])
def test_language_mentions_are_not_switches(text):
    assert pc.explicit_switch(text) is None


LABELS = ("Korean", "korean", "KOREAN", "한국어", "韩语", "韓語", "韓国語")


@pytest.mark.parametrize("label", LABELS)
@pytest.mark.parametrize("body,want", [
    ("*韓國 문학*이 좋아요.", "韓國 문학이 좋아요."),
    ("*叹了口气* 네, 좋아요.", "네, 좋아요."),
    ("**한국어**로 말해요.", "한국어로 말해요."),
])
def test_batch_and_streaming_every_chunk_split(label, body, want):
    text = f"（ {label} ）{body}"
    assert pc.sanitize_speech(text) == want
    surface = f"status: ok\ntone: casual_happy\nmode: say\nreply: {text}\n"
    deep = f'[casual_happy]"{text}"\n我心想：我很开心。'
    assert pc.parse_surface(surface)["reply"] == want
    assert pc.extract_deep(deep)["speech"] == want
    assert pc.extract_deep(deep)["thought"] == "我很开心。"
    for raw, extractor in ((surface, SurfaceSpeechExtractor), (deep, DeepSpeechExtractor)):
        for chunks in ([raw[:i], raw[i:]] for i in range(len(raw) + 1)):
            parser = extractor()
            parts = []
            for chunk in chunks:
                parts.extend(parser.feed(chunk))
            parts.extend(parser.flush())
            assert "".join(t for _, t in parts).strip() == want, chunks
        parser = extractor()
        parts = [part for char in raw for part in parser.feed(char)]
        parts.extend(parser.flush())
        assert "".join(t for _, t in parts).strip() == want


def test_both_shipped_contract_interfaces():
    root = Path(__file__).resolve().parents[1]
    assert (root / "brain/po_contract.py").read_bytes() == (root / "speech/po_contract.py").read_bytes()
    for folder in ("brain", "speech"):
        spec = importlib.util.spec_from_file_location(f"{folder}_contract", root / folder / "po_contract.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        assert module.detect_lang("네") == "ko"
        assert module.reply_lang("用韩语回答", "zh") == ("ko", "switch")
        assert module.sanitize_speech("*韓國 문학*이 좋아요.") == "韓國 문학이 좋아요."


@pytest.mark.parametrize("source,text", [("en", "Hello there"), ("zh", "你好啊"), ("ja", "こんにちは")])
def test_switch_is_one_turn(source, text):
    assert pc.reply_lang("Please reply in Korean", source) == ("ko", "switch")
    assert pc.reply_lang(text, "ko") == (source, "detected")
    assert pc.reply_lang("안녕하세요", source) == ("ko", "detected")
