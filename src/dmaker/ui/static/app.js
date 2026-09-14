"use strict";
/*
 * DMaker - interface gráfica (frontend estático, sem framework).
 *
 * As listas de opções e enums (espelhando src/dmaker/domain/spec.py) ficam em options.js,
 * compartilhadas com filters.js.
 *
 * Organização deste arquivo:
 *   2. estado da aplicação
 *   3. utilidades puras (prune, get/set por caminho, redistribuição de palavras)
 *   4. cliente da API
 *   5. alerta, modal e navegador de arquivos
 *   6. lateral: projetos, jobs, saídas
 *   7. barra superior e painel de andamento (SSE)
 *   8. aba Editor (formulário) por bloco
 *   9. aba JSON
 *   10. aba Preview
 *   11. aba Legendas
 *   12. inicialização
 */

/* ==================== 2. estado ==================== */

const state = {
  stateInfo: null,
  projects: [],
  currentProject: null,
  spec: null,
  captionsExists: false,
  projectOutputs: [],
  outputs: [],
  jobs: [],
  activeJobId: {},
  eventSource: null,
  previewOutput: null,
  captionsData: null,
  activeTab: "editor",
  syncResults: null,
};

const newProjectState = { name: "", preset: "", brand: "", sources: [], captions: true, logo: false };
const browseState = { path: "", multi: false, selected: [], onSelect: null };

/* ==================== 3. utilidades puras ==================== */

function escHtml(value) {
  return String(value).replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
}
const escAttr = escHtml;

function isIndexKey(part) {
  return part !== "" && !Number.isNaN(Number(part));
}

function getPath(obj, path) {
  let cur = obj;
  for (const part of path.split(".")) {
    if (cur === null || cur === undefined) return undefined;
    cur = cur[isIndexKey(part) ? Number(part) : part];
  }
  return cur;
}

/** Escreve `value` em `obj` seguindo um caminho tipo "timeline.0.reframe.focus.0".
 * Cria objetos/arrays intermediários conforme necessário; value === undefined remove a chave. */
function setPath(obj, path, value) {
  const parts = path.split(".");
  let cur = obj;
  for (let i = 0; i < parts.length - 1; i++) {
    const key = isIndexKey(parts[i]) ? Number(parts[i]) : parts[i];
    if (cur[key] === null || cur[key] === undefined) {
      cur[key] = isIndexKey(parts[i + 1]) ? [] : {};
    }
    cur = cur[key];
  }
  const lastKey = isIndexKey(parts[parts.length - 1]) ? Number(parts[parts.length - 1]) : parts[parts.length - 1];
  if (value === undefined) {
    if (Array.isArray(cur)) cur[lastKey] = undefined;
    else delete cur[lastKey];
  } else {
    cur[lastKey] = value;
  }
}

/** Remove chaves vazias (undefined/null/"") e objetos que ficam vazios após a limpeza.
 * Arrays são preservados mesmo vazios (ex.: overlays: []). Não é destrutivo. */
function pruneEmpty(value) {
  if (Array.isArray(value)) {
    return value.map(pruneEmpty);
  }
  if (value !== null && typeof value === "object") {
    const out = {};
    for (const [key, raw] of Object.entries(value)) {
      if (raw === undefined || raw === null || raw === "") continue;
      const cleaned = pruneEmpty(raw);
      if (cleaned !== null && typeof cleaned === "object" && !Array.isArray(cleaned) && Object.keys(cleaned).length === 0) {
        continue;
      }
      out[key] = cleaned;
    }
    return out;
  }
  return value;
}

/** Reparte o tempo de uma cue de legenda entre as palavras de um novo texto,
 * mantendo o início/fim da cue. Se a quantidade de palavras não mudar, só troca os textos;
 * senão distribui a duração proporcionalmente ao tamanho de cada palavra. Função pura. */
function redistributeWords(cue, newText) {
  const tokens = newText.trim().split(/\s+/).filter(Boolean);
  const words = cue.words || [];
  if (tokens.length === 0) return [];
  if (words.length === tokens.length) {
    return tokens.map((text, i) => ({ start: words[i].start, end: words[i].end, text }));
  }
  const start = words.length ? words[0].start : cue.start;
  const end = words.length ? words[words.length - 1].end : cue.end;
  const totalDuration = Math.max(end - start, 0.001);
  const totalChars = tokens.reduce((sum, t) => sum + t.length, 0) || tokens.length;
  let cursor = start;
  return tokens.map((text) => {
    const share = totalChars ? (text.length / totalChars) * totalDuration : totalDuration / tokens.length;
    const wordStart = cursor;
    const wordEnd = Math.min(cursor + share, end);
    cursor = wordEnd;
    return { start: wordStart, end: wordEnd, text };
  });
}

function formatTime(seconds) {
  const s = Math.max(0, seconds || 0);
  const m = Math.floor(s / 60);
  const rest = (s % 60).toFixed(2).padStart(5, "0");
  return `${String(m).padStart(2, "0")}:${rest}`;
}

function fileExt(path) {
  const match = /\.[a-z0-9]+$/i.exec(path || "");
  return match ? match[0].toLowerCase() : "";
}

function baseName(path) {
  return (path || "").split(/[\\/]/).pop();
}

/* ==================== 4. cliente da API ==================== */

class ApiError extends Error {
  constructor(status, data) {
    super(formatApiError(data));
    this.status = status;
    this.data = data;
  }
}

function formatApiError(data) {
  if (!data) return "Erro desconhecido";
  const detail = typeof data === "object" && "detail" in data ? data.detail : data;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) return detail.map((d) => `${d.loc}: ${d.msg}`).join("; ");
  return JSON.stringify(detail);
}

async function apiRequest(method, path, body) {
  const opts = { method, headers: {} };
  if (body !== undefined) {
    opts.headers["Content-Type"] = "application/json";
    opts.body = JSON.stringify(body);
  }
  const resp = await fetch(path, opts);
  const text = await resp.text();
  let data = null;
  if (text) {
    try { data = JSON.parse(text); } catch { data = text; }
  }
  if (!resp.ok) throw new ApiError(resp.status, data);
  return data;
}

const api = {
  get: (path) => apiRequest("GET", path),
  post: (path, body) => apiRequest("POST", path, body ?? {}),
  put: (path, body) => apiRequest("PUT", path, body ?? {}),
};

function handleError(err) {
  console.error(err);
  showAlert(err && err.message ? err.message : "Erro inesperado", "error");
}

/** Executa `fn` desabilitando/mostrando carregamento no botão; devolve {ok, value|error}. */
async function runAction(button, fn) {
  button.disabled = true;
  button.classList.add("loading");
  try {
    const value = await fn();
    return { ok: true, value };
  } catch (err) {
    handleError(err);
    return { ok: false, error: err };
  } finally {
    button.disabled = false;
    button.classList.remove("loading");
  }
}

/* ==================== 5. alerta, modal, navegador de arquivos ==================== */

let alertTimer = null;
function showAlert(message, kind) {
  const bar = document.getElementById("alert-bar");
  document.getElementById("alert-text").textContent = message;
  bar.classList.toggle("success", kind === "success");
  bar.hidden = false;
  clearTimeout(alertTimer);
  if (kind === "success") {
    alertTimer = setTimeout(() => { bar.hidden = true; }, 3000);
  }
}

function openModal(html) {
  document.getElementById("modal-box").innerHTML = html;
  document.getElementById("modal-overlay").hidden = false;
}

function closeModal() {
  document.getElementById("modal-overlay").hidden = true;
  document.getElementById("modal-box").innerHTML = "";
}

function openFileBrowser({ multi = false, onSelect }) {
  browseState.path = "";
  browseState.multi = multi;
  browseState.selected = [];
  browseState.onSelect = onSelect;
  openModal(fileBrowserHtml());
  loadBrowsePath("");
}

function fileBrowserHtml() {
  return `
    <h3>Escolher arquivo${browseState.multi ? "s" : ""}</h3>
    <div class="file-browser-path" id="browse-path">Carregando...</div>
    <div class="file-browser-list" id="browse-list"></div>
    <div class="modal-actions">
      <button type="button" class="btn" id="browse-cancel">Cancelar</button>
      ${browseState.multi ? '<button type="button" class="btn btn-accent" id="browse-confirm">Selecionar</button>' : ""}
    </div>`;
}

async function loadBrowsePath(path) {
  try {
    const query = path ? `?path=${encodeURIComponent(path)}` : "";
    const data = await api.get(`/api/browse${query}`);
    browseState.path = data.path;
    const pathLabel = document.getElementById("browse-path");
    if (pathLabel) pathLabel.textContent = data.path || "Discos";
    const rows = [];
    if (data.parent !== null && data.parent !== undefined) {
      rows.push(`<div class="file-browser-row" data-browse-dir="${escAttr(data.parent)}"><span class="file-browser-icon">..</span><span>Voltar</span></div>`);
    }
    for (const dir of data.dirs) {
      const label = dir.split("/").filter(Boolean).pop() || dir;
      rows.push(`<div class="file-browser-row" data-browse-dir="${escAttr(dir)}"><span class="file-browser-icon">Pasta</span><span>${escHtml(label)}</span></div>`);
    }
    for (const file of data.files) {
      const checked = browseState.selected.includes(file.path);
      rows.push(`
        <div class="file-browser-row ${checked ? "selected" : ""}" data-browse-file="${escAttr(file.path)}">
          ${browseState.multi ? `<input type="checkbox" ${checked ? "checked" : ""}>` : '<span class="file-browser-icon">Arq.</span>'}
          <span>${escHtml(file.name)}</span>
          <span class="file-browser-size">${file.size_mb} MB</span>
        </div>`);
    }
    const list = document.getElementById("browse-list");
    if (list) list.innerHTML = rows.join("") || '<div class="file-browser-row">Pasta vazia</div>';
  } catch (err) {
    handleError(err);
  }
}

