const assert = require('node:assert/strict');
const { test } = require('node:test');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const read = name => fs.readFileSync(path.join(__dirname, '..', name), 'utf8');
function catalog() {
  let messages;
  vm.runInNewContext(read('ui/locales/use.js'), { OAI18n: { register(value) { messages = value; } } });
  return messages;
}
test('Use catalog has matching Korean keys and interpolation parameters', () => {
  const { en, ko } = catalog();
  assert.ok(Object.keys(en).length > 140);
  assert.deepEqual(Object.keys(en).sort(), Object.keys(ko).sort());
  for (const key of Object.keys(en)) {
    assert.ok(key.startsWith('use.'));
    assert.equal(typeof ko[key], 'string');
    assert.deepEqual(en[key].match(/\{\w+\}/g)?.sort() || [], ko[key].match(/\{\w+\}/g)?.sort() || [], key);
  }
});
test('Use loads locale foundation and catalog before page scripts and tags static text', () => {
  const html = read('ui/use.html');
  const paths = ['/ui/i18n.js', '/ui/locales/common.js', '/ui/locales/use.js', '/ui/common.js', '/ui/use.js'];
  for (let i = 1; i < paths.length; i++) assert.ok(html.indexOf(paths[i - 1]) < html.indexOf(paths[i]));
  const messages = catalog();
  for (const match of html.matchAll(/data-i18n(?:-[\w-]+)?="([^"]+)"/g)) assert.ok(messages.en[match[1]], match[1]);
  assert.match(html, /data-i18n-placeholder=/);
  assert.match(html, /data-i18n-aria-label=/);
});

