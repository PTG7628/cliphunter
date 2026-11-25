/* ClipHunter Studio: core, shared components, Home / Projects / Project / Live / Create. Vanilla JS, no build step. */
"use strict";
const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const hms = (t) => { t = Math.max(0, Math.floor(t || 0)); const h = Math.floor(t / 3600), m = Math.floor((t % 3600) / 60), s = t % 60; return (h ? h + ":" + String(m).padStart(2, "0") : m) + ":" + String(s).padStart(2, "0"); };
const fmtN = (n) => n == null ? "–" : n >= 1e6 ? (n / 1e6).toFixed(1) + "M" : n >= 1e3 ? (n / 1e3).toFixed(1) + "k" : String(Math.round(n));
const ago = (ts) => { if (!ts) return ""; const d = Date.now() / 1000 - ts; return d < 60 ? "just now" : d < 3600 ? Math.floor(d / 60) + " min ago" : d < 86400 ? Math.floor(d / 3600) + " h ago" : Math.floor(d / 86400) + " d ago"; };

async function api(url, opts = {}) {
  const o = { ...opts, headers: { ...(opts.body && !(opts.body instanceof FormData) ? { "Content-Type": "application/json" } : {}) } };
  if (opts.body && !(opts.body instanceof FormData)) o.body = JSON.stringify(opts.body);
  const r = await fetch(url, o);
  const data = await r.json().catch(() => ({}));
  if (!r.ok && data && data.ok === undefined) data.ok = false;
  return data;
}

/* ---------- icons (stroke icons, 24px grid) ---------- */
const ICONS = {
  home: '<path d="M3 11l9-7 9 7"/><path d="M5 10v10h14V10"/><path d="M10 20v-6h4v6"/>',
  plus: '<path d="M12 5v14M5 12h14"/>',
  folder: '<path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>',
  sparkles: '<path d="M12 3l1.8 4.6L18 9.5l-4.2 1.9L12 16l-1.8-4.6L6 9.5l4.2-1.9z"/><path d="M19 15l.8 2 2 .8-2 .8-.8 2-.8-2-2-.8 2-.8z"/>',
  scissors: '<circle cx="6" cy="6" r="3"/><circle cx="6" cy="18" r="3"/><path d="M8.1 8.1L20 20M8.1 15.9L20 4"/>',
  radio: '<circle cx="12" cy="12" r="2"/><path d="M16.2 7.8a6 6 0 0 1 0 8.4M7.8 16.2a6 6 0 0 1 0-8.4M19 5a10 10 0 0 1 0 14M5 19A10 10 0 0 1 5 5"/>',
  chart: '<path d="M4 20V10M10 20V4M16 20v-7M22 20H2"/>',
  settings: '<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z"/>',
  upload: '<path d="M12 16V4M7 9l5-5 5 5"/><path d="M4 16v3a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-3"/>',
  link: '<path d="M10 14a4 4 0 0 0 5.7 0l3-3a4 4 0 0 0-5.7-5.7l-1 1"/><path d="M14 10a4 4 0 0 0-5.7 0l-3 3a4 4 0 0 0 5.7 5.7l1-1"/>',
  play: '<path d="M7 4l13 8-13 8z" fill="currentColor"/>',
  pause: '<path d="M7 4h4v16H7zM13 4h4v16h-4z" fill="currentColor"/>',
  check: '<path d="M5 12l5 5L20 7"/>', x: '<path d="M6 6l12 12M18 6L6 18"/>',
  eye: '<path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12z"/><circle cx="12" cy="12" r="3"/>',
  download: '<path d="M12 4v12M7 11l5 5 5-5"/><path d="M4 20h16"/>',
  wand: '<path d="M15 4V2M15 10V8M11 6h2M17 6h2M4 20l11-11"/><path d="M19 13l.7 1.3L21 15l-1.3.7L19 17l-.7-1.3L17 15l1.3-.7z"/>',
  film: '<rect x="3" y="3" width="18" height="18" rx="2"/><path d="M7 3v18M17 3v18M3 8h4M3 16h4M17 8h4M17 16h4"/>',
  alert: '<path d="M12 3l10 18H2z"/><path d="M12 10v5M12 18h.01"/>', info: '<circle cx="12" cy="12" r="9"/><path d="M12 11v6M12 7.5h.01"/>',
  trash: '<path d="M4 7h16M10 11v6M14 11v6M6 7l1 13h10l1-13M9 7V4h6v3"/>', refresh: '<path d="M20 11a8 8 0 1 0-2.3 5.7M20 4v7h-7"/>',
  stop: '<rect x="6" y="6" width="12" height="12" rx="2" fill="currentColor"/>', camera: '<rect x="3" y="6" width="13" height="12" rx="2"/><path d="M16 10l5-3v10l-5-3"/>',
  keyboard: '<rect x="2" y="6" width="20" height="12" rx="2"/><path d="M6 10h.01M10 10h.01M14 10h.01M18 10h.01M7 14h10"/>',
  copy: '<rect x="9" y="9" width="11" height="11" rx="2"/><path d="M5 15V5a1 1 0 0 1 1-1h10"/>', save: '<path d="M5 3h11l3 3v15H5z"/><path d="M8 3v5h7M8 21v-7h8v7"/>',
  external: '<path d="M14 4h6v6M20 4l-9 9"/><path d="M19 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V6a1 1 0 0 1 1-1h5"/>',
  left: '<path d="M15 6l-6 6 6 6"/>', right: '<path d="M9 6l6 6-6 6"/>', clock: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
};
function icon(name, extra = "") {
  return `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" ${extra}>${ICONS[name] || ""}</svg>`;
}
function hydrateIcons(root = document) { $$("[data-icon]", root).forEach((el) => { el.outerHTML = icon(el.dataset.icon); }); }

