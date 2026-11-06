#!/usr/bin/env python3
"""Bounded public-path observations, never a native-quality acceptance score."""
import argparse
import asyncio
import ipaddress
import json
from pathlib import Path
from urllib.parse import urlsplit

HTTP_PATHS = ('/health', '/api/preflight', '/use', '/setup', '/tools', '/about', '/flow')
CORPUS = Path(__file__).resolve().parents[1] / 'tests/fixtures/korean_acceptance.json'
LANGUAGES = {'ko', 'en', 'ja', 'zh'}


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-url', required=True, help='Explicit isolated service origin, without credentials/path/query')
    parser.add_argument('--text', action='store_true', help='Opt in to paid/model dialogue on a literal loopback IP and possible test-profile memory writes')
    parser.add_argument('--limit', type=int, default=3, help='First 1..20 automatic scenarios (manual scenarios always excluded)')
    parser.add_argument('--rounds', type=int, default=1, help='Repeat corpus 1..2 times, without resetting service memory')
    args = parser.parse_args(argv)
    try:
        url = urlsplit(args.base_url)
        valid = (url.scheme in ('http', 'https') and url.hostname and not url.username
                 and not url.password and not url.query and not url.fragment
                 and url.path in ('', '/') and not any(c.isspace() for c in args.base_url))
        url.port
    except ValueError:
        valid = False
    if not valid:
        parser.error('base URL must be an HTTP(S) origin without credentials, path, query or fragment')
    if args.text:
        try:
            loopback = ipaddress.ip_address(url.hostname).is_loopback
        except ValueError:
            loopback = False
        if not loopback:
            parser.error('--text requires a literal loopback IP origin for an isolated test service')
    if not 1 <= args.limit <= 20 or not 1 <= args.rounds <= 2:
        parser.error('limit must be 1..20 and rounds must be 1..2')
    args.base_url = args.base_url.rstrip('/')
    return args


def select_dialogues(data, limit):
    return [row for row in data['dialogues'] if row['mode'] == 'automatic'][:limit]


async def check_http(client, base_url):
    records = []
    for path in HTTP_PATHS:
        try:
            async with client.get(base_url + path, allow_redirects=False) as response:
                records.append({'path': path, 'http_status': response.status,
                                'status': 'reachable' if response.status == 200 else 'http_failure'})
        except Exception:
            # Neither response bodies nor exception URLs/messages are safe to echo.
            records.append({'path': path, 'status': 'transport_error'})
    return records


async def exchange(ws, text):
    """Correlate one committed turn, ignore replayed or unsolicited events."""
    events = []
    turn_id = None
    async with asyncio.timeout(90):
        await ws.send_json({'type': 'text', 'text': text})
        for _ in range(2000):
            event = await ws.receive_json()
            if not isinstance(event, dict):
                raise ValueError('invalid event')
            kind = event.get('type')
            if kind == 'ai_error' and (turn_id is None or event.get('turn_id') in (None, turn_id)):
                return [{'type': 'ai_error'}]
            if kind == 'commit' and event.get('text') == text and isinstance(event.get('turn_id'), str):
                turn_id = event['turn_id']
            if turn_id is None or event.get('turn_id') != turn_id:
                continue
            if kind in ('ai_surface_done', 'ai_deep_done', 'ai_end'):
                # Only retain contract fields. Never retain raw model/inner thought/error content.
                lang = event.get('reply_lang')
                events.append({'type': kind, 'reply_lang': lang if lang in LANGUAGES else None})
            if kind == 'ai_end':
                return events
    raise TimeoutError('event budget exceeded')


def summarize_turn(scenario_id, round_number, turn_number, turn, events):
    langs = [e.get('reply_lang') for e in events if e.get('reply_lang') in LANGUAGES]
    kinds = [e.get('type') for e in events]
    if 'ai_error' in kinds:
        status = 'error'
    elif any(lang != turn['expected_lang'] for lang in langs):
        status = 'mismatch'
    elif not langs or 'ai_end' not in kinds:
        status = 'incomplete'
    else:
        status = 'contract_observed'
    return {'scenario': scenario_id, 'round': round_number, 'turn': turn_number,
            'expected_lang': turn['expected_lang'], 'observed_langs': langs,
            'status': status, 'human_review': 'pending'}


async def reject_redirect(session, context, params):
    """Reject before following redirects, including WebSocket handshakes."""
    raise ValueError('redirects are not permitted')


async def run(args):
    import aiohttp
    data = json.loads(CORPUS.read_text(encoding='utf-8'))
    records = []
    trace = aiohttp.TraceConfig()
    trace.on_request_redirect.append(reject_redirect)
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15), trust_env=False,
                                     cookie_jar=aiohttp.DummyCookieJar(), trace_configs=[trace]) as client:
        records.extend(await check_http(client, args.base_url))
        if args.text and all(r['status'] == 'reachable' for r in records):
            # A new transport per scenario is not a new memory profile.
            for round_number in range(1, args.rounds + 1):
                for scenario in select_dialogues(data, args.limit):
                    try:
                        async with client.ws_connect(args.base_url + '/ws/dialog', max_msg_size=262144) as ws:
                            ready = await ws.receive_json(timeout=15)
                            if not isinstance(ready, dict) or ready.get('type') != 'ready' or ready.get('brain') is not True:
                                raise ValueError('not ready')
                            # Session-only setting: no audio generation or playback consent.
                            await ws.send_json({'type': 'settings', 'voice_output': False})
                            for number, turn in enumerate(scenario['turns'], 1):
                                events = await exchange(ws, turn['text'])
                                record = summarize_turn(scenario['id'], round_number, number, turn, events)
                                records.append(record)
                                if record['status'] in ('error', 'incomplete'):
                                    break
                    except Exception:
                        records.append({'scenario': scenario['id'], 'round': round_number,
                                        'status': 'transport_or_protocol_error', 'human_review': 'pending'})
                        continue
    return records


def main(argv=None):
    args = parse_args(argv)
    try:
        records = asyncio.run(run(args))
    except (Exception, KeyboardInterrupt):
        print(json.dumps({'status': 'runner_error', 'human_review': 'pending'}))
        return 1
    for record in records:
        print(json.dumps(record, ensure_ascii=False))
    print(json.dumps({'native_quality': 'not_evaluated', 'manual_scenarios': 'not_run',
                      'text_requested': args.text}))
    return int(any(r['status'] not in ('reachable', 'contract_observed') for r in records))


if __name__ == '__main__':
    raise SystemExit(main())
