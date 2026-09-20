"use strict";
/* analysis_ai web UI. Vanilla JS, no build step. Untrusted text only ever reaches the DOM through
   textContent / createTextNode; the one HTML path is markdown, sanitised by DOMPurify first. */

// ---------------------------------------------------------------- helpers
function h(tag, props, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(props || {})) {
    if (v == null || v === false) continue;
    if (k === "class") el.className = v;
    else if (k === "text") el.textContent = v;
    else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else el.setAttribute(k, v === true ? "" : v);
  }
  for (const kid of kids.flat(Infinity)) {
    if (kid == null || kid === false) continue;
    el.append(kid.nodeType ? kid : document.createTextNode(String(kid)));
  }
  return el;
}

// replaceChildren that skips null/false (which would otherwise be stringified into the page).
function fill(el, ...kids) {
  el.replaceChildren(...kids.flat(Infinity).filter((k) => k != null && k !== false));
}

async function api(path, { method = "GET", body } = {}) {
  const res = await fetch(path, {
    method,
    headers: body !== undefined || method !== "GET" ? { "Content-Type": "application/json" } : {},
    body: body !== undefined ? JSON.stringify(body) : method !== "GET" ? "{}" : undefined,
  });
  let data = null;
  try { data = await res.json(); } catch (_) { /* non-JSON error body */ }
  if (!res.ok) throw new Error((data && data.error) || `${res.status} ${res.statusText}`);
  return data;
}

function toast(message) {
  const el = h("div", { class: "toast", text: message });
  document.body.append(el);
  setTimeout(() => el.remove(), 4000);
}

const NOTES_URL = `${location.protocol}//${location.hostname}`; // the notes app answers on port 80
function noteHref(projectId, noteId, { start, page } = {}) {
  const hash = start != null ? `#t=${Math.floor(start)}` : page != null ? `#page=${page}` : "";
  return `${NOTES_URL}/projects/${projectId}/notes/${noteId}${hash}`;
}
function atToLoc(at) { // "12:34" | "1:13:19" | "p.5" -> {start} | {page}
  if (!at) return {};
  const p = /^p\.(\d+)$/.exec(at);
  if (p) return { page: Number(p[1]) };
  const parts = at.split(":").map(Number);
  if (parts.some(Number.isNaN)) return {};
  return { start: parts.reduce((a, b) => a * 60 + b, 0) };
}
const fmtMin = (s) => (s < 90 ? "<2 min" : `~${Math.round(s / 60)} min`);
function ago(ts) {
  if (!ts) return "never";
  const s = Math.max(0, Date.now() / 1000 - ts);
  return s < 60 ? "just now" : s < 3600 ? `${Math.floor(s / 60)} min ago` : `${Math.floor(s / 3600)} h ago`;
}
const ICON = { audio: "🎙", video: "🎬", document: "📄", text: "📝" };

// ---------------------------------------------------------------- state
const S = {
  status: null, health: null, settings: null, tab: null, statusKey: "",
  openClasses: new Set(), seenClasses: new Set(), openLogs: new Set(), collapsedClasses: new Set(),
  chat: { scope: null, mode: "strict", messages: [], busy: false, controller: null },
  library: { project: null },
};
try {
  const saved = JSON.parse(localStorage.getItem("aai-collapsed-classes") || "null");
  if (Array.isArray(saved)) S.collapsedClasses = new Set(saved);
} catch (_) { /* storage unavailable */ }
function saveCollapsedClasses() {
  try { localStorage.setItem("aai-collapsed-classes", JSON.stringify([...S.collapsedClasses])); } catch (_) { /* ignore */ }
}
try {
  const saved = JSON.parse(sessionStorage.getItem("aai-chat") || "null");
  if (saved) Object.assign(S.chat, { messages: saved.messages || [], scope: saved.scope ? new Set(saved.scope) : null, mode: saved.mode || "strict" });
} catch (_) { /* storage unavailable */ }
function saveChat() {
  try {
    sessionStorage.setItem("aai-chat", JSON.stringify({ messages: S.chat.messages.slice(-30), scope: S.chat.scope ? [...S.chat.scope] : null, mode: S.chat.mode }));
  } catch (_) { /* ignore */ }
}

const $view = () => document.getElementById("view");
const projects = () => (S.status ? S.status.overview.projects : []);
const runningJob = () => (S.status ? S.status.jobs.find((j) => j.status === "running") : null);
const activeJobs = () => (S.status ? S.status.jobs.filter((j) => j.status === "running" || j.status === "queued") : []);

// ---------------------------------------------------------------- polling
async function refresh() {
  try {
    S.status = await api("/api/status");
    S.statusError = null;
  } catch (e) {
    S.statusError = e.message;
  }
  renderHeader();
  const key = JSON.stringify(S.status);
  if (key !== S.statusKey) {
    S.statusKey = key;
    if (TABS[S.tab] && TABS[S.tab].onStatus) TABS[S.tab].onStatus();
  }
  setTimeout(refresh, activeJobs().length ? 2000 : 8000);
}
async function refreshHealth() {
  try { S.health = await api("/api/health"); } catch (_) { S.health = null; }
  renderHeader();
  setTimeout(refreshHealth, 30000);
}