/* ---------- toasts & modals ---------- */
function toast(msg, kind = "") {
  const t = document.createElement("div");
  t.className = "toast " + kind; t.textContent = msg;
  $("#toasts").appendChild(t);
  setTimeout(() => { t.style.opacity = "0"; t.style.transition = "opacity .3s"; setTimeout(() => t.remove(), 300); }, 3200);
}
function openModal(html, { wide = false, onClose } = {}) {
  closeModal();
  const wrap = document.createElement("div");
  wrap.className = "modal-wrap"; wrap.innerHTML = `<div class="modal ${wide ? "wide" : ""}" role="dialog" aria-modal="true">${html}</div>`;
  wrap.addEventListener("mousedown", (e) => { if (e.target === wrap) closeModal(); });
  $("#modalRoot").appendChild(wrap);
  wrap._onClose = onClose;
  const first = $("input, select, textarea, button", wrap); if (first) first.focus();
  return wrap;
}
function closeModal() { const w = $("#modalRoot .modal-wrap"); if (w) { if (w._onClose) w._onClose(); w.remove(); } }

/* ---------- shared components ---------- */
function qring(q, size = 44, cls = "") {
  const r = size / 2 - 4, c = 2 * Math.PI * r, v = Math.max(0, Math.min(100, q || 0));
  const color = v >= 85 ? "url(#gHot)" : v >= 70 ? "#FBBF24" : "#6B7189";
  return `<div class="qring ${cls}" style="width:${size}px;height:${size}px" title="Quality ${v}/100">
    <svg width="${size}" height="${size}"><defs><linearGradient id="gHot" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#FF3D81"/><stop offset="1" stop-color="#8B5CF6"/></linearGradient></defs>
    <circle class="track" cx="${size / 2}" cy="${size / 2}" r="${r}"/>
    <circle class="val" cx="${size / 2}" cy="${size / 2}" r="${r}" stroke="${color}" stroke-dasharray="${c}" stroke-dashoffset="${c}" data-off="${c * (1 - v / 100)}"/></svg><b>${v}</b></div>`;
}
function animateRings(root = document) { requestAnimationFrame(() => $$(".qring .val", root).forEach((el) => { el.style.strokeDashoffset = el.dataset.off; })); }

const STATUS_LABEL = { ready: "Top pick", review: "Review", approved: "Approved", rejected: "Rejected" };
function statusChip(status) {
  const cls = { ready: "top", review: "review", approved: "approved", rejected: "rejected" }[status] || "";
  return `<span class="chip ${cls}">${status === "ready" ? icon("sparkles") : ""}${STATUS_LABEL[status] || esc(status)}</span>`;
}

const STEPS = [["downloading", "Download"], ["scanning", "Scan"], ["finding", "Find moments"], ["transcribing", "Transcribe"],
  ["analyzing", "AI analysis"], ["reviewing", "AI review"], ["rendering", "Render"], ["done", "Done"]];
function stepper(p) {
  if (p.stage === "recording") return `<div class="stepper"><span class="chip live"><span class="dot live"></span>Recording live${p.detail ? " · " + esc(p.detail) : ""}</span></div>`;
  const idx = STEPS.findIndex(([k]) => k === p.stage);
  const isFile = p.source && p.source.kind === "file";
  return `<div class="stepper">${STEPS.map(([k, label], i) => {
    let cls = "";
    if (p.stage === "done" || (idx >= 0 && i < idx) || (isFile && k === "downloading" && idx > 0)) cls = "done";
    else if (i === idx) cls = p.status === "error" ? "err" : "on";
    const mark = cls === "done" ? "✓" : cls === "err" ? "!" : "";
    return `<span class="step ${cls}"><i>${mark}</i>${label}</span>`;
  }).join("")}</div>`;
}
function projStatus(p) {
  const map = { queued: ["", "Queued"], downloading: ["cyan", "Downloading"], processing: ["cyan", "Processing"], recording: ["live", "Live"],
    done: ["approved", "Done"], error: ["rejected", "Failed"], cancelled: ["", "Cancelled"], interrupted: ["review", "Interrupted"] };
  const [cls, label] = map[p.status] || ["", p.status];
  return `<span class="chip ${cls}">${label}</span>`;
}
const ACTIVE = (p) => ["queued", "downloading", "processing", "recording"].includes(p.status);

