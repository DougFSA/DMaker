"use strict";
/*
 * DMaker - painel "Mídia" (direita da aba Linha do tempo): lista as fontes sincronizadas e os
 * arquivos já usados na linha do tempo, com miniatura e duração, para arrastar (ou soltar com A/V)
 * na linha do tempo. Não decide o que a soltura vira (clipe, PiP, sobreposição): só descreve o que
 * foi solto e onde; quem decide é o editor.js, que conhece a spec inteira.
 *
 * window.DMakerMedia.create(container, callbacks) -> controlador:
 *   setSpec(spec)     atualiza a lista (fontes + arquivos referenciados na spec)
 *   getSelected()      entrada da mídia selecionada (clique simples) ou null
 *
 * callbacks: { onInsertEnd(entry), onDragStart(entry) (opcional, só para log/depuração) }
 * Os botões da barra (Adicionar arquivo, Texto, Cartão, Logo, Música) são ids estáticos no
 * index.html; quem liga o clique deles a uma ação é o editor.js (fica no mesmo lugar que decide
 * o resto da orquestração).
 */

const MEDIA_DND_MIME = "application/x-dmaker-media";

function mdEsc(value) {
  return String(value).replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
}

function mdKindFromExt(path) {
  const ext = fileExt(path);
  if (VIDEO_EXTENSIONS.includes(ext)) return "clip";
  if (IMAGE_EXTENSIONS.includes(ext)) return "image";
  if (AUDIO_EXTENSIONS.includes(ext)) return "audio";
  return "clip";
}

/** Fontes sincronizadas e arquivos avulsos referenciados na spec (trechos, sobreposições, música),
 * sem repetir o mesmo caminho duas vezes. Função pura. */
function collectMediaEntries(spec) {
  const entries = [];
  const seen = new Set();
  for (const [name, ref] of Object.entries(spec.sources || {})) {
    entries.push({ id: `source:${name}`, kind: "clip", label: name, path: ref.src, source: name });
    seen.add(ref.src);
  }
  const addFile = (path, kind) => {
    if (!path || seen.has(path)) return;
    seen.add(path);
    entries.push({ id: `file:${path}`, kind, label: baseName(path), path, src: path });
  };
  for (const seg of spec.timeline || []) {
    if (seg.type === "clip" && seg.src) addFile(seg.src, "clip");
    if (seg.type === "image" && seg.src) addFile(seg.src, "image");
  }
  for (const ov of spec.overlays || []) {
    if (ov.type === "image" && ov.src && ov.src !== "logo" && !String(ov.src).startsWith("logo:")) addFile(ov.src, "image");
    if (ov.type === "video" && ov.src) addFile(ov.src, "clip");
  }
  if (spec.audio && spec.audio.music && spec.audio.music.src) addFile(spec.audio.music.src, "audio");
  return entries;
}

function createMedia(container, callbacks) {
  const cb = Object.assign({ onInsertEnd() {}, onDragStart() {} }, callbacks || {});
  let spec = { sources: {}, timeline: [], overlays: [] };
  let entries = [];
  let selectedId = null;
  const durations = new Map(); // path -> segundos (ou null se falhou)

  function kindLabel(kind) {
    return { clip: "vídeo", image: "imagem", audio: "áudio" }[kind] || kind;
  }

  function durationLabel(path) {
    if (!durations.has(path)) return "";
    const d = durations.get(path);
    return d == null ? "" : ` · ${d.toFixed(1)}s`;
  }

  function entryHtml(entry) {
    const thumb = mediaThumbHtml(entry.path, entry.kind === "clip" ? "video" : entry.kind === "image" ? "image" : "");
    const selected = entry.id === selectedId ? "selected" : "";
    return `
      <div class="media-item ${selected}" data-media-id="${mdEsc(entry.id)}" draggable="true" title="${mdEsc(entry.path)}">
        ${thumb ? `<div class="media-thumb">${thumb}</div>` : '<div class="media-thumb media-thumb-empty"></div>'}
        <div class="media-info">
          <div class="media-name">${mdEsc(entry.label)}</div>
          <div class="media-meta">${mdEsc(kindLabel(entry.kind))}${durationLabel(entry.path)}</div>
        </div>
      </div>`;
  }

  function render() {
    container.innerHTML = entries.length
      ? entries.map(entryHtml).join("")
      : '<p class="empty-hint">Nenhum arquivo ainda. Use "+ Arquivo" ou os botões acima.</p>';
  }

  async function probeMissingDurations() {
    const missing = entries.map((e) => e.path).filter((p) => p && !durations.has(p));
    if (!missing.length) return;
    for (const path of missing) durations.set(path, undefined); // marca "em andamento" pra não pedir de novo
    try {
      const results = await api.post("/api/probe", { paths: missing });
      for (const r of results) durations.set(r.path, r.error ? null : r.duration_s);
    } catch {
      for (const path of missing) durations.set(path, null);
    }
    render();
  }

  container.addEventListener("click", (e) => {
    const item = e.target.closest("[data-media-id]");
    if (!item) return;
    selectedId = item.dataset.mediaId;
    render();
  });

  container.addEventListener("dblclick", (e) => {
    const item = e.target.closest("[data-media-id]");
    if (!item) return;
    const entry = entries.find((en) => en.id === item.dataset.mediaId);
    if (entry) cb.onInsertEnd(entry);
  });

  container.addEventListener("dragstart", (e) => {
    const item = e.target.closest("[data-media-id]");
    if (!item) return;
    const entry = entries.find((en) => en.id === item.dataset.mediaId);
    if (!entry) return;
    e.dataTransfer.effectAllowed = "copy";
    e.dataTransfer.setData(MEDIA_DND_MIME, JSON.stringify(entry));
    cb.onDragStart(entry);
  });

  return {
    setSpec(newSpec) {
      spec = newSpec || spec;
      entries = collectMediaEntries(spec);
      if (!entries.some((e) => e.id === selectedId)) selectedId = null;
      render();
      probeMissingDurations();
    },
    getSelected() {
      return entries.find((e) => e.id === selectedId) || null;
    },
  };
}

window.DMakerMedia = { create: createMedia, collectMediaEntries, MEDIA_DND_MIME };
