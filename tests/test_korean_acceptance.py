"""Offline asset/runner checks. Mock transports are not live acceptance."""
import asyncio
import importlib.util
import json
from pathlib import Path
import unicodedata

import pytest
from brain import po_contract

ROOT = Path(__file__).resolve().parents[1]


def runner():
    spec = importlib.util.spec_from_file_location('acceptance', ROOT / 'scripts/check_korean_acceptance.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def corpus():
    return json.loads((ROOT / 'tests/fixtures/korean_acceptance.json').read_text())


def test_fixed_corpus_and_contract():
    data = corpus()
    ids = []
    for key, count in [('dialogues', 20), ('memory', 10), ('tts', 60)]:
        assert len(data[key]) == count
        ids.extend(row['id'] for row in data[key])
    assert len(ids) == len(set(ids))
    assert {row['category'] for row in data['tts']} == {'pronunciation', 'numbers', 'names', 'mixed', 'long', 'emotions'}
    assert all(sum(row['category'] == c for row in data['tts']) == 10 for c in {r['category'] for r in data['tts']})
    for scenario in data['dialogues']:
        assert len(scenario['turns']) >= 2
        assert scenario['review']
        for turn in scenario['turns']:
            assert po_contract.reply_lang(turn['text'], turn['previous_lang']) == (turn['expected_lang'], turn['reason'])
    by_id = {s['id']: s for s in data['dialogues']}
    assert by_id['D03']['turns'][1]['reason'] == 'switch'
    assert by_id['D03']['turns'][2]['expected_lang'] == 'ko'
    assert unicodedata.normalize('NFC', by_id['D05']['turns'][0]['text']) != by_id['D05']['turns'][0]['text']
    for ident in ['D17', 'D18', 'D19', 'D20']:
        assert by_id[ident]['mode'] == 'manual'
        assert by_id[ident]['manual_steps']
    for fact in data['memory']:
        assert all(fact[k] for k in ['store', 'recall', 'correct', 'recall_corrected', 'original', 'replacement'])
        assert fact['original'] != fact['replacement']
    for sentence in data['tts']:
        assert sentence['text'] and sentence['review']
        assert po_contract.resolve_emotion(sentence['emotion']) == sentence['emotion']


@pytest.mark.parametrize('args', [[], ['--base-url', 'https://u:p@example.com'], ['--base-url', 'file:///tmp/a'], ['--base-url', 'http://localhost?token=x'], ['--base-url', 'http://localhost/path'], ['--base-url', 'http://localhost', '--limit', '0'], ['--base-url', 'http://localhost', '--rounds', '3']])
def test_arguments_reject_unsafe_or_unbounded(args, capsys):
    with pytest.raises(SystemExit):
        runner().parse_args(args)
    assert 'u:p' not in capsys.readouterr().err


def test_defaults_and_selection():
    m = runner()
    args = m.parse_args(['--base-url', 'http://127.0.0.1:53999/'])
    assert not args.text and args.limit == 3 and args.rounds == 1
    assert args.base_url == 'http://127.0.0.1:53999'
    assert len(m.select_dialogues(corpus(), 20)) == 16


def test_record_handling_no_raw_output():
    m = runner()
    turn = {'expected_lang': 'ko'}
    record = m.summarize_turn('D01', 1, 1, turn, [
        {'type': 'ai_surface_done', 'reply_lang': 'ko', 'reply': 'SECRET'},
        {'type': 'ai_end', 'token': 'SECRET'}])
    assert record['status'] == 'contract_observed'
    assert 'SECRET' not in json.dumps(record)
    assert m.summarize_turn('D01', 1, 1, turn, [{'type': 'ai_end'}])['status'] == 'incomplete'
    assert m.summarize_turn('D01', 1, 1, turn, [{'type': 'ai_surface_done', 'reply_lang': 'en'}, {'type': 'ai_end'}])['status'] == 'mismatch'
    assert m.summarize_turn('D01', 1, 1, turn, [{'type': 'ai_error', 'message': 'SECRET'}])['status'] == 'error'


def test_mocked_turn_ignores_stale_events_and_sends_only_text():
    m = runner()
    class WS:
        def __init__(self):
            self.sent = []
            self.events = iter([
                {'type': 'ai_end', 'turn_id': 'old'},
                {'type': 'commit', 'turn_id': 'new', 'text': '네'},
                {'type': 'ai_surface_done', 'turn_id': 'old', 'reply_lang': 'en'},
                {'type': 'ai_surface_done', 'turn_id': 'new', 'reply_lang': 'ko'},
                {'type': 'ai_end', 'turn_id': 'new'}])
        async def send_json(self, data):
            self.sent.append(data)
        async def receive_json(self, **kwargs):
            return next(self.events)
    ws = WS()
    events = asyncio.run(m.exchange(ws, '네'))
    assert ws.sent == [{'type': 'text', 'text': '네'}]
    assert [e['type'] for e in events] == ['ai_surface_done', 'ai_end']


def test_http_allowlist_and_redirect_safety():
    m = runner()
    assert m.HTTP_PATHS == ('/health', '/api/preflight', '/use', '/setup', '/tools', '/about', '/flow')
    class Response:
        status = 302
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
    class Client:
        def get(self, url, **kwargs):
            assert kwargs['allow_redirects'] is False
            return Response()
    records = asyncio.run(m.check_http(Client(), 'http://127.0.0.1:53999'))
    assert len(records) == 7
    assert all(r['status'] == 'http_failure' for r in records)


def test_redirect_hook_rejects_without_echo():
    with pytest.raises(ValueError, match='redirects are not permitted'):
        asyncio.run(runner().reject_redirect(None, None, {'url': 'SECRET'}))


def test_event_budget_and_malformed_input():
    m = runner()
    class WS:
        async def send_json(self, data): pass
        async def receive_json(self): return {'type': 'noise'}
    with pytest.raises(TimeoutError):
        asyncio.run(m.exchange(WS(), '네'))
    class BadWS(WS):
        async def receive_json(self): return ['not an event']
    with pytest.raises(ValueError):
        asyncio.run(m.exchange(BadWS(), '네'))


@pytest.mark.parametrize('text,healthy', [(False, True), (True, False), (True, True)])
def test_mocked_runner_boundaries(monkeypatch, text, healthy):
    import aiohttp
    m = runner()
    sent = []
    connections = []
    class Response:
        status = 200 if healthy else 503
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
    class WS:
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        async def receive_json(self, **kwargs): return {'type': 'ready', 'brain': True}
        async def send_json(self, data): sent.append(data)
    class Client:
        def __init__(self, **kwargs):
            assert kwargs['trust_env'] is False
            assert kwargs['trace_configs'][0].on_request_redirect[0] is m.reject_redirect
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        def get(self, url, **kwargs):
            assert kwargs['allow_redirects'] is False
            return Response()
        def ws_connect(self, url, **kwargs):
            connections.append(url)
            return WS()
    async def exchange(ws, prompt):
        await ws.send_json({'type': 'text', 'text': prompt})
        return [{'type': 'ai_surface_done', 'reply_lang': 'ko'}, {'type': 'ai_end'}]
    monkeypatch.setattr(aiohttp, 'ClientSession', Client)
    monkeypatch.setattr(m, 'exchange', exchange)
    args = m.parse_args(['--base-url', 'http://127.0.0.1:53999', '--limit', '1', '--rounds', '2'] + (['--text'] if text else []))
    records = asyncio.run(m.run(args))
    assert len(connections) == (2 if text and healthy else 0)
    assert all(row['type'] in ('text', 'settings') for row in sent)
    assert all(row == {'type': 'settings', 'voice_output': False} for row in sent if row['type'] == 'settings')
    assert len(records) == (11 if text and healthy else 7)


def test_main_failure_is_redacted(monkeypatch, capsys):
    m = runner()
    async def fail(args): raise RuntimeError('SECRET')
    monkeypatch.setattr(m, 'run', fail)
    assert m.main(['--base-url', 'http://127.0.0.1:53999']) == 1
    assert 'SECRET' not in capsys.readouterr().out


@pytest.mark.parametrize('origin', ['https://example.com', 'http://192.168.1.2:53100', 'http://localhost:53100', 'http://127.0.0.1.example.com:53100'])
def test_text_requires_literal_loopback(origin):
    with pytest.raises(SystemExit):
        runner().parse_args(['--base-url', origin, '--text'])
    assert runner().parse_args(['--base-url', origin]).text is False


@pytest.mark.parametrize('origin', ['http://127.0.0.1:53100', 'http://[::1]:53100'])
def test_text_accepts_literal_loopback(origin):
    assert runner().parse_args(['--base-url', origin, '--text']).text is True


@pytest.mark.parametrize('failure', ['mismatch', 'error', 'incomplete', 'exception'])
def test_failures_retained_and_later_scenarios_run(monkeypatch, failure):
    import aiohttp
    m = runner()
    prompts = []
    connections = []
    class WS:
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        async def receive_json(self, **kwargs): return {'type': 'ready', 'brain': True}
        async def send_json(self, data): pass
    class Client:
        def __init__(self, **kwargs): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        def ws_connect(self, url, **kwargs):
            connections.append(url)
            return WS()
    async def http(*args): return [{'status': 'reachable'}]
    async def exchange(ws, text):
        prompts.append(text)
        if len(prompts) == 1:
            if failure == 'exception': raise ValueError('SECRET')
            if failure == 'error': return [{'type': 'ai_error'}]
            if failure == 'incomplete': return [{'type': 'ai_end'}]
            return [{'type': 'ai_surface_done', 'reply_lang': 'en'}, {'type': 'ai_end'}]
        return [{'type': 'ai_surface_done', 'reply_lang': 'ko'}, {'type': 'ai_end'}]
    monkeypatch.setattr(aiohttp, 'ClientSession', Client)
    monkeypatch.setattr(m, 'check_http', http)
    monkeypatch.setattr(m, 'exchange', exchange)
    args = m.parse_args(['--base-url', 'http://127.0.0.1:53100', '--text', '--limit', '2', '--rounds', '2'])
    records = asyncio.run(m.run(args))
    assert len(connections) == 4
    expected = 'transport_or_protocol_error' if failure == 'exception' else failure
    assert records[1]['status'] == expected
    assert any(r.get('scenario') == 'D02' and r['status'] == 'contract_observed' for r in records)
    assert any(r.get('round') == 2 for r in records)
    first_followup = corpus()['dialogues'][0]['turns'][1]['text']
    assert prompts.count(first_followup) == (2 if failure == 'mismatch' else 1)
    assert 'SECRET' not in json.dumps(records)