function renderHeader() {
  const right = document.getElementById("header-right");
  const job = runningJob();
  const dot = (ok, label) => h("span", { title: ok ? `${label} reachable` : `${label} NOT reachable` }, ok ? "● " : "○ ", label);
  fill(right,
    job ? h("span", { class: "chip info", text: `Working: ${job.title}${job.progress.total ? ` (${job.progress.done}/${job.progress.total})` : ""}` }) : null,
    S.health ? dot(S.health.ollama.ok, "Ollama") : null,
    S.health ? dot(S.health.notes_app.ok, "notes app") : null,
    S.status
      ? h("span", { title: S.status.sync.last_error || "" },
          S.status.sync.last_error ? "Sync failed" : `Synced ${ago(S.status.sync.last_ok_at)}`)
      : S.statusError ? h("span", { class: "chip bad", text: "Server unreachable" }) : null,
    h("a", { href: NOTES_URL, text: "← notes_app" }),
  );
}

// ---------------------------------------------------------------- shared pieces
const CARD = {
  current: ["Up to date", "ok"], short: ["Short note (kept as is)", ""], stale: ["Out of date", "warn"],
  none: ["Not built", ""], "needs-transcript": ["Needs transcript", ""], "search-only": ["Search only (large)", ""], empty: ["Empty", ""],
};
const INDEX = { current: ["Indexed", "ok"], stale: ["Re-index needed", "warn"], none: ["Not indexed", ""], "n/a": ["—", ""] };
const chip = (map, key) => { const [t, c] = map[key] || [key, ""]; return h("span", { class: `chip ${c}`, text: t }); };

async function submitJob(body, what) {
  try {
    await api("/api/jobs", { method: "POST", body });
    toast(`Queued: ${what}`);
    await refresh();
  } catch (e) { toast(e.message); }
}

function md(el, text) {
  el.classList.add("md");
  el.innerHTML = DOMPurify.sanitize(marked.parse(text || "", { gfm: true }));
  for (const a of el.querySelectorAll("a")) { a.target = "_blank"; a.rel = "noopener noreferrer"; }
}

// ---------------------------------------------------------------- note preview modal
async function openNote(noteId) {
  const back = h("div", { class: "modal-back", onclick: (e) => { if (e.target === back) back.remove(); } });
  const box = h("div", { class: "modal" }, h("p", { class: "muted", text: "Loading…" }));
  back.append(box);
  document.body.append(back);
  try {
    const d = await api(`/api/notes/${noteId}`);
    box.replaceChildren(
      h("div", { class: "modal-head" },
        h("h2", { text: `${ICON[d.type] || ""} ${d.title}` }),
        h("a", { class: "btn small", href: noteHref(d.project_id, d.id), target: "_blank", rel: "noopener", text: "Open in notes_app ↗" }),
        h("button", { class: "btn small", onclick: () => back.remove(), text: "Close" })),
      h("p", { class: "muted small", text: `${d.project} / ${d.folder || "(top level)"} · ${d.type}` }),
      d.card ? renderCard(d) : h("p", { class: "banner info", text: "No summary card yet — build it from the Pipeline tab." }),
      renderSource(d),
    );
  } catch (e) { box.replaceChildren(h("p", { class: "banner bad", text: e.message })); }
}

function atLink(d, at, label) {
  return at ? h("a", { href: noteHref(d.project_id, d.id, atToLoc(at)), target: "_blank", rel: "noopener", text: label || `[${at}]` }) : null;
}

function renderCard(d) {
  const c = d.card;
  if (c.short) return h("div", { class: "card" }, h("h3", { text: "Short note (shown as written)" }), h("div", { class: "body-text", text: c.summary }));
  const sec = (title, items, fn) => (items && items.length ? h("div", null, h("h3", { text: title }), h("ul", { class: "plain" }, items.map((i) => h("li", null, fn(i))))) : null);
  const txt = (i) => (typeof i === "string" ? i : i.text);
  return h("div", { class: "card" },
    h("h2", { text: c.title }),
    h("p", { text: c.summary }),
    h("p", { class: "muted small", text: `Built with ${c.meta.model}${c.meta.seconds ? ` in ${c.meta.seconds}s` : ""}` }),
    sec("Topics", c.topics, (t) => [h("strong", { text: t.name }), " ", atLink(d, t.at), " — ", t.explanation]),
    sec("Key terms", c.key_terms, (t) => [h("strong", { text: t.term }), ": ", t.definition]),
    sec("Formulas and rules", c.formulas_and_rules, (f) => [f.statement, " ", h("span", { class: "muted", text: `(${f.context})` })]),
    sec("Examples", c.examples, (e) => [e.description, " → ", e.takeaway]),
    sec("Flagged as important", c.instructor_emphasis, (e) => [txt(e), " ", atLink(d, e.at)]),
    sec("Exams, deadlines, assignments", c.logistics, (e) => [txt(e), " ", atLink(d, e.at)]),
  );
}

