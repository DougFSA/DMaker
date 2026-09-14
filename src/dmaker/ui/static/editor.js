"use strict";
/*
 * DMaker - orquestração da aba "Linha do tempo": liga app.js (estado do projeto e da spec),
 * timeline.js (grade multitrilha), player.js (prévia ao vivo) e keymap.js (atalhos).
 *
 * Namespace público: window.DMakerEditor
 *   open(name, spec)   chamado por app.js.openProject ao abrir um projeto
 *   refreshView()      chamado por app.js após qualquer mudança na spec (formulário/JSON/undo)
 *   markSaved()        chamado por app.js após um Salvar bem sucedido (limpa o indicador)
 *
 * Todas as edições passam por applyOp(op), que chama POST /api/projects/{nome}/edit, atualiza
 * a spec e a vista compartilhadas com app.js e empilha um snapshot para desfazer/refazer.
 */

function edEsc(value) {
  return String(value).replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
}

const ED_UNDO_LIMIT = 100;

const edState = {
  view: { total: 0, fps: 30, tracks: [], sources: {} },
  theme: { colors: {}, font: "", logos: {}, no_dash: false },
  proxyUrls: {},
  undoStack: [],
  redoStack: [],
  dirty: false,
  timeline: null,
  player: null,
  filters: null,
  media: null,
  keymapController: null,
  selection: { typeKey: null, base: null },
  proxyEventSource: null,
  playDirection: 0,
  playLevel: 1,
};

function edProjectPath(suffix) {
  return `/api/projects/${encodeURIComponent(state.currentProject)}${suffix}`;
}

function edIsOverlayTrack(trackId, item) {
  if (trackId === "TX") return true;
  if (trackId === "GR") return item.kind === "image";
  return trackId.startsWith("V") && trackId !== "V1";
}

/** Traduz um item selecionado na linha do tempo para o que o painel de filtros precisa: o tipo
 * de catálogo (FILTER_CATALOG) e o caminho absoluto do item na spec. A1 é só a "sombra" de áudio
 * de um clipe da V1, então selecionar um item da A1 edita o clipe correspondente. */
function contextForItem(trackId, item) {
  if (trackId === "A1") {
    const v1 = edState.view.tracks.find((t) => t.id === "V1");
    const v1Item = v1 && v1.items[item.index];
    return v1Item ? { typeKey: v1Item.kind, base: `timeline.${v1Item.index}` } : { typeKey: null, base: null };
  }
  if (trackId === "V1") return { typeKey: item.kind, base: `timeline.${item.index}` };
  if (trackId === "TX") return { typeKey: "text", base: `overlays.${item.index}` };
  if (trackId === "GR") return { typeKey: item.kind === "progress-bar" ? "progress-bar" : "image-overlay", base: `overlays.${item.index}` };
  if (trackId.startsWith("V") && trackId !== "V1") return { typeKey: "video", base: `overlays.${item.index}` };
  if (/^A[2-9]\d*$/.test(trackId)) return { typeKey: "track", base: `audio.tracks.${item.index}` };
  if (trackId === "MUS") return { typeKey: "music", base: "audio.music" };
  if (trackId === "CC") return { typeKey: "captions", base: "captions" };
  return { typeKey: null, base: null };
}

function setSelectionContext(typeKey, base) {
  edState.selection = { typeKey, base };
  if (edState.filters) edState.filters.setSelection(typeKey, base);
}

function refreshSidePanels() {
  if (edState.filters) edState.filters.refresh();
  if (edState.media) edState.media.setSpec(state.spec);
}

/* ---------- snapshots (desfazer/refazer) ---------- */

function specSnapshot() {
  return JSON.stringify(state.spec);
}

function markDirty(isDirty) {
  edState.dirty = isDirty;
  const el = document.getElementById("unsaved-indicator");
  if (el) el.hidden = !isDirty;
}

function markSaved() {
  markDirty(false);
}

async function loadSpecSnapshot(snapshot) {
  state.spec = normalizeSpec(JSON.parse(snapshot));
  markDirty(true);
  await refreshViewNow();
  syncJsonFromSpec();
  if (state.activeTab === "editor") renderEditorForm();
}

async function undo() {
  if (!edState.undoStack.length) return;
  const snapshot = edState.undoStack.pop();
  edState.redoStack.push(specSnapshot());
  await loadSpecSnapshot(snapshot);
}

