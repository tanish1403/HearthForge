"use strict";
const pageOf = (...kids) => h("div", { class: "page" }, h("div", { class: "wrap" }, ...kids));
const choice = (checked, title, text, on) => h("button", { class: "choice", role: "radio", "aria-checked": checked ? "true" : "false", on: { click: on } }, h("span", { class: "rd" }), h("span", {}, h("strong", {}, title), h("div", { class: "muted" }, text)));

// ---------------------------------------------------------------- Models & privacy
function modelsView() {
  const p = S.st.policy, ex = S.st.policy_explain; let mode = p.cloud_mode;
  const mb = h("input", { type: "number", min: 0, step: "0.5", value: p.monthly_budget_usd ?? "", "aria-label": "Monthly budget USD" }), tb = h("input", { type: "number", min: 0, step: "0.1", value: p.task_budget_usd ?? "", "aria-label": "Per-task budget USD" });
  const modes = h("div", { role: "radiogroup", "aria-label": "Privacy mode" });
  const paintModes = () => fill(modes, 
    choice(mode === "local_only", "Local only (safest)", "Only models running on this computer. Remote services are blocked.", () => { mode = "local_only"; paintModes(); }),
    choice(mode === "free_only", "Free tier only", "Remote services you marked free are allowed; anything else is blocked.", () => { mode = "free_only"; paintModes(); }),
    choice(mode === "budgeted", "Budgeted cloud", "Any connected remote service. Spending is limited by the budgets below where prices are known.", () => { mode = "budgeted"; paintModes(); }));
  paintModes();
  return pageOf(h("div", { class: "row" }, h("h1", {}, "Models"), h("span", { class: "spacer" }), h("button", { class: "btn primary big", on: { click: () => openConnectWizard() } }, icon("plus", 16), "Connect a model")),
    h("p", { class: "lede" }, "Local servers and cloud/gateway services all work the same way: connect, pick a model, chat."),
    S.st.providers.map(providerCard),
    h("h2", { class: "t" }, "Quick add"), h("div", { class: "chips" }, PRESETS.map((x) => h("button", { class: "chipbtn", on: { click: () => openConnectWizard(x) } }, x.name))),
    h("h2", { class: "t" }, "Privacy"), h("div", { class: "notice" }, ex.summary), modes,
    h("div", { class: "row" }, h("label", {}, "Monthly budget $ ", mb), h("label", {}, "Per-task budget $ ", tb), h("button", { class: "btn primary", on: { click: act(async () => { S.st = await api("/api/policy", "PUT", { cloud_mode: mode, internet: p.internet, monthly_budget_usd: mb.value === "" ? null : +mb.value, task_budget_usd: tb.value === "" ? null : +tb.value }); toast("Privacy saved"); render(); }) } }, "Save privacy")),
    h("p", { class: "muted small" }, "Budgets can only be enforced for models with a price you enter in their provider settings; unpriced paid models are blocked when a budget is set. Free-tier status is your own declaration."));
}
function providerCard(p) {
  const isActive = S.st.active && S.st.active.provider === p.id, models = h("div", {});
  const key = h("input", { type: "password", placeholder: p.has_key ? "Key saved (type to replace)" : "API key (if needed)", "aria-label": "API key for " + p.name, autocomplete: "off" });
  const showModels = act(async () => {
    fill(models, h("span", { class: "spin" }));
    try { const ms = await api(`/api/providers/${p.id}/models?refresh=true`, "GET", undefined, { quiet: true });
      fill(models, ms.length ? h("div", { class: "list" }, ms.map((m) => h("button", { class: "item", "aria-selected": isActive && S.st.active.model === m.id ? "true" : "false", on: { click: act(async () => { S.st = await api("/api/active", "PUT", { provider: p.id, model: m.id }); toast("Using " + m.id); render(); }) } }, h("span", { class: "grow mono" }, m.id), m.capabilities.length > 0 && h("span", { class: "badge info" }, m.capabilities.join(", "))))) : h("div", { class: "notice" }, "The server answered but listed no models."));
    } catch (e) { fill(models, h("div", { class: "notice bad" }, e.message, h("div", { class: "small" }, "Open Connect a model to re-detect the URL or key."))); }
  });
  return h("div", { class: "card" + (isActive ? " hl" : "") }, h("div", { class: "row" }, h("strong", {}, p.name), h("span", { class: "badge " + (p.local ? "ok" : "warn") }, p.local ? "local" : "remote"), isActive && h("span", { class: "badge info" }, "active: " + S.st.active.model), !p.enabled && h("span", { class: "badge" }, "disabled"), h("span", { class: "spacer" }), h("span", { class: "mono muted small" }, p.base_url)),
    h("div", { class: "row" }, h("button", { class: "btn sm", on: { click: showModels } }, "Show models"),
      h("button", { class: "btn sm", on: { click: act(async () => { const r = await api(`/api/providers/${p.id}/test`, "POST"); toast(r.ok ? `${p.name}: reachable, ${r.models} models, ${r.latency_ms} ms` : `${p.name}: ${r.error.message || r.error.kind}`); }) } }, "Test"),
      h("button", { class: "btn sm", on: { click: () => openConnectWizard({ id: p.id, name: p.name, url: p.base_url, kind: p.kind, key: !p.local }) } }, "Edit / re-detect"),
      !p.local && h("select", { "aria-label": "Cost class", on: { change: act(async (e) => { await api("/api/providers/" + p.id, "PUT", { cost_class: e.target.value }); refresh(); }) } }, ["unknown", "free_tier", "metered"].map((c) => h("option", { value: c, selected: p.cost_class === c }, { unknown: "cost: not sure", free_tier: "cost: free tier", metered: "cost: paid" }[c]))),
      h("button", { class: "btn sm", on: { click: act(async () => { await api("/api/providers/" + p.id, "PUT", { enabled: !p.enabled }); refresh(); }) } }, p.enabled ? "Disable" : "Enable"),
      h("button", { class: "btn sm danger", on: { click: act(async () => { if (confirm("Remove " + p.name + " and its stored key?")) { await api("/api/providers/" + p.id, "DELETE"); refresh(); } }) } }, "Remove")),
    h("div", { class: "row" }, key, h("button", { class: "btn sm", on: { click: act(async () => { if (!key.value) return; const r = await api(`/api/providers/${p.id}/key`, "PUT", { key: key.value, allow_session: true }); key.value = ""; toast(r.stored === "keychain" ? "Key saved to the OS keychain" : "Key kept in memory until you quit (no OS keychain)"); refresh(); }) } }, "Save key"), p.has_key && h("button", { class: "btn sm", on: { click: act(async () => { await api(`/api/providers/${p.id}/key`, "DELETE"); refresh(); }) } }, "Delete key")), models);
}