function renderSource(d) {
  if (d.transcript === null) return h("p", { class: "banner info", text: "This recording hasn't been transcribed yet." });
  if (d.transcript) {
    const t = d.transcript;
    const fmt = (s) => { s = Math.floor(s); const hh = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), ss = s % 60; return (hh ? `${hh}:${String(m).padStart(2, "0")}` : String(m).padStart(2, "0")) + `:${String(ss).padStart(2, "0")}`; };
    return h("details", null,
      h("summary", { text: `Transcript (${t.segments.length} segments · ${t.model} · ${t.language})` }),
      h("div", { class: "body-text" }, t.segments.map((s) => h("div", { class: "transcript-line" },
        h("a", { class: "t", href: noteHref(d.project_id, d.id, { start: s.start }), target: "_blank", rel: "noopener", text: fmt(s.start) }),
        h("span", { text: s.text })))));
  }
  return h("details", null,
    h("summary", { text: "Source text" }),
    h("div", { class: "body-text", text: d.body + (d.body_truncated ? "\n\n… (truncated)" : "") }));
}

// ---------------------------------------------------------------- pipeline tab
function classSummary(p) {
  const media = p.notes.filter((n) => n.type === "audio" || n.type === "video");
  const done = media.filter((n) => n.transcript).length;
  const eligible = p.notes.filter((n) => !["empty", "search-only", "short"].includes(n.card));
  const current = eligible.filter((n) => n.card === "current").length;
  return { media, done, eligible, current, pending: media.filter((n) => !n.transcript) };
}

function noteActions(n) {
  const acts = [];
  const isMedia = n.type === "audio" || n.type === "video";
  if (isMedia && !n.transcript) {
    acts.push(h("button", { class: "btn small primary", title: "Whisper on the GPU; runs only because you clicked", onclick: () => {
      if (confirm(`Transcribe "${n.title}"?\n\nModel ${S.status.whisper.model}, language ${S.status.whisper.language}. Estimated ${fmtMin(n.estimate_seconds)}.\nThis uses the GPU and unloads any Ollama model first.`))
        submitJob({ kind: "transcribe", ids: [n.id] }, `transcribe ${n.title}`);
    }, text: `Transcribe ${fmtMin(n.estimate_seconds)}` }));
  }
  if (isMedia && n.transcript) {
    acts.push(h("button", { class: "btn small", onclick: () => {
      if (confirm(`Re-transcribe "${n.title}"?\n\nThe current transcript is kept in transcripts/previous/. Estimated ${fmtMin(n.estimate_seconds)}.`))
        submitJob({ kind: "transcribe", ids: [n.id], force: true }, `re-transcribe ${n.title}`);
    }, text: "Re-transcribe" }));
  }
  if (n.card === "none" || n.card === "stale") {
    acts.push(h("button", { class: "btn small primary", onclick: () => submitJob({ kind: "extract", ids: [n.id] }, `summary card for ${n.title}`), text: "Build card" }));
  } else if (n.card === "current") {
    acts.push(h("button", { class: "btn small", onclick: () => {
      if (confirm(`Rebuild the summary card for "${n.title}" from scratch?`)) submitJob({ kind: "extract", ids: [n.id], force: true }, `rebuild card ${n.title}`);
    }, text: "Rebuild" }));
  }
  if (n.card !== "empty") acts.push(h("button", { class: "btn small", onclick: () => openNote(n.id), text: "View" }));
  return h("div", { class: "actions" }, acts);
}