async function redo() {
  if (!edState.redoStack.length) return;
  const snapshot = edState.redoStack.pop();
  edState.undoStack.push(specSnapshot());
  await loadSpecSnapshot(snapshot);
}

/* ---------- vista e edições ---------- */

async function refreshViewNow() {
  if (!state.currentProject || !state.spec) return;
  try {
    const view = await api.post(edProjectPath("/timeline"), { spec: pruneEmpty(state.spec) });
    edState.view = view;
    if (edState.timeline) edState.timeline.setView(view);
    if (edState.player) edState.player.setData({ view, spec: state.spec, theme: edState.theme, proxyUrls: edState.proxyUrls });
    updateTimecode(edState.player ? edState.player.getTime() : 0);
    refreshSidePanels();
  } catch (err) {
    handleError(err);
  }
}

let refreshViewTimer = null;

/** Recalcula a vista a partir da spec atual. Chamada com frequência (a cada tecla digitada
 * no formulário ou no JSON), por isso é discreta: espera 250ms de silêncio antes de bater
 * na API, para não disparar um pedido por caractere. */
function refreshView() {
  clearTimeout(refreshViewTimer);
  return new Promise((resolve) => {
    refreshViewTimer = setTimeout(() => resolve(refreshViewNow()), 250);
  });
}

async function applyOp(op) {
  if (!state.currentProject || !state.spec) return false;
  const before = specSnapshot();
  try {
    const result = await api.post(edProjectPath("/edit"), { spec: pruneEmpty(state.spec), op });
    edState.undoStack.push(before);
    if (edState.undoStack.length > ED_UNDO_LIMIT) edState.undoStack.shift();
    edState.redoStack = [];
    state.spec = normalizeSpec(result.spec);
    edState.view = result.timeline;
    markDirty(true);
    if (edState.timeline) edState.timeline.setView(edState.view);
    if (edState.player) edState.player.setData({ view: edState.view, spec: state.spec, theme: edState.theme, proxyUrls: edState.proxyUrls });
    syncJsonFromSpec();
    if (state.activeTab === "editor") renderEditorForm();
    refreshSidePanels();
    return true;
  } catch (err) {
    handleError(err);
    return false;
  }
}

/* ---------- seleção e ações de alto nível ---------- */

function selectionWithTrack() {
  return edState.timeline ? edState.timeline.getSelectionWithTrack() : [];
}

function editableSelection() {
  return selectionWithTrack().filter(({ trackId, item }) => trackId === "V1" || edIsOverlayTrack(trackId, item));
}

function editableUnderPlayhead() {
  const t = edState.player.getTime();
  const item = edState.timeline.itemAt("V1", t);
  return item ? { trackId: "V1", item } : null;
}

function splitAtPlayhead() {
  const t = edState.player.getTime();
  const sel = editableSelection().find((s) => s.trackId === "V1");
  const target = sel ? sel.item : edState.timeline.itemAt("V1", t);
  if (!target) { showAlert("Não há trecho da V1 sob o cursor.", "error"); return; }
  const at = t - target.start;
  if (at <= 0.02 || at >= target.end - target.start - 0.02) {
    showAlert("Posicione o cursor dentro do trecho para cortar.", "error");
    return;
  }
  applyOp({ type: "split", index: target.index, at });
}

async function removeSelected() {
  const sel = editableSelection();
  if (!sel.length) { showAlert("Selecione um trecho ou sobreposição para remover.", "error"); return; }
  for (const { trackId, item } of sel) {
    if (trackId === "V1") await applyOp({ type: "remove", index: item.index });
    else await applyOp({ type: "overlay_remove", index: item.index });
  }
}

async function liftSelected() {
  const sel = editableSelection();
  if (!sel.length) { showAlert("Selecione um trecho ou sobreposição para o lift.", "error"); return; }
  let liftedV1 = false;
  for (const { trackId, item } of sel) {
    if (trackId === "V1") {
      liftedV1 = await applyOp({ type: "remove", index: item.index }) || liftedV1;
    } else {
      await applyOp({ type: "overlay_remove", index: item.index });
    }
  }
  if (liftedV1) showAlert("A V1 não tem lacunas: o lift removeu o trecho (ripple).", "success");
}

