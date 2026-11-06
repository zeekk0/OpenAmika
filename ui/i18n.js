/* Explicit UI translations only. Locale never changes conversation settings. */
(function () {
  'use strict';
  const STORAGE_KEY = 'openamika-ui-locale';
  const catalogs = {en: Object.create(null), ko: Object.create(null)};
  const valid = value => value === 'en' || value === 'ko';
  const detected = () => {
    for (const candidate of [...(navigator.languages || []), navigator.language]) {
      const language = String(candidate || '').toLowerCase().split('-')[0];
      if (valid(language)) return language;
    }
    return 'en';
  };
  let locale = detected();
  try { const saved = localStorage.getItem(STORAGE_KEY); if (valid(saved)) locale = saved; } catch (_) {}
  const placeholders = text => [...new Set(text.match(/\{[A-Za-z_][A-Za-z0-9_]*\}/g) || [])].sort().join(',');
  function register(bundle) {
    const en = bundle.en || {}, ko = bundle.ko || {};
    if (Object.keys(en).sort().join('\n') !== Object.keys(ko).sort().join('\n')) throw Error('Locale key sets must match');
    for (const key of Object.keys(en)) {
      if (typeof en[key] !== 'string' || typeof ko[key] !== 'string' || placeholders(en[key]) !== placeholders(ko[key])) {
        throw Error('Locale placeholders must match: ' + key);
      }
    }
    Object.assign(catalogs.en, en); Object.assign(catalogs.ko, ko);
  }
  // Returns plain text, not trusted HTML. Render using textContent/setAttribute.
  const missingKeys = new Set();
  function t(key, params = {}) {
    if (catalogs[locale][key] === undefined && missingKeys.size < 50 && !missingKeys.has(key)) {
      missingKeys.add(key);
      // Only bounded identifier-shaped keys, never params or arbitrary user text.
      const diagnosticKey = /^[A-Za-z0-9_.-]{1,120}$/.test(String(key)) ? String(key) : '[invalid key]';
      console.warn('Missing UI translation:', locale, diagnosticKey);
    }
    const text = catalogs[locale][key] ?? catalogs.en[key] ?? String(key);
    return text.replace(/\{([A-Za-z_][A-Za-z0-9_]*)\}/g, (token, name) =>
      Object.prototype.hasOwnProperty.call(params, name) ? String(params[name]) : token);
  }
  const attributes = ['title', 'placeholder', 'aria-label', 'alt'];
  const selector = ['[data-i18n]', ...attributes.map(a => '[data-i18n-' + a + ']')].join(',');
  function translate(root = document) {
    const nodes = [...(root.querySelectorAll?.(selector) || [])];
    if (root.getAttribute) nodes.unshift(root);
    for (const node of nodes) {
      const key = node.getAttribute('data-i18n');
      // Never overwrite editable values, child controls or composed IME input.
      if (key && !['INPUT', 'TEXTAREA', 'SELECT'].includes(node.tagName) && !node.isContentEditable && !node.children?.length) {
        node.textContent = t(key);
      }
      for (const attribute of attributes) {
        const attrKey = node.getAttribute('data-i18n-' + attribute);
        if (attrKey) node.setAttribute(attribute, t(attrKey));
      }
    }
  }
  function apply(next, persist) {
    if (!valid(next)) return locale;
    if (persist) { try { localStorage.setItem(STORAGE_KEY, next); } catch (_) {} }
    const changed = locale !== next;
    locale = next;
    document.documentElement.setAttribute('lang', locale);
    translate();
    if (changed) window.dispatchEvent(new CustomEvent('oa:localechange', {detail: {locale}}));
    return locale;
  }
  window.OAI18n = {register, t, getLocale: () => locale, setLocale: next => apply(next, true), translate};
  document.documentElement.setAttribute('lang', locale);
  window.addEventListener('storage', event => {
    if (event.key === STORAGE_KEY || event.key === null) apply(valid(event.newValue) ? event.newValue : detected(), false);
  });
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', () => translate());
  else translate();
})();