function onModalClick(e) {
  const dirRow = e.target.closest("[data-browse-dir]");
  if (dirRow) { loadBrowsePath(dirRow.dataset.browseDir); return; }

  const fileRow = e.target.closest("[data-browse-file]");
  if (fileRow) {
    const path = fileRow.dataset.browseFile;
    if (browseState.multi) {
      const idx = browseState.selected.indexOf(path);
      if (idx >= 0) browseState.selected.splice(idx, 1); else browseState.selected.push(path);
      loadBrowsePath(browseState.path);
    } else if (browseState.onSelect) {
      browseState.onSelect([path]);
    }
    return;
  }

  if (e.target.id === "browse-cancel") { closeModal(); return; }
  if (e.target.id === "browse-confirm") { browseState.onSelect(browseState.selected.slice()); return; }

  if (e.target.id === "np-cancel") { closeModal(); return; }
  if (e.target.id === "np-choose-sources") { chooseNewProjectSources(); return; }
  if (e.target.matches("[data-remove-source]")) {
    newProjectState.sources.splice(Number(e.target.dataset.removeSource), 1);
    renderNewProjectTags();
    return;
  }
  if (e.target.id === "np-submit") { submitNewProject(); return; }

  if (e.target.id === "export-cancel") { closeModal(); return; }
  if (e.target.id === "export-submit") { submitExportFromModal(); return; }
}

document.getElementById("modal-overlay").addEventListener("click", (e) => {
  if (e.target.id === "modal-overlay") closeModal();
});

/* ==================== 6. lateral: projetos, jobs, saídas ==================== */

async function refreshProjectList() {
  state.projects = await api.get("/api/projects");
  renderProjectList();
}

function renderProjectList() {
  const ul = document.getElementById("project-list");
  if (!state.projects.length) {
    ul.innerHTML = '<li class="empty-hint">Nenhum projeto ainda</li>';
    return;
  }
  ul.innerHTML = state.projects.map((p) => `
    <li class="project-item ${p.name === state.currentProject ? "active" : ""}" data-project="${escAttr(p.name)}">
      <div class="project-item-name">${escHtml(p.name)}</div>
      <div class="project-item-meta">${escHtml(p.preset || "?")}${p.brand ? " · " + escHtml(p.brand) : ""} · ${p.segments ?? 0} trechos</div>
    </li>`).join("");
}

function statusLabel(status) {
  return { running: "Em andamento", done: "Concluído", error: "Erro" }[status] || status;
}

let jobsPollTimer = null;
const seenJobIds = new Set();
let jobsSeeded = false;

/** Sondagem de /api/jobs continua sempre rodando (mais devagar sem job ativo), para captar renders
 * disparados por fora da interface (CLI, MCP) mesmo com a página já aberta. */
async function refreshJobs() {
  state.jobs = await api.get("/api/jobs");
  renderJobList();
  if (!jobsSeeded) {
    state.jobs.forEach((j) => seenJobIds.add(j.job_id));
    jobsSeeded = true;
  } else {
    await focusNewJobs();
  }
  const running = state.jobs.some((j) => j.status === "running");
  clearTimeout(jobsPollTimer);
  jobsPollTimer = setTimeout(() => { refreshJobs().catch(handleError); }, running ? 3000 : 5000);
}

/** Abre sozinho o projeto/painel de um job novo marcado com focus (render disparado pela CLI/MCP). */
async function focusNewJobs() {
  const fresh = state.jobs.filter((j) => j.focus && j.project && !seenJobIds.has(j.job_id));
  state.jobs.forEach((j) => seenJobIds.add(j.job_id));
  const target = fresh.find((j) => j.status === "running") || fresh[fresh.length - 1];
  if (!target || state.activeJobId[target.project] === target.job_id) return;
  try {
    if (target.project !== state.currentProject) await openProject(target.project);
    openJobEvents(target.project, target.job_id, "render");
  } catch (err) {
    handleError(err);
  }
}

function renderJobList() {
  const ul = document.getElementById("job-list");
  if (!state.jobs.length) {
    ul.innerHTML = '<li class="empty-hint">Nenhum job ainda</li>';
    return;
  }
  ul.innerHTML = state.jobs.slice().reverse().map((j) => `
    <li class="job-item">
      <div class="job-item-desc">${escHtml(j.description)}<span class="job-status job-status-${j.status}">${statusLabel(j.status)}</span></div>
      ${j.progress && j.progress.total ? `
        <div class="mini-bar-track"><div class="mini-bar-fill" style="width:${j.progress.percent || 0}%"></div></div>
        <div class="project-item-meta">${escHtml(j.progress.label || "")} ${j.progress.percent ?? 0}%</div>` : ""}
      ${j.error ? `<div class="project-item-meta" style="color:var(--danger)">${escHtml(j.error.split("\n")[0])}</div>` : ""}
    </li>`).join("");
}

async function refreshOutputsGlobal() {
  state.outputs = await api.get("/api/outputs");
  renderOutputList();
}

function renderOutputList() {
  const ul = document.getElementById("output-list");
  if (!state.outputs.length) {
    ul.innerHTML = '<li class="empty-hint">Nenhuma saída ainda</li>';
    return;
  }
  ul.innerHTML = state.outputs.map((o, idx) => `
    <li class="output-item" data-output-index="${idx}">
      ${o.thumbnail ? `<img class="output-thumb" src="${o.thumbnail}" alt="">` : '<div class="output-thumb"></div>'}
      <div class="output-info">
        <div class="output-name">${escHtml(o.name)}</div>
        <div class="output-meta">${escHtml(o.preset || "?")} · ${o.kind === "preview" ? "preview" : "final"} · ${o.size_mb} MB</div>
      </div>
    </li>`).join("");
}

document.getElementById("project-list").addEventListener("click", async (e) => {
  const item = e.target.closest("[data-project]");
  if (!item) return;
  try { await openProject(item.dataset.project); } catch (err) { handleError(err); }
});

document.getElementById("output-list").addEventListener("click", (e) => {
  const item = e.target.closest("[data-output-index]");
  if (!item) return;
  const output = state.outputs[Number(item.dataset.outputIndex)];
  if (output) { loadOutputIntoPreview(output); switchTab("preview"); }
});

/* ==================== 7. barra superior e andamento (SSE) ==================== */

function setTopbarEnabled(enabled) {
  ["btn-save", "btn-validate", "btn-preview", "btn-render", "btn-export"].forEach((id) => {
    document.getElementById(id).disabled = !enabled;
  });
}

async function saveProject() {
  const btn = document.getElementById("btn-save");
  const payload = pruneEmpty(state.spec);
  const result = await runAction(btn, () => api.put(`/api/projects/${encodeURIComponent(state.currentProject)}`, payload));
  if (result.ok) {
    showAlert("Projeto salvo.", "success");
    refreshProjectList().catch(() => {});
    if (window.DMakerEditor) DMakerEditor.markSaved();
  }
  return result.ok;
}

async function validateProject() {
  const ok = await saveProject();
  if (!ok) return;
  const btn = document.getElementById("btn-validate");
  const result = await runAction(btn, () => api.post(`/api/projects/${encodeURIComponent(state.currentProject)}/validate`));
  if (result.ok) renderValidateBanner(result.value);
}

function renderValidateBanner(summary) {
  const el = document.getElementById("validate-banner");
  el.hidden = false;
  const warnings = summary.warnings.length
    ? `<div class="validate-warnings">${summary.warnings.map((w) => escHtml(w)).join("<br>")}</div>` : "";
  const segments = summary.segments
    .map((s) => `#${s.index + 1} ${escHtml(s.type)} (${s.duration_s}s)${s.label ? " - " + escHtml(s.label) : ""}`)
    .join(" | ");
  el.innerHTML = `
    <div class="validate-summary">
      <span>Duração total: <b>${summary.total_s}s</b></span>
      <span>Resolução: <b>${escHtml(summary.resolution)}</b></span>
      <span>Preset: <b>${escHtml(summary.preset)}</b></span>
    </div>
    <div class="validate-segments">${segments}</div>
    ${warnings}`;
}

/** Lê o campo "Só os trechos" do Preview: null se vazio, "de-ate" se preenchido.
 * Lança erro se só um dos dois números foi informado. */
function readPreviewSegmentsField() {
  const from = document.getElementById("preview-segment-from").value.trim();
  const to = document.getElementById("preview-segment-to").value.trim();
  if (from === "" && to === "") return null;
  if (from === "" || to === "") {
    throw new Error("Preencha os dois campos de trechos (de e até) ou deixe ambos vazios.");
  }
  return `${from}-${to}`;
}

async function startRender(preview) {
  let segments = null;
  if (preview) {
    try { segments = readPreviewSegmentsField(); } catch (err) { handleError(err); return; }
  }
  const ok = await saveProject();
  if (!ok) return;
  const btn = document.getElementById(preview ? "btn-preview" : "btn-render");
  const body = segments ? { preview, segments } : { preview };
  const result = await runAction(btn, () => api.post(`/api/projects/${encodeURIComponent(state.currentProject)}/render`, body));
  if (result.ok) openJobEvents(state.currentProject, result.value.job_id, "render");
}

async function submitExport(presets) {
  const btn = document.getElementById("btn-export");
  const result = await runAction(btn, () => api.post(`/api/projects/${encodeURIComponent(state.currentProject)}/export`, { presets }));
  if (result.ok) openJobEvents(state.currentProject, result.value.job_id, "export");
}

function openExportModal() {
  const options = (state.stateInfo?.presets || []).map((p) => `
    <label class="export-preset-row"><input type="checkbox" value="${escAttr(p.id)}"> ${escHtml(p.platform)} - ${escHtml(p.name)} (${p.id})</label>`).join("");
  openModal(`
    <h3>Exportar em vários presets</h3>
    <div class="export-preset-list" id="export-preset-list">${options}</div>
    <div class="modal-actions">
      <button type="button" class="btn" id="export-cancel">Cancelar</button>
      <button type="button" class="btn btn-accent" id="export-submit">Exportar</button>
    </div>`);
}

