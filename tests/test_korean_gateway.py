"""Korean gateway regressions using the production methods and existing offline seam.

These tests do not establish voice-model or microphone acceptance.
"""
import ast
import asyncio
import json
import copy
import unicodedata
from pathlib import Path

import pytest

from test_api_carry import DialogSession, NS, new_session
import stt_carry
import tts_pause
import voice_adapter
from sentence_splitter import StreamingSplitter
from test_wipe_proxy import Request, HTTPException

SOURCE = Path(__file__).resolve().parents[1] / "speech" / "api.py"


def constant(name):
    tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(getattr(t, "id", "") == name for t in node.targets):
            return ast.literal_eval(node.value)
    raise AssertionError(name)


@pytest.mark.parametrize("text", ["한국어로 이야기해요.", "네", "ㅋㅋ", unicodedata.normalize("NFD", "안녕하세요")])
def test_gateway_detects_korean_without_rewriting_text(text):
    assert DialogSession._detect_lang(text) == "KOREAN"


@pytest.mark.parametrize("text, expected", [("Hello there", "ENGLISH"), ("你好世界", "CHINESE"), ("こんにちは", "JAPANESE"), ("", "CHINESE")])
def test_gateway_previous_languages_remain_unchanged(text, expected):
    assert DialogSession._detect_lang(text) == expected


def test_brain_metadata_resolves_korean_mixed_and_hanja_tts():
    session = new_session()
    session._note_reply_lang({"reply_lang": "ko", "reply_lang_reason": "switch"})
    assert session._turn_reply_lang == "ko"
    assert session._tts_language("안녕하세요.") == "Korean"
    assert session._tts_language("韓國") == "Korean"
    assert session._tts_language("한국어로 hello") == "Korean"
    session._note_reply_lang({"reply_lang": "unsupported"})
    assert session._turn_reply_lang is None


@pytest.mark.parametrize("adapter_enabled", [False, True])
def test_korean_queue_reaches_socketio_with_original_display_text(monkeypatch, adapter_enabled):
    async def scenario():
        session = new_session()
        session.tts._connected = True
        session.voice_output = True
        session._committed_turn_id = "ko-turn"
        session._note_reply_lang({"reply_lang": "ko"})
        sentence = "한국 문학이 좋아요."
        session._tts_sentence_queue.append(("casual_happy", sentence, "surface"))
        monkeypatch.setitem(NS, "prefix_emotion", lambda key, text: f"【{key}】{text}")
        monkeypatch.setitem(NS, "voice_adapter", voice_adapter)
        monkeypatch.setattr(voice_adapter, "live_state", lambda: (adapter_enabled, voice_adapter.DEFAULT_VOICE, voice_adapter.DEFAULT_MAP))
        await session._pump_tts_queue()
        request = next(payload for event, payload in session.tts.sio.emitted if event == "tts_request_gateway")
        assert request["language"] == "Korean"
        tag = voice_adapter.DEFAULT_MAP["casual_happy"] if adapter_enabled else "casual_happy"
        assert request["text"] == f"【{tag}】.{sentence}"
        assert request["character_id"] == (voice_adapter.DEFAULT_VOICE if adapter_enabled else NS["TTS_CHARACTER_ID"])
        assert session._tts_inflight["sentence"] == sentence
    asyncio.run(scenario())


def test_offline_voice_does_not_mutate_korean_text():
    async def scenario():
        session = new_session()
        session._committed_turn_id = "ko-turn"
        session._tts_sentence_queue.append(("casual_happy", "안녕!", "surface"))
        await session._pump_tts_queue()
        assert not session._tts_sentence_queue
        assert session._tts_inflight is None
        assert not session.tts.sio.emitted
    asyncio.run(scenario())


@pytest.mark.parametrize("text", ["네", "응", "네 OK", "ㅋㅋ", unicodedata.normalize("NFD", "네")])
def test_korean_replies_are_not_discarded_as_noise(text):
    assert not NS["_is_trivial_utterance"](text)


def test_interruption_placeholder_is_korean():
    session = new_session()
    session._my_partial_pending = "방금 하던 말"
    session._my_partial_lang = "KOREAN"
    assert "잡음" in session._maybe_substitute_noise("...")
    assert session._maybe_substitute_noise("네 OK") == "네 OK"


