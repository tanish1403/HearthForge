"use strict";
// Shared UI toolkit. Everything is built with DOM nodes / text nodes, never innerHTML,
// so file contents, model output and web pages can never inject markup or script.
const $ = (s, r = document) => r.querySelector(s);

function h(tag, props, ...kids) {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(props || {})) {
    if (v === false || v == null) continue;
    if (k === "class") e.className = v;
    else if (k === "on") for (const [ev, fn] of Object.entries(v)) e.addEventListener(ev, fn);
    else if (["value", "checked", "disabled", "type", "id", "title", "placeholder", "rows", "min", "step", "selected", "open", "name", "autocomplete", "spellcheck"].includes(k)) e[k] = v;
    else e.setAttribute(k, v === true ? "" : v);
  }
  for (const kid of kids.flat(Infinity)) { if (kid == null || kid === false) continue; e.append(kid.nodeType ? kid : document.createTextNode(String(kid))); }
  return e;
}

// Replace an element's children from nested arrays / falsy values (DOM replaceChildren() can't take arrays).
function fill(el, ...kids) { el.replaceChildren(...kids.flat(Infinity).filter((k) => k != null && k !== false).map((k) => (k.nodeType ? k : document.createTextNode(String(k))))); return el; }

const SVGNS = "http://www.w3.org/2000/svg";
const ICONS = {
  home: "M4 11l8-7 8 7v9h-5v-6H9v6H4z", chat: "M21 12a8 8 0 0 1-11.6 7.1L4 20l1-4.6A8 8 0 1 1 21 12z", bot: "M5 8h14v10H5z|M12 8V4|M9 13h.01|M15 13h.01|M2 13v2|M22 13v2",
  folder: "M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z", globe: "M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18z|M3 12h18|M12 3c2.5 2.5 3.5 5.5 3.5 9s-1 6.5-3.5 9c-2.5-2.5-3.5-5.5-3.5-9s1-6.5 3.5-9z",
  cpu: "M7 7h10v10H7z|M9 3v4M15 3v4M9 17v4M15 17v4M3 9h4M3 15h4M17 9h4M17 15h4", book: "M4 5a2 2 0 0 1 2-2h13v16H6a2 2 0 0 0-2 2z|M4 19V5", plug: "M9 3v5M15 3v5M6 8h12v3a6 6 0 0 1-12 0z|M12 17v4",
  chart: "M4 20V4|M4 20h16|M8 16v-4M12 16V8M16 16v-6", guide: "M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18z|M9.5 9.5a2.5 2.5 0 1 1 3.5 2.3c-.7.4-1 .9-1 1.7|M12 17h.01", plus: "M12 5v14M5 12h14",
  check: "M5 13l4 4L19 7", x: "M6 6l12 12M18 6L6 18", search: "M11 4a7 7 0 1 0 0 14 7 7 0 0 0 0-14z|M21 21l-4.3-4.3", send: "M22 2L11 13|M22 2l-7 20-4-9-9-4z", stop: "M7 7h10v10H7z",
  copy: "M9 9h11v11H9z|M5 15V5h10", trash: "M4 7h16M10 11v6M14 11v6M6 7l1 13h10l1-13M9 7V4h6v3", spark: "M12 3l2 6 6 2-6 2-2 6-2-6-6-2 6-2z", shield: "M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6z",
  up: "M12 19V5M6 11l6-6 6 6", chev: "M9 6l6 6-6 6", menu: "M4 7h16M4 12h16M4 17h16", sliders: "M4 6h10M18 6h2M4 12h4M12 12h8M4 18h12|M16 4v4M10 10v4M18 16v4", play: "M8 5l11 7-11 7z", key: "M14 10a4 4 0 1 0-3.5 4L21 14v4h-3v3h-3v-3l-4.5-2",
};
function icon(name, size = 18) {
  const s = document.createElementNS(SVGNS, "svg");
  for (const [k, v] of Object.entries({ viewBox: "0 0 24 24", width: size, height: size, fill: "none", stroke: "currentColor", "stroke-width": "1.8", "stroke-linecap": "round", "stroke-linejoin": "round", "aria-hidden": "true" })) s.setAttribute(k, v);
  for (const d of (ICONS[name] || ICONS.spark).split("|")) { const p = document.createElementNS(SVGNS, "path"); p.setAttribute("d", d); s.append(p); }
  return s;
}