async function submitExportFromModal() {
  const checked = Array.from(document.querySelectorAll("#export-preset-list input:checked")).map((el) => el.value);
  if (!checked.length) { showAlert("Escolha ao menos um preset.", "error"); return; }
  const ok = await saveProject();
  closeModal();
  if (!ok) return;
  await submitExport(checked);
}

/* -- painel de andamento (SSE) -- */

let progressState = window.DMakerProgress.initialState();
let progressTicker = null;

function showProgressPanel() {
  document.getElementById("progress-panel").classList.remove("collapsed");
}

function stopProgressTicker() {
  if (progressTicker) {
    clearInterval(progressTicker);
    progressTicker = null;
  }
}

function renderProgressSteps() {
  document.getElementById("progress-steps").innerHTML = window.DMakerProgress.stepsHtml(progressState);
  document.getElementById("progress-elapsed").textContent = window.DMakerProgress.elapsedLabel(progressState, Date.now());
}

function resetProgressPanel() {
  document.getElementById("progress-log").innerHTML = "";
  document.getElementById("progress-bar-fill").style.width = "0%";
  document.getElementById("progress-bar-label").textContent = "";
  document.getElementById("progress-status").textContent = "Em andamento";
  progressState = window.DMakerProgress.initialState();
  renderProgressSteps();
  stopProgressTicker();
  progressTicker = setInterval(renderProgressSteps, 1000);
}

function appendLog(message, isError) {
  const log = document.getElementById("progress-log");
  const line = document.createElement("div");
  if (isError) line.className = "log-error";
  line.textContent = message;
  log.appendChild(line);
  log.scrollTop = log.scrollHeight;
}

function updateProgressBar(label, percent) {
  document.getElementById("progress-bar-fill").style.width = `${percent}%`;
  document.getElementById("progress-bar-label").textContent = `${label || ""} ${percent}%`;
}

function openJobEvents(projectName, jobId, kind) {
  state.activeJobId[projectName] = jobId;
  seenJobIds.add(jobId);
  if (state.eventSource) state.eventSource.close();
  showProgressPanel();
  resetProgressPanel();
  const source = new EventSource(`/api/jobs/${jobId}/events`);
  state.eventSource = source;
  source.onmessage = (evt) => {
    let data;
    try { data = JSON.parse(evt.data); } catch { return; }
    handleJobEvent(data, projectName, kind);
    if (data.kind === "end") {
      source.close();
      refreshJobs().catch(() => {});
    }
  };
  refreshJobs().catch(() => {});
}

function handleJobEvent(evt, projectName, kind) {
  progressState = window.DMakerProgress.nextState(progressState, evt);
  renderProgressSteps();
  if (evt.kind === "start") {
    appendLog(`Iniciado: ${evt.description || ""}`);
  } else if (evt.kind === "log") {
    appendLog(evt.message);
  } else if (evt.kind === "progress") {
    updateProgressBar(evt.label, evt.percent ?? 0);
  } else if (evt.kind === "end") {
    stopProgressTicker();
    document.getElementById("progress-status").textContent = evt.status === "done" ? "Concluído" : "Erro";
    if (evt.status === "done") {
      appendLog("Concluído.");
      handleRenderDone(evt.result, projectName, kind).catch(handleError);
    } else {
      appendLog(evt.error || "Erro desconhecido", true);
    }
  }
}

async function handleRenderDone(result, projectName, kind) {
  await refreshOutputsGlobal();
  if (projectName !== state.currentProject) return;
  const data = await api.get(`/api/projects/${encodeURIComponent(projectName)}`);
  state.projectOutputs = data.outputs;
  state.captionsExists = data.captions_exists;
  updateCaptionsTabVisibility();
  if (kind === "render" && result && result.output_url) {
    loadOutputIntoPreview({
      path: result.output,
      url: result.output_url,
      size_mb: result.size_mb,
      preset: result.preset,
      name: baseName(result.output),
    });
    switchTab("preview");
  } else if (data.outputs.length) {
    loadOutputIntoPreview(data.outputs[0]);
  }
}

document.getElementById("btn-save").addEventListener("click", () => saveProject());
document.getElementById("btn-validate").addEventListener("click", () => validateProject());
document.getElementById("btn-preview").addEventListener("click", () => startRender(true));
document.getElementById("btn-render").addEventListener("click", () => startRender(false));
document.getElementById("btn-export").addEventListener("click", () => openExportModal());
document.getElementById("progress-toggle").addEventListener("click", () => {
  document.getElementById("progress-panel").classList.toggle("collapsed");
});
document.getElementById("alert-close").addEventListener("click", () => {
  document.getElementById("alert-bar").hidden = true;
});
document.addEventListener("keydown", (e) => {
  if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "s") {
    e.preventDefault();
    if (state.currentProject && !document.getElementById("btn-save").disabled) saveProject();
  }
});

/* ==================== 8. aba Editor ==================== */

function normalizeSpec(spec) {
  spec.output = spec.output || {};
  spec.audio = spec.audio || {};
  spec.overlays = spec.overlays || [];
  spec.timeline = spec.timeline || [];
  spec.sources = spec.sources || {};
  return spec;
}

function renderEditorForm() {
  document.getElementById("editor-empty").hidden = true;
  document.getElementById("editor-form").hidden = false;
  renderOutputFields();
  renderSourcesBlock();
  renderTimelineCards();
  renderOverlayCards();
  renderCaptionsSettingsFields();
  renderAudioFields();
}

/* -- construtores de campo genéricos -- */

function textField(path, label, value) {
  return `<div class="field"><label>${escHtml(label)}</label><input type="text" data-path="${path}" data-kind="string" value="${escAttr(value ?? "")}"></div>`;
}

function numField(path, label, value, opts = {}) {
  const attrs = [];
  if (opts.step !== undefined) attrs.push(`step="${opts.step}"`);
  if (opts.min !== undefined) attrs.push(`min="${opts.min}"`);
  if (opts.max !== undefined) attrs.push(`max="${opts.max}"`);
  const shown = value === undefined || value === null ? "" : value;
  return `<div class="field"><label>${escHtml(label)}</label><input type="number" data-path="${path}" data-kind="number" value="${shown}" ${attrs.join(" ")}></div>`;
}

function checkField(path, label, checked) {
  return `<div class="field field-checkbox"><input type="checkbox" data-path="${path}" data-kind="boolean" ${checked ? "checked" : ""}><label>${escHtml(label)}</label></div>`;
}

function selectField(path, label, value, options, extraClass) {
  const opts = options.map((o) => `<option value="${escAttr(o.value)}" ${String(value ?? "") === String(o.value) ? "selected" : ""}>${escHtml(o.label)}</option>`).join("");
  return `<div class="field"><label>${escHtml(label)}</label><select class="${extraClass || ""}" data-path="${path}" data-kind="string">${opts}</select></div>`;
}

function srcField(path, label, value, browseKind) {
  return `<div class="field"><label>${escHtml(label)}</label><div class="field-src"><input type="text" data-path="${path}" data-kind="string" value="${escAttr(value ?? "")}"><button type="button" class="btn btn-small" data-browse-path="${path}" data-browse-kind="${browseKind}">Escolher...</button></div></div>`;
}

function mediaThumbHtml(src, kind) {
  if (!src) return "";
  const url = `/api/file?path=${encodeURIComponent(src)}`;
  if (kind === "video") return `<video class="seg-thumb" src="${url}" preload="metadata" muted></video>`;
  if (kind === "image") return `<img class="seg-thumb" src="${url}" alt="">`;
  return "";
}

function sourceNames() {
  return Object.keys(state.spec.sources || {});
}

/** Campo de origem que alterna entre arquivo avulso (`src`) e fonte sincronizada (`source`);
 * a spec exige exatamente um dos dois, então trocar a seleção limpa o outro campo. */
function originFieldHtml(prefix, current, browseKind, sourceHint) {
  const usesSource = !!current.source;
  const options = [`<option value="">Arquivo avulso</option>`].concat(
    sourceNames().map((name) => `<option value="${escAttr(name)}" ${usesSource && current.source === name ? "selected" : ""}>${escHtml(name)}</option>`)
  ).join("");
  const srcRow = `
    <div class="field field-src" data-origin-src-row ${usesSource ? "hidden" : ""}>
      <label>Arquivo</label>
      <div class="field-src">
        <input type="text" data-path="${escAttr(prefix)}.src" data-kind="string" value="${escAttr(usesSource ? "" : (current.src ?? ""))}">
        <button type="button" class="btn btn-small" data-browse-path="${escAttr(prefix)}.src" data-browse-kind="${browseKind}">Escolher...</button>
      </div>
    </div>`;
  const hint = usesSource ? `<div class="hint-text" style="grid-column:1/-1">${escHtml(sourceHint)}</div>` : "";
  return `
    <div class="field">
      <label>Origem</label>
      <select data-origin-toggle="${escAttr(prefix)}">${options}</select>
    </div>${srcRow}${hint}`;
}

function handleOriginToggle(el) {
  const prefix = el.dataset.originToggle;
  const value = el.value;
  if (value) {
    setPath(state.spec, `${prefix}.source`, value);
    setPath(state.spec, `${prefix}.src`, undefined);
  } else {
    setPath(state.spec, `${prefix}.source`, undefined);
  }
  syncJsonFromSpec();
  refreshEditorBlockForPath(prefix);
}

/* -- bloco Saída -- */