def test_korean_oneshot_and_camera_language_tables():
    assert constant("_TTS_LANGUAGE_NAMES")["KOREAN"] == "Korean"
    assert "{context}" in constant("_VLM_PROMPT_TEMPLATES")["KOREAN"]
    assert "{desc}" in constant("_VISION_SUFFIX_TEMPLATES")["KOREAN"]


def test_korean_pause_has_explicit_default_not_chinese_tuning(monkeypatch):
    monkeypatch.setitem(tts_pause.PAUSE_TABLE, "casual_happy", (0.7, 0.3, 0.1))
    assert tts_pause.pause_after("casual_happy", "KOREAN") == tts_pause.DEFAULT_PAUSE
    assert tts_pause.pause_after("casual_happy", "CHINESE") == 0.7


def test_korean_carry_and_spoken_anchor_keep_original_characters():
    carry = stt_carry.note_force_commit("", "오늘은 한국 문학", protected=False)
    assert stt_carry.with_carry(carry, "이야기를 해요") == "오늘은 한국 문학 이야기를 해요"
    assert DialogSession._effective_chars("【casual_happy】한국 문학!") == list("한국문학")


def oneshot_endpoint(synthesize):
    tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
    node = copy.deepcopy(next(n for n in tree.body if isinstance(n, ast.AsyncFunctionDef) and n.name == "tts_say"))
    node.decorator_list = []
    namespace = dict(NS, json=json, Request=Request, HTTPException=HTTPException,
                     voice_adapter=voice_adapter, _tts_say_once=synthesize,
                     _TTS_SAY_EMOTION_DEFAULT="casual_happy", _TTS_LANGUAGE_NAMES=constant("_TTS_LANGUAGE_NAMES"))
    namespace["prefix_emotion"] = lambda key, text: f"【{key}】{text}"
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(SOURCE), "exec"), namespace)
    return namespace["tts_say"]


def test_korean_name_preview_routes_endpoint_and_keeps_spoken_name():
    calls = []

    async def synthesize(text, language):
        calls.append((text, language))
        return {"audio": b"test-audio", "audio_format": "wav"}

    endpoint = oneshot_endpoint(synthesize)
    request = Request(body=json.dumps({"text": "민수", "raw": True}).encode())
    response = asyncio.run(endpoint(request))
    assert calls == [("【casual_happy】.민수", "Korean")]
    assert response["spoken"] == "민수"
    assert response["language"] == "Korean"


@pytest.mark.parametrize("failure,status", [(RuntimeError("Korean pronunciation unavailable"), 503), (asyncio.TimeoutError(), 504), ({}, 502)])
def test_korean_voice_errors_remain_explicit(failure, status):
    async def synthesize(text, language):
        assert language == "Korean"
        if isinstance(failure, Exception):
            raise failure
        return failure

    with pytest.raises(HTTPException) as error:
        asyncio.run(oneshot_endpoint(synthesize)(Request(body=json.dumps({"text": "안녕"}).encode())))
    assert error.value.status_code == status


def test_korean_preview_does_not_bypass_origin_protection():
    async def forbidden(*args):
        raise AssertionError("cross-origin request must not synthesize")

    with pytest.raises(HTTPException) as error:
        asyncio.run(oneshot_endpoint(forbidden)(Request(origin="https://untrusted.test", body=b'{}')))
    assert error.value.status_code == 403


def test_korean_camera_prompt_and_suffix_respect_freshness_and_off_state():
    tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
    names = {"_vision_fresh_desc", "vision_suffix_for", "_build_vlm_prompt", "vision_note_user_lang"}
    nodes = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in names]
    broadcasts = []
    namespace = dict(NS, VLM_URL="local-vision", _vision_lang="CHINESE", _vision_desc="창가에 앉아 있어요.",
                     _vision_desc_ts=NS["time"].time(), VISION_EXPIRE_SEC=10, _vision_her_line="안녕하세요.",
                     _VLM_PROMPT_TEMPLATES=constant("_VLM_PROMPT_TEMPLATES"),
                     _VISION_SUFFIX_TEMPLATES=constant("_VISION_SUFFIX_TEMPLATES"),
                     _vision_broadcast_prompt=lambda: broadcasts.append(True))
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(SOURCE), "exec"), namespace)
    namespace["vision_note_user_lang"](DialogSession._detect_lang("안녕하세요"))
    assert namespace["_vision_lang"] == "KOREAN"
    assert len(broadcasts) == 1
    assert '"안녕하세요."' in namespace["_build_vlm_prompt"]()
    assert namespace["vision_suffix_for"]("뭐가 보여?") == "（영상 통화에서 보이는 모습: 창가에 앉아 있어요.）"
    namespace["_vision_desc_ts"] = 0
    assert namespace["vision_suffix_for"]("뭐가 보여?") == ""
    namespace["_vision_desc_ts"] = NS["time"].time()
    namespace["VLM_URL"] = ""
    assert namespace["vision_suffix_for"]("뭐가 보여?") == ""


