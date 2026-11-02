"use strict";
const loadChat = () => { try { return JSON.parse(localStorage.getItem("hf_chat") || "[]"); } catch (_) { return []; } };
const saveChat = () => { try { localStorage.setItem("hf_chat", JSON.stringify(S.chat.msgs.filter((m) => !m.pending).slice(-40))); } catch (_) { /* storage may be unavailable */ } };
const S = { st: null, view: "home", wsId: null, taskId: null, events: [], task: null, es: null, tab: "changes", mode: "build", tasks: [], hw: null, navOpen: false, live: "",
  chat: { msgs: loadChat(), web: false, kb: false, busy: false, abort: null, draft: "" }, agentDraft: "" };
const ws = () => S.st.workspaces.find((w) => w.id === S.wsId) || null;
const TERMINAL = ["completed", "completed_verified", "completed_unverified", "failed", "cancelled", "exhausted", "interrupted"];
const STATUS_TEXT = { completed_verified: "Verified", completed_unverified: "Not verified", completed: "Finished", failed: "Failed", cancelled: "Cancelled", exhausted: "Step limit reached", interrupted: "Interrupted", running: "Running", awaiting_approval: "Needs your approval", awaiting_input: "Needs your answer", queued: "Queued" };
const STATUS_CLS = { completed_verified: "ok", completed_unverified: "warn", completed: "info", failed: "bad", running: "info", awaiting_approval: "warn", awaiting_input: "warn", exhausted: "warn", interrupted: "warn" };
const badge = (s) => h("span", { class: "badge " + (STATUS_CLS[s] || "") }, STATUS_TEXT[s] || s);

async function refresh() {
  S.st = await api("/api/state");
  if (!S.wsId || !ws()) S.wsId = S.st.workspaces[0]?.id || null;
  S.tasks = S.wsId ? await api("/api/tasks?workspace_id=" + S.wsId) : [];
  render();
}
function go(v) {
  S.view = v; S.navOpen = false;
  if (v === "hardware" && !S.hw) api("/api/hardware").then((d) => { S.hw = d; if (S.view === "hardware") render(); }).catch(() => {});
  render(); const m = $("#main .page, #main .scroll"); if (m) m.scrollTop = 0;
}

// ---------------------------------------------------------------- shell
function render() {
  const draft = $("#cin"); if (draft) S.chat.draft = draft.value; const ad = $("#goal"); if (ad) S.agentDraft = ad.value;
  const app = $("#app"); app.removeAttribute("aria-busy");
  fill(app, h("div", { class: "shell" + (S.navOpen ? " navopen" : "") }, side(), h("div", { class: "col" }, topbar(), h("main", { id: "main" }, VIEWS[S.view]()))));
  const fo = $("[data-focus]"); if (fo) fo.focus();
  if (S.view === "chat") { const m = $("#msgs"); if (m) m.scrollTop = m.scrollHeight; }
}
function side() {
  const nb = (v, label, ic, dot) => h("button", { class: "navb", "aria-current": S.view === v ? "true" : "false", on: { click: () => go(v) } }, icon(ic), h("span", {}, label), dot && h("span", { class: "dot " + (dot === "ok" ? "ok" : ""), title: dot === "ok" ? "Ready" : "Needs setup" }));
  const needModel = !S.st.active, needWs = !S.st.workspaces.length;
  return h("nav", { class: "side", "aria-label": "Sections" },
    h("div", { class: "logo" }, h("i", {}, icon("spark", 18)), "Hearthforge"),
    nb("home", "Start", "home"), nb("chat", "Chat", "chat"), nb("agent", "Agent", "bot"),
    S.view === "agent" && S.tasks.length > 0 && h("div", { class: "tasklist" }, S.tasks.slice(0, 8).map((t) => h("button", { class: "navb", "aria-current": S.taskId === t.id ? "true" : "false", title: t.goal, on: { click: () => openTask(t.id) } }, h("span", {}, t.goal)))),
    h("h2", {}, "Set up"), nb("models", "Models", "cpu", needModel ? "warn" : "ok"), nb("folders", "Folders", "folder", needWs ? "warn" : "ok"), nb("internet", "Internet", "globe"),
    h("h2", {}, "Library"), nb("knowledge", "Knowledge", "book"), nb("capabilities", "Capabilities", "plug"),
    h("h2", {}, "Insight"), nb("hardware", "Hardware fit", "cpu"), nb("usage", "Usage and audit", "chart"), nb("guide", "Guide", "guide"));
}
function topbar() {
  const p = S.st.policy, a = S.st.active, net = p.internet, w = ws();
  const label = { local_only: "Local only", free_only: "Free tier only", budgeted: "Budgeted cloud" }[p.cloud_mode];
  return h("header", { class: "top" },
    h("button", { class: "btn ghost menu", "aria-label": "Menu", on: { click: () => { S.navOpen = !S.navOpen; render(); } } }, icon("menu")),
    h("button", { class: "chip " + (a ? "" : "none"), on: { click: () => (a ? openModelPicker() : openConnectWizard()) }, title: "Switch model" }, h("span", { class: "pip" }), a ? [h("strong", {}, a.model), h("small", {}, a.provider)] : h("strong", {}, "Connect a model")),
    h("button", { class: "chip " + (p.cloud_mode === "local_only" ? "local" : "remote"), on: { click: () => go("models") }, title: S.st.policy_explain.summary }, icon("shield", 15), h("strong", {}, label)),
    h("button", { class: "chip " + (net === "off" ? "off" : "remote"), on: { click: () => go("internet") }, title: "Internet access for search and fetching pages" }, icon("globe", 15), "Internet: " + { off: "off", ask: "ask", on: "on" }[net]),
    h("button", { class: "chip", on: { click: () => (w ? go("folders") : openFolderPicker()) } }, icon("folder", 15), w ? w.name : "Open a folder"),
    h("span", { class: "spacer" }),
    h("button", { class: "btn sm", on: { click: openPalette }, title: "Command palette" }, icon("search", 15), "Actions ", h("span", { class: "kbd" }, "Ctrl K")));
}

