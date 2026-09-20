"use strict";
/*
 * DMaker - organização da tela: painéis arrastáveis e redimensionáveis, com layouts nomeados
 * (embutidos, inspirados no menu "Layout" do Shotcut, e salvos pela pessoa usando a interface).
 *
 * Um layout é um objeto simples e serializável:
 *   { version: 1, areas: {<slot>: <painel>}, sizes: {<divisor>: <número>}, hidden: [<painel>] }
 *
 * Grade fixa de slots (dentro da aba Linha do tempo): "top-center" (linha inteira, em cima),
 * "top-left", "bottom" e "top-right" (linha de baixo, três colunas). O painel Andamento
 * ("dock-bottom") e a barra lateral ("sidebar") ficam fora dessa grade, em posição fixa; o layout
 * só controla o tamanho e se estão ocultos/recolhidos.
 *
 * Painéis: "player", "filters", "media", "timeline" (movidos entre os quatro slots), "progress"
 * (recolhe/expande, reaproveitando o toggle existente do painel de Andamento), "sidebar" (só
 * redimensiona) e "properties" (reservado para o formulário da aba Propriedades virar encaixável;
 * ainda não tem um lugar na grade, mas já é um nome de painel válido).
 *
 * window.DMakerLayout:
 *   normalizeLayout(obj), swapPanels(layout, a, b), builtinLayouts()   funções puras, testáveis
 *   applyLayout(layout)   move os painéis para os slots, aplica tamanhos e ocultos no DOM
 *   init()                monta a grade, o seletor da barra superior e os manipuladores de arrasto
 *   refresh()             chamado após trocar de aba: redesenha o que dependa de layout
 */

const DMAKER_LAYOUT_STORAGE_KEY = "dmaker.layout.current";
const DMAKER_LAYOUT_DRAG_MIME = "application/x-dmaker-panel";

const KNOWN_PANELS = ["player", "filters", "media", "timeline", "progress", "properties", "sidebar"];
const KNOWN_SLOTS = ["top-left", "top-center", "top-right", "bottom", "dock-bottom", "sidebar"];
const MOVABLE_PANELS = ["player", "filters", "media", "timeline"];

const SIZE_KEYS = ["row-top", "col-left", "col-right", "col-sidebar"];
const SIZE_DEFAULTS = { "row-top": 0.42, "col-left": 240, "col-right": 240, "col-sidebar": 300 };
const SIZE_RANGES = {
  "row-top": [0.1, 0.85],
  "col-left": [160, 560],
  "col-right": [160, 560],
  "col-sidebar": [200, 520],
};

/* ==================== funções puras ==================== */

function lyClamp(value, min, max) {
  return Math.min(max, Math.max(min, value));
}

/** Devolve um layout completo e são a partir de um objeto qualquer (localStorage, servidor,
 * layout embutido): entradas com slot/painel desconhecido são descartadas, tamanhos fora da
 * faixa são cortados e os que faltam recebem o padrão. Nunca lança erro. */
function normalizeLayout(raw) {
  const obj = raw && typeof raw === "object" ? raw : {};
  const rawAreas = obj.areas && typeof obj.areas === "object" ? obj.areas : {};
  const areas = {};
  for (const [slot, panel] of Object.entries(rawAreas)) {
    if (KNOWN_SLOTS.includes(slot) && KNOWN_PANELS.includes(panel)) areas[slot] = panel;
  }
  const hidden = Array.isArray(obj.hidden) ? obj.hidden.filter((p) => KNOWN_PANELS.includes(p)) : [];
  const rawSizes = obj.sizes && typeof obj.sizes === "object" ? obj.sizes : {};
  const sizes = {};
  for (const key of SIZE_KEYS) {
    const [min, max] = SIZE_RANGES[key];
    const value = typeof rawSizes[key] === "number" && Number.isFinite(rawSizes[key]) ? rawSizes[key] : SIZE_DEFAULTS[key];
    sizes[key] = lyClamp(value, min, max);
  }
  return { version: 1, areas, sizes, hidden };
}

