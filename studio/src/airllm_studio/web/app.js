/* AirLLM Studio web UI. No build step, no dependencies. */
(() => {
  "use strict";

  const $ = (sel, root = document) => root.querySelector(sel);
  const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];
  const el = (tag, attrs = {}, ...kids) => {
    const node = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs)) {
      if (v === undefined || v === null || v === false) continue;
      if (k === "class") node.className = v;
      else if (k === "text") node.textContent = v;
      else if (k === "html") node.innerHTML = v;
      else if (k.startsWith("on")) node.addEventListener(k.slice(2), v);
      else node.setAttribute(k, v === true ? "" : v);
    }
    for (const kid of kids.flat()) if (kid !== null && kid !== undefined && kid !== false)
      node.append(kid instanceof Node ? kid : document.createTextNode(String(kid)));
    return node;
  };
  const icon = (path, extra = "") => {
    const span = document.createElement("span");
    span.innerHTML = `<svg viewBox="0 0 20 20" aria-hidden="true" ${extra}>${path}</svg>`;
    return span.firstChild;
  };
  const ICONS = {
    copy: '<rect x="6.5" y="6.5" width="9" height="9" rx="1.6"/><path d="M4.5 13V5.6c0-.6.5-1.1 1.1-1.1H13"/>',
    check: '<path d="M4.5 10.5l3.5 3.5 7.5-8"/>',
    retry: '<path d="M15.5 9.5a5.5 5.5 0 1 1-1.8-4.1M15.5 3.5v3.5H12"/>',
    edit: '<path d="M4 16h3l8.3-8.3-3-3L4 13v3zM11.3 5.7l3 3"/>',
    trash: '<path d="M4.5 6h11M8 6V4.5h4V6M6 6l.7 9.5h6.6L14 6"/>',
    folder: '<path d="M3 6.5V15a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1V8a1 1 0 0 0-1-1h-6.2L8.3 5H4a1 1 0 0 0-1 1.5z"/>',
    plus: '<path d="M10 4v12M4 10h12"/>',
    x: '<path d="M5 5l10 10M15 5L5 15"/>',
    move: '<path d="M3 6.5V15a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1V8a1 1 0 0 0-1-1h-6.2L8.3 5H4a1 1 0 0 0-1 1.5z"/><path d="M8 11.5h5M11 9.5l2 2-2 2"/>',
    file: '<path d="M6 3h5.5L15 6.5V16a1 1 0 0 1-1 1H6a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1z"/><path d="M11 3v4h4"/>',
    wave: '<path d="M3 10h1.5M6 7v6M9 4.5v11M12 7v6M15 8.5v3M17 10h0"/>',
    more: '<path d="M5 10h.01M10 10h.01M15 10h.01" stroke-width="2.8"/>',
  };

  const store = {
    get(key, fallback) { try { const v = localStorage.getItem("airllm." + key); return v === null ? fallback : JSON.parse(v); } catch { return fallback; } },
    set(key, value) { try { localStorage.setItem("airllm." + key, JSON.stringify(value)); } catch { /* storage may be off */ } },
  };

  // ------------------------------------------------------------------ API
  async function api(path, { method = "GET", body, signal } = {}) {
    const res = await fetch(path, {
      method, signal,
      headers: body !== undefined ? { "Content-Type": "application/json" } : {},
      body: body !== undefined ? JSON.stringify(body) : undefined,
    });
    const text = await res.text();
    let data = {};
    try { data = text ? JSON.parse(text) : {}; } catch { data = { error: text }; }
    if (!res.ok) {
      const msg = data.error?.message || data.error || data.detail || `${res.status} ${res.statusText}`;
      throw new Error(typeof msg === "string" ? msg : JSON.stringify(msg));
    }
    return data;
  }

  function toast(message, kind = "") {
    const node = el("div", { class: `toast ${kind}`, role: kind === "error" ? "alert" : "status", text: message });
    $("#toasts").append(node);
    setTimeout(() => node.remove(), kind === "error" ? 7000 : 3500);
  }

  // ------------------------------------------------------------------ formatting
  const fmtBytes = (n) => {
    if (!n) return "0 B";
    const u = ["B", "KB", "MB", "GB", "TB"];
    const i = Math.min(Math.floor(Math.log(n) / Math.log(1024)), u.length - 1);
    const v = n / 1024 ** i;
    return `${v >= 100 || i < 2 ? v.toFixed(0) : v.toFixed(1)} ${u[i]}`;
  };
  const fmtDuration = (s) => {
    if (s < 60) return `${s.toFixed(s < 10 ? 1 : 0)} s`;
    const m = Math.floor(s / 60);
    return m < 60 ? `${m} min ${Math.round(s % 60)} s` : `${Math.floor(m / 60)} h ${m % 60} min`;
  };
  const escapeHtml = (s) => s.replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);

  // Small, safe Markdown: everything is escaped first, then a fixed set of constructs is formatted.
  function inlineMd(s) {
    const codes = [];
    s = s.replace(/`([^`\n]+)`/g, (_, c) => { codes.push(c); return `\u0000${codes.length - 1}\u0000`; });
    s = escapeHtml(s);
    s = s.replace(/\[([^\]\n]+)\]\((https?:\/\/[^\s)]+)\)/g, (_, t, u) => `<a href="${u}" target="_blank" rel="noopener noreferrer">${t}</a>`);
    s = s.replace(/\*\*([^*\n]+)\*\*/g, "<strong>$1</strong>");
    s = s.replace(/(^|[^*\w])\*([^*\n]+)\*(?!\w)/g, "$1<em>$2</em>");
    s = s.replace(/(^|[^_\w])_([^_\n]+)_(?!\w)/g, "$1<em>$2</em>");
    return s.replace(/\u0000(\d+)\u0000/g, (_, i) => `<code>${escapeHtml(codes[+i])}</code>`);
  }

  function renderMarkdown(src) {
    const out = [];
    const lines = src.replace(/\r\n/g, "\n").split("\n");
    let i = 0;
    let para = [];
    const flushPara = () => { if (para.length) { out.push(`<p>${inlineMd(para.join("\n")).replace(/\n/g, "<br>")}</p>`); para = []; } };
    while (i < lines.length) {
      const line = lines[i];
      const fence = line.match(/^\s*```\s*([\w+#.-]*)/);
      if (fence) {
        flushPara();
        const lang = fence[1];
        const code = [];
        i++;
        while (i < lines.length && !/^\s*```\s*$/.test(lines[i])) code.push(lines[i++]);
        i++;
        out.push(`<pre${lang ? ` data-lang="${escapeHtml(lang)}"` : ""}>${lang ? `<span class="code-lang">${escapeHtml(lang)}</span>` : ""}<code>${escapeHtml(code.join("\n"))}</code></pre>`);
        continue;
      }
      const heading = line.match(/^(#{1,3})\s+(.*)$/);
      if (heading) { flushPara(); out.push(`<h${heading[1].length + 1}>${inlineMd(heading[2])}</h${heading[1].length + 1}>`); i++; continue; }
      if (/^\s*([-*+]|\d+[.)])\s+/.test(line)) {
        flushPara();
        const ordered = /^\s*\d+[.)]\s+/.test(line);
        const items = [];
        while (i < lines.length && /^\s*([-*+]|\d+[.)])\s+/.test(lines[i])) {
          let item = lines[i].replace(/^\s*([-*+]|\d+[.)])\s+/, "");
          i++;
          while (i < lines.length && /^\s{2,}\S/.test(lines[i]) && !/^\s*([-*+]|\d+[.)])\s+/.test(lines[i])) item += "\n" + lines[i++].trim();
          items.push(`<li>${inlineMd(item).replace(/\n/g, "<br>")}</li>`);
        }
        out.push(ordered ? `<ol>${items.join("")}</ol>` : `<ul>${items.join("")}</ul>`);
        continue;
      }
      if (/^\s*>/.test(line)) {
        flushPara();
        const quote = [];
        while (i < lines.length && /^\s*>/.test(lines[i])) quote.push(lines[i++].replace(/^\s*>\s?/, ""));
        out.push(`<blockquote>${inlineMd(quote.join("\n")).replace(/\n/g, "<br>")}</blockquote>`);
        continue;
      }
      if (!line.trim()) { flushPara(); i++; continue; }
      para.push(line);
      i++;
    }
    flushPara();
    return out.join("");
  }

  // Reasoning models (e.g. Qwen3) wrap their thinking in <think>…</think>.
  function renderAnswer(text, streaming) {
    if (streaming && (text.match(/\*\*/g) || []).length % 2) text = text.replace(/\*\*(?!.*\*\*)/s, "");
    const m = text.match(/^\s*<think>([\s\S]*?)(<\/think>|$)([\s\S]*)$/);
    if (!m) return renderMarkdown(text);
    const closed = m[2] === "</think>";
    const thinking = `<details class="think"${closed ? "" : " open"}><summary>${closed ? "Reasoning" : "Reasoning…"}</summary>${renderMarkdown(m[1].trim())}</details>`;
    return thinking + renderMarkdown(m[3] || "");
  }

  // ------------------------------------------------------------------ state
  const state = {
    view: "chat",
    status: null,
    models: [],
    chats: [],
    chat: null,                 // { id, title, model, messages: [{role, content, stats?, model?}] }
    model: store.get("model", ""),
    abort: null,                // AbortController of the answer being written (one at a time)
    run: null,                  // { chat, meter } of that answer; it keeps going while you browse
    settings: null,
    catalog: [],
    online: true,
    projects: [],
    project: null,              // project open in the project view (with files)
    newChatProject: null,       // project id for the next new chat
    attachments: [],            // pending: { kind: "image"|"audio", data: base64, url, name, seconds }
    recorder: null,
  };

  const readyModels = () => state.models.filter((m) => m.status === "ready");

  // An answer keeps being written while you look at other chats, projects or pages. These tell
  // whether it is the thing on screen, so only then do the thread, the layer meter and the
  // stop button follow it.
  const runVisible = () => !!state.run && state.view === "chat" && state.chat === state.run.chat;
  const isRunning = (chatId) => !!chatId && state.run?.chat.id === chatId;
  function syncRun() {
    setBusy(runVisible());
    if (runVisible() && state.run.meter) meter[state.run.meter[0]](...state.run.meter[1]);
    else meter.hide();
  }

  // ------------------------------------------------------------------ views
  function show(view) {
    state.view = view;
    for (const v of ["chat", "project", "models", "settings"]) $(`#view-${v}`).hidden = v !== view;
    $("#navModels").classList.toggle("active", view === "models");
    $("#navSettings").classList.toggle("active", view === "settings");
    $("#app").classList.remove("menu-open");
    if (view === "models") refreshModels().then(renderDiscover);
    if (view === "settings") loadSettings();
    if (view === "chat") { renderCrumb(); $("#prompt").focus(); }
    syncRun();
    renderChatList();
  }

  const projectById = (id) => state.projects.find((p) => p.id === id);
  const modelCaps = (name) => state.models.find((m) => m.name === name)?.capabilities || ["completion"];
  const currentModel = () => $("#modelSelect").value || state.model;

  // ------------------------------------------------------------------ status
  async function refreshStatus() {
    try {
      state.status = await api("/api/studio/status");
      state.online = true;
    } catch {
      state.online = false;
    }
    renderStatus();
  }

  function deviceLabel(s) {
    if (!s) return "Connecting…";
    const gpus = s.hardware?.gpus || [];
    const dev = s.device || "";
    if (dev.startsWith("cuda") && gpus.length) {
      const idx = parseInt(dev.split(":")[1] || "0", 10);
      return (gpus[idx] || gpus[0]).name;
    }
    if (!s.hardware?.torch) return "Checking hardware…";
    return gpus.length ? "CPU (GPU available)" : "CPU only";
  }

  function renderStatus() {
    const s = state.status;
    const dot = $("#deviceDot");
    dot.className = "dot " + (!state.online ? "down" : s?.engine?.state === "generating" || s?.engine?.state === "loading" ? "busy" : "ok");
    $("#deviceText").textContent = state.online ? deviceLabel(s) : "Server not reachable";
    const eng = s?.engine;
    let text = "";
    if (!state.online) text = "Server not reachable";
    else if (eng?.state === "loading") text = `Loading ${eng.model || "model"}…`;
    else if (eng?.state === "generating") text = eng.queued ? `Busy, ${eng.queued} waiting` : "Generating";
    else if (eng?.model) text = `${eng.model} loaded`;
    $("#engineState").textContent = text;
    if (s && state.view === "models") $("#storageInfo").textContent =
      `Stored in ${s.models_dir} (${fmtBytes(s.disk?.free || 0)} free)`;
  }

  // ------------------------------------------------------------------ models
  async function refreshModels() {
    try {
      state.models = (await api("/api/studio/models")).models;
    } catch (e) { return; }
    renderModelPicker();
    if (state.view === "models") renderInstalled();
    if (state.view === "chat" && !state.chat?.messages?.length) renderThread();
  }

  function renderModelPicker() {
    const sel = $("#modelSelect");
    const ready = readyModels();
    const current = state.chat?.model || state.model;
    sel.innerHTML = "";
    if (!ready.length) {
      sel.append(el("option", { value: "", text: "No models yet" }));
      sel.disabled = true;
      updateComposerTools();
      return;
    }
    sel.disabled = false;
    for (const m of ready) sel.append(el("option", { value: m.name, text: m.name }));
    const pick = ready.some((m) => m.name === current) ? current : ready[0].name;
    sel.value = pick;
    if (!state.model || !ready.some((m) => m.name === state.model)) { state.model = pick; store.set("model", pick); }
    updateComposerTools();
  }

  // Attach/mic buttons appear only for models that take images/audio natively.
  function updateComposerTools() {
    const caps = modelCaps(currentModel());
    const vision = caps.includes("vision"), audio = caps.includes("audio");
    $("#attachBtn").hidden = !vision;
    $("#micBtn").hidden = !audio && !state.recorder;
    const dropped = state.attachments.filter((a) => (a.kind === "image" && !vision) || (a.kind === "audio" && !audio));
    if (dropped.length) {
      state.attachments = state.attachments.filter((a) => !dropped.includes(a));
      renderAttachments();
      toast(`${currentModel()} does not take ${dropped[0].kind === "image" ? "images" : "audio"}; removed the attachment.`);
    }
    $("#prompt").placeholder = vision && audio ? "Message, image or voice" : vision ? "Message or image" : audio ? "Message or voice" : "Message";
  }

  function jobLine(job) {
    if (!job || job.done) return null;
    let pct = 0, label = job.message || job.phase;
    if (job.phase === "downloading" && job.total) {
      pct = (job.completed / job.total) * 100;
      label = `Downloading ${fmtBytes(job.completed)} of ${fmtBytes(job.total)}`;
    } else if (job.phase === "preparing" && job.layers_total) {
      pct = (job.layers_done / job.layers_total) * 100;
      label = `Preparing layers ${job.layers_done} of ${job.layers_total} (one time)`;
    }
    return el("div", { class: "progress" },
      el("div", { class: "bar", role: "progressbar", "aria-valuenow": Math.round(pct), "aria-valuemin": 0, "aria-valuemax": 100 },
        el("span", { style: `width:${Math.max(2, pct).toFixed(1)}%` })),
      el("small", { text: `${label} (${Math.floor(pct)}%)` }));
  }

  function confirmInline(container, question, onYes, yes = "Delete", no = "Keep") {
    const original = [...container.childNodes];
    container.replaceChildren(el("span", { class: "confirm" }, question,
      el("button", { class: "btn small danger", type: "button", onclick: onYes, text: yes }),
      el("button", { class: "btn small", type: "button", text: no, onclick: () => container.replaceChildren(...original) })));
  }

  function renderInstalled() {
    const box = $("#installed");
    box.replaceChildren();
    if (!state.models.length) {
      box.append(el("p", { class: "empty-row", text: "Nothing installed yet. Pull one of the suggested models below to start." }));
      return;
    }
    for (const m of state.models) {
      const busy = m.job && !m.job.done;
      const meta = el("div", { class: "meta" });
      if (m.parameter_size) meta.append(el("span", { text: `${m.parameter_size} parameters` }));
      if (m.size_on_disk) meta.append(el("span", { text: fmtBytes(m.size_on_disk) + " on disk" }));
      if (m.context_length) meta.append(el("span", { text: `${m.context_length.toLocaleString()} token context` }));
      if (m.compression && m.compression !== "none") meta.append(el("span", { text: m.compression }));
      if ((m.capabilities || []).includes("vision")) meta.append(el("span", { class: "tag", text: "Images" }));
      if ((m.capabilities || []).includes("audio")) meta.append(el("span", { class: "tag", text: "Voice" }));
      if (m.status === "error" && !busy) meta.append(el("span", { class: "err", text: m.error || "Failed" }));

      const actions = el("div", { class: "actions" });
      if (busy) {
        actions.append(el("button", { class: "btn small", type: "button", text: "Cancel", onclick: () => cancelPull(m.name) }));
      } else if (m.status === "ready") {
        actions.append(el("button", { class: "btn small primary", type: "button", text: "Chat", onclick: () => { selectModel(m.name); newChat(); } }));
        actions.append(m.loaded
          ? el("button", { class: "btn small", type: "button", text: "Unload", onclick: () => unloadModel() })
          : el("button", { class: "btn small", type: "button", text: "Load", onclick: (e) => loadModel(m.name, e.target) }));
      } else if (m.needs_remote_code) {
        const source = m.source === "local" ? m.repo : m.name;
        actions.append(el("button", { class: "btn small", type: "button", text: "Allow custom code", title: "This model ships Python code that runs on your computer",
          onclick: () => confirmInline(actions, "Run this model's own code? Only for publishers you trust.", () => pull(source, true), "Allow", "Cancel") }));
      } else {
        actions.append(el("button", { class: "btn small", type: "button", text: "Retry", onclick: () => pull(m.source === "local" ? m.repo : m.name) }));
      }
      if (!busy) actions.append(el("button", {
        class: "icon-btn", type: "button", "aria-label": `Delete ${m.name}`, title: "Delete",
        onclick: () => confirmInline(actions, `Delete ${fmtBytes(m.size_on_disk)}?`, () => deleteModel(m.name)),
      }, icon(ICONS.trash)));

      const row = el("div", { class: "row" },
        el("div", {},
          el("div", { class: "name" }, m.name, m.loaded ? " " : "", m.loaded ? el("span", { class: "tag", text: "loaded" }) : null),
          meta),
        actions);
      const line = jobLine(m.job);
      if (line) row.append(line);
      box.append(row);
    }
  }

  let searchTimer = null;
  let searchSeq = 0;
  async function renderDiscover() {
    const q = $("#pullInput").value.trim();
    const box = $("#discover");
    const looksLikeId = /^[\w.-]+\/[\w.-]+$/.test(q) || /^([a-zA-Z]:)?[\\/~.]/.test(q);
    let items;
    if (q.length >= 2 && !looksLikeId) {
      $("#discoverTitle").textContent = `Hugging Face results for “${q}”`;
      const seq = ++searchSeq;
      box.replaceChildren(el("p", { class: "empty-row", text: "Searching…" }));
      try {
        const res = await api(`/api/studio/search?q=${encodeURIComponent(q)}`);
        if (seq !== searchSeq) return;
        items = res.models.map((r) => ({
          name: r.name, title: "", summary: "",
          download: "", vram: "", gated: r.gated, gguf: r.gguf,
          extra: `${r.downloads.toLocaleString()} downloads`,
        }));
      } catch (e) {
        box.replaceChildren(el("p", { class: "empty-row", text: `Search failed: ${e.message}` }));
        return;
      }
      if (!items.length) { box.replaceChildren(el("p", { class: "empty-row", text: "No text-generation models match." })); return; }
    } else {
      $("#discoverTitle").textContent = "Suggested";
      if (!state.catalog.length) {
        try { state.catalog = (await api("/api/studio/catalog")).models; } catch { state.catalog = []; }
      }
      items = state.catalog;
    }
    const installed = new Map(state.models.map((m) => [m.name.toLowerCase(), m]));
    box.replaceChildren(...items.map((c) => {
      const have = installed.get(c.name.toLowerCase());
      const meta = el("div", { class: "meta" });
      if (c.download) meta.append(el("span", { text: `${c.download} download` }));
      if (c.vram) meta.append(el("span", { text: `${c.vram} GPU memory` }));
      if (c.extra) meta.append(el("span", { text: c.extra }));
      if (c.gated) meta.append(el("span", { class: "tag warn", text: "needs Hugging Face token" }));
      if (c.gguf) meta.append(el("span", { class: "tag warn", text: "GGUF only, not supported" }));
      const action = have
        ? el("span", { class: "tag", text: have.status === "ready" ? "Installed" : have.status })
        : el("button", { class: "btn small", type: "button", text: "Pull", onclick: () => pull(c.name) });
      return el("div", { class: "row" },
        el("div", {},
          c.title ? el("div", { class: "title", text: c.title }) : null,
          el("div", { class: "name", text: c.name }),
          c.summary ? el("div", { class: "summary", text: c.summary }) : null,
          meta),
        el("div", { class: "actions" }, action));
    }));
  }

  async function pull(name, trustRemoteCode = false) {
    if (!name) return;
    try {
      const body = trustRemoteCode ? { name, trust_remote_code: true } : { name };
      await api("/api/studio/models/pull", { method: "POST", body });
      toast(`Pulling ${name}`);
      await refreshModels();
      renderDiscover();
      pollModelsSoon();
    } catch (e) { toast(e.message, "error"); }
  }

  async function cancelPull(name) {
    try { await api("/api/studio/models/cancel", { method: "POST", body: { name } }); toast("Cancelling…"); }
    catch (e) { toast(e.message, "error"); }
  }

  async function deleteModel(name) {
    try {
      await api("/api/delete", { method: "DELETE", body: { model: name } });
      toast(`Deleted ${name}`);
      await refreshModels();
      renderDiscover();
    } catch (e) { toast(e.message, "error"); }
  }

  async function loadModel(name, button) {
    if (button) { button.disabled = true; button.textContent = "Loading…"; }
    try {
      await api("/api/studio/models/load", { method: "POST", body: { name } });
      toast(`${name} is loaded`);
    } catch (e) { toast(e.message, "error"); }
    await refreshModels();
    refreshStatus();
  }

  async function unloadModel() {
    try { await api("/api/studio/models/unload", { method: "POST" }); } catch (e) { toast(e.message, "error"); }
    await refreshModels();
    refreshStatus();
  }

  let modelPoll = null;
  function pollModelsSoon() {
    if (modelPoll) return;
    modelPoll = setInterval(async () => {
      await refreshModels();
      const active = state.models.some((m) => m.job && !m.job.done);
      if (!active) {
        clearInterval(modelPoll); modelPoll = null;
        const justReady = state.models.filter((m) => m.status === "ready" && m.job?.phase === "success");
        if (justReady.length && state.view === "models") renderDiscover();
      }
    }, 1200);
  }

  function selectModel(name) {
    state.model = name;
    store.set("model", name);
    if (state.chat) state.chat.model = name;
    renderModelPicker();
  }

  // ------------------------------------------------------------------ chats
  // The sidebar and, when it is open, the project page list the same chats.
  function renderLists() {
    renderChatList();
    if (state.view === "project") renderProjectChats();
  }

  async function refreshChats() {
    try { state.chats = (await api("/api/studio/chats")).chats; } catch { state.chats = []; }
    renderLists();
  }

  function groupLabel(ts) {
    const d = new Date(ts * 1000), now = new Date();
    const day = (x) => new Date(x.getFullYear(), x.getMonth(), x.getDate()).getTime();
    const diff = (day(now) - day(d)) / 86400000;
    if (diff < 1) return "Today";
    if (diff < 2) return "Yesterday";
    if (diff < 7) return "Previous 7 days";
    if (diff < 30) return "Previous 30 days";
    return d.toLocaleDateString(undefined, { year: "numeric", month: "long" });
  }

  // The project whose chats are shown expanded in the sidebar.
  function openProjectId() {
    if (state.view === "project") return state.project?.id || null;
    return state.chat?.project_id || (state.chat ? null : state.newChatProject);
  }

  function renderChatList() {
    const nav = $("#chatList");
    nav.replaceChildren();
    const expanded = openProjectId();

    nav.append(el("div", { class: "side-head" }, el("span", { text: "Projects" }),
      el("button", { class: "icon-btn", type: "button", "aria-label": "New project", title: "New project", onclick: createProject }, icon(ICONS.plus))));
    if (!state.projects.length) nav.append(el("div", { class: "side-empty", text: "Group chats with shared instructions and files." }));
    for (const p of state.projects) {
      const open = p.id === expanded;
      const active = state.view === "project" && state.project?.id === p.id;
      // A collapsed project still shows that one of its chats is being answered.
      const busy = !open && state.run?.chat.project_id === p.id;
      const item = el("div", { class: "chat-item project-item" + (open ? " open" : "") + (active ? " active" : "") + (busy ? " running" : "") },
        el("a", { href: "#", title: busy ? `${p.name} (writing an answer)` : p.name, "aria-current": active ? "page" : null, "aria-expanded": String(open),
          onclick: (e) => { e.preventDefault(); openProject(p.id); } }, icon(ICONS.folder), el("span", { text: p.name })));
      nav.append(item);
      if (open) for (const c of state.chats.filter((c) => c.project_id === p.id)) nav.append(chatItem(c, true));
    }

    let lastGroup = "";
    for (const c of state.chats.filter((c) => !c.project_id)) {
      const g = groupLabel(c.updated_at);
      if (g !== lastGroup) { nav.append(el("div", { class: "chat-group", text: g })); lastGroup = g; }
      nav.append(chatItem(c, false));
    }
  }

  function chatItem(c, nested) {
    const active = state.view === "chat" && state.chat?.id === c.id;
    const item = el("div", { class: "chat-item" + (active ? " active" : "") + (nested ? " nested" : "") + (isRunning(c.id) ? " running" : "") });
    const link = el("a", { href: "#" + c.id, text: c.title || "New chat", title: isRunning(c.id) ? `${c.title} (writing an answer)` : c.title,
      "aria-current": active ? "page" : null, onclick: (e) => { e.preventDefault(); openChat(c.id); } });
    const more = el("button", { class: "icon-btn", type: "button", "aria-label": `Options for ${c.title || "chat"}`,
      "aria-haspopup": "menu", title: "Rename, move or delete", onclick: (e) => chatMenu(e.currentTarget, c, item) }, icon(ICONS.more));
    item.append(link, more);
    return item;
  }

  function renameChat(c, item) {
    const input = el("input", { value: c.title, "aria-label": "Chat title" });
    let done = false;
    const finish = async (save) => {
      if (done) return;
      done = true;
      if (save && input.value.trim() && input.value.trim() !== c.title) {
        await api(`/api/studio/chats/${c.id}`, { method: "PATCH", body: { title: input.value.trim() } }).catch((e) => toast(e.message, "error"));
        if (state.chat?.id === c.id) state.chat.title = input.value.trim();
      }
      refreshChats();
    };
    input.addEventListener("keydown", (e) => { if (e.key === "Enter") finish(true); if (e.key === "Escape") finish(false); });
    input.addEventListener("blur", () => finish(true));
    item.replaceChildren(input);
    input.focus();
    input.select();
  }

  function stopRunIf(matches) {
    if (state.run && matches(state.run.chat)) { state.run.chat.deleted = true; state.abort.abort(); }
  }

  async function deleteChat(c) {
    stopRunIf((chat) => chat.id === c.id);
    try { await api(`/api/studio/chats/${c.id}`, { method: "DELETE" }); } catch (e) { return toast(e.message, "error"); }
    if (state.chat?.id === c.id) newChat();
    refreshChats();
    refreshProjects();
  }

  function chatMenu(anchor, chat, item) {
    const move = async (projectId) => {
      closeMenu();
      try {
        await api(`/api/studio/chats/${chat.id}`, { method: "PATCH", body: { project_id: projectId } });
        if (state.chat?.id === chat.id) { state.chat.project_id = projectId; renderCrumb(); }
        const name = projectId ? projectById(projectId)?.name : null;
        toast(name ? `Moved to ${name}` : "Moved out of the project");
        await Promise.all([refreshChats(), refreshProjects()]);
        if (state.view === "project" && state.project) openProject(state.project.id);
      } catch (e) { toast(e.message, "error"); }
    };
    const items = [
      el("button", { type: "button", role: "menuitem", onclick: () => { closeMenu(); renameChat(chat, item); } }, icon(ICONS.edit), el("span", { text: "Rename" })),
      el("div", { class: "menu-title", text: "Move to project" }),
      ...state.projects.map((p) => el("button", { type: "button", role: "menuitemradio", "aria-checked": String(chat.project_id === p.id),
        onclick: () => move(p.id) }, icon(ICONS.folder), el("span", { text: p.name }))),
      el("button", { type: "button", role: "menuitemradio", "aria-checked": String(!chat.project_id), onclick: () => move(null) },
        icon(ICONS.x), el("span", { text: "No project" })),
      el("button", { type: "button", role: "menuitem", onclick: async () => { closeMenu(); const p = await createProject(); if (p) move(p.id); } },
        icon(ICONS.plus), el("span", { text: "New project…" })),
      el("div", { class: "menu-sep", role: "separator" }),
      el("button", { type: "button", role: "menuitem", class: "danger", onclick: () => { closeMenu(); deleteChat(chat); } },
        icon(ICONS.trash), el("span", { text: "Delete chat" })),
    ];
    popover(anchor, items);
  }

  // ------------------------------------------------------------------ popover menu
  let openMenu = null;
  function closeMenu() { if (openMenu) { openMenu.remove(); openMenu = null; } }
  function popover(anchor, children) {
    closeMenu();
    const menu = el("div", { class: "menu", role: "menu" }, ...children);
    document.body.append(menu);
    const r = anchor.getBoundingClientRect();
    const top = Math.min(r.bottom + 4, window.innerHeight - menu.offsetHeight - 8);
    menu.style.top = `${Math.max(8, top)}px`;
    menu.style.left = `${Math.max(8, Math.min(r.left, window.innerWidth - menu.offsetWidth - 8))}px`;
    openMenu = menu;
    menu.querySelector("button")?.focus();
    return menu;
  }

  async function openChat(id) {
    try {
      // The chat being answered right now is shown from memory: the saved copy lacks the live answer.
      state.chat = isRunning(id) ? state.run.chat : await api(`/api/studio/chats/${id}`);
      if (state.chat.model) selectModel(state.chat.model);
      clearAttachments();
      show("chat");
      renderThread(true);
    } catch (e) { toast(e.message, "error"); }
  }

  function newChat(projectId = null) {
    state.chat = null;
    state.newChatProject = typeof projectId === "string" ? projectId : null;
    const project = state.newChatProject ? projectById(state.newChatProject) : null;
    if (project?.model && readyModels().some((m) => m.name === project.model)) selectModel(project.model);
    clearAttachments();
    show("chat");
    renderThread();
  }

  function renderCrumb() {
    const pid = state.chat ? state.chat.project_id : state.newChatProject;
    const project = pid ? projectById(pid) : null;
    $("#projectCrumb").hidden = $("#projectCrumbSep").hidden = !project;
    if (project) {
      $("#projectCrumbName").textContent = project.name;
      $("#projectCrumb").title = `Open project ${project.name}`;
    }
  }

  async function persistChat(c = state.chat) {
    if (!c || c.deleted) return;
    const messages = c.messages.filter((m) => !m.pending);
    try {
      if (!c.id) {
        const created = await api("/api/studio/chats", { method: "POST", body: { title: c.title, model: c.model, messages, project_id: c.project_id || null } });
        c.id = created.id;
      } else {
        await api(`/api/studio/chats/${c.id}`, { method: "PATCH", body: { model: c.model, messages } });
      }
      refreshChats();
      if (c.project_id) refreshProjects();
    } catch (e) { toast(`Could not save the chat: ${e.message}`, "error"); }
  }

  // ------------------------------------------------------------------ projects
  async function refreshProjects() {
    try { state.projects = (await api("/api/studio/projects")).projects; } catch { state.projects = []; }
    renderChatList();
    renderCrumb();
  }

  async function createProject() {
    try {
      const n = state.projects.length + 1;
      const project = await api("/api/studio/projects", { method: "POST", body: { name: n > 1 ? `New project ${n}` : "New project" } });
      await refreshProjects();
      await openProject(project.id, true);
      return project;
    } catch (e) { toast(e.message, "error"); return null; }
  }

  async function openProject(id, focusName = false) {
    try { state.project = await api(`/api/studio/projects/${id}`); } catch (e) { return toast(e.message, "error"); }
    show("project");
    renderProject();
    if (focusName) { $("#projectName").focus(); $("#projectName").select(); }
  }

  const approxTokens = (bytes) => Math.round(bytes / 4);

  function renderProjectChats() {
    const p = state.project;
    if (!p) return;
    const chats = state.chats.filter((c) => c.project_id === p.id);
    $("#projectChats").replaceChildren(...(chats.length ? chats.map((c) => el("div", { class: "row" + (isRunning(c.id) ? " running" : "") },
      el("a", { class: "name-link", href: "#" + c.id, text: c.title || "New chat", onclick: (e) => { e.preventDefault(); openChat(c.id); } }),
      el("span", { class: "when", text: isRunning(c.id) ? "Writing an answer…" : groupLabel(c.updated_at) })))
      : [el("p", { class: "empty-row", text: "No chats yet. Start one with “New chat”: it will use this project’s instructions and files." })]));
  }

  function renderProject() {
    const p = state.project;
    if (!p) return;
    $("#projectName").value = p.name;
    $("#projectInstructions").value = p.instructions;
    $("#instructionsState").textContent = "";

    renderProjectChats();

    $("#projectFiles").replaceChildren(...(p.files || []).map((f) => {
      const actions = el("div", { class: "actions" });
      actions.append(el("button", { class: "icon-btn", type: "button", "aria-label": `Remove ${f.name}`, title: "Remove",
        onclick: () => confirmInline(actions, "Remove file?", () => deleteProjectFile(f.id)) }, icon(ICONS.trash)));
      return el("div", { class: "row" },
        el("div", {}, el("div", { class: "name", text: f.name }),
          el("div", { class: "meta" }, el("span", { text: fmtBytes(f.size) }), el("span", { text: `~${approxTokens(f.size).toLocaleString()} tokens` }))),
        actions);
    }));
    const ctx = state.settings?.defaults?.context_length || 4096;
    const tokens = approxTokens((p.file_bytes || 0) + (p.instructions || "").length);
    $("#projectBudget").textContent = p.file_count
      ? `Instructions and files: about ${tokens.toLocaleString()} tokens. With a ${ctx.toLocaleString()}-token context, ${tokens > ctx / 2 ? "files are cut to fit about half of it (raise the context length in Settings if the model supports more)" : "they fit comfortably"}.`
      : "";

    const sel = $("#projectModel");
    sel.replaceChildren(el("option", { value: "", text: "Whatever is selected in the chat" }),
      ...readyModels().map((m) => el("option", { value: m.name, text: m.name })));
    sel.value = readyModels().some((m) => m.name === p.model) ? p.model : "";
    $("#projectDangerZone").replaceChildren(el("button", { type: "button", class: "btn danger", text: "Delete project",
      onclick: () => confirmInline($("#projectDangerZone"),
        p.chat_count ? `Delete the project and its ${p.chat_count} chat${p.chat_count > 1 ? "s" : ""}?` : "Delete the project?",
        deleteProject) }));
  }

  async function saveProject(patch, quiet = false) {
    const p = state.project;
    try {
      state.project = await api(`/api/studio/projects/${p.id}`, { method: "PATCH", body: patch });
      await refreshProjects();
      if (!quiet) renderProject();
      return true;
    } catch (e) { toast(e.message, "error"); return false; }
  }

  async function uploadProjectFiles(files) {
    const p = state.project;
    if (!p || !files.length) return;
    let added = 0;
    for (const file of files) {
      try {
        const res = await fetch(`/api/studio/projects/${p.id}/files?name=${encodeURIComponent(file.name)}`, { method: "POST", body: file });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) throw new Error(data.error || data.detail || `${res.status} ${res.statusText}`);
        added++;
      } catch (e) { toast(`${file.name}: ${e.message}`, "error"); }
    }
    if (added) toast(`Added ${added} file${added > 1 ? "s" : ""}`);
    await openProject(p.id);
    refreshProjects();
  }

  async function deleteProjectFile(fileId) {
    const p = state.project;
    try { await api(`/api/studio/projects/${p.id}/files/${fileId}`, { method: "DELETE" }); } catch (e) { toast(e.message, "error"); }
    await openProject(p.id);
    refreshProjects();
  }

  async function deleteProject() {
    const p = state.project;
    stopRunIf((chat) => chat.project_id === p.id);
    try {
      await api(`/api/studio/projects/${p.id}`, { method: "DELETE" });
      toast(`Deleted ${p.name}`);
      state.project = null;
      if (state.chat?.project_id === p.id) state.chat = null;
      if (state.newChatProject === p.id) state.newChatProject = null;
      await Promise.all([refreshProjects(), refreshChats()]);
      newChat();
    } catch (e) { toast(e.message, "error"); }
  }

  // ------------------------------------------------------------------ thread rendering
  function emptyState() {
    const box = el("div", { class: "empty" }, el("img", { src: "icon.svg", alt: "" }));
    if (!state.online) {
      box.append(el("h2", { text: "AirLLM server is not reachable" }),
        el("p", { text: "Start it from the AirLLM app or run “airllm serve”, then this page reconnects by itself." }));
    } else if (!readyModels().length) {
      const pulling = state.models.find((m) => m.job && !m.job.done);
      box.append(el("h2", { text: pulling ? `Getting ${pulling.name} ready` : "Get a model to start" }),
        el("p", { text: pulling
          ? "You can chat as soon as the download and one-time layer preparation finish."
          : "AirLLM runs models far larger than your GPU memory by reading one layer at a time from disk. Start with the tiny test model to check everything works, then pull a real one." }),
        el("button", { class: "btn primary", type: "button", text: "Browse models", onclick: () => show("models") }),
        pulling ? null : el("button", { class: "btn", type: "button", text: "Try SmolLM2 135M (270 MB)",
          onclick: () => { pull("HuggingFaceTB/SmolLM2-135M-Instruct"); show("models"); } }));
    } else if (state.newChatProject && projectById(state.newChatProject)) {
      const p = projectById(state.newChatProject);
      const bits = [];
      if (p.instructions) bits.push("its instructions");
      if (p.file_count) bits.push(`${p.file_count} file${p.file_count > 1 ? "s" : ""}`);
      box.append(el("h2", { text: `New chat in ${p.name}` }),
        el("p", { text: bits.length ? `${currentModel()} will see ${bits.join(" and ")} from this project.`
          : `This project has no instructions or files yet. Add them from the project page.` }),
        el("button", { class: "btn", type: "button", text: "Open project", onclick: () => openProject(p.id) }));
    } else {
      box.append(el("h2", { text: "What should we work on?" }),
        el("p", { text: `Talking to ${state.model}. Large models read every layer from disk for each token, so answers arrive slowly but steadily; the meter above the message box shows the progress.` }));
    }
    return box;
  }

  function imageMime(b64) {
    const magic = { "iVBOR": "image/png", "/9j/": "image/jpeg", "R0lG": "image/gif", "UklGR": "image/webp", "Qk": "image/bmp" };
    for (const [prefix, mime] of Object.entries(magic)) if (b64.startsWith(prefix)) return mime;
    return "image/png";
  }

  function lightbox(src) {
    const close = () => { overlay.remove(); document.removeEventListener("keydown", onKey); };
    const onKey = (e) => { if (e.key === "Escape") close(); };
    const overlay = el("div", { class: "lightbox", role: "dialog", "aria-label": "Image", onclick: close },
      el("img", { src, alt: "Attached image" }));
    document.addEventListener("keydown", onKey);
    document.body.append(overlay);
  }

  function mediaNode(m) {
    const imgs = m.images || [], clips = m.audio || [];
    if (!imgs.length && !clips.length) return null;
    const box = el("div", { class: "media" });
    for (const b64 of imgs) {
      const src = `data:${imageMime(b64)};base64,${b64}`;
      box.append(el("img", { src, alt: "Attached image", loading: "lazy", onclick: () => lightbox(src) }));
    }
    for (const b64 of clips) box.append(el("audio", { controls: true, src: "data:audio/wav;base64," + b64, preload: "none" }));
    return box;
  }

  function messageNode(m, index) {
    const node = el("div", { class: `msg ${m.role}${m.error ? " error" : ""}` });
    const body = el("div", { class: "body" });
    if (m.role === "user") {
      const media = mediaNode(m);
      if (media) node.append(media);
      body.textContent = m.content;
      if (!m.content) body.hidden = true;
    }
    else if (m.error) body.textContent = m.content;
    else if (m.pending && !m.content) body.append(el("span", { class: "waiting caret", text: m.statusText || "" }));
    else {
      body.innerHTML = renderAnswer(m.content, m.pending);
      if (m.pending) body.lastElementChild?.classList.add("caret");
      decorateCode(body);
    }
    node.append(body);
    if (m.role === "assistant" && !m.pending) {
      const foot = el("div", { class: "msg-foot" });
      if (!m.error) foot.append(copyButton(() => m.content, "Copy answer"));
      if (index === state.chat.messages.length - 1) foot.append(el("button", {
        class: "icon-btn", type: "button", "aria-label": "Regenerate", title: "Regenerate", onclick: regenerate,
      }, icon(ICONS.retry)));
      if (m.stats) {
        const s = m.stats;
        const parts = [`${s.tokens} tokens`];
        if (s.tps) parts.push(`${s.tps.toFixed(s.tps < 1 ? 2 : 1)} tokens/s`);
        if (s.seconds) parts.push(fmtDuration(s.seconds));
        if (s.reason === "length") parts.push("stopped at max length");
        if (s.reason === "cancelled") parts.push("stopped");
        foot.append(el("span", { class: "stats", text: parts.join(", ") }));
      }
      node.append(foot);
    }
    return node;
  }

  function copyButton(getText, label) {
    const btn = el("button", { class: "icon-btn", type: "button", "aria-label": label, title: label }, icon(ICONS.copy));
    btn.addEventListener("click", async () => {
      try {
        await navigator.clipboard.writeText(getText());
        btn.replaceChildren(icon(ICONS.check));
        setTimeout(() => btn.replaceChildren(icon(ICONS.copy)), 1400);
      } catch { toast("Copy failed: clipboard not available", "error"); }
    });
    return btn;
  }

  function decorateCode(root) {
    for (const pre of $$("pre", root)) {
      const code = $("code", pre);
      pre.append(el("span", { class: "copy-code" }, copyButton(() => code.textContent, "Copy code")));
    }
  }

  function renderThread(scrollToEnd = false) {
    const thread = $("#thread");
    if (!state.chat || !state.chat.messages.length) {
      thread.replaceChildren(emptyState());
      return;
    }
    thread.replaceChildren(...state.chat.messages.map(messageNode));
    if (scrollToEnd) scrollDown(true);
  }

  function updateLastMessage() {
    const thread = $("#thread");
    const msgs = state.chat.messages;
    const last = thread.lastElementChild;
    const fresh = messageNode(msgs[msgs.length - 1], msgs.length - 1);
    if (last && last.classList.contains("msg") && thread.children.length === msgs.length) last.replaceWith(fresh);
    else renderThread();
    scrollDown();
  }

  function scrollDown(force = false) {
    const sc = $("#scroller");
    const nearBottom = sc.scrollHeight - sc.scrollTop - sc.clientHeight < 160;
    if (force || nearBottom) sc.scrollTop = sc.scrollHeight;
  }

  // ------------------------------------------------------------------ layer meter
  const meter = {
    ticks: 0,
    show(layers) {
      $("#meter").hidden = false;
      const n = Math.max(1, Math.min(layers || 48, 96));
      if (n !== this.ticks || !$("#meterTrack").children.length) {
        this.ticks = n;
        $("#meterTrack").replaceChildren(...Array.from({ length: n }, (_, i) => el("i", { style: `--i:${i}` })));
      }
    },
    indeterminate(label) {
      this.show(this.ticks || 48);
      $("#meterTrack").classList.add("indeterminate");
      $$("#meterTrack i").forEach((t) => t.className = "");
      $("#meterLabel").replaceChildren(el("span", { text: label }));
    },
    progress(layer, layers, tokens, tps) {
      this.show(layers);
      const track = $("#meterTrack");
      track.classList.remove("indeterminate");
      const pos = Math.floor(((layer - 1) / Math.max(layers, 1)) * this.ticks);
      $$("i", track).forEach((t, i) => { t.className = i < pos ? "done" : i === pos ? "now" : ""; });
      const label = [el("span", {}, "Reading layer ", el("b", { text: `${layer} of ${layers}` }))];
      label.push(el("span", { text: tokens ? `token ${tokens + 1}` : "first token" }));
      if (tps) label.push(el("span", { text: `${tps.toFixed(tps < 1 ? 2 : 1)} tokens/s` }));
      $("#meterLabel").replaceChildren(...label);
    },
    hide() { $("#meter").hidden = true; },
  };

  // ------------------------------------------------------------------ sending
  function setBusy(busy) {
    $("#composer").classList.toggle("busy", busy);
    $("#sendBtn").setAttribute("aria-label", busy ? "Stop" : "Send");
    $("#sendBtn").disabled = false;
  }

  async function send(text) {
    if (!state.online) return toast("The AirLLM server is not reachable.", "error");
    const model = $("#modelSelect").value;
    if (!model) { show("models"); return toast("Pull a model first."); }
    const images = state.attachments.filter((a) => a.kind === "image").map((a) => a.data);
    const audio = state.attachments.filter((a) => a.kind === "audio").map((a) => a.data);
    const title = text || (images.length ? "Image" : "Voice message");
    if (!state.chat) state.chat = { id: null, title: title.slice(0, 80).replace(/\s+/g, " "), model, messages: [],
      project_id: state.newChatProject || null };
    state.chat.model = model;
    const msg = { role: "user", content: text };
    if (images.length) msg.images = images;
    if (audio.length) msg.audio = audio;
    clearAttachments();
    state.chat.messages.push(msg);
    renderCrumb();
    const chat = state.chat;
    // Save a new chat right away: it then shows in the sidebar and its project, so you can leave
    // it while the answer is written and come back to it.
    if (!chat.id) await persistChat(chat);
    await generate(chat);
  }

  async function regenerate() {
    if (!state.chat) return;
    if (state.run) return toast("An answer is still being written. Wait for it, or stop it first.");
    const msgs = state.chat.messages;
    while (msgs.length && msgs[msgs.length - 1].role === "assistant") msgs.pop();
    if (!msgs.length) return;
    await generate(state.chat);
  }

  async function generate(chat) {
    const history = chat.messages.filter((m) => !m.error).map(({ role, content, images, audio }) => ({
      role, content, ...(images?.length ? { images } : {}), ...(audio?.length ? { audio } : {}) }));
    const answer = { role: "assistant", content: "", pending: true, model: chat.model, statusText: "" };
    chat.messages.push(answer);
    const controller = new AbortController();
    const run = state.run = { chat, meter: null };
    state.abort = controller;
    // Meter and thread are only touched while this chat is on screen; syncRun() repaints them on return.
    const paintMeter = (fn, ...args) => { run.meter = [fn, args]; if (runVisible()) meter[fn](...args); };
    const paintAnswer = () => { if (runVisible()) updateLastMessage(); };
    if (runVisible()) renderThread(true);
    syncRun();
    paintMeter("indeterminate", "Starting…");
    renderLists();
    const started = performance.now();
    let firstTokenAt = 0, tokens = 0, finalStats = null;

    try {
      const res = await fetch("/api/chat", {
        method: "POST", signal: controller.signal, headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ model: chat.model, messages: history, stream: true, airllm_progress: true,
          airllm_project: chat.project_id || undefined }),
      });
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error(data.error || data.detail || `${res.status} ${res.statusText}`);
      }
      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buf = "", lastPaint = 0;
      for (;;) {
        const { value, done } = await reader.read();
        if (done) break;
        buf += decoder.decode(value, { stream: true });
        let nl;
        while ((nl = buf.indexOf("\n")) >= 0) {
          const line = buf.slice(0, nl).trim();
          buf = buf.slice(nl + 1);
          if (!line) continue;
          const ev = JSON.parse(line);
          if (ev.error) throw new Error(ev.error);
          if (ev.status) {
            answer.statusText = ev.status === "loading" ? "Loading the model…"
              : ev.status === "queued" ? "Waiting for another answer to finish…" : "Thinking…";
            paintMeter("indeterminate", answer.statusText);
            if (!answer.content) paintAnswer();
          }
          if (ev.progress) {
            tokens = ev.progress.tokens;
            const secs = firstTokenAt ? (performance.now() - firstTokenAt) / 1000 : 0;
            paintMeter("progress", ev.progress.layer, ev.progress.layers, tokens, secs > 0 && tokens > 1 ? (tokens - 1) / secs : 0);
          }
          const piece = ev.message?.content;
          if (piece) {
            if (!firstTokenAt) firstTokenAt = performance.now();
            answer.content += piece;
            const now = performance.now();
            if (now - lastPaint > 60) { paintAnswer(); lastPaint = now; }
          }
          if (ev.done) finalStats = ev;
        }
      }
    } catch (e) {
      if (e.name !== "AbortError") {
        if (!answer.content) {
          answer.error = true;
          answer.content = e.message;
        }
        if (answer.content !== e.message || !runVisible()) toast(runVisible() ? e.message : `“${chat.title}”: ${e.message}`, "error");
      }
    } finally {
      const onScreen = runVisible();
      state.abort = null;
      state.run = null;
      renderLists();              // the "writing" marker goes now, not after the save round trip
      answer.pending = false;
      delete answer.statusText;
      const seconds = (performance.now() - started) / 1000;
      if (!answer.error) {
        const evalCount = finalStats?.eval_count ?? tokens;
        const evalSecs = finalStats ? finalStats.eval_duration / 1e9 : 0;
        answer.stats = {
          tokens: evalCount,
          tps: finalStats?.tokens_per_second || (evalSecs ? evalCount / evalSecs : 0),
          seconds,
          reason: controller.signal.aborted ? "cancelled" : finalStats?.done_reason,
        };
      }
      setBusy(false);
      meter.hide();
      if (onScreen) { updateLastMessage(); $("#prompt").focus(); }
      if (!answer.error || chat.messages.length > 2) persistChat(chat);
      refreshStatus();
    }
  }

  // ------------------------------------------------------------------ attachments and voice
  const MAX_IMAGE_BYTES = 20e6, MAX_IMAGES = 8, MAX_RECORD_SECONDS = 300;
  const fmtClock = (s) => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, "0")}`;

  function readAsBase64(blob) {
    return new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => resolve(String(reader.result).replace(/^data:[^,]*,/, ""));
      reader.onerror = () => reject(reader.error);
      reader.readAsDataURL(blob);
    });
  }

  function clearAttachments() {
    for (const a of state.attachments) if (a.url?.startsWith("blob:")) URL.revokeObjectURL(a.url);
    state.attachments = [];
    renderAttachments();
  }

  function renderAttachments() {
    const box = $("#attachments");
    box.hidden = !state.attachments.length;
    box.replaceChildren(...state.attachments.map((a) => {
      const remove = el("button", { class: "x", type: "button", "aria-label": `Remove ${a.name}`, title: "Remove",
        onclick: () => { state.attachments = state.attachments.filter((x) => x !== a); renderAttachments(); } }, icon(ICONS.x));
      return a.kind === "image"
        ? el("div", { class: "att", title: a.name }, el("img", { src: a.url, alt: a.name }), remove)
        : el("div", { class: "att audio", title: "Voice message" }, icon(ICONS.wave), el("span", { text: `Voice ${fmtClock(a.seconds)}` }), remove);
    }));
  }

  async function addImages(files) {
    const images = [...files].filter((f) => f.type.startsWith("image/"));
    if (!images.length) return;
    if (!modelCaps(currentModel()).includes("vision")) return toast(`${currentModel()} does not take images. Pick a vision model to attach them.`);
    for (const f of images) {
      if (state.attachments.filter((a) => a.kind === "image").length >= MAX_IMAGES) { toast(`Up to ${MAX_IMAGES} images per message.`); break; }
      if (f.size > MAX_IMAGE_BYTES) { toast(`${f.name} is larger than 20 MB.`, "error"); continue; }
      try { state.attachments.push({ kind: "image", data: await readAsBase64(f), url: URL.createObjectURL(f), name: f.name || "image" }); }
      catch (e) { toast(`${f.name}: ${e.message}`, "error"); }
    }
    renderAttachments();
    $("#prompt").focus();
  }

  // Browser recordings (webm/ogg) -> 16 kHz mono 16-bit WAV, what audio models' processors expect.
  async function toWav16k(blob) {
    const ctx = new AudioContext();
    let decoded;
    try { decoded = await ctx.decodeAudioData(await blob.arrayBuffer()); } finally { ctx.close(); }
    const rate = 16000;
    const offline = new OfflineAudioContext(1, Math.max(1, Math.ceil(decoded.duration * rate)), rate);
    const source = offline.createBufferSource();
    source.buffer = decoded;
    source.connect(offline.destination);
    source.start();
    const pcm = (await offline.startRendering()).getChannelData(0);
    const view = new DataView(new ArrayBuffer(44 + pcm.length * 2));
    const text = (offset, str) => { for (let i = 0; i < str.length; i++) view.setUint8(offset + i, str.charCodeAt(i)); };
    text(0, "RIFF"); view.setUint32(4, 36 + pcm.length * 2, true); text(8, "WAVE"); text(12, "fmt ");
    view.setUint32(16, 16, true); view.setUint16(20, 1, true); view.setUint16(22, 1, true);
    view.setUint32(24, rate, true); view.setUint32(28, rate * 2, true); view.setUint16(32, 2, true); view.setUint16(34, 16, true);
    text(36, "data"); view.setUint32(40, pcm.length * 2, true);
    for (let i = 0; i < pcm.length; i++) view.setInt16(44 + i * 2, Math.max(-1, Math.min(1, pcm[i])) * 0x7fff, true);
    return { wav: new Blob([view.buffer], { type: "audio/wav" }), seconds: pcm.length / rate };
  }

  async function toggleRecording() {
    if (state.recorder) { state.recorder.stop(); return; }
    if (!navigator.mediaDevices?.getUserMedia || !window.MediaRecorder) return toast("This window cannot use the microphone.", "error");
    let stream;
    try { stream = await navigator.mediaDevices.getUserMedia({ audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true } }); }
    catch (e) { return toast(`Microphone not available: ${e.message}`, "error"); }
    const chunks = [];
    const rec = new MediaRecorder(stream);
    const started = performance.now();
    const mic = $("#micBtn"), clock = $("#recTime");
    const timer = setInterval(() => {
      const secs = (performance.now() - started) / 1000;
      clock.textContent = fmtClock(secs);
      if (secs >= MAX_RECORD_SECONDS && rec.state === "recording") rec.stop();
    }, 250);
    rec.ondataavailable = (e) => { if (e.data.size) chunks.push(e.data); };
    rec.onstop = async () => {
      clearInterval(timer);
      stream.getTracks().forEach((t) => t.stop());
      state.recorder = null;
      mic.classList.remove("recording");
      mic.setAttribute("aria-label", "Record voice");
      clock.hidden = true;
      updateComposerTools();
      try {
        const { wav, seconds } = await toWav16k(new Blob(chunks, { type: rec.mimeType }));
        if (seconds < 0.3) return toast("That recording was too short.");
        state.attachments.push({ kind: "audio", data: await readAsBase64(wav), name: "voice.wav", seconds });
        renderAttachments();
        $("#prompt").focus();
      } catch (e) { toast(`Could not use the recording: ${e.message}`, "error"); }
    };
    rec.start(250);
    state.recorder = rec;
    mic.classList.add("recording");
    mic.setAttribute("aria-label", "Stop recording");
    clock.textContent = "0:00";
    clock.hidden = false;
  }

  // ------------------------------------------------------------------ settings
  async function loadSettings() {
    try {
      const [settings, status] = await Promise.all([api("/api/studio/settings"), api("/api/studio/status")]);
      state.settings = settings;
      state.status = status;
    } catch (e) { return toast(e.message, "error"); }
    const f = $("#settingsForm");
    const s = state.settings, d = s.defaults;
    f.system_prompt.value = d.system_prompt;
    f.max_new_tokens.value = d.max_new_tokens;
    f.temperature.value = d.temperature;
    f.top_p.value = d.top_p;
    f.context_length.value = d.context_length;
    f.keep_alive_minutes.value = s.keep_alive_minutes;
    f.models_dir.value = s.models_dir;
    f.models_dir.placeholder = s.models_dir_effective;
    f.delete_original.checked = s.delete_original;
    f.hf_token.value = "";
    $("#tokenState").replaceChildren(s.hf_token_set
      ? el("span", {}, "A token is saved. ", el("button", { type: "button", class: "btn small", text: "Remove token",
          onclick: () => saveSettings({ clear_hf_token: true }) }))
      : "No token saved. Public models work without one.");

    const hw = state.status.hardware || {};
    const dev = f.device;
    dev.replaceChildren(el("option", { value: "auto", text: "Automatic (GPU if available)" }),
      el("option", { value: "cpu", text: "CPU" }),
      ...(hw.gpus || []).map((g) => el("option", { value: `cuda:${g.index}`, text: `GPU ${g.index}: ${g.name}` })));
    dev.value = [...dev.options].some((o) => o.value === s.device) ? s.device : "auto";
    const comp = f.compression;
    comp.value = s.compression;
    const bnb = !!hw.bitsandbytes;
    for (const o of comp.options) o.disabled = !bnb && o.value !== "none";
    const help = [];
    if (hw.torch) help.push(`PyTorch ${hw.torch}${hw.cuda ? ` with CUDA ${hw.cuda}` : " (CPU build)"}.`);
    if (!(hw.gpus || []).length) help.push(hw.cuda
      ? "No NVIDIA GPU detected."
      : "To use an NVIDIA GPU, run “sudo airllm-enable-cuda” (Linux) or “airllm-enable-cuda” as Administrator (Windows), then restart AirLLM.");
    if (!bnb) help.push("Compression needs the bitsandbytes package, which is not installed.");
    help.push("Changes to hardware apply the next time a model loads.");
    $("#hardwareHelp").textContent = help.join(" ");

    const base = location.origin;
    $("#endpoints").replaceChildren(...[
      ["Ollama API", base],
      ["OpenAI base URL", base + "/v1"],
      ["CLI", "airllm run " + (state.model || "<model>")],
    ].map(([label, value]) => el("div", { class: "copy-row" }, el("span", { text: label }), el("code", { text: value }), copyButton(() => value, `Copy ${label}`))));

    const st = state.status;
    $("#about").replaceChildren(...[
      ["AirLLM Studio", st.version], ["AirLLM", st.airllm], ["Python", st.python],
      ["Data folder", st.data_dir], ["Models folder", st.models_dir],
      ["Free disk", fmtBytes(st.disk?.free || 0)],
    ].flatMap(([k, v]) => [el("dt", { text: k }), el("dd", { text: v })]));
  }

  async function saveSettings(patch) {
    const stateEl = $("#saveState");
    stateEl.textContent = "Saving…";
    try {
      await api("/api/studio/settings", { method: "PUT", body: patch });
      stateEl.textContent = "Saved";
      setTimeout(() => { if (stateEl.textContent === "Saved") stateEl.textContent = ""; }, 2500);
      await loadSettings();
      refreshModels();
    } catch (e) {
      stateEl.textContent = "";
      toast(e.message, "error");
    }
  }

  function settingsFromForm() {
    const f = $("#settingsForm");
    const num = (v, fallback) => (v === "" || isNaN(+v) ? fallback : +v);
    const d = state.settings.defaults;
    const patch = {
      device: f.device.value,
      compression: f.compression.value,
      keep_alive_minutes: num(f.keep_alive_minutes.value, state.settings.keep_alive_minutes),
      models_dir: f.models_dir.value.trim(),
      delete_original: f.delete_original.checked,
      defaults: {
        system_prompt: f.system_prompt.value,
        max_new_tokens: num(f.max_new_tokens.value, d.max_new_tokens),
        temperature: num(f.temperature.value, d.temperature),
        top_p: num(f.top_p.value, d.top_p),
        context_length: num(f.context_length.value, d.context_length),
      },
    };
    if (f.hf_token.value.trim()) patch.hf_token = f.hf_token.value.trim();
    return patch;
  }

  // ------------------------------------------------------------------ wiring
  function autosize() {
    const t = $("#prompt");
    t.style.height = "auto";
    t.style.height = Math.min(t.scrollHeight, window.innerHeight * 0.4) + "px";
  }

  function wire() {
    $("#newChat").addEventListener("click", () => newChat());
    $("#navModels").addEventListener("click", () => show("models"));
    $("#navSettings").addEventListener("click", () => show("settings"));
    $("#openSidebar").addEventListener("click", () => $("#app").classList.add("menu-open"));
    $$("[data-open-sidebar]").forEach((b) => b.addEventListener("click", () => $("#app").classList.add("menu-open")));
    $("#closeSidebar").addEventListener("click", () => $("#app").classList.remove("menu-open"));
    $("#modelSelect").addEventListener("change", (e) => selectModel(e.target.value));

    const prompt = $("#prompt");
    prompt.addEventListener("input", autosize);
    prompt.addEventListener("keydown", (e) => {
      if (e.key === "Enter" && !e.shiftKey && !e.isComposing) { e.preventDefault(); $("#composer").requestSubmit(); }
    });
    $("#composer").addEventListener("submit", (e) => {
      e.preventDefault();
      if (state.run) {
        if (runVisible()) state.abort.abort();
        else toast(`An answer is still being written in “${state.run.chat.title}”. Open that chat to stop it, or wait.`);
        return;
      }
      if (state.recorder) return toast("Stop the recording first (click the microphone).");
      const text = prompt.value.trim();
      if (!text && !state.attachments.length) return;
      prompt.value = "";
      autosize();
      send(text);
    });

    // images: button, paste, drag and drop (only offered for vision models)
    $("#attachBtn").addEventListener("click", () => $("#fileInput").click());
    $("#fileInput").addEventListener("change", (e) => { addImages(e.target.files); e.target.value = ""; });
    prompt.addEventListener("paste", (e) => {
      const files = [...(e.clipboardData?.files || [])];
      if (files.some((f) => f.type.startsWith("image/"))) { e.preventDefault(); addImages(files); }
    });
    const composer = $("#composer");
    composer.addEventListener("dragover", (e) => {
      if ([...(e.dataTransfer?.items || [])].some((i) => i.kind === "file")) { e.preventDefault(); composer.classList.add("dragover"); }
    });
    composer.addEventListener("dragleave", () => composer.classList.remove("dragover"));
    composer.addEventListener("drop", (e) => {
      composer.classList.remove("dragover");
      if (e.dataTransfer?.files?.length) { e.preventDefault(); addImages(e.dataTransfer.files); }
    });
    $("#micBtn").addEventListener("click", toggleRecording);

    // projects
    $("#projectCrumb").addEventListener("click", () => {
      const pid = state.chat ? state.chat.project_id : state.newChatProject;
      if (pid) openProject(pid);
    });
    $("#projectNewChat").addEventListener("click", () => newChat(state.project?.id));
    const nameInput = $("#projectName");
    nameInput.addEventListener("keydown", (e) => { if (e.key === "Enter") nameInput.blur(); if (e.key === "Escape") { nameInput.value = state.project?.name || ""; nameInput.blur(); } });
    nameInput.addEventListener("change", () => {
      const name = nameInput.value.trim();
      if (!state.project) return;
      if (!name) { nameInput.value = state.project.name; return; }
      if (name !== state.project.name) saveProject({ name }, true);
    });
    $("#saveInstructions").addEventListener("click", async () => {
      if (!state.project) return;
      $("#instructionsState").textContent = "Saving…";
      const ok = await saveProject({ instructions: $("#projectInstructions").value }, true);
      $("#instructionsState").textContent = ok ? "Saved" : "";
      if (ok) setTimeout(() => { if ($("#instructionsState").textContent === "Saved") $("#instructionsState").textContent = ""; }, 2500);
    });
    $("#projectModel").addEventListener("change", (e) => saveProject({ model: e.target.value }, true));
    const drop = $("#dropzone");
    drop.addEventListener("click", () => $("#projectFileInput").click());
    drop.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); $("#projectFileInput").click(); } });
    drop.addEventListener("dragover", (e) => { e.preventDefault(); drop.classList.add("over"); });
    drop.addEventListener("dragleave", () => drop.classList.remove("over"));
    drop.addEventListener("drop", (e) => { e.preventDefault(); drop.classList.remove("over"); uploadProjectFiles([...(e.dataTransfer?.files || [])]); });
    $("#projectFileInput").addEventListener("change", (e) => { uploadProjectFiles([...e.target.files]); e.target.value = ""; });
    document.addEventListener("click", (e) => {
      if (openMenu && !openMenu.contains(e.target) && !e.target.closest('[aria-haspopup="menu"]')) closeMenu();
    });
    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape" && openMenu) { closeMenu(); return; }
      if (e.key === "Escape" && runVisible()) state.abort.abort();
      if ((e.ctrlKey || e.metaKey) && e.shiftKey && e.key.toLowerCase() === "o") { e.preventDefault(); newChat(); }
    });

    $("#pullForm").addEventListener("submit", (e) => {
      e.preventDefault();
      const name = $("#pullInput").value.trim();
      if (!name) return;
      if (!/^[\w.-]+\/[\w.-]+$/.test(name) && !/^([a-zA-Z]:)?[\\/~.]/.test(name)) {
        renderDiscover();
        return toast("Pick a model from the results, or paste a full id like Qwen/Qwen3-8B.");
      }
      pull(name);
      $("#pullInput").value = "";
    });
    $("#pullInput").addEventListener("input", () => {
      clearTimeout(searchTimer);
      searchTimer = setTimeout(renderDiscover, 450);
    });

    $("#settingsForm").addEventListener("submit", (e) => { e.preventDefault(); saveSettings(settingsFromForm()); });
    $$("[data-open]").forEach((b) => b.addEventListener("click", () =>
      api("/api/studio/open-folder", { method: "POST", body: { what: b.dataset.open } }).catch((e) => toast(e.message, "error"))));
    $("#quitBtn").addEventListener("click", async () => {
      const btn = $("#quitBtn");
      if (btn.dataset.armed !== "1") {
        btn.dataset.armed = "1";
        btn.textContent = "Click again to quit";
        setTimeout(() => { btn.dataset.armed = ""; btn.textContent = "Quit AirLLM"; }, 4000);
        return;
      }
      await api("/api/shutdown", { method: "POST" }).catch(() => {});
      document.body.replaceChildren(el("div", { class: "empty" }, el("img", { src: "icon.svg", alt: "" }),
        el("h2", { text: "AirLLM has stopped" }), el("p", { text: "You can close this window." })));
    });
  }

  async function boot() {
    wire();
    renderThread();
    await Promise.all([refreshStatus(), refreshModels(), refreshChats(), refreshProjects(),
      api("/api/studio/settings").then((st) => { state.settings = st; }).catch(() => {})]);
    renderThread();
    const id = location.hash.slice(1);
    if (id && state.chats.some((c) => c.id === id)) openChat(id);
    if (state.models.some((m) => m.job && !m.job.done)) pollModelsSoon();
    setInterval(() => {
      const wasOnline = state.online;
      refreshStatus().then(() => {
        if (!wasOnline && state.online) { refreshModels(); refreshChats(); refreshProjects(); }
        if (state.view === "chat" && (!state.chat || !state.chat.messages.length)) renderThread();
      });
    }, 4000);
    $("#prompt").focus();
  }

  boot();
})();