// ---------------------------------------------------------------- Home
function homeView() {
  const hasModel = !!S.st.active, hasWs = S.st.workspaces.length > 0, net = S.st.policy.internet;
  const step = (n, done, title, text, btn) => h("div", { class: "card step" + (done ? " done" : "") }, h("span", { class: "num" }, done ? icon("check", 16) : n), h("h3", {}, title), h("p", {}, text), btn);
  const tile = (ic, title, text, on, dis) => h("button", { class: "card tile" + (dis ? " disabled" : ""), on: { click: on } }, h("i", {}, icon(ic)), h("span", {}, h("strong", {}, title), h("span", { class: "muted" }, text)));
  return h("div", { class: "page" }, h("div", { class: "wrap" },
    h("div", { class: "hero" }, h("h1", {}, "Your AI development workstation"), h("p", { class: "lede" }, "Chat with any model, or let an agent read, edit and test your project. Every risky step waits for your approval, and nothing leaves your machine unless you allow it.")),
    h("div", { class: "steps" },
      step(1, hasModel, hasModel ? "Model connected" : "Connect a model", hasModel ? `${S.st.active.model} via ${S.st.active.provider}` : "Local (Ollama, LM Studio, llama.cpp) or a gateway/cloud service such as OmniRoute or OpenRouter.", h("div", { class: "row" }, h("button", { class: "btn primary", on: { click: () => openConnectWizard() } }, icon(hasModel ? "plus" : "plug", 16), hasModel ? "Add another" : "Connect a model"), hasModel && h("button", { class: "btn", on: { click: openModelPicker } }, "Switch"))),
      step(2, hasWs, hasWs ? "Folder opened" : "Open a project folder", hasWs ? (ws()?.name || "") + " · " + (ws()?.path || "") : "Pick the folder the agent may work in. It can't touch anything outside it.", h("button", { class: "btn primary", on: { click: () => openFolderPicker() } }, icon("folder", 16), hasWs ? "Open another" : "Open a folder")),
      step(3, net !== "off", net !== "off" ? "Internet enabled" : "Internet (optional)", net !== "off" ? "Search and page reading are available" + (net === "ask" ? " (asks first)." : ".") : "Let chat and the agent search the web and read pages. Off by default.", h("button", { class: "btn", on: { click: () => go("internet") } }, icon("globe", 16), "Internet settings"))),
    h("h2", { class: "t" }, "What would you like to do?"),
    h("div", { class: "grid" },
      tile("chat", "Chat", "Ask questions, get code, optionally with web search.", () => (hasModel ? go("chat") : openConnectWizard()), !hasModel),
      tile("bot", "Let the agent work on a project", "Plan or build with diffs you approve and tests it runs.", () => (!hasModel ? openConnectWizard() : !hasWs ? openFolderPicker() : go("agent")), !hasModel || !hasWs),
      tile("book", "Index my project for search", "Ask questions with cited excerpts from your files.", () => (hasWs ? go("knowledge") : openFolderPicker()), !hasWs),
      tile("guide", "Read the guide", "Step-by-step: every provider and feature.", () => go("guide"))),
    h("p", { class: "muted small" }, "Tip: press ", h("span", { class: "kbd" }, "Ctrl K"), " anywhere to jump to any action.")));
}