/** Layout novo com os painéis `a` e `b` trocados de slot. Se só um dos dois estiver na grade,
 * ele simplesmente assume o slot do outro (o que não estava na grade continua fora dela). */
function swapPanels(layout, a, b) {
  const norm = normalizeLayout(layout);
  const areas = { ...norm.areas };
  const slotOf = (panel) => Object.keys(areas).find((slot) => areas[slot] === panel);
  const slotA = slotOf(a);
  const slotB = slotOf(b);
  if (slotA && slotB) {
    areas[slotA] = b;
    areas[slotB] = a;
  } else if (slotA && !slotB) {
    areas[slotA] = b;
  } else if (slotB && !slotA) {
    areas[slotB] = a;
  }
  return { ...norm, areas };
}

const EDITING_AREAS = { "top-center": "player", "top-left": "filters", bottom: "timeline", "top-right": "media" };

/** Layouts embutidos, inspirados no menu "Layout" do Shotcut. "Edição" reproduz a disposição
 * atual (o painel de Andamento recolhido, como sempre foi); os outros só mudam tamanhos e o que
 * fica oculto, sem precisar mover painel nenhum de slot. */
function builtinLayouts() {
  return {
    Edição: normalizeLayout({ areas: EDITING_AREAS, sizes: {}, hidden: ["progress"] }),
    Efeitos: normalizeLayout({ areas: EDITING_AREAS, sizes: { "col-left": 420 }, hidden: ["progress", "media"] }),
    Áudio: normalizeLayout({ areas: EDITING_AREAS, sizes: { "row-top": 0.16 }, hidden: ["progress"] }),
    Player: normalizeLayout({ areas: EDITING_AREAS, sizes: { "row-top": 0.72 }, hidden: ["progress"] }),
    Revisão: normalizeLayout({ areas: EDITING_AREAS, sizes: { "row-top": 0.22 }, hidden: [] }),
  };
}

/* ==================== estado e persistência ==================== */

let currentLayout = normalizeLayout(builtinLayouts().Edição);
let currentLayoutName = "Edição";
let savedLayouts = {};

function loadStoredCurrent() {
  try {
    const raw = localStorage.getItem(DMAKER_LAYOUT_STORAGE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw);
    return { name: parsed.name || null, layout: normalizeLayout(parsed.layout) };
  } catch {
    return null;
  }
}

function persistCurrent() {
  try {
    localStorage.setItem(
      DMAKER_LAYOUT_STORAGE_KEY,
      JSON.stringify({ name: currentLayoutName, layout: currentLayout })
    );
  } catch {
    /* localStorage indisponível (janela privada, por exemplo): o layout só não sobrevive a um recarregamento */
  }
}

/* ==================== aplicação no DOM ==================== */

function panelElement(name) {
  return document.querySelector(`[data-panel="${name}"]`);
}

function slotElement(slot) {
  return document.querySelector(`[data-slot="${slot}"]`);
}

/** Move cada painel para o slot indicado em `areas`, aplica os tamanhos como variáveis CSS e
 * oculta/recolhe os painéis da lista `hidden`. Avisa o resto da interface (player, linha do
 * tempo, forma de onda) para redesenhar, porque o tamanho dos contêineres pode ter mudado. */
function applyLayout(layout) {
  const norm = normalizeLayout(layout);

  for (const [slot, panelName] of Object.entries(norm.areas)) {
    const slotEl = slotElement(slot);
    const panelEl = panelElement(panelName);
    if (slotEl && panelEl) slotEl.appendChild(panelEl);
  }

  const grid = document.getElementById("tl-layout-grid");
  if (grid) {
    grid.style.setProperty("--row-top", `${(norm.sizes["row-top"] * 100).toFixed(1)}%`);
    grid.style.setProperty("--col-left", `${norm.sizes["col-left"]}px`);
    grid.style.setProperty("--col-right", `${norm.sizes["col-right"]}px`);
  }
  const layoutRoot = document.querySelector(".layout");
  if (layoutRoot) layoutRoot.style.setProperty("--col-sidebar", `${norm.sizes["col-sidebar"]}px`);

  for (const panelName of KNOWN_PANELS) {
    const isHidden = norm.hidden.includes(panelName);
    if (panelName === "progress") {
      const progressEl = document.getElementById("progress-panel");
      if (progressEl) progressEl.classList.toggle("collapsed", isHidden);
    } else {
      const panelEl = panelElement(panelName);
      if (panelEl) panelEl.hidden = isHidden;
    }
  }

  currentLayout = norm;
  window.dispatchEvent(new Event("resize"));
  document.dispatchEvent(new CustomEvent("dmaker:layout-applied"));
}