function projRow(p) {
  const c = p.counts || {};
  const kept = (c.ready || 0) + (c.review || 0) + (c.approved || 0);
  const cover = p.cover ? `style="background-image:url('/media/poster/${p.cover}')"` : "";
  const prog = ACTIVE(p) && p.progress != null ? `<div class="proj-progress"><div class="bar"><i style="width:${Math.round(p.progress * 100)}%"></i></div><span class="tnum">${Math.round(p.progress * 100)}%</span></div>` : "";
  const detail = ACTIVE(p) && p.detail ? `<div class="faint" style="font-size:12px;margin-top:4px">${esc(p.detail)}</div>` : "";
  const err = p.status === "error" ? `<div class="callout bad" style="margin-top:8px">${icon("alert")}<div>${esc(p.error || "Failed")}</div></div>` : "";
  return `<div class="proj" data-id="${p.id}">
    <a class="cover" href="#/project/${p.id}" ${cover} aria-label="Open project">${p.cover ? "" : icon("film")}</a>
    <div style="min-width:0">
      <div class="row" style="gap:8px"><h3 class="ellipsis"><a href="#/project/${p.id}" style="color:inherit">${esc(p.title || p.name)}</a></h3>${projStatus(p)}</div>
      <div class="meta">${p.profile_name ? `<span class="chip cat">${esc(p.profile_name)}</span>` : ""}
        ${p.duration ? `<span>${icon("clock", 'style="width:13px;height:13px;vertical-align:-2px"')} ${hms(p.duration)}</span>` : ""}
        <span>${p.candidates || 0} moment${p.candidates === 1 ? "" : "s"} checked</span>
        ${c.ready ? `<span class="chip top">${c.ready} top</span>` : ""}${c.review ? `<span class="chip review">${c.review} review</span>` : ""}
        ${c.approved ? `<span class="chip approved">${c.approved} approved</span>` : ""}
        <span class="faint">${ago(p.started_at)}</span></div>
      ${ACTIVE(p) || p.status === "error" ? stepper(p) : ""}${prog}${detail}${err}
      ${!ACTIVE(p) && p.summary ? `<div class="summary">${esc(p.summary)}</div>` : ""}
    </div>
    <div class="row">
      ${ACTIVE(p) ? `<button class="btn sm bad" data-act="cancel" data-id="${p.id}">${icon("stop")}Cancel</button>` : ""}
      ${["error", "cancelled", "interrupted"].includes(p.status) ? `<button class="btn sm" data-act="retry" data-id="${p.id}">${icon("refresh")}Retry</button>` : ""}
      ${kept ? `<a class="btn sm" href="#/highlights?project=${p.id}">${icon("sparkles")}${kept} clip${kept > 1 ? "s" : ""}</a>` : ""}
      <a class="btn sm ghost" href="#/project/${p.id}">Details ${icon("right")}</a>
    </div></div>`;
}
function wireProjActions(root, reload) {
  root.addEventListener("click", async (e) => {
    const b = e.target.closest("[data-act]"); if (!b) return;
    const id = b.dataset.id, act = b.dataset.act;
    if (act === "cancel" && !confirm("Cancel this project?")) return;
    if (act === "delete" && !confirm("Delete this project and all its clips?")) return;
    await api(`/api/projects/${id}${act === "delete" ? "" : "/" + act}`, { method: act === "delete" ? "DELETE" : "POST" });
    toast(act === "retry" ? "Queued again" : act === "cancel" ? "Cancelling…" : "Deleted");
    reload && reload();
  });
}

function clipCard(c) {
  const poster = c.poster ? `style="background-image:url('/media/poster/${c.id}?v=${Math.floor(c.updated_at || 0)}')"` : "";
  const badge = c.status === "ready" ? `<span class="chip top badge">${icon("sparkles")}Top pick</span>` : `<span class="badge">${statusChip(c.status)}</span>`;
  const why = c.status === "rejected" ? (c.reject_reason || c.reason) : c.summary;
  return `<article class="hcard ${c.status === "ready" ? "top" : ""}" data-id="${c.id}">
    <div class="media" ${poster} data-preview="${c.id}" tabindex="0" role="button" aria-label="Preview clip">
      <div class="shade"></div>${badge}<div class="ring">${qring(c.quality, 46, "glass")}</div>
      ${c.hook ? `<div class="hookline">${esc(c.hook)}</div>` : ""}<span class="dur">${(c.duration || 0).toFixed(0)}s</span>
      ${c.rendering ? `<div class="overlay-state" style="position:absolute;inset:0;display:grid;place-items:center;background:rgba(5,5,10,.6)"><div class="spinner"></div></div>` : ""}
    </div>
    <div class="body">
      <div class="row wrap" style="gap:6px">${c.category ? `<span class="chip cat">${esc(c.category)}</span>` : ""}<span class="faint" style="font-size:12px">${esc(c.source_name || "")}</span></div>
      <h3>${esc(c.title || c.hook || "Untitled moment")}</h3>
      <div class="why">${esc(why || "")}</div>
      <div class="actions">
        ${c.status !== "rejected" ? `<a class="btn sm primary" href="#/editor/${c.id}">${icon("scissors")}Edit</a>` : `<a class="btn sm" href="#/project/${c.recording_id}">Why rejected</a>`}
        ${["ready", "review"].includes(c.status) ? `<button class="btn sm icon good" data-act="approve" data-id="${c.id}" title="Approve & export" aria-label="Approve">${icon("check")}</button>
        <button class="btn sm icon bad" data-act="reject" data-id="${c.id}" title="Reject" aria-label="Reject">${icon("x")}</button>` : ""}
        ${c.status === "approved" ? `<a class="btn sm icon" href="/download/${c.id}" title="Download" aria-label="Download">${icon("download")}</a>` : ""}
      </div></div></article>`;
}
function wireCards(root, reload) {
  root.addEventListener("mouseover", (e) => {
    const m = e.target.closest(".media[data-preview]"); if (!m || m.querySelector("video") || m.closest(".hcard").querySelector(".overlay-state")) return;
    const st = (m.closest(".hcard").querySelector(".chip.rejected")); if (st) return;
    const v = document.createElement("video");
    v.src = `/media/${m.dataset.preview}`; v.muted = true; v.loop = true; v.playsInline = true;
    v.addEventListener("playing", () => m.classList.add("playing"));
    m.appendChild(v); v.play().catch(() => {});
    m.addEventListener("mouseleave", () => { v.remove(); m.classList.remove("playing"); }, { once: true });
  });
  root.addEventListener("click", async (e) => {
    const p = e.target.closest(".media[data-preview]");
    if (p && !e.target.closest("[data-act]")) return previewModal(p.dataset.preview);
    const b = e.target.closest("[data-act]"); if (!b) return;
    if (b.dataset.act === "reject" && !confirm("Reject this clip? Its video will be deleted.")) return;
    const r = await api(`/api/clips/${b.dataset.id}/${b.dataset.act}`, { method: "POST", body: {} });
    if (r.ok === false) return toast(r.error || "Failed", "bad");
    toast(b.dataset.act === "approve" ? "Approved: copied to your APPROVED_CLIPS folder" : "Rejected", b.dataset.act === "approve" ? "good" : "");
    reload && reload();
  });
  root.addEventListener("keydown", (e) => { const p = e.target.closest(".media[data-preview]"); if (p && e.key === "Enter") previewModal(p.dataset.preview); });
}
function previewModal(id) {
  openModal(`<div class="row" style="justify-content:space-between;margin-bottom:12px"><h2>Preview</h2><button class="btn icon ghost" onclick="closeModal()" aria-label="Close">${icon("x")}</button></div>
    <div style="display:grid;place-items:center;background:#05050a;border-radius:14px;overflow:hidden"><video src="/media/${id}" controls autoplay style="max-height:70vh;max-width:100%"></video></div>
    <div class="modal-foot"><a class="btn" href="/download/${id}">${icon("download")}Download</a><a class="btn primary" href="#/editor/${id}" onclick="closeModal()">${icon("scissors")}Open in editor</a></div>`);
}