function renderOutputFields() {
  const o = state.spec.output || {};
  const presetOptions = (state.stateInfo?.presets || []).map((p) => ({ value: p.id, label: `${p.platform} · ${p.name} (${p.id})` }));
  const brandOptions = [{ value: "", label: "Nenhuma" }].concat((state.stateInfo?.brands || []).map((b) => ({ value: b.key, label: b.name })));
  const html = [
    selectField("output.preset", "Preset", o.preset ?? "instagram/reels", presetOptions),
    selectField("output.quality", "Qualidade", o.quality ?? "high", QUALITY_OPTIONS),
    selectField("output.encoder", "Encoder", o.encoder ?? "x264", ENCODER_OPTIONS),
    numField("output.fps", "FPS (opcional)", o.fps, { min: 1, max: 120, step: 1 }),
    selectField("brand", "Marca", state.spec.brand ?? "", brandOptions),
    checkField("output.guides", "Mostrar guias de zona segura", !!o.guides),
  ].join("");
  document.getElementById("output-fields").innerHTML = html;
}

/* -- bloco Fontes sincronizadas -- */

function renderSourcesBlock() {
  const sources = state.spec.sources || {};
  const names = Object.keys(sources);
  document.getElementById("sources-rows").innerHTML =
    names.map((name) => sourceRowHtml(name, sources[name])).join("") ||
    '<p class="empty-hint">Nenhuma fonte sincronizada ainda.</p>';
  const masterOptions = [{ value: "", label: names.length ? `Automática (${names[0]})` : "Nenhuma fonte" }].concat(
    names.map((n) => ({ value: n, label: n }))
  );
  document.getElementById("sources-master-field").innerHTML = selectField(
    "master", "Fonte principal (relógio)", state.spec.master ?? "", masterOptions
  );
  renderSyncResults();
}

function sourceRowHtml(name, src) {
  const mode = src.sync === "auto" ? "auto" : "manual";
  const syncField = mode === "manual"
    ? numField(`sources.${name}.sync`, "Deslocamento (s)", typeof src.sync === "number" ? src.sync : 0, { step: 0.01 })
    : "";
  const thumb = mediaThumbHtml(src.src, "video");
  return `
    <div class="source-row" data-source-name="${escAttr(name)}">
      <div class="form-grid">
        <div class="field">
          <label>Nome</label>
          <input type="text" value="${escAttr(name)}" data-source-rename="${escAttr(name)}">
        </div>
        <div class="field field-src">
          <label>Arquivo</label>
          <div class="field-src">
            <input type="text" data-path="${escAttr(`sources.${name}.src`)}" data-kind="string" value="${escAttr(src.src ?? "")}">
            <button type="button" class="btn btn-small" data-browse-path="${escAttr(`sources.${name}.src`)}" data-browse-kind="video">Escolher...</button>
          </div>
        </div>
        <div class="field">
          <label>Sincronização</label>
          <select data-sync-mode-toggle="${escAttr(name)}">
            ${SYNC_MODE_OPTIONS.map((o) => `<option value="${o.value}" ${mode === o.value ? "selected" : ""}>${o.label}</option>`).join("")}
          </select>
        </div>
        ${syncField}
        ${numField(`sources.${name}.audio_stream`, "Faixa de áudio", src.audio_stream ?? 0, { step: 1, min: 0 })}
        ${textField(`sources.${name}.label`, "Rótulo (opcional)", src.label ?? "")}
      </div>
      ${thumb ? `<div class="seg-thumb-row">${thumb}</div>` : ""}
      <div class="source-row-actions">
        <button type="button" class="icon-btn" data-source-remove="${escAttr(name)}" title="Remover">&times;</button>
      </div>
    </div>`;
}

function addSourceRow() {
  const sources = state.spec.sources || (state.spec.sources = {});
  let i = 1;
  while (sources[`fonte${i}`] !== undefined) i++;
  sources[`fonte${i}`] = { src: "", sync: "auto", audio_stream: 0 };
  renderSourcesBlock();
  syncJsonFromSpec();
}

function removeSourceRow(name) {
  const sources = state.spec.sources || {};
  delete sources[name];
  if (state.spec.master === name) state.spec.master = undefined;
  updateSourceReferences(name, undefined);
  renderSourcesBlock();
  renderTimelineCards();
  renderOverlayCards();
  renderAudioFields();
  syncJsonFromSpec();
}

function renameSource(oldName, rawName) {
  const newName = rawName.trim().replace(/\s+/g, "-");
  if (!newName || newName === oldName) { renderSourcesBlock(); return; }
  const sources = state.spec.sources || {};
  if (sources[newName] !== undefined) {
    showAlert(`Já existe uma fonte chamada "${newName}".`, "error");
    renderSourcesBlock();
    return;
  }
  state.spec.sources = Object.fromEntries(
    Object.entries(sources).map(([k, v]) => (k === oldName ? [newName, v] : [k, v]))
  );
  if (state.spec.master === oldName) state.spec.master = newName;
  updateSourceReferences(oldName, newName);
  renderSourcesBlock();
  renderTimelineCards();
  renderOverlayCards();
  renderAudioFields();
  syncJsonFromSpec();
}

/** Atualiza (ou remove, quando `newName` é undefined) as referências a uma fonte renomeada/excluída
 * na linha do tempo, nas sobreposições de vídeo e nas faixas de áudio externas. */
function updateSourceReferences(oldName, newName) {
  (state.spec.timeline || []).forEach((seg) => {
    if (seg.type === "clip" && seg.source === oldName) {
      seg.source = newName;
      if (!newName) seg.src = seg.src || "";
    }
  });
  (state.spec.overlays || []).forEach((ov) => {
    if (ov.type === "video" && ov.source === oldName) {
      ov.source = newName;
      if (!newName) ov.src = ov.src || "";
    }
  });
  if (state.spec.audio) {
    state.spec.audio.tracks = (state.spec.audio.tracks || [])
      .filter((t) => newName || t.source !== oldName)
      .map((t) => (t.source === oldName ? { ...t, source: newName } : t));
  }
}

function handleSyncModeToggle(el) {
  const name = el.dataset.syncModeToggle;
  const path = `sources.${name}.sync`;
  if (el.value === "auto") {
    setPath(state.spec, path, "auto");
  } else {
    const current = getPath(state.spec, path);
    setPath(state.spec, path, typeof current === "number" ? current : 0);
  }
  syncJsonFromSpec();
  renderSourcesBlock();
}

async function runSourceSync() {
  const sources = state.spec.sources || {};
  const names = Object.keys(sources);
  if (names.length < 2) { showAlert("Cadastre ao menos duas fontes para sincronizar.", "error"); return; }
  const masterName = state.spec.master || names[0];
  const master = sources[masterName];
  const others = names.filter((n) => n !== masterName).map((n) => sources[n].src);
  if (!master.src || others.some((s) => !s)) {
    showAlert("Preencha o arquivo de cada fonte antes de sincronizar.", "error");
    return;
  }
  const btn = document.getElementById("btn-sync-sources");
  const result = await runAction(btn, () => api.post("/api/sync", {
    master: master.src, others, master_stream: master.audio_stream ?? 0,
  }));
  if (result.ok) {
    state.syncResults = result.value;
    renderSyncResults();
  }
}

function renderSyncResults() {
  const container = document.getElementById("sync-results");
  if (!container) return;
  const rows = state.syncResults;
  if (!rows || !rows.length) { container.innerHTML = ""; return; }
  container.innerHTML = `
    <table class="sync-table">
      <thead><tr><th>Arquivo</th><th>Deslocamento (s)</th><th>Confiança</th><th>Confiável</th></tr></thead>
      <tbody>
        ${rows.map((r) => `
          <tr>
            <td>${escHtml(baseName(r.path))}</td>
            <td>${r.offset_s.toFixed(3)}</td>
            <td>${Math.round(r.confidence * 100)}%</td>
            <td>${r.reliable ? "Sim" : "Não"}</td>
          </tr>`).join("")}
      </tbody>
    </table>
    <div class="add-row"><button type="button" class="btn btn-small btn-accent" id="btn-apply-sync">Usar estes valores</button></div>`;
}

function applySyncResults() {
  const rows = state.syncResults;
  if (!rows) return;
  const sources = state.spec.sources || {};
  for (const r of rows) {
    const name = Object.keys(sources).find((n) => sources[n].src === r.path);
    if (name) sources[name].sync = r.offset_s;
  }
  state.syncResults = null;
  renderSourcesBlock();
  syncJsonFromSpec();
  showAlert("Valores de sincronização aplicados.", "success");
}

/* -- bloco Linha do tempo -- */

function newSegment(type) {
  if (type === "clip") return { type: "clip", src: "", start: 0, end: undefined, speed: 1, volume: 1, mute: false, fade_in: 0, fade_out: 0 };
  if (type === "image") return { type: "image", src: "", duration: 3, motion: "zoom-in", motion_amount: 0.12, fade_in: 0, fade_out: 0 };
  return { type: "card", title: "", subtitle: undefined, duration: 3, variant: undefined, logo: true, motion: "zoom-in", motion_amount: 0.04, fade_in: 0, fade_out: 0 };
}

function changeSegmentType(index, newType) {
  const old = state.spec.timeline[index];
  const fresh = newSegment(newType);
  fresh.label = old.label;
  fresh.transition = old.transition;
  fresh.fade_in = old.fade_in ?? 0;
  fresh.fade_out = old.fade_out ?? 0;
  if (old.reframe) fresh.reframe = old.reframe;
  if (old.color) fresh.color = old.color;
  state.spec.timeline[index] = fresh;
  renderTimelineCards();
  syncJsonFromSpec();
}

function renderTimelineCards() {
  const container = document.getElementById("timeline-cards");
  container.innerHTML = state.spec.timeline.map((seg, i) => renderSegCard(seg, i)).join("") || '<p class="empty-hint">Sem trechos ainda.</p>';
}

