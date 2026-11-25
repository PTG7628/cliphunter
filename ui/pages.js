/* ClipHunter Studio: Highlights, Editor, Results, Settings. */
"use strict";

/* ---------- HIGHLIGHTS ---------- */
PAGES.highlights = async (el, _id, params) => {
  const f = { status: params.get("status") || "top", sort: params.get("sort") || "quality", profile: params.get("profile") || "",
    category: params.get("category") || "", project: params.get("project") || "" };
  topbar("Highlights", "Find, review and export your best moments",
    `<button class="btn" id="openApproved">${icon("folder")}Approved folder</button>`);
  $("#openApproved").onclick = async () => { const r = await api("/api/open-approved", { method: "POST" }); toast("Opened " + r.folder); };
  const tabs = [["top", "Top picks"], ["review", "To review"], ["approved", "Approved"], ["rejected", "Rejected"], ["all", "All kept"]];
  el.innerHTML = `<div class="tabs" id="htabs" role="tablist">${tabs.map(([k, l]) => `<button role="tab" data-s="${k}" class="${f.status === k ? "on" : ""}">${l}<span class="n" data-n="${k}"></span></button>`).join("")}</div>
    <div class="toolbar">
      <label class="f" style="margin:0" for="hsort">Sort</label>
      <select id="hsort"><option value="quality">Overall quality</option><option value="significance">Gameplay significance</option>
        <option value="entertainment">Entertainment (hook + reaction + retention)</option><option value="duration">Shortest first</option>
        <option value="timeline">Timeline position</option><option value="newest">Newest</option></select>
      <select id="hprof" aria-label="Game"><option value="">All games</option>${PROFILES.map((p) => `<option value="${p.id}">${esc(p.name)}</option>`).join("")}</select>
      <select id="hcat" aria-label="Highlight type"><option value="">All highlight types</option></select>
      <select id="hproj" aria-label="Project"><option value="">All projects</option></select>
      <div class="spacer" style="flex:1"></div><span class="muted" id="hcount" style="font-size:12.5px"></span>
    </div>
    <div class="cards" id="hcards">${Array.from({ length: 8 }, () => '<div class="skel" style="height:420px;border-radius:16px"></div>').join("")}</div>`;
  $("#hsort").value = f.sort; $("#hprof").value = f.profile;
  const projects = await api("/api/projects");
  $("#hproj").innerHTML = '<option value="">All projects</option>' + projects.map((p) => `<option value="${p.id}">${esc((p.title || p.name).slice(0, 50))}</option>`).join("");
  $("#hproj").value = f.project;
  const cats = new Set(PROFILES.flatMap((p) => p.categories));
  $("#hcat").innerHTML += [...cats].sort().map((c) => `<option>${esc(c)}</option>`).join(""); $("#hcat").value = f.category;
  const sync = () => { const q = new URLSearchParams(Object.entries(f).filter(([, v]) => v)); history.replaceState(null, "", "#/highlights?" + q); };
  $("#htabs").onclick = (e) => { const b = e.target.closest("button"); if (!b) return; f.status = b.dataset.s; $$("#htabs button").forEach((x) => x.classList.toggle("on", x === b)); sync(); load(true); };
  [["#hsort", "sort"], ["#hprof", "profile"], ["#hcat", "category"], ["#hproj", "project"]].forEach(([s, k]) => $(s).addEventListener("change", (e) => { f[k] = e.target.value; sync(); load(true); }));
  wireCards($("#hcards"), () => load(true));
  let sig = "";
  async function load(force) {
    const q = new URLSearchParams({ status: f.status, sort: f.sort, ...(f.profile && { profile: f.profile }), ...(f.category && { category: f.category }), ...(f.project && { project: f.project }) });
    const rows = await api("/api/clips?" + q);
    if (!$("#hcards")) return;
    const s2 = JSON.stringify(rows.map((r) => [r.id, r.status, r.updated_at, r.rendering]));
    if (!force && s2 === sig) return; sig = s2;
    $("#hcount").textContent = `${rows.length} clip${rows.length === 1 ? "" : "s"}`;
    const empty = { top: ["No top picks yet", `Top picks are clips that score ${ST?.thresholds.export || 85}+ and survive the second review. Check "To review" for borderline ones.`],
      review: ["Nothing to review", "Clips scoring between the review and export thresholds land here."], approved: ["Nothing approved yet", "Approve a clip to export it to your APPROVED_CLIPS folder."],
      rejected: ["No rejected moments", "Rejected moments and the reason for each will show here."], all: ["No clips yet", "Create a project to get started."] }[f.status];
    $("#hcards").innerHTML = rows.length ? rows.map(clipCard).join("") : `<div class="card empty" style="grid-column:1/-1">${icon("sparkles")}<div class="big">${empty[0]}</div>${empty[1]}</div>`;
    animateRings($("#hcards"));
  }
  const counts = (s) => { if (!s) return; const c = s.counts; const n = { top: c.ready, review: c.review, approved: c.approved, rejected: c.rejected, all: (c.ready || 0) + (c.review || 0) + (c.approved || 0) };
    $$("[data-n]").forEach((x) => (x.textContent = n[x.dataset.n] || "")); };
  counts(ST); const onS = (e) => counts(e.detail); document.addEventListener("state", onS); window.addEventListener("hashchange", () => document.removeEventListener("state", onS), { once: true });
  await load(true); every(() => load(false), 4000);
};