// ---------------------------------------------------------------- Folders & permissions
const PERM_PRESETS = {
  careful: { label: "Careful", text: "Ask before every edit and command.", p: { read: "allow", write: "ask", exec: "ask", network: "deny", install: "ask", destructive: "ask" }, auto: false },
  balanced: { label: "Balanced", text: "Ask before edits; run recognised test/lint commands automatically.", p: { read: "allow", write: "ask", exec: "ask", network: "deny", install: "ask", destructive: "ask" }, auto: true },
  hands: { label: "Hands-off", text: "Apply edits and run commands without asking (still snapshotted, undoable). Installs and deletes still ask.", p: { read: "allow", write: "allow", exec: "allow", network: "deny", install: "ask", destructive: "ask" }, auto: true },
};
const LEVEL_HELP = { read: "Read files, search, list directories, git status/diff", write: "Create and modify files (always snapshotted for undo)", exec: "Run allowlisted commands (tests, builds, linters)", network: "Commands that use the network (git push, curl…)", install: "Install packages (pip/npm install…)", destructive: "Delete files or discard git state" };
function currentPreset(w) { return Object.entries(PERM_PRESETS).find(([, v]) => Object.entries(v.p).every(([k, m]) => w.permissions[k] === m) && v.auto === w.auto_approve_safe_commands)?.[0] || "custom"; }
function foldersView() {
  const w = ws(); const upd = (patch) => act(async () => { await api("/api/workspaces/" + w.id, "PUT", patch); await refresh(); });
  const extra = h("input", { type: "text", value: w ? w.extra_allowed_commands.join(", ") : "", placeholder: "e.g. make, cargo-nextest", "aria-label": "Extra allowed commands" });
  return pageOf(h("div", { class: "row" }, h("h1", {}, "Folders"), h("span", { class: "spacer" }), h("button", { class: "btn primary big", on: { click: () => openFolderPicker({ stay: true }) } }, icon("folder", 16), "Open a folder")),
    h("p", { class: "lede" }, "The agent can only see and change files inside a folder you open here."),
    !S.st.workspaces.length && h("div", { class: "notice" }, "No folder yet. Click “Open a folder” and browse to your project."),
    S.st.workspaces.map((x) => h("div", { class: "card" + (x.id === S.wsId ? " hl" : "") }, h("div", { class: "row" }, h("strong", {}, x.name), x.id === S.wsId && h("span", { class: "badge info" }, "current"), h("span", { class: "spacer" }), h("span", { class: "mono muted small" }, x.path), x.id !== S.wsId && h("button", { class: "btn sm", on: { click: act(async () => { S.wsId = x.id; S.taskId = null; await refresh(); }) } }, "Use this folder"), h("button", { class: "btn sm danger", on: { click: act(async () => { if (confirm("Remove this folder from Hearthforge? Files are not deleted.")) { await api("/api/workspaces/" + x.id, "DELETE"); S.wsId = null; await refresh(); } }) } }, "Remove")))),
    w && [h("h2", { class: "t" }, "How much freedom for " + w.name + "?"), h("div", { role: "radiogroup", "aria-label": "Permission preset" }, Object.entries(PERM_PRESETS).map(([k, v]) => choice(currentPreset(w) === k, v.label, v.text, upd({ permissions: v.p, auto_approve_safe_commands: v.auto })))),
      currentPreset(w) === "custom" && h("div", { class: "notice" }, "Custom settings in use (see details below)."),
      h("details", {}, h("summary", {}, "Fine-grained permissions"), S.st.levels.map((l) => h("div", { class: "perm" }, h("strong", {}, l), h("span", { class: "muted" }, LEVEL_HELP[l]), h("select", { "aria-label": l + " permission", on: { change: (e) => upd({ permissions: { [l]: e.target.value } })() } }, ["allow", "ask", "deny"].map((m) => h("option", { value: m, selected: w.permissions[l] === m }, m))))),
        h("label", { class: "f" }, h("span", {}, "Extra allowed executables (comma separated; shells are never allowed)"), h("div", { class: "row" }, extra, h("button", { class: "btn", on: { click: () => upd({ extra_allowed_commands: extra.value.split(",").map((s) => s.trim()).filter(Boolean) })() } }, "Save"))),
        h("label", { class: "f" }, h("span", {}, "Maximum agent steps per run"), h("input", { type: "number", min: 1, value: w.max_steps, on: { change: (e) => upd({ max_steps: +e.target.value })() } }))),
      h("p", { class: "muted small" }, "Commands run with your user rights and no OS sandbox. Use Careful for code you don't trust.")]);
}