async function duplicateSelected() {
  const sel = editableSelection();
  if (!sel.length) { showAlert("Selecione um trecho ou sobreposição para duplicar.", "error"); return; }
  for (const { trackId, item } of sel) {
    if (trackId === "V1") await applyOp({ type: "duplicate", index: item.index });
    else await applyOp({ type: "overlay_duplicate", index: item.index });
  }
}

function trimSelectedToPlayhead(side) {
  const t = edState.player.getTime();
  const sel = editableSelection()[0] || editableUnderPlayhead();
  if (!sel) { showAlert("Selecione um trecho ou sobreposição para aparar.", "error"); return; }
  const { trackId, item } = sel;
  if (trackId === "V1") {
    const delta = side === "in" ? t - item.start : t - item.end;
    applyOp({ type: "trim", index: item.index, side, delta });
  } else {
    const start = side === "in" ? t : item.start;
    const end = side === "out" ? t : item.end;
    if (end - start < 0.1) { showAlert("O cursor precisa ficar dentro do intervalo da sobreposição.", "error"); return; }
    applyOp({ type: "overlay_span", index: item.index, start, end });
  }
}

function jumpEdit(direction) {
  const edges = edState.timeline.edgeTimes();
  const t = edState.player.getTime();
  const eps = 0.005;
  const target = direction > 0
    ? edges.find((e) => e > t + eps)
    : edges.slice().reverse().find((e) => e < t - eps);
  if (target !== undefined) seekTo(target);
}

function selectAllV1() {
  const v1 = edState.view.tracks.find((t) => t.id === "V1");
  if (v1) edState.timeline.setSelection(v1.items.map((it) => it.id));
}

/* ---------- reprodução e timecode ---------- */

function seekTo(t) {
  edState.player.setTime(t);
  edState.timeline.setPlayhead(t);
  updateTimecode(t);
}

function updateTimecode(t) {
  const el = document.getElementById("timeline-timecode");
  if (el) el.textContent = window.DMakerTimeline.formatTimecode(t, edState.view.fps);
}

function bumpPlay(direction) {
  edState.playLevel = edState.playDirection === direction ? Math.min(8, edState.playLevel * 2) : 1;
  edState.playDirection = direction;
  edState.player.setRate(direction * edState.playLevel);
}

function stopPlay() {
  edState.playDirection = 0;
  edState.playLevel = 1;
  edState.player.pause();
}

/* ---------- proxies (prévia de vídeos HEVC) ---------- */

function renderProxiesStatus(list) {
  const el = document.getElementById("proxies-status");
  if (!el) return;
  if (!list || !list.length) { el.textContent = ""; return; }
  const ready = list.filter((s) => s.ready).length;
  el.textContent = ready === list.length ? "" : `proxies de prévia: ${ready}/${list.length} prontos`;
}

function applyProxyStatus(list) {
  edState.proxyUrls = {};
  for (const s of list || []) {
    if (s.ready && s.url) edState.proxyUrls[s.src] = s.url;
  }
  if (edState.player) edState.player.setProxyUrls(edState.proxyUrls);
  renderProxiesStatus(list);
}

async function ensureProxies() {
  if (!state.currentProject) return;
  try {
    const status = await api.get(edProjectPath("/proxies"));
    applyProxyStatus(status);
    if (!status.length || status.every((s) => s.ready)) return;
    const result = await api.post(edProjectPath("/proxies"));
    applyProxyStatus(result.proxies);
    if (result.job && result.job.job_id) watchProxyJob(result.job.job_id);
  } catch (err) {
    console.error(err);
  }
}

function watchProxyJob(jobId) {
  if (edState.proxyEventSource) edState.proxyEventSource.close();
  const source = new EventSource(`/api/jobs/${jobId}/events`);
  edState.proxyEventSource = source;
  source.onmessage = (evt) => {
    let data;
    try { data = JSON.parse(evt.data); } catch { return; }
    if (data.kind === "end") {
      source.close();
      ensureProxies();
    }
  };
}

/* ---------- modal de atalhos ---------- */

const SHORTCUT_CATEGORIES = [
  ["reproducao", "Reprodução"], ["navegacao", "Navegação"], ["edicao", "Edição"],
  ["midia", "Mídia"], ["visualizacao", "Visualização"], ["geral", "Geral"],
];

