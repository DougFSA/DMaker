"use strict";
/*
 * DMaker - tabela de atalhos de teclado (padrão inspirado no Shotcut).
 *
 * Expõe window.DMakerKeymap com:
 *   KEYMAP_DEFAULTS  - tabela padrão (id, rótulo, teclas, categoria)
 *   loadKeymap()     - tabela padrão mesclada com overrides salvos (localStorage)
 *   bindKeymap(map)  - liga teclado -> ids de ação; ignora foco em campos de formulário
 *   keyLabel(keys)   - texto amigável para exibir um atalho
 *
 * A tela de rebind (editar as teclas) fica para uma tarefa futura; o formato de
 * armazenamento (objeto id -> lista de combinações em localStorage["dmaker.keymap"])
 * já está pronto para ela.
 */

const KEYMAP_STORAGE_KEY = "dmaker.keymap";

const KEYMAP_DEFAULTS = [
  { id: "play_pause", label: "Reproduzir ou pausar", keys: ["Space"], category: "reproducao" },
  { id: "pause", label: "Pausar", keys: ["k"], category: "reproducao" },
  { id: "play_reverse", label: "Retroceder (repetir acelera 2x/4x/8x)", keys: ["j"], category: "reproducao" },
  { id: "play_forward", label: "Avançar (repetir acelera 2x/4x/8x)", keys: ["l"], category: "reproducao" },
  { id: "step_back", label: "Um quadro para trás", keys: ["ArrowLeft"], category: "navegacao" },
  { id: "step_forward", label: "Um quadro para frente", keys: ["ArrowRight"], category: "navegacao" },
  { id: "prev_edit", label: "Edição anterior", keys: ["Alt+ArrowLeft"], category: "navegacao" },
  { id: "next_edit", label: "Próxima edição", keys: ["Alt+ArrowRight"], category: "navegacao" },
  { id: "go_start", label: "Ir ao início", keys: ["Home"], category: "navegacao" },
  { id: "go_end", label: "Ir ao fim", keys: ["End"], category: "navegacao" },
  { id: "back_1s", label: "Voltar 1 segundo", keys: ["PageUp"], category: "navegacao" },
  { id: "forward_1s", label: "Avançar 1 segundo", keys: ["PageDown"], category: "navegacao" },
  { id: "split", label: "Cortar no cursor", keys: ["s"], category: "edicao" },
  { id: "remove_ripple", label: "Remover (ripple)", keys: ["x", "Delete"], category: "edicao" },
  { id: "lift", label: "Lift (remover sem deixar lacuna na V1)", keys: ["z"], category: "edicao" },
  { id: "trim_in", label: "Aparar entrada até o cursor", keys: ["i"], category: "edicao" },
  { id: "trim_out", label: "Aparar saída até o cursor", keys: ["o"], category: "edicao" },
  { id: "undo", label: "Desfazer", keys: ["Ctrl+z"], category: "geral" },
  { id: "redo", label: "Refazer", keys: ["Ctrl+y", "Ctrl+Shift+z"], category: "geral" },
  { id: "save", label: "Salvar", keys: ["Ctrl+s"], category: "geral" },
  { id: "duplicate", label: "Duplicar", keys: ["Ctrl+d"], category: "edicao" },
  { id: "select_all", label: "Selecionar tudo", keys: ["Ctrl+a"], category: "edicao" },
  { id: "zoom_in", label: "Aproximar", keys: ["="], category: "visualizacao" },
  { id: "zoom_out", label: "Afastar", keys: ["-"], category: "visualizacao" },
  { id: "zoom_fit", label: "Ajustar à janela", keys: ["0"], category: "visualizacao" },
  { id: "toggle_snap", label: "Alternar encaixe (snap)", keys: ["Ctrl+p"], category: "visualizacao" },
  { id: "toggle_ripple", label: "Alternar rótulo de ripple", keys: ["Ctrl+r"], category: "edicao" },
  { id: "clear_selection", label: "Limpar seleção", keys: ["Escape"], category: "geral" },
  { id: "show_shortcuts", label: "Mostrar atalhos", keys: ["?"], category: "geral" },
  { id: "media_append", label: "Acrescentar a mídia selecionada no fim da V1", keys: ["a"], category: "midia" },
  { id: "media_insert", label: "Inserir a mídia selecionada no cursor", keys: ["v"], category: "midia" },
];