// ---------------------------------------------------------------- Connect wizard
const PRESETS = [
  { id: "ollama", name: "Ollama", url: "http://127.0.0.1:11434", kind: "ollama", hint: "Local and private. Install Ollama, run `ollama pull <model>`, and keep it running. No key needed." },
  { id: "omniroute", name: "OmniRoute", url: "http://localhost:20128/v1", key: true, hint: "Use the URL from your OmniRoute dashboard and an API/endpoint key you created there. Model names look like `auto` or `provider/model`." },
  { id: "lmstudio", name: "LM Studio", url: "http://127.0.0.1:1234/v1", hint: "Start the Local Server in LM Studio and load a model." },
  { id: "llamacpp", name: "llama.cpp", url: "http://127.0.0.1:8080/v1", hint: "Run `llama-server -m model.gguf` first." },
  { id: "openrouter", name: "OpenRouter", url: "https://openrouter.ai/api/v1", key: true, hint: "Key from openrouter.ai/keys. Model ids look like `vendor/model`." },
  { id: "groq", name: "Groq", url: "https://api.groq.com/openai/v1", key: true, hint: "Key from the Groq console." },
  { id: "gemini", name: "Gemini", url: "https://generativelanguage.googleapis.com/v1beta/openai/", key: true, hint: "Key from Google AI Studio." },
  { id: "hf", name: "Hugging Face", url: "https://router.huggingface.co/v1", key: true, hint: "Access token from your Hugging Face settings." },
  { id: "custom", name: "Custom", url: "", key: true, hint: "Any OpenAI-compatible service. The base URL usually ends in `/v1`." },
];
async function streamChat(body, { onDelta, onSources, signal } = {}) {
  const r = await fetch("/api/chat", { method: "POST", credentials: "same-origin", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body), signal });
  if (!r.ok) { const j = await r.json().catch(() => ({})); const e = new Error(j.detail || r.statusText); e.status = r.status; throw e; }
  const rd = r.body.getReader(), dec = new TextDecoder(); let buf = "", usage = null;
  for (;;) {
    const { done, value } = await rd.read(); if (done) break; buf += dec.decode(value, { stream: true });
    let i; while ((i = buf.indexOf("\n\n")) >= 0) {
      const ch = buf.slice(0, i); buf = buf.slice(i + 2); if (!ch.startsWith("data:")) continue;
      const ev = JSON.parse(ch.slice(5));
      if (ev.type === "delta") onDelta && onDelta(ev.text); else if (ev.type === "sources") onSources && onSources(ev.sources);
      else if (ev.type === "done") usage = ev.usage; else if (ev.type === "error") throw new Error(ev.message); else if (ev.type === "notice") toast(ev.text);
    }
  }
  return usage;
}
function openConnectWizard(preset) {
  const W = { step: 1, preset: preset ? preset.id : null, name: preset?.name || "", url: preset?.url || "", key: "", cost: "unsure", consent: false, showKey: false, busy: false, error: null, models: [], model: "", kind: preset?.kind || "auto", filter: "", res: null, test: null };
  const m = openModal({ title: "Connect a model", wide: true });
  const bar = () => h("div", { class: "progress" }, [1, 2, 3].map((i) => h("i", { class: i <= W.step ? "on" : "" })));
  const remote = () => !!W.url.trim() && !isLocalUrl(W.url.trim());
  const pick = (p) => { W.preset = p.id; W.url = p.url; W.name = p.name; W.kind = p.kind || "auto"; paint(); };
  function paint() { ({ 1: step1, 2: step2, 3: step3 })[W.step](); }
  function step1() {
    const cur = PRESETS.find((p) => p.id === W.preset);
    const nameI = h("input", { type: "text", value: W.name, placeholder: "e.g. My gateway", "aria-label": "Name", on: { input: (e) => (W.name = e.target.value) } });
    const urlI = h("input", { type: "text", value: W.url, placeholder: "http://localhost:20128/v1", "aria-label": "Base URL", spellcheck: "false", "data-autofocus": "1", on: { input: (e) => { W.url = e.target.value; } , change: () => paint() } });
    const keyI = h("input", { type: W.showKey ? "text" : "password", value: W.key, placeholder: remote() || cur?.key ? "API key" : "Not needed for most local servers", "aria-label": "API key", autocomplete: "off", spellcheck: "false", on: { input: (e) => (W.key = e.target.value) } });
    const go_ = async () => {
      if (!W.url.trim()) { urlI.focus(); toast("Enter the service URL"); return; }
      if (remote() && !W.consent) { toast("Tick the box to confirm you want to contact this remote service"); return; }
      W.busy = true; W.error = null; paint();
      try {
        const r = await api("/api/providers/probe", "POST", { base_url: W.url.trim(), key: W.key.trim(), kind: W.kind, allow_remote: W.consent || !remote() }, { quiet: true });
        if (r.ok) { W.url = r.base_url; W.kind = r.kind; W.models = r.models; W.model = r.models.includes("auto") ? "auto" : (r.models[0] || ""); W.step = 2; }
        else W.error = { message: r.error?.message || "Could not connect", hint: r.hint || "" };
      } catch (e) { W.error = { message: e.message, hint: "" }; }
      W.busy = false; paint();
    };
    m.set([bar(),
      h("p", { class: "muted" }, "Pick a service to prefill its address, or enter your own."),
      h("div", { class: "chips" }, PRESETS.map((p) => h("button", { class: "chipbtn", "aria-pressed": W.preset === p.id ? "true" : "false", on: { click: () => pick(p) } }, p.name))),
      cur && h("div", { class: "notice" }, inlineMd(cur.hint)),
      h("label", { class: "f" }, h("span", {}, "Name"), nameI),
      h("label", { class: "f" }, h("span", {}, "Base URL"), urlI, h("small", {}, "Paste whatever you have: a missing `/v1`, trailing slash or `/chat/completions` is fixed automatically.")),
      h("label", { class: "f" }, h("span", {}, "API key"), h("div", { class: "row", style: false }, keyI, h("button", { class: "btn sm", type: "button", on: { click: () => { W.showKey = !W.showKey; keyI.type = W.showKey ? "text" : "password"; } } }, "Show/hide")), h("small", {}, "Stored in your OS keychain, never in a file or the UI.")),
      remote() && h("div", { class: "notice warn" }, h("strong", {}, `${hostOf(W.url)} is a remote service.`), " Your prompts, code excerpts you send, and the key will go there.",
        h("label", { class: "row" }, h("input", { type: "checkbox", checked: W.consent, on: { change: (e) => { W.consent = e.target.checked; } } }), `I allow Hearthforge to send data to ${hostOf(W.url)}`),
        h("div", { class: "small muted" }, "Is this service free to use?"),
        h("div", { class: "chips" }, [["free", "Free tier"], ["paid", "Paid"], ["unsure", "Not sure"]].map(([v, l]) => h("button", { class: "chipbtn", type: "button", "aria-pressed": W.cost === v ? "true" : "false", on: { click: () => { W.cost = v; paint(); } } }, l))),
        h("div", { class: "small muted" }, "Hearthforge will switch its privacy mode just enough to allow this (you'll see what changed).")),
      W.busy && h("div", { class: "notice" }, h("span", { class: "spin" }), " Contacting the server…"),
      W.error && h("div", { class: "notice bad" }, h("strong", {}, W.error.message), W.error.hint && h("div", {}, W.error.hint), h("div", { class: "row" }, h("button", { class: "btn sm", on: { click: () => { W.step = 2; W.error = null; paint(); } } }, "Continue without detection (type a model name)")))],
      [h("button", { class: "btn", on: { click: () => m.close() } }, "Cancel"), h("button", { class: "btn primary", disabled: W.busy, on: { click: act(go_) } }, "Connect and find models")]);
  }
  function step2() {
    const list = W.models.filter((x) => x.toLowerCase().includes(W.filter.toLowerCase()));
    const manual = h("input", { type: "text", value: W.model, placeholder: "e.g. auto, llama3.2, vendor/model", "aria-label": "Model name", spellcheck: "false", on: { input: (e) => { W.model = e.target.value; $$sel(); } } });
    const $$sel = () => m.el.querySelectorAll(".item").forEach((i) => i.setAttribute("aria-selected", i.dataset.model === W.model ? "true" : "false"));
    const useIt = act(async () => {
      if (!W.model.trim()) { manual.focus(); toast("Choose or type a model name"); return; }
      const r = await api("/api/providers/connect", "POST", { name: W.name || hostOf(W.url), base_url: W.url, kind: W.kind === "auto" ? "openai_compat" : W.kind, key: W.key.trim() || undefined, cost: W.cost, allow_remote: W.consent || !remote(), model: W.model.trim() });
      S.st = r.state; W.res = r; W.step = 3; await refresh(); paint();
    });
    m.set([bar(), h("h3", {}, W.models.length ? `Found ${W.models.length} model${W.models.length === 1 ? "" : "s"}. Choose one.` : "Type the model name"),
      !W.models.length && h("div", { class: "notice" }, "No list was returned. That's fine: type the exact model name from your service's dashboard (for gateways `auto` often works)."),
      W.models.length > 8 && h("input", { type: "search", placeholder: "Filter models…", "aria-label": "Filter models", value: W.filter, on: { input: (e) => { W.filter = e.target.value; const pos = e.target.selectionStart; paint(); const f = m.el.querySelector("input[type=search]"); f.focus(); f.setSelectionRange(pos, pos); } } }),
      W.models.length > 0 && h("div", { class: "list", role: "listbox", "aria-label": "Models" }, list.map((x) => h("button", { class: "item", role: "option", "data-model": x, "aria-selected": x === W.model ? "true" : "false", on: { click: () => { W.model = x; manual.value = x; $$sel(); }, dblclick: useIt } }, h("span", { class: "grow mono" }, x)))),
      h("label", { class: "f" }, h("span", {}, "Model name"), manual, h("small", {}, "You can always change the model later from the top bar."))],
      [h("button", { class: "btn", on: { click: () => { W.step = 1; paint(); } } }, "Back"), h("button", { class: "btn primary", on: { click: useIt } }, "Use this model")]);
  }
  async function runTest() {
    W.test = { state: "run", text: "" }; paint();
    try { await streamChat({ messages: [{ role: "user", content: "Reply with one short friendly sentence confirming you work." }] }, { onDelta: (d) => { W.test.text += d; } }); W.test.state = "ok"; }
    catch (e) { W.test = { state: "bad", text: e.message }; }
    paint();
  }
  function step3() {
    const r = W.res, pc = r.policy_changed;
    if (!W.test) runTest();
    m.set([bar(), h("div", { class: "notice ok" }, h("strong", {}, `Connected: ${W.model}`), ` via ${W.name || hostOf(W.url)}. It is now your active model.`),
      pc && h("div", { class: "notice warn" }, `Privacy mode changed: ${pc.from.replace("_", " ")} → ${pc.to.replace("_", " ")} so this remote service can be used. Change it any time under Models.`),
      r.key_stored === "session" && h("div", { class: "notice warn" }, "No OS keychain found, so the key is kept in memory only until you quit Hearthforge. To keep it permanently set the environment variable ", h("code", {}, "HEARTHFORGE_KEY_" + r.provider.toUpperCase().replace(/[^A-Z0-9]/g, "_")), "."),
      h("h3", {}, "Test message"),
      !W.test || W.test.state === "run" ? h("div", { class: "notice" }, h("span", { class: "spin" }), " Asking the model… ", h("span", { class: "muted" }, W.test?.text)) :
        W.test.state === "ok" ? h("div", { class: "notice ok" }, "✔ Works. The model said: ", h("em", {}, W.test.text.trim().slice(0, 300))) :
        h("div", { class: "notice bad" }, h("strong", {}, "The connection saved but the test failed: "), W.test.text, h("div", { class: "small" }, "Check the model name, the key, and that the service is running. You can switch model from the top bar."))],
      [h("button", { class: "btn", on: { click: () => { W.test = null; paint(); } } }, "Test again"), h("button", { class: "btn", on: { click: () => m.close() } }, "Close"), h("button", { class: "btn primary", on: { click: () => { m.close(); go("chat"); } } }, "Start chatting")]);
  }
  paint();
}