// Small DOM boundary, with real i18n and real page handlers. No network or browser permissions.
class Element {
  constructor(tag = 'div') {
    this.tagName = tag.toUpperCase(); this.attrs = {}; this.childNodes = []; this.events = {};
    this.value = ''; this.checked = true; this.disabled = false; this.hidden = false; this.style = {};
    this.classList = { add() {}, remove() {}, toggle() {}, contains() { return false; } };
  }
  get children() { return this.childNodes.filter(n => n instanceof Element); }
  get textContent() { return this.childNodes.map(n => n instanceof Element ? n.textContent : String(n)).join(''); }
  set textContent(text) { this.childNodes = [String(text)]; }
  set innerHTML(text) { assert.equal(text, '', 'Only clearing HTML is permitted'); this.childNodes = []; }
  get innerHTML() { return this.textContent; }
  setAttribute(k, v) { this.attrs[k] = String(v); if (k === 'placeholder' || k === 'title') this[k] = String(v); }
  getAttribute(k) { return this.attrs[k] ?? null; }
  removeAttribute(k) { delete this.attrs[k]; }
  append(...nodes) { for (const n of nodes) { if (n instanceof Element) n.parentNode = this; this.childNodes.push(n); } }
  replaceChildren(...nodes) { this.childNodes = []; this.append(...nodes); }
  addEventListener(k, fn) { (this.events[k] ||= []).push(fn); }
  dispatch(k, extra = {}) { const event = { type: k, preventDefault() { this.prevented = true; }, ...extra }; for (const fn of this.events[k] || []) fn(event); return event; }
  async click() { if (!this.disabled) { this.dispatch('click'); return this.onclick?.(); } }
  focus() { this.ownerDocument.activeElement = this; }
  remove() { if (this.parentNode) this.parentNode.childNodes = this.parentNode.childNodes.filter(n => n !== this); }
  contains(node) { return this === node || this.children.some(n => n.contains(node)); }
  matches(selector) {
    return selector.split(',').some(s => s.startsWith('[') ? this.getAttribute(s.slice(1, -1)) !== null
      : s.startsWith('.') ? (this.attrs.class || '').split(' ').includes(s.slice(1)) : this.tagName === s.toUpperCase());
  }
  querySelectorAll(selector) { return this.children.flatMap(n => [...(n.matches(selector) ? [n] : []), ...n.querySelectorAll(selector)]); }
  querySelector(selector) { return this.querySelectorAll(selector)[0] || null; }
  closest() { return null; }
}
const flush = () => new Promise(resolve => setImmediate(resolve));
function fixture({ locale = 'ko', transport = 'openrouter', onboarded = true, telemetry = false } = {}) {
  const body = new Element('body'), html = new Element('html'), nodes = {}, calls = [], toasts = [], sockets = [], events = {};
  html.append(body);
  const document = { body, documentElement: html, readyState: 'complete', activeElement: null,
    querySelectorAll: selector => html.querySelectorAll(selector), addEventListener() {} };
  const $ = id => {
    if (!nodes[id]) { const n = new Element(/Input$/.test(id) ? 'input' : 'div'); n.ownerDocument = document; nodes[id] = n; body.append(n); }
    return nodes[id];
  };
  const roles = ['surface', 'deep', 'reflection', 'memory_write'];
  const models = { selections: Object.fromEntries(roles.map(r => [r, r])), options: Object.fromEntries(roles.map(r => [r, [{ key: r, transport }]])) };
  const context = vm.createContext({ document, $, console, URL, Blob, Intl, setTimeout, clearTimeout, setInterval, clearInterval,
    location: { protocol: 'http:', host: 'test.invalid' }, navigator: { language: locale, mediaDevices: { getUserMedia() { calls.push('microphone'); throw Error('not allowed'); } } },
    localStorage: { getItem() { return null; }, setItem() {} },
    CustomEvent: class { constructor(type, options) { this.type = type; this.detail = options.detail; } },
    addEventListener(type, fn) { (events[type] ||= []).push(fn); }, dispatchEvent(event) { for (const fn of events[event.type] || []) fn(event); },
    getJSON: async url => { calls.push(url); return url === '/health' ? { device: 'cpu', cuda_available: false }
      : url.endsWith('/persona') ? { onboarded, user_name: 'User', city: '', timezone: 'America/Los_Angeles', timezones: ['America/Los_Angeles', 'Asia/Tokyo'] }
      : url.endsWith('/models') ? models : {}; },
    Audio: class {
      constructor(source) { this.source = source; }
      async play() { calls.push('audio-play'); }
      pause() {}
    },
    postAction: async (url, action, payload) => { calls.push({ url, action, payload }); return { ok: true, audio: 'synthetic', audio_format: 'wav' }; },
    toast: text => toasts.push(text), setNavDot() {}, pollStatus() {}, resetEmote() {},
    avatar: { flush() {}, hasModel: false }, avatarReady: false, TARGET_SR: 16000,
    hideTip() {}, renderChart() {}, lastUsage: null,
    WebSocket: class { constructor() { this.readyState = 1; this.sent = []; sockets.push(this); } send(data) { this.sent.push(JSON.parse(data)); } },
  });
  context.window = context;
  context.OA = { healthCheck: async () => ({ level: 'ok', items: [] }) };
  context.el = (tag, attrs = {}, ...children) => {
    const node = new Element(tag); node.ownerDocument = document;
    for (const [k, v] of Object.entries(attrs)) {
      if (v === null || v === undefined) continue;
      if (k === 'text') node.textContent = v;
      else if (k === 'onclick' || k === 'value') node[k] = v;
      else if (k === 'disabled' || k === 'hidden') node[k] = true;
      else node.setAttribute(k, v);
    }
    node.append(...children); context.OAI18n.translate(node); return node;
  };
  vm.runInContext(read('ui/i18n.js'), context);
  vm.runInContext(read('ui/locales/use.js'), context);
  const source = read('ui/use.js');
  const runSlice = (start, end) => {
    const at = source.indexOf(start);
    vm.runInContext(source.slice(at, source.indexOf(end, at)), context);
  };
  runSlice('  // ── power / socket', '  // ── outgoing text');
  runSlice('  // ── outgoing text / controls', '  // ── incoming dialog events');
  if (telemetry) {
    context.fmt = { int: v => String(v), pct: v => v + '%', usd: v => '$' + v, ms: v => v + ' ms', s1: v => v / 1000 + ' s' };
    runSlice('  // ── latency chart', '  // ── tool dialogue:');
  }
  runSlice('  function refreshUseLocale()', '  // ── first run:');
  return { context, document, body, nodes, $, calls, toasts, sockets, runSlice, source,
    setLocale: language => context.OAI18n.setLocale(language) };
}
test('actual power labels switch locale while active chat composition and socket are preserved', async () => {
  const f = fixture(); await flush();
  vm.runInContext('connect(); ws.onopen();', f.context);
  assert.equal(f.$('powerState').textContent, '온라인');
  assert.match(f.$('powerDetail').textContent, /텍스트와 마이크 준비됨/);
  assert.equal(f.$('micBtn').disabled, false);
  const input = f.$('sayInput'); input.value = '한글 조합 중'; input.selectionStart = 3; input.focus(); input.dispatch('compositionstart');
  const socket = f.sockets[0], requests = f.calls.length;
  f.setLocale('en');
  assert.equal(f.$('powerState').textContent, 'Online');
  assert.match(f.$('powerDetail').textContent, /text & mic ready/);
  assert.strictEqual(f.$('sayInput'), input); assert.equal(input.value, '한글 조합 중'); assert.equal(input.selectionStart, 3);
  assert.strictEqual(f.document.activeElement, input); assert.equal(f.sockets.length, 1); assert.equal(f.calls.length, requests);
  f.$('sayForm').dispatch('submit'); assert.equal(socket.sent.filter(m => m.type === 'text').length, 0);
  input.dispatch('compositionend'); f.setLocale('ko'); f.$('sayForm').dispatch('submit');
  assert.deepEqual(socket.sent.filter(m => m.type === 'text'), [{ type: 'text', text: '한글 조합 중' }]);
  assert.equal(f.calls.includes('microphone'), false);
});
test('baseline microphone requests browser permission without capability negotiation', async () => {
  const f = fixture();
  f.$('sayInput').value = '보존할 초안';
  await vm.runInContext('startMic()', f.context);
  assert.equal(f.calls.includes('microphone'), true);
  assert.equal(f.calls.includes('/health'), false);
  assert.equal(f.$('sayInput').value, '보존할 초안');
  assert.match(f.toasts.at(-1), /마이크 권한이 거부되었습니다/);
  assert.doesNotMatch(f.source, /text_only|textOnly|applyCapabilities|provider_status|directOpenAI/);
});
test('tool approval and question labels switch without recreating drafts or translating payloads', async () => {
  const f = fixture(); await flush();
  vm.runInContext('let toolTimer = null, jobsSeen = "";', f.context);
  f.runSlice('  // ── polling the brain', '  async function pollTools()');
  f.context.jobs = [{ server: 'Hermes', job: 'id-1', state: 'waiting_question', task: 'Keep this English task', pending: { kind: 'question', text: '<img onerror=alert(1)>' } },
    { server: 'nanoMuse', job: 'id-2', state: 'waiting_approval', task: 'raw task', pending: { kind: 'approval', text: 'raw approval request' } }];
  vm.runInContext('renderJobs(jobs)', f.context);
  const box = f.$('jobsBox'), input = box.querySelector('input');
  input.value = '내 답변'; input.selectionStart = 2; input.focus();
  assert.match(box.textContent, /승인 요청: raw approval request/); assert.match(box.textContent, /질문: <img onerror=alert\(1\)>/);
  assert.equal(box.querySelector('img'), null);
  const requestCount = f.calls.length;
  f.setLocale('en');
  assert.strictEqual(box.querySelector('input'), input); assert.equal(input.value, '내 답변'); assert.equal(input.selectionStart, 2);
  assert.match(box.textContent, /Approval requested: raw approval request/); assert.match(box.textContent, /Keep this English task/);
  assert.equal(f.calls.length, requestCount, 'Switching locale must never approve or answer a job');
  f.setLocale('ko');
  const button = box.querySelectorAll('button').find(n => n.textContent === '답변 보내기');
  await button.click();
  const action = f.calls.find(c => c?.action === 'tools-job');
  assert.equal(action.payload.action, 'answer'); assert.equal(action.payload.text, '내 답변'); assert.equal(action.payload.job, 'id-1');
  vm.runInContext('clearTimeout(toolTimer)', f.context);
});
async function wizardFixture(options = {}) {
  const f = fixture({ ...options, onboarded: false });
  f.$('stageEmpty').hidden = false;
  vm.runInContext(f.source.slice(f.source.indexOf('  async function firstRun()'), f.source.lastIndexOf('  firstRun();')), f.context);
  await vm.runInContext('firstRun()', f.context);
  f.box = f.body.querySelector('.oa-wizard');
  f.button = text => f.box.querySelectorAll('button').find(n => n.textContent === text);
  return f;
}
test('Korean wizard retains name/city/IME/timezone across locale changes and saves original identity', async () => {
  const f = await wizardFixture();
  assert.match(f.box.textContent, /안녕! 나는 Amika야/);
  const name = f.box.querySelector('input'); name.value = '김하늘'; name.dispatch('input'); name.dispatch('compositionstart'); name.focus();
  f.setLocale('en');
  assert.strictEqual(f.box.querySelector('input'), name); assert.equal(name.value, '김하늘'); assert.equal(name.placeholder, 'your name');
  name.dispatch('keydown', { key: 'Enter', isComposing: true }); assert.strictEqual(f.box.querySelector('input'), name);
  name.dispatch('compositionend'); await f.button("That's me →").click();
  const city = f.box.querySelector('input'), zone = f.box.querySelector('select');
  city.value = '부산'; city.dispatch('input'); zone.value = 'America/Los_Angeles'; city.focus();
  f.setLocale('ko');
  assert.strictEqual(f.box.querySelector('input'), city); assert.equal(city.value, '부산'); assert.equal(zone.value, 'America/Los_Angeles');
  await f.button('여기예요 →').click(); await f.button('설정하기 →').click();
  assert.match(f.box.textContent, /OpenRouter API 키/);
  await f.button('다음 →').click(); await flush();
  assert.match(f.box.textContent, /네 목소리를 들을 수 있는지/); assert.equal(f.button('대화 시작').disabled, false);
  await f.button('대화 시작').click();
  const saved = f.calls.find(c => c?.action === 'persona-identity');
  assert.deepEqual(JSON.parse(JSON.stringify(saved.payload)), { user_name: '김하늘', city: '부산', timezone: 'America/Los_Angeles', onboarded: true });
  assert.equal(f.calls.some(c => c?.action === 'tts-say'), true);
  assert.equal(f.calls.includes('audio-play'), true);
});
test('OpenRouter/Ollama wizard key draft and provider selection survive language switching', async () => {
  const f = await wizardFixture({ transport: 'openrouter' });
  let input = f.box.querySelector('input'); input.value = '테스트'; input.dispatch('input'); await f.button('이 이름이에요 →').click();
  input = f.box.querySelector('input'); input.value = '도시'; input.dispatch('input'); await f.button('여기예요 →').click(); await f.button('설정하기 →').click(); await flush();
  const password = f.box.querySelectorAll('input').find(n => n.getAttribute('type') === 'password');
  password.value = 'synthetic-key-draft'; password.focus();
  const count = f.calls.length; f.setLocale('en');
  assert.equal(password.value, 'synthetic-key-draft'); assert.strictEqual(f.document.activeElement, password);
  assert.equal(f.calls.length, count); assert.match(f.box.textContent, /Ollama does not require an OpenRouter account/);
  f.setLocale('ko'); assert.match(f.box.textContent, /OpenRouter 계정이 필요하지 않습니다/);
});