/* ---------- create clips (upload / link) ---------- */
let PROFILES = [];
function profileOptions(sel = "auto") {
  return `<option value="auto" ${sel === "auto" ? "selected" : ""}>Auto-detect game</option>` +
    PROFILES.map((p) => `<option value="${p.id}" ${sel === p.id ? "selected" : ""}>${esc(p.name)}</option>`).join("");
}
function createPanel(id = "cp") {
  return `<div class="drop" id="${id}">
    <label class="drop-target" for="${id}-file">${icon("upload")}<b>Drop a gameplay video</b><span class="muted">or click to choose · MP4, MKV, MOV, WEBM</span></label>
    <input type="file" id="${id}-file" accept="video/*,.mkv,.ts,.flv" hidden>
    <div class="upload-progress" id="${id}-up"><div class="row"><span class="grow ellipsis muted" id="${id}-upname"></span><span class="tnum" id="${id}-uppct">0%</span></div><div class="bar" style="margin-top:6px"><i id="${id}-upbar" style="width:0"></i></div></div>
    <div class="or">or paste a link</div>
    <div class="row"><input id="${id}-url" placeholder="youtube.com/watch?v=…  ·  twitch.tv/videos/…  ·  youtube.com/@channel" aria-label="Video or channel link">
      <button class="btn primary" id="${id}-go">${icon("sparkles")}Find highlights</button></div>
    <div class="row"><label class="f" style="margin:0;white-space:nowrap" for="${id}-profile">Game</label><select id="${id}-profile">${profileOptions()}</select></div>
  </div>`;
}
function uploadFile(file, profile, prefix) {
  const up = $(`#${prefix}-up`);
  if (up) { up.classList.add("on"); $(`#${prefix}-upname`).textContent = file.name; }
  const fd = new FormData(); fd.append("file", file); fd.append("profile", profile || "auto");
  const xhr = new XMLHttpRequest();
  xhr.open("POST", "/api/upload");
  xhr.upload.onprogress = (e) => { if (e.lengthComputable && up) { const p = Math.round((e.loaded / e.total) * 100); $(`#${prefix}-uppct`).textContent = p + "%"; $(`#${prefix}-upbar`).style.width = p + "%"; } };
  xhr.onload = () => {
    const r = JSON.parse(xhr.responseText || "{}");
    if (r.ok) { toast("Uploaded. Analysing now…", "good"); closeModal(); location.hash = r.recording_id ? `#/project/${r.recording_id}` : "#/projects"; }
    else toast(r.error || "Upload failed", "bad");
    if (up) up.classList.remove("on");
  };
  xhr.onerror = () => toast("Upload failed", "bad");
  xhr.send(fd);
}
function wireCreate(prefix) {
  const box = $(`#${prefix}`); if (!box) return;
  const prof = () => $(`#${prefix}-profile`).value;
  $(`#${prefix}-file`).addEventListener("change", (e) => e.target.files[0] && uploadFile(e.target.files[0], prof(), prefix));
  ["dragover", "dragenter"].forEach((ev) => box.addEventListener(ev, (e) => { e.preventDefault(); e.stopPropagation(); box.classList.add("over"); }));
  box.addEventListener("dragleave", () => box.classList.remove("over"));
  box.addEventListener("drop", (e) => { e.preventDefault(); e.stopPropagation(); box.classList.remove("over"); $("#dragcover").classList.remove("on"); const f = e.dataTransfer.files[0]; if (f) uploadFile(f, prof(), prefix); });
  const go = async () => {
    const url = $(`#${prefix}-url`).value.trim(); if (!url) return $(`#${prefix}-url`).focus();
    $(`#${prefix}-go`).disabled = true;
    const r = await api("/api/sources", { method: "POST", body: { url, profile: prof() } });
    $(`#${prefix}-go`).disabled = false;
    if (!r.ok) return toast(r.error || "Couldn't add that", "bad");
    closeModal();
    if (r.kind === "channel") { toast("Channel added. Clips start when it goes live.", "good"); location.hash = "#/live"; }
    else { toast("Added. Downloading and analysing…", "good"); location.hash = `#/project/${r.recording_id}`; }
  };
  $(`#${prefix}-go`).addEventListener("click", go);
  $(`#${prefix}-url`).addEventListener("keydown", (e) => e.key === "Enter" && go());
}
function openCreate() {
  openModal(`<h2>Create clips</h2><p class="sub">Drop a video or paste a link. ClipHunter analyses the whole thing and only keeps moments that pass a strict review. Zero clips is a valid answer.</p>${createPanel("mc")}`);
  wireCreate("mc");
}