function classBlock(p) {
  const sum = classSummary(p);
  const needsUpdate = p.notes.some((n) => n.card === "none" || n.card === "stale" || n.index === "none" || n.index === "stale") || ["none", "stale"].includes(p.rollup);
  const estimate = sum.pending.reduce((a, n) => a + (n.estimate_seconds || 0), 0);
  const det = h("div", { class: "card" });
  if (!S.seenClasses.has(p.id)) { // first sight: open the note table for classes with recordings (that's where Transcribe lives)
    S.seenClasses.add(p.id);
    if (sum.media.length) S.openClasses.add(p.id);
  }
  const rollupLabel = { "no-cards": "no overview yet", none: "overview not built", stale: "overview out of date", current: "overview up to date" }[p.rollup];
  const collapsed = S.collapsedClasses.has(p.id);
  const toggleCollapsed = () => {
    collapsed ? S.collapsedClasses.delete(p.id) : S.collapsedClasses.add(p.id);
    saveCollapsedClasses();
    renderPipeline();
  };
  det.append(h("div", { class: "class-head" },
    h("button", { class: "class-toggle", title: collapsed ? "Expand" : "Minimize", onclick: toggleCollapsed, text: collapsed ? "▸" : "▾" }),
    h("h2", { style: "cursor:pointer", onclick: toggleCollapsed, text: p.name }),
    sum.media.length ? h("span", { class: `chip ${sum.pending.length ? "" : "ok"}`, text: `${sum.done}/${sum.media.length} recordings transcribed` }) : null,
    h("span", { class: `chip ${sum.eligible.length && sum.current === sum.eligible.length ? "ok" : ""}`, text: `${sum.current}/${sum.eligible.length} summary cards` }),
    h("span", { class: `chip ${p.rollup === "current" ? "ok" : p.rollup === "stale" ? "warn" : ""}`, text: rollupLabel }),
  ));
  if (collapsed) return det;
  det.append(h("div", { class: "class-head", style: "margin-top:.6rem" },
    h("button", { class: "btn primary", disabled: !needsUpdate || undefined,
      title: "Builds cards for new/edited notes, then the class overview and search index. Never transcribes.",
      onclick: () => submitJob({ kind: "update", project_id: p.id }, `update ${p.name}`), text: needsUpdate ? "Update class" : "Class is up to date" }),
    h("button", { class: "btn", disabled: !sum.pending.length || undefined, onclick: () => {
      if (confirm(`Transcribe ${sum.pending.length} recording(s) in ${p.name}?\n\nModel ${S.status.whisper.model}, language ${S.status.whisper.language}. Estimated ${fmtMin(estimate)} in total.\nUses the GPU; runs one at a time; you can cancel.`))
        submitJob({ kind: "transcribe", ids: sum.pending.map((n) => n.id), project_id: p.id }, `transcribe ${sum.pending.length} recordings in ${p.name}`);
    }, text: sum.pending.length ? `Transcribe ${sum.pending.length} pending (${fmtMin(estimate)})` : "Nothing to transcribe" }),
  ));

  const rows = [];
  let folder = null;
  for (const n of p.notes) {
    if (n.folder !== folder) {
      folder = n.folder;
      rows.push(h("tr", { class: "folder" }, h("td", { colspan: 5, text: folder || "(top level)" })));
    }
    const t = n.transcript;
    rows.push(h("tr", null,
      h("td", null, `${ICON[n.type] || ""} ${n.title}`),
      h("td", null, t === null ? h("span", { class: "muted", text: "—" })
        : t ? h("span", { class: "chip ok", title: `${t.segments} segments`, text: `${t.model} · ${t.language}` }) : h("span", { class: "chip", text: "Not transcribed" })),
      h("td", null, chip(CARD, n.card)),
      h("td", null, chip(INDEX, n.index)),
      h("td", null, noteActions(n))));
  }
  det.append(h("details", { style: "margin-top:.7rem", open: S.openClasses.has(p.id) || undefined,
      ontoggle: (e) => { e.target.open ? S.openClasses.add(p.id) : S.openClasses.delete(p.id); } },
    h("summary", { class: "muted small", text: `Notes (${p.notes.length})` }),
    h("div", { class: "scroll-x" }, h("table", { class: "notes" },
      h("thead", null, h("tr", null, ["Note", "Transcript", "Summary card", "Search index", ""].map((t) => h("th", { text: t })))),
      h("tbody", null, rows)))));
  return det;
}

function jobCard(j) {
  const pct = j.progress.total ? Math.round((100 * j.progress.done) / j.progress.total) : 0;
  const live = j.status === "running";
  const statusChip = { queued: ["Queued", ""], running: ["Running", "info"], done: ["Done", "ok"], failed: ["Failed", "bad"], cancelled: ["Cancelled", "warn"], interrupted: ["Interrupted", "warn"] }[j.status];
  const logId = j.id;
  const pre = h("pre", { class: "log", text: j.log.join("\n") });
  setTimeout(() => { pre.scrollTop = pre.scrollHeight; });
  return h("div", { class: "job" },
    h("div", { class: "job-head" },
      h("span", { class: "job-title", text: j.title }),
      h("span", { class: `chip ${statusChip[1]}`, text: statusChip[0] }),
      (j.status === "running" || j.status === "queued")
        ? h("button", { class: "btn small danger", onclick: async () => { try { await api(`/api/jobs/${j.id}/cancel`, { method: "POST" }); await refresh(); } catch (e) { toast(e.message); } }, text: "Cancel" }) : null),
    live ? h("div", { class: `bar ${j.progress.total ? "" : "indeterminate"}` }, h("div", { style: `width:${pct}%` })) : null,
    live && j.progress.current ? h("div", { class: "muted small", text: `${j.progress.done}/${j.progress.total} · ${j.progress.current}` }) : null,
    j.error ? h("div", { class: "small", style: "color:var(--bad)", text: j.error }) : null,
    h("details", { open: (live || S.openLogs.has(logId)) || undefined, ontoggle: (e) => { e.target.open ? S.openLogs.add(logId) : S.openLogs.delete(logId); } },
      h("summary", { class: "muted small", text: "Log" }), pre));
}

function renderPipeline() {
  const view = $view();
  if (!S.status) { view.replaceChildren(h("p", { class: "muted", text: S.statusError ? `Cannot reach the analysis server: ${S.statusError}` : "Loading…" })); return; }
  const st = S.status;
  const scroll = window.scrollY;
  const jobsPanel = h("div", { class: "jobs-panel" },
    h("div", { class: "card" }, h("h2", { text: "Jobs" }),
      st.jobs.length ? st.jobs.map(jobCard) : h("p", { class: "muted small", text: "Nothing has run yet. Nothing runs unless you start it." })));
  view.replaceChildren(h("div", { class: "pipeline" },
    h("div", null,
      h("div", { class: "card" },
        h("div", { class: "class-head" },
          h("h2", { text: "Your notes" }),
          h("span", { class: "muted small", text: `Read from the notes app automatically; last sync ${ago(st.sync.last_ok_at)}${st.sync.last_error ? ` — last attempt failed: ${st.sync.last_error}` : ""}` }),
          h("span", { class: "spacer" }),
          h("button", { class: "btn small", onclick: async () => { try { await api("/api/sync", { method: "POST" }); await refresh(); toast("Synced"); } catch (e) { toast(e.message); } }, text: "Sync now" })),
        h("p", { class: "muted small", text: `Transcription: ${st.whisper.model}, language "${st.whisper.language}" (${st.whisper.mode}). Summary cards & chat: ${st.models.extract} / ${st.models.chat}. Change these under Settings. Nothing here starts on its own — every button below is a job you choose to run.` })),
      st.overview.projects.length ? st.overview.projects.map(classBlock) : h("p", { class: "muted", text: "No classes yet — waiting for the first sync from the notes app." })),
    jobsPanel));
  window.scrollTo(0, scroll);
}

