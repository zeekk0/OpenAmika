/* OpenAmika — Tools page: her agents & MCP servers, consent settings, jobs, approvals, call log. */
(function () {
  "use strict";
  const { nav, footer, toast, getJSON, postAction, el: makeElement } = window.OA;
  const t = (key, params) => window.OAI18n.t(key, params);
  const bindings = new Map();
  function text(node, render) {
    bindings.set(node, render);
    node.textContent = render();
    return node;
  }
  function el(tag, attrs = {}, ...children) {
    const { i18n, render, ...rest } = attrs;
    const node = makeElement(tag, rest, ...children);
    if (i18n || render) text(node, render || (() => t(i18n)));
    return node;
  }
  const dateNote = (date) => date ? t("tools.onDate", { date: new Date(date).toLocaleString(window.OAI18n.getLocale()) }) : "";
  nav("tools"); footer();
  const $ = (id) => document.getElementById(id);
  window.OAI18n.translate();
  for (const [id, key] of Object.entries({ iotSub: "checking", iotConsentState: "consentOff",
    iotPairNote: "pairHint", addTargetLabel: "command", iotConsentVersion: "versionPending",
    iotConsentLead: "consentLead", iotConsentCancel: "cancel" })) text($(id), () => t("tools." + key));
  function pruneBindings() {
    for (const node of bindings.keys()) if (!node.isConnected) bindings.delete(node);
  }
  window.addEventListener("oa:localechange", () => {
    // Labels only: no config application, network requests, form replacement or consent side effects.
    pruneBindings();
    for (const [node, render] of bindings) node.textContent = render();
    if ($("iotConsent").open && !consent.manualLanguage) {
      const scroll = $("iotConsentText").scrollTop;
      showStatement(window.OAI18n.getLocale());
      $("iotConsentText").scrollTop = scroll;
    }
  });

  let state = null;        // last GET /api/build_f/tools payload (jobs and approvals are shown on the Use page)

  function configFromState(s) {
    // the brain hands over the raw tools.json (env / cwd / headers included) — a save must never strip
    // what the cards do not show. The reconstruction below is only for a brain that predates "config".
    if (s.config && typeof s.config === "object") {
      const doc = JSON.parse(JSON.stringify(s.config));
      doc.mcpServers = doc.mcpServers && typeof doc.mcpServers === "object" ? doc.mcpServers : {};
      return doc;
    }
    const servers = {};
    for (const [name, server] of Object.entries(s.servers || {})) {
      const entry = { enabled: !!server.enabled, tools: { ...(server.policies || {}) } };
      if (server.transport === "http") {
        entry.url = server.target;
      } else {
        const parts = (server.target || "").trim().split(/\s+/);
        entry.command = parts[0] || "";
        entry.args = parts.slice(1);
      }
      if (server.kind === "agent") entry.kind = "agent";
      if (server.persona_note) entry.persona_note = server.persona_note;
      servers[name] = entry;
    }
    return { enabled: !!s.enabled, clerk_role: s.clerk_role || "surface", limits: { ...(s.limits || {}) }, mcpServers: servers };
  }

  function splitCommand(text) {
    const out = [];
    const re = /"([^"]*)"|(\S+)/g;
    let m;
    while ((m = re.exec(text || ""))) out.push(m[1] !== undefined ? m[1] : m[2]);
    return out;
  }
  function joinCommand(auto) {
    if (!auto || !auto.command) return "";
    const q = (s) => (/\s/.test(s) ? '"' + s + '"' : s);
    return [auto.command, ...(auto.args || [])].map(q).join(" ");
  }

  function mergedConfig() {
    // the UI-visible knobs win; everything else (env/headers/cwd) comes from the raw editor
    let raw;
    try { raw = JSON.parse($("rawConfig").value); } catch (_) { raw = null; }
    const base = raw && typeof raw === "object" ? raw : configFromState(state || {});
    base.enabled = $("toolsEnabled").checked;
    base.clerk_role = $("clerkRole").value;
    base.limits = {
      max_calls_per_turn: Number($("limCalls").value) || 3,
      call_timeout_s: Number($("limTimeout").value) || 20,
      poll_interval_s: Number($("limPoll").value) || 2.5,
    };
    base.mcpServers = base.mcpServers || {};
    document.querySelectorAll("[data-server-toggle]").forEach((input) => {
      const name = input.getAttribute("data-server-toggle");
      if (base.mcpServers[name]) base.mcpServers[name].enabled = input.checked;
    });
    document.querySelectorAll("select[data-policy-server]").forEach((select) => {
      const name = select.getAttribute("data-policy-server");
      const tool = select.getAttribute("data-policy-tool");
      if (base.mcpServers[name]) {
        base.mcpServers[name].tools = base.mcpServers[name].tools || {};
        base.mcpServers[name].tools[tool] = select.value;
      }
    });
    document.querySelectorAll("input[data-autostart]").forEach((input) => {
      const name = input.getAttribute("data-autostart");
      const entry = base.mcpServers[name];
      if (!entry) return;
      const parts = splitCommand(input.value.trim());
      if (!parts.length) { delete entry.autostart; return; }
      const prev = entry.autostart && typeof entry.autostart === "object" ? entry.autostart : {};
      entry.autostart = { ...prev, command: parts[0], args: parts.slice(1) };   // cwd/env from the raw editor survive
    });
    document.querySelectorAll("textarea[data-note]").forEach((area) => {
      const name = area.getAttribute("data-note");
      if (base.mcpServers[name]) {
        const note = area.value.trim();
        if (note) base.mcpServers[name].persona_note = note; else delete base.mcpServers[name].persona_note;
      }
    });
    return base;
  }

  // ── the IoT safety statement (docs/IOT_DISCLAIMER.md): IoT turns on only after it was read and accepted ──
  // The brain and the gateway refuse a config that switches a smart-home server on before that (409, code
  // iot_disclaimer_required); this page asks first, and answers such a refusal with the same dialog.
  const consent = { doc: null, resolve: null, promise: null, mode: null, autoShown: false, manualLanguage: false };

  function iotAccepted() { return !!(state && state.iot_disclaimer && state.iot_disclaimer.accepted); }
  function isSmartHome(name) { return !!(state && state.servers && state.servers[name] && state.servers[name].iot); }
  function turnsOnIot(cfg) {
    return Object.entries((cfg && cfg.mcpServers) || {}).some(([name, entry]) => entry && entry.enabled && isSmartHome(name));
  }

  function inlineText(text) {               // the statement's **bold**; everything else stays plain text
    const frag = document.createDocumentFragment();
    String(text || "").split("**").forEach((part, i) => {
      if (part) frag.append(i % 2 ? el("strong", { text: part }) : document.createTextNode(part));
    });
    return frag;
  }

  function showStatement(lang) {
    const languages = (consent.doc && consent.doc.statement && consent.doc.statement.languages) || {};
    const section = languages[lang] || languages.en;
    if (!section) return;
    const box = $("iotConsentText");
    box.replaceChildren(...section.blocks.map((block) =>
      block.type === "h" ? el("h4", {}, inlineText(block.text))
        : block.type === "ul" ? el("ul", {}, ...block.items.map((item) => el("li", {}, inlineText(item))))
          : el("p", {}, inlineText(block.text))));
    box.setAttribute("lang", lang === "zh" ? "zh-CN" : languages[lang] ? lang : "en");
    box.scrollTop = 0;
    document.querySelectorAll(".oa-consent-lang").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.lang === lang)));
  }

  // mode "accept": resolves true once the person ticked the box, pressed Enable IoT and the acceptance was recorded;
  // false on Cancel / Escape (IoT stays off); null when the statement could not even be loaded (already said so).
  // mode "view": the statement with a Close button.
  async function openConsent(mode) {
    const dialog = $("iotConsent");
    if (dialog.open) return mode !== "view" && consent.mode === "accept" ? consent.promise : false;
    try { consent.doc = await getJSON("/api/build_f/iot/disclaimer"); }
    catch (error) {
      toast(t("tools.loadStatementError", { error: error.message || error }), true);
      return null;
    }
    if (dialog.open) return false;
    const doc = consent.doc, accepting = mode !== "view";
    consent.mode = accepting ? "accept" : "view";
    consent.manualLanguage = false;
    text($("iotConsentVersion"), () => t("tools.version", { version: doc.version }));
    text($("iotConsentLead"), () => accepting ? t("tools.consentLead")
      : doc.accepted ? t("tools.acceptedView", { date: dateNote(doc.accepted_at) }) : t("tools.viewOff"));
    const changed = $("iotConsentChanged");
    changed.hidden = !(accepting && doc.accepted_version && doc.accepted_version !== doc.version);
    text(changed, () => t("tools.changed", { version: doc.accepted_version }));
    $("iotConsentAccept").hidden = !accepting;
    $("iotConsentEnable").hidden = !accepting;
    text($("iotConsentCancel"), () => t(accepting ? "tools.cancel" : "tools.close"));
    $("iotConsentCheck").checked = false;
    $("iotConsentEnable").disabled = true;
    $("iotConsentError").hidden = true;
    showStatement(window.OAI18n.getLocale());
    dialog.showModal();
    $("iotConsentText").focus();
    consent.promise = new Promise((resolve) => { consent.resolve = resolve; });
    return consent.promise;
  }

  function closeConsent(result) {
    const resolve = consent.resolve;
    consent.resolve = null;
    consent.promise = null;
    consent.mode = null;
    if ($("iotConsent").open) $("iotConsent").close();
    if (resolve) resolve(result);
  }

  $("iotConsentCheck").addEventListener("change", () => { $("iotConsentEnable").disabled = !$("iotConsentCheck").checked; });
  $("iotConsentCancel").addEventListener("click", () => closeConsent(false));
  $("iotConsent").addEventListener("cancel", (event) => { event.preventDefault(); closeConsent(false); });   // Escape
  $("iotConsent").addEventListener("close", () => { if (consent.resolve) closeConsent(false); });
  document.querySelectorAll(".oa-consent-lang").forEach((b) => b.addEventListener("click", () => {
    consent.manualLanguage = true;
    showStatement(b.dataset.lang);
  }));
  $("iotConsentEnable").addEventListener("click", async () => {
    const button = $("iotConsentEnable");
    if (!$("iotConsentCheck").checked || !consent.doc) return;
    button.disabled = true;
    try {
      const result = await postAction("/api/build_f/iot/disclaimer", "iot-disclaimer", { accept: true, version: consent.doc.version });
      if (state) state.iot_disclaimer = result.iot_disclaimer;
      renderConsent(result.iot_disclaimer);
      closeConsent(true);
    } catch (error) {
      const box = $("iotConsentError");
      box.hidden = false;
      text(box, () => t("tools.recordError", { error: error.message || error }));
      button.disabled = !$("iotConsentCheck").checked;
    }
  });

  // the safety line in the Smart Home and IoT card: accepted (which version, when), held off, or not asked yet
  function renderConsent(c) {
    if (!c) return;
    const held = !c.accepted && Array.isArray(c.held) && c.held.length > 0;
    $("iotSafety").classList.toggle("held", held);
    text($("iotConsentState"), () => c.accepted
      ? t("tools.acceptedState", { version: c.version, date: dateNote(c.accepted_at) })
      : held && c.accepted_version
        ? t("tools.heldChanged", { old: c.accepted_version, version: c.version })
        : held ? t("tools.held", { servers: c.held.join(", "), version: c.version }) : t("tools.consentOff"));
    const button = $("iotConsentOpen");
    button.removeAttribute("data-i18n");
    text(button, () => t(held ? "tools.readAccept" : "tools.readStatement"));
    button.classList.toggle("primary", held);
    button.dataset.mode = held ? "accept" : "view";
  }

  async function acceptHeld() {
    if (await openConsent("accept")) {
      toast(t("tools.acceptedToast"));
      refresh();
      iotRefresh();
    }
  }
  $("iotConsentOpen").addEventListener("click", () => {
    if ($("iotConsentOpen").dataset.mode === "accept") acceptHeld();
    else openConsent("view");
  });

  // false when the person did not accept the statement: then nothing is saved and the cards show IoT off again
  // (the raw editor keeps what was typed in it)
  async function consentFirst() {
    const accepted = await openConsent("accept");
    if (accepted) return true;
    if (state) renderServers(state);
    if (accepted === false) toast(t("tools.nothingSaved"));
    return false;
  }

  async function save(cfg) {
    // a smart-home server switched on before the statement was accepted: the statement first; Cancel = nothing saved
    if (turnsOnIot(cfg) && !iotAccepted() && !(await consentFirst())) return;
    let result;
    try { result = await postAction("/api/build_f/tools/config", "tools-config", { config: cfg }); }
    catch (error) {
      if (error.code !== "iot_disclaimer_required") throw error;
      if (!(await consentFirst())) return;        // the server knew better (a new entry, or another tab): same dialog
      result = await postAction("/api/build_f/tools/config", "tools-config", { config: cfg });
    }
    apply(result);
    toast(t("tools.savedSettings"));
  }

  function apply(s) {
    state = s;
    renderConsent(s.iot_disclaimer);
    // switched on but held off (an install from before the statement, or a new version of it): ask once per visit
    const c = s.iot_disclaimer;
    if (c && !c.accepted && Array.isArray(c.held) && c.held.length && !consent.autoShown) {
      consent.autoShown = true;
      acceptHeld();
    }
    $("toolsEnabled").checked = !!s.enabled;
    $("clerkRole").value = s.clerk_role || "surface";
    const limits = s.limits || {};
    $("limCalls").value = limits.max_calls_per_turn || 3;
    $("limTimeout").value = limits.call_timeout_s || 20;
    $("limPoll").value = limits.poll_interval_s || 2.5;
    if (document.activeElement !== $("rawConfig")) {
      $("rawConfig").value = JSON.stringify(configFromState(s), null, 2);
    }
    renderServers(s);
    renderLog(s);
    pruneBindings();
  }

  function renderServers(s) {
    const box = $("serversBox");
    box.replaceChildren();
    const entries = Object.entries(s.servers || {});
    if (!entries.length) {
      box.append(el("section", { class: "tech-card" },
        el("div", { class: "card-hint", i18n: "tools.noServers" })));
      return;
    }
    for (const [name, server] of entries) {
      const card = el("section", { class: "tech-card server-card" });
      const toggle = el("input", { type: "checkbox", "data-server-toggle": name });
      // a smart-home server held off by the IoT safety statement shows as off: it is off until the statement is accepted
      toggle.checked = !!server.enabled && !server.blocked;
      toggle.addEventListener("change", () => save(mergedConfig()).catch((e) => toast(t("tools.actionError", { error: e.message || e }), true)));
      // dot: grey = disabled · amber = enabled but the bridge is not up · red = bridge up, the agent itself unreachable · green = all good
      const health = server.health || null;
      const agentDown = !!(server.connected && health && health.ok === false);
      const starting = agentDown && health.reason === "starting";
      const startFailed = agentDown && health.reason === "start_failed";
      const refusing = agentDown && health.reason === "refused";      // up and authenticated, but it would not take her last task
      const noModel = agentDown && health.reason === "no_model";      // up, but its own model has no working key
      // Start only for an agent that is not up: one that answers (refusing tasks, no model, a rejected key) is running
      // already, and a second copy would only fail on its port
      const canStart = server.kind === "agent" && server.enabled && server.autostart && agentDown && !starting
        && !refusing && !noModel && health.reason !== "unauthorized";
      const head = el("div", { class: "server-head" },
        el("span", { class: "dot " + (!server.enabled ? "" : !server.connected ? "warn" : starting ? "warn" : agentDown ? "err" : "ok") }),
        el("span", { class: "name", text: name }),
        el("span", { class: "tag", render: () => server.kind === "agent" ? t("tools.agent") : server.transport }),
        health ? el("span", { class: "tag", style: starting ? "color:var(--warn);" : agentDown ? "color:var(--err);" : "",
          render: () => t(starting ? "tools.agentStarting" : startFailed ? "tools.startFailed" : refusing ? "tools.refusing"
            : noModel ? "tools.noModel" : agentDown ? "tools.unreachable" : "tools.online") + (!agentDown && health.version ? " · v" + health.version : "") }) : "",
        canStart ? el("button", {
          class: "btn small primary", i18n: "tools.start",
          onclick: async (event) => {
            event.preventDefault();
            toast(t("tools.starting", { name }));
            try {
              const result = await postAction("/api/build_f/tools/start", "tools-start", { server: name });
              toast(result.started ? t("tools.launched", { name }) : name + ": " + ((result.health || {}).detail || t("tools.notStarted")), !result.started);
              refresh();
            } catch (error) { toast(t("tools.actionError", { error: name + ": " + (error.message || error) }), true); }
          },
        }) : "",
        el("span", { class: "target mono", text: server.target || "" }),
        el("label", { class: "switch" }, toggle, el("span", { class: "track" })),
        el("button", {
          class: "btn small", i18n: "tools.test",
          onclick: async (event) => {
            event.preventDefault();
            toast(t("tools.connecting", { name }));
            try {
              const result = await postAction("/api/build_f/tools/test", "tools-test", { server: name });
              const h = result.health;
              const agentNote = h ? (h.ok ? t("tools.agentOnlineNote") + (h.version ? " v" + h.version : "") : t("tools.agentOfflineNote", { detail: h.detail || "" })) : "";
              toast(t("tools.discovered", { name, count: (result.tools || []).length, agent: result.kind === "agent" ? t("tools.agentBridge") : "", health: agentNote }), !!(h && !h.ok));
              refresh();
            } catch (error) { toast(t("tools.actionError", { error: name + ": " + (error.message || error) }), true); }
          },
        }),
        el("button", {
          class: "btn small danger", i18n: "tools.remove", "data-pro": "",   // deleting a server from tools.json: Professional only
          onclick: async (event) => {
            event.preventDefault();
            if (!window.confirm(t("tools.removeConfirm", { name }))) return;
            const cfg = mergedConfig();
            delete cfg.mcpServers[name];
            save(cfg).catch((e) => toast(t("tools.actionError", { error: e.message || e }), true));
          },
        }));
      card.append(head);
      if (server.blocked) card.append(el("div", { class: "card-hint", style: "color:var(--warn);margin-top:8px;",
        i18n: "tools.blocked" }));
      else if (server.error) card.append(el("div", { class: "card-hint", style: "color:var(--err);margin-top:8px;", text: server.error }));
      if (starting) card.append(el("div", { class: "card-hint", style: "margin-top:8px;", render: () => t("tools.startingDetail", { detail: health.detail || t("tools.startingShort") }) }));
      else if (agentDown) card.append(el("div", { class: "card-hint", style: "color:var(--err);margin-top:8px;",
        render: () => (health.detail || t("tools.bridgeNoAnswer")) + t(refusing ? "tools.refuseHelp" : noModel ? "tools.modelHelp" : "tools.unreachableHelp") }));
      if (health && health.ok && health.note) card.append(el("div", { class: "card-hint", style: "margin-top:8px;", text: health.note }));
      if (server.kind === "agent") {
        const startField = el("div", { class: "field", style: "margin-top:10px;", "data-pro": "" },   // Professional only
          el("label", { i18n: "tools.startCommand" }));
        const startInput = el("input", { type: "text", class: "mono", "data-autostart": name, spellcheck: "false",
          placeholder: name === "nanomuse" ? "C:\\OpenAmika\\Nanomuse\\venv\\Scripts\\nanomuse.exe serve --config C:\\OpenAmika\\Nanomuse\\data\\config.toml --no-qr --host 127.0.0.1 --port 8787" : "%LOCALAPPDATA%\\hermes\\bin\\hermes.exe gateway" });
        startInput.value = joinCommand(server.autostart);
        startField.append(startInput);
        card.append(startField);
      }
      // what she is told about this server (in character, Chinese like the rest of her prompts)
      const noteField = el("div", { class: "field", style: "margin-top:10px;", "data-pro": "" },   // Professional only
        el("label", { i18n: "tools.personaNote" }));
      const area = el("textarea", { class: "mono", rows: "3", "data-note": name, spellcheck: "false",
        placeholder: t(server.kind === "agent" ? "tools.agentExample" : "tools.deviceExample"),
        "data-i18n-placeholder": server.kind === "agent" ? "tools.agentExample" : "tools.deviceExample" });
      area.value = server.persona_note || "";
      noteField.append(area);
      card.append(noteField);
      if (server.tools && server.tools.length) {
        const table = el("table", { class: "oa-table", style: "margin-top:10px;" });
        table.append(el("thead", {}, el("tr", {}, el("th", { i18n: "tools.tool" }), el("th", { i18n: "tools.description" }), el("th", { i18n: "tools.policy" }))));
        const body = el("tbody");
        for (const tool of server.tools) {
          const select = el("select", { class: "policy-select", "data-policy-server": name, "data-policy-tool": tool.name });
          for (const policy of ["auto", "confirm", "deny"]) select.append(el("option", { value: policy, i18n: "tools." + policy }));
          select.value = tool.policy || "confirm";
          select.addEventListener("change", () => save(mergedConfig()).catch((e) => toast(t("tools.actionError", { error: e.message || e }), true)));
          body.append(el("tr", {}, el("td", { text: tool.name }), el("td", { text: (tool.description || "").slice(0, 160) }), el("td", {}, select)));
        }
        table.append(body);
        card.append(el("div", { class: "table-scroll", "data-pro": "" }, table));   // per-tool policies: Professional only
      } else if (server.enabled && !server.blocked) {
        card.append(el("div", { class: "card-hint", style: "margin-top:8px;", i18n: "tools.noTools" }));
      }
      // the smart-home server lives inside the Smart Home and IoT panel, above its devices, without its own card chrome
      if (name === "iot") { card.classList.add("embedded"); $("iotServer").replaceChildren(card); }
      else box.append(card);
    }
  }

  function renderLog(s) {
    const body = $("logBody");
    const log = (s.log || []).slice().reverse();
    body.replaceChildren();
    if (!log.length) {
      body.append(el("tr", {}, el("td", { colspan: "5", class: "card-hint", i18n: "tools.noCalls" })));
      return;
    }
    for (const entry of log) {
      const when = new Date((entry.ts || 0) * 1000);
      const outcome = entry.ok === null ? "pending" : entry.ok ? "ok"
        : (entry.policy === "refused" ? "refused" : entry.policy === "unreachable" ? "notSent" : "error");
      const detail = () => (entry.result || "").slice(0, 120) + (entry.quote ? t("tools.quote", { quote: String(entry.quote).slice(0, 60) }) : "");
      body.append(el("tr", {},
        el("td", { render: () => when.toLocaleTimeString(window.OAI18n.getLocale()) }),
        el("td", { text: entry.server + "__" + entry.tool }),
        el("td", {}, el("code", { text: JSON.stringify(entry.arguments || {}).slice(0, 80) })),
        el("td", { render: () => t("tools." + outcome) + (entry.policy === "confirmed" ? t("tools.approved") : "") }),
        el("td", { render: detail })));
    }
  }

  $("toolsSave").addEventListener("click", () => save(mergedConfig()).catch((e) => toast(t("tools.actionError", { error: e.message || e }), true)));
  $("rawSave").addEventListener("click", () => {
    let raw;
    try { raw = JSON.parse($("rawConfig").value); }
    catch (error) { toast(t("tools.rawError", { error: error.message }), true); return; }
    save(raw).catch((e) => toast(t("tools.actionError", { error: e.message || e }), true));
  });

  $("addTransport").addEventListener("change", () => {
    const http = $("addTransport").value === "http";
    text($("addTargetLabel"), () => t(http ? "tools.url" : "tools.command"));
    $("addTarget").placeholder = http ? "http://homeassistant.local:8123/mcp_server/sse" : "python -m openamika_agents hermes";
  });
  $("addBtn").addEventListener("click", () => {
    const name = $("addName").value.trim();
    const target = $("addTarget").value.trim();
    if (!/^[A-Za-z0-9_-]{1,32}$/.test(name)) { toast(t("tools.invalidName"), true); return; }
    if (!target) { toast(t("tools.targetRequired"), true); return; }
    const cfg = mergedConfig();
    if (cfg.mcpServers[name]) { toast(t("tools.exists"), true); return; }
    if ($("addTransport").value === "http") {
      cfg.mcpServers[name] = { url: target, enabled: false };
    } else {
      const parts = target.split(/\s+/);
      cfg.mcpServers[name] = { command: parts[0], args: parts.slice(1), enabled: false };
      if (/openamika_agents/.test(target)) { cfg.mcpServers[name].kind = "agent"; cfg.mcpServers[name].cwd = "../servers/openamika-agents"; }
    }
    save(cfg).then(() => { $("addName").value = ""; $("addTarget").value = ""; })
      .catch((e) => toast(t("tools.actionError", { error: e.message || e }), true));
  });

  // ── smart home: the plugs by hand (brain /api/build_f/iot — she reaches the same server through MCP) ──
  const iot = { timer: null, cards: new Map(), permit: false };
  const iotNum = (v, digits) => (typeof v === "number" && Number.isFinite(v) ? v.toLocaleString(window.OAI18n.getLocale(), { minimumFractionDigits: digits, maximumFractionDigits: digits }) : null);
  function iotAgo(epoch) {
    const s = Math.max(0, Date.now() / 1000 - (Number(epoch) || 0));
    if (s < 60) return t("tools.justNow");
    if (s < 3600) return t("tools.minutesAgo", { count: Math.round(s / 60) });
    if (s < 86400) return t("tools.hoursAgo", { count: Math.round(s / 3600) });
    return t("tools.daysAgo", { count: Math.round(s / 86400) });
  }
  const iotClock = (epoch) => new Date((Number(epoch) || 0) * 1000).toLocaleTimeString(window.OAI18n.getLocale(), { hour: "2-digit", minute: "2-digit" });
  async function iotPost(url, action, body) {
    try { return await postAction(url, action, body); }
    catch (error) { toast(t("tools.actionError", { error: error.message || error }), true); return null; }   // 409 while she speaks: the detail says so, just retry
  }
  function iotLight(d) {                 // [dot class, text to show]
    if (!d || !d.enabled) return ["", t("tools.serverOff")];
    if (d.blocked) return ["warn", t("tools.consentBlocked")];
    if (!d.connected) return ["err", (d.health && d.health.detail) || t("tools.disconnected")];
    if (d.health && d.health.ok === false) return ["warn", d.health.detail || d.health.reason || t("tools.degraded")];
    return ["ok", ""];
  }
  // one card per device, built once and updated in place so a nickname being typed survives the refresh
  function iotCard(dev) {
    const key = dev.friendly_name;
    const card = el("div", { class: "iot-dev" });
    const name = el("b"), sub = el("div", { class: "card-hint" }), state = el("span", { class: "iot-state" });
    const readings = el("div", { class: "iot-readings mono" }), seen = el("div", { class: "card-hint" });
    const flags = el("div", { class: "card-hint mono", "data-pro": "" });
    const actions = el("div", { class: "iot-actions" });
    const setState = (st) => {
      const s = String(st || "unknown").toUpperCase();
      state.dataset.state = s;
      text(state, () => t(s === "ON" ? "tools.stateOn" : s === "OFF" ? "tools.stateOff" : "tools.stateUnknown"));
      state.className = "iot-state " + (s === "ON" ? "on" : s === "OFF" ? "off" : "unknown");
    };
    const switchTo = async (action) => {
      actions.querySelectorAll("button").forEach((b) => { b.disabled = true; });
      setState(action === "toggle" ? (state.dataset.state === "ON" ? "OFF" : "ON") : action);   // optimistic; the refresh tells the truth
      const result = await iotPost("/api/build_f/iot/device", "iot-device", { device: key, action });
      const r = result && result.result;
      if (r && r.ok === false) toast(r.error || r.message || t("tools.plugNoAnswer"), true);
      actions.querySelectorAll("button").forEach((b) => { b.disabled = false; });
      iotRefresh();
    };
    for (const [label, action, cls] of [["tools.on", "on", "btn small primary"], ["tools.off", "off", "btn small"], ["tools.toggle", "toggle", "btn small"]]) {
      actions.append(el("button", { class: cls, type: "button", i18n: label, onclick: () => switchTo(action) }));
    }
    const nick = el("input", { type: "text", placeholder: t("tools.nickname"), "data-i18n-placeholder": "tools.nickname", maxlength: "40" });
    const note = el("input", { type: "text", placeholder: t("tools.deviceNote"), "data-i18n-placeholder": "tools.deviceNote", maxlength: "200" });
    for (const input of [nick, note]) input.addEventListener("input", () => { card.dataset.dirty = "yes"; });
    const save = el("button", { class: "btn small", type: "button", i18n: "tools.save", onclick: async () => {
      const was = card._dev || {};
      let ok = true;
      if (nick.value.trim() !== (was.nickname || "")) ok = !!(await iotPost("/api/build_f/iot/device", "iot-device", { device: key, nickname: nick.value.trim() })) && ok;
      if (note.value.trim() !== (was.note || "")) ok = !!(await iotPost("/api/build_f/iot/device", "iot-device", { device: key, note: note.value.trim() })) && ok;
      if (ok) { card.dataset.dirty = "no"; toast(t("tools.savedName", { name: nick.value.trim() || key })); }
      iotRefresh();
    } });
    card.update = (d) => {
      card._dev = d;
      name.textContent = d.nickname || d.friendly_name;
      sub.textContent = [d.vendor, d.model].filter(Boolean).join(" ") + (d.description ? " — " + d.description : "");
      setState(d.state);
      text(readings, () => [[d.power, 1, " W"], [d.voltage, 0, " V"], [d.current, 2, " A"], [d.energy, 2, " kWh"], [d.temperature, 0, " °C"]]
        .map(([v, digits, unit]) => { const formatted = iotNum(v, digits); return formatted === null ? null : formatted + unit; }).filter(Boolean).join(" · "));
      readings.hidden = !readings.textContent;
      // availability is only known when zigbee2mqtt's availability feature is on; "unknown" would just look broken
      const avail = d.availability === "online" || d.availability === "offline" ? d.availability : null;
      text(seen, () => [avail ? t(avail === "online" ? "tools.available" : "tools.unavailableDevice") : null, d.last_seen ? t("tools.seen", { ago: iotAgo(d.last_seen) }) : null].filter(Boolean).join(" · "));
      text(flags, () => [d.ieee, d.supported === false ? t("tools.unsupported") : d.supported ? t("tools.supported") : null,
        d.interview_completed === false ? t("tools.interviewPending") : null].filter(Boolean).join(" · "));
      card.classList.toggle("offline", d.availability === "offline");
      if (card.dataset.dirty !== "yes" && document.activeElement !== nick && document.activeElement !== note) {
        nick.value = d.nickname || "";
        note.value = d.note || "";
      }
    };
    card.append(
      el("div", { class: "iot-head" }, el("div", { class: "iot-name" }, name, sub), state),
      actions, readings, seen,
      el("div", { class: "iot-edit" }, nick, el("div", { class: "row" }, note, save)),
      flags);
    card.update(dev);
    return card;
  }
  function renderIot(d) {
    const [level, detail] = iotLight(d);
    $("iotDot").className = "dot " + level;
    if (d && d.iot_disclaimer) renderConsent(d.iot_disclaimer);
    const devices = d && d.enabled && Array.isArray(d.devices) ? d.devices : [];
    const on = devices.filter((x) => String(x.state).toUpperCase() === "ON").length;
    text($("iotSub"), () => !d || !d.enabled ? t("tools.noHomeEnabled") : d.blocked ? t("tools.offNotAccepted")
      : !d.connected ? t("tools.disconnected") : t("tools.deviceCount", { count: devices.length, on }));
    const hint = $("iotHint");
    hint.style.color = level === "err" ? "var(--err)" : level === "warn" ? "var(--warn)" : "";
    text(hint, () => !d || !d.enabled ? iotLight(d)[1] : iotLight(d)[1] || (!devices.length ? t("tools.noDevices") : ""));
    hint.hidden = !hint.textContent;
    const box = $("iotDevices"), present = new Set();
    for (const dev of devices) {
      const key = dev.friendly_name || dev.ieee;
      if (!key) continue;
      present.add(key);
      let card = iot.cards.get(key);
      if (!card) { card = iotCard({ ...dev, friendly_name: key }); iot.cards.set(key, card); box.append(card); }
      else card.update(dev);
    }
    for (const [key, card] of iot.cards) if (!present.has(key)) { card.remove(); iot.cards.delete(key); }
    // pairing: Find opens permit-join for ~4 minutes; the note counts down from permit_join_end
    const disc = (d && d.discovery) || {};
    iot.permit = !!disc.permit_join;
    const left = iot.permit && disc.permit_join_end ? Math.max(0, Math.round(Number(disc.permit_join_end) - Date.now() / 1000)) : 0;
    $("iotPairBtn").hidden = iot.permit;
    $("iotPairBtn").disabled = !d || !d.enabled || !d.connected;
    $("iotPairStop").hidden = !iot.permit;
    text($("iotPairNote"), () => iot.permit
      ? t("tools.pairing", { left: left ? t("tools.left", { time: Math.floor(left / 60) + ":" + String(left % 60).padStart(2, "0") }) : "" })
      : disc.zigbee2mqtt_online === false && d && d.connected ? t("tools.zigbeeOffline") : t("tools.pairHint"));
    const events = (Array.isArray(disc.events) ? disc.events : []).slice().sort((a, b) => (b.at || 0) - (a.at || 0)).slice(0, 8);
    $("iotEvents").replaceChildren(...events.map((e, i) =>
      el("div", { class: i === 0 ? "fresh" : "", render: () => [iotClock(e.at), e.type, e.device, e.status, e.description].filter(Boolean).join(" ") })));
    pruneBindings();
  }
  async function iotRefresh() {
    clearTimeout(iot.timer); iot.timer = null;
    if (document.hidden) return;                                   // resumes on visibilitychange
    try { renderIot(await getJSON("/api/build_f/iot")); }
    catch (error) {
      $("iotDot").className = "dot err";
      text($("iotSub"), () => t("tools.unavailable"));
      const hint = $("iotHint");
      hint.hidden = false; hint.style.color = "var(--err)";
      text(hint, () => t("tools.homeError", { error: error.message || error }));
    }
    iot.timer = setTimeout(iotRefresh, iot.permit ? 1500 : 3000);
  }
  document.addEventListener("visibilitychange", () => { if (!document.hidden && !iot.timer) iotRefresh(); });
  $("iotPairBtn").addEventListener("click", async () => {
    $("iotPairBtn").disabled = true;
    if (await iotPost("/api/build_f/iot/pairing", "iot-pairing", { enable: true, seconds: 254 })) toast(t("tools.pairingOpened"));
    iotRefresh();
  });
  $("iotPairStop").addEventListener("click", async () => {
    if (await iotPost("/api/build_f/iot/pairing", "iot-pairing", { enable: false })) toast(t("tools.pairingClosed"));
    iotRefresh();
  });
  iotRefresh();

  async function refresh() {
    try { apply(await getJSON("/api/build_f/tools")); }
    catch (error) {
      $("serversBox").replaceChildren(el("section", { class: "tech-card" },
        el("div", { class: "card-hint", render: () => t("tools.toolsError", { error: error.message || error }) })));
    }
  }
  refresh();
  setInterval(() => { if (!document.hidden) refresh(); }, 5000);
})();
