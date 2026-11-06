/* OpenAmika Setup: localization changes presentation only, never editable source or configuration. */
(function () {
  "use strict";
  const { nav, footer, toast, getJSON, postAction, el, setNavDot } = window.OA;
  nav("setup"); footer();
  const $ = (id) => document.getElementById(id);

  // setup locale helpers
  const bindings = new Map();
  function tr(key, params = {}) {
    const full = "setup." + key;
    const fallback = window.OASetupMessages?.en[full];
    if (fallback === undefined) return key;
    if (window.OAI18n) return window.OAI18n.t(full, params);
    return fallback.replace(/\{(\w+)\}/g, (token, name) => Object.prototype.hasOwnProperty.call(params, name) ? String(params[name]) : token);
  }
  const message = (key, params = {}) => () => tr(key, typeof params === "function" ? params() : params);
  function metadataText(source, explain = false) {
    const key = window.OASetupMetadata?.[source];
    if (key) return tr(key);
    const local = String(source).match(/^(.*) \(Ollama · local\)$/);
    if (local) return tr("localModelName", { name: local[1] });
    const ollama = String(source).match(/^Runs on your own GPU through Ollama: no API key, no cost; speed depends on the card\.(.*)$/);
    if (ollama) {
      const [specs, capabilities = ""] = ollama[1].split(" Can: ");
      return tr("ollamaDescription", { specs: specs.trim(), capabilities: capabilities.replace(/\.$/, "").split(", ").filter(Boolean).map(c => tr(c === "vision" ? "visionCapability" : c)).join(", ") });
    }
    return explain && source ? tr("diagnostic", { detail: source }) : source;
  }
  function paint(node, render, attribute = "textContent") {
    if (!node) return node;
    const props = bindings.get(node) || new Map();
    props.set(attribute, render);
    bindings.set(node, props);
    // A dynamic binding replaces the initial static loading label, not the control itself.
    node.removeAttribute?.(attribute === "textContent" ? "data-i18n" : "data-i18n-" + attribute);
    const value = render();
    if (attribute === "textContent" || attribute === "title") node[attribute] = value;
    else node.setAttribute(attribute, value);
    return node;
  }
  const put = (node, key, params, attribute) => paint(node, message(key, params), attribute);
  const label = (tag, key, params = {}, props = {}) => put(el(tag, props), key, params);
  function pruneBindings() {
    for (const node of bindings.keys()) if (node.isConnected === false) bindings.delete(node);
  }
  function startupName(name) {
    const component = String(name).match(/^(service|agent|tool) (.+)$/);
    if (component) return tr("check_" + component[1], { name: component[2] });
    const imports = String(name).match(/^(.+) imports$/);
    return imports ? tr("check_imports", { name: imports[1] }) : metadataText(name);
  }
  function refreshLocale() {
    window.OAI18n?.translate(document);
    for (const [node, props] of bindings) {
      if (node.isConnected === false) { bindings.delete(node); continue; }
      for (const [attribute, render] of props) {
        if (attribute === "textContent" || attribute === "title") node[attribute] = render();
        else node.setAttribute(attribute, render());
      }
    }
  }
  function errorText(error) {
    const codes = { unauthorized: "authError", forbidden: "authError", rate_limit: "rateError",
      timeout: "timeoutError", audio_disabled: "voiceDisabled", conflict: "idleError" };
    const statuses = { 401: "authError", 403: "authError", 408: "timeoutError", 409: "idleError",
      429: "rateError", 504: "timeoutError" };
    const key = Object.prototype.hasOwnProperty.call(codes, error?.code) ? codes[error.code]
      : Object.prototype.hasOwnProperty.call(statuses, error?.status) ? statuses[error.status] : "error";
    // Provider prose can contain secrets, private prompts or paths. Never render it.
    return tr(key);
  }
  const fail = (error) => toast(errorText(error), true);
  function row(state, name, render) {
    return el("div", { class: "health-row" }, el("span", { class: "dot " + state, "aria-hidden": "true" }),
      paint(el("span", { class: "name" }), typeof name === "function" ? name : message(name)), paint(el("span", { class: "meta" }), typeof render === "function" ? render : () => render));
  }
  window.addEventListener("oa:localechange", refreshLocale);
  refreshLocale();
  // end setup locale helpers

  // ───────────────────── health ─────────────────────
  async function health() {
    const rows = $("healthRows");
    rows.replaceChildren();
    const add = (state, name, render) => rows.append(row(state, name, render));
    try {
      const s = await getJSON("/api/build_f/status");
      const problems = Object.values(s.template_check || {}).reduce((a, list) => a + (Array.isArray(list) ? list.length : 0), 0);
      add(problems ? "warn" : "ok", "brain", message("templates", { app: s.app || "?", count: problems }));
      const m = s.memory || {};
      add(m.degraded ? "warn" : "ok", "memory", message("memoryCounts", { events: m.events ?? "—", facts: m.facts ?? "—", pending: m.pending || 0 }));
      setNavDot(0, "ok");
    } catch (error) { add("err", "brain", () => errorText(error)); setNavDot(0, "err"); }
    try {
      const h = await getJSON("/health");
      add("ok", "speech", message("device", { device: h.device || "?", gpu: h.cuda_available ? "✓ " + (h.gpu_name || "") : "✗ (cpu)" }));
      setNavDot(1, "ok");
    } catch (error) { add("err", "speech", () => errorText(error)); setNavDot(1, "err"); }
    try {
      const p = await getJSON("/api/tts_probe");
      add(p.ok ? "ok" : "err", "TTS", () => `${p.url || "?"} · ${p.character || "?"} · ${p.ok ? tr("reachable") : errorText(p.error || tr("unreachable"))}`);
      $("ttsUrlShow").textContent = p.url || "—";
      $("ttsCharShow").textContent = p.character || "—";
      $("ttsDot").className = "dot " + (p.ok ? "ok" : "err");
      paint($("ttsDotNote"), () => p.ok ? tr("reachable") : tr("voiceInstall") + (p.error ? " " + errorText(p.error) : ""));
      const states = { disabled: "koreanDisabled", unavailable: "koreanUnavailable", unknown: "koreanUnknown", frontend_ready: "koreanFrontend" };
      // G2P readiness is not acoustic acceptance, even when the server answers successfully.
      add(p.korean?.state === "unavailable" ? "err" : "warn", "koreanVoice", message(states[p.korean?.state] || "koreanUnknown"));
      setNavDot(2, p.ok ? "ok" : "err");
    } catch (_) { add("err", "TTS", message("probeFailed")); add("warn", "koreanVoice", message("koreanUnknown")); setNavDot(2, "err"); }
    try {
      const a = await getJSON("/api/avatar/models");
      const models = a.models || [], mine = models.filter(m => m.role !== "agent");
      add(mine.length ? "ok" : "err", "Live2D", () => models.map(m => m.name + (m.role === "agent" ? tr("agentSuffix") : "")).join(", ") + (mine.length ? "" : " " + tr("avatarMissing")));
    } catch (_) { add("err", "Live2D", message("registryFailed")); }
    try {
      const tools = await getJSON("/api/build_f/tools");
      add(tools.enabled ? "ok" : "warn", "tools", tools.enabled ? message("servers", { count: Object.keys(tools.servers || {}).length }) : message("toolsDisabled"));
    } catch (_) { add("warn", "tools", message("unavailable")); }
    try {
      const p = await getJSON("/api/preflight"), s = p.summary || {};
      if (p.at) {
        add(s.err ? "err" : s.warn ? "warn" : "ok", "startup", message("startupCounts", { ok: s.ok || 0, warn: s.warn || 0, err: s.err || 0, at: String(p.at).replace("T", " ") }));
        for (const c of p.checks || []) if (c.level !== "ok") add(c.level === "err" ? "err" : "warn", () => "↳ " + startupName(c.name), message("startupDiagnostic", { detail: c.detail }));
      }
    } catch (_) {}
    pruneBindings();
  }
  $("healthRefresh").addEventListener("click", health);
  health();

  // ───────────────────── vision ─────────────────────
  async function loadVision() {
    const rows = $("visionRows");
    try {
      const v = await getJSON("/api/vision");
      if (!v.enabled) { rows.replaceChildren(row("warn", "vision", message("visionDisabled"))); return; }
      const s = v.service;
      rows.replaceChildren(
        s ? row(s.model_loaded ? "ok" : "warn", "vlm", message("vlmStatus", () => ({ model: s.model || "?", loaded: tr(s.model_loaded ? "modelLoaded" : "loading"), feed: tr(s.feed_connected ? "connected" : "waiting"), frames: s.frames_seen || 0 })))
          : row("err", "vlm", message("visionUnreachable", { url: v.url })),
        row(v.camera_clients ? "ok" : "warn", "camera", v.camera_clients ? message("cameraClients", { count: v.camera_clients }) : message("noCamera")),
        row(v.description ? "ok" : "warn", "sheSees", () => v.description || (v.last_description ? tr("stale", { description: v.last_description }) : tr("noDescription")))
      );
    } catch (error) { rows.replaceChildren(row("err", "vision", () => errorText(error))); }
    finally { pruneBindings(); }
  }
  loadVision();
  setInterval(() => { if (!document.hidden) loadVision(); }, 3000);
  $("meterReset").addEventListener("click", async () => {
    try { await postAction("/api/build_f/meter/reset", "reset-meter", { action: "reset_display" }); toast(tr("meterDone")); health(); }
    catch (error) { fail(error); }
  });

  // ── danger zone ──
  async function dangerAction(route, action, word, inputId, buttonId, done) {
    const input = $(inputId), button = $(buttonId), note = $("dangerNote");
    if (input.value.trim() !== word) { toast(tr("confirmWord", { word }), true); input.focus(); return; }
    button.disabled = true;
    put(note, "working");
    try {
      const response = await fetch(route, { method: "POST", headers: { "Content-Type": "application/json", "X-Build-F-Action": action }, body: JSON.stringify({ confirmation: word }) });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) {
        throw Object.assign(new Error(), { status: response.status, code: payload.code || payload.detail?.code });
      }
      input.value = "";
      paint(note, () => done(payload));
      toast(note.textContent);
      health(); loadPersona(); loadBuilder();
    } catch (error) { paint(note, () => errorText(error)); fail(error); }
    finally { button.disabled = false; }
  }
  $("wipeBtn").addEventListener("click", () => dangerAction("/api/build_f/wipe", "wipe-memory", "WIPE", "wipeConfirm", "wipeBtn",
    p => tr("wipeDone", { backup: p.backup_id || tr("backupKept") })));
  $("resetBtn").addEventListener("click", () => dangerAction("/api/build_f/reset", "reset-all", "RESET", "resetConfirm", "resetBtn",
    p => tr("resetDone", { backup: p.backup_id || tr("backupKept"), files: (p.restored || []).join(", ") || tr("nothing") })));

  // ───────────────────── models ─────────────────────
  let modelData = null;
  const ROLE_LABELS = { surface: "roleSurface", deep: "roleDeep", reflection: "roleReflection", memory_write: "roleMemory" };
  async function loadModels() {
    try { modelData = await getJSON("/api/build_f/models"); }
    catch (error) { put($("modelsNote"), "modelError", () => ({ detail: errorText(error) })); return; }
    const ROLES = ["surface", "deep", "reflection", "memory_write"];
    const optionList = role => Array.isArray(modelData.options?.[role]) ? modelData.options[role] : [];
    const selections = modelData.selections || {};
    $("modelSummary").replaceChildren(...ROLES.map(role => {
      const sel = selections[role], item = optionList(role).find(o => o.key === sel);
      return el("div", { class: "row" }, label("span", ROLE_LABELS[role], {}, { class: "role" }),
        paint(el("span", { class: "mdl" }), () => metadataText(item?.name || sel || tr("notSelected"))));
    }));
    const kinds = new Set(ROLES.map(role => optionList(role).find(o => o.key === selections[role])?.transport || "openrouter"));
    const onOllama = kinds.has("ollama"), onCloud = kinds.has("openrouter") || kinds.has("alibaba") || kinds.has("native");
    paint($("modelsNote"), () => "");
    $("provOpenrouter").classList.toggle("active", onCloud);
    $("provOllama").classList.toggle("active", onOllama);
    put($("provOpenrouter").querySelector("span"), onCloud && !onOllama ? "cloudActive" : "cloudChoice");
    put($("provOllama").querySelector("span"), onOllama && !onCloud ? "localActive" : "localChoice");
    $("orBackNote").hidden = !onOllama;
    if (!provChosen) showProvider(onOllama && !onCloud ? "ollama" : "openrouter");
    const grid = $("roleGrid");
    grid.replaceChildren();
    for (const role of ROLES) {
      const options = optionList(role), select = el("select", { id: "role_" + role });
      for (const item of options) {
        const option = paint(el("option", { value: item.key }), () => metadataText(item.name || item.key) + (item.disabled ? tr("disabledSuffix") : ""));
        if (item.disabled) option.disabled = true;
        select.append(option);
      }
      if (selections[role]) select.value = selections[role];
      const description = el("div", { class: "card-hint", style: "min-height:30px" });
      const refreshDesc = () => {
        const item = options.find(o => o.key === select.value);
        if (item) put(description, "modelDescriptionTranslated", () => ({ provider: item.transport || item.provider || "?", description: metadataText(item.description || "", true) }));
        else paint(description, () => "");
      };
      select.addEventListener("change", refreshDesc);
      refreshDesc();
      grid.append(el("div", { class: "field" }, label("label", ROLE_LABELS[role], {}, { for: "role_" + role }), select, description));
    }
    loadOllama();
    $("presetSelect").replaceChildren(...(Array.isArray(modelData.presets) ? modelData.presets : []).map(p => {
      const name = p?.name || String(p), option = paint(el("option", { value: name }), () => metadataText(name));
      paint(option, () => metadataText(p?.description || "", true), "title");
      if (p?.available === false) option.disabled = true;
      return option;
    }));
  }
  loadModels();
  let provChosen = false;
  function showProvider(which) {
    $("orPanel").hidden = which !== "openrouter";
    $("ollamaPanel").hidden = which !== "ollama";
    $("provOpenrouter").setAttribute("aria-pressed", String(which === "openrouter"));
    $("provOllama").setAttribute("aria-pressed", String(which === "ollama"));
  }
  $("provOpenrouter").addEventListener("click", () => { provChosen = true; showProvider("openrouter"); });
  $("provOllama").addEventListener("click", () => { provChosen = true; showProvider("ollama"); loadOllama(); });
  $("orBack").addEventListener("click", async () => {
    try { const r = await postAction("/api/build_f/preset", "apply-preset", { provider: "openrouter" }); toast(tr("cloudRestored", { preset: metadataText(r.applied_preset || tr("presetApplied")) })); loadModels(); }
    catch (error) { fail(error); }
  });
  let ollamaInfo = null;
  function olModelLabel(m) {
    const bits = [m.parameter_size, m.quantization, m.size_gb ? m.size_gb + " GB" : ""].filter(Boolean);
    const caps = [m.thinking ? tr("thinking") : "", m.vision ? tr("visionCapability") : ""].filter(Boolean);
    return m.name + (bits.length ? " · " + bits.join(" ") : "") + (caps.length ? " · " + caps.join(", ") : "");
  }
  async function loadOllama() {
    try { ollamaInfo = await getJSON("/api/build_f/ollama"); }
    catch (error) { put($("olStatus"), "statusError", () => ({ detail: errorText(error) })); return; }
    if (!$("olUrl").value.trim()) $("olUrl").value = ollamaInfo.base_url || "http://127.0.0.1:11434";
    const info = ollamaInfo, n = (info.models || []).length;
    put($("olStatus"), info.reachable ? "ollamaRunning" : "ollamaDown", { version: info.live_version || "", count: n, url: info.base_url || "?" });
    const select = $("olModel"), inUse = info.in_use || {}, current = inUse.deep || inUse.surface || "";
    select.replaceChildren(...(n ? info.models.map(m => paint(el("option", { value: m.name }), () => olModelLabel(m))) : [label("option", "detectFirst", {}, { value: "" })]));
    if (current) select.value = current;
    $("olUse").disabled = !n;
    const roles = Object.keys(inUse);
    paint($("olNote"), () => roles.length === 4 ? tr("allLocal", { model: new Set(Object.values(inUse)).size === 1 ? current : tr("localModels") })
      : roles.length ? tr("someLocal", { roles: roles.map(r => tr(ROLE_LABELS[r] || r)).join(", ") }) : "");
  }
  $("olDetect").addEventListener("click", async () => {
    $("olDetect").disabled = true; put($("olStatus"), "askingOllama");
    try {
      const r = await postAction("/api/build_f/ollama/detect", "ollama-detect", { base_url: $("olUrl").value.trim() });
      const n = (r.models || []).length;
      toast(tr(n ? "detected" : "ollamaEmpty", { count: n }), !n);
      await loadOllama(); loadModels();
    } catch (error) { paint($("olStatus"), () => errorText(error)); fail(error); }
    finally { $("olDetect").disabled = false; }
  });
  $("olUse").addEventListener("click", async () => {
    const model = $("olModel").value;
    if (!model) { toast(tr("detectFirst"), true); return; }
    try { const r = await postAction("/api/build_f/ollama/use", "ollama-use", { model }); toast(tr("localSelected", { model, transport: r.transport || "ollama" })); loadModels(); loadOllama(); }
    catch (error) { fail(error); }
  });
  async function loadKey() {
    try { const k = await getJSON("/api/build_f/openrouter_key"); put($("orKeyStatus"), k.present ? "keySavedStatus" : "noKey", { hint: k.hint || "" }); }
    catch (_) { put($("orKeyStatus"), "keyUnavailable"); }
  }
  loadKey();
  $("orKeySave").addEventListener("click", async () => {
    const key = $("orKeyInput").value.trim();
    if (!key) { toast(tr("pasteKey"), true); return; }
    try { await postAction("/api/build_f/openrouter_key", "openrouter-key", { key }); $("orKeyInput").value = ""; toast(tr("keySaved")); loadKey(); }
    catch (error) { fail(error); }
  });
  $("modelsSave").addEventListener("click", async () => {
    const selections = {};
    for (const role of ["surface", "deep", "reflection", "memory_write"]) { const select = $("role_" + role); if (select) selections[role] = select.value; }
    try { await postAction("/api/build_f/models", "select-models", { selections }); toast(tr("modelsSaved")); loadModels(); }
    catch (error) { fail(error); }
  });
  $("presetApply").addEventListener("click", async () => {
    try { await postAction("/api/build_f/preset", "apply-preset", { preset: $("presetSelect").value }); toast(tr("presetApplied")); loadModels(); }
    catch (error) { fail(error); }
  });

  // ───────────────────── voice adapter ─────────────────────
  let vmap = null;
  const FAMILY = id => id.replace(/\d+$/, "");
  async function loadVoiceMap() {
    vmap = await getJSON("/api/voice_map").catch(() => null);
    if (!vmap) { $("vmapGrid").replaceChildren(label("div", "mapUnavailable", {}, { class: "card-hint" })); return; }
    $("vmapEnabled").checked = !!vmap.enabled;
    $("vmapVoice").value = vmap.voice || "";
    $("vmapVoices").replaceChildren(...(vmap.v1_voices || []).map(v => el("option", { value: v })));
    $("ttsCharShow").textContent = vmap.native_character || $("ttsCharShow").textContent;
    const families = new Map();
    for (const id of vmap.v1_ids || []) { const fam = FAMILY(id); if (!families.has(fam)) families.set(fam, []); families.get(fam).push(id); }
    const grid = $("vmapGrid"); grid.replaceChildren();
    for (const [register, emotions] of Object.entries(vmap.v2_grouped || {})) {
      const cells = el("div", { class: "vmap-cells" });
      for (const emotion of emotions) {
        const key = register + "_" + emotion, select = el("select", { "data-key": key, id: "vmap_" + key });
        put(select, "mappingLabel", { key }, "aria-label");
        for (const [fam, ids] of families) { const group = el("optgroup", { label: fam }); for (const id of ids) group.append(el("option", { value: id, text: id })); select.append(group); }
        select.value = vmap.map?.[key] || vmap.defaults?.[key] || "neutral1";
        const cell = el("div", { class: "vmap-cell" }, el("label", { text: key, for: "vmap_" + key }), select);
        const markChanged = () => cell.classList.toggle("changed", select.value !== (vmap.defaults ? vmap.defaults[key] : select.value));
        select.addEventListener("change", markChanged); markChanged(); cells.append(cell);
      }
      grid.append(el("div", { class: "vmap-register" }, el("h4", { text: register }), cells));
    }
  }
  loadVoiceMap();
  async function saveVoiceMap() {
    const map = {};
    document.querySelectorAll("#vmapGrid select[data-key]").forEach(select => { map[select.dataset.key] = select.value; });
    try {
      const response = await fetch("/api/voice_map", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ enabled: $("vmapEnabled").checked, voice: $("vmapVoice").value.trim(), map }) });
      if (!response.ok) throw Object.assign(new Error(), { status: response.status });
      toast(tr($("vmapEnabled").checked ? "adapterOn" : "adapterOff", { voice: $("vmapVoice").value.trim() || tr("default") })); loadVoiceMap();
    } catch (error) { fail(error); }
  }
  $("vmapSave").addEventListener("click", saveVoiceMap);
  $("vmapReset").addEventListener("click", async () => {
    try { const r = await fetch("/api/voice_map/reset", { method: "POST" }); if (!r.ok) throw Object.assign(new Error(), { status: r.status }); toast(tr("mapReset")); loadVoiceMap(); }
    catch (error) { fail(error); }
  });

  // ───────────────────── avatar ─────────────────────
  let avatars = [];
  async function loadAvatars() {
    const payload = await getJSON("/api/avatar/models").catch(() => ({ models: [] }));
    avatars = payload.models || [];
    put($("avSimpleList"), avatars.length ? "installedModels" : "noAvatars", { models: avatars.map(m => m.name).join(" · ") });
    $("avModelSelect").replaceChildren(...(avatars.length ? avatars.map(m => el("option", { value: m.id, text: m.name })) : [label("option", "noModels", {}, { value: "" })]));
    if (avatars.length) loadAvatarConfig(avatars[0].id);
    else { $("avBanks").value = ""; put($("avNote"), "addModel"); }
  }
  async function loadAvatarConfig(id) {
    const model = avatars.find(m => m.id === id); if (!model) return;
    const doc = await getJSON(model.banks_url).catch(() => ({ config: {}, banks: {} }));
    $("avDisplayName").value = doc.config?.display_name || model.name || "";
    $("avMouthOpen").value = doc.config?.mouth_open_param || "";
    $("avMouthForm").value = doc.config?.mouth_form_param || "";
    $("avScale").value = doc.config?.scale || "";
    const banks = {};
    for (const [key, entry] of Object.entries(doc.banks || {})) if (entry && (entry.emotes?.length || entry.movements?.length)) banks[key] = entry;
    $("avBanks").value = JSON.stringify({ banks }, null, 2); put($("avNote"), "emptyBanks");
  }
  $("avModelSelect").addEventListener("change", () => loadAvatarConfig($("avModelSelect").value));
  $("avReload").addEventListener("click", loadAvatars); loadAvatars();
  $("avSave").addEventListener("click", async () => {
    const id = $("avModelSelect").value;
    if (!id) { toast(tr("noModelSelected"), true); return; }
    let parsed;
    try { parsed = $("avBanks").value.trim() ? JSON.parse($("avBanks").value) : { banks: {} }; }
    catch (error) { toast(tr("invalidBanks", { detail: error.message }), true); return; }
    const config = {};
    if ($("avDisplayName").value.trim()) config.display_name = $("avDisplayName").value.trim();
    if ($("avMouthOpen").value.trim()) config.mouth_open_param = $("avMouthOpen").value.trim();
    if ($("avMouthForm").value.trim()) config.mouth_form_param = $("avMouthForm").value.trim();
    if ($("avScale").value) config.scale = Number($("avScale").value);
    try {
      const response = await fetch("/api/avatar/models/" + encodeURIComponent(id) + "/banks", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ config, banks: parsed.banks || parsed }) });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) throw Object.assign(new Error(), { status: response.status, code: payload.code || payload.detail?.code });
      toast(tr("avatarSaved"));
    } catch (error) { fail(error); }
  });

  // ───────────────────── persona builder ─────────────────────
  const STORY_LABELS = { "WHO YOU ARE": "storyOrigin", "YOUR FAMILY": "storyFamily", "YOUR SCHOOL LIFE": "storySchool", "YOUR DAYS HERE": "storyDays", "YOUR PATH": "storyPath", "YOUR ROLE": "storyRole", "YOUR PRIVATE SELF": "storyPrivate", "现在": "storyNow", "PERSONALITY": "storyTraits" };
  const DAY_ORDER = ["清晨", "上午", "中午", "下午", "傍晚", "晚上", "深夜", "凌晨"];
  const DAY_LABELS = { "清晨": "earlyMorning", "上午": "morning", "中午": "noon", "下午": "afternoon", "傍晚": "evening", "晚上": "night", "深夜": "lateNight", "凌晨": "preDawn" };
  const ABOUT_FIELDS = [["recent_mood", "mood"], ["current_action", "action"], ["relationship", "relationship"], ["surface_context", "surfaceContext"], ["communication_style", "communication"]];
  let pbDirty = { story: {}, days: {}, about: {} };
  let fieldSerial = 0;
  function pbField(group, key, render, source, rows) {
    const id = "pb_" + (++fieldSerial), area = el("textarea", { id, rows: String(rows || 4), spellcheck: "false" });
    area.value = source || "";
    const wrap = el("div", { class: "pb-field" }, paint(el("label", { for: id }), render), area);
    area.addEventListener("input", () => { pbDirty[group][key] = area.value; wrap.classList.add("dirty"); });
    return wrap;
  }
  const SLOT_COUNT = 5;
  function pbSlot(key, period, options) {
    const list = Array.from({ length: SLOT_COUNT }, (_, i) => typeof options[i] === "string" ? options[i] : ""), saved = list.slice();
    let current = 0;
    const id = "pb_" + (++fieldSerial), area = el("textarea", { id, rows: "3", spellcheck: "false" });
    const tabs = el("div", { class: "pb-slot-tabs", role: "tablist" }); put(tabs, "slotTabs", {}, "aria-label");
    const buttons = list.map((_, i) => el("button", { type: "button", role: "tab", text: String(i + 1), "aria-controls": id }));
    const wrap = el("div", { class: "pb-slot" }, el("div", { class: "pb-slot-head" },
      label("label", "dayQuestion", () => ({ period: tr(DAY_LABELS[period]) }), { for: id }), tabs), area,
      label("div", "possibilities", {}, { class: "pb-slot-note" }));
    const paintTabs = () => buttons.forEach((b, j) => {
      b.classList.toggle("active", j === current); b.classList.toggle("dirty", list[j] !== saved[j]);
      b.setAttribute("aria-selected", String(j === current));
      const params = () => ({ number: j + 1, empty: list[j].trim() ? "" : tr("empty") });
      put(b, "possibility", params, "title"); put(b, "possibility", params, "aria-label");
    });
    const show = i => { current = i; area.value = list[i]; paintTabs(); };
    buttons.forEach((b, i) => { b.addEventListener("click", () => show(i)); tabs.append(b); });
    area.addEventListener("input", () => { list[current] = area.value; pbDirty.days[key] = list.map(s => s.trim()).filter(Boolean); wrap.classList.add("dirty"); paintTabs(); });
    show(0); return wrap;
  }
  function pbGroup(key, open, children) {
    const details = el("details", { class: "oa-details" }, label("summary", key));
    if (open) details.setAttribute("open", "");
    details.append(el("div", { class: "inner" }, ...children)); return details;
  }
  async function loadBuilder() {
    const box = $("personaBuilder"); let data;
    try { data = await getJSON("/api/build_f/persona/simple"); }
    catch (error) { box.replaceChildren(label("p", "builderError", () => ({ detail: errorText(error) }), { class: "card-hint" })); return; }
    pbDirty = { story: {}, days: {}, about: {} };
    const story = (data.story || []).map(s => pbField("story", s.key, message(STORY_LABELS[s.key] || s.key), s.text, Math.min(10, Math.max(3, Math.ceil((s.text || "").length / 90)))));
    const dayFields = prefix => {
      const fields = [];
      for (const period of DAY_ORDER) {
        const key = prefix + "/" + period;
        if (data.days && key in data.days) {
          const value = data.days[key];
          fields.push(Array.isArray(value) ? pbSlot(key, period, value) : pbField("days", key, message("dayQuestion", () => ({ period: tr(DAY_LABELS[period]) })), value, 3));
        }
      }
      return el("div", { class: "pb-days" }, ...fields);
    };
    const about = ABOUT_FIELDS.filter(([key]) => data.about && data.about[key] !== undefined && data.about[key] !== "").map(([key, title]) => pbField("about", key, message(title), data.about[key], 4));
    box.replaceChildren(pbGroup("storyGroup", true, story.length ? story : [label("p", "noStory", {}, { class: "card-hint" })]),
      pbGroup("weekdayGroup", false, [dayFields("weekday")]), pbGroup("weekendGroup", false, [dayFields("weekend")]), pbGroup("aboutGroup", false, about),
      label("p", "tokensHelp", {}, { class: "card-hint", style: "margin-top:8px" }));
  }
  loadBuilder();
  $("pbSave").addEventListener("click", async () => {
    const payload = {};
    for (const group of ["story", "days", "about"]) if (Object.keys(pbDirty[group]).length) payload[group] = pbDirty[group];
    if (!Object.keys(payload).length) { toast(tr("nothingChanged")); return; }
    try {
      const result = await postAction("/api/build_f/persona/simple", "persona-simple", payload), problems = result.problems || [];
      put($("pbNote"), problems.length ? "formatWarnings" : "savedFiles", { count: problems.length, detail: problems.slice(0, 2).join(" · "), files: (result.touched || []).join(", ") });
      toast(tr(problems.length ? "checkWarnings" : "savedApplied"), problems.length > 0); loadBuilder(); loadPersona();
    } catch (error) { fail(error); }
  });

  // ───────────────────── personality (raw files) ─────────────────────
  let persona = null;
  const edited = {};
  function showPersonaFile() {
    if (!persona) return;
    const target = $("pTarget").value;
    $("pEditor").value = edited[target] !== undefined ? edited[target] : (persona.files?.[target] || "");
    const checkMap = { deep: "例子.txt", surface: "表层.txt", thinking: "思考.txt" }, tag = $("pCheckTag");
    if (target === "scenes") { tag.hidden = true; return; }
    const problems = persona.template_check?.[checkMap[target]] || persona.template_check?.[target] || [];
    tag.hidden = false; put(tag, problems.length ? "templateWarnings" : "templateOK", { count: problems.length });
    tag.style.color = problems.length ? "var(--warn)" : "";
    put(tag, "diagnostic", { detail: problems.join("\n") }, "title");
  }
  function fillTimezones(list, current) {
    let mine = "";
    try { mine = Intl.DateTimeFormat().resolvedOptions().timeZone || ""; } catch (_) {}
    const zones = Array.from(new Set([...(list || []), current, mine].filter(Boolean))).sort(), select = $("pTimezone");
    select.replaceChildren(...zones.map(z => z === mine ? label("option", "thisComputer", { zone: z }, { value: z }) : el("option", { value: z, text: z })));
    if (current) select.value = current;
  }
  function showClock(clock) {
    if (clock) put($("pClock"), "clock", { local: clock.local, abbrev: clock.abbrev || "", timezone: clock.timezone });
    else paint($("pClock"), () => "");
  }
  async function loadPersona() {
    try {
      persona = await getJSON("/api/build_f/persona");
      $("pName").value = persona.persona_name || ""; $("pUser").value = persona.user_name || ""; $("pCity").value = persona.city || "";
      try { const pron = await getJSON("/api/name_pronunciation"); $("pSayAs").value = pron.name && pron.name.toLowerCase() === (persona.user_name || "").toLowerCase() ? pron.say_as || "" : ""; } catch (_) {}
      fillTimezones(persona.timezones, persona.timezone || ""); showClock(persona.clock); showPersonaFile();
    } catch (error) { put($("pNote"), "personaError", () => ({ detail: errorText(error) })); }
  }
  $("pTarget").addEventListener("change", showPersonaFile);
  $("pEditor").addEventListener("input", () => { edited[$("pTarget").value] = $("pEditor").value; });
  $("pRevert").addEventListener("click", () => { delete edited[$("pTarget").value]; showPersonaFile(); toast(tr("discarded")); });
  $("pIdentitySave").addEventListener("click", async () => {
    try {
      const result = await postAction("/api/build_f/persona/identity", "persona-identity", { persona_name: $("pName").value.trim() || "Amika", user_name: $("pUser").value.trim() || "User", timezone: $("pTimezone").value, city: $("pCity").value.trim() });
      put($("pIdentityNote"), "savedApplied"); showClock(result.clock);
      const name = $("pUser").value.trim();
      if (name) try { await postAction("/api/name_pronunciation", "name-pronunciation", { name, say_as: $("pSayAs").value.trim() }); }
      catch (error) { toast(tr("pronError", { detail: errorText(error) }), true); }
      toast(tr("identitySaved", { name: result.user_name || name, city: result.city || "" }));
    } catch (error) { fail(error); }
  });
  let hearAudio = null;
  $("pHear").addEventListener("click", async () => {
    const name = $("pUser").value.trim(), sayAs = $("pSayAs").value.trim();
    if (!name) { toast(tr("nameFirst"), true); return; }
    const spoken = sayAs || name; $("pHear").disabled = true;
    try {
      // This is a voice sample, not a UI-language or reply-language configuration change.
      const r = await postAction("/api/tts_say", "tts-say", { text: `${spoken}. Hi, ${spoken}! Nice to meet you.`, emotion: "intimate_caring", voice: "happy1", raw: !!sayAs });
      if (hearAudio) try { hearAudio.pause(); } catch (_) {}
      const mime = { opus: "audio/ogg", ogg: "audio/ogg", mp3: "audio/mpeg", wav: "audio/wav" }[r.audio_format] || "audio/wav";
      hearAudio = new Audio("data:" + mime + ";base64," + r.audio); await hearAudio.play();
    } catch (error) { toast(tr("voiceUnavailable", { detail: errorText(error) }), true); }
    finally { $("pHear").disabled = false; }
  });
  $("pSave").addEventListener("click", async () => {
    const target = $("pTarget").value;
    try {
      const result = await postAction("/api/build_f/persona/save", "persona-save", { target, content: $("pEditor").value });
      delete edited[target]; const problems = result.problems || [];
      put($("pNote"), problems.length ? "formatWarnings" : "savedApplied", { count: problems.length, detail: problems.slice(0, 3).join(" · ") });
      toast(tr(problems.length ? "checkWarnings" : "savedApplied"), problems.length > 0); loadPersona();
    } catch (error) { fail(error); }
  });
  loadPersona();

  // ───────────────────── messengers ─────────────────────
  const MSG = { discord: "Discord", telegram: "Telegram" };
  function msgRows(status) {
    const rows = $("msgRows"); rows.replaceChildren();
    const add = (state, name, render) => rows.append(row(state, name, render));
    add(status.brain ? "ok" : "err", "brainLink", message(status.brain ? "brainLinked" : "brainUnlinked"));
    for (const p of Object.keys(MSG)) {
      const cfg = status[p] || {}, live = status.live?.[p] || {};
      if (!cfg.token_present) { add("", MSG[p], message(p === "discord" && status.discord_library === false ? "discordMissing" : "noToken")); continue; }
      if (!cfg.enabled) { add("", MSG[p], message("tokenOff")); continue; }
      if (live.error) { add("err", MSG[p], () => errorText(live.error)); continue; }
      if (!live.connected) { add("warn", MSG[p], message("connecting")); continue; }
      const who = (cfg.allowed_users || []).length;
      add(who ? "ok" : "warn", MSG[p], message(who ? "botOnline" : "botNoUsers", () => ({ name: live.name || tr("bot"), count: who })));
    }
    if (status.last_chat?.label) add("ok", "lastChat", message("lastChatDetail", { label: status.last_chat.label }));
    pruneBindings();
  }
  function msgFill(status) {
    for (const p of Object.keys(MSG)) {
      const cfg = status[p] || {}, cap = p[0].toUpperCase() + p.slice(1);
      paint($("msg" + cap + "Hint"), () => cfg.token_present ? tr("tokenHint", { hint: cfg.token_hint || "" }) : "");
      $("msg" + cap + "Users").value = (cfg.allowed_users || []).join(", ");
      $("msg" + cap + "On").checked = !!cfg.enabled; $("msg" + cap + "Clear").hidden = !cfg.token_present;
    }
  }
  async function loadMessengers(fill) {
    try { const status = await getJSON("/api/build_f/messengers"); msgRows(status); if (fill) msgFill(status); }
    catch (error) { $("msgRows").replaceChildren(label("div", "messengerError", () => ({ detail: errorText(error) }), { class: "card-hint" })); }
  }
  async function msgSave(body, done, params = {}) {
    try {
      const result = await postAction("/api/build_f/messengers", "messengers", body);
      $("msgDiscordToken").value = ""; $("msgTelegramToken").value = ""; msgRows(result); msgFill(result);
      const bad = Object.keys(MSG).filter(p => result.live?.[p]?.error);
      paint($("msgNote"), () => bad.length ? bad.map(p => MSG[p] + ": " + errorText(result.live[p].error)).join(" · ") : tr(done, params));
      toast(tr(bad.length ? "botFailed" : done, params), bad.length > 0);
    } catch (error) { fail(error); }
  }
  $("msgSave").addEventListener("click", () => msgSave({
    discord: { token: $("msgDiscordToken").value.trim(), allowed_users: $("msgDiscordUsers").value, enabled: $("msgDiscordOn").checked },
    telegram: { token: $("msgTelegramToken").value.trim(), allowed_users: $("msgTelegramUsers").value, enabled: $("msgTelegramOn").checked }
  }, "botsConnecting"));
  $("msgDiscordClear").addEventListener("click", () => msgSave({ discord: { clear_token: true } }, "tokenForgotten", { provider: "Discord" }));
  $("msgTelegramClear").addEventListener("click", () => msgSave({ telegram: { clear_token: true } }, "tokenForgotten", { provider: "Telegram" }));
  loadMessengers(true);
  setInterval(() => loadMessengers(false), 10000);
})();