function toast(msg, ms = 4800) {
  const t = $("#toast"); if (!t) return; t.textContent = msg; t.classList.add("show"); clearTimeout(toast.t); toast.t = setTimeout(() => t.classList.remove("show"), ms);
}

async function copyText(text) {
  try { await navigator.clipboard.writeText(text); toast("Copied"); }
  catch (_) { const ta = h("textarea", { value: text }); document.body.append(ta); ta.select(); try { document.execCommand("copy"); toast("Copied"); } catch (e) { toast("Copy failed"); } ta.remove(); }
}

// ---------------------------------------------------------------- safe markdown
function inlineMd(text) {
  const frag = document.createDocumentFragment();
  const re = /(`[^`\n]+`)|(\*\*[^*\n]+\*\*)|(\*[^*\n]+\*)|(\[([^\]\n]+)\]\((https?:\/\/[^\s)]+)\))|(\[\d{1,2}\])/g;
  let last = 0, m;
  while ((m = re.exec(text))) {
    if (m.index > last) frag.append(text.slice(last, m.index));
    if (m[1]) frag.append(h("code", {}, m[1].slice(1, -1)));
    else if (m[2]) frag.append(h("strong", {}, m[2].slice(2, -2)));
    else if (m[3]) frag.append(h("em", {}, m[3].slice(1, -1)));
    else if (m[4]) frag.append(h("a", { href: m[6], target: "_blank", rel: "noopener noreferrer" }, m[5]));
    else frag.append(h("sup", { class: "cite" }, m[7]));
    last = re.lastIndex;
  }
  if (last < text.length) frag.append(text.slice(last));
  return frag;
}
function codeBlock(code, lang) {
  return h("div", { class: "codeblock" }, h("header", {}, h("span", {}, lang || "code"), h("button", { class: "btn sm ghost", on: { click: () => copyText(code) } }, icon("copy", 14), "Copy")), h("pre", {}, h("code", {}, code)));
}
function md(text) {
  const root = h("div", { class: "md" }), lines = String(text).split("\n"); let i = 0;
  const isBlock = (l) => /^(```|#{1,4}\s|\s*[-*]\s|\s*\d+\.\s|>)/.test(l);
  while (i < lines.length) {
    const l = lines[i]; let m;
    if ((m = l.match(/^```([\w+-]*)/))) { const buf = []; i++; while (i < lines.length && !lines[i].startsWith("```")) buf.push(lines[i++]); i++; root.append(codeBlock(buf.join("\n"), m[1])); continue; }
    if ((m = l.match(/^(#{1,4})\s+(.*)/))) { root.append(h("h" + Math.min(m[1].length + 2, 5), {}, inlineMd(m[2]))); i++; continue; }
    if (/^\s*[-*]\s+/.test(l)) { const ul = h("ul"); while (i < lines.length && /^\s*[-*]\s+/.test(lines[i])) ul.append(h("li", {}, inlineMd(lines[i++].replace(/^\s*[-*]\s+/, "")))); root.append(ul); continue; }
    if (/^\s*\d+\.\s+/.test(l)) { const ol = h("ol"); while (i < lines.length && /^\s*\d+\.\s+/.test(lines[i])) ol.append(h("li", {}, inlineMd(lines[i++].replace(/^\s*\d+\.\s+/, "")))); root.append(ol); continue; }
    if (/^>\s?/.test(l)) { const buf = []; while (i < lines.length && /^>\s?/.test(lines[i])) buf.push(lines[i++].replace(/^>\s?/, "")); root.append(h("blockquote", {}, inlineMd(buf.join("\n")))); continue; }
    if (!l.trim()) { i++; continue; }
    const buf = [l]; i++; while (i < lines.length && lines[i].trim() && !isBlock(lines[i])) buf.push(lines[i++]);
    root.append(h("p", {}, inlineMd(buf.join("\n"))));
  }
  return root;
}

// ---------------------------------------------------------------- modal
let _modalStack = [];
function openModal({ title, wide = false, body, footer, onClose }) {
  const prev = document.activeElement;
  const bodyEl = h("div", { class: "mb" }), footEl = h("footer", {});
  const titleEl = h("h2", { id: "mt" + Date.now() }, title);
  const modal = h("div", { class: "modal" + (wide ? " wide" : ""), role: "dialog", "aria-modal": "true", "aria-labelledby": titleEl.id }, h("header", {}, titleEl, h("button", { class: "btn ghost sm", "aria-label": "Close", on: { click: () => api_.close() } }, icon("x"))), bodyEl, footEl);
  const overlay = h("div", { class: "overlay", on: { mousedown: (e) => { if (e.target === overlay) api_.close(); } } }, modal);
  const api_ = {
    el: modal, body: bodyEl,
    set(b, f) { fill(bodyEl, b); fill(footEl, f); footEl.hidden = !(f && [].concat(f).length); },
    title(t) { titleEl.textContent = t; },
    close() { overlay.remove(); _modalStack = _modalStack.filter((m) => m !== api_); document.removeEventListener("keydown", key, true); if (prev && prev.focus) prev.focus(); onClose && onClose(); },
  };
  function key(e) {
    if (_modalStack[_modalStack.length - 1] !== api_) return;
    if (e.key === "Escape") { e.stopPropagation(); api_.close(); }
    if (e.key === "Tab") { const f = [...modal.querySelectorAll("button:not(:disabled), input:not(:disabled), select, textarea, a[href]")]; if (!f.length) return; const a = f[0], z = f[f.length - 1]; if (e.shiftKey && document.activeElement === a) { e.preventDefault(); z.focus(); } else if (!e.shiftKey && document.activeElement === z) { e.preventDefault(); a.focus(); } }
  }
  document.addEventListener("keydown", key, true);
  api_.set(body, footer); _modalStack.push(api_); document.body.append(overlay);
  const first = modal.querySelector("[data-autofocus], input, textarea, select"); (first || modal.querySelector("button")).focus();
  return api_;
}

// ---------------------------------------------------------------- api
async function api(path, method = "GET", body, opts = {}) {
  let r;
  try { r = await fetch(path, { method, credentials: "same-origin", headers: body ? { "Content-Type": "application/json" } : {}, body: body ? JSON.stringify(body) : undefined, signal: opts.signal }); }
  catch (e) { if (e.name === "AbortError") throw e; if (!opts.quiet) toast("Cannot reach the Hearthforge server. Is it still running?"); throw e; }
  if (r.status === 401) { toast("Not authorised: open the URL printed in the terminal."); throw new Error("unauthorized"); }
  const data = await r.json().catch(() => ({}));
  if (!r.ok) { const m = data.detail || data.error || r.statusText; const msg = typeof m === "string" ? m : JSON.stringify(m); if (!opts.quiet) toast(msg); const err = new Error(msg); err.status = r.status; throw err; }
  return data;
}
const act = (fn) => async (...a) => { try { await fn(...a); } catch (e) { /* toast already shown */ } };
const fmtT = (ts) => new Date(ts * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
const isLocalUrl = (u) => { try { const x = new URL(/^[a-z]+:\/\//i.test(u) ? u : "http://" + u).hostname.replace(/^\[|\]$/g, ""); return x === "localhost" || /^127\./.test(x) || x === "::1"; } catch (_) { return true; } };
const hostOf = (u) => { try { return new URL(/^[a-z]+:\/\//i.test(u) ? u : "http://" + u).hostname; } catch (_) { return u; } };
