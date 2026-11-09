const assert = require('node:assert/strict');
const {test} = require('node:test');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const source = file => fs.readFileSync(path.join(__dirname, '..', file), 'utf8');
function node(attrs = {}, children = []) {
  return {attrs, children, tagName: 'SPAN', textContent: 'original', value: '한글 조합',
    getAttribute(k) { return this.attrs[k] ?? null; }, setAttribute(k,v) { this.attrs[k] = String(v); },
    querySelectorAll() { return children; }};
}
function fixture({stored = null, language = 'en-US', languages, blocked = false} = {}) {
  const listeners = {}, writes = [], nodes = [], warnings = [], html = node();
  const document = {documentElement: html, readyState: 'complete', querySelectorAll: () => nodes,
    addEventListener(name, fn) { listeners[name] = fn; }};
  const context = vm.createContext({document, navigator: {language, languages}, console: {warn: (...args)=>warnings.push(args)},
    localStorage: {getItem() { if (blocked) throw Error('blocked'); return stored; },
      setItem(k,v) { if (blocked) throw Error('blocked'); writes.push([k,v]); stored=v; }},
    CustomEvent: class { constructor(type, init) { this.type=type; this.detail=init.detail; } },
    addEventListener(name, fn) { listeners[name]=fn; }, dispatchEvent(event) { listeners[event.type]?.(event); }});
  context.window = context;
  vm.runInContext(source('ui/i18n.js'), context);
  return {api:context.OAI18n, context, nodes, html, writes, listeners, warnings};
}
test('locale detection, explicit persistence, invalid and blocked storage', () => {
  assert.equal(fixture({language:'ko-KR'}).api.getLocale(), 'ko');
  assert.equal(fixture({language:'ja-JP'}).api.getLocale(), 'en');
  assert.equal(fixture({stored:'en',language:'ko-KR'}).api.getLocale(), 'en');
  assert.equal(fixture({stored:'bad',language:'ko-KR'}).api.getLocale(), 'ko');
  const f=fixture({blocked:true,language:'ko-KR'}); f.api.setLocale('en'); assert.equal(f.api.getLocale(),'en');
  f.api.setLocale('xx'); assert.equal(f.api.getLocale(),'en');
});
test('events, html language, persistence and cross-tab synchronization', () => {
  const f=fixture(); const events=[]; f.listeners['oa:localechange']=e=>events.push(e.detail.locale);
  f.api.setLocale('ko'); assert.equal(f.html.attrs.lang,'ko'); assert.deepEqual(events,['ko']);
  assert.deepEqual(f.writes,[['openamika-ui-locale','ko']]);
  f.listeners.storage({key:'openamika-ui-locale',newValue:'en'});
  assert.equal(f.api.getLocale(),'en'); assert.deepEqual(events,['ko','en']); assert.equal(f.writes.length,1);
});
test('tagged text and attributes, root itself, safe interpolation, preservation', () => {
  const f=fixture(); f.api.register({en:{'x.text':'Hello {name}','x.attr':'Type here'},ko:{'x.text':'안녕 {name}','x.attr':'입력하세요'}});
  const tagged=node({'data-i18n':'x.attr'}), input=node({'data-i18n-placeholder':'x.attr','data-i18n-title':'x.attr','data-i18n-aria-label':'x.attr','data-i18n-alt':'x.attr'});
  input.tagName='INPUT'; const untouched=node(); f.nodes.push(tagged,input,untouched);
  f.api.setLocale('ko'); assert.equal(tagged.textContent,'입력하세요'); assert.equal(untouched.textContent,'original');
  assert.equal(input.value,'한글 조합'); for(const a of ['placeholder','title','aria-label','alt']) assert.equal(input.attrs[a],'입력하세요');
  const payload='<img src=x onerror=alert(1)>'; assert.equal(f.api.t('x.text',{name:payload}),'안녕 '+payload);
  const root=node({'data-i18n':'x.text'}); f.api.translate(root); assert.equal(root.textContent,'안녕 {name}');
  f.api.register({en:{'x.attack':payload},ko:{'x.attack':payload}}); root.attrs['data-i18n']='x.attack'; f.api.translate(root);
  assert.equal(root.textContent,payload); assert.equal(root.innerHTML,undefined); assert.equal(f.api.t('absent'),'absent');
});
test('catalog registration rejects mismatched keys/placeholders atomically', () => {
  const f=fixture(); assert.throws(()=>f.api.register({en:{x:'{name}'},ko:{x:'{other}'}}));
  assert.throws(()=>f.api.register({en:{x:'x'},ko:{y:'y'}})); assert.equal(f.api.t('x'),'x');
  f.api.register({en:{x:'Original'},ko:{x:'원문'}});
  assert.throws(()=>f.api.register({en:{x:'Replacement',y:'{name}'},ko:{x:'교체',y:'{other}'}}));
  assert.equal(f.api.t('x'),'Original'); assert.equal(f.api.t('y'),'y');
});
test('production common catalog has matching keys and every common reference', () => {
  const f=fixture(); vm.runInContext(source('ui/locales/common.js'),f.context);
  const common=source('ui/common.js');
  for(const key of new Set(common.match(/common\.[A-Za-z0-9_.]+/g))) assert.notEqual(f.api.t(key),key,key);
  f.api.setLocale('ko'); assert.equal(f.api.t('common.nav.setup'),'설정');
});