function setCurrentLayout(name, layout) {
  currentLayoutName = name;
  applyLayout(layout);
  persistCurrent();
  renderSelectorOptions();
}

/* ==================== seletor de layouts (barra superior) ==================== */

const LAYOUT_SELECT_SAVE_AS = "__save_as__";
const LAYOUT_SELECT_DELETE = "__delete_current__";
const LAYOUT_SELECT_RESTORE = "__restore_default__";

function isBuiltinName(name) {
  return Object.prototype.hasOwnProperty.call(builtinLayouts(), name);
}

function renderSelectorOptions() {
  const select = document.getElementById("layout-select");
  if (!select) return;
  const builtins = Object.keys(builtinLayouts());
  const savedNames = Object.keys(savedLayouts).filter((n) => !builtins.includes(n));
  const groups = [
    { label: "Embutidos", names: builtins },
    { label: "Salvos", names: savedNames },
  ].filter((g) => g.names.length);
  const optionsHtml = groups
    .map(
      (g) =>
        `<optgroup label="${g.label}">${g.names
          .map((n) => `<option value="${n}" ${n === currentLayoutName ? "selected" : ""}>${n}</option>`)
          .join("")}</optgroup>`
    )
    .join("");
  select.innerHTML =
    optionsHtml +
    `<option value="${LAYOUT_SELECT_SAVE_AS}">Salvar layout como...</option>` +
    `<option value="${LAYOUT_SELECT_DELETE}">Excluir layout atual</option>` +
    `<option value="${LAYOUT_SELECT_RESTORE}">Restaurar padrão</option>`;
  if (!builtins.includes(currentLayoutName) && !savedNames.includes(currentLayoutName)) {
    select.value = "";
  } else {
    select.value = currentLayoutName;
  }
}

async function refreshSavedLayouts() {
  try {
    const resp = await fetch("/api/layouts");
    if (!resp.ok) return;
    const data = await resp.json();
    savedLayouts = data.layouts || {};
  } catch {
    savedLayouts = {};
  }
  renderSelectorOptions();
}

function openSaveLayoutModal() {
  if (!window.openModal) return;
  window.openModal(`
    <h3>Salvar layout como</h3>
    <div class="field"><label>Nome</label><input type="text" id="ly-save-name" value="${currentLayoutName === "Edição" ? "" : currentLayoutName}"></div>
    <div class="modal-actions">
      <button type="button" class="btn" id="ly-save-cancel">Cancelar</button>
      <button type="button" class="btn btn-accent" id="ly-save-confirm">Salvar</button>
    </div>`);
  const input = document.getElementById("ly-save-name");
  if (input) input.focus();
  const cancel = document.getElementById("ly-save-cancel");
  const confirm = document.getElementById("ly-save-confirm");
  if (cancel) cancel.addEventListener("click", () => window.closeModal && window.closeModal());
  if (confirm) {
    confirm.addEventListener("click", async () => {
      const name = (input ? input.value : "").trim();
      if (!name) return;
      try {
        await fetch(`/api/layouts/${encodeURIComponent(name)}`, {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(currentLayout),
        });
        await refreshSavedLayouts();
        currentLayoutName = name;
        persistCurrent();
        renderSelectorOptions();
        if (window.closeModal) window.closeModal();
        if (window.showAlert) window.showAlert("Layout salvo.", "success");
      } catch (err) {
        if (window.handleError) window.handleError(err);
      }
    });
  }
}