function openShortcutsModal() {
  renderShortcutsModal();
}

function renderShortcutsModal() {
  const keymap = window.DMakerKeymap.loadKeymap();
  const rows = SHORTCUT_CATEGORIES.map(([cat, label]) => {
    const entries = keymap.filter((k) => k.category === cat);
    if (!entries.length) return "";
    return `<h4 class="shortcuts-cat">${edEsc(label)}</h4>` + entries.map((k) => `
      <div class="shortcuts-row">
        <span>${edEsc(k.label)}</span>
        <button type="button" class="shortcut-key-btn" data-rebind-id="${edEsc(k.id)}">${edEsc(window.DMakerKeymap.keyLabel(k.keys))}</button>
      </div>`).join("");
  }).join("");
  openModal(`
    <h3>Atalhos de teclado</h3>
    <p class="hint-text">Clique numa tecla para trocar: a próxima combinação que você apertar vira o novo atalho.</p>
    <div class="shortcuts-list" id="shortcuts-list">${rows}</div>
    <div class="modal-actions">
      <button type="button" class="btn" id="shortcuts-reset">Restaurar padrões</button>
      <button type="button" class="btn btn-accent" id="shortcuts-close">Fechar</button>
    </div>`);
  document.getElementById("shortcuts-close").addEventListener("click", closeModal);
  document.getElementById("shortcuts-reset").addEventListener("click", () => {
    window.DMakerKeymap.resetKeymap();
    if (edState.keymapController) edState.keymapController.rebuild();
    renderShortcutsModal();
  });
  document.getElementById("shortcuts-list").addEventListener("click", (e) => {
    const btn = e.target.closest("[data-rebind-id]");
    if (btn) startShortcutCapture(btn.dataset.rebindId, btn);
  });
}

/** Modo de captura: a próxima tecla (ignorando um modificador sozinho) vira a combinação
 * principal do atalho `id`. Avisa, mas não bloqueia, se a combinação já pertencer a outro atalho:
 * dois atalhos na mesma tecla é uma escolha da pessoa usando, não um erro. */
function startShortcutCapture(id, btn) {
  const original = btn.textContent;
  btn.textContent = "Pressione uma tecla...";
  btn.classList.add("capturing");

  function onKey(e) {
    if (["Control", "Alt", "Shift", "Meta"].includes(e.key)) return;
    e.preventDefault();
    e.stopPropagation();
    document.removeEventListener("keydown", onKey, true);
    if (e.key === "Escape") { btn.textContent = original; btn.classList.remove("capturing"); return; }
    const combo = window.DMakerKeymap.comboFromEvent(e);
    const conflict = window.DMakerKeymap.findKeyConflict(combo, id);
    window.DMakerKeymap.setKeyBinding(id, 0, combo);
    if (edState.keymapController) edState.keymapController.rebuild();
    if (conflict) {
      showAlert(`"${window.DMakerKeymap.keyLabel([combo])}" já era o atalho de "${conflict.label}"; agora os dois usam essa tecla.`, "error");
    }
    renderShortcutsModal();
  }
  document.addEventListener("keydown", onKey, true);
}

/* ---------- montagem dos widgets (uma vez) ---------- */

