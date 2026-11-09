"""Readiness is frontend evidence only, with no synthesis or asset installation."""
import asyncio
import ast
import copy
import json
from types import SimpleNamespace

import pytest
from test_korean_voice_probe import vendor, voice, SCRIPT
from test_korean_gateway import SOURCE


def gateway(responses, url='http://127.0.0.1:9'):
    import aiohttp
    calls = []
    class Response:
        def __init__(self, status, body):
            self.status = status
            self.body = body
            self.content = self
        async def read(self, n=-1):
            raw = json.dumps(self.body).encode()[:n]
            return raw
        async def readexactly(self, n):
            raw = json.dumps(self.body).encode()
            if len(raw) < n: raise asyncio.IncompleteReadError(raw, n)
            return raw[:n]
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
    class Client:
        def __init__(self, **kwargs): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        def get(self, url, **kwargs):
            calls.append((url, kwargs))
            value = responses.pop(0)
            if isinstance(value, Exception): raise value
            return Response(*value)
    tree = ast.parse(SOURCE.read_text())
    nodes = [copy.deepcopy(n) for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
             and n.name in {'tts_probe', '_korean_readiness_status'}]
    for node in nodes: node.decorator_list = []
    ns = dict(asyncio=asyncio, json=json, TTS_URL=url,
              TTS_CHARACTER_ID='original', aiohttp=SimpleNamespace(ClientSession=Client,
              ClientTimeout=aiohttp.ClientTimeout, ClientError=aiohttp.ClientError))
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(SOURCE), 'exec'), ns)
    return ns['tts_probe'], calls


def test_public_probe_url_does_not_expose_credentials_or_paths():
    fn, calls = gateway([(503, {})], 'http://user:SECRET@127.0.0.1:9/private/file?token=KEY#secret')
    result = asyncio.run(fn())
    assert result['url'] == 'http://127.0.0.1:9'
    assert result['korean']['state'] == 'unavailable'
    assert len(calls) == 1


@pytest.mark.parametrize('status,body,state', [(404, {}, 'unknown'), (302, {}, 'unknown'),
    (200, {'state':'frontend_ready', 'code':'korean_frontend_ready', 'secret':'/private/key'}, 'frontend_ready'),
    (200, {'state':'accepted', 'code':'secret'}, 'unknown')])
def test_ping_is_not_korean_acceptance(status, body, state):
    fn, calls = gateway([(200, {}), (status, body)])
    result = asyncio.run(fn())
    assert result['ok'] is True
    assert result['korean']['state'] == state
    assert result['korean']['acoustic_acceptance'] == 'unverified'
    assert 'secret' not in json.dumps(result)
    assert all(call[1]['allow_redirects'] is False for call in calls)


def test_missing_engine_public_error_is_safe():
    import aiohttp
    fn, _ = gateway([aiohttp.ClientError('/private/token=SECRET')])
    result = asyncio.run(fn())
    assert result['korean']['state'] == 'unavailable'
    assert 'SECRET' not in json.dumps(result)


def test_vendor_missing_engine_no_child(vendor, monkeypatch, tmp_path):
    server = object.__new__(vendor.Server)
    server.engine = SimpleNamespace(state='loading')
    server.args = SimpleNamespace(gpt_sovits_dir=tmp_path)
    monkeypatch.setattr(asyncio, 'create_subprocess_exec', lambda *a, **kw: pytest.fail('spawn while loading'))
    result = asyncio.run(server.korean_readiness())
    assert result['state'] == 'unavailable'
    assert result['acoustic_acceptance'] == 'unverified'


def test_vendor_child_is_guarded_cached_and_bounded(vendor, monkeypatch, tmp_path):
    helper = tmp_path / 'korean_voice_probe.py'
    helper.write_text('import json\nprint(json.dumps({"ok": True}))\n')
    monkeypatch.setattr(vendor, 'ENGINE_DIR', tmp_path)
    server = object.__new__(vendor.Server)
    server.engine = SimpleNamespace(state='ready')
    server.args = SimpleNamespace(gpt_sovits_dir=tmp_path)
    async def scenario():
        first = await server.korean_readiness()
        assert first['state'] == 'frontend_ready'
        first['state'] = 'corrupted'
        helper.write_text('raise RuntimeError("must use cache")')
        assert (await server.korean_readiness())['state'] == 'frontend_ready'
        server._korean_cache = None
        assert (await server.korean_readiness())['state'] == 'unavailable'
    asyncio.run(scenario())