async function deleteCurrentLayout() {
  if (isBuiltinName(currentLayoutName)) {
    if (window.showAlert) window.showAlert("Layouts embutidos não podem ser excluídos.", "error");
    renderSelectorOptions();
    return;
  }
  try {
    await fetch(`/api/layouts/${encodeURIComponent(currentLayoutName)}`, { method: "DELETE" });
    await refreshSavedLayouts();
    setCurrentLayout("Edição", builtinLayouts().Edição);
  } catch (err) {
    if (window.handleError) window.handleError(err);
  }
}

function resolveLayoutByName(name) {
  const builtins = builtinLayouts();
  if (builtins[name]) return builtins[name];
  if (savedLayouts[name]) return normalizeLayout(savedLayouts[name]);
  return null;
}

function setupLayoutSelect() {
  const select = document.getElementById("layout-select");
  if (!select) return;
  select.addEventListener("change", () => {
    const value = select.value;
    if (value === LAYOUT_SELECT_SAVE_AS) {
      openSaveLayoutModal();
      renderSelectorOptions();
      return;
    }
    if (value === LAYOUT_SELECT_DELETE) {
      deleteCurrentLayout();
      return;
    }
    if (value === LAYOUT_SELECT_RESTORE) {
      setCurrentLayout("Edição", builtinLayouts().Edição);
      return;
    }
    const layout = resolveLayoutByName(value);
    if (layout) setCurrentLayout(value, layout);
  });
}

/* ==================== arrasto dos painéis (.panel-title) ==================== */

function setupDragAndDrop() {
  for (const name of MOVABLE_PANELS) {
    const panelEl = panelElement(name);
    if (!panelEl) continue;
    const title = panelEl.querySelector(":scope > .panel-title");
    if (title) {
      title.draggable = true;
      title.addEventListener("dragstart", (e) => {
        e.dataTransfer.setData(DMAKER_LAYOUT_DRAG_MIME, name);
        e.dataTransfer.effectAllowed = "move";
        panelEl.classList.add("panel-dragging");
      });
      title.addEventListener("dragend", () => panelEl.classList.remove("panel-dragging"));
    }
    panelEl.addEventListener("dragover", (e) => {
      if ([...e.dataTransfer.types].includes(DMAKER_LAYOUT_DRAG_MIME)) {
        e.preventDefault();
        panelEl.classList.add("panel-drop-target");
      }
    });
    panelEl.addEventListener("dragleave", () => panelEl.classList.remove("panel-drop-target"));
    panelEl.addEventListener("drop", (e) => {
      panelEl.classList.remove("panel-drop-target");
      const source = e.dataTransfer.getData(DMAKER_LAYOUT_DRAG_MIME);
      if (!source || source === name) return;
      e.preventDefault();
      const swapped = swapPanels(currentLayout, source, name);
      applyLayout(swapped);
      persistCurrent();
    });
  }
}

function setupHideButtons() {
  document.querySelectorAll("[data-panel-hide]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const name = btn.dataset.panelHide;
      const hidden = currentLayout.hidden.includes(name)
        ? currentLayout.hidden.filter((p) => p !== name)
        : currentLayout.hidden.concat([name]);
      applyLayout({ ...currentLayout, hidden });
      persistCurrent();
    });
  });
}

/* ==================== divisores (redimensionar) ==================== */

/** Liga um divisor vertical (arrasto horizontal) a uma variável CSS em pixels, gravando o valor
 * final em `sizes[sizeKey]` quando a pessoa solta o botão. */
function bindColumnDivider(el, { cssVar, sizeKey, invert }) {
  if (!el) return;
  const grid = document.getElementById("tl-layout-grid");
  if (!grid) return;
  const [min, max] = SIZE_RANGES[sizeKey];
  let dragging = false;
  let startX = 0;
  let startValue = 0;
  el.addEventListener("mousedown", (e) => {
    dragging = true;
    startX = e.clientX;
    startValue = currentLayout.sizes[sizeKey];
    e.preventDefault();
  });
  window.addEventListener("mousemove", (e) => {
    if (!dragging) return;
    const delta = (e.clientX - startX) * (invert ? -1 : 1);
    const value = lyClamp(startValue + delta, min, max);
    grid.style.setProperty(cssVar, `${value}px`);
  });
  window.addEventListener("mouseup", () => {
    if (!dragging) return;
    dragging = false;
    const value = parseFloat(grid.style.getPropertyValue(cssVar)) || startValue;
    currentLayout = { ...currentLayout, sizes: { ...currentLayout.sizes, [sizeKey]: value } };
    persistCurrent();
    window.dispatchEvent(new Event("resize"));
  });
}