// ---------------------------------------------------------------- Internet
function internetView() {
  const p = S.st.policy, web_ = S.st.web; let net = p.internet, engine = web_.engine;
  const sx = h("input", { type: "text", value: web_.searxng_url, placeholder: "http://127.0.0.1:8888", "aria-label": "SearXNG URL" }), out = h("div", {}), nets = h("div", { role: "radiogroup", "aria-label": "Internet access" }), engines = h("div", { role: "radiogroup", "aria-label": "Search engine" });
  const paintN = () => fill(nets, choice(net === "off", "Off", "No searches or page fetches. Chat's Web toggle and the agent's web tools are blocked.", () => { net = "off"; paintN(); }), choice(net === "ask", "Ask each time", "The agent shows every search/fetch and waits for your approval. Chat Web searches run when you press Send.", () => { net = "ask"; paintN(); }), choice(net === "on", "On", "Search and page reading run automatically. Your search words leave this machine.", () => { net = "on"; paintN(); }));
  const paintE = () => fill(engines, choice(engine === "duckduckgo", "DuckDuckGo (no key)", "Works without an account by reading its HTML results page. Unofficial: it can break or rate-limit.", () => { engine = "duckduckgo"; paintE(); }), choice(engine === "wikipedia", "Wikipedia", "Reliable official API; encyclopedic topics only.", () => { engine = "wikipedia"; paintE(); }), choice(engine === "searxng", "My SearXNG server", "Best option: a search server you control (enable its JSON format). Local addresses allowed here.", () => { engine = "searxng"; paintE(); }));
  paintN(); paintE();
  const persist = async () => { S.st = await api("/api/policy", "PUT", { cloud_mode: p.cloud_mode, monthly_budget_usd: p.monthly_budget_usd, task_budget_usd: p.task_budget_usd, internet: net }); S.st = await api("/api/web", "PUT", { engine, searxng_url: sx.value }); const t = $(".top"); if (t) t.replaceWith(topbar()); };
  const save = act(async () => { await persist(); toast("Internet settings saved"); });
  const test = act(async () => {
    await persist(); fill(out, h("span", { class: "spin" }), " Searching…");
    if (net === "off") { fill(out, h("div", { class: "notice warn" }, "Internet is Off. Choose Ask or On to test search.")); return; }
    try { const r = await api("/api/web/test", "POST", { query: "python programming language" }, { quiet: true }); fill(out, h("div", { class: "notice ok" }, `✔ Connected via ${engine}. Sample results:`), r.map((x) => h("div", { class: "card flat" }, h("a", { href: x.url, target: "_blank", rel: "noopener noreferrer" }, x.title || x.url), h("div", { class: "muted small" }, x.snippet)))); }
    catch (e) { fill(out, h("div", { class: "notice bad" }, h("strong", {}, "Search failed: "), e.message)); }
  });
  return pageOf(h("h1", {}, "Internet"), h("p", { class: "lede" }, "Let chat and the agent search the web and read public pages. Off by default so nothing leaves your computer unexpectedly."), nets, h("h2", { class: "t" }, "Search engine"), engines, h("label", { class: "f" }, h("span", {}, "SearXNG URL (only if you picked your own server)"), sx),
    h("div", { class: "row" }, h("button", { class: "btn primary", on: { click: save } }, "Save"), h("button", { class: "btn", on: { click: test } }, icon("globe", 15), "Save and test search")), out,
    h("h2", { class: "t" }, "Safeguards"), h("ul", {}, h("li", {}, "Pages are fetched as plain text with size and time limits; scripts are never run."), h("li", {}, "Addresses on your computer or network (localhost, 192.168.x.x, cloud metadata) are always refused, including after redirects."), h("li", {}, "Web text is marked untrusted: instructions inside a page can't command the agent."), h("li", {}, "Every use is written to the audit log.")));
}