function renderSegCard(seg, i) {
  const typeOptions = [{ value: "clip", label: "Clipe" }, { value: "image", label: "Imagem" }, { value: "card", label: "Cartão" }];
  let fieldsHtml;
  let thumb = "";
  if (seg.type === "clip") { fieldsHtml = clipFieldsHtml(i, seg); thumb = mediaThumbHtml(seg.src, "video"); }
  else if (seg.type === "image") { fieldsHtml = imageFieldsHtml(i, seg); thumb = mediaThumbHtml(seg.src, "image"); }
  else fieldsHtml = cardFieldsHtml(i, seg);
  return `
    <div class="seg-card" data-seg-index="${i}">
      <div class="seg-card-header">
        <span class="seg-index">${i + 1}</span>
        <select data-seg-type-select="${i}">
          ${typeOptions.map((o) => `<option value="${o.value}" ${seg.type === o.value ? "selected" : ""}>${o.label}</option>`).join("")}
        </select>
        <div class="seg-card-actions">
          <button type="button" class="icon-btn" data-seg-action="up" data-seg-index="${i}" title="Subir">&uarr;</button>
          <button type="button" class="icon-btn" data-seg-action="down" data-seg-index="${i}" title="Descer">&darr;</button>
          <button type="button" class="icon-btn" data-seg-action="duplicate" data-seg-index="${i}" title="Duplicar">&#10064;</button>
          <button type="button" class="icon-btn" data-seg-action="remove" data-seg-index="${i}" title="Remover">&times;</button>
        </div>
      </div>
      ${thumb ? `<div class="seg-thumb-row">${thumb}</div>` : ""}
      <div class="form-grid">${fieldsHtml}</div>
      ${renderSegCommon(i, seg)}
    </div>`;
}

function clipFieldsHtml(i, seg) {
  return [
    originFieldHtml(`timeline.${i}`, seg, "video", "start/end no relógio da fonte principal."),
    numField(`timeline.${i}.start`, "Início (s)", seg.start ?? 0, { step: 0.1, min: 0 }),
    numField(`timeline.${i}.end`, "Fim (s, opcional)", seg.end, { step: 0.1, min: 0 }),
    numField(`timeline.${i}.speed`, "Velocidade", seg.speed ?? 1, { step: 0.1, min: 0.1, max: 8 }),
    numField(`timeline.${i}.volume`, "Volume", seg.volume ?? 1, { step: 0.1, min: 0, max: 4 }),
    checkField(`timeline.${i}.mute`, "Mudo", !!seg.mute),
    numField(`timeline.${i}.fade_in`, "Fade in (s)", seg.fade_in ?? 0, { step: 0.1, min: 0 }),
    numField(`timeline.${i}.fade_out`, "Fade out (s)", seg.fade_out ?? 0, { step: 0.1, min: 0 }),
  ].join("");
}

function imageFieldsHtml(i, seg) {
  return [
    srcField(`timeline.${i}.src`, "Origem (imagem)", seg.src, "image"),
    numField(`timeline.${i}.duration`, "Duração (s)", seg.duration ?? 3, { step: 0.1, min: 0.1 }),
    selectField(`timeline.${i}.motion`, "Movimento", seg.motion ?? "zoom-in", IMAGE_MOTION_OPTIONS),
    numField(`timeline.${i}.motion_amount`, "Intensidade do movimento", seg.motion_amount ?? 0.12, { step: 0.01, min: 0, max: 0.6 }),
    numField(`timeline.${i}.fade_in`, "Fade in (s)", seg.fade_in ?? 0, { step: 0.1, min: 0 }),
    numField(`timeline.${i}.fade_out`, "Fade out (s)", seg.fade_out ?? 0, { step: 0.1, min: 0 }),
  ].join("");
}

function cardFieldsHtml(i, seg) {
  return [
    textField(`timeline.${i}.title`, "Título", seg.title ?? ""),
    textField(`timeline.${i}.subtitle`, "Subtítulo (opcional)", seg.subtitle ?? ""),
    numField(`timeline.${i}.duration`, "Duração (s)", seg.duration ?? 3, { step: 0.1, min: 0.1 }),
    selectField(`timeline.${i}.variant`, "Variante", seg.variant ?? "", VARIANT_OPTIONS),
    checkField(`timeline.${i}.logo`, "Mostrar logo", seg.logo !== false),
    selectField(`timeline.${i}.motion`, "Movimento", seg.motion ?? "zoom-in", CARD_MOTION_OPTIONS),
    numField(`timeline.${i}.motion_amount`, "Intensidade do movimento", seg.motion_amount ?? 0.04, { step: 0.01, min: 0, max: 0.3 }),
  ].join("");
}

function renderSegCommon(i, seg) {
  const tr = seg.transition || {};
  const rf = seg.reframe || {};
  const mode = rf.mode ?? "auto";
  return `
    <div class="sub-block">
      <div class="sub-block-title">Transição de entrada</div>
      <div class="form-grid">
        ${selectField(`timeline.${i}.transition.type`, "Tipo", tr.type ?? "cut", TRANSITION_OPTIONS)}
        ${numField(`timeline.${i}.transition.duration`, "Duração (s)", tr.duration ?? 0.5, { min: 0.1, max: 5, step: 0.1 })}
      </div>
    </div>
    <div class="sub-block">
      <div class="sub-block-title">Enquadramento</div>
      <div class="form-grid">
        ${selectField(`timeline.${i}.reframe.mode`, "Modo", mode, REFRAME_MODE_OPTIONS, "reframe-mode-select")}
        <div class="reframe-focus-fields" ${mode === "crop" ? "" : "hidden"}>
          ${numField(`timeline.${i}.reframe.focus.0`, "Foco X (0 a 1)", rf.focus ? rf.focus[0] : 0.5, { min: 0, max: 1, step: 0.05 })}
          ${numField(`timeline.${i}.reframe.focus.1`, "Foco Y (0 a 1)", rf.focus ? rf.focus[1] : 0.5, { min: 0, max: 1, step: 0.05 })}
        </div>
      </div>
    </div>`;
}

function handleSegAction(action, index) {
  const arr = state.spec.timeline;
  if (action === "up" && index > 0) {
    [arr[index - 1], arr[index]] = [arr[index], arr[index - 1]];
  } else if (action === "down" && index < arr.length - 1) {
    [arr[index + 1], arr[index]] = [arr[index], arr[index + 1]];
  } else if (action === "duplicate") {
    arr.splice(index + 1, 0, JSON.parse(JSON.stringify(arr[index])));
  } else if (action === "remove") {
    if (arr.length <= 1) { showAlert("É preciso manter ao menos um trecho na linha do tempo.", "error"); return; }
    arr.splice(index, 1);
  }
  renderTimelineCards();
  syncJsonFromSpec();
}

function addSegment(type) {
  state.spec.timeline.push(newSegment(type));
  renderTimelineCards();
  syncJsonFromSpec();
}

/* -- bloco Sobreposições -- */

function newOverlay(type) {
  if (type === "text") return { type: "text", text: "", role: "title", start: 0, end: undefined, position: undefined, animation: undefined };
  if (type === "image") return { type: "image", src: "logo", position: "top-right", width: 0.22, opacity: 1, start: 0, end: undefined };
  if (type === "video") {
    return {
      type: "video", src: "", start: 0, end: undefined, offset: 0, position: "bottom-right",
      width: 0.28, shape: "rounded", radius: 0.08, border: 6, border_color: "white", shadow: true,
      opacity: 1, margin: 40, volume: 1, animation: "fade", fade: 0.3,
    };
  }
  return { type: "progress-bar", position: "bottom", height: 10 };
}

function changeOverlayType(index, newType) {
  const old = state.spec.overlays[index];
  const fresh = newOverlay(newType);
  if ("start" in fresh && old.start !== undefined) fresh.start = old.start;
  if ("end" in fresh && old.end !== undefined) fresh.end = old.end;
  state.spec.overlays[index] = fresh;
  renderOverlayCards();
  syncJsonFromSpec();
}

function renderOverlayCards() {
  const container = document.getElementById("overlay-cards");
  container.innerHTML = state.spec.overlays.map((ov, i) => renderOverlayCard(ov, i)).join("") || '<p class="empty-hint">Sem sobreposições ainda.</p>';
}

function renderOverlayCard(ov, i) {
  const typeOptions = [
    { value: "text", label: "Texto" },
    { value: "image", label: "Imagem" },
    { value: "video", label: "Vídeo (PiP)" },
    { value: "progress-bar", label: "Barra de progresso" },
  ];
  let fieldsHtml;
  let thumb = "";
  if (ov.type === "text") fieldsHtml = textOverlayFieldsHtml(i, ov);
  else if (ov.type === "image") fieldsHtml = imageOverlayFieldsHtml(i, ov);
  else if (ov.type === "video") { fieldsHtml = videoOverlayFieldsHtml(i, ov); thumb = mediaThumbHtml(ov.src, "video"); }
  else fieldsHtml = progressOverlayFieldsHtml(i, ov);
  return `
    <div class="overlay-card" data-overlay-index="${i}">
      <div class="overlay-card-header">
        <select data-overlay-type-select="${i}">
          ${typeOptions.map((o) => `<option value="${o.value}" ${ov.type === o.value ? "selected" : ""}>${o.label}</option>`).join("")}
        </select>
        <div class="seg-card-actions">
          <button type="button" class="icon-btn" data-ov-action="up" data-ov-index="${i}" title="Subir">&uarr;</button>
          <button type="button" class="icon-btn" data-ov-action="down" data-ov-index="${i}" title="Descer">&darr;</button>
          <button type="button" class="icon-btn" data-ov-action="remove" data-ov-index="${i}" title="Remover">&times;</button>
        </div>
      </div>
      ${thumb ? `<div class="seg-thumb-row">${thumb}</div>` : ""}
      <div class="form-grid">${fieldsHtml}</div>
    </div>`;
}

function textOverlayFieldsHtml(i, ov) {
  return [
    textField(`overlays.${i}.text`, "Texto", ov.text ?? ""),
    textField(`overlays.${i}.secondary`, "Segunda linha (opcional)", ov.secondary ?? ""),
    selectField(`overlays.${i}.role`, "Papel", ov.role ?? "title", TEXT_ROLE_OPTIONS),
    numField(`overlays.${i}.start`, "Início (s)", ov.start ?? 0, { step: 0.1, min: 0 }),
    numField(`overlays.${i}.end`, "Fim (s, opcional)", ov.end, { step: 0.1, min: 0 }),
    selectField(`overlays.${i}.position`, "Posição", ov.position ?? "", TEXT_POSITION_OPTIONS),
    selectField(`overlays.${i}.animation`, "Animação", ov.animation ?? "", TEXT_ANIMATION_OPTIONS),
  ].join("");
}