test('transcript metadata and errors localize but user/model/thought text is never translated', async () => {
  const f = fixture(); await flush();
  f.runSlice('  // ── chat log', '  // ── power / socket');
  f.runSlice('  function handle(msg)', '  // ── latency chart');
  vm.runInContext(`chatAdd('you', 'You', 'Send'); chatAdd('her', 'Amika', '<b>Online</b>', '我心想：原文');
    handle({type: 'ai_error'}); handle({type: 'tts_error', error: 'HTTP 503'});`, f.context);
  const log = f.$('chatLog'), line = log.children[0], modelLine = log.children[1];
  assert.equal(line.textContent, '나Send'); assert.equal(modelLine.textContent, 'Amika<b>Online</b>속마음 · 我心想：原文');
  assert.equal(modelLine.querySelector('b'), null);
  assert.deepEqual(f.toasts, ['응답 중 오류가 발생했습니다.', '음성 합성 오류: HTTP 503']);
  f.setLocale('en');
  assert.strictEqual(log.children[0], line); assert.strictEqual(log.children[1], modelLine);
  assert.equal(line.textContent, 'YouSend'); assert.equal(modelLine.textContent, 'Amika<b>Online</b>Thought · 我心想：原文');
});

test('expert telemetry and camera descriptions render localized copy without interpreting markup', async t => {
  const f = fixture({ telemetry: true });
  t.after(() => vm.runInContext('clearTimeout(statusTimer)', f.context));
  await flush();
  vm.runInContext(`lastUsage = {amika: {dialogues: 2, cost_usd: 1, avg_per_dialogue_usd: .5, cache_unreported_requests: 3}, agents: {requests: 2, cost_usd: .4, avg_per_request_usd: .2}};
    renderUsage(lastUsage);
    ui($('camBtn'), 'cameraSees', 'She sees: {description}', {description: '<img src=x> English description'}, 'title');`, f.context);
  assert.match(f.$('statCostAmikaSub').textContent, /대화당/);
  assert.match(f.$('statCacheSub').textContent, /캐시 정보를 제공하지 않습니다/);
  assert.match(f.$('latLegend').textContent, /음성 인식/);
  assert.equal(f.$('camBtn').title, '보고 있는 내용: <img src=x> English description');
  f.setLocale('en');
  assert.match(f.$('statCostAmikaSub').textContent, /dialogue/);
  assert.match(f.$('latLegend').textContent, /STT/);
  assert.equal(f.$('camBtn').title, 'She sees: <img src=x> English description');
  vm.runInContext('clearTimeout(statusTimer)', f.context);
});

test('wizard health message metadata switches in place without another check', async () => {
  const f = await wizardFixture();
  vm.runInContext(read('ui/locales/common.js'), f.context);
  let checks = 0;
  f.context.OA.healthCheck = async () => {
    checks++;
    return { level: 'err', items: [{ level: 'err', name: 'Brain', detail: 'not answering',
      nameMessage: { key: 'common.health.brain', params: {} }, detailMessage: { key: 'common.health.brainDown', params: {} } }] };
  };
  let input = f.box.querySelector('input'); input.value = '이름'; input.dispatch('input'); await f.button('이 이름이에요 →').click();
  input = f.box.querySelector('input'); input.value = '도시'; input.dispatch('input'); await f.button('여기예요 →').click();
  await f.button('설정하기 →').click(); await f.button('다음 →').click(); await flush();
  const row = f.box.querySelector('.health-row');
  assert.match(row.textContent, /두뇌/); assert.ok(f.button('그래도 시작'));
  f.setLocale('en');
  assert.strictEqual(f.box.querySelector('.health-row'), row); assert.match(row.textContent, /Brain/);
  assert.ok(f.button('Start anyway')); assert.equal(checks, 1);
});