// ---------------------------------------------------------------- library tab
async function renderLibrary() {
  const view = $view();
  if (!S.status) { view.replaceChildren(h("p", { class: "muted", text: "Loading…" })); return; }
  const list = projects();
  if (!S.library.project || !list.some((p) => p.id === S.library.project)) S.library.project = list.length ? list[0].id : null;
  const sel = h("select", { onchange: (e) => { S.library.project = e.target.value; renderLibrary(); } },
    list.map((p) => h("option", { value: p.id, selected: p.id === S.library.project || undefined, text: p.name })));
  const body = h("div", { class: "library-grid" }, h("p", { class: "muted", text: "Loading…" }));
  view.replaceChildren(h("div", { class: "class-head", style: "margin-bottom:1rem" }, h("h2", { text: "Library" }), sel), body);
  if (!S.library.project) return;
  const p = list.find((x) => x.id === S.library.project);
  let lib;
  try { lib = await api(`/api/projects/${p.id}/library`); } catch (e) { body.replaceChildren(h("p", { class: "banner bad", text: e.message })); return; }
  if (lib.built === false) {
    body.replaceChildren(h("div", { class: "banner info" }, "Nothing has been built for this class yet. ",
      h("a", { href: "#pipeline", text: "Go to Pipeline" }), " to transcribe recordings and build summary cards."),
      noteList(p));
    return;
  }
  const filter = h("input", { type: "text", placeholder: "Filter glossary…" });
  const gl = h("dl", { class: "glossary" });
  const paintGlossary = () => {
    const q = filter.value.toLowerCase();
    gl.replaceChildren(...lib.glossary.filter((g) => !q || g.term.toLowerCase().includes(q) || g.definition.toLowerCase().includes(q))
      .flatMap((g) => [h("dt", { text: g.term }), h("dd", null, g.definition, h("div", { class: "muted small", text: [...new Set(g.sources)].join(", ") }))]));
  };
  filter.addEventListener("input", paintGlossary);
  paintGlossary();
  const bullet = (items, fn) => h("ul", { class: "plain" }, items.map((i) => h("li", null, fn(i))));
  const srcs = (e) => h("div", { class: "muted small", text: [...new Set(e.sources)].join(", ") });
  body.replaceChildren(
    h("div", { class: "card" }, h("h2", { text: "Overview" }), h("p", { text: lib.overview }),
      lib.rollupStale ? null : null,
      h("h3", { text: "Themes" }), bullet(lib.themes, (t) => [h("strong", { text: t.name }), " — ", t.description]),
      h("h3", { text: "How ideas connect" }), bullet(lib.connections, (c) => c),
      h("p", { class: "muted small", text: `Built with ${lib.model} on ${new Date(lib.generated_at).toLocaleString()}` })),
    h("div", { class: "card" }, h("h2", { text: "By folder" }), Object.entries(lib.groups).map(([k, v]) => h("div", null, h("h3", { text: k }), h("p", { text: v })))),
    h("div", { class: "card" }, h("h2", { text: "Exams, deadlines and assignments" }),
      lib.logistics.length ? bullet(lib.logistics, (l) => [l.text, srcs(l)]) : h("p", { class: "muted", text: "None found." }),
      h("h3", { text: "Flagged as important by the instructor" }),
      lib.emphasis.length ? bullet(lib.emphasis, (l) => [l.text, srcs(l)]) : h("p", { class: "muted", text: "None found." })),
    h("div", { class: "card" }, h("h2", { text: `Glossary (${lib.glossary.length})` }), filter, gl),
    noteList(p),
  );
}
function noteList(p) {
  const withContent = p.notes.filter((n) => n.card !== "empty");
  return h("div", { class: "card note-list" }, h("h2", { text: "Notes" }),
    h("ul", { class: "plain" }, withContent.map((n) => h("li", null,
      h("a", { onclick: () => openNote(n.id), text: `${ICON[n.type] || ""} ${n.folder ? n.folder + " / " : ""}${n.title}` }), " ", chip(CARD, n.card)))));
}

// ---------------------------------------------------------------- chat tab
function chatReadiness(names) {
  const byName = Object.fromEntries(projects().map((p) => [p.name, p]));
  const notBuilt = names.filter((n) => byName[n] && ["none", "no-cards"].includes(byName[n].rollup));
  const notIndexed = names.filter((n) => byName[n] && !byName[n].notes.some((x) => x.index === "current" || x.index === "stale"));
  return { notBuilt, notIndexed };
}