/* ---------- router ---------- */
const PAGES = {};
let pageTimers = [], pageKeys = null;
function every(fn, ms) { pageTimers.push(setInterval(fn, ms)); }
function topbar(title, crumb = "", actions = "") {
  $("#topbar").innerHTML = `<div><div class="crumb">${crumb}</div><h1>${title}</h1></div><div class="spacer"></div>${actions}
    <button class="btn icon ghost" id="kbdBtn" title="Keyboard shortcuts (?)" aria-label="Keyboard shortcuts">${icon("keyboard")}</button>`;
  $("#kbdBtn").onclick = showShortcuts;
}
function route() {
  pageTimers.forEach(clearInterval); pageTimers = []; pageKeys = null;
  const h = location.hash || "#/";
  const [path, qs] = h.slice(1).split("?");
  const params = new URLSearchParams(qs || "");
  const parts = path.split("/").filter(Boolean);
  const name = parts[0] || "home";
  $$("#nav a").forEach((a) => a.classList.toggle("on", a.dataset.route === (name === "project" ? "projects" : name)));
  const el = $("#page"); el.className = "page" + (name === "editor" ? " wide" : ""); el.innerHTML = "";
  (PAGES[name] || PAGES.home)(el, parts[1], params);
  window.scrollTo(0, 0);
}

/* ---------- global status ---------- */
let ST = null;
async function pollState() {
  const s = await api("/api/state").catch(() => null);
  if (!s || !s.counts) return;
  ST = s;
  const busy = s.job !== "idle";
  $("#jobDot").className = "dot " + (s.live.length ? "live" : busy ? "busy" : "ok");
  $("#jobText").textContent = busy ? s.job : s.live.length ? `Recording ${s.live.length} stream(s)` : s.queue ? `${s.queue} queued` : "Idle · ready";
  $("#aiDot").className = "dot " + (s.ai_on ? "ok" : "warn");
  $("#aiText").textContent = s.ai_on ? `AI judge on · ${s.usage.ai_calls} calls today` : "AI off: clips unverified";
  $("#visDot").className = "dot " + (s.vision.on ? "ok" : "warn");
  $("#visText").textContent = s.vision.on ? "Vision: sees frames" : "Vision: " + (s.ai_on ? "off" : "needs AI");
  $("#visText").title = s.vision.text;
  const set = (id, n) => { const e = $(id); e.textContent = n; e.classList.toggle("hidden", !n); };
  set("#navTop", s.counts.ready || 0); set("#navLive", s.live.length);
  document.dispatchEvent(new CustomEvent("state", { detail: s }));
}

function showShortcuts() {
  const rows = [["N", "Create clips"], ["?", "Show shortcuts"], ["Esc", "Close dialogs"], ["Editor:", ""], ["Space", "Play / pause the selection"],
    ["I / O", "Set clip start / end at the playhead"], ["← / →", "Seek 1 s (Shift: 5 s)"], ["P", "Switch source / vertical preview"],
    ["J / K", "Previous / next clip"], ["R", "Render changes"], ["Ctrl + S", "Save without rendering"], ["A / X", "Approve / reject"]];
  openModal(`<h2>Keyboard shortcuts</h2><p class="sub">Shortcuts are ignored while you type in a field.</p><div class="shortcuts">${rows.map(([k, v]) => v ? `<span class="kbd">${k}</span><span>${v}</span>` : `<b style="grid-column:1/-1;margin-top:6px">${k}</b>`).join("")}</div>
    <div class="modal-foot"><button class="btn" onclick="closeModal()">Close</button></div>`);
}
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") return closeModal();
  const typing = e.target.closest("input, textarea, select, [contenteditable]");
  if (pageKeys && pageKeys(e, typing)) return;
  if (typing || e.ctrlKey || e.metaKey || e.altKey) return;
  if (e.key === "n" || e.key === "N") { e.preventDefault(); openCreate(); }
  if (e.key === "?") showShortcuts();
});
let dragDepth = 0;
window.addEventListener("dragenter", (e) => { if ([...(e.dataTransfer?.types || [])].includes("Files")) { dragDepth++; $("#dragcover").classList.add("on"); } });
window.addEventListener("dragleave", () => { dragDepth = Math.max(0, dragDepth - 1); if (!dragDepth) $("#dragcover").classList.remove("on"); });
window.addEventListener("dragover", (e) => e.preventDefault());
window.addEventListener("drop", (e) => {
  e.preventDefault(); dragDepth = 0; $("#dragcover").classList.remove("on");
  const f = e.dataTransfer?.files?.[0]; if (f) { openCreate(); uploadFile(f, "auto", "mc"); }
});