def test_korean_sentence_streaming_preserves_complete_text():
    text = "안녕하세요. 오늘은 날씨가 정말 좋아요!"
    for split in range(len(text) + 1):
        splitter = StreamingSplitter()
        sentences = splitter.feed(text[:split]) + splitter.feed(text[split:]) + splitter.flush()
        assert "".join(sentences).replace(" ", "") == text.replace(" ", "")
        assert sentences[0] == "안녕하세요."


@pytest.mark.parametrize("mode", ["cancel_connect", "timeout", "stale_then_current"])
def test_korean_oneshot_task_boundaries(mode):
    from types import SimpleNamespace
    import uuid
    callbacks = {}
    disconnected = []
    class Socket:
        def on(self, event):
            def register(fn):
                callbacks[event] = fn
                return fn
            return register
        async def connect(self, *a, **kw):
            if mode == "cancel_connect":
                raise asyncio.CancelledError()
        async def emit(self, event, data):
            assert data['language'] == 'Korean'
            await callbacks['audio_ready']({'task_id':'old-request', 'audio':b'stale'})
            if mode == 'stale_then_current':
                await callbacks['audio_ready']({'task_id':data['task_id'], 'audio':b'current'})
        async def disconnect(self):
            disconnected.append(True)
    tree = ast.parse(SOURCE.read_text())
    node = next(n for n in tree.body if isinstance(n, ast.AsyncFunctionDef) and n.name == '_tts_say_once')
    ns = dict(NS, uuid=uuid, socketio=SimpleNamespace(AsyncClient=lambda **kw: Socket()),
              voice_adapter=SimpleNamespace(live_state=lambda: (False, '', {})), _TTS_SAY_TIMEOUT_S=0.01)
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(SOURCE), 'exec'), ns)
    async def scenario():
        if mode == 'stale_then_current':
            result = await ns['_tts_say_once']('안녕하세요', 'Korean')
            assert result['audio'] == b'current'
        else:
            with pytest.raises(asyncio.CancelledError if mode == 'cancel_connect' else asyncio.TimeoutError):
                await ns['_tts_say_once']('안녕하세요', 'Korean')
        assert disconnected == [True]
    asyncio.run(scenario())


@pytest.mark.parametrize('event', ['audio_ready', 'error'])
def test_korean_stale_turn_does_not_reappear(event):
    async def scenario():
        session = new_session()
        sent = []
        async def send(data): sent.append(data)
        session._send = send
        session._committed_turn_id = 'new-ko-turn'
        session._tts_inflight = {'task_id':'old-task', 'idx':0, 'sentence':'안녕하세요', 'kind':'surface'}
        await session._on_tts_event(event, {'task_id':'old-task', 'turn_id':'old-ko-turn-0',
                                           'audio':b'stale', 'error':'old failure'})
        assert not sent
        assert session._tts_inflight is None
    asyncio.run(scenario())


@pytest.mark.parametrize('code,expected', [('korean_voice_unavailable','korean_voice_unavailable'),
                                        ('secret/path','tts_unavailable'), (None,'tts_unavailable')])
def test_korean_tts_error_code_is_additive_and_allowlisted(code, expected):
    async def scenario():
        session = new_session()
        sent = []
        async def send(data): sent.append(data)
        session._send = send
        session._committed_turn_id = 'ko-turn'
        session._tts_inflight = {'task_id':'task', 'idx':0, 'sentence':'안녕하세요', 'kind':'surface'}
        await session._on_tts_event('error', {'task_id':'task', 'turn_id':'ko-turn-0',
                                            'error':'Voice unavailable', 'code':code})
        assert sent[0]['error'] == 'Voice unavailable'
        assert sent[0]['code'] == expected
    asyncio.run(scenario())