/** Liga o divisor horizontal (arrasto vertical) entre a linha do player e a grade de baixo. */
function bindRowDivider(el) {
  if (!el) return;
  const grid = document.getElementById("tl-layout-grid");
  if (!grid) return;
  const [min, max] = SIZE_RANGES["row-top"];
  let dragging = false;
  el.addEventListener("mousedown", (e) => {
    dragging = true;
    e.preventDefault();
  });
  window.addEventListener("mousemove", (e) => {
    if (!dragging) return;
    const rect = grid.getBoundingClientRect();
    const ratio = lyClamp((e.clientY - rect.top) / rect.height, min, max);
    grid.style.setProperty("--row-top", `${(ratio * 100).toFixed(1)}%`);
  });
  window.addEventListener("mouseup", () => {
    if (!dragging) return;
    dragging = false;
    const value = parseFloat(grid.style.getPropertyValue("--row-top")) / 100;
    currentLayout = { ...currentLayout, sizes: { ...currentLayout.sizes, "row-top": value || SIZE_DEFAULTS["row-top"] } };
    persistCurrent();
    window.dispatchEvent(new Event("resize"));
  });
}

/** Liga o divisor entre a barra lateral e a área principal. */
function bindSidebarDivider(el) {
  if (!el) return;
  const layoutRoot = document.querySelector(".layout");
  if (!layoutRoot) return;
  const [min, max] = SIZE_RANGES["col-sidebar"];
  let dragging = false;
  let startX = 0;
  let startValue = 0;
  el.addEventListener("mousedown", (e) => {
    dragging = true;
    startX = e.clientX;
    startValue = currentLayout.sizes["col-sidebar"];
    e.preventDefault();
  });
  window.addEventListener("mousemove", (e) => {
    if (!dragging) return;
    const value = lyClamp(startValue + (e.clientX - startX), min, max);
    layoutRoot.style.setProperty("--col-sidebar", `${value}px`);
  });
  window.addEventListener("mouseup", () => {
    if (!dragging) return;
    dragging = false;
    const value = parseFloat(layoutRoot.style.getPropertyValue("--col-sidebar")) || startValue;
    currentLayout = { ...currentLayout, sizes: { ...currentLayout.sizes, "col-sidebar": value } };
    persistCurrent();
    window.dispatchEvent(new Event("resize"));
  });
}

function setupDividers() {
  bindRowDivider(document.getElementById("tl-divider-row"));
  bindColumnDivider(document.getElementById("tl-divider-col-left"), { cssVar: "--col-left", sizeKey: "col-left" });
  bindColumnDivider(document.getElementById("tl-divider-col-right"), {
    cssVar: "--col-right",
    sizeKey: "col-right",
    invert: true,
  });
  bindSidebarDivider(document.getElementById("sidebar-divider"));
}

/* ==================== ponto de entrada ==================== */

function init() {
  const stored = loadStoredCurrent();
  currentLayoutName = stored && stored.name ? stored.name : "Edição";
  applyLayout(stored ? stored.layout : builtinLayouts().Edição);
  setupDragAndDrop();
  setupHideButtons();
  setupDividers();
  setupLayoutSelect();
  refreshSavedLayouts();
}

/** Chamado após trocar de aba: alguns painéis (player, linha do tempo) só calculam o próprio
 * tamanho quando ficam visíveis, então um "resize" extra garante que redesenhem certo. */
function refresh() {
  window.dispatchEvent(new Event("resize"));
}

window.DMakerLayout = {
  normalizeLayout,
  swapPanels,
  builtinLayouts,
  applyLayout,
  init,
  refresh,
};