function imageOverlaySrcField(path, value) {
  const known = ["logo", "logo:symbol", "logo:horizontal_dark", "logo:symbol_dark"];
  const isCustom = !!value && !known.includes(value);
  const options = [
    { value: "logo", label: "Logo horizontal" },
    { value: "logo:symbol", label: "Logo símbolo" },
    { value: "logo:horizontal_dark", label: "Logo horizontal (escuro)" },
    { value: "logo:symbol_dark", label: "Logo símbolo (escuro)" },
    { value: "__custom__", label: "Personalizado (arquivo)" },
  ];
  const opts = options.map((o) => {
    const selected = (isCustom && o.value === "__custom__") || (!isCustom && value === o.value);
    return `<option value="${o.value}" ${selected ? "selected" : ""}>${o.label}</option>`;
  }).join("");
  return `
    <div class="field">
      <label>Origem</label>
      <select class="overlay-src-select" data-overlay-src-toggle="${path}">${opts}</select>
    </div>
    <div class="field field-src" data-overlay-src-custom ${isCustom ? "" : "hidden"}>
      <label>Arquivo</label>
      <div class="field-src">
        <input type="text" data-path="${path}" data-kind="string" value="${escAttr(isCustom ? value : "")}">
        <button type="button" class="btn btn-small" data-browse-path="${path}" data-browse-kind="image">Escolher...</button>
      </div>
    </div>`;
}

function imageOverlayFieldsHtml(i, ov) {
  return [
    imageOverlaySrcField(`overlays.${i}.src`, ov.src ?? "logo"),
    selectField(`overlays.${i}.position`, "Posição", ov.position ?? "top-right", IMAGE_OVERLAY_POSITION_OPTIONS),
    numField(`overlays.${i}.width`, "Largura (fração)", ov.width ?? 0.22, { step: 0.01, min: 0.01, max: 1 }),
    numField(`overlays.${i}.opacity`, "Opacidade", ov.opacity ?? 1, { step: 0.05, min: 0, max: 1 }),
    numField(`overlays.${i}.start`, "Início (s)", ov.start ?? 0, { step: 0.1, min: 0 }),
    numField(`overlays.${i}.end`, "Fim (s, opcional)", ov.end, { step: 0.1, min: 0 }),
  ].join("");
}

function videoOverlayFieldsHtml(i, ov) {
  const prefix = `overlays.${i}`;
  const usesSource = !!ov.source;
  const offsetLabel = usesSource ? "Tempo de entrada na fonte (s)" : "Ponto de entrada no arquivo (s)";
  const sourceHint = "start/end ficam na linha do tempo; offset é o tempo, no relógio da fonte principal, em que a sobreposição entra nesta fonte.";
  return [
    originFieldHtml(prefix, ov, "video", sourceHint),
    numField(`${prefix}.start`, "Início na linha do tempo (s)", ov.start ?? 0, { step: 0.1, min: 0 }),
    numField(`${prefix}.end`, "Fim (s, opcional)", ov.end, { step: 0.1, min: 0 }),
    numField(`${prefix}.offset`, offsetLabel, ov.offset ?? 0, { step: 0.1, min: 0 }),
    selectField(`${prefix}.position`, "Posição", ov.position ?? "bottom-right", IMAGE_OVERLAY_POSITION_OPTIONS),
    numField(`${prefix}.x`, "X (0 a 1, opcional)", ov.x, { step: 0.01, min: 0, max: 1 }),
    numField(`${prefix}.y`, "Y (0 a 1, opcional)", ov.y, { step: 0.01, min: 0, max: 1 }),
    numField(`${prefix}.width`, "Largura (fração)", ov.width ?? 0.28, { step: 0.01, min: 0.01, max: 1 }),
    textField(`${prefix}.aspect`, "Proporção (ex.: 16:9, opcional)", ov.aspect ?? ""),
    selectField(`${prefix}.shape`, "Formato", ov.shape ?? "rounded", VIDEO_OVERLAY_SHAPE_OPTIONS),
    numField(`${prefix}.radius`, "Raio dos cantos (fração)", ov.radius ?? 0.08, { step: 0.01, min: 0, max: 0.5 }),
    numField(`${prefix}.softness`, "Suavidade da borda (px)", ov.softness ?? 0, { step: 1, min: 0 }),
    numField(`${prefix}.border`, "Borda (px)", ov.border ?? 6, { step: 1, min: 0 }),
    textField(`${prefix}.border_color`, "Cor da borda", ov.border_color ?? "white"),
    checkField(`${prefix}.shadow`, "Sombra", ov.shadow !== false),
    numField(`${prefix}.opacity`, "Opacidade", ov.opacity ?? 1, { step: 0.05, min: 0, max: 1 }),
    numField(`${prefix}.margin`, "Margem (px)", ov.margin ?? 40, { step: 1, min: 0 }),
    numField(`${prefix}.volume`, "Volume do PiP", ov.volume ?? 1, { step: 0.1, min: 0, max: 4 }),
    selectField(`${prefix}.animation`, "Animação", ov.animation ?? "fade", VIDEO_OVERLAY_ANIMATION_OPTIONS),
    numField(`${prefix}.fade`, "Duração da animação (s)", ov.fade ?? 0.3, { step: 0.05, min: 0 }),
  ].join("");
}

function progressOverlayFieldsHtml(i, ov) {
  return [
    selectField(`overlays.${i}.position`, "Posição", ov.position ?? "bottom", PROGRESS_POSITION_OPTIONS),
    numField(`overlays.${i}.height`, "Altura (px)", ov.height ?? 10, { step: 1, min: 1 }),
  ].join("");
}

function handleOverlaySrcToggle(el) {
  const path = el.dataset.overlaySrcToggle;
  const customRow = el.closest(".field").nextElementSibling;
  if (el.value === "__custom__") {
    if (customRow) customRow.hidden = false;
  } else {
    if (customRow) customRow.hidden = true;
    setPath(state.spec, path, el.value);
    syncJsonFromSpec();
  }
}

function handleOvAction(action, index) {
  const arr = state.spec.overlays;
  if (action === "up" && index > 0) {
    [arr[index - 1], arr[index]] = [arr[index], arr[index - 1]];
  } else if (action === "down" && index < arr.length - 1) {
    [arr[index + 1], arr[index]] = [arr[index], arr[index + 1]];
  } else if (action === "remove") {
    arr.splice(index, 1);
  }
  renderOverlayCards();
  syncJsonFromSpec();
}

function addOverlay(type) {
  state.spec.overlays.push(newOverlay(type));
  renderOverlayCards();
  syncJsonFromSpec();
}

/* -- bloco Legendas (configuração, não a lista de cues) -- */

function renderCaptionsSettingsFields() {
  const container = document.getElementById("captions-fields");
  const enabled = !!state.spec.captions;
  const c = state.spec.captions || {};
  const style = c.style || {};
  let html = `<div class="field field-checkbox"><input type="checkbox" id="captions-enabled-toggle" ${enabled ? "checked" : ""}><label for="captions-enabled-toggle">Gerar legendas automáticas</label></div>`;
  if (enabled) {
    html += textField("captions.source", "Origem (auto ou caminho .srt)", c.source ?? "auto");
    html += textField("captions.language", "Idioma", c.language ?? "pt");
    html += selectField("captions.model", "Modelo", c.model ?? "small", MODEL_OPTIONS);
    html += selectField("captions.style.mode", "Estilo", style.mode ?? "karaoke", CAPTION_STYLE_MODE_OPTIONS);
    html += numField("captions.style.max_words", "Máx. palavras por linha", style.max_words ?? 4, { min: 1, max: 12, step: 1 });
    html += numField("captions.style.max_chars", "Máx. caracteres por linha", style.max_chars ?? 22, { min: 4, max: 80, step: 1 });
    html += checkField("captions.style.uppercase", "Maiúsculas", style.uppercase ?? true);
    html += numField("captions.style.size", "Tamanho", style.size ?? 72, { min: 1, step: 1 });
  }
  container.innerHTML = html;
  document.getElementById("captions-enabled-toggle").addEventListener("change", (e) => {
    if (e.target.checked) {
      state.spec.captions = state.spec.captions || { source: "auto", language: "pt", model: "small" };
    } else {
      state.spec.captions = null;
    }
    renderCaptionsSettingsFields();
    syncJsonFromSpec();
  });
}

/* -- bloco Áudio -- */

function renderAudioFields() {
  const container = document.getElementById("audio-fields");
  const a = state.spec.audio || {};
  const music = a.music || null;
  let html = `<div class="field field-checkbox"><input type="checkbox" id="music-enabled-toggle" ${music ? "checked" : ""}><label for="music-enabled-toggle">Usar música de fundo</label></div>`;
  if (music) {
    html += srcField("audio.music.src", "Arquivo de música", music.src ?? "", "audio");
    html += numField("audio.music.volume", "Volume", music.volume ?? 0.18, { step: 0.01, min: 0, max: 2 });
    html += checkField("audio.music.ducking", "Abaixar sob a voz (ducking)", music.ducking !== false);
    html += numField("audio.music.fade_in", "Fade in (s)", music.fade_in ?? 1, { step: 0.1, min: 0 });
    html += numField("audio.music.fade_out", "Fade out (s)", music.fade_out ?? 2, { step: 0.1, min: 0 });
    html += numField("audio.music.start_at", "Começar em (s)", music.start_at ?? 0, { step: 0.1, min: 0 });
    html += checkField("audio.music.loop", "Repetir em loop", music.loop !== false);
  }
  html += numField("audio.voice_gain", "Ganho da voz", a.voice_gain ?? 1, { step: 0.1, min: 0, max: 4 });
  html += selectField("audio.normalize", "Normalização", a.normalize ?? "two-pass", NORMALIZE_OPTIONS);
  html += checkField("audio.mute_clips", "Silenciar áudio original dos clipes", !!a.mute_clips);
  container.innerHTML = `<div class="form-grid">${html}</div>${audioTracksHtml()}`;
  document.getElementById("music-enabled-toggle").addEventListener("change", (e) => {
    state.spec.audio = state.spec.audio || {};
    if (e.target.checked) {
      state.spec.audio.music = state.spec.audio.music || { src: "" };
    } else {
      state.spec.audio.music = null;
    }
    renderAudioFields();
    syncJsonFromSpec();
  });
}