/* ---------- HOME ---------- */
PAGES.home = async (el) => {
  topbar("Home", "ClipHunter Studio", `<button class="btn" id="openApproved">${icon("folder")}Approved folder</button>`);
  $("#openApproved").onclick = async () => { const r = await api("/api/open-approved", { method: "POST" }); toast("Opened " + r.folder); };
  el.innerHTML = `<section class="hero">
      <div class="hero-copy"><div class="eyebrow">Quality-first AI clipper</div>
        <h2>Turn streams into <em>highlights worth posting.</em></h2>
        <p>Every moment is judged on gameplay, reaction, hook and payoff with a strict 100-point review, then checked by a second AI pass. Ordinary gameplay is thrown out, even if it's loud.</p>
        <div class="row wrap"><button class="btn primary lg" id="heroCreate">${icon("sparkles")}Create clips</button><a class="btn lg" href="#/live">${icon("radio")}Watch a live channel</a></div></div>
      ${createPanel("hp")}</section>
    <div class="stats" id="stats">${[0, 1, 2, 3, 4].map(() => '<div class="stat skel" style="height:86px"></div>').join("")}</div>
    <div id="homeActive"></div>
    <div class="section-head"><h2>Fresh top picks</h2><div class="spacer"></div><a class="btn sm ghost" href="#/highlights">All highlights ${icon("right")}</a></div>
    <div class="cards" id="homeClips">${[0, 1, 2, 3].map(() => '<div class="skel" style="height:420px;border-radius:16px"></div>').join("")}</div>
    <div class="section-head"><h2>Recent projects</h2><div class="spacer"></div><a class="btn sm ghost" href="#/projects">All projects ${icon("right")}</a></div>
    <div id="homeProjects"></div>`;
  $("#heroCreate").onclick = openCreate;
  $("#hp-profile").innerHTML = profileOptions();
  wireCreate("hp");
  wireCards($("#homeClips"), load); wireProjActions($("#homeActive"), load); wireProjActions($("#homeProjects"), load);
  const drawStats = (s) => {
    if (!s || !$("#stats")) return;
    const u = s.usage;
    $("#stats").innerHTML = `
      <div class="stat accent"><b>${s.counts.ready || 0}</b><span>Top picks ready</span><small>score ≥ ${s.thresholds.export}</small></div>
      <div class="stat"><b>${s.counts.review || 0}</b><span>Waiting for review</span><small>score ${s.thresholds.review}–${s.thresholds.export - 1}</small></div>
      <div class="stat"><b>${s.counts.approved || 0}</b><span>Approved & exported</span><small>in APPROVED_CLIPS</small></div>
      <div class="stat"><b>${s.avg_quality || "–"}</b><span>Average quality</span><small>of kept clips</small></div>
      <div class="stat"><b>${u.ai_calls}</b><span>AI checks today</span><small>${u.images} frames sent · ${u.ai_failures} failed</small></div>`;
  };
  const onState = (e) => drawStats(e.detail);
  document.addEventListener("state", onState);
  pageTimers.push(setTimeout(() => {}, 0));
  const off = () => document.removeEventListener("state", onState);
  window.addEventListener("hashchange", off, { once: true });
  drawStats(ST);
  async function load() {
    const [projects, clips] = await Promise.all([api("/api/projects"), api("/api/clips?status=top&sort=quality")]);
    if (!$("#homeClips")) return;
    const active = projects.filter(ACTIVE);
    $("#homeActive").innerHTML = active.length ? `<div class="section-head"><h2>Processing now</h2></div>${active.map(projRow).join("")}` : "";
    $("#homeClips").innerHTML = clips.length ? clips.slice(0, 4).map(clipCard).join("") :
      `<div class="card empty" style="grid-column:1/-1">${icon("sparkles")}<div class="big">No top picks yet</div>Top picks appear here when a moment scores ${ST ? ST.thresholds.export : 85}+ and passes the second review.</div>`;
    const recent = projects.filter((p) => !ACTIVE(p)).slice(0, 5);
    $("#homeProjects").innerHTML = recent.length ? recent.map(projRow).join("") : `<div class="card empty">${icon("folder")}<div class="big">No projects yet</div>Drop a video above to start.</div>`;
    animateRings($("#homeClips"));
  }
  await load();
  every(load, 4000);
};

/* ---------- PROJECTS ---------- */
PAGES.projects = async (el) => {
  topbar("Projects", "Every video and stream you've processed", `<button class="btn primary" id="pc">${icon("plus")}New project</button>`);
  $("#pc").onclick = openCreate;
  el.innerHTML = `<div id="plist">${[0, 1, 2].map(() => '<div class="skel" style="height:104px;margin-bottom:10px"></div>').join("")}</div>`;
  wireProjActions(el, load);
  async function load() {
    const rows = await api("/api/projects");
    if (!$("#plist")) return;
    $("#plist").innerHTML = rows.length ? rows.map(projRow).join("") : `<div class="card empty">${icon("folder")}<div class="big">No projects yet</div><p>Upload a video or paste a YouTube / Twitch link.</p><button class="btn primary" onclick="openCreate()">${icon("plus")}Create clips</button></div>`;
  }
  await load(); every(load, 3000);
};