@pytest.mark.parametrize('mode', ['timeout', 'oversize', 'cancel', 'stale', 'changed_checkout'])
def test_vendor_inflight_boundaries(vendor, monkeypatch, tmp_path, mode):
    helper = tmp_path / 'korean_voice_probe.py'
    script = ('import time, json\ntime.sleep(0.15)\nprint(json.dumps({"ok": True}))\n')
    if mode == 'timeout': script = 'import time\ntime.sleep(60)\n'
    if mode == 'oversize': script = 'print("x" * 20000)\n'
    helper.write_text(script)
    monkeypatch.setattr(vendor, 'ENGINE_DIR', tmp_path)
    server = object.__new__(vendor.Server)
    server.engine = SimpleNamespace(state='ready')
    server.args = SimpleNamespace(gpt_sovits_dir=tmp_path)
    async def scenario():
        task = asyncio.create_task(server.korean_readiness())
        await asyncio.sleep(0.05)
        if mode == 'cancel':
            task.cancel()
            with pytest.raises(asyncio.CancelledError): await task
            result = await server.korean_readiness()
            assert result['state'] == 'frontend_ready'
        elif mode == 'changed_checkout':
            server.args.gpt_sovits_dir = tmp_path / 'other'
            result = await server.korean_readiness()
            assert result['state'] != 'frontend_ready'
            assert (await task)['state'] != 'frontend_ready'
        else:
            if mode == 'stale': server.engine.state = 'error'
            result = await task
            assert result['state'] == 'unavailable'
            if mode == 'timeout': assert result['code'] == 'korean_probe_timeout'
        assert result['acoustic_acceptance'] == 'unverified'
    asyncio.run(asyncio.wait_for(scenario(), 4))


def test_vendor_cache_expires(vendor, monkeypatch, tmp_path):
    helper = tmp_path / 'korean_voice_probe.py'
    helper.write_text('print(\'{"ok": true}\')')
    monkeypatch.setattr(vendor, 'ENGINE_DIR', tmp_path)
    server = object.__new__(vendor.Server)
    server.engine = SimpleNamespace(state='ready')
    server.args = SimpleNamespace(gpt_sovits_dir=tmp_path)
    async def scenario():
        assert (await server.korean_readiness())['state'] == 'frontend_ready'
        key, stamp, result = server._korean_cache
        server._korean_cache = (key, stamp - 31, result)
        helper.write_text('print(\'{"ok": false}\')')
        assert (await server.korean_readiness())['state'] == 'unavailable'
    asyncio.run(scenario())


@pytest.mark.parametrize('action', ['import subprocess; subprocess.run(["pip", "install", "unsafe"])',
    'import nltk; nltk.download("cmudict")', 'open("must-not-write", "w")'])
def test_readiness_real_guard_never_installs(vendor, voice, monkeypatch, action):
    engine, packages, front = voice
    front.joinpath('korean.py').write_text(action + '\ndef g2p(text): return ["a"]\n')
    engine.joinpath('korean_voice_probe.py').write_text(
        f'import sys, runpy\nsys.path.insert(0, {str(packages)!r})\nrunpy.run_path({str(SCRIPT)!r}, run_name="__main__")\n')
    monkeypatch.setattr(vendor, 'ENGINE_DIR', engine)
    server = object.__new__(vendor.Server)
    server.engine = SimpleNamespace(state='ready')
    server.args = SimpleNamespace(gpt_sovits_dir=engine / 'GPT-SoVITS')
    result = asyncio.run(server.korean_readiness())
    assert result == {'state':'unavailable', 'code':'korean_probe_failed', 'acoustic_acceptance':'unverified'}
    assert not (engine / 'GPT-SoVITS' / 'must-not-write').exists()