function audioTracksHtml() {
  const tracks = (state.spec.audio && state.spec.audio.tracks) || [];
  const names = sourceNames();
  const rows = tracks.map((t, i) => `
    <div class="source-row" data-track-index="${i}">
      <div class="form-grid">
        ${selectField(`audio.tracks.${i}.source`, "Fonte", t.source ?? "", names.map((n) => ({ value: n, label: n })))}
        ${numField(`audio.tracks.${i}.volume`, "Volume", t.volume ?? 1, { step: 0.1, min: 0, max: 4 })}
      </div>
      <div class="source-row-actions">
        <button type="button" class="icon-btn" data-track-remove="${i}" title="Remover">&times;</button>
      </div>
    </div>`).join("");
  const hint = names.length ? "" : '<p class="hint-text">Cadastre uma fonte sincronizada acima para usar faixas externas.</p>';
  return `
    <div class="sub-block">
      <div class="sub-block-title">Faixas externas sincronizadas</div>
      ${hint}
      ${rows || '<p class="empty-hint">Nenhuma faixa ainda.</p>'}
      <div class="add-row"><button type="button" class="btn btn-small" id="btn-add-audio-track" ${names.length ? "" : "disabled"}>Adicionar faixa</button></div>
    </div>`;
}

function addAudioTrack() {
  const names = sourceNames();
  if (!names.length) return;
  state.spec.audio = state.spec.audio || {};
  state.spec.audio.tracks = state.spec.audio.tracks || [];
  state.spec.audio.tracks.push({ source: names[0], volume: 1 });
  renderAudioFields();
  syncJsonFromSpec();
}

function removeAudioTrack(index) {
  state.spec.audio.tracks.splice(index, 1);
  renderAudioFields();
  syncJsonFromSpec();
}

/* -- eventos delegados do formulário do editor -- */

function toggleReframeFocus(el) {
  if (!el.classList.contains("reframe-mode-select")) return;
  const subBlock = el.closest(".sub-block");
  const focusFields = subBlock && subBlock.querySelector(".reframe-focus-fields");
  if (focusFields) focusFields.hidden = el.value !== "crop";
}

function applyFieldChange(el) {
  const path = el.dataset.path;
  const kind = el.dataset.kind;
  let value;
  if (kind === "boolean") value = el.checked;
  else if (kind === "number") value = el.value === "" ? undefined : Number(el.value);
  else value = el.value === "" ? undefined : el.value;
  setPath(state.spec, path, value);
  if (/\.focus\.[01]$/.test(path)) {
    const arr = getPath(state.spec, path.replace(/\.[01]$/, ""));
    if (Array.isArray(arr)) {
      if (arr[0] === undefined) arr[0] = 0.5;
      if (arr[1] === undefined) arr[1] = 0.5;
    }
  }
  syncJsonFromSpec();
}

function refreshEditorBlockForPath(path) {
  if (path.startsWith("timeline.")) renderTimelineCards();
  else if (path.startsWith("overlays.")) renderOverlayCards();
  else if (path.startsWith("audio.")) renderAudioFields();
  else if (path.startsWith("captions.")) renderCaptionsSettingsFields();
  else if (path.startsWith("sources.")) renderSourcesBlock();
}

function openBrowseForField(path) {
  openFileBrowser({
    multi: false,
    onSelect: (paths) => {
      closeModal();
      setPath(state.spec, path, paths[0]);
      syncJsonFromSpec();
      refreshEditorBlockForPath(path);
    },
  });
}

function toggleDropdown(menuId) {
  const menu = document.getElementById(menuId);
  const willShow = menu.hidden;
  closeDropdowns();
  menu.hidden = !willShow;
}

function closeDropdowns() {
  document.querySelectorAll(".dropdown-menu").forEach((m) => { m.hidden = true; });
}

document.addEventListener("click", (e) => {
  if (!e.target.closest(".dropdown")) closeDropdowns();
});

const editorForm = document.getElementById("editor-form");

editorForm.addEventListener("click", (e) => {
  if (e.target.closest("#btn-add-segment")) { toggleDropdown("add-segment-menu"); return; }
  const addSegItem = e.target.closest("[data-add-segment]");
  if (addSegItem) { addSegment(addSegItem.dataset.addSegment); closeDropdowns(); return; }
  if (e.target.closest("#btn-add-overlay")) { toggleDropdown("add-overlay-menu"); return; }
  const addOvItem = e.target.closest("[data-add-overlay]");
  if (addOvItem) { addOverlay(addOvItem.dataset.addOverlay); closeDropdowns(); return; }
  const segAction = e.target.closest("[data-seg-action]");
  if (segAction) { handleSegAction(segAction.dataset.segAction, Number(segAction.dataset.segIndex)); return; }
  const ovAction = e.target.closest("[data-ov-action]");
  if (ovAction) { handleOvAction(ovAction.dataset.ovAction, Number(ovAction.dataset.ovIndex)); return; }
  if (e.target.closest("#btn-add-source")) { addSourceRow(); return; }
  const sourceRemove = e.target.closest("[data-source-remove]");
  if (sourceRemove) { removeSourceRow(sourceRemove.dataset.sourceRemove); return; }
  if (e.target.closest("#btn-sync-sources")) { runSourceSync(); return; }
  if (e.target.closest("#btn-apply-sync")) { applySyncResults(); return; }
  if (e.target.closest("#btn-add-audio-track")) { addAudioTrack(); return; }
  const trackRemove = e.target.closest("[data-track-remove]");
  if (trackRemove) { removeAudioTrack(Number(trackRemove.dataset.trackRemove)); return; }
  const browseBtn = e.target.closest("[data-browse-path]");
  if (browseBtn) { openBrowseForField(browseBtn.dataset.browsePath); }
});

editorForm.addEventListener("input", (e) => {
  const el = e.target;
  if (el.matches('input[type="text"][data-path], input[type="number"][data-path], textarea[data-path]')) {
    applyFieldChange(el);
  }
});

editorForm.addEventListener("change", (e) => {
  const el = e.target;
  if (el.matches("[data-seg-type-select]")) { changeSegmentType(Number(el.dataset.segTypeSelect), el.value); return; }
  if (el.matches("[data-overlay-type-select]")) { changeOverlayType(Number(el.dataset.overlayTypeSelect), el.value); return; }
  if (el.matches("[data-overlay-src-toggle]")) { handleOverlaySrcToggle(el); return; }
  if (el.matches("[data-origin-toggle]")) { handleOriginToggle(el); return; }
  if (el.matches("[data-source-rename]")) { renameSource(el.dataset.sourceRename, el.value); return; }
  if (el.matches("[data-sync-mode-toggle]")) { handleSyncModeToggle(el); return; }
  if (el.matches('select[data-path], input[type="checkbox"][data-path]')) {
    applyFieldChange(el);
    toggleReframeFocus(el);
  }
});

/* ==================== 9. aba JSON ==================== */

function syncJsonFromSpec() {
  const el = document.getElementById("json-editor");
  if (document.activeElement !== el) el.value = JSON.stringify(state.spec, null, 2);
  document.getElementById("json-error").textContent = "";
}

document.getElementById("btn-apply-json").addEventListener("click", () => {
  const el = document.getElementById("json-editor");
  try {
    const parsed = JSON.parse(el.value);
    state.spec = normalizeSpec(parsed);
    document.getElementById("json-error").textContent = "";
    showAlert("JSON aplicado.", "success");
    if (window.DMakerEditor) DMakerEditor.refreshView();
  } catch (err) {
    document.getElementById("json-error").textContent = `JSON inválido: ${err.message}`;
  }
});

/* ==================== 10. aba Preview ==================== */

function findPreset(id) {
  return (state.stateInfo?.presets || []).find((p) => p.id === id);
}

function loadOutputIntoPreview(output) {
  state.previewOutput = output;
  document.getElementById("preview-empty").hidden = true;
  document.getElementById("preview-content").hidden = false;
  const video = document.getElementById("preview-player");
  video.src = output.url;
  video.classList.remove("orientation-vertical", "orientation-horizontal");
  const preset = findPreset(output.preset);
  if (preset) video.classList.add(preset.width < preset.height ? "orientation-vertical" : "orientation-horizontal");
  document.getElementById("preview-meta").textContent = `${output.path} - ${output.size_mb} MB - ${output.preset || ""}`;
  document.getElementById("qa-result").innerHTML = "";
}

document.getElementById("btn-qa-sheet").addEventListener("click", async () => {
  if (!state.previewOutput) { showAlert("Nenhuma saída carregada no preview.", "error"); return; }
  const btn = document.getElementById("btn-qa-sheet");
  const result = await runAction(btn, () => api.post("/api/qa/sheet", { video: state.previewOutput.path }));
  if (result.ok) document.getElementById("qa-result").innerHTML = `<img src="${result.value.url}" alt="grade de quadros">`;
});

document.getElementById("btn-qa-frame").addEventListener("click", async () => {
  if (!state.previewOutput) { showAlert("Nenhuma saída carregada no preview.", "error"); return; }
  const t = Number(document.getElementById("qa-frame-time").value || 0);
  const btn = document.getElementById("btn-qa-frame");
  const result = await runAction(btn, () => api.post("/api/qa/frame", { video: state.previewOutput.path, t }));
  if (result.ok) document.getElementById("qa-result").innerHTML = `<img src="${result.value.url}" alt="quadro do vídeo">`;
});