function initWidgets() {
  const tracksEl = document.getElementById("timeline-tracks");
  const playerEl = document.getElementById("live-player");

  edState.timeline = window.DMakerTimeline.create(tracksEl, {
    onSeek(t) { seekTo(t); },
    onSelect(item, trackId) { const ctx = contextForItem(trackId, item); setSelectionContext(ctx.typeKey, ctx.base); },
    onClearSelection() { setSelectionContext(null, null); },
    onOp(op) { applyOp(op); },
  });

  edState.player = window.DMakerPlayer.create(playerEl, {
    onTick(t, rate) {
      edState.timeline.setPlayhead(t);
      if (rate !== 0) edState.timeline.ensurePlayheadVisible();
      updateTimecode(t);
    },
    onMediaError() { ensureProxies(); },
  });

  edState.filters = window.DMakerFilters.create(document.getElementById("filters-body"), {
    applyOp,
    getSpec: () => state.spec,
  });
  edState.filters.setSelection(null, null);

  edState.media = window.DMakerMedia.create(document.getElementById("media-body"), {
    onInsertEnd(entry) { appendMediaEntry(entry); },
  });
  edState.media.setSpec(state.spec);

  setupMediaDrop(tracksEl);
  setupMediaToolbar();
  setupPanelToggles();

  const handlers = {
    play_pause() { if (edState.player.isPlaying()) stopPlay(); else bumpPlay(1); },
    pause() { stopPlay(); },
    play_forward(e) { if (!e.repeat) bumpPlay(1); },
    play_reverse(e) { if (!e.repeat) bumpPlay(-1); },
    step_back() { stopPlay(); edState.player.stepFrame(-1); seekTo(edState.player.getTime()); },
    step_forward() { stopPlay(); edState.player.stepFrame(1); seekTo(edState.player.getTime()); },
    prev_edit() { jumpEdit(-1); },
    next_edit() { jumpEdit(1); },
    go_start() { stopPlay(); seekTo(0); },
    go_end() { stopPlay(); seekTo(edState.view.total); },
    back_1s() { seekTo(Math.max(0, edState.player.getTime() - 1)); },
    forward_1s() { seekTo(Math.min(edState.view.total, edState.player.getTime() + 1)); },
    split() { splitAtPlayhead(); },
    remove_ripple() { removeSelected(); },
    lift() { liftSelected(); },
    trim_in() { trimSelectedToPlayhead("in"); },
    trim_out() { trimSelectedToPlayhead("out"); },
    undo() { undo(); },
    redo() { redo(); },
    duplicate() { duplicateSelected(); },
    select_all() { selectAllV1(); },
    zoom_in() { edState.timeline.zoomIn(); },
    zoom_out() { edState.timeline.zoomOut(); },
    zoom_fit() { edState.timeline.zoomFit(tracksEl.clientWidth); },
    toggle_snap() { toggleSnapButton(); },
    toggle_ripple() { toggleRippleLabel(); },
    clear_selection() { edState.timeline.clearSelection(); },
    show_shortcuts() { openShortcutsModal(); },
    media_append() { const entry = edState.media.getSelected(); if (entry) appendMediaEntry(entry); else showAlert("Selecione um arquivo no painel de mídia.", "error"); },
    media_insert() { const entry = edState.media.getSelected(); if (entry) insertMediaEntryAtPlayhead(entry); else showAlert("Selecione um arquivo no painel de mídia.", "error"); },
  };
  edState.keymapController = window.DMakerKeymap.bindKeymap(handlers);

  const toolbarActions = {
    "btn-split": handlers.split,
    "btn-remove": handlers.remove_ripple,
    "btn-lift": handlers.lift,
    "btn-duplicate": handlers.duplicate,
    "btn-trim-in": handlers.trim_in,
    "btn-trim-out": handlers.trim_out,
    "btn-snap": handlers.toggle_snap,
    "btn-ripple": handlers.toggle_ripple,
    "btn-zoom-out": handlers.zoom_out,
    "btn-zoom-in": handlers.zoom_in,
    "btn-zoom-fit": handlers.zoom_fit,
    "btn-shortcuts": handlers.show_shortcuts,
  };
  for (const [id, fn] of Object.entries(toolbarActions)) {
    const btn = document.getElementById(id);
    if (btn) btn.addEventListener("click", () => fn({ repeat: false }));
  }
  updateSnapButton();
  setupResizer();
}

/* ---------- painel de mídia: inserir na linha do tempo ---------- */

/** Posição de inserção na V1 (índice do trecho) para um tempo dado: antes do primeiro trecho que
 * começa depois de `time`, ou no fim se não houver nenhum. */
function v1InsertIndexAt(time) {
  const v1 = edState.view.tracks.find((t) => t.id === "V1");
  if (!v1 || !v1.items.length) return 0;
  const idx = v1.items.findIndex((it) => it.start > time + 0.001);
  return idx === -1 ? v1.items.length : idx;
}

function segmentFromMediaEntry(entry) {
  if (entry.kind === "image") {
    return { type: "image", src: entry.src, duration: 3, motion: "zoom-in", motion_amount: 0.12 };
  }
  const base = { type: "clip", start: 0, speed: 1, volume: 1, mute: false };
  return entry.source ? { ...base, source: entry.source } : { ...base, src: entry.src };
}