// ---------------------------------------------------------------- folder picker
function openFolderPicker(opts = {}) {
  const P = { data: null, error: "", busy: true, mk: false, typed: "", req: 0 };
  const m = openModal({ title: "Open a folder", wide: true });
  async function load(path) {
    const mine = ++P.req; P.busy = true; paint();
    let data = null, error = "";
    try { data = await api("/api/fs/browse?path=" + encodeURIComponent(path), "GET", undefined, { quiet: true }); } catch (e) { error = e.message; }
    if (mine !== P.req) return; // a newer navigation superseded this response
    if (data) { P.data = data; P.typed = data.path; } P.error = error; P.busy = false; paint();
  }
  const crumbs = (path) => {
    const sep = path.includes("\\") ? "\\" : "/", parts = path.split(sep).filter(Boolean), out = []; let acc = sep === "/" ? "/" : "";
    out.push(h("button", { on: { click: () => load("") } }, "Places"));
    parts.forEach((p, i) => { acc = sep === "/" ? (i === 0 ? "/" + p : acc + sep + p) : (i === 0 ? p + "\\" : acc + (i === 1 ? "" : sep) + p); const target = acc; out.push("›", h("button", { on: { click: () => load(target) } }, p)); });
    return h("div", { class: "crumbs" }, out);
  };
  function paint() {
    const d = P.data, atRoot = !d || d.path === "";
    const pathI = h("input", { type: "text", value: P.typed, placeholder: "Paste a folder path, or pick below", "aria-label": "Folder path", spellcheck: "false", "data-autofocus": "1", on: { input: (e) => (P.typed = e.target.value), keydown: (e) => { if (e.key === "Enter") load(P.typed); } } });
    const mkI = h("input", { type: "text", placeholder: "New folder name", "aria-label": "New folder name", "data-autofocus": "1" });
    const choose = act(async () => {
      const w = await api("/api/workspaces", "POST", { path: d.path }); S.wsId = w.id; m.close(); await refresh(); toast("Opened " + w.name); if (!opts.stay) go("agent");
    });
    m.set([
      h("div", { class: "row" }, h("div", { style: false, class: "grow", id: "pi" }, pathI), h("button", { class: "btn", on: { click: () => load(P.typed) } }, "Go")),
      !atRoot && crumbs(d.path),
      P.error && h("div", { class: "notice bad" }, P.error),
      P.busy ? h("div", { class: "notice" }, h("span", { class: "spin" }), " Loading…") : h("div", { class: "list", role: "list" },
        atRoot ? (d?.roots || []).map((r) => h("button", { class: "item", on: { click: () => load(r.path) } }, icon("folder", 16), h("span", { class: "grow" }, r.name), h("span", { class: "muted small mono" }, r.path)))
          : [d.parent !== undefined && d.parent !== null && h("button", { class: "item", on: { click: () => load(d.parent) } }, icon("up", 16), h("span", { class: "grow" }, "Up one folder")),
            ...d.entries.map((e) => h("button", { class: "item", on: { click: () => load(e.path) } }, icon("folder", 16), h("span", { class: "grow" }, e.name), e.project && h("span", { class: "badge ok" }, "project"))),
            !d.entries.length && h("div", { class: "item muted" }, "No subfolders here.")]),
      !atRoot && !d.selectable && h("div", { class: "notice warn" }, "Choose a project folder inside your home folder, not the home folder or a drive itself: the agent could then reach everything."),
      !atRoot && d.selectable && h("div", { class: "notice" }, h("strong", {}, d.path), d.is_project ? " looks like a project." : ""),
      P.mk && h("div", { class: "row" }, mkI, h("button", { class: "btn primary", on: { click: act(async () => { const r = await api("/api/fs/mkdir", "POST", { parent: d.path, name: mkI.value }); P.mk = false; await load(r.path); }) } }, "Create")),
    ], [!atRoot && h("button", { class: "btn", on: { click: () => { P.mk = !P.mk; paint(); } } }, icon("plus", 15), "New folder"), h("span", { class: "spacer" }), h("button", { class: "btn", on: { click: () => m.close() } }, "Cancel"), h("button", { class: "btn primary", disabled: atRoot || !d.selectable, on: { click: choose } }, "Select this folder")]);
  }
  load(opts.start || "");
}