function linkifyCitations(root, sources) {
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, {
    acceptNode: (n) => (n.parentElement.closest("a, code, pre") ? NodeFilter.FILTER_REJECT : /\[\d+\]/.test(n.nodeValue) ? NodeFilter.FILTER_ACCEPT : NodeFilter.FILTER_REJECT),
  });
  const nodes = [];
  while (walker.nextNode()) nodes.push(walker.currentNode);
  for (const node of nodes) {
    const frag = document.createDocumentFragment();
    node.nodeValue.split(/(\[\d+\])/).forEach((part) => {
      const m = /^\[(\d+)\]$/.exec(part);
      if (!m) { frag.append(part); return; }
      const n = Number(m[1]);
      const src = sources && sources.find((s) => s.n === n);
      frag.append(h("a", { class: "cite", title: src ? `${src.title}${src.label ? " @ " + src.label : ""}` : "", onclick: src ? () => {
        const d = document.getElementById(`src-${src.msgId}-${n}`);
        if (d) { d.open = true; d.scrollIntoView({ block: "center", behavior: "smooth" }); }
      } : undefined, text: `[${n}]` }));
    });
    node.replaceWith(frag);
  }
}

function sourceItem(msgId, s) {
  const where = s.label ? ` @ ${s.label}` : "";
  return h("details", { id: `src-${msgId}-${s.n}` },
    h("summary", { text: `[${s.n}] ${s.project} › ${s.folder || "(top)"} › ${s.title}${where}` }),
    h("a", { href: noteHref(s.project_id, s.note_id, { start: s.start_sec, page: s.page }), target: "_blank", rel: "noopener", text: "Open in notes_app ↗" }),
    h("blockquote", { text: s.text.length > 700 ? s.text.slice(0, 700) + "…" : s.text }));
}

function paintMessage(msg, el) {
  if (msg.role === "user") { el.textContent = msg.display || msg.content; return; }
  const body = h("div", { class: msg.streaming ? "typing" : "" });
  md(body, msg.content || (msg.streaming ? "" : "(no answer)"));
  const srcs = msg.sources ? msg.sources.map((s) => ({ ...s, msgId: msg.id })) : null;
  linkifyCitations(body, srcs);
  const kids = [body];
  if (msg.error) kids.push(h("div", { class: "banner bad", style: "margin-top:.6rem", text: msg.error }));
  if (srcs) {
    const cited = srcs.filter((s) => s.cited), other = srcs.filter((s) => !s.cited);
    if (srcs.length) kids.push(h("div", { class: "sources" },
      h("div", { class: "muted", text: cited.length ? `Sources cited (${cited.length})` : "No passages were cited in this answer" }),
      cited.map((s) => sourceItem(msg.id, s)),
      other.length ? h("details", null, h("summary", { class: "muted", text: `Also retrieved (${other.length})` }), other.map((s) => sourceItem(msg.id, s))) : null));
  }
  if (!msg.streaming && msg.content) {
    kids.push(h("div", { class: "msg-tools" }, h("button", { class: "btn small", onclick: async () => { try { await navigator.clipboard.writeText(msg.content); toast("Copied"); } catch (_) { toast("Copy failed"); } }, text: "Copy" })));
  }
  el.replaceChildren(...kids);
}

async function ask({ message, display, task }) {
  const C = S.chat;
  if (C.busy) return;
  const names = [...(C.scope || new Set(projects().map((p) => p.name)))];
  const user = { role: "user", content: message, display: display || message };
  const bot = { role: "assistant", content: "", streaming: true, id: `m${Date.now()}` };
  C.messages.push(user, bot);
  C.busy = true;
  C.controller = new AbortController();
  renderChatMessages();
  const history = C.messages.slice(0, -2).filter((m) => m.content && !m.error).slice(-8).map((m) => ({ role: m.role, content: m.content }));
  try {
    const res = await fetch("/api/chat", {
      method: "POST", headers: { "Content-Type": "application/json" }, signal: C.controller.signal,
      body: JSON.stringify({ message, projects: names, mode: C.mode, history, task }),
    });
    if (!res.ok) { let e = `${res.status}`; try { e = (await res.json()).error || e; } catch (_) { /* */ } throw new Error(e); }
    const reader = res.body.getReader(), dec = new TextDecoder();
    let buf = "";
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      buf += dec.decode(value, { stream: true });
      let nl;
      while ((nl = buf.indexOf("\n")) >= 0) {
        const line = buf.slice(0, nl).trim(); buf = buf.slice(nl + 1);
        if (!line) continue;
        const ev = JSON.parse(line);
        if (ev.type === "delta") bot.content += ev.text;
        else if (ev.type === "sources") bot.sources = ev.sources;
        else if (ev.type === "error") bot.error = ev.message;
        renderChatMessages(true);
      }
    }
  } catch (e) {
    if (e.name !== "AbortError") bot.error = e.message; else bot.content += "\n\n*(stopped)*";
  } finally {
    bot.streaming = false; C.busy = false; C.controller = null;
    renderChatMessages(); saveChat(); updateComposer();
  }
}

