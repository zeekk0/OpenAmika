/* Synthetic event sequences exercise production handlers, not native IME acceptance. */
const assert = require('node:assert/strict');
const { test } = require('node:test');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname, '../ui/use.js'), 'utf8');

class Element {
  constructor(value = '') { this.value = value; this.listeners = new Map(); this.disabled = false; }
  addEventListener(type, fn) {
    const listeners = this.listeners.get(type) || [];
    listeners.push(fn);
    this.listeners.set(type, listeners);
  }
  dispatch(type, props = {}) {
    const event = { type, defaultPrevented: false, ...props,
      preventDefault() { this.defaultPrevented = true; } };
    for (const fn of this.listeners.get(type) || []) fn(event);
    return event;
  }
  click() { if (!this.disabled) this.dispatch('click'); }
}

function fixture(target = 'chat') {
  const elements = { sayInput: new Element(), sayForm: new Element() };
  const sent = [], advances = [];
  const socket = { readyState: 1, send(text) { sent.push(JSON.parse(text)); } };
  const context = vm.createContext({
    $: id => elements[id], ws: socket, state: { name: '', city: '', sayAs: '', tz: 'Asia/Seoul' },
    el: (_tag, attrs = {}) => new Element(attrs.value || ''),
    button: (_text, onclick) => { const b = new Element(); b.addEventListener('click', onclick); return b; },
    go: n => advances.push(n), previewName() {}, zones: [], voiceAvailable: true,
  });
  // Execute the shipped outgoing block, including any shared helper, without starting the app.
  const outgoing = source.slice(source.indexOf('  // ── outgoing text / controls'),
    source.indexOf('  $("stopBtn").addEventListener'));
  vm.runInContext(outgoing, context);
  let input = elements.sayInput, next;
  if (target !== 'chat') {
    const start = source.indexOf(target === 'name'
      ? '        const input = el("input", { type: "text", maxlength: "40"'
      : '        const city = el("input", { type: "text", maxlength: "80"');
    const endMarker = target === 'name' ? '        sync();' : '        next.disabled = !state.city;';
    const end = source.indexOf(endMarker, start) + endMarker.length;
    assert.ok(start >= 0 && end > start, 'onboarding source block found');
    vm.runInContext(source.slice(start, end) + `\nthis.input = ${target === 'name' ? 'input' : 'city'}; this.next = next;`, context);
    input = context.input; next = context.next;
  }
  return {
    input, socket, sent, advances, context,
    count: () => target === 'chat' ? sent.length : advances.length,
    value(text) { input.value = text; input.dispatch('input'); },
    enter(props = {}) {
      const event = input.dispatch('keydown', { key: 'Enter', code: 'Enter', isComposing: false, keyCode: 13, ...props });
      // Model only the native implicit form default. Synthetic dispatch cannot supply it.
      if (target === 'chat' && !event.defaultPrevented) elements.sayForm.dispatch('submit');
      return event;
    },
    click() { if (target === 'chat') elements.sayForm.dispatch('submit'); else next.click(); },
    submit() { elements.sayForm.dispatch('submit'); },
  };
}