document.getElementById("btn-open-folder").addEventListener("click", () => {
  if (!state.previewOutput) return;
  const dir = state.previewOutput.path.replace(/[\\/][^\\/]*$/, "");
  showAlert(`Pasta do arquivo: ${dir}`, "success");
});

/* ==================== 11. aba Legendas ==================== */

function updateCaptionsTabVisibility() {
  const btn = document.getElementById("tab-btn-captions");
  btn.hidden = !state.captionsExists;
  if (!state.captionsExists && state.activeTab === "captions") switchTab("editor");
}

async function loadCaptionsTab() {
  if (!state.captionsExists || !state.currentProject) return;
  try {
    state.captionsData = await api.get(`/api/projects/${encodeURIComponent(state.currentProject)}/captions`);
    renderCaptionsRows();
  } catch (err) {
    handleError(err);
  }
}

function renderCaptionsRows() {
  const tbody = document.getElementById("captions-rows");
  tbody.innerHTML = state.captionsData.cues.map((c, i) => `
    <tr data-cue-index="${i}">
      <td class="captions-time">${formatTime(c.start)}</td>
      <td class="captions-time">${formatTime(c.end)}</td>
      <td><input type="text" value="${escAttr(c.text)}" data-cue-text="${i}"></td>
    </tr>`).join("");
}

document.getElementById("captions-rows").addEventListener("change", (e) => {
  const input = e.target.closest("[data-cue-text]");
  if (!input) return;
  const i = Number(input.dataset.cueText);
  const cue = state.captionsData.cues[i];
  cue.words = redistributeWords(cue, input.value);
  cue.text = input.value;
});

document.getElementById("btn-save-captions").addEventListener("click", async () => {
  if (!state.captionsData) return;
  const btn = document.getElementById("btn-save-captions");
  const result = await runAction(btn, () => api.put(`/api/projects/${encodeURIComponent(state.currentProject)}/captions`, { cues: state.captionsData.cues }));
  if (result.ok) showAlert("Legendas salvas.", "success");
});

/* ==================== abas ==================== */

function switchTab(tab) {
  state.activeTab = tab;
  document.querySelectorAll(".tab-btn").forEach((b) => b.classList.toggle("active", b.dataset.tab === tab));
  document.querySelectorAll(".tab-panel").forEach((p) => p.classList.toggle("active", p.id === `panel-${tab}`));
  if (tab === "json") syncJsonFromSpec();
  if (tab === "editor" && state.spec) renderEditorForm();
  if (tab === "captions") loadCaptionsTab();
  if (tab === "timeline" && state.spec && window.DMakerEditor) DMakerEditor.refreshView();
}

document.getElementById("tabs").addEventListener("click", (e) => {
  const btn = e.target.closest(".tab-btn");
  if (!btn || btn.hidden) return;
  switchTab(btn.dataset.tab);
});

/* ==================== novo projeto ==================== */

function openNewProjectModal() {
  if (!newProjectState.preset && state.stateInfo?.presets?.length) {
    newProjectState.preset = state.stateInfo.presets[0].id;
  }
  const presetOptions = (state.stateInfo?.presets || []).map((p) => `<option value="${p.id}" ${p.id === newProjectState.preset ? "selected" : ""}>${escHtml(p.platform)} - ${escHtml(p.name)} (${p.id})</option>`).join("");
  const brandOptions = ['<option value="">Nenhuma</option>'].concat((state.stateInfo?.brands || []).map((b) => `<option value="${b.key}" ${b.key === newProjectState.brand ? "selected" : ""}>${escHtml(b.name)}</option>`)).join("");
  openModal(`
    <h3>Novo projeto</h3>
    <div class="form-grid">
      <div class="field"><label>Nome</label><input type="text" id="np-name" value="${escAttr(newProjectState.name)}"></div>
      <div class="field"><label>Preset</label><select id="np-preset">${presetOptions}</select></div>
      <div class="field"><label>Marca</label><select id="np-brand">${brandOptions}</select></div>
    </div>
    <div class="field" style="margin-top:10px">
      <label>Fontes (vídeos/imagens)</label>
      <button type="button" class="btn btn-small" id="np-choose-sources">Escolher arquivos...</button>
      <div class="tag-list" id="np-sources-tags"></div>
    </div>
    <div class="checkbox-row"><input type="checkbox" id="np-captions" ${newProjectState.captions ? "checked" : ""}><label for="np-captions">Gerar legendas automáticas</label></div>
    <div class="checkbox-row"><input type="checkbox" id="np-logo" ${newProjectState.logo ? "checked" : ""}><label for="np-logo">Incluir logo</label></div>
    <div class="modal-actions">
      <button type="button" class="btn" id="np-cancel">Cancelar</button>
      <button type="button" class="btn btn-accent" id="np-submit">Criar</button>
    </div>`);
  renderNewProjectTags();
}

function renderNewProjectTags() {
  const el = document.getElementById("np-sources-tags");
  if (!el) return;
  el.innerHTML = newProjectState.sources.map((s, i) => `<span class="tag">${escHtml(baseName(s))}<button type="button" data-remove-source="${i}">&times;</button></span>`).join("");
}

function captureNewProjectDraft() {
  const name = document.getElementById("np-name");
  const preset = document.getElementById("np-preset");
  const brand = document.getElementById("np-brand");
  const captions = document.getElementById("np-captions");
  const logo = document.getElementById("np-logo");
  if (name) newProjectState.name = name.value;
  if (preset) newProjectState.preset = preset.value;
  if (brand) newProjectState.brand = brand.value;
  if (captions) newProjectState.captions = captions.checked;
  if (logo) newProjectState.logo = logo.checked;
}

function chooseNewProjectSources() {
  captureNewProjectDraft();
  openFileBrowser({
    multi: true,
    onSelect: (paths) => {
      newProjectState.sources = paths;
      openNewProjectModal();
    },
  });
}

async function submitNewProject() {
  captureNewProjectDraft();
  if (!newProjectState.name.trim()) { showAlert("Informe um nome para o projeto.", "error"); return; }
  const btn = document.getElementById("np-submit");
  const result = await runAction(btn, () => api.post("/api/projects", {
    name: newProjectState.name.trim(),
    preset: newProjectState.preset,
    brand: newProjectState.brand || null,
    sources: newProjectState.sources,
    captions: newProjectState.captions,
    logo: newProjectState.logo,
  }));
  if (result.ok) {
    closeModal();
    newProjectState.name = "";
    newProjectState.sources = [];
    await refreshProjectList();
    await openProject(result.value.name);
  }
}

document.getElementById("btn-new-project").addEventListener("click", () => openNewProjectModal());
document.getElementById("modal-box").addEventListener("click", onModalClick);

/* ==================== abrir projeto ==================== */

async function openProject(name) {
  const data = await api.get(`/api/projects/${encodeURIComponent(name)}`);
  state.currentProject = name;
  state.spec = normalizeSpec(data.spec);
  state.captionsExists = data.captions_exists;
  state.projectOutputs = data.outputs;
  localStorage.setItem("dmaker.lastProject", name);
  document.getElementById("project-name").textContent = name;
  document.getElementById("validate-banner").hidden = true;
  setTopbarEnabled(true);
  renderProjectList();
  updateCaptionsTabVisibility();
  if (data.outputs.length) {
    loadOutputIntoPreview(data.outputs[0]);
  } else {
    document.getElementById("preview-empty").hidden = false;
    document.getElementById("preview-content").hidden = true;
    state.previewOutput = null;
  }
  if (window.DMakerEditor) await DMakerEditor.open(name, state.spec);
  switchTab("timeline");
}

/* ==================== hash da URL: #project=<nome>&job=<id> ==================== */

/** Um render disparado pela CLI/MCP abre a interface com o hash apontando para o projeto e o job,
 * para o painel de andamento conectar sozinho (ver pipeline/remote.py RenderDispatcher). */
function parseRouteHash() {
  const params = new URLSearchParams(window.location.hash.replace(/^#/, ""));
  return { project: params.get("project"), job: params.get("job") };
}

async function applyRouteHash() {
  const { project, job } = parseRouteHash();
  if (!project) return;
  if (project !== state.currentProject) {
    try { await openProject(project); } catch (err) { handleError(err); return; }
  }
  if (job) openJobEvents(project, job, "render");
}

window.addEventListener("hashchange", () => { applyRouteHash().catch(handleError); });

/* ==================== heartbeat: quem está com a página aberta ==================== */

/** Avisa o backend a cada 5s enquanto a aba está visível, para um render disparado por fora não abrir
 * outra aba quando já tem alguém olhando esta (ver RenderDispatcher.open_browser_if_needed). */
function startHeartbeat() {
  const ping = () => {
    if (document.visibilityState === "visible") api.post("/api/clients/ping").catch(() => {});
  };
  ping();
  setInterval(ping, 5000);
}

/* ==================== 12. inicialização ==================== */

async function init() {
  try {
    state.stateInfo = await api.get("/api/state");
  } catch (err) { handleError(err); }
  try {
    await refreshProjectList();
  } catch (err) { handleError(err); }
  try {
    await refreshOutputsGlobal();
  } catch (err) { handleError(err); }
  try {
    await refreshJobs();
  } catch (err) { handleError(err); }
  const { project: hashProject } = parseRouteHash();
  const last = hashProject || localStorage.getItem("dmaker.lastProject");
  if (last && state.projects.some((p) => p.name === last)) {
    try { await openProject(last); } catch (err) { handleError(err); }
  }
  try {
    await applyRouteHash();
  } catch (err) { handleError(err); }
  startHeartbeat();
}

init();

/* Funções puras expostas para inspeção/teste. */
window.DMakerPure = { pruneEmpty, redistributeWords, getPath, setPath };