/* ---------- PROJECT DETAIL ---------- */
PAGES.project = async (el, id) => {
  topbar("Project", `<a href="#/projects">Projects</a> / #${id}`);
  el.innerHTML = '<div class="skel" style="height:140px"></div>';
  let lastSig = "";
  async function load() {
    const p = await api(`/api/projects/${id}`);
    if (!p || !p.id) { el.innerHTML = `<div class="card empty"><div class="big">Project not found</div></div>`; return; }
    const sig = JSON.stringify([p.stage, p.progress, p.status, p.clips.length, p.clips.map((c) => c.status + c.quality), p.wave.length]);
    if (sig === lastSig) return; lastSig = sig;
    topbar(esc(p.title || p.name), `<a href="#/projects">Projects</a> / #${p.id}`,
      `${ACTIVE(p) ? `<button class="btn bad" data-act="cancel" data-id="${p.id}">${icon("stop")}Cancel</button>` : ""}
       ${["error", "cancelled", "interrupted"].includes(p.status) ? `<button class="btn" data-act="retry" data-id="${p.id}">${icon("refresh")}Retry</button>` : ""}
       <button class="btn ghost bad" data-act="delete" data-id="${p.id}">${icon("trash")}Delete</button>`);
    const kept = p.clips.filter((c) => ["ready", "review", "approved"].includes(c.status));
    const cam = p.cam && p.cam.box ? `Facecam ${p.cam.source === "manual" ? "set by you" : "auto-detected"}` : "No facecam detected";
    el.innerHTML = `
      <div class="card"><div class="row wrap" style="gap:8px">${projStatus(p)}${p.profile_name ? `<span class="chip cat">${esc(p.profile_name)}</span>` : ""}
          <span class="chip">${icon("clock")}${hms(p.duration)}</span><span class="chip">${p.candidates || 0} moment${p.candidates === 1 ? "" : "s"} checked</span><span class="chip">${icon("camera")}${cam}</span>
          ${p.proc_secs ? `<span class="chip">processed in ${hms(p.proc_secs)}</span>` : ""}</div>
        ${stepper(p)}
        ${ACTIVE(p) && p.progress != null ? `<div class="proj-progress"><div class="bar"><i style="width:${Math.round(p.progress * 100)}%"></i></div><span class="tnum">${Math.round(p.progress * 100)}%</span><span>${esc(p.detail || "")}</span></div>` : ACTIVE(p) ? `<div class="faint" style="margin-top:8px">${esc(p.detail || "")}</div>` : ""}
        ${p.status === "error" ? `<div class="callout bad" style="margin-top:12px">${icon("alert")}<div>${esc(p.error)}</div></div>` : ""}
        ${p.summary ? `<div class="callout ${kept.length ? "" : "warn"}" style="margin-top:12px">${icon("info")}<div>${esc(p.summary)}</div></div>` : ""}
      </div>
      <div class="section-head"><h2>Timeline</h2><span class="muted" style="font-size:12.5px">Loudness across the video. Markers are every moment the AI judged (pink = top pick, amber = review, grey = rejected).</span></div>
      <div class="wavebox" id="pwave"><canvas></canvas></div>
      ${kept.length ? `<div class="section-head"><h2>Kept clips</h2><div class="spacer"></div><a class="btn sm" href="#/editor/${kept[0].id}">${icon("scissors")}Open editor</a></div><div class="cards" id="pclips">${kept.map((c) => clipCard({ ...c, duration: c.clip_out - c.clip_in })).join("")}</div>` : ""}
      <div class="section-head"><h2>Every moment judged</h2><span class="muted" style="font-size:12.5px">Full transparency: what was flagged, how it scored, and why it was kept or thrown out.</span></div>
      <div class="card" style="padding:6px 10px">${p.clips.length ? `<table class="t"><thead><tr><th>Time</th><th>Flagged by</th><th>Category</th><th>Quality</th><th>Status</th><th>Why</th></tr></thead><tbody>
        ${p.clips.map((c) => `<tr class="${["ready", "review", "approved"].includes(c.status) ? "click" : ""}" data-open="${["ready", "review", "approved"].includes(c.status) ? c.id : ""}">
          <td class="mono">${hms(c.peak != null ? c.peak : c.start)}</td><td class="muted" style="max-width:220px">${esc((c.cues || []).map((q) => q.kind).filter((v, i, a) => a.indexOf(v) === i).join(", ") || c.nominated_by || "")}</td>
          <td>${c.category && c.category !== "none" ? `<span class="chip cat">${esc(c.category)}</span>` : '<span class="faint">–</span>'}</td>
          <td class="mono">${c.quality}<span class="faint">/100</span>${c.stage2 != null ? `<div class="faint" style="font-size:11px">1st ${c.stage1} · 2nd ${c.stage2}</div>` : ""}</td>
          <td>${statusChip(c.status)}</td><td class="muted" style="max-width:420px">${esc(c.status === "rejected" ? c.reject_reason : c.summary)}</td></tr>`).join("")}
        </tbody></table>` : `<div class="empty">${ACTIVE(p) ? '<div class="spinner" style="margin:0 auto 10px"></div>Analysing…' : "No moments stood out enough to judge."}</div>`}</div>`;
    hydrateIcons(el); animateRings(el);
    const pc = $("#pclips"); if (pc) wireCards(pc, load);
    $$("tr[data-open]", el).forEach((tr) => tr.dataset.open && tr.addEventListener("click", () => (location.hash = `#/editor/${tr.dataset.open}`)));
    drawProjectWave($("#pwave"), p);
  }
  wireProjActions($("#topbar"), () => { if (location.hash.startsWith("#/project/")) { lastSig = ""; load(); } });
  $("#topbar").addEventListener("click", (e) => { const b = e.target.closest('[data-act="delete"]'); if (b) setTimeout(() => (location.hash = "#/projects"), 300); });
  await load(); every(load, 3000);
};
function drawProjectWave(box, p) {
  if (!box || !$("canvas", box)) return;
  const cv = $("canvas", box), w = box.clientWidth, h = box.clientHeight, dpr = window.devicePixelRatio || 1;
  cv.width = w * dpr; cv.height = h * dpr;
  const ctx = cv.getContext("2d"); ctx.scale(dpr, dpr);
  const dur = p.duration || (p.wave.length ? p.wave[p.wave.length - 1][0] : 1) || 1;
  const grad = ctx.createLinearGradient(0, 0, w, 0); grad.addColorStop(0, "#8B5CF6"); grad.addColorStop(1, "#00E5FF");
  ctx.fillStyle = grad; ctx.globalAlpha = 0.75;
  for (const [t, db] of p.wave) {
    const v = Math.max(0.03, Math.min(1, (db + 60) / 60)), x = (t / dur) * w, bh = v * (h - 16);
    ctx.fillRect(x, (h - bh) / 2, Math.max(1, (2 / dur) * w - 0.5), bh);
  }
  if (!p.wave.length) { ctx.globalAlpha = 1; ctx.fillStyle = "#6B7189"; ctx.font = "13px sans-serif"; ctx.fillText(ACTIVE(p) ? "Scanning…" : "No waveform", 14, h / 2 + 4); }
  $$(".marker", box).forEach((m) => m.remove());
  for (const c of p.clips) {
    const t = c.peak != null ? c.peak : c.start;
    const m = document.createElement("div");
    m.className = "marker " + c.status; m.style.left = (t / dur) * 100 + "%"; m.dataset.q = c.quality;
    m.title = `${hms(t)} · ${c.quality}/100 · ${c.status}${c.reject_reason ? " · " + c.reject_reason : ""}`;
    if (["ready", "review", "approved"].includes(c.status)) m.onclick = () => (location.hash = `#/editor/${c.id}`);
    box.appendChild(m);
  }
}