/* ---------- EDITOR ---------- */
const LAYOUTS = [["auto", "Auto"], ["facecam", "Facecam split"], ["blur", "Blur fill"], ["crop", "Center crop"], ["action", "Follow action"]];
const ASPECTS = [["9:16", "9:16"], ["1:1", "1:1"], ["16:9", "16:9"]];
PAGES.editor = async (el, id) => {
  topbar("Editor", "Trim, caption, reframe and export");
  if (!id) {
    const rows = await api("/api/clips?status=all&sort=quality");
    if (rows.length) { location.replace(`#/editor/${rows[0].id}`); return; }
    el.innerHTML = `<div class="card empty">${icon("scissors")}<div class="big">Nothing to edit yet</div>Kept clips open here. <a href="#/highlights">Go to highlights</a></div>`; return;
  }
  el.innerHTML = '<div class="editor"><div class="skel" style="height:500px"></div><div class="skel" style="height:500px"></div><div class="skel" style="height:500px"></div></div>';
  const [clip, queue] = await Promise.all([api(`/api/clips/${id}`), api("/api/clips?status=all&sort=quality")]);
  if (!clip || !clip.id) { el.innerHTML = `<div class="card empty"><div class="big">Clip not found</div></div>`; return; }
  const E = {
    clip, mode: clip.has_path ? "vertical" : "source", dirty: false, tab: "score", hooks: [],
    d: { edit: { ...clip.edit_json }, words: (clip.words_json || []).map((w) => [...w]), title: clip.title || "", caption: clip.caption || "" },
  };
  const ctxLen = clip.ctx_len || 60;
  const b = (clip.analysis_json && (clip.analysis_json.bounds_final || clip.analysis_json.bounds)) || {};
  const idx = queue.findIndex((q) => q.id === clip.id);
  const neighbours = [queue[idx - 1], queue[idx + 1]];
  const canEdit = clip.has_raw_path;
  topbar(esc(clip.title || clip.hook || "Clip #" + clip.id), `<a href="#/highlights">Highlights</a> / <a href="#/project/${clip.recording_id}">${esc((clip.project.title || clip.project.name || "").slice(0, 40))}</a>`,
    `${statusChip(clip.status)}<span id="dirtyFlag" class="chip review hidden">Unsaved changes</span>
     <button class="btn" id="eSave" title="Save (Ctrl+S)" ${canEdit ? "" : "disabled"}>${icon("save")}Save</button>
     <button class="btn primary" id="eRender" title="Render (R)" ${canEdit ? "" : "disabled"}>${icon("wand")}Render</button>`);

  el.innerHTML = `<div class="editor">
    <aside class="queue" aria-label="Clips">${queue.map((q) => `<a class="qitem ${q.id === clip.id ? "on" : ""}" href="#/editor/${q.id}">
      <div class="th" style="${q.poster ? `background-image:url('/media/poster/${q.id}?v=${Math.floor(q.updated_at || 0)}')` : ""}"></div>
      <div style="min-width:0"><b class="ellipsis" style="display:block">${esc(q.hook || q.title || "Clip " + q.id)}</b><span>${q.quality}/100 · ${STATUS_LABEL[q.status] || q.status}</span></div></a>`).join("") || '<div class="muted">No other clips</div>'}</aside>
    <section class="stage">
      <div class="viewer" id="viewer"><video id="vid" playsinline controls preload="metadata"></video><div class="overlay-state hidden" id="vstate"></div></div>
      <div class="transport">
        <div class="seg" id="modeSeg"><button data-m="vertical">Vertical preview</button><button data-m="source">Source + trim</button></div>
        <button class="btn sm" id="playSel">${icon("play")}Play selection</button>
        <span class="timecode" id="tc">0:00</span><div class="grow"></div>
        <span class="muted" style="font-size:12.5px" id="selInfo"></span>
        ${neighbours[0] ? `<a class="btn sm icon" href="#/editor/${neighbours[0].id}" title="Previous (J)" aria-label="Previous clip">${icon("left")}</a>` : ""}
        ${neighbours[1] ? `<a class="btn sm icon" href="#/editor/${neighbours[1].id}" title="Next (K)" aria-label="Next clip">${icon("right")}</a>` : ""}
      </div>
      <div class="timeline" id="tl">
        <div class="tl-ruler" id="ruler"></div>
        <div class="tl-track" id="track">${clip.has_sprite ? `<img src="/media/sprite/${clip.id}" alt="" id="sprite" draggable="false">` : ""}</div>
        <div class="tl-wave"><canvas id="ewave"></canvas></div>
        <div class="tl-dim" id="dimL"></div><div class="tl-dim" id="dimR"></div><div class="tl-sel" id="sel"></div>
        <div class="tl-handle" id="hIn" role="slider" aria-label="Clip start" tabindex="0"></div><div class="tl-handle" id="hOut" role="slider" aria-label="Clip end" tabindex="0"></div>
        <div id="marks"></div><div class="tl-head" id="head"></div><div class="tl-hover hidden" id="hov"></div>
      </div>
      <div class="row wrap faint" style="font-size:12px;gap:14px"><span><span class="kbd">Space</span> play selection</span><span><span class="kbd">I</span>/<span class="kbd">O</span> set start/end</span><span><span class="kbd">R</span> render</span>
        <span>Red stripes = dead air removed in the last render.</span></div>
      ${canEdit ? "" : `<div class="callout warn">${icon("alert")}<div>The original footage for this clip was deleted, so it can't be re-edited.</div></div>`}
    </section>
    <aside class="card panel" id="panel"></aside></div>`;
  hydrateIcons(el);
  const vid = $("#vid");
  const T = { in: () => +E.d.edit.in, out: () => +E.d.edit.out };

  function setDirty(v = true) { E.dirty = v; $("#dirtyFlag").classList.toggle("hidden", !v); }
  function setMode(m) {
    E.mode = m;
    $$("#modeSeg button").forEach((x) => x.classList.toggle("on", x.dataset.m === m));
    const t = Date.now();
    if (m === "vertical") { vid.src = clip.has_path ? `/media/${clip.id}?v=${t}` : ""; }
    else { vid.src = canEdit ? `/media/raw/${clip.id}` : ""; vid.addEventListener("loadedmetadata", () => { vid.currentTime = T.in(); }, { once: true }); }
    showState();
  }
  function showState() {
    const s = $("#vstate");
    if (E.clip.rendering) { s.innerHTML = '<div><div class="spinner" style="margin:0 auto 10px"></div><b>Rendering…</b><div class="muted">Your vertical clip will appear here</div></div>'; s.classList.remove("hidden"); }
    else if (E.mode === "vertical" && !clip.has_path) { s.innerHTML = `<div><b>No render yet</b><div class="muted">Press Render to create the vertical clip</div></div>`; s.classList.remove("hidden"); }
    else s.classList.add("hidden");
  }
  $("#modeSeg").onclick = (e) => { const x = e.target.closest("button"); if (x) setMode(x.dataset.m); };

  // ---- timeline
  const track = $("#track");
  const tToPct = (t) => (Math.max(0, Math.min(ctxLen, t)) / ctxLen) * 100;
  function xToT(clientX) { const r = track.getBoundingClientRect(); return Math.max(0, Math.min(ctxLen, ((clientX - r.left) / r.width) * ctxLen)); }
  function drawTimeline() {
    const a = tToPct(T.in()), z = tToPct(T.out());
    $("#sel").style.left = a + "%"; $("#sel").style.width = z - a + "%";
    $("#dimL").style.left = "0"; $("#dimL").style.width = a + "%"; $("#dimR").style.left = z + "%"; $("#dimR").style.width = 100 - z + "%";
    $("#hIn").style.left = a + "%"; $("#hOut").style.left = z + "%";
    const len = T.out() - T.in();
    $("#selInfo").innerHTML = `Clip ${hms(T.in())} → ${hms(T.out())} · <b class="tnum" style="color:${len > 60 ? "#FCD34D" : "inherit"}">${len.toFixed(1)}s</b>${len > 60 ? " (over 60 s)" : ""}`;
    const marks = [["setup_start", "setup", ""], ["key_action", "action", "action"], ["reaction", "reaction", ""], ["payoff", "payoff", "payoff"]];
    const cuts = (E.d.edit.cuts || []).map(([x, y]) => `<div class="tl-cut" style="left:${tToPct(x)}%;width:${tToPct(y) - tToPct(x)}%" title="Dead air removed"></div>`).join("");
    $("#marks").innerHTML = cuts + marks.filter(([k]) => b[k] != null).map(([k, label, cls]) => `<div class="tl-mark ${cls}" style="left:${tToPct(b[k])}%"><span>${label}</span></div>`).join("");
  }
  function drawRuler() {
    const step = ctxLen > 120 ? 20 : ctxLen > 50 ? 10 : 5; let h = "";
    for (let t = 0; t <= ctxLen; t += step) h += `<span style="left:${tToPct(t)}%">${hms(t)}</span>`;
    $("#ruler").innerHTML = h;
  }
  function drawWave() {
    const cv = $("#ewave"); if (!cv) return window.removeEventListener("resize", drawWave);
    const w = cv.clientWidth, h = cv.clientHeight, dpr = window.devicePixelRatio || 1;
    cv.width = w * dpr; cv.height = h * dpr; const ctx = cv.getContext("2d"); ctx.scale(dpr, dpr);
    const wave = clip.wave_json || []; const step = 0.25;
    const g = ctx.createLinearGradient(0, 0, w, 0); g.addColorStop(0, "#8B5CF6"); g.addColorStop(1, "#00E5FF"); ctx.fillStyle = g;
    wave.forEach((v, i) => { const x = ((i * step) / ctxLen) * w, bh = Math.max(1, v * (h - 4)); ctx.fillRect(x, (h - bh) / 2, Math.max(1, (step / ctxLen) * w - 0.4), bh); });
  }
  const sp = $("#sprite"); if (sp) { const tiles = E.d.edit.sprite_tiles || 1, every_ = E.d.edit.sprite_every || 2; sp.style.width = ((tiles * every_) / ctxLen) * 100 + "%"; }
  drawRuler(); drawWave(); drawTimeline();
  window.addEventListener("resize", drawWave);
  vid.addEventListener("timeupdate", () => {
    if (E.mode === "source") {
      $("#head").style.left = tToPct(vid.currentTime) + "%"; $("#head").classList.remove("hidden");
      if (E.playSel && vid.currentTime >= T.out()) { vid.pause(); E.playSel = false; vid.currentTime = T.in(); }
    } else { $("#head").style.left = tToPct(T.in() + vid.currentTime) + "%"; }
    $("#tc").textContent = hms(E.mode === "source" ? vid.currentTime : vid.currentTime) + (E.mode === "source" ? " (source)" : "");
  });
  function playSelection() {
    if (E.mode !== "source") setMode("source");
    if (!vid.paused) { vid.pause(); E.playSel = false; return; }
    if (vid.currentTime < T.in() || vid.currentTime >= T.out() - 0.1) vid.currentTime = T.in();
    E.playSel = true; vid.play().catch(() => {});
  }
  $("#playSel").onclick = playSelection;
  track.addEventListener("click", (e) => { if (!canEdit) return; if (E.mode !== "source") setMode("source"); const t = xToT(e.clientX); setTimeout(() => (vid.currentTime = t), E.mode === "source" ? 0 : 300); });
  const tl = $("#tl");
  tl.addEventListener("mousemove", (e) => { const r = track.getBoundingClientRect(); if (e.clientX < r.left || e.clientX > r.right) return $("#hov").classList.add("hidden");
    const hv = $("#hov"); hv.textContent = hms(xToT(e.clientX)); hv.style.left = ((e.clientX - r.left) / r.width) * 100 + "%"; hv.classList.remove("hidden"); });
  tl.addEventListener("mouseleave", () => $("#hov").classList.add("hidden"));
  function dragHandle(h, key) {
    h.addEventListener("pointerdown", (e) => {
      if (!canEdit) return; e.preventDefault(); h.setPointerCapture(e.pointerId); h.classList.add("drag");
      const move = (ev) => { let t = Math.round(xToT(ev.clientX) * 10) / 10;
        if (key === "in") t = Math.min(t, T.out() - 3); else t = Math.max(t, T.in() + 3);
        E.d.edit[key] = t; setDirty(); drawTimeline(); if (E.mode === "source") vid.currentTime = t; };
      const up = () => { h.classList.remove("drag"); h.removeEventListener("pointermove", move); h.removeEventListener("pointerup", up); renderPanel(); };
      h.addEventListener("pointermove", move); h.addEventListener("pointerup", up);
    });
    h.addEventListener("keydown", (e) => { if (!["ArrowLeft", "ArrowRight"].includes(e.key)) return; e.preventDefault(); e.stopPropagation();
      const d = (e.key === "ArrowLeft" ? -1 : 1) * (e.shiftKey ? 1 : 0.1); const t = Math.round((T[key]() + d) * 10) / 10;
      if (key === "in" ? t < T.out() - 3 && t >= 0 : t > T.in() + 3 && t <= ctxLen) { E.d.edit[key] = t; setDirty(); drawTimeline(); } });
  }
  dragHandle($("#hIn"), "in"); dragHandle($("#hOut"), "out");

  // ---- side panel
  const PTABS = [["score", "Score"], ["text", "Text"], ["captions", "Captions"], ["layout", "Layout"], ["audio", "Audio"], ["export", "Export"]];
  function renderPanel() {
    const p = $("#panel"); const ed = E.d.edit;
    const tabs = `<div class="tabs" role="tablist">${PTABS.map(([k, l]) => `<button role="tab" data-t="${k}" class="${E.tab === k ? "on" : ""}">${l}</button>`).join("")}</div>`;
    let body = "";
    if (E.tab === "score") {
      const bd = clip.breakdown_json || {}; const sc = bd.scores || {}, rs = bd.review_scores || {}, js = bd.justification || {};
      const rv = clip.review_json || {};
      body = `<div class="row" style="gap:16px;margin-bottom:12px">${qring(clip.quality, 92, "lg")}<div><div style="font:800 18px var(--display)">${clip.quality}/100</div>
          <div class="row wrap" style="gap:6px;margin-top:6px">${statusChip(clip.status)}${clip.category && clip.category !== "none" ? `<span class="chip cat">${esc(clip.category)}</span>` : ""}</div>
          <div class="faint" style="font-size:12px;margin-top:6px">Evidence: ${esc(clip.evidence || "–")}</div></div></div>
        ${clip.summary ? `<div class="callout" style="margin-bottom:12px">${icon("info")}<div><b>What happens:</b> ${esc(clip.summary)}</div></div>` : ""}
        ${(clip.rubric.order || Object.keys(clip.rubric.max)).map((k) => { const mx = clip.rubric.max[k], v = sc[k] ?? 0, v2 = rs ? rs[k] : null;
          return `<div class="rubric-row"><div class="top"><span>${esc(clip.rubric.labels[k])}</span><b>${v}<span class="faint">/${mx}</span>${v2 != null ? `<span class="faint"> · 2nd ${v2}</span>` : ""}</b></div>
            <div class="bar"><i style="width:${(v / mx) * 100}%"></i></div>${js[k] ? `<p>${esc(js[k])}</p>` : ""}</div>`; }).join("")}
        ${clip.weaknesses ? `<div class="field" style="margin-top:12px"><label class="f">Weaknesses</label><div class="muted" style="font-size:13px">${esc(clip.weaknesses)}</div></div>` : ""}
        ${rv && rv.verdict ? `<div class="field"><label class="f">Second review: ${esc(rv.verdict)}${rv.verified ? " · verified" : " · NOT verified"}</label><div class="muted" style="font-size:13px">${esc([rv.evidence, rv.notes, ...(rv.issues || [])].filter(Boolean).join(" · "))}</div></div>` : ""}
        ${clip.learn_adj ? `<div class="chip cyan">Learning: ${esc(clip.reason)}</div>` : ""}
        ${clip.status === "rejected" ? `<div class="callout bad">${icon("x")}<div>Rejected: ${esc(clip.reject_reason)}</div></div>` : ""}
        <p class="faint" style="font-size:12px;margin-top:12px">Views/likes potential (AI guess, not a guarantee): ${clip.view_pct || 0}% / ${clip.like_pct || 0}%</p>`;
    } else if (E.tab === "text") {
      body = `<div class="field"><label class="f" for="fHook">On-screen hook</label><input id="fHook" value="${esc(ed.hook || "")}" maxlength="80">
          <div class="row" style="margin-top:8px"><button class="btn sm" id="moreHooks">${icon("wand")}5 more hooks</button><span class="muted" style="font-size:12px">Shown for</span>
          <input type="range" id="fHookSecs" min="1.5" max="6" step="0.5" value="${ed.hook_secs || 3.5}" style="width:110px"><output class="mono">${ed.hook_secs || 3.5}s</output></div>
          <div class="row wrap" style="gap:6px;margin-top:8px" id="hookChips">${E.hooks.map((h) => `<button class="btn xs" data-hook="${esc(h)}">${esc(h)}</button>`).join("")}</div></div>
        <div class="field"><label class="f" for="fTitle">Post title</label><input id="fTitle" value="${esc(E.d.title)}" maxlength="120"></div>
        <div class="field"><label class="f" for="fCap">Caption + hashtags</label><textarea id="fCap" rows="4">${esc(E.d.caption)}</textarea></div>
        <button class="btn sm" id="copyText">${icon("copy")}Copy title + caption</button>`;
    } else if (E.tab === "captions") {
      const inWords = E.d.words.map((w, i) => [w, i]).filter(([w]) => w[0] >= T.in() - 0.5 && w[0] <= T.out() + 0.5);
      body = `<label class="toggle field"><input type="checkbox" id="fCaps" ${ed.captions !== false ? "checked" : ""}> Burn in captions</label>
        <label class="f">Style</label><div class="styles field">${[["bold", "Bold", "BRO <em>NO</em> WAY"], ["clean", "Clean", "<span>bro <em>no</em> way</span>"], ["neon", "Neon", "BRO <em>NO</em> WAY"], ["minimal", "Minimal", "bro no way"]].map(([k, l, s]) =>
          `<button class="style-card s-${k} ${ed.caption_style === k ? "on" : ""}" data-style="${k}"><div class="sample">${s}</div><small>${l}</small></button>`).join("")}</div>
        <label class="f">Position</label><div class="seg field" id="capPos">${["auto", "top", "middle", "bottom"].map((k) => `<button data-pos="${k}" class="${(ed.caption_pos || "auto") === k ? "on" : ""}">${k[0].toUpperCase() + k.slice(1)}</button>`).join("")}</div>
        <small class="faint" style="display:block;margin:-6px 0 12px">Auto keeps captions off the gameplay (below the action, or under the facecam).</small>
        <label class="f">Transcript words (click to fix a word)</label>
        <div class="words" id="words">${inWords.length ? inWords.map(([w, i]) => `<input data-w="${i}" value="${esc(w[2])}" title="${hms(w[0])}">`).join("") : '<span class="muted">No speech transcribed in this clip.</span>'}</div>
        <small class="faint" style="display:block;margin-top:8px">Separate speakers aren't detected yet, so all words use one caption style.</small>`;
    } else if (E.tab === "layout") {
      const cam = ed.cam_box;
      body = `<label class="f">Aspect ratio</label><div class="seg field" id="aspSeg">${ASPECTS.map(([k, l]) => `<button data-asp="${k}" class="${ed.aspect === k ? "on" : ""}">${l}</button>`).join("")}</div>
        <label class="f">Layout${ed.aspect === "16:9" ? " (16:9 keeps the original frame)" : ""}</label>
        <div class="layouts field">${LAYOUTS.map(([k, l]) => `<button class="layout-card ${(ed.layout || "auto") === k ? "on" : ""}" data-layout="${k}" ${ed.aspect === "16:9" ? "disabled" : ""}><div class="pv pv-${k}"></div>${l}</button>`).join("")}</div>
        ${(ed.layout === "facecam" || ed.layout === "auto") && !cam ? `<div class="callout warn field">${icon("camera")}<div>No webcam area set, so Facecam/Auto uses the blur layout. Set it below.</div></div>` : ""}
        <div class="field"><label class="f">Webcam</label><div class="row"><span class="grow muted" style="font-size:13px">${cam ? `Area set (${cam.map((v) => Math.round(v * 100)).join(", ")}%)` : "Not set"}</span>
          <button class="btn sm" id="camBtn" ${canEdit ? "" : "disabled"}>${icon("camera")}${cam ? "Adjust" : "Set webcam area"}</button></div></div>
        <div class="field"><label class="f">Gameplay zoom (blur layout)</label><div class="range-row"><input type="range" id="fZoom" min="1" max="1.8" step="0.05" value="${ed.zoom || 1.35}"><output>${(+(ed.zoom || 1.35)).toFixed(2)}×</output></div></div>
        <div class="field"><label class="f">Action focus (follow-action / facecam crop)</label><div class="range-row"><input type="range" id="fFocus" min="0.15" max="0.85" step="0.01" value="${ed.focus_x || 0.5}"><output>${Math.round((ed.focus_x || 0.5) * 100)}%</output></div>
          <small>Auto-set from where things move on screen. 50% = center.</small></div>`;
    } else if (E.tab === "audio") {
      body = `<div class="field"><label class="f">Volume</label><div class="range-row"><input type="range" id="fGain" min="-12" max="12" step="1" value="${ed.gain_db || 0}"><output>${ed.gain_db > 0 ? "+" : ""}${ed.gain_db || 0} dB</output></div></div>
        <label class="toggle field"><input type="checkbox" id="fNorm" ${ed.normalize !== false ? "checked" : ""}> Normalize loudness for phones (-14 LUFS)</label>
        <label class="toggle field"><input type="checkbox" id="fDead" ${ed.dead_air ? "checked" : ""}> Cut dead air</label>
        <small class="faint">Removes quiet, wordless, still pauses between lines. Never touches the build-up before the key action, the payoff or the reaction. ${(ed.cuts || []).length ? `Last render removed ${ed.cuts.length} pause(s), ${ed.cuts.reduce((s, [a, z]) => s + z - a, 0).toFixed(1)} s total.` : ""}</small>`;
    } else if (E.tab === "export") {
      const presets = [["TikTok / Shorts / Reels", "9:16"], ["Square post", "1:1"], ["YouTube landscape", "16:9"]];
      body = `<label class="f">Export preset</label><div class="field" style="display:grid;gap:8px">${presets.map(([l, a]) => `<button class="btn ${ed.aspect === a ? "primary" : ""}" data-preset="${a}">${l} <span class="faint" style="margin-left:auto">${a}</span></button>`).join("")}</div>
        <label class="f">Quality</label><div class="seg field" id="qSeg">${["high", "balanced", "small"].map((k) => `<button data-q="${k}" class="${(ed.quality || "high") === k ? "on" : ""}">${k[0].toUpperCase() + k.slice(1)}</button>`).join("")}</div>
        <div style="display:grid;gap:8px;margin-top:6px">
          <button class="btn primary lg" id="xRender" ${canEdit ? "" : "disabled"}>${icon("wand")}${E.dirty ? "Render changes" : "Re-render"}</button>
          <button class="btn good lg" id="xApprove" ${clip.has_path ? "" : "disabled"}>${icon("check")}${clip.status === "approved" ? "Export again" : "Approve & export"}</button>
          ${clip.has_path ? `<a class="btn" href="/download/${clip.id}">${icon("download")}Download MP4</a>` : ""}
          ${clip.status !== "rejected" ? `<button class="btn bad" id="xReject">${icon("x")}Reject clip</button>` : ""}</div>
        <p class="faint" style="font-size:12px;margin-top:12px">Approving copies the MP4 and a .txt with title, caption and scores into your APPROVED_CLIPS folder. ${E.dirty ? "<b style='color:#FCD34D'>Render your changes before approving.</b>" : ""}</p>`;
    }
    p.innerHTML = tabs + body;
    animateRings(p);
    $$(".tabs button", p).forEach((x) => (x.onclick = () => { E.tab = x.dataset.t; renderPanel(); }));
    wirePanel(p);
  }
  function wirePanel(p) {
    const ed = E.d.edit;
    const on = (sel, ev, fn) => { const x = $(sel, p); if (x) x.addEventListener(ev, fn); };
    on("#fHook", "input", (e) => { ed.hook = e.target.value; setDirty(); });
    on("#fHookSecs", "input", (e) => { ed.hook_secs = +e.target.value; e.target.nextElementSibling.textContent = e.target.value + "s"; setDirty(); });
    on("#fTitle", "input", (e) => { E.d.title = e.target.value; setDirty(); });
    on("#fCap", "input", (e) => { E.d.caption = e.target.value; setDirty(); });
    on("#copyText", "click", () => { navigator.clipboard.writeText(`${E.d.title}\n\n${E.d.caption}`); toast("Copied"); });
    on("#moreHooks", "click", async (e) => { e.target.disabled = true; const r = await api(`/api/clips/${clip.id}/hooks`, { method: "POST" }); e.target.disabled = false;
      if (!r.ok) return toast(r.error || "Failed", "bad"); E.hooks = r.hooks; renderPanel(); });
    $$("[data-hook]", p).forEach((x) => (x.onclick = () => { ed.hook = x.dataset.hook; setDirty(); renderPanel(); toast("Hook set. Render to apply."); }));
    on("#fCaps", "change", (e) => { ed.captions = e.target.checked; setDirty(); });
    $$("[data-style]", p).forEach((x) => (x.onclick = () => { ed.caption_style = x.dataset.style; setDirty(); renderPanel(); }));
    $$("[data-pos]", p).forEach((x) => (x.onclick = () => { ed.caption_pos = x.dataset.pos; setDirty(); renderPanel(); }));
    $$("[data-w]", p).forEach((x) => x.addEventListener("input", () => { E.d.words[+x.dataset.w][2] = x.value; setDirty(); }));
    $$("[data-asp]", p).forEach((x) => (x.onclick = () => { ed.aspect = x.dataset.asp; setDirty(); renderPanel(); }));
    $$("[data-layout]", p).forEach((x) => (x.onclick = () => { ed.layout = x.dataset.layout; setDirty(); renderPanel(); if (x.dataset.layout === "facecam" && !ed.cam_box) camModal(); }));
    on("#fZoom", "input", (e) => { ed.zoom = +e.target.value; e.target.nextElementSibling.textContent = (+e.target.value).toFixed(2) + "×"; setDirty(); });
    on("#fFocus", "input", (e) => { ed.focus_x = +e.target.value; e.target.nextElementSibling.textContent = Math.round(e.target.value * 100) + "%"; setDirty(); });
    on("#camBtn", "click", camModal);
    on("#fGain", "input", (e) => { ed.gain_db = +e.target.value; e.target.nextElementSibling.textContent = (ed.gain_db > 0 ? "+" : "") + ed.gain_db + " dB"; setDirty(); });
    on("#fNorm", "change", (e) => { ed.normalize = e.target.checked; setDirty(); });
    on("#fDead", "change", (e) => { ed.dead_air = e.target.checked; setDirty(); });
    $$("[data-preset]", p).forEach((x) => (x.onclick = () => { ed.aspect = x.dataset.preset; setDirty(); renderPanel(); }));
    $$("[data-q]", p).forEach((x) => (x.onclick = () => { ed.quality = x.dataset.q; setDirty(); renderPanel(); }));
    on("#xRender", "click", doRender); on("#xApprove", "click", doApprove); on("#xReject", "click", doReject);
  }
  const body = () => ({ edit: E.d.edit, words: E.d.words, title: E.d.title, caption: E.d.caption });
  async function doSave() { if (!canEdit) return; const r = await api(`/api/clips/${clip.id}/save`, { method: "POST", body: body() }); if (r.ok) { setDirty(false); toast("Saved", "good"); } else toast(r.error || "Save failed", "bad"); }
  async function doRender() {
    if (!canEdit) return;
    const r = await api(`/api/clips/${clip.id}/render`, { method: "POST", body: body() });
    if (!r.ok) return toast(r.error || "Render failed", "bad");
    setDirty(false); E.clip.rendering = true; vid.pause(); setMode("vertical"); toast("Rendering…");
    const t0 = Date.now();
    const poll = setInterval(async () => {
      const c = await api(`/api/clips/${clip.id}`);
      if (!c.rendering || Date.now() - t0 > 600000) {
        clearInterval(poll); Object.assign(clip, c); E.clip = clip; E.d.edit.cuts = c.edit_json.cuts; E.clip.rendering = false;
        setMode("vertical"); drawTimeline(); renderPanel(); toast("Render finished", "good");
      }
    }, 1500);
    pageTimers.push(poll);
  }
  async function doApprove() {
    if (E.dirty) { toast("Render your changes first", "bad"); E.tab = "export"; return renderPanel(); }
    const r = await api(`/api/clips/${clip.id}/approve`, { method: "POST", body: {} });
    if (!r.ok) return toast(r.error || "Failed", "bad");
    toast("Approved: " + r.file, "good"); clip.status = "approved"; renderPanel();
    if (neighbours[1]) setTimeout(() => (location.hash = `#/editor/${neighbours[1].id}`), 700);
  }
  async function doReject() {
    if (!confirm("Reject this clip? Its video files will be deleted.")) return;
    await api(`/api/clips/${clip.id}/reject`, { method: "POST" }); toast("Rejected");
    location.hash = neighbours[1] ? `#/editor/${neighbours[1].id}` : neighbours[0] ? `#/editor/${neighbours[0].id}` : "#/highlights";
  }
  function camModal() {
    let box = E.d.edit.cam_box ? [...E.d.edit.cam_box] : null;
    const w = openModal(`<h2>Webcam area</h2><p class="sub">Drag a rectangle around the streamer's facecam. It goes on top in the Facecam split layout.</p>
      <div style="text-align:center"><div class="camstage" id="camStage"><img src="/media/frame/${clip.id}?t=${(T.in() + 1).toFixed(1)}" alt="Frame from the clip" draggable="false"><div class="cambox hidden" id="camBox"></div></div></div>
      <label class="toggle" style="margin-top:14px"><input type="checkbox" id="camAll" checked> Use for every clip from this channel/video</label>
      <div class="modal-foot"><button class="btn ghost bad" id="camClear">No webcam</button><div class="grow"></div><button class="btn" onclick="closeModal()">Cancel</button><button class="btn primary" id="camSave">Save area</button></div>`, { wide: true });
    const stage = $("#camStage", w), cb = $("#camBox", w);
    const show = () => { if (!box) return cb.classList.add("hidden"); cb.classList.remove("hidden"); Object.assign(cb.style, { left: box[0] * 100 + "%", top: box[1] * 100 + "%", width: box[2] * 100 + "%", height: box[3] * 100 + "%" }); };
    show();
    stage.addEventListener("pointerdown", (e) => {
      e.preventDefault(); const r = stage.getBoundingClientRect(); const sx = (e.clientX - r.left) / r.width, sy = (e.clientY - r.top) / r.height;
      stage.setPointerCapture(e.pointerId);
      const mv = (ev) => { const x = Math.max(0, Math.min(1, (ev.clientX - r.left) / r.width)), y = Math.max(0, Math.min(1, (ev.clientY - r.top) / r.height));
        box = [Math.min(sx, x), Math.min(sy, y), Math.abs(x - sx), Math.abs(y - sy)].map((v) => Math.round(v * 1000) / 1000); show(); };
      const up = () => { stage.removeEventListener("pointermove", mv); stage.removeEventListener("pointerup", up); };
      stage.addEventListener("pointermove", mv); stage.addEventListener("pointerup", up);
    });
    const save = async (bx) => {
      if (bx && (bx[2] < 0.04 || bx[3] < 0.04)) return toast("Draw a bigger box", "bad");
      const r = await api(`/api/clips/${clip.id}/webcam`, { method: "POST", body: { box: bx, apply_to: $("#camAll", w).checked ? "channel" : "clip" } });
      if (!r.ok) return toast(r.error || "Failed", "bad");
      E.d.edit.cam_box = r.edit.cam_box; E.d.edit.layout = r.edit.layout; setDirty(); closeModal(); E.tab = "layout"; renderPanel(); toast(bx ? "Webcam area saved. Render to apply." : "Webcam cleared");
    };
    $("#camSave", w).onclick = () => save(box); $("#camClear", w).onclick = () => save(null);
  }
  $("#eSave").onclick = doSave; $("#eRender").onclick = doRender;
  pageKeys = (e, typing) => {
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "s") { e.preventDefault(); doSave(); return true; }
    if (typing || e.ctrlKey || e.metaKey || e.altKey || $("#modalRoot .modal-wrap")) return false;
    const k = e.key;
    if (k === " ") { e.preventDefault(); playSelection(); return true; }
    if ((k === "i" || k === "I") && E.mode === "source" && canEdit) { E.d.edit.in = Math.min(+vid.currentTime.toFixed(1), T.out() - 3); setDirty(); drawTimeline(); return true; }
    if ((k === "o" || k === "O") && E.mode === "source" && canEdit) { E.d.edit.out = Math.max(+vid.currentTime.toFixed(1), T.in() + 3); setDirty(); drawTimeline(); return true; }
    if (k === "ArrowLeft" || k === "ArrowRight") { vid.currentTime = Math.max(0, vid.currentTime + (k === "ArrowLeft" ? -1 : 1) * (e.shiftKey ? 5 : 1)); return true; }
    if (k === "p" || k === "P") { setMode(E.mode === "source" ? "vertical" : "source"); return true; }
    if ((k === "j" || k === "J") && neighbours[0]) { location.hash = `#/editor/${neighbours[0].id}`; return true; }
    if ((k === "k" || k === "K") && neighbours[1]) { location.hash = `#/editor/${neighbours[1].id}`; return true; }
    if (k === "r" || k === "R") { doRender(); return true; }
    if (k === "a" || k === "A") { doApprove(); return true; }
    if (k === "x" || k === "X") { doReject(); return true; }
    return false;
  };
  window.addEventListener("beforeunload", (e) => { if (E.dirty) e.preventDefault(); });
  window.addEventListener("hashchange", () => { if (E.dirty) api(`/api/clips/${clip.id}/save`, { method: "POST", body: body() }); }, { once: true });
  setMode(E.mode); renderPanel();
  if (clip.rendering) { E.clip.rendering = true; showState(); doPollOnly(); }
  function doPollOnly() { const poll = setInterval(async () => { const c = await api(`/api/clips/${clip.id}`); if (!c.rendering) { clearInterval(poll); location.reload(); } }, 2000); pageTimers.push(poll); }
};

