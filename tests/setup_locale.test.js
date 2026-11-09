const assert = require('node:assert/strict');
const { test } = require('node:test');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const read = file => fs.readFileSync(path.join(__dirname, '..', file), 'utf8');
function catalog() {
  let messages;
  const context = { OAI18n: { register(value) { messages = value; } } };
  context.window = context;
  vm.runInNewContext(read('ui/locales/setup.js'), context);
  return messages;
}
test('Setup loads its catalog before the page and tags static text', () => {
  const html = read('ui/setup.html');
  for (const file of ['i18n.js', 'locales/common.js', 'locales/setup.js']) {
    assert.ok(html.indexOf(`/ui/${file}`) >= 0, `${file} missing`);
    assert.ok(html.indexOf(`/ui/${file}`) < html.indexOf('/ui/setup.js'));
  }
  assert.match(html, /data-i18n="setup\./);
  assert.doesNotMatch(html, /Brain · OpenRouter models|That's the only account/);
  assert.doesNotMatch(html, /Direct OpenAI|OPENAI_API_KEY|Memory embeddings use their separately configured provider/);
  assert.match(html, /STT and memory embeddings run locally/);
});
test('Setup catalog has Korean and English key and placeholder parity', () => {
  const { en, ko } = catalog();
  assert.deepEqual(Object.keys(en).sort(), Object.keys(ko).sort());
  assert.ok(Object.keys(en).length > 150);
  for (const key of Object.keys(en)) {
    assert.ok(key.startsWith('setup.'), key);
    assert.equal(typeof ko[key], 'string');
    assert.ok(ko[key].length, key);
    const params = text => [...text.matchAll(/\{([a-zA-Z_][\w]*)\}/g)].map(m => m[1]).sort();
    assert.deepEqual(params(en[key]), params(ko[key]), key);
  }
  for (const match of read('ui/setup.html').matchAll(/data-i18n(?:-[\w-]+)?="(setup\.[^"]+)"/g)) {
    assert.ok(en[match[1]], match[1]);
  }
});
test('locale changes only repaint explicitly bound text, not forms or network', () => {
  const s = read('ui/setup.js');
  assert.match(s, /oa:localechange/);
  const start = s.indexOf('  function refreshLocale()');
  assert.ok(start >= 0);
  const body = s.slice(start, s.indexOf('\n  }', start));
  assert.doesNotMatch(body, /loadModels|loadPersona|loadBuilder|loadVoiceMap|fetch\(|postAction|\.value\s*=|replaceChildren/);
  assert.doesNotMatch(s, /textOnly|text_only|provider_status|onlyOpenAI/);
  assert.match(s, /getJSON\("\/api\/tts_probe"\)/);
  assert.match(s, /confirmation: word/);
});

// A deliberately small DOM fixture. It executes the actual complete page and i18n
// scripts, but is not a substitute for a native browser/OS IME acceptance run.
class Node {
  constructor(tag = 'div') {
    this.tagName = tag.toUpperCase(); this.childNodes = []; this.attributes = {};
    this.value = ''; this.checked = false; this.disabled = false; this.hidden = false;
    this.style = {}; this.dataset = {}; this.events = {}; this.parent = null;
    this.selectionStart = 0; this.selectionEnd = 0;
    const classes = new Set();
    this.classList = { add: x => classes.add(x), remove: x => classes.delete(x),
      toggle: (x, on) => on ? classes.add(x) : classes.delete(x), contains: x => classes.has(x) };
  }
  get isConnected() { return this.root || !!this.parent?.isConnected; }
  get children() { return this.childNodes.filter(child => typeof child === 'object'); }
  get textContent() { return this.childNodes.map(x => typeof x === 'string' ? x : x.textContent).join(''); }
  set textContent(value) { this.replaceChildren(String(value)); }
  append(...children) { for (const child of children) { this.childNodes.push(child); if (typeof child === 'object') child.parent = this; } }
  replaceChildren(...children) { for (const child of this.children) child.parent = null; this.childNodes = []; this.append(...children); }
  setAttribute(k, v) { this.attributes[k] = String(v); if (k === 'id') this.id = v; if (k === 'value') this.value = v; if (k === 'data-key') this.dataset.key = v; }
  getAttribute(k) { return this.attributes[k] ?? null; }
  removeAttribute(k) { delete this.attributes[k]; }
  addEventListener(k, fn) { (this.events[k] ||= []).push(fn); }
  async dispatch(k, event = {}) { for (const fn of this.events[k] || []) await fn(event); }
  async click() { if (!this.disabled) await this.dispatch('click'); }
  focus() { this.focused = true; }
  querySelectorAll(selector) {
    const matches = node => selector.split(',').some(part => {
      const p = part.trim();
      if (p.startsWith('[data-i18n')) return node.getAttribute(p.slice(1, -1)) !== null;
      if (p === '#vmapGrid select[data-key]') return node.tagName === 'SELECT' && node.getAttribute('data-key') !== null;
      return node.tagName.toLowerCase() === p;
    });
    return descendants(this).slice(1).filter(matches);
  }
  querySelector(selector) { return this.querySelectorAll(selector)[0] || null; }
}
const descendants = node => [node, ...node.children.flatMap(child => typeof child === 'object' ? descendants(child) : [])];
const flush = () => new Promise(resolve => setImmediate(resolve));
function parseHTML(html) {
  const root = new Node('document'); root.root = true;
  const stack = [root];
  const decode = s => s.replace(/&amp;/g, '&').replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&quot;/g, '"');
  for (const token of html.match(/<!--[^]*?-->|<[^>]+>|[^<]+/g)) {
    if (token.startsWith('<!')) continue;
    if (token.startsWith('</')) { stack.pop(); continue; }
    if (token.startsWith('<')) {
      const tag = token.match(/^<([\w-]+)/)?.[1]; if (!tag) continue;
      const node = new Node(tag);
      for (const match of token.matchAll(/([\w-]+)="([^"]*)"/g)) node.setAttribute(match[1], decode(match[2]));
      stack.at(-1).append(node);
      if (!['input', 'meta', 'link', 'br', 'hr'].includes(tag)) stack.push(node);
    } else stack.at(-1).append(decode(token));
  }
  root.getElementById = id => descendants(root).find(n => n.id === id) || null;
  root.documentElement = root.querySelector('html'); root.readyState = 'loading';
  return root;
}
async function fixture({ locale = 'ko', korean, fallback = false, overrides = {}, fetchResponse } = {}) {
  const document = parseHTML(read('ui/setup.html')), events = {}, calls = [], writes = [], toasts = [];
  const roles = ['surface', 'deep', 'reflection', 'memory_write'];
  const responses = {
    '/health': { device: 'cpu', cuda_available: false }, '/api/build_f/status': { memory: { events: 2, facts: 3 } },
    '/api/tts_probe': { ok: true, url: 'http://voice', character: 'MekaHime_Amika', korean },
    '/api/avatar/models': { models: [] }, '/api/build_f/tools': { enabled: true, servers: {} },
    '/api/preflight': {}, '/api/vision': { enabled: false },
    '/api/build_f/models': { options: Object.fromEntries(roles.map(r => [r, [{ key: r, name: 'Baseline model', transport: 'openrouter' }]])), selections: Object.fromEntries(roles.map(r => [r, r])), presets: [{ name: 'Lean (validated)' }] },
    '/api/build_f/ollama': { models: [], base_url: 'http://localhost:11434' },
    '/api/voice_map': { enabled: true, voice: 'MekaHime_Amika', v1_ids: ['happy1', 'neutral1'], v2_grouped: { casual: ['happy'] }, map: { casual_happy: 'happy1' } },
    '/api/build_f/persona/simple': { story: [{ key: 'WHO YOU ARE', text: '原文 그대로' }], days: { 'weekday/清晨': ['原文一', '原文二'] }, about: { relationship: '관계 원문' } },
    '/api/build_f/persona': { user_name: 'Tester', persona_name: 'Amika', city: 'Paris', timezone: 'Europe/Paris', timezones: ['Europe/Paris'], files: { scenes: '{"original":true}', deep: '我说：原文' } },
    '/api/name_pronunciation': {}, '/api/build_f/messengers': {}, '/api/build_f/openrouter_key': { present: false }, ...overrides
  };
  const context = vm.createContext({ document, navigator: { language: locale },
    localStorage: { getItem() { return null; }, setItem() {} }, Intl, Date, console,
    setInterval() {}, CustomEvent: class { constructor(type, options) { this.type = type; this.detail = options.detail; } },
    fetch: async (url, options) => { writes.push({ url, options }); return fetchResponse || { ok: true, json: async () => ({}) }; },
    Audio: class { async play() {} pause() {} }
  });
  context.window = context;
  context.addEventListener = (name, fn) => (events[name] ||= []).push(fn);
  context.dispatchEvent = event => { for (const fn of events[event.type] || []) fn(event); };
  context.OA = { nav() {}, footer() {}, setNavDot() {}, toast: (...args) => toasts.push(args),
    el: (tag, props = {}, ...children) => { const n = new Node(tag); for (const [k, v] of Object.entries(props)) k === 'text' ? n.textContent = v : n.setAttribute(k, v); n.append(...children); return n; },
    getJSON: async url => { calls.push(url); const r = responses[url] || {}; if (r instanceof Error) throw r; return r; },
    postAction: async (url, action, data) => { writes.push({ url, action, data }); return {}; }
  };
  if (!fallback) vm.runInContext(read('ui/i18n.js'), context);
  vm.runInContext(read('ui/locales/setup.js'), context);
  document.getElementById('pTarget').value = 'scenes';
  vm.runInContext(read('ui/setup.js'), context);
  document.readyState = 'complete'; await document.dispatch('DOMContentLoaded');
  await flush(); await flush();
  return { context, document, calls, writes, toasts, nodes: id => document.getElementById(id) };
}
test('complete Setup switches Korean and English without replacing drafts, selections, focus or IME', async () => {
  const f = await fixture();
  assert.equal(f.document.querySelector('h1').textContent, 'Amika 설정하기');
  assert.match(f.nodes('pEditor').getAttribute('aria-label'), /원문/);
  assert.equal(f.nodes('providerNote'), null);
  assert.equal(f.nodes('orPanel').hidden, false);
  assert.equal(f.calls.includes('/api/tts_probe'), true);
  const fields = ['pUser', 'pCity', 'pSayAs', 'pEditor', 'avBanks', 'vmapVoice', 'orKeyInput', 'msgDiscordToken', 'msgDiscordUsers', 'olUrl'];
  for (const id of fields) { f.nodes(id).value = '한글 조합중 ㄱ ' + id; f.nodes(id).selectionStart = 3; f.nodes(id).selectionEnd = 5; }
  f.nodes('pUser').focus(); await f.nodes('pUser').dispatch('compositionstart');
  f.nodes('role_deep').value = 'unsaved-role'; f.nodes('vmap_casual_happy').value = 'neutral1';
  const story = f.nodes('personaBuilder').querySelector('textarea'); story.value = '수정한 원문'; await story.dispatch('input');
  const before = descendants(f.document), calls = f.calls.length;
  f.context.OAI18n.setLocale('en'); f.context.OAI18n.setLocale('ko');
  assert.deepEqual(descendants(f.document), before);
  assert.equal(f.calls.length, calls); assert.equal(f.writes.length, 0);
  for (const id of fields) { assert.equal(f.nodes(id).value, '한글 조합중 ㄱ ' + id); assert.equal(f.nodes(id).selectionStart, 3); assert.equal(f.nodes(id).selectionEnd, 5); }
  assert.equal(f.nodes('pUser').focused, true);
  assert.equal(f.nodes('role_deep').value, 'unsaved-role'); assert.equal(f.nodes('vmap_casual_happy').value, 'neutral1');
  assert.equal(story.value, '수정한 원문');
  await f.nodes('pbSave').click();
  assert.equal(f.writes.find(w => w.action === 'persona-simple').data.story['WHO YOU ARE'], '수정한 원문');
});
test('day-slot pending edits and protocol IDs survive a locale change', async () => {
  const f = await fixture();
  const buttons = descendants(f.nodes('personaBuilder')).filter(n => n.getAttribute('role') === 'tab');
  await buttons[1].click();
  const areas = f.nodes('personaBuilder').querySelectorAll('textarea'), slot = areas[1];
  slot.value = '새로운 일상'; await slot.dispatch('input');
  f.context.OAI18n.setLocale('en');
  assert.equal(slot.value, '새로운 일상'); assert.equal(buttons[1].getAttribute('aria-selected'), 'true');
  assert.match(buttons[1].title, /Possibility 2/);
  await f.nodes('pbSave').click();
  assert.deepEqual(Array.from(f.writes[0].data.days['weekday/清晨']), ['原文一', '새로운 일상']);
});
test('raw persona drafts preserve source and save the unchanged target ID', async () => {
  const f = await fixture();
  const source = '原文 {user_name} 【casual_happy】 한글 수정';
  f.nodes('pTarget').value = 'deep'; await f.nodes('pTarget').dispatch('change');
  assert.equal(f.nodes('pEditor').value, '我说：原文');
  f.nodes('pEditor').value = source; await f.nodes('pEditor').dispatch('input');
  f.context.OAI18n.setLocale('en');
  f.nodes('pTarget').value = 'scenes'; await f.nodes('pTarget').dispatch('change');
  f.context.OAI18n.setLocale('ko');
  f.nodes('pTarget').value = 'deep'; await f.nodes('pTarget').dispatch('change');
  assert.equal(f.nodes('pEditor').value, source);
  assert.equal(f.writes.length, 0);
  await f.nodes('pSave').click();
  const saved = f.writes.find(w => w.action === 'persona-save');
  assert.equal(saved.data.target, 'deep'); assert.equal(saved.data.content, source);
});
test('readiness distinguishes frontend-only from acoustic acceptance and old servers', async () => {
  for (const state of [undefined, 'disabled', 'unavailable', 'unknown', 'frontend_ready']) {
    const f = await fixture({ korean: state && { state, acoustic_acceptance: 'unverified' } });
    const rows = f.nodes('healthRows').textContent;
    assert.match(rows, /한국어 음성 준비 상태/); assert.match(rows, /품질은 검증되지 않았습니다/);
    if (state === 'frontend_ready') assert.match(rows, /전처리\(G2P\)만/);
    if (!state || state === 'unknown') assert.match(rows, /준비 상태를 알 수 없습니다/);
  }
});
test('baseline pronunciation sample stays available and sends the original pronunciation', async () => {
  const f = await fixture();
  assert.equal(f.nodes('pHear').disabled, false);
  f.nodes('pSayAs').value = '하늘';
  await f.nodes('pHear').dispatch('click');
  const sample = f.writes.find(write => write.action === 'tts-say');
  assert.equal(sample.data.text, '하늘. Hi, 하늘! Nice to meet you.');
  assert.equal(sample.data.raw, true);
  assert.equal(f.nodes('pHear').disabled, false);
});
test('confirmation remains WIPE/RESET and localized failures render as text', async () => {
  const f = await fixture({ overrides: { '/api/build_f/status': Object.assign(new Error('401 <img src=x onerror=bad>'), { status: 401 }) } });
  assert.match(f.nodes('healthRows').textContent, /인증에 실패/);
  assert.equal(f.document.querySelectorAll('img').length, 0);
  f.nodes('wipeConfirm').value = '삭제'; await f.nodes('wipeBtn').click();
  assert.equal(f.writes.length, 0); assert.match(f.toasts.at(-1)[0], /WIPE/);
  f.nodes('wipeConfirm').value = 'WIPE'; await f.nodes('wipeBtn').click();
  assert.equal(JSON.parse(f.writes[0].options.body).confirmation, 'WIPE');
});
test('provider failures use only stable status/code and never echo diagnostic sentinels', async () => {
  const sentinel = 'PRIVATE_PROVIDER_SENTINEL sk-secret@example.invalid unauthorized 429 timeout';
  for (const [fields, expected] of [
    [{ status: 401 }, /인증에 실패/], [{ code: 'unauthorized' }, /인증에 실패/],
    [{ status: 429 }, /요청 한도/], [{ code: 'timeout' }, /시간/], [{}, /요청에 실패/]
  ]) {
    const error = Object.assign(new Error(sentinel), fields, { detail: sentinel });
    const f = await fixture({ overrides: { '/api/build_f/status': error } });
    assert.match(f.nodes('healthRows').textContent, expected);
    assert.equal(f.document.textContent.includes(sentinel), false);
    f.context.OAI18n.setLocale('en');
    assert.equal(f.document.textContent.includes(sentinel), false);
  }
  const f = await fixture({ fetchResponse: { ok: false, status: 409, json: async () => ({ detail: sentinel }) } });
  f.nodes('wipeConfirm').value = 'WIPE'; await f.nodes('wipeBtn').click();
  assert.equal(f.nodes('dangerNote').textContent.includes(sentinel), false);
  assert.equal(f.toasts.some(([text]) => text.includes(sentinel)), false);
});
test('English catalog fallback works when the shared locale engine is absent', async () => {
  const f = await fixture({ fallback: true });
  assert.equal(f.nodes('modelsNote').textContent, '');
  assert.match(f.nodes('ttsDotNote').textContent, /reachable/);
  assert.match(f.nodes('healthRows').textContent, /Speech \/ STT/);
});
test('startup health labels translate while diagnostic identifiers stay intact', async () => {
  const f = await fixture({ overrides: { '/api/preflight': { at: '2026-11-06T07:00:00', summary: { warn: 2 }, checks: [
    { level: 'warn', name: 'API keys', detail: 'OPENAI_API_KEY missing' },
    { level: 'warn', name: 'service embedder', detail: 'connection refused' }
  ] } } });
  assert.match(f.nodes('healthRows').textContent, /API 키/);
  assert.match(f.nodes('healthRows').textContent, /서비스 · embedder/);
  assert.match(f.nodes('healthRows').textContent, /OPENAI_API_KEY missing/);
  f.context.OAI18n.setLocale('en');
  assert.match(f.nodes('healthRows').textContent, /API keys/);
});
test('shipped model and preset descriptions are Korean, while option IDs remain unchanged', async () => {
  const { execFileSync } = require('node:child_process');
  const shipped = JSON.parse(execFileSync('git', ['show', 'HEAD:config/llm_roles.json'], { cwd: path.join(__dirname, '..'), encoding: 'utf8' }));
  const f = await fixture({ overrides: { '/api/build_f/models': shipped } });
  for (const [role, choices] of Object.entries(shipped.options)) {
    const select = f.nodes('role_' + role);
    assert.deepEqual(select.children.map(n => n.value), choices.map(c => c.key));
    for (const choice of choices) {
      select.value = choice.key; await select.dispatch('change');
      const description = select.parent.children.at(-1).textContent;
      assert.match(description, /[가-힣]/, choice.key);
      assert.equal(description.includes(choice.description), false, 'untranslated description: ' + choice.key);
    }
  }
  for (let i = 0; i < shipped.presets.length; i++) {
    const option = f.nodes('presetSelect').children[i];
    assert.equal(option.value, shipped.presets[i].name);
    assert.equal(option.title.includes(shipped.presets[i].description), false, 'untranslated preset ' + option.value);
  }
});