// ---------------------------------------------------------------- Capabilities
function capsView() {
  const groups = {}; S.st.capabilities.forEach((c) => (groups[c.group] ||= []).push(c));
  const ta = h("textarea", { rows: 7, placeholder: '{"id":"my-linter","name":"My linter","tools":[{"name":"run","description":"Lint the project","command":["mylint","--json"],"parameters":{"type":"object","properties":{}}}]}', "aria-label": "Plugin manifest JSON", class: "mono" });
  return pageOf(h("h1", {}, "Capabilities"), h("p", { class: "lede" }, "Turn features on or off. A disabled capability is removed from the agent and refused by the backend. “Planned” means not built yet."),
    Object.entries(groups).map(([g, cs]) => [h("h2", { class: "t" }, g), cs.map((c) => h("div", { class: "card" }, h("div", { class: "row" }, h("label", { class: "row" }, h("input", { type: "checkbox", checked: c.enabled, disabled: c.status === "planned", on: { change: act(async (e) => { await api("/api/capabilities/" + c.id, "PUT", { enabled: e.target.checked }); refresh(); }) } }), h("strong", {}, c.name)), h("span", { class: "badge " + (c.status === "implemented" ? "ok" : c.status === "partial" ? "warn" : "") }, c.status), h("span", { class: "spacer" }), c.removable && h("button", { class: "btn sm danger", on: { click: act(async () => { await api("/api/plugins/" + c.id.replace("plugin.", ""), "DELETE"); refresh(); }) } }, "Remove")),
      h("div", { class: "muted" }, c.desc), c.tools.length > 0 && h("div", { class: "mono muted small" }, "tools: " + c.tools.join(", ")), c.status !== "planned" && c.health.detail && h("div", { class: "small " + (c.health.ok ? "muted" : "badge warn") }, c.health.detail)))]),
    h("h2", { class: "t" }, "Add an external-command plugin"), h("p", { class: "lede" }, "A JSON manifest maps tool names to fixed commands (no shell). Arguments arrive as JSON on stdin. Plugin tools always need at least “exec” permission."), ta,
    h("div", { class: "row" }, h("button", { class: "btn primary", on: { click: act(async () => { let m; try { m = JSON.parse(ta.value); } catch (e) { toast("That is not valid JSON"); return; } await api("/api/plugins", "POST", m); ta.value = ""; refresh(); }) } }, "Add plugin")));
}