/* ---------- RESULTS ---------- */
PAGES.results = async (el) => {
  topbar("Results", "Teach ClipHunter what actually performs on your channels");
  el.innerHTML = '<div class="skel" style="height:200px"></div>';
  async function load() {
    const r = await api("/api/results");
    const st = r.stats;
    const groupTable = (title, rows) => {
      if (!rows.length) return "";
      const mx = Math.max(...rows.map((g) => g.median_views), 1);
      return `<div class="card"><h2>${title}</h2>${rows.map((g) => `<div class="statrow"><span class="ellipsis">${esc(g.name)}</span><div class="bar"><i style="width:${(g.median_views / mx) * 100}%"></i></div>
        <span class="mono" style="text-align:right">${fmtN(g.median_views)}</span><span class="faint" style="text-align:right">n=${g.n}</span></div>`).join("")}
        <div class="faint" style="font-size:11.5px;margin-top:6px">Median views${rows.some((g) => g.avg_pct_viewed != null) ? " · avg % viewed: " + rows.filter((g) => g.avg_pct_viewed != null).map((g) => `${esc(g.name)} ${g.avg_pct_viewed}%`).join(", ") : ""}</div></div>`;
    };
    el.innerHTML = `
      <div class="callout" style="margin-bottom:18px">${icon("info")}<div>Add the real numbers from TikTok, YouTube Studio or Instagram for clips you posted. After ${6} results, ClipHunter tells the AI what worked for <b>you</b> and nudges rankings by at most ±5 points per category. It never invents stats or promises views.</div></div>
      <div class="kv"><div class="stat"><b>${st.total}</b><span>Results logged</span></div><div class="stat"><b>${fmtN(st.median_views)}</b><span>Median views</span></div>
        <div class="stat"><b>${r.approved.length}</b><span>Approved clips</span></div><div class="stat ${st.enough_data ? "accent" : ""}"><b>${st.enough_data ? "On" : "Not yet"}</b><span>Learning</span><small>${st.enough_data ? "used in AI scoring" : `needs ${Math.max(0, 6 - st.total)} more`}</small></div></div>
      <div class="grid2" style="margin-top:18px">
        <div class="card"><h2>Add a result</h2>
          <div class="field"><label class="f" for="rClip">Clip</label><select id="rClip">${r.approved.map((c) => `<option value="${c.id}">#${c.id} · ${esc((c.hook || c.title || c.category || "").slice(0, 50))} (${esc(c.source_name || "")})</option>`).join("") || '<option value="">Approve a clip first</option>'}</select></div>
          <div class="grid2"><div class="field"><label class="f">Platform</label><select id="rPlat"><option>TikTok</option><option>YouTube Shorts</option><option>Instagram Reels</option><option>Facebook</option><option>Other</option></select></div>
            <div class="field"><label class="f">Posted</label><input type="date" id="rDate"></div></div>
          <div class="grid2">${[["views", "Views *"], ["avg_pct_viewed", "Avg % viewed"], ["completion_rate", "Completion %"], ["watch_time_sec", "Watch time (s)"], ["likes", "Likes"], ["comments", "Comments"], ["shares", "Shares"], ["saves", "Saves"]].map(([k, l]) =>
            `<div class="field"><label class="f">${l}</label><input data-r="${k}" inputmode="decimal" placeholder="${k === "views" ? "e.g. 12.4k" : ""}"></div>`).join("")}</div>
          <button class="btn primary" id="rAdd" ${r.approved.length ? "" : "disabled"}>${icon("plus")}Add result</button></div>
        <div class="card"><h2>Import a CSV</h2><p class="muted" style="font-size:13px;margin-top:-4px">Columns: clip_id (or the approved file name), views, and any of avg_pct_viewed, completion_rate, likes, comments, shares, saves, platform, posted_at. Common YouTube Studio column names work too.</p>
          <div class="row"><input type="file" id="rCsv" accept=".csv,text/csv"><a class="btn" href="/api/results/template.csv">${icon("download")}Template</a></div>
          <div id="rCsvOut" class="muted" style="font-size:13px;margin-top:10px"></div>
          ${r.insights ? `<h2 style="margin-top:18px">What the AI is told</h2><pre class="mono" style="white-space:pre-wrap;color:var(--muted);margin:0">${esc(r.insights)}</pre>` : ""}</div></div>
      ${st.total ? `<div class="grid2" style="margin-top:18px">${groupTable("By highlight type", st.by_category)}${groupTable("By clip length", st.by_length)}${groupTable("By platform", st.by_platform)}${groupTable("By layout", st.by_layout)}</div>` : ""}
      <div class="section-head"><h2>Logged results</h2></div>
      <div class="card" style="padding:6px 10px">${r.results.length ? `<table class="t"><thead><tr><th>Clip</th><th>Platform</th><th>Views</th><th>% viewed</th><th>Likes</th><th>Shares</th><th></th></tr></thead><tbody>${r.results.map((x) => `<tr>
        <td><b>#${x.clip_id}</b> <span class="muted">${esc((x.hook || "").slice(0, 40))}</span> <span class="chip cat">${esc(x.category || "")}</span></td><td>${esc(x.platform || "")}</td>
        <td class="mono">${fmtN(x.views)}</td><td class="mono">${x.avg_pct_viewed != null ? x.avg_pct_viewed + "%" : "–"}</td><td class="mono">${fmtN(x.likes)}</td><td class="mono">${fmtN(x.shares)}</td>
        <td style="text-align:right"><button class="btn xs ghost bad" data-delres="${x.id}" aria-label="Delete">${icon("trash")}</button></td></tr>`).join("")}</tbody></table>` : '<div class="empty">No results yet.</div>'}</div>`;
    $("#rAdd").onclick = async () => {
      const body = { clip_id: $("#rClip").value, platform: $("#rPlat").value, posted_at: $("#rDate").value };
      $$("[data-r]").forEach((i) => { if (i.value) body[i.dataset.r] = i.value; });
      const x = await api("/api/results", { method: "POST", body });
      if (!x.ok) return toast(x.error, "bad"); toast("Result added", "good"); load();
    };
    $("#rCsv").onchange = async (e) => { const fd = new FormData(); fd.append("file", e.target.files[0]); const x = await api("/api/results/import", { method: "POST", body: fd });
      $("#rCsvOut").textContent = `Imported ${x.added} row(s).${x.skipped && x.skipped.length ? " Skipped: " + x.skipped.join("; ") : ""}`; if (x.added) setTimeout(load, 800); };
    $$("[data-delres]").forEach((b) => (b.onclick = async () => { await api(`/api/results/${b.dataset.delres}`, { method: "DELETE" }); load(); }));
  }
  await load();
};

/* ---------- SETTINGS ---------- */
PAGES.settings = async (el) => {
  topbar("Settings", "AI, quality gate, game profiles and clip defaults");
  const { settings: S, providers, profiles, styles } = await api("/api/settings");
  const sel = (k, opts) => `<select data-k="${k}">${opts.map(([v, l]) => `<option value="${esc(v)}" ${String(S[k]) === String(v) ? "selected" : ""}>${esc(l)}</option>`).join("")}</select>`;
  const inp = (k, type = "text", extra = "") => `<input data-k="${k}" type="${type}" value="${esc(S[k])}" ${extra}>`;
  const chk = (k, label) => `<label class="toggle field"><input type="checkbox" data-k="${k}" ${S[k] ? "checked" : ""}> ${label}</label>`;
  const rng = (k, min, max, step = 1) => `<div class="range-row"><input type="range" data-k="${k}" min="${min}" max="${max}" step="${step}" value="${S[k]}"><output>${S[k]}</output></div>`;
  const f = (label, control, help = "") => `<div class="field"><label class="f">${label}</label>${control}${help ? `<small>${help}</small>` : ""}</div>`;
  const sections = [["ai", "AI & vision"], ["stt", "Transcription"], ["quality", "Quality gate"], ["game", "Game & language"], ["defaults", "Clip defaults"], ["live", "Live channels"], ["advanced", "Advanced"]];
  el.innerHTML = `<div class="settings-layout"><nav class="settings-nav">${sections.map(([k, l]) => `<a href="javascript:void(0)" data-go="${k}">${l}</a>`).join("")}</nav><div>
    <section class="card settings-section" id="s-ai"><h2>AI & vision</h2><p>The AI editor scores every moment and picks where clips start and end. A second, independent pass re-checks every clip. With vision, both passes see frames.</p>
      ${f("Provider", sel("ai_provider", Object.entries(providers).map(([k, p]) => [k, p.label])), `<span id="signup"></span>`)}
      <div class="grid2">${f("API key", inp("ai_key", "password", 'autocomplete="off" placeholder="paste your key"'))}${f("API address", inp("ai_base_url"))}</div>
      <div class="grid2">${f("Text model", inp("ai_model", "text", 'list="models"'))}${f("Vision model (optional)", inp("vision_model", "text", 'list="models" placeholder="same as text model"'), "An image-capable model on the same provider. Leave empty if the text model can see.")}</div>
      <datalist id="models"></datalist>
      ${f("Send frames to the AI", sel("vision_mode", [["auto", "Yes, when the model can see (recommended)"], ["off", "No, text only (transcript + chat)"]]))}
      <div class="row field"><button class="btn" id="testAI">${icon("refresh")}Test connection & vision</button><span id="testOut" class="test-result muted"></span></div>
      ${f("Pause between AI calls (seconds)", inp("ai_min_gap_sec", "number", 'min="0"'), "Free plans limit requests per minute. 3 is safe for Groq's free tier.")}</section>
    <section class="card settings-section" id="s-stt"><h2>Transcription</h2><p>Word timestamps power captions, smart start/end points and the AI's understanding of what the streamer said.</p>
      ${f("Where to transcribe", sel("transcription", [["auto", "Auto: PC first, Groq cloud if the PC can't"], ["groq", "Groq cloud (free, best quality, recommended)"], ["local", "PC only"]]))}
      <div class="grid2">${f("Groq key for transcription", inp("stt_key", "password", 'placeholder="empty = reuse AI key if Groq"'))}${f("PC speech model", sel("whisper_model", [["tiny", "tiny (fastest)"], ["base", "base"], ["small", "small"], ["medium", "medium (slow)"]]))}</div>
      ${f("Language", sel("caption_language", [["auto", "Auto detect"], ["en", "English"], ["ur", "Urdu (Urdu script)"], ["hi", "Hindi"]]))}</section>
    <section class="card settings-section" id="s-quality"><h2>Quality gate</h2><p>Quality first: these numbers decide what you see. A video with nothing good gives zero clips.</p>
      <div class="grid2">${f("Top pick at or above", rng("export_threshold", 60, 100), "Ready to post. Default 85.")}${f("Review at or above", rng("review_threshold", 40, 100), "Below this, moments are rejected. Default 70.")}</div>
      <div class="grid2">${f("Max clips per video", inp("max_clips_per_video", "number", 'min="1" max="50"'), "A limit, not a target.")}${f("Moments the AI checks per hour of video", inp("candidates_per_hour", "number", 'min="2" max="60"'), "More = more thorough, more AI calls.")}</div>
      ${chk("second_pass", "Independent second AI review of every clip that passes the first check (recommended)")}
      ${chk("learning", "Use my posted-clip results to nudge rankings (max ±5 points)")}
      ${chk("keep_rejected_media", "Keep video of rejected moments (uses disk; lets you rescue them)")}</section>
    <section class="card settings-section" id="s-game"><h2>Game & language</h2>
      <div class="grid2">${f("Default game profile", sel("default_profile", [["auto", "Auto-detect from the video title"], ...profiles.map((p) => [p.id, p.name])]), "Each profile knows its highlight types and what to reject.")}${f("Game name (for the AI)", inp("game_context"))}</div>
      ${f("Hook & caption language", sel("hook_language", [["English", "English"], ["Roman Urdu", "Roman Urdu"], ["Hinglish", "Hinglish"]]))}
      <div class="row wrap" style="gap:6px">${profiles.map((p) => `<span class="chip cat" title="${esc(p.categories.join(", "))}">${esc(p.name)}</span>`).join("")}</div></section>
    <section class="card settings-section" id="s-defaults"><h2>Clip defaults</h2><p>Every new clip starts with these. You can change each clip in the editor.</p>
      <div class="grid2">${f("Aspect ratio", sel("aspect", [["9:16", "9:16 (TikTok / Shorts / Reels)"], ["1:1", "1:1 square"], ["16:9", "16:9 landscape"]]))}${f("Layout", sel("layout", [["auto", "Auto (facecam split if a webcam is found)"], ["facecam", "Facecam split"], ["blur", "Full gameplay on blurred background"], ["crop", "Center crop"], ["action", "Follow the action"]]))}</div>
      <div class="grid2">${f("Caption style", sel("caption_style", Object.entries(styles)))}${f("Caption position", sel("caption_pos", [["auto", "Auto (avoid gameplay)"], ["top", "Top"], ["middle", "Middle"], ["bottom", "Bottom"]]))}</div>
      <div class="grid2">${f("Gameplay zoom (blur)", inp("zoom", "number", 'step="0.05" min="1" max="1.8"'))}${f("Export quality", sel("export_quality", [["high", "High"], ["balanced", "Balanced"], ["small", "Small files"]]))}</div>
      ${chk("captions", "Burn in captions")}${chk("dead_air", "Cut dead air automatically")}${chk("auto_webcam", "Detect the streamer's webcam automatically (needs opencv-python)")}</section>
    <section class="card settings-section" id="s-live"><h2>Live channels</h2>
      <div class="grid2">${f("Check channels every (seconds)", inp("check_interval_sec", "number", 'min="30"'))}${f("Find clips every (minutes) while live", inp("process_every_min", "number", 'min="3"'))}</div>
      <div class="grid2">${f("Max streams recorded at once", inp("max_live_recordings", "number", 'min="1" max="5"'))}${f("Recording quality", inp("record_quality"), "720p uses about 2–3 GB of internet per hour.")}</div>
      ${chk("keep_recordings", "Keep full recordings after clipping (uses lots of disk)")}</section>
    <section class="card settings-section" id="s-advanced"><h2>Advanced</h2>
      <div class="grid2">${f("Signal sensitivity", inp("min_signal", "number", 'step="0.1" min="0.5"'), "Lower = more moments get a closer look.")}${f("Chat delay (seconds)", inp("chat_delay_sec", "number", 'min="0"'))}</div>
      <div class="grid2">${f("Chunk length (minutes)", inp("chunk_minutes", "number", 'min="1"'))}${f("Chunk overlap (seconds)", inp("chunk_overlap_sec", "number", 'min="45"'), "Highlights crossing chunk edges are never missed.")}</div>
      <div class="grid2">${f("Context before a moment (s, 0 = game profile)", inp("context_before", "number", 'min="0"'))}${f("Context after (s, 0 = game profile)", inp("context_after", "number", 'min="0"'))}</div>
      <div class="grid2">${f("Shortest clip (s)", inp("min_clip_sec", "number", 'min="5"'))}${f("Longest clip (s)", inp("max_clip_sec", "number", 'max="180"'))}</div></section>
    <div class="savebar"><span class="muted grow" id="saveNote" style="align-self:center;font-size:13px"></span><button class="btn primary" id="saveS">${icon("save")}Save settings</button></div></div></div>`;
  $$("[data-go]", el).forEach((a) => (a.onclick = () => $("#s-" + a.dataset.go).scrollIntoView({ behavior: "smooth" })));
  $$('input[type=range][data-k]', el).forEach((r) => r.addEventListener("input", () => (r.nextElementSibling.textContent = r.value)));
  const v = (k) => $(`[data-k="${k}"]`, el);
  const signup = () => { const p = providers[v("ai_provider").value] || {}; $("#signup").innerHTML = p.signup ? `Free key: <a href="${p.signup}" target="_blank" rel="noopener">${p.signup} ${icon("external", 'style="width:12px;height:12px"')}</a>` : ""; v("ai_key").disabled = !p.needs_key; };
  signup();
  v("ai_provider").addEventListener("change", () => { const p = providers[v("ai_provider").value]; if (p && v("ai_provider").value !== "custom") { v("ai_base_url").value = p.base_url; v("ai_model").value = p.model; v("vision_model").value = p.vision_model || ""; } signup(); });
  $("#testAI").onclick = async () => {
    $("#testOut").textContent = "Testing…"; $("#testOut").style.color = "";
    const r = await api("/api/ai/test", { method: "POST", body: { base_url: v("ai_base_url").value, key: v("ai_key").value, model: v("ai_model").value, vision_model: v("vision_model").value } });
    $("#testOut").innerHTML = `${r.ok ? '<span class="chip approved">Text ✓</span>' : '<span class="chip rejected">Text ✗</span>'} ${r.vision ? '<span class="chip approved">Vision ✓</span>' : r.vision === false ? '<span class="chip review">Vision ✗</span>' : ""} <span class="muted">${esc(r.message)}</span>`;
    $("#models").innerHTML = (r.models || []).map((m) => `<option value="${esc(m)}">`).join("");
  };
  $("#saveS").onclick = async () => {
    const body = {}; $$("[data-k]", el).forEach((i) => (body[i.dataset.k] = i.type === "checkbox" ? i.checked : i.value));
    const r = await api("/api/settings", { method: "POST", body });
    toast("Settings saved", "good"); $("#saveNote").textContent = r.reclassified ? `${r.reclassified} clip(s) moved between Top pick / Review / Rejected with the new thresholds.` : "";
    pollState();
  };
};