function insertMediaEntryAt(entry, index) {
  if (entry.kind === "audio") {
    showAlert('Arquivos de áudio entram pelo botão "Música", não na V1.', "error");
    return;
  }
  applyOp({ type: "insert", index, segment: segmentFromMediaEntry(entry) });
}

function appendMediaEntry(entry) {
  const v1 = edState.view.tracks.find((t) => t.id === "V1");
  insertMediaEntryAt(entry, v1 ? v1.items.length : 0);
}

function insertMediaEntryAtPlayhead(entry) {
  insertMediaEntryAt(entry, v1InsertIndexAt(edState.player.getTime()));
}

/** Sobreposição (PiP para clipe/fonte, imagem para o resto) a partir de uma entrada de mídia
 * solta fora da V1. Não existe uma op de "inserir sobreposição": manda o array inteiro por
 * set_field, como os outros pontos da interface que mexem em `overlays`. */
function overlayFromMediaEntry(entry, time) {
  const end = Math.min(edState.view.total, time + 3);
  if (entry.kind === "image") {
    return { type: "image", src: entry.src, position: "top-right", width: 0.22, opacity: 1, start: time, end };
  }
  const base = { type: "video", start: time, end, offset: 0, position: "bottom-right", width: 0.28, shape: "rounded", volume: 1, animation: "fade", fade: 0.3 };
  return entry.source ? { ...base, source: entry.source } : { ...base, src: entry.src };
}

function insertOverlayFromMediaEntry(entry, time) {
  if (entry.kind === "audio") {
    showAlert('Arquivos de áudio entram pelo botão "Música", não como sobreposição.', "error");
    return;
  }
  const overlays = (state.spec.overlays || []).concat([overlayFromMediaEntry(entry, time)]);
  applyOp({ type: "set_field", path: "overlays", value: overlays });
}

function setupMediaDrop(tracksEl) {
  tracksEl.addEventListener("dragover", (e) => {
    if ([...e.dataTransfer.types].includes(window.DMakerMedia.MEDIA_DND_MIME)) e.preventDefault();
  });
  tracksEl.addEventListener("drop", (e) => {
    const raw = e.dataTransfer.getData(window.DMakerMedia.MEDIA_DND_MIME);
    if (!raw) return;
    e.preventDefault();
    let entry;
    try { entry = JSON.parse(raw); } catch { return; }
    const hit = edState.timeline.hitTest(e.clientX, e.clientY);
    if (hit.trackId === "V1") insertMediaEntryAt(entry, v1InsertIndexAt(hit.time));
    else insertOverlayFromMediaEntry(entry, hit.time);
  });
}

function setupMediaToolbar() {
  document.getElementById("btn-add-media").addEventListener("click", () => {
    openFileBrowser({
      multi: false,
      onSelect: (paths) => {
        closeModal();
        const path = paths[0];
        const kind = mdKindFromExt(path);
        if (kind === "audio") {
          applyOp({ type: "set_field", path: "audio.music", value: { src: path, volume: 0.18 } });
          return;
        }
        appendMediaEntry({ kind, src: path, label: baseName(path) });
      },
    });
  });

  document.getElementById("btn-media-text").addEventListener("click", () => {
    const t = edState.player.getTime();
    const overlays = (state.spec.overlays || []).concat([
      { type: "text", text: "Novo texto", role: "title", start: t, end: Math.min(edState.view.total, t + 3) },
    ]);
    applyOp({ type: "set_field", path: "overlays", value: overlays });
  });

  document.getElementById("btn-media-card").addEventListener("click", () => {
    const v1 = edState.view.tracks.find((t) => t.id === "V1");
    applyOp({
      type: "insert",
      index: v1 ? v1.items.length : 0,
      segment: { type: "card", title: "Novo cartão", duration: 3, motion: "zoom-in" },
    });
  });

  document.getElementById("btn-media-logo").addEventListener("click", () => {
    const t = edState.player.getTime();
    const overlays = (state.spec.overlays || []).concat([
      { type: "image", src: "logo", position: "top-right", width: 0.22, start: t, end: Math.min(edState.view.total, t + 3) },
    ]);
    applyOp({ type: "set_field", path: "overlays", value: overlays });
  });

  document.getElementById("btn-media-music").addEventListener("click", () => {
    openFileBrowser({
      multi: false,
      onSelect: (paths) => {
        closeModal();
        applyOp({ type: "set_field", path: "audio.music", value: { src: paths[0], volume: 0.18 } });
      },
    });
  });
}