// ---------------------------------------------------------------- Knowledge & memory
function knowledgeView() {
  const w = ws(); if (!w) return pageOf(h("h1", {}, "Knowledge"), h("div", { class: "notice" }, "Open a folder first."), h("button", { class: "btn primary", on: { click: () => openFolderPicker({ stay: true }) } }, "Open a folder"));
  const box = h("div", {}), res = h("div", {});
  const load = act(async () => {
    const d = await api("/api/knowledge/" + w.id);
    fill(box, h("h2", { class: "t" }, "Indexed sources"), d.sources.length ? d.sources.map((s) => { const docs = h("div", {});
      return h("div", { class: "card" }, h("div", { class: "row" }, h("strong", {}, s.name), h("span", { class: "badge" }, `${s.documents} docs · ${s.chunks} chunks`), h("span", { class: "spacer" }), h("span", { class: "muted mono small" }, s.root)),
        h("div", { class: "row" }, h("button", { class: "btn sm", on: { click: act(async () => { const r = await api(`/api/knowledge/sources/${s.id}/index`, "POST", {}); toast(`Indexed: +${r.added} updated ${r.updated} removed ${r.removed}`); load(); }) } }, "Re-index"),
          h("button", { class: "btn sm", on: { click: act(async () => { const r = await api(`/api/knowledge/sources/${s.id}/docs`); fill(docs, h("table", {}, h("tbody", {}, r.map((x) => h("tr", {}, h("td", { class: "mono" }, x.path), h("td", {}, x.chunks + " chunks"), h("td", {}, h("button", { class: "btn sm", on: { click: act(async () => { await api(`/api/knowledge/docs/${x.id}/exclude`, "POST", { excluded: !x.excluded }); load(); }) } }, x.excluded ? "Include" : "Exclude"))))))); }) } }, "Show documents"),
          h("button", { class: "btn sm danger", on: { click: act(async () => { await api("/api/knowledge/sources/" + s.id, "DELETE"); load(); }) } }, "Delete index")), docs); }) : h("div", { class: "notice" }, "Nothing indexed yet. Index this folder so you (and the agent) can search it with cited excerpts."),
      h("div", { class: "row" }, h("button", { class: "btn primary", on: { click: act(async () => { const s = await api("/api/knowledge/sources", "POST", { scope: w.id, name: w.name }); await api(`/api/knowledge/sources/${s.id}/index`, "POST", {}); load(); }) } }, "Index this folder"),
        (() => { const p = h("input", { type: "text", placeholder: "Another folder (e.g. a notes or Obsidian vault)", "aria-label": "Folder to index" }); return h("span", { class: "row grow" }, p, h("button", { class: "btn", on: { click: act(async () => { const s = await api("/api/knowledge/sources", "POST", { scope: w.id, root: p.value }); await api(`/api/knowledge/sources/${s.id}/index`, "POST", {}); load(); }) } }, "Add folder")); })()),
      h("h2", { class: "t" }, "Project memory"), h("p", { class: "muted" }, "Short notes the agent can recall in later tasks. Credentials are refused."),
      d.memories.map((m) => { const t = h("input", { type: "text", value: m.text, "aria-label": "Memory text" }); return h("div", { class: "row" }, t, h("button", { class: "btn sm", on: { click: act(async () => { await api("/api/memories/" + m.id, "PUT", { text: t.value }); toast("Saved"); }) } }, "Save"), h("button", { class: "btn sm danger", on: { click: act(async () => { await api("/api/memories/" + m.id, "DELETE"); load(); }) } }, "Forget")); }),
      (() => { const t = h("input", { type: "text", placeholder: "Add a note, e.g. “Tests run with make test”", "aria-label": "New memory" }); return h("div", { class: "row" }, t, h("button", { class: "btn", on: { click: act(async () => { await api("/api/memories", "POST", { scope: w.id, text: t.value }); load(); }) } }, "Remember")); })(),
      h("h2", { class: "t" }, "Your data"), h("div", { class: "row" }, h("button", { class: "btn", on: { click: act(async () => { const j = await api(`/api/knowledge/${w.id}/export`); const a = h("a", { href: URL.createObjectURL(new Blob([JSON.stringify(j, null, 2)], { type: "application/json" })), download: "hearthforge-knowledge.json" }); document.body.append(a); a.click(); a.remove(); }) } }, "Export"), h("button", { class: "btn danger", on: { click: act(async () => { if (confirm("Delete all indexed knowledge and memories for this folder?")) { await api("/api/knowledge/" + w.id, "DELETE"); load(); } }) } }, "Delete everything")));
  }); load();
  const q = h("input", { type: "search", placeholder: "Search your indexed files…", "aria-label": "Search knowledge" });
  const doSearch = act(async () => { const r = await api("/api/knowledge/search", "POST", { scope: w.id, query: q.value }); fill(res, r.length ? r.map((x) => h("div", { class: "card flat" }, h("div", { class: "mono" }, `${x.path} · ${x.loc}`), h("pre", { class: "mono" }, x.text))) : h("div", { class: "notice" }, "No matches.")); });
  q.addEventListener("keydown", (e) => { if (e.key === "Enter") doSearch(); });
  return pageOf(h("h1", {}, "Knowledge and memory"), h("p", { class: "lede" }, "Local keyword (BM25) search with citations. Indexed text is untrusted data. Vector search is not implemented yet."), h("div", { class: "row" }, q, h("button", { class: "btn", on: { click: doSearch } }, "Search")), res, box);
}