let paintQueued = false;
function renderChatMessages(soft) {
  const box = document.getElementById("messages");
  if (!box) return;
  if (soft) { // streaming: repaint only the last assistant bubble, at most once per frame
    if (paintQueued) return;
    paintQueued = true;
    requestAnimationFrame(() => {
      paintQueued = false;
      const last = box.lastElementChild, msg = S.chat.messages[S.chat.messages.length - 1];
      if (last && msg && msg.role === "assistant") { const near = window.innerHeight + window.scrollY >= document.body.scrollHeight - 120; paintMessage(msg, last); if (near) window.scrollTo(0, document.body.scrollHeight); }
    });
    return;
  }
  box.replaceChildren(...S.chat.messages.map((m) => { const el = h("div", { class: `msg ${m.role}` }); paintMessage(m, el); return el; }));
  if (!S.chat.messages.length) box.append(h("p", { class: "muted", text: "Ask a question about your notes, or use the study tools on the left. Answers cite the note and the timestamp or page." }));
  window.scrollTo(0, document.body.scrollHeight);
}
function updateComposer() {
  const send = document.getElementById("send"), stop = document.getElementById("stop");
  if (send) send.disabled = S.chat.busy;
  if (stop) stop.style.display = S.chat.busy ? "" : "none";
}

function chatBanner() {
  const box = document.getElementById("chat-banner");
  if (!box || !S.status) return;
  const names = [...(S.chat.scope || new Set(projects().map((p) => p.name)))];
  const { notBuilt, notIndexed } = chatReadiness(names);
  const job = runningJob();
  fill(box,
    notIndexed.length ? h("div", { class: "banner" }, `Not searchable yet: ${notIndexed.join(", ")}. `, h("a", { href: "#pipeline", text: "Update it in Pipeline" }), " — until then answers can't cite those notes.") : null,
    notBuilt.length ? h("div", { class: "banner info" }, `No class overview yet for: ${notBuilt.join(", ")}. Answers will rely on retrieved passages only.`) : null,
    job ? h("div", { class: "banner info", text: `A job is running (${job.title}). It shares the GPU with chat, so answers may be slow until it finishes.` }) : null);
}

function renderChat() {
  const view = $view();
  const C = S.chat;
  if (!S.status) { view.replaceChildren(h("p", { class: "muted", text: "Loading…" })); return; }
  if (!C.scope) C.scope = new Set(projects().map((p) => p.name));
  const scopeBox = h("div", null, projects().map((p) => h("label", { class: "row" },
    h("input", { type: "checkbox", checked: C.scope.has(p.name) || undefined, onchange: (e) => { e.target.checked ? C.scope.add(p.name) : C.scope.delete(p.name); saveChat(); chatBanner(); } }),
    p.name)));
  const kind = h("select", null, [["quiz", "Practice quiz"], ["flashcards", "Flashcards"], ["guide", "Study guide"]].map(([v, t]) => h("option", { value: v, text: t })));
  const num = h("input", { type: "number", min: 1, max: 50, placeholder: "How many (optional)", style: "width:100%" });
  const topic = h("input", { type: "text", placeholder: "Topic (optional, e.g. factor price equalization)", style: "width:100%" });
  const input = h("textarea", { rows: 2, placeholder: "Ask about your notes…  (Enter to send, Shift+Enter for a new line)" });
  const send = () => {
    const text = input.value.trim();
    if (!text || C.busy) return;
    input.value = "";
    ask({ message: text });
  };
  input.addEventListener("keydown", (e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); } });
  view.replaceChildren(h("div", { class: "chat-layout" },
    h("div", { class: "side" },
      h("div", { class: "card" }, h("h2", { text: "Classes" }), scopeBox,
        h("div", { class: "field", style: "margin-top:.6rem" }, h("strong", { class: "small", text: "Answers" }),
          h("select", { onchange: (e) => { C.mode = e.target.value; saveChat(); } },
            h("option", { value: "strict", selected: C.mode === "strict" || undefined, text: "Only from my notes" }),
            h("option", { value: "open", selected: C.mode === "open" || undefined, text: "Notes + labelled outside knowledge" })))),
      h("div", { class: "card" }, h("h2", { text: "Study tools" }),
        h("div", { class: "field" }, kind, num, topic),
        h("button", { class: "btn primary", onclick: () => {
          const t = topic.value.trim();
          const label = { quiz: "Practice quiz", flashcards: "Flashcards", guide: "Study guide" }[kind.value] + (t ? `: ${t}` : "");
          ask({ message: label, display: label, task: { kind: kind.value, n: num.value ? Number(num.value) : null, topic: t } });
        }, text: "Generate" })),
      h("button", { class: "btn", onclick: () => { if (C.busy && C.controller) C.controller.abort(); C.messages = []; saveChat(); renderChatMessages(); }, text: "New chat" })),
    h("div", { class: "chat-main" },
      h("div", { id: "chat-banner" }),
      h("div", { class: "messages", id: "messages" }),
      h("div", { class: "composer" }, input,
        h("button", { class: "btn primary", id: "send", onclick: send, text: "Send" }),
        h("button", { class: "btn danger", id: "stop", style: "display:none", onclick: () => C.controller && C.controller.abort(), text: "Stop" })))));
  renderChatMessages(); chatBanner(); updateComposer();
}