/* ---------- LIVE ---------- */
PAGES.live = async (el) => {
  topbar("Live channels", "Record streams the moment they go live and clip during the stream");
  el.innerHTML = `<div class="card"><h2>Watch a channel</h2>
      <div class="row wrap"><input id="chUrl" class="grow" style="min-width:260px" placeholder="youtube.com/@DuckyBhai  ·  twitch.tv/streamer">
      <select id="chProf" style="width:220px">${profileOptions()}</select><button class="btn primary" id="chAdd">${icon("plus")}Watch</button></div>
      <p class="muted" style="margin:10px 0 0;font-size:13px">ClipHunter checks every channel every couple of minutes. When one goes live it records the stream and chat, and runs the full highlight review every few minutes while the stream is still going. Your PC has to stay on.</p></div>
    <div class="section-head"><h2>Channels</h2></div><div id="chList"></div>`;
  async function load() {
    const [rows, st] = [await api("/api/channels"), ST];
    if (!$("#chList")) return;
    const live = new Map((st?.live || []).map((l) => [l.source_id, l]));
    $("#chList").innerHTML = rows.length ? `<div class="card" style="padding:6px 10px"><table class="t"><thead><tr><th>Channel</th><th>Status</th><th>Game</th><th>Watching</th><th></th></tr></thead><tbody>${rows.map((c) => {
      const l = live.get(c.id);
      return `<tr><td><b>${esc(c.name)}</b><div class="faint mono">${esc(c.url)}</div></td>
        <td>${l ? `<span class="chip live"><span class="dot live"></span>Live · ${l.elapsed} · ${l.chat} chat msgs</span>${l.recording_id ? `<div style="margin-top:6px"><a href="#/project/${l.recording_id}">Open project</a></div>` : ""}` : `<span class="chip">${esc(c.status)}</span>`}</td>
        <td><select data-prof="${c.id}" style="width:190px;height:34px;padding:0 8px">${profileOptions(c.profile || "auto")}</select></td>
        <td><label class="toggle"><input type="checkbox" data-toggle="${c.id}" ${c.enabled ? "checked" : ""}> ${c.enabled ? "On" : "Off"}</label></td>
        <td style="text-align:right;white-space:nowrap">${l ? `<button class="btn sm bad" data-ch="stop" data-id="${c.id}">${icon("stop")}Stop</button>` : `<button class="btn sm" data-ch="check" data-id="${c.id}">${icon("refresh")}Check now</button>`}
          <button class="btn sm icon ghost bad" data-del="${c.id}" aria-label="Remove">${icon("trash")}</button></td></tr>`;
    }).join("")}</tbody></table></div>` : `<div class="card empty">${icon("radio")}<div class="big">No channels yet</div>Add a streamer above. Tip: big streamers often go live on a separate "live" channel.</div>`;
  }
  $("#chAdd").onclick = async () => {
    const url = $("#chUrl").value.trim(); if (!url) return;
    const r = await api("/api/sources", { method: "POST", body: { url, profile: $("#chProf").value } });
    if (!r.ok) return toast(r.error, "bad");
    if (r.kind !== "channel") { toast("That's a single video, so it was added as a project", "good"); location.hash = `#/project/${r.recording_id}`; return; }
    $("#chUrl").value = ""; toast("Watching channel", "good"); load();
  };
  el.addEventListener("click", async (e) => {
    const b = e.target.closest("[data-ch]"); const d = e.target.closest("[data-del]");
    if (b) { await api(`/api/channels/${b.dataset.id}/${b.dataset.ch}`, { method: "POST" }); toast(b.dataset.ch === "stop" ? "Stopping recording…" : "Checking…"); load(); }
    if (d && confirm("Stop watching this channel?")) { await api(`/api/channels/${d.dataset.del}`, { method: "DELETE" }); load(); }
  });
  el.addEventListener("change", async (e) => {
    if (e.target.dataset.toggle) { await api(`/api/channels/${e.target.dataset.toggle}/toggle`, { method: "POST" }); load(); }
    if (e.target.dataset.prof) { await api(`/api/channels/${e.target.dataset.prof}/profile`, { method: "POST", body: { profile: e.target.value } }); toast("Game profile saved"); }
  });
  await load(); every(load, 4000);
};

/* ---------- boot ---------- */
window.addEventListener("load", async () => {
  hydrateIcons();
  $("#createBtn").onclick = openCreate;
  PROFILES = await api("/api/profiles").catch(() => []);
  await pollState();
  setInterval(pollState, 2500);
  window.addEventListener("hashchange", route);
  route();
});