// ---------------------------------------------------------------- Hardware / Usage / Guide
function hardwareView() {
  if (!S.hw) return pageOf(h("h1", {}, "Hardware fit"), h("div", { class: "notice" }, h("span", { class: "spin" }), " Detecting hardware…"));
  const hw = S.hw.hardware, VC = { gpu: "ok", hybrid: "warn", cpu: "warn", no: "bad" }, VT = { gpu: "Fits GPU", hybrid: "GPU + CPU", cpu: "CPU only", no: "Too large" };
  return pageOf(h("h1", {}, "Hardware fit"), h("p", { class: "lede" }, `${hw.os} · ${hw.cpu_threads} threads · ${hw.ram_gb} GB RAM (${hw.ram_available_gb} free) · ${hw.disk_free_gb} GB disk free · ` + (hw.gpus.length ? hw.gpus.map((g) => `${g.name}${g.vram_gb ? " " + g.vram_gb + " GB" : ""}`).join(", ") : "no dedicated GPU detected")),
    S.hw.suggested && h("div", { class: "notice ok" }, h("strong", {}, "Suggested starting size: "), `${S.hw.suggested.params_b}B at ${S.hw.suggested.quant}, ${S.hw.context} context.`), S.hw.disk_warning && h("div", { class: "notice warn" }, "Low disk space."),
    h("table", {}, h("thead", {}, h("tr", {}, ["Size", "Memory needed (est.)", "Download", "Verdict"].map((t) => h("th", {}, t)))), h("tbody", {}, S.hw.options.map((o) => h("tr", {}, h("td", {}, o.params_b + "B " + o.quant), h("td", {}, `${o.total_gb} GB (weights ${o.weights_gb} + context ${o.kv_cache_gb})`), h("td", {}, "≈" + o.disk_gb + " GB"), h("td", {}, h("span", { class: "badge " + VC[o.verdict] }, VT[o.verdict]), " ", h("span", { class: "muted small" }, o.note)))))),
    h("ul", { class: "muted" }, S.hw.notes.map((n) => h("li", {}, n))));
}
function usageView() {
  const box = pageOf(h("h1", {}, "Usage and audit"), h("div", { class: "notice" }, h("span", { class: "spin" }), " Loading…")), wrap = box.firstChild;
  Promise.all([api("/api/usage"), api("/api/audit?n=150")]).then(([u, a]) => {
    fill(wrap, h("h1", {}, "Usage and audit"), h("p", { class: "lede" }, "Token counts marked “reported” come from the provider; “estimated” are guesses. Cost appears only where you configured a price."),
      u.rows.length ? h("table", {}, h("thead", {}, h("tr", {}, ["Provider", "Model", "Where", "Calls", "Tokens in/out", "Source", "Cost"].map((t) => h("th", {}, t)))), h("tbody", {}, u.rows.map((r) => h("tr", {}, h("td", {}, r.provider), h("td", { class: "mono" }, r.model), h("td", {}, r.remote ? "remote" : "local"), h("td", {}, r.calls), h("td", {}, `${r.pt}/${r.ct}`), h("td", {}, r.src), h("td", {}, r.cost == null ? "unknown" : "$" + r.cost.toFixed(4)))))) : h("div", { class: "notice" }, "No model calls yet."),
      h("h2", { class: "t" }, "Audit log (latest)"), h("table", {}, h("tbody", {}, a.slice().reverse().map((x) => h("tr", {}, h("td", { class: "mono" }, new Date(x.ts * 1000).toLocaleString()), h("td", {}, x.kind), h("td", { class: "mono muted small" }, JSON.stringify(Object.fromEntries(Object.entries(x).filter(([k]) => !["ts", "kind"].includes(k)))).slice(0, 200)))))));
  }).catch(() => {});
  return box;
}
function guideView() {
  const q = h("input", { type: "search", placeholder: "Search the guide…", "aria-label": "Search the guide" }), list = h("div", { class: "guide" });
  const steps = (s) => h("ol", {}, s.map((x) => h("li", {}, inlineMd(x))));
  const paint = () => { const t = q.value.toLowerCase(); fill(list, ...GUIDE.filter((s) => !t || JSON.stringify(s).toLowerCase().includes(t)).map((s) => h("details", { open: !!t || s.id === "start" }, h("summary", {}, s.title), h("div", { class: "gb" }, s.intro && h("p", {}, inlineMd(s.intro)), s.steps && steps(s.steps), (s.subs || []).filter((x) => !t || JSON.stringify(x).toLowerCase().includes(t)).map((sub) => h("details", { open: !!t }, h("summary", {}, sub.title), h("div", { class: "gb" }, steps(sub.steps))))))));
    if (!list.children.length) list.append(h("div", { class: "notice" }, "Nothing matches that search.")); };
  q.addEventListener("input", paint); paint();
  return pageOf(h("h1", {}, "Guide"), h("p", { class: "lede" }, "How to connect each kind of model and use every feature."), h("div", { class: "row" }, q, h("button", { class: "btn", on: { click: () => openConnectWizard() } }, icon("plug", 15), "Connect a model"), h("button", { class: "btn", on: { click: () => openFolderPicker() } }, icon("folder", 15), "Open a folder")), list);
}