/* ---------- painéis laterais ocultáveis ---------- */

const PANEL_VISIBILITY_KEYS = { filters: "dmaker.panels.filtersHidden", media: "dmaker.panels.mediaHidden" };

function applyPanelVisibility() {
  const filtersHidden = localStorage.getItem(PANEL_VISIBILITY_KEYS.filters) === "1";
  const mediaHidden = localStorage.getItem(PANEL_VISIBILITY_KEYS.media) === "1";
  document.getElementById("panel-filters").hidden = filtersHidden;
  document.getElementById("panel-media").hidden = mediaHidden;
  const bf = document.getElementById("btn-toggle-filters");
  if (bf) bf.classList.toggle("active", !filtersHidden);
  const bm = document.getElementById("btn-toggle-media");
  if (bm) bm.classList.toggle("active", !mediaHidden);
}

function setupPanelToggles() {
  document.getElementById("btn-toggle-filters").addEventListener("click", () => {
    const key = PANEL_VISIBILITY_KEYS.filters;
    localStorage.setItem(key, localStorage.getItem(key) === "1" ? "0" : "1");
    applyPanelVisibility();
  });
  document.getElementById("btn-toggle-media").addEventListener("click", () => {
    const key = PANEL_VISIBILITY_KEYS.media;
    localStorage.setItem(key, localStorage.getItem(key) === "1" ? "0" : "1");
    applyPanelVisibility();
  });
  applyPanelVisibility();
}

function toggleSnapButton() {
  edState.timeline.toggleSnap();
  updateSnapButton();
}

function updateSnapButton() {
  const btn = document.getElementById("btn-snap");
  if (btn) btn.classList.toggle("active", edState.timeline.isSnapEnabled());
}

let rippleLabelOn = true;

function toggleRippleLabel() {
  rippleLabelOn = !rippleLabelOn;
  const btn = document.getElementById("btn-ripple");
  if (btn) btn.textContent = rippleLabelOn ? "Ripple: V1" : "Ripple: V1 (sempre)";
}

function setupResizer() {
  const resizer = document.getElementById("timeline-resizer");
  const editorEl = document.getElementById("timeline-editor");
  if (!resizer || !editorEl) return;
  let dragging = false;
  resizer.addEventListener("mousedown", (e) => {
    dragging = true;
    e.preventDefault();
  });
  document.addEventListener("mousemove", (e) => {
    if (!dragging) return;
    const rect = editorEl.getBoundingClientRect();
    const ratio = Math.min(0.8, Math.max(0.15, (e.clientY - rect.top) / rect.height));
    editorEl.style.setProperty("--player-h", `${(ratio * 100).toFixed(1)}%`);
  });
  document.addEventListener("mouseup", () => {
    dragging = false;
  });
}

/* ---------- ponto de entrada ---------- */

async function open(name, spec) {
  state.currentProject = name;
  state.spec = spec || state.spec;
  edState.undoStack = [];
  edState.redoStack = [];
  markDirty(false);
  document.getElementById("timeline-empty").hidden = true;
  document.getElementById("timeline-editor").hidden = false;
  if (!edState.timeline) initWidgets();
  edState.timeline.clearSelection();
  setSelectionContext(null, null);
  edState.proxyUrls = {};
  try {
    edState.theme = await api.get(edProjectPath("/theme"));
  } catch {
    edState.theme = { colors: {}, font: "", logos: {}, no_dash: false };
  }
  // esvazia o palco enquanto a vista do projeto novo ainda não chegou, para não mostrar por um
  // instante o conteúdo do projeto anterior (o cartão de prévia é autossuficiente por parâmetros,
  // mas a vista e a spec ainda seriam as antigas até o refreshViewNow abaixo terminar).
  if (edState.player) {
    edState.player.setData({
      theme: edState.theme,
      proxyUrls: edState.proxyUrls,
      view: { total: 0, fps: 30, tracks: [], sources: {} },
      spec: state.spec,
    });
  }
  await refreshViewNow();
  ensureProxies();
}

window.DMakerEditor = { open, refreshView, markSaved, applyOp };