function commonFixture() {
  const f = fixture({language:'ko-KR'}), calls=[];
  const classList={add(){},remove(){},toggle(){}};
  f.html.classList=classList;
  const elements={navHealth:node(),navHealthLabel:node(),navHealthLight:node(),oaLocale:node()};
  f.context.document.getElementById=id=>elements[id] || null;
  f.context.document.createElement=tag=>Object.assign(node(),{tagName:tag.toUpperCase(),classList,
    append(...children){this.children.push(...children);},addEventListener(){},replaceChildren(){this.children=[];}});
  f.context.document.body={append(){}};
  f.context.setTimeout=()=>1; f.context.clearTimeout=()=>{};
  f.context.fetch=async url=>{ calls.push(url); return {ok:true,json:async()=> url==='/health' ? {cuda_available:false} : {}}; };
  vm.runInContext(source('ui/locales/common.js'),f.context);
  vm.runInContext(source('ui/common.js'),f.context);
  return {...f,calls,elements,oa:f.context.OA};
}
test('full common module localizes health and switches without network or page rebuild', async () => {
  const f=commonFixture(); const result=await f.oa.healthCheck();
  assert.ok(result.items.some(i=>i.name==='음성 / 음성 인식' && /CPU/.test(i.detail)));
  assert.ok(f.calls.includes('/api/tts_probe'));
  assert.ok(result.items.some(i=>i.name==='Live2D 모델' && i.level==='err'));
  const count=f.calls.length, form=node({'data-i18n-placeholder':'common.language'});
  form.tagName='INPUT'; form.isComposing=true; form.selectionStart=3; f.nodes.push(form);
  f.api.setLocale('en');
  assert.equal(f.calls.length,count); assert.equal(form.value,'한글 조합'); assert.equal(form.isComposing,true);
  assert.equal(form.selectionStart,3); assert.equal(f.elements.oaLocale.value,'en');
  assert.ok(result.items.some(i=>i.name==='Speech / STT'));
  assert.equal(f.elements.navHealthLabel.textContent,'System Failures');
});
test('common numeric formatters use selected UI locale rather than browser default', () => {
  const f=commonFixture();
  // Korean and English group these values identically, so observe the actual locale argument.
  vm.runInContext("Number.prototype.toLocaleString = function(locale) { return locale + ':' + this; }",f.context);
  assert.equal(f.oa.fmt.int(1234.6),'ko:1235');
  assert.equal(f.oa.fmt.ms(1234.6),'ko:1235 ms');
  f.api.setLocale('en');
  assert.equal(f.oa.fmt.int(1234.6),'en:1235');
  assert.equal(f.oa.fmt.ms(1234.6),'en:1235 ms');
  assert.equal(f.oa.fmt.int(NaN),'—');
  assert.equal(f.oa.fmt.ms(Infinity),'—');
});
test('full common errors retain status/code and display untrusted details as text', async () => {
  const f=commonFixture(), payload='<img src=x onerror=alert(1)>';
  f.context.fetch=async()=>({ok:false,status:403,json:async()=>({detail:{code:'iot_disclaimer_required',message:payload}})});
  await assert.rejects(f.oa.postAction('/fake','save',{}), error=>{
    assert.equal(error.status,403); assert.equal(error.code,'iot_disclaimer_required');
    assert.equal(error.detail,payload); assert.match(error.message,/동의/); assert.ok(!error.message.includes(payload)); return true;
  });
  f.context.fetch=async()=>{throw Error('network');};
  await assert.rejects(f.oa.getJSON('/fake'), /연결할 수 없습니다/);
  f.context.fetch=async()=>({ok:true,json:async()=>{throw SyntaxError('Unexpected token');}});
  await assert.rejects(f.oa.getJSON('/fake'), /응답을 읽을 수 없습니다/);
});
test('browser preference order selects first supported language before primary fallback', () => {
  assert.equal(fixture({language:'en-US',languages:['fr-FR','ko-KR','en-US']}).api.getLocale(),'ko');
  assert.equal(fixture({language:'ko-KR',languages:['en-GB','ko-KR']}).api.getLocale(),'en');
  assert.equal(fixture({language:'ko-KR',languages:['fr-FR']}).api.getLocale(),'ko');
  assert.equal(fixture({language:'fr-FR',languages:['ja-JP']}).api.getLocale(),'en');
});
test('missing-key warnings are deduplicated, bounded, and never log interpolation params', () => {
  const f=fixture(), secret='sk-provider-secret';
  f.api.t('missing.key',{secret}); f.api.t('missing.key',{secret}); assert.equal(f.warnings.length,1);
  for(let n=0;n<200;n++) f.api.t('missing.key'+n,{secret});
  assert.ok(f.warnings.length<=50); assert.ok(!JSON.stringify(f.warnings).includes(secret));
  assert.ok(JSON.stringify(f.warnings[0]).includes('missing.key'));
});
test('common failures choose safe messages by code/status and preserve machine diagnostics', async () => {
  const f=commonFixture(), secret='sk-secret /Users/private/brain/.env provider traceback';
  for(const [status,code,pattern] of [[401,'unauthorized',/인증/],[403,'forbidden',/권한/],[429,'rate_limit',/잠시/],
    [408,'timeout',/시간/],[504,'timeout',/시간/],[409,'conflict',/상태/],[400,'bad_request',/입력/],
    [500,'provider_error',/서버/],[503,'unavailable',/서버/],[400,'audio_disabled',/음성/],
    [400,'unauthorized',/인증/],[400,'rate_limit',/잠시/],[418,'unknown_code',/HTTP 418/]]) {
    f.context.fetch=async()=>({ok:false,status,json:async()=>({detail:{code,message:secret}})});
    await assert.rejects(f.oa.getJSON('/fake'),error=>{
      assert.equal(error.status,status); assert.equal(error.code,code); assert.equal(error.detail,secret);
      assert.match(error.message,pattern); assert.ok(!error.message.includes(secret)); return true;
    });
  }
});
test('tagged editable containers and nested controls are not destroyed', () => {
  const f=fixture(); f.api.register({en:{x:'English'},ko:{x:'한국어'}});
  const child=node(), parent=node({'data-i18n':'x'},[child]), edit=node({'data-i18n':'x'});
  edit.isContentEditable=true; f.nodes.push(parent,edit); f.api.setLocale('ko');
  assert.equal(parent.children[0],child); assert.equal(parent.textContent,'original'); assert.equal(edit.textContent,'original');
});
test('storage clears restore navigator default and repeated selection emits no duplicate event', () => {
  const f=fixture({stored:'en',language:'ko-KR'}), events=[];
  f.listeners['oa:localechange']=e=>events.push(e.detail.locale);
  f.api.setLocale('en'); assert.equal(events.length,0);
  f.listeners.storage({key:'unrelated',newValue:'ko'}); assert.equal(f.api.getLocale(),'en');
  f.listeners.storage({key:'openamika-ui-locale',newValue:null}); assert.equal(f.api.getLocale(),'ko');
  f.listeners.storage({key:null,newValue:null}); assert.deepEqual(events,['ko']);
  assert.equal(f.writes.length,1);
});
test('attribute translations are literal, never expanded into markup or executable attributes', () => {
  const f=fixture(), attack='" onfocus="alert(1)';
  f.api.register({en:{x:attack},ko:{x:attack}});
  const input=node({'data-i18n-placeholder':'x','data-i18n-onclick':'x','data-i18n-href':'x'});
  f.api.translate(input); assert.equal(input.attrs.placeholder,attack);
  assert.equal(input.attrs.onclick,undefined); assert.equal(input.attrs.href,undefined);
});
