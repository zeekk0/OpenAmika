/* OpenAmika UI — shared chrome (nav, toast, fetch helpers). */
(function () {
  "use strict";
  document.documentElement.classList.add("js");
  const tr = (key, fallback, params = {}) => typeof OAI18n !== "undefined" ? OAI18n.t(key, params) : fallback;

  const SAKURA = `<svg class="oa-sakura" viewBox="0 0 100 100" aria-hidden="true">
    <g fill="#f4a8c1">
      <ellipse cx="50" cy="26" rx="11" ry="17" transform="rotate(0 50 50)"/>
      <ellipse cx="50" cy="26" rx="11" ry="17" transform="rotate(72 50 50)"/>
      <ellipse cx="50" cy="26" rx="11" ry="17" transform="rotate(144 50 50)"/>
      <ellipse cx="50" cy="26" rx="11" ry="17" transform="rotate(216 50 50)"/>
      <ellipse cx="50" cy="26" rx="11" ry="17" transform="rotate(288 50 50)"/>
      <circle cx="50" cy="50" r="7" fill="#c8385a"/>
    </g></svg>`;

  // Simple / Professional UI mode — pure CSS gating via a class on <html>.
  function uiMode() {
    let mode = "simple";
    try { mode = localStorage.getItem("openamika-ui-mode") || "simple"; } catch (_) {}
    return mode === "pro" ? "pro" : "simple";
  }
  function applyMode(mode) {
    document.documentElement.classList.remove("mode-simple", "mode-pro");
    document.documentElement.classList.add("mode-" + mode);
    try { localStorage.setItem("openamika-ui-mode", mode); } catch (_) {}
    document.querySelectorAll(".oa-mode button").forEach((b) =>
      b.classList.toggle("active", b.dataset.mode === mode));
  }
  applyMode(uiMode());

  function nav(active) {
    const el = document.createElement("nav");
    el.className = "oa-nav";
    el.innerHTML = `
      <a class="oa-wordmark" href="/use" aria-label="OpenAmika home" data-i18n-aria-label="common.nav.home">
        ${SAKURA}
        <span class="mark-name">Open<em>Amika</em></span>
        <span class="mark-jp">オープン・アミカ</span>
      </a>
      <div class="oa-nav-links">
        <a href="/setup" data-page="setup" data-i18n="common.nav.setup">Setup</a>
        <a href="/tools" data-page="tools" data-i18n="common.nav.tools">Tools</a>
        <a href="/use" data-page="use" data-i18n="common.nav.use">Use</a>
        <a href="/about" data-page="about" data-i18n="common.nav.about">About</a>
      </div>
      <div style="display:flex;align-items:center;">
        <label class="oa-language"><span class="oa-sr-only" data-i18n="common.language">Interface language</span>
          <select id="oaLocale" data-i18n-aria-label="common.language" aria-label="Interface language">
            <option value="en" lang="en" data-i18n="common.language.en">English</option>
            <option value="ko" lang="ko" data-i18n="common.language.ko">한국어</option>
          </select>
        </label>
        <div class="oa-mode" data-i18n-title="common.mode.help" title="Simple hides the expert controls; Professional shows everything">
          <button type="button" data-mode="simple" data-i18n="common.mode.simple">Simple</button>
          <button type="button" data-mode="pro" data-i18n="common.mode.pro">Professional</button>
        </div>
        <button type="button" class="oa-health" id="navHealth" aria-haspopup="true" aria-expanded="false" title="System health">
          <span class="light" id="navHealthLight"></span><span class="label" id="navHealthLabel">Checking…</span>
        </button>
      </div>`;
    el.querySelectorAll("a[data-page]").forEach((a) => {
      if (a.dataset.page === active) a.classList.add("active");
    });
    el.querySelectorAll(".oa-mode button").forEach((b) =>
      b.addEventListener("click", () => applyMode(b.dataset.mode)));
    document.body.prepend(el);
    const picker = el.querySelector("#oaLocale");
    if (picker && typeof OAI18n !== "undefined") {
      picker.value = OAI18n.getLocale();
      picker.addEventListener("change", () => OAI18n.setLocale(picker.value));
      OAI18n.translate(el);
    }
    applyMode(uiMode());
    startHealth();
  }

  function footer() {
    const el = document.createElement("footer");
    el.className = "oa-footer";
    el.innerHTML = `
      <div class="links">
        <a href="/setup" data-i18n="common.nav.setup">Setup</a>
        <a href="/tools" data-i18n="common.nav.tools">Tools</a>
        <a href="/use" data-i18n="common.nav.use">Use</a>
        <a href="/flow" data-i18n="common.nav.flow">System flow</a>
        <a href="/about" data-i18n="common.nav.support">About &amp; support</a>
        <a href="https://github.com/zeekk0/OpenAmika" rel="noopener" target="_blank">GitHub</a>
      </div>
      <p class="fine" data-i18n="common.footer">OpenAmika · an open companion · locally yours</p>`;
    document.body.append(el);
    if (typeof OAI18n !== "undefined") OAI18n.translate(el);
  }

  let toastEl = null, toastTimer = null;
  function toast(message, isError) {
    if (!toastEl) {
      toastEl = document.createElement("div");
      toastEl.className = "oa-toast";
      document.body.append(toastEl);
    }
    toastEl.textContent = message;
    toastEl.classList.toggle("err", !!isError);
    toastEl.classList.add("show");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => toastEl.classList.remove("show"), isError ? 6000 : 3200);
  }

  // a refusal's detail is a sentence, or {code, message} when the page should react to it (e.g. the IoT safety
  // statement: code "iot_disclaimer_required"); the Error carries .status and .code either way
  function refusal(payload, status, fallback) {
    const detail = payload && payload.detail;
    const structured = detail && typeof detail === "object";
    const raw = (structured ? detail.message : detail) || (payload && payload.error);
    const code = (structured && detail.code) || (payload && payload.code) || null;
    const codes = {audio_disabled: "common.error.audioDisabled", iot_disclaimer_required: "common.error.consent",
      unauthorized: "common.error.auth", forbidden: "common.error.forbidden", rate_limit: "common.error.rate",
      timeout: "common.error.timeout", conflict: "common.error.conflict", bad_request: "common.error.input",
      provider_error: "common.error.server"};
    const statuses = {400: "common.error.input", 401: "common.error.auth", 403: "common.error.forbidden",
      408: "common.error.timeout", 409: "common.error.conflict", 429: "common.error.rate", 504: "common.error.timeout"};
    const key = Object.prototype.hasOwnProperty.call(codes, code) ? codes[code]
      : statuses[status] || (status >= 500 ? "common.error.server" : "common.error.http");
    // Raw backend diagnostics remain machine-readable, never user-facing prose.
    const error = new Error(tr(key, fallback, {status}));
    error.detail = raw;
    error.status = status;
    error.code = code;
    return error;
  }

  async function getJSON(url) {
    let response;
    try { response = await fetch(url, { cache: "no-store" }); }
    catch (_) { throw new Error(tr("common.error.network", "Cannot connect. Check that the app is running.")); }
    if (!response.ok) {
      let payload = null;
      try { payload = await response.json(); } catch (_) {}
      throw refusal(payload, response.status, tr("common.error.http", `HTTP ${response.status}`, {status: response.status}));
    }
    try { return await response.json(); }
    catch (_) { throw new Error(tr("common.error.response", "Cannot read the response. Try again.")); }
  }

  async function postAction(url, action, body) {
    let response;
    try { response = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-Build-F-Action": action },
      body: JSON.stringify(body || {}),
    }); } catch (_) { throw new Error(tr("common.error.network", "Cannot connect. Check that the app is running.")); }
    let payload = null;
    try { payload = await response.json(); } catch (_) {}
    if (!response.ok) throw refusal(payload, response.status, tr("common.error.http", `HTTP ${response.status}`, {status: response.status}));
    return payload;
  }

  function el(tag, attrs, ...children) {
    const node = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs || {})) {
      if (k === "class") node.className = v;
      else if (k === "text") node.textContent = v;
      else if (k.startsWith("on") && typeof v === "function") node.addEventListener(k.slice(2), v);
      else if (v !== null && v !== undefined) node.setAttribute(k, v);
    }
    for (const child of children) {
      if (child === null || child === undefined) continue;
      node.append(child.nodeType ? child : document.createTextNode(String(child)));
    }
    return node;
  }

  // ── system health: the one light at the top right (green / yellow / breathing red), like the launcher's
  // console lights. Click it for the list of what is wrong. Every page shares this poll.
  const LEVEL_RANK = { ok: 0, warn: 1, err: 2 };
  const LEVEL_LABEL = { ok: "System Ready", warn: "Warnings", err: "System Failures" };
  const LEVEL_KEY = { ok: "common.health.ok", warn: "common.health.warn", err: "common.health.err" };
  const health = { level: null, items: [], listeners: new Set(), timer: null, pop: null };

  async function healthCheck() {
    // This function is also exercised alone by the legacy extracted-script harness.
    // Keep its English fallback local, while full-page tests require real catalogs.
    const msg = (key, fallback, params = {}) => ({key, fallback, params});
    const text = value => typeof value === "object" && value !== null && value.key
      ? (typeof OAI18n !== "undefined" ? OAI18n.t(value.key, value.params) : value.fallback) : value;
    const items = [];
    const add = (level, name, detail) => items.push({ level, name: text(name), detail: text(detail), nameMessage: name, detailMessage: detail });
    // brain (via the gateway's proxy): templates and memory
    try {
      const s = await getJSON("/api/build_f/status");
      const checks = s.template_check || {};
      const problems = Object.values(checks).reduce((a, list) => a + (Array.isArray(list) ? list.length : 0), 0);
      add(problems ? "warn" : "ok", msg("common.health.brain", "Brain"), problems ? msg("common.health.templates", problems + " template warning(s). Setup → Personality", {count: problems}) : (s.app || msg("common.health.online", "online")));
      const memory = s.memory || {};
      if (memory.degraded) add("warn", msg("common.health.memory", "Memory"), msg("common.health.degraded", "running degraded. See Setup → System health"));
      else add("ok", msg("common.health.memory", "Memory"), (memory.events != null ? msg("common.health.conversations", memory.events + " conversations", {count: memory.events}) : msg("common.health.available", "ready")));
    } catch (error) { add("err", msg("common.health.brain", "Brain"), msg("common.health.brainDown", "not answering. Is the brain running? (launch.py)")); }
    // Check only the providers selected by her roles.
    let usesCloud = true, usesOllama = false, localModels = [];
    try {
      const m = await getJSON("/api/build_f/models");
      const roles = ["surface", "deep", "reflection", "memory_write"];
      const kinds = roles.map((role) => { const item = ((m.options || {})[role] || []).find((o) => o.key === (m.selections || {})[role]); return item ? item.transport : "openrouter"; });
      usesCloud = kinds.includes("openrouter");
      usesOllama = kinds.includes("ollama");
      localModels = roles.filter((_, i) => kinds[i] === "ollama").map((role) => { const item = (m.options[role] || []).find((o) => o.key === m.selections[role]); return item ? item.model : ""; });
    } catch (_) {}
    if (usesCloud) {
      try {
        const k = await getJSON("/api/build_f/openrouter_key");
        add(k.present ? "ok" : "err", msg("common.health.openrouter", "OpenRouter key"), k.present ? msg("common.health.saved", "saved " + (k.hint || ""), {hint: k.hint || ""}) : msg("common.health.routerMissing", "no key saved. Setup → Brain (or switch to Ollama)"));
      } catch (_) { /* the brain row already says it is down */ }
    }
    if (usesOllama) {
      try {
        const o = await getJSON("/api/build_f/ollama");
        const have = new Set((o.models || []).map((x) => x.name));
        const missing = Array.from(new Set(localModels)).filter((name) => name && !have.has(name));
        if (!o.reachable) add("err", msg("common.health.ollama", "Ollama (local brain)"), msg("common.health.ollamaDown", "not answering at " + o.base_url + ". Start Ollama", {url: o.base_url}));
        else if (missing.length) add("warn", msg("common.health.ollama", "Ollama (local brain)"), msg("common.health.modelsMissing", "model(s) no longer detected: " + missing.join(", ") + ". Setup → Brain → Detect", {models: missing.join(", ")}));
        else add("ok", msg("common.health.ollama", "Ollama (local brain)"), (o.live_version ? "v" + o.live_version + " · " : "") + Array.from(new Set(localModels)).join(", "));
      } catch (_) { add("err", msg("common.health.ollama", "Ollama (local brain)"), msg("common.health.unavailable", "status unavailable")); }
    }
    // Speech / STT
    try {
      const h = await getJSON("/health");
      add(h.cuda_available ? "ok" : "warn", msg("common.health.speech", "Speech / STT"), h.cuda_available ? (h.gpu_name || "cuda") : msg("common.health.cpu", "running on CPU (slow)"));
    } catch (_) { add("err", msg("common.health.speech", "Speech / STT"), msg("common.health.gatewayDown", "gateway not answering")); }
    // TTS
    try {
      const p = await getJSON("/api/tts_probe");
      add(p.ok ? "ok" : "err", msg("common.health.tts", "TTS (her voice)"), p.ok ? p.url : msg("common.health.ttsDown", "unreachable at " + p.url + ". See logs/tts.log and voice setup guide", {url: p.url}));
    } catch (_) { add("err", msg("common.health.tts", "TTS (her voice)"), msg("common.health.probeFailed", "probe failed")); }
    // her Live2D model: the Use page's stage needs one; scripts/setup_tts.py installs hers together with her voice
    try {
      const a = await getJSON("/api/avatar/models");
      const mine = (a.models || []).filter((m) => m.role !== "agent");
      add(mine.length ? "ok" : "err", msg("common.health.avatar", "Live2D model"), mine.length ? mine.map((m) => m.name).join(", ")
        : msg("common.health.avatarMissing", "none in avatar/models/. Run scripts/setup_tts.py in the brain environment, then reload"));
    } catch (_) { add("err", msg("common.health.avatar", "Live2D model"), msg("common.health.avatarUnknown", "model list unavailable")); }
    // the launcher's pre-flight: whatever was not green when the stack started
    try {
      const p = await getJSON("/api/preflight");
      for (const c of (p.checks || [])) {
        if (c.level && c.level !== "ok") add(c.level === "err" ? "err" : "warn", msg("common.health.startup", "Startup: " + c.name, {name: c.name}), c.detail || "");
      }
    } catch (_) {}
    // messengers (optional): only a configured bot that cannot connect is a warning
    try {
      const m = await getJSON("/api/build_f/messengers");
      for (const p of ["discord", "telegram"]) {
        const cfg = m[p] || {}, live = (m.live || {})[p] || {};
        if (cfg.enabled && cfg.token_present && live.error) add("warn", msg("common.health.bot", p[0].toUpperCase() + p.slice(1) + " bot", {name: p[0].toUpperCase() + p.slice(1)}), live.error);
      }
    } catch (_) {}
    let level = "ok";
    for (const it of items) if (LEVEL_RANK[it.level] > LEVEL_RANK[level]) level = it.level;
    health.level = level; health.items = items;
    renderHealth();
    for (const fn of health.listeners) { try { fn(level, items); } catch (_) {} }
    return { level, items };
  }

  function renderHealth() {
    const light = document.getElementById("navHealthLight"), label = document.getElementById("navHealthLabel");
    const button = document.getElementById("navHealth");
    if (!light || !label || !button) return;
    const level = health.level || "";
    light.className = "light " + level;
    label.textContent = level ? tr(LEVEL_KEY[level], LEVEL_LABEL[level]) : tr("common.health.checking", "Checking…");
    button.title = level === "ok" ? tr("common.health.ok", "System Ready") : tr("common.health.details", "Click for details");
    if (health.pop) renderHealthPop();
  }

  function renderHealthPop() {
    const pop = health.pop;
    if (!pop) return;
    pop.replaceChildren();
    const level = health.level || "ok";
    pop.setAttribute("aria-label", tr("common.health.title", "System health"));
    pop.append(el("div", { class: "head " + level }, el("span", { class: "light " + level }), el("b", { text: tr(LEVEL_KEY[level], LEVEL_LABEL[level]) })));
    const bad = health.items.filter((it) => it.level !== "ok");
    if (!bad.length) {
      pop.append(el("p", { class: "fine", text: tr("common.health.ready", "All checks for the enabled features are green.") }));
    } else {
      pop.append(el("p", { class: "fine", text: level === "err" ? tr("common.health.down", "Something she needs is down:") : tr("common.health.warning", "She works, but check these:") }));
      for (const it of bad) {
        pop.append(el("div", { class: "row" }, el("span", { class: "dot " + it.level }),
          el("span", { class: "name", text: it.name }), el("span", { class: "meta", text: it.detail || "" })));
      }
    }
    pop.append(el("div", { class: "foot" },
      el("a", { href: "/setup", text: tr("common.health.setup", "Open Setup →") }),
      el("button", { type: "button", class: "editorial-link", text: tr("common.health.retry", "Re-check"), onclick: () => { healthCheck(); } })));
  }

  function toggleHealthPop(force) {
    const button = document.getElementById("navHealth");
    if (!button) return;
    const open = force !== undefined ? force : !health.pop;
    if (!open) {
      if (health.pop) health.pop.remove();
      health.pop = null;
      button.setAttribute("aria-expanded", "false");
      return;
    }
    health.pop = el("div", { class: "oa-health-pop", role: "dialog", "aria-label": tr("common.health.title", "System health") });
    document.body.append(health.pop);
    button.setAttribute("aria-expanded", "true");
    renderHealthPop();
  }

  function startHealth() {
    const button = document.getElementById("navHealth");
    if (!button) return;
    renderHealth();
    button.addEventListener("click", (event) => { event.stopPropagation(); toggleHealthPop(); });
    document.addEventListener("click", (event) => {
      if (health.pop && !health.pop.contains(event.target)) toggleHealthPop(false);
    });
    document.addEventListener("keydown", (event) => { if (event.key === "Escape") toggleHealthPop(false); });
    const tick = () => {
      clearTimeout(health.timer);
      const run = document.hidden ? Promise.resolve() : healthCheck().catch(() => {});
      run.finally(() => { health.timer = setTimeout(tick, 15000); });
    };
    tick();
  }
  function onHealth(fn) { health.listeners.add(fn); if (health.level) fn(health.level, health.items); }

  window.addEventListener("oa:localechange", () => {
    const picker = document.getElementById("oaLocale");
    if (picker) picker.value = OAI18n.getLocale();
    for (const item of health.items) {
      for (const field of ["name", "detail"]) {
        const message = item[field + "Message"];
        if (message && message.key) item[field] = OAI18n.t(message.key, message.params);
      }
    }
    renderHealth();
    for (const fn of health.listeners) { try { fn(health.level, health.items); } catch (_) {} }
  });

  // kept for older page scripts: the three dots became the one health light above
  function setNavDot() {}

  const fmt = {
    ms: (v) => (Number.isFinite(v) ? Math.round(v).toLocaleString(typeof OAI18n !== "undefined" ? OAI18n.getLocale() : "en") + " ms" : "—"),
    s1: (v) => (Number.isFinite(v) ? (v / 1000).toFixed(v >= 10000 ? 1 : 2) + " s" : "—"),
    usd: (v) => (Number.isFinite(v) ? "$" + (v >= 0.01 ? v.toFixed(3) : v.toFixed(4)) : "—"),
    int: (v) => (Number.isFinite(v) ? Math.round(v).toLocaleString(typeof OAI18n !== "undefined" ? OAI18n.getLocale() : "en") : "—"),
    pct: (v) => (Number.isFinite(v) ? (Math.round(v * 10) / 10) + "%" : "—"),
  };

  window.OA = { nav, footer, toast, getJSON, postAction, el, setNavDot, fmt, healthCheck, onHealth };
})();