// ---------------------------------------------------------------- settings tab
async function renderSettings() {
  const view = $view();
  view.replaceChildren(h("p", { class: "muted", text: "Loading…" }));
  let d;
  try { d = await api("/api/settings"); } catch (e) { view.replaceChildren(h("p", { class: "banner bad", text: e.message })); return; }
  const s = d.settings;
  const names = d.ollama_models.map((m) => m.name);
  const modelField = (stage, note) => {
    const cur = s.models[stage];
    // Ollama lists "nomic-embed-text" as "nomic-embed-text:latest". Keep saving the name the
    // config already uses -- changing it would change the index hash and force a full re-embed.
    const inst = names.find((n) => n === cur || n === `${cur}:latest`);
    const opts = inst ? names : [cur, ...names];
    const el = d.ollama_error ? h("input", { type: "text", value: cur }) : h("select", null, opts.map((n) => {
      const m = d.ollama_models.find((x) => x.name === n);
      return h("option", { value: n === inst ? cur : n, selected: (n === inst || (!inst && n === cur)) || undefined,
        text: m ? `${n}  (${m.params || "?"}, ${m.size_gb} GB)` : `${n}  (not installed)` });
    }));
    return [h("label", null, h("strong", { text: note.label }), h("div", { class: "muted small", text: note.help })), el];
  };
  const ext = modelField("extract", { label: "Summary cards & overviews", help: "Reads every note once (slow, runs when you press a button). Bake-off: qwen3.6:27b most accurate; gpt-oss:20b ~5× faster." });
  const cht = modelField("chat", { label: "Chat", help: "Answers your questions and writes quizzes." });
  const emb = modelField("embed", { label: "Search embeddings", help: "Changing this makes every note need re-indexing." });
  const wm = h("select", null, d.whisper_models.map((m) => h("option", { value: m, selected: m === s.whisper_model || undefined, text: m })));
  const lang = h("input", { type: "text", value: s.whisper_language, maxlength: 3, style: "width:5rem" });
  const auto = h("input", { type: "checkbox", checked: s.auto_sync || undefined });
  const interval = h("input", { type: "number", value: s.sync_interval_seconds, min: 30, style: "width:8rem" });
  const topk = h("input", { type: "number", value: s.retrieval_top_k, min: 1, max: 40, style: "width:6rem" });
  const maxc = h("input", { type: "number", value: s.max_extract_chars, min: 10000, style: "width:10rem" });
  const val = (el) => el.value;
  view.replaceChildren(h("div", { class: "card" }, h("h2", { text: "Settings" }),
    d.ollama_error ? h("div", { class: "banner bad", text: `Ollama isn't reachable (${d.ollama_error}) — type model names by hand.` }) : null,
    h("div", { class: "banner info", text: "Changing the study-card model marks existing cards \"out of date\" — nothing is rebuilt until you press Update in Pipeline." }),
    h("div", { class: "form-grid" }, ext, cht, emb,
      h("label", null, h("strong", { text: "Whisper model" }), h("div", { class: "muted small", text: "large-v3 is the most accurate; smaller ones are faster." })), wm,
      h("label", null, h("strong", { text: "Spoken language" }), h("div", { class: "muted small", text: "Forced, never auto-detected: auto-detect mislabelled English lectures as Welsh." })), lang,
      h("label", null, h("strong", { text: "Auto-sync from notes app" }), h("div", { class: "muted small", text: "Read-only check for new/edited/deleted notes. Never runs anything expensive." })), h("div", null, auto, " every ", interval, " seconds"),
      h("label", null, h("strong", { text: "Passages per answer" })), topk,
      h("label", null, h("strong", { text: "Largest note to summarise" }), h("div", { class: "muted small", text: "Bigger documents (textbooks) are searchable but not summarised. Characters." })), maxc),
    h("div", { style: "margin-top:1rem" }, h("button", { class: "btn primary", onclick: async () => {
      try {
        await api("/api/settings", { method: "PUT", body: {
          models: { extract: val(ext[1]), chat: val(cht[1]), embed: val(emb[1]) },
          whisper_model: wm.value, whisper_language: lang.value.trim().toLowerCase(), auto_sync: auto.checked,
          sync_interval_seconds: Number(interval.value), retrieval_top_k: Number(topk.value), max_extract_chars: Number(maxc.value),
        } });
        toast("Saved"); await refresh();
      } catch (e) { toast(e.message); }
    }, text: "Save settings" }))));
}

// ---------------------------------------------------------------- router
const TABS = {
  chat: { label: "Chat", render: renderChat, onStatus: () => { chatBanner(); } },
  library: { label: "Library", render: renderLibrary },
  pipeline: { label: "Pipeline", render: renderPipeline, onStatus: renderPipeline },
  settings: { label: "Settings", render: renderSettings },
};
function setTab(name) {
  if (!TABS[name]) name = "pipeline";
  S.tab = name;
  document.getElementById("tabs").replaceChildren(...Object.entries(TABS).map(([k, t]) =>
    h("button", { class: `tab${k === name ? " active" : ""}`, onclick: () => { location.hash = k; }, text: t.label })));
  TABS[name].render();
}
window.addEventListener("hashchange", () => setTab(location.hash.slice(1)));

(async function init() {
  refreshHealth();
  await refresh();
  const wanted = location.hash.slice(1);
  const anyBuilt = projects().some((p) => p.notes.some((n) => n.card === "current"));
  setTab(TABS[wanted] ? wanted : anyBuilt ? "chat" : "pipeline");
})();