// ---------------------------------------------------------------- model picker + palette
async function openModelPicker() {
  const m = openModal({ title: "Switch model", body: h("div", { class: "notice" }, h("span", { class: "spin" }), " Looking for models…") });
  let d; try { d = await api("/api/models", "GET", undefined, { quiet: true }); } catch (e) { m.set(h("div", { class: "notice bad" }, e.message)); return; }
  const act_ = S.st.active;
  m.set([!d.models.length && h("div", { class: "notice warn" }, "No models found. Connect one, or start your local server."),
    h("div", { class: "list" }, d.models.map((x) => h("button", { class: "item", "aria-selected": act_ && act_.provider === x.provider && act_.model === x.model ? "true" : "false", on: { click: act(async () => { S.st = await api("/api/active", "PUT", { provider: x.provider, model: x.model }); m.close(); render(); toast("Using " + x.model); }) } }, h("span", { class: "grow mono" }, x.model), h("span", { class: "badge " + (x.local ? "ok" : "warn") }, x.local ? "local" : "remote"), h("span", { class: "muted small" }, x.provider_name)))),
    d.problems.map((p) => h("div", { class: "notice " + (p.reason === "blocked" ? "warn" : "") }, h("strong", {}, p.name + ": "), p.message))],
    [h("button", { class: "btn", on: { click: () => { m.close(); go("models"); } } }, "Manage"), h("button", { class: "btn primary", on: { click: () => { m.close(); openConnectWizard(); } } }, icon("plus", 15), "Connect a model")]);
}
function openPalette() {
  const items = [
    { t: "Connect a model", ic: "plug", run: () => openConnectWizard() }, { t: "Switch model", ic: "cpu", run: () => openModelPicker() }, { t: "Open a folder", ic: "folder", run: () => openFolderPicker() },
    { t: "New chat", ic: "chat", run: () => { S.chat.msgs = []; saveChat(); go("chat"); } },
    ...[["home", "Start", "home"], ["chat", "Chat", "chat"], ["agent", "Agent", "bot"], ["models", "Models and privacy", "cpu"], ["folders", "Folders and permissions", "folder"], ["internet", "Internet settings", "globe"], ["knowledge", "Knowledge and memory", "book"], ["capabilities", "Capabilities and plugins", "plug"], ["hardware", "Hardware fit", "cpu"], ["usage", "Usage and audit", "chart"], ["guide", "Guide", "guide"]].map(([v, t, ic]) => ({ t: "Go to " + t, ic, run: () => go(v) })),
    ...S.st.workspaces.map((w) => ({ t: "Use folder: " + w.name, ic: "folder", run: () => { S.wsId = w.id; S.taskId = null; refresh().then(() => go("agent")); } })),
  ];
  let sel = 0, shown = items; const inp = h("input", { type: "text", placeholder: "Type an action…", "aria-label": "Search actions", "data-autofocus": "1" }), box = h("div", { class: "list" });
  const m = openModal({ title: "Actions", body: [inp, h("div", { style: false }), box] });
  const paint = () => fill(box, ...shown.map((x, i) => h("button", { class: "item", "aria-selected": i === sel ? "true" : "false", on: { click: () => { m.close(); x.run(); } } }, icon(x.ic, 16), h("span", { class: "grow" }, x.t))));
  inp.addEventListener("input", () => { const q = inp.value.toLowerCase(); shown = items.filter((x) => x.t.toLowerCase().includes(q)); sel = 0; paint(); });
  inp.addEventListener("keydown", (e) => { if (e.key === "ArrowDown") { sel = Math.min(sel + 1, shown.length - 1); paint(); e.preventDefault(); } else if (e.key === "ArrowUp") { sel = Math.max(sel - 1, 0); paint(); e.preventDefault(); } else if (e.key === "Enter" && shown[sel]) { m.close(); shown[sel].run(); } });
  paint();
}
document.addEventListener("keydown", (e) => { if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") { e.preventDefault(); if (S.st && !$(".overlay")) openPalette(); } });

// ---------------------------------------------------------------- Chat
const SUGGESTIONS = ["Explain the difference between a process and a thread, with a short example.", "Write a Python function that reads a CSV and returns the top 5 rows by a column.", "Review this approach: storing user sessions in a JWT. What are the trade-offs?"];
function msgEl(m) {
  const user = m.role === "user";
  let body;
  if (user) body = m.content;
  else if (m.error) body = h("div", { class: "notice bad" }, h("strong", {}, "Couldn't get a reply. "), m.error, h("div", { class: "row" }, h("button", { class: "btn sm", on: { click: () => go("models") } }, "Model and privacy settings")));
  else if (m.pending && !m.content) body = h("div", { class: "typing", "aria-label": "Thinking" }, h("span"), h("span"), h("span"));
  else body = md(m.content);
  return h("div", { class: "msg " + (user ? "user" : "ai") }, h("div", { class: "av" }, user ? "You" : "AI"), h("div", { class: "body" }, body,
    !user && m.sources && m.sources.length > 0 && h("div", { class: "sources" }, m.sources.map((s) => (s.url ? h("a", { href: s.url, target: "_blank", rel: "noopener noreferrer", title: s.url }, `[${s.n}] ${s.title}`) : h("span", {}, `[${s.n}] ${s.title}`)))),
    !user && !m.pending && m.content && h("div", { class: "meta row" }, m.usage && `${m.usage.prompt}+${m.usage.completion} tokens (${m.usage.source})`, h("button", { class: "btn sm ghost", on: { click: () => copyText(m.content) } }, icon("copy", 13), "Copy"))));
}
function chatView() {
  const C = S.chat, a = S.st.active, w = ws();
  const list = h("div", { class: "msgs", id: "msgs", role: "log", "aria-live": "polite", "aria-label": "Conversation" }, h("div", { class: "in" },
    C.msgs.length ? C.msgs.map(msgEl) : h("div", { class: "hero" }, h("h1", {}, a ? "How can I help?" : "Connect a model to start"), h("p", { class: "lede" }, a ? `Chatting with ${a.model}. Toggle Web for sourced answers${w ? " or Project for answers from your files" : ""}.` : "Add a local or cloud model first. It takes about a minute."),
      a ? h("div", { class: "sugg" }, SUGGESTIONS.map((s) => h("button", { on: { click: () => sendChat(s) } }, s))) : h("button", { class: "btn primary big", on: { click: () => openConnectWizard() } }, icon("plug"), "Connect a model"))));
  const ta = h("textarea", { id: "cin", rows: 1, placeholder: a ? "Message… (Enter to send, Shift+Enter for a new line)" : "Connect a model first", "aria-label": "Message", value: C.draft, "data-focus": C.msgs.length ? null : "1" });
  ta.addEventListener("input", () => { ta.style.height = "auto"; ta.style.height = Math.min(ta.scrollHeight, 220) + "px"; });
  ta.addEventListener("keydown", (e) => { if (e.key === "Enter" && !e.shiftKey && !e.isComposing) { e.preventDefault(); sendChat(ta.value); } });
  const tg = (key, label, ic, on) => h("button", { class: "toggle", "aria-pressed": C[key] ? "true" : "false", on: { click: on } }, icon(ic, 14), label);
  return h("div", { class: "chatcol" }, list, h("div", { class: "composer" }, h("div", { class: "in" }, h("div", { class: "box" }, ta,
    h("div", { class: "row" }, tg("web", "Web", "globe", toggleWeb), w && tg("kb", "Project", "book", () => { C.kb = !C.kb; render(); }), h("span", { class: "spacer" }),
      C.msgs.length > 0 && !C.busy && h("button", { class: "btn sm ghost", on: { click: () => { C.msgs = []; saveChat(); render(); } } }, icon("trash", 14), "Clear"),
      C.busy ? h("button", { class: "btn danger", on: { click: () => C.abort && C.abort.abort() } }, icon("stop", 14), "Stop") : h("button", { class: "btn primary", on: { click: () => sendChat(ta.value) } }, icon("send", 14), "Send"))),
    h("div", { class: "muted small", style: false }, a ? `Using ${a.model} · ${S.st.providers.find((p) => p.id === a.provider)?.local ? "runs on this computer" : "remote service"}${C.web ? " · web search on" : ""}` : "No model connected"))));
}
function toggleWeb() {
  const C = S.chat;
  if (C.web) { C.web = false; return render(); }
  if (S.st.policy.internet !== "off") { C.web = true; return render(); }
  const m = openModal({ title: "Allow web search?", body: [h("p", {}, `With Web on, your question is sent to ${{ duckduckgo: "DuckDuckGo", wikipedia: "Wikipedia", searxng: "your SearXNG server" }[S.st.web.engine]} and the top pages are read to answer with sources.`), h("p", { class: "muted" }, "Internet is currently off. The agent will still ask before each use if you choose 'Ask'.")],
    footer: [h("button", { class: "btn", on: { click: () => m.close() } }, "Cancel"), h("button", { class: "btn", on: { click: act(async () => { S.st = await api("/api/policy", "PUT", { ...S.st.policy, internet: "ask" }); C.web = true; m.close(); render(); }) } }, "Allow (agent asks each time)"), h("button", { class: "btn primary", on: { click: act(async () => { S.st = await api("/api/policy", "PUT", { ...S.st.policy, internet: "on" }); C.web = true; m.close(); render(); }) } }, "Allow fully")] });
}
function paintLast() { const el = $("#msgs .msg:last-child"); if (el) { el.replaceWith(msgEl(S.chat.msgs[S.chat.msgs.length - 1])); } const m = $("#msgs"); if (m && m.scrollHeight - m.scrollTop - m.clientHeight < 160) m.scrollTop = m.scrollHeight; }
let _raf = 0; const paintSoon = () => { if (!_raf) _raf = requestAnimationFrame(() => { _raf = 0; paintLast(); }); };
async function sendChat(text) {
  const C = S.chat; text = (text || "").trim(); if (C.busy || !text) return;
  if (!S.st.active) return openConnectWizard();
  C.msgs.push({ role: "user", content: text }); const a = { role: "assistant", content: "", sources: [], pending: true }; C.msgs.push(a);
  C.busy = true; C.abort = new AbortController(); C.draft = ""; render();
  try {
    const usage = await streamChat({ messages: C.msgs.slice(0, -1).filter((m) => m.content && !m.error).map(({ role, content }) => ({ role, content })), use_web: C.web, use_knowledge: C.kb, workspace_id: S.wsId },
      { signal: C.abort.signal, onDelta: (d) => { a.content += d; paintSoon(); }, onSources: (s) => { a.sources = s; paintSoon(); } });
    a.usage = usage;
  } catch (e) { if (e.name === "AbortError") { a.content += a.content ? "\n\n*(stopped)*" : "*(stopped)*"; } else a.error = e.message; }
  a.pending = false; C.busy = false; C.abort = null; saveChat(); render();
}

// ---------------------------------------------------------------- Agent
const EXAMPLES = [["plan", "Explain how this project is structured and where to start reading."], ["build", "Find why the tests fail and fix it."], ["plan", "Review the code for bugs and security problems; list them by severity."], ["build", "Add a short 'Getting started' section to the README based on the code."]];
async function openTask(id) {
  closeStream(); S.view = "agent"; S.taskId = id; S.events = []; S.live = ""; S.task = await api("/api/tasks/" + id); render();
  const es = new EventSource(`/api/tasks/${id}/stream`); S.es = es;
  es.onmessage = (m) => {
    const e = JSON.parse(m.data);
    if (e.type === "model_delta") { S.live += e.data.text; paintLive(); return; }
    if (e.type === "model_start") S.live = "";
    S.events.push(e);
    if (["approval_request", "final", "question", "change_applied", "status", "verification"].includes(e.type)) refreshTask(); else renderRail();
    if (e.type === "final") { closeStream(); api("/api/tasks?workspace_id=" + S.wsId).then((t) => { S.tasks = t; }).catch(() => {}); }
  };
}
function closeStream() { if (S.es) { S.es.close(); S.es = null; } }
async function refreshTask() { if (!S.taskId) return; S.task = await api("/api/tasks/" + S.taskId); render(); const r = $("#scroller"); if (r) r.scrollTop = r.scrollHeight; }
function renderRail() { const old = $("#rail"); if (old) { old.replaceWith(rail()); const r = $("#scroller"); if (r) r.scrollTop = r.scrollHeight; } paintLive(); }
function paintLive() { const l = $("#live"); if (l) l.textContent = S.live ? "Model is writing… " + S.live.slice(-160) : ""; }
function agentView() {
  const w = ws();
  if (!S.st.active || !w) return h("div", { class: "page" }, h("div", { class: "wrap" }, h("h1", {}, "Agent"), h("p", { class: "lede" }, "The agent works inside one project folder using your model. You approve every change."),
    h("div", { class: "steps" }, h("div", { class: "card" }, h("h3", {}, S.st.active ? "✔ Model connected" : "1. Connect a model"), !S.st.active && h("button", { class: "btn primary", on: { click: () => openConnectWizard() } }, "Connect a model")),
      h("div", { class: "card" }, h("h3", {}, w ? "✔ Folder opened" : "2. Open a folder"), !w && h("button", { class: "btn primary", on: { click: () => openFolderPicker() } }, "Open a folder")))));
  const t = S.task && S.task.id === S.taskId ? S.task : null;
  const content = t ? h("div", {}, h("h1", {}, t.goal), h("div", { class: "row" }, badge(t.status), h("span", { class: "muted" }, `${t.mode === "plan" ? "Plan (read-only)" : "Build"} · ${t.model} via ${t.provider}`),
    !TERMINAL.includes(t.status) && h("button", { class: "btn danger sm", on: { click: act(() => api(`/api/tasks/${t.id}/cancel`, "POST")) } }, "Cancel"),
    ["interrupted", "exhausted", "cancelled", "failed"].includes(t.status) && h("button", { class: "btn sm", on: { click: act(async () => { await api(`/api/tasks/${t.id}/resume`, "POST", {}); openTask(t.id); }) } }, "Resume")), rail(), h("p", { id: "live", class: "live", "aria-live": "off" }))
    : h("div", {}, h("h1", {}, "Agent"), h("p", { class: "lede" }, "Describe what you want done in this project. Plan mode only investigates. Build mode edits files (you review diffs) and runs your tests."),
      h("div", { class: "muted small" }, "Try one:"), h("div", { class: "chips" }, EXAMPLES.map(([md_, tx]) => h("button", { class: "chipbtn", on: { click: () => { S.mode = md_; S.agentDraft = tx; render(); } } }, tx))));
  return h("div", { class: "agent" }, h("div", { class: "main" }, h("div", { class: "scroll", id: "scroller" }, h("div", { class: "row" }, h("button", { class: "chip", on: { click: () => openFolderPicker() } }, icon("folder", 15), w.name, h("small", {}, w.path)), h("button", { class: "btn sm", on: { click: () => { closeStream(); S.taskId = null; S.task = null; S.events = []; render(); } } }, icon("plus", 14), "New task")), content), agentComposer(t)), inspector());
}
function agentComposer(t) {
  if (t && !TERMINAL.includes(t.status)) return h("div", { class: "composer" }, h("div", { class: "in muted" }, "Task in progress. Approve or reject gates on the rail, or cancel."));
  const ta = h("textarea", { id: "goal", rows: 2, value: S.agentDraft, placeholder: "What should be done? e.g. Fix the failing test in test_calc.py", "aria-label": "Task description", "data-focus": "1" });
  const start = act(async () => { const goal = ta.value.trim(); if (!goal) { ta.focus(); return; } const r = await api("/api/tasks", "POST", { workspace_id: S.wsId, goal, mode: S.mode }); S.agentDraft = ""; S.tasks = await api("/api/tasks?workspace_id=" + S.wsId); openTask(r.id); });
  ta.addEventListener("keydown", (e) => { if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) start(); });
  return h("div", { class: "composer" }, h("div", { class: "in" }, h("div", { class: "box" }, ta, h("div", { class: "row" }, h("div", { class: "seg", role: "group", "aria-label": "Mode" }, ["plan", "build"].map((m) => h("button", { "aria-pressed": S.mode === m ? "true" : "false", on: { click: () => { S.agentDraft = ta.value; S.mode = m; render(); } } }, m === "plan" ? "Plan" : "Build"))),
    h("span", { class: "muted small" }, S.mode === "plan" ? "Read-only investigation" : "Edits wait for your approval"), h("span", { class: "spacer" }), h("button", { class: "btn primary", on: { click: start } }, icon("play", 14), "Start")))));
}
function diffView(text) { return h("div", { class: "diff", tabindex: "0", role: "region", "aria-label": "Diff" }, String(text || "").split("\n").map((l) => h("div", { class: l.startsWith("+") && !l.startsWith("+++") ? "a" : l.startsWith("-") && !l.startsWith("---") ? "d" : l.startsWith("@@") ? "h" : "" }, l || " "))); }
function rail() {
  const ev = S.events, out = []; let n = 0; const resolved = {};
  ev.forEach((e) => { if (e.type === "approval_resolved") resolved[e.data.id] = e.data; });
  for (let i = 0; i < ev.length; i++) {
    const e = ev[i], d = e.data, when = h("span", { class: "when" }, fmtT(e.ts));
    if (e.type === "model_message") {
      n++; let a = null; try { a = JSON.parse(d.text.slice(d.text.indexOf("{"), d.text.lastIndexOf("}") + 1)); } catch (_) { /* not json */ }
      out.push(h("div", { class: "entry" }, h("div", { class: "head" }, when, h("strong", {}, `Step ${n}`), h("span", { class: "muted small" }, `${d.usage.prompt}+${d.usage.completion} tokens (${d.usage.source})`)), a && a.thought ? h("div", { class: "thought" }, String(a.thought)) : !a && h("details", {}, h("summary", {}, "Unparsed model output"), h("pre", {}, d.text))));
    } else if (e.type === "tool_call") {
      const r = ev.slice(i + 1).find((x) => x.type === "tool_result" && x.data.tool === d.tool);
      out.push(h("div", { class: "entry " + (r ? (r.data.ok ? "ok" : "bad") : "") }, h("div", { class: "head" }, when, h("strong", { class: "mono" }, d.tool), h("span", { class: "mono muted" }, JSON.stringify(d.args).slice(0, 140)), r && h("span", { class: "badge " + (r.data.ok ? "ok" : "bad") }, r.data.ok ? "ok" : r.data.meta?.denied ? "denied" : "failed")), r && h("details", {}, h("summary", {}, "Output"), h("pre", {}, r.data.output))));
    } else if (e.type === "approval_request") {
      const res = resolved[d.id];
      out.push(h("section", { class: "gate " + (res ? "done" : ""), "aria-label": "Approval required" }, h("h4", {}, res ? (res.approved ? "Approved: " : "Rejected: ") + d.title : "Waiting for you: " + d.title), h("div", { class: "muted small" }, `Permission level: ${d.level}`),
        d.detail.changes && d.detail.changes.map((c) => h("div", {}, h("div", { class: "mono" }, `${c.kind} ${c.path} (+${c.added} −${c.removed})`), diffView(c.diff))),
        d.detail.argv && h("pre", { class: "mono" }, d.detail.argv.join(" ") + (d.detail.reason ? `\n(${d.detail.reason})` : "")), d.detail.query && h("pre", { class: "mono" }, "search: " + d.detail.query), d.detail.url && h("pre", { class: "mono" }, d.detail.url), !res && approvalControls(d)), !res && h("div", { class: "cap", "aria-hidden": "true" }));
    } else if (e.type === "change_applied") {
      out.push(h("div", { class: "entry edit" }, h("div", { class: "head" }, when, h("strong", {}, `${d.kind === "create" ? "Created" : d.kind === "delete" ? "Deleted" : "Changed"} ${d.path}`), h("span", { class: "muted" }, `+${d.added} −${d.removed}`), h("button", { class: "btn sm", on: { click: () => { S.tab = "changes"; render(); } } }, "Review diff"))));
    } else if (e.type === "verification") {
      out.push(h("div", { class: "entry " + (d.passed ? "ok" : "bad") }, h("div", { class: "head" }, when, h("strong", {}, d.passed ? "Check passed" : "Check failed"), h("span", { class: "mono muted" }, d.argv.join(" ")), h("span", { class: "badge " + (d.passed ? "ok" : "bad") }, "exit " + d.exit_code))));
    } else if (e.type === "question" && !ev.slice(i + 1).some((x) => x.type === "answer")) {
      const inp = h("input", { type: "text", "aria-label": "Your answer", "data-focus": "1" });
      out.push(h("section", { class: "gate" }, h("h4", {}, "The agent asks: " + d.question), h("div", { class: "row" }, inp, h("button", { class: "btn primary", on: { click: act(async () => { await api(`/api/tasks/${S.taskId}/answer`, "POST", { text: inp.value }); }) } }, "Answer"))));
    } else if (e.type === "answer") { out.push(h("div", { class: "entry" }, h("div", { class: "head" }, when, h("strong", {}, "You answered:"), d.text)));
    } else if (e.type === "final") {
      const cls = d.status === "completed_verified" ? "v" : d.status === "failed" ? "f" : d.status === "completed" ? "" : "u";
      out.push(h("section", { class: "final " + cls, "aria-label": "Result" }, h("div", { class: "row" }, badge(d.status), h("strong", {}, d.note || "")), h("p", {}, d.message), d.changed_files.length > 0 && h("p", { class: "mono" }, "Changed: " + d.changed_files.join(", ")),
        d.verification.commands.length > 0 ? h("p", { class: "muted" }, "Checks: " + d.verification.commands.map((c) => `${c.argv.join(" ")} → exit ${c.exit_code}${c.after_last_edit ? "" : " (before last edit)"}`).join("; ")) : d.changed_files.length > 0 && h("p", { class: "muted" }, "No verification command ran after the edits.")));
    }
  }
  return h("div", { class: "rail", id: "rail", role: "log", "aria-label": "Agent activity" }, out.length ? out : h("div", { class: "muted" }, h("span", { class: "spin" }), " Waiting for the agent…"));
}
function approvalControls(d) {
  const fb = h("input", { type: "text", placeholder: "Optional feedback for the agent", "aria-label": "Feedback if rejecting" });
  const send = (ok) => act(() => api(`/api/tasks/${S.taskId}/approvals/${d.id}`, "POST", { approved: ok, feedback: fb.value }));
  return h("div", { class: "row" }, h("button", { class: "btn primary", "data-focus": "1", on: { click: send(true) } }, "Approve"), h("button", { class: "btn danger", on: { click: send(false) } }, "Reject"), fb);
}
function inspector() {
  const t = S.task && S.task.id === S.taskId ? S.task : null, st = t?.state || {};
  const tabs = [["changes", "Changes"], ["plan", "Plan"], ["checks", "Checks"], ["files", "Files read"]]; let body;
  if (!t) body = h("p", { class: "muted" }, "Start or select a task to see its changes, plan and checks here.");
  else if (S.tab === "changes") body = (st.changes || []).length ? st.changes.map((c) => h("div", { class: "card flat" }, h("div", { class: "row" }, h("strong", { class: "mono" }, c.path), h("span", { class: "muted" }, `${c.kind} +${c.added} −${c.removed}`)), diffView(c.diff), h("button", { class: "btn sm", on: { click: act(async () => { await api(`/api/tasks/${t.id}/undo`, "POST", { snapshot: c.snapshot }); toast("Reverted " + c.path); refreshTask(); }) } }, "Undo this change"))) : h("p", { class: "muted" }, "No files changed.");
  else if (S.tab === "plan") body = (st.plan || []).length ? h("ol", {}, st.plan.map((p) => h("li", {}, p.text, " ", h("span", { class: "badge " + (p.status === "done" ? "ok" : p.status === "doing" ? "info" : "") }, p.status)))) : h("p", { class: "muted" }, "The agent has not published a plan.");
  else if (S.tab === "checks") body = (st.verifications || []).length ? h("table", {}, h("tbody", {}, st.verifications.map((v) => h("tr", {}, h("td", { class: "mono" }, v.argv.join(" ")), h("td", {}, h("span", { class: "badge " + (v.exit_code === 0 ? "ok" : "bad") }, "exit " + v.exit_code)), h("td", { class: "muted" }, v.seq > st.last_mutation ? "after last edit" : "before last edit"))))) : h("p", { class: "muted" }, "No test, lint or build command has run.");
  else body = (st.files_read || []).length ? h("ul", {}, [...new Set(st.files_read)].map((f) => h("li", { class: "mono" }, f))) : h("p", { class: "muted" }, "No files read yet.");
  return h("aside", { class: "insp", "aria-label": "Inspector" }, h("div", { class: "tabs", role: "tablist" }, tabs.map(([k, l]) => h("button", { role: "tab", "aria-selected": S.tab === k ? "true" : "false", on: { click: () => { S.tab = k; render(); } } }, l))), h("div", { class: "pad", role: "tabpanel" }, body));
}

const VIEWS = { home: homeView, chat: chatView, agent: agentView, models: () => modelsView(), folders: () => foldersView(), internet: () => internetView(), knowledge: () => knowledgeView(), capabilities: () => capsView(), hardware: () => hardwareView(), usage: () => usageView(), guide: () => guideView() };
refresh().then(() => { if (!S.st.active && !S.st.workspaces.length) S.view = "home"; else if (S.st.active) S.view = "chat"; render(); })
  .catch(() => { $("#app").textContent = "Cannot reach the Hearthforge server, or you are not authorised. Open the URL printed in your terminal."; });