function isTypingTarget(el) {
  if (!el) return false;
  const tag = el.tagName;
  return tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT" || !!el.isContentEditable;
}

/** Normaliza um evento de teclado para uma combinação canônica ("Ctrl+Alt+Shift+tecla"),
 * na mesma ordem usada em KEYMAP_DEFAULTS, para que as duas formas sempre coincidam. */
function comboFromEvent(e) {
  let key = e.key === " " ? "Space" : e.key;
  if (key.length === 1) key = key.toLowerCase();
  const parts = [];
  if (e.ctrlKey || e.metaKey) parts.push("Ctrl");
  if (e.altKey) parts.push("Alt");
  if (e.shiftKey) parts.push("Shift");
  parts.push(key);
  return parts.join("+");
}

function loadKeymap() {
  let overrides = {};
  try {
    const raw = localStorage.getItem(KEYMAP_STORAGE_KEY);
    if (raw) overrides = JSON.parse(raw) || {};
  } catch {
    overrides = {};
  }
  return KEYMAP_DEFAULTS.map((entry) => ({
    ...entry,
    keys: Array.isArray(overrides[entry.id]) && overrides[entry.id].length ? overrides[entry.id] : entry.keys,
  }));
}

/** Liga o teclado do documento aos ids de `handlers` (id -> function(event)).
 * Devolve { unbind, rebuild }: unbind() remove o listener; rebuild() relê o keymap (defaults +
 * overrides) do zero, para um rebind feito na hora (tela de atalhos) valer sem precisar recarregar
 * a página. Ignora teclas quando o foco está num campo de formulário, para não atrapalhar quem
 * está digitando. */
function bindKeymap(handlers) {
  let byCombo = new Map();

  function rebuild() {
    byCombo = new Map();
    for (const entry of loadKeymap()) {
      for (const combo of entry.keys) {
        if (!byCombo.has(combo)) byCombo.set(combo, []);
        byCombo.get(combo).push(entry.id);
      }
    }
  }

  function onKeyDown(e) {
    if (isTypingTarget(e.target)) return;
    const ids = byCombo.get(comboFromEvent(e));
    if (!ids) return;
    for (const id of ids) {
      const handler = handlers[id];
      if (handler) {
        e.preventDefault();
        handler(e);
      }
    }
  }

  rebuild();
  document.addEventListener("keydown", onKeyDown);
  return { unbind: () => document.removeEventListener("keydown", onKeyDown), rebuild };
}

/** Texto amigável para uma lista de combinações, ex.: ["Ctrl+Shift+z"] -> "Ctrl + Shift + Z". */
function keyLabel(keys) {
  return (keys || [])
    .map((combo) => combo.split("+").map((part) => (part.length === 1 ? part.toUpperCase() : part)).join(" + "))
    .join(" ou ");
}

function keymapOverrides() {
  try {
    return JSON.parse(localStorage.getItem(KEYMAP_STORAGE_KEY)) || {};
  } catch {
    return {};
  }
}

/** Combinação já usada por outro atalho (para avisar de conflito ao rebindar); ignora o próprio
 * atalho que está sendo editado. */
function findKeyConflict(combo, exceptId) {
  return loadKeymap().find((entry) => entry.id !== exceptId && entry.keys.includes(combo)) || null;
}

/** Troca, no atalho `id`, a combinação da posição `index` (0 = principal, 1 = alternativa...) por
 * `combo`, e persiste em localStorage. Não valida conflito: quem chama decide se avisa e segue,
 * já que dois atalhos com a mesma tecla é uma escolha do usuário, não um erro fatal. */
function setKeyBinding(id, index, combo) {
  const entry = KEYMAP_DEFAULTS.find((k) => k.id === id);
  if (!entry) return;
  const keys = (loadKeymap().find((k) => k.id === id) || entry).keys.slice();
  keys[index] = combo;
  const overrides = keymapOverrides();
  overrides[id] = keys;
  localStorage.setItem(KEYMAP_STORAGE_KEY, JSON.stringify(overrides));
}

function resetKeymap() {
  localStorage.removeItem(KEYMAP_STORAGE_KEY);
}

window.DMakerKeymap = {
  KEYMAP_DEFAULTS, loadKeymap, bindKeymap, keyLabel, comboFromEvent,
  findKeyConflict, setKeyBinding, resetKeymap,
};