for (const target of ['chat', 'name', 'city']) {
  test(`${target}: isComposing alone suppresses confirming Enter`, () => {
    const f = fixture(target); f.value('안녕하세요');
    assert.equal(f.enter({ isComposing: true }).defaultPrevented, true);
    assert.equal(f.count(), 0); assert.equal(f.input.value, '안녕하세요');
    f.input.dispatch('keyup', { key: 'Enter' });
    f.enter(); assert.equal(f.count(), 1);
  });
  test(`${target}: composition state protects missing keyboard flag, then next Enter works`, () => {
    const f = fixture(target); f.value('민수');
    f.input.dispatch('compositionstart');
    f.enter(); assert.equal(f.count(), 0);
    f.input.dispatch('compositionend');
    f.input.dispatch('keyup', { key: 'Enter' });
    f.enter(); assert.equal(f.count(), 1);
  });
  test(`${target}: end-before-keydown with 229 does not advance`, () => {
    const f = fixture(target); f.value('서울');
    f.input.dispatch('compositionstart'); f.input.dispatch('compositionend');
    f.enter({ keyCode: 229 }); assert.equal(f.count(), 0);
    f.input.dispatch('keyup', { key: 'Enter' });
    f.enter(); assert.equal(f.count(), 1);
  });
  test(`${target}: mouse immediately after composition sends exactly once`, () => {
    const f = fixture(target); f.value('한국어');
    f.input.dispatch('compositionstart'); f.enter({ isComposing: true });
    assert.equal(f.count(), 0);
    f.input.dispatch('compositionend');
    f.click(); assert.equal(f.count(), 1);
    f.input.dispatch('keypress', { key: 'Enter' });
    f.input.dispatch('keyup', { key: 'Enter' });
    assert.equal(f.count(), 1);
  });
  test(`${target}: held confirming Enter cannot advance after composition ends`, () => {
    const f = fixture(target); f.value('한국어');
    f.input.dispatch('compositionstart'); f.enter({ isComposing: true });
    f.input.dispatch('compositionend');
    f.enter({ repeat: true }); assert.equal(f.count(), 0);
    f.input.dispatch('keyup', { key: 'Enter' }); f.enter(); assert.equal(f.count(), 1);
  });
  test(`${target}: ordinary keys and empty values preserve behavior`, () => {
    const f = fixture(target);
    f.value('   '); f.enter(); assert.equal(f.count(), 0);
    f.value('hello');
    assert.equal(f.input.dispatch('keydown', { key: 'a' }).defaultPrevented, false);
    f.enter(); assert.equal(f.count(), 1);
  });
  test(`${target}: blur clears abandoned composition state`, () => {
    const f = fixture(target); f.value('hello');
    f.input.dispatch('compositionstart'); f.input.dispatch('blur');
    f.enter(); assert.equal(f.count(), 1);
  });
  test(`${target}: only the final committed value reaches the action`, () => {
    const f = fixture(target); f.value('서우');
    f.input.dispatch('compositionstart');
    f.enter({ isComposing: true });
    assert.equal(f.input.value, '서우'); assert.equal(f.count(), 0);
    f.input.dispatch('compositionend'); f.value('  서울  ');
    f.input.dispatch('keyup', { key: 'Enter' });
    f.enter(); assert.equal(f.count(), 1);
    if (target === 'chat') {
      assert.deepEqual(f.sent, [{ type: 'text', text: '서울' }]);
      assert.equal(f.input.value, '');
    } else {
      assert.equal(f.context.state[target], '서울');
      assert.deepEqual(f.advances, [target === 'name' ? 1 : 2]);
    }
  });
}

test('chat: exact payload, reset only after send, duplicate submit is empty', () => {
  const f = fixture(); f.value('  안녕하세요  ');
  f.enter(); f.submit();
  assert.deepEqual(f.sent, [{ type: 'text', text: '안녕하세요' }]);
  assert.equal(f.input.value, '');
});
test('chat: composition blocks direct form submission without clearing', () => {
  const f = fixture(); f.value('한국어'); f.input.dispatch('compositionstart');
  f.submit(); assert.equal(f.count(), 0); assert.equal(f.input.value, '한국어');
  f.input.dispatch('compositionend'); f.click(); assert.equal(f.count(), 1);
});
test('chat: disconnected, missing and failing sockets retain input', () => {
  const f = fixture(); f.value('한국어');
  f.socket.readyState = 3; f.enter(); assert.equal(f.count(), 0); assert.equal(f.input.value, '한국어');
  f.context.ws = null; f.click(); assert.equal(f.input.value, '한국어');
  f.context.ws = { readyState: 1, send() { throw new Error('closed'); } };
  assert.throws(() => f.click(), /closed/); assert.equal(f.input.value, '한국어');
  f.context.ws = f.socket; f.socket.readyState = 1; f.click(); assert.equal(f.count(), 1);
});
test('chat: composition on another input does not block the main field', () => {
  const f = fixture('name'); f.input.dispatch('compositionstart');
  vm.runInContext('$("sayInput").value = "hello"; $("sayForm").dispatch("submit");', f.context);
  assert.equal(f.sent.length, 1);
});
