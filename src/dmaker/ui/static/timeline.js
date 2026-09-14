"use strict";
/*
 * DMaker - linha do tempo multitrilha (renderização e interação, estilo Shotcut).
 *
 * Não sabe nada sobre a spec do projeto nem sobre a API: recebe uma "vista" (o corpo
 * devolvido por POST /api/projects/{nome}/timeline) e devolve, por callbacks, a intenção
 * do usuário (buscar um tempo, selecionar um item, mover/aparar/deslocar). Quem decide o
 * que fazer com isso é o editor.js.
 *
 * window.DMakerTimeline.create(container, callbacks) -> controlador:
 *   setView(view)            substitui a vista e redesenha
 *   setPlayhead(t)           move o cursor (não redesenha os itens)
 *   getPlayhead()
 *   getSelection()           lista de itens selecionados (objetos da vista)
 *   setSelection(ids)        ids (array) a marcar como selecionados
 *   clearSelection()
 *   itemAt(trackId, t)       item da trilha que cobre o tempo t (ou null)
 *   edgeTimes()              tempos de início/fim únicos dos trechos da V1, ordenados
 *   zoomIn() / zoomOut() / zoomFit(availablePx)
 *   isSnapEnabled() / toggleSnap()
 *   ensurePlayheadVisible()
 *
 * callbacks: { onSeek(t), onSelect(item, trackId, additive), onClearSelection(),
 *              onOp(op) }  -- op é o corpo de POST /api/projects/{nome}/edit (campo "op")
 */

const TL_HEADER_WIDTH = 92;
const TL_ROW_HEIGHT = 34;
const TL_RULER_HEIGHT = 26;
const TL_MIN_PX_PER_SEC = 4;
const TL_MAX_PX_PER_SEC = 400;
const TL_SNAP_PX = 8;
const TL_MIN_ITEM_SECONDS = 0.1;

function tlEsc(value) {
  return String(value).replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
}

function tlKindClass(kind) {
  return String(kind || "other").replace(/[^a-z0-9-]/gi, "-");
}

function tlFormatTimecode(seconds, fps) {
  const total = Math.max(0, seconds || 0);
  const frameRate = fps && fps > 0 ? fps : 30;
  let frames = Math.round(total * frameRate);
  const framesPerSecond = Math.round(frameRate);
  const h = Math.floor(frames / (framesPerSecond * 3600));
  frames -= h * framesPerSecond * 3600;
  const m = Math.floor(frames / (framesPerSecond * 60));
  frames -= m * framesPerSecond * 60;
  const s = Math.floor(frames / framesPerSecond);
  frames -= s * framesPerSecond;
  const pad = (n) => String(n).padStart(2, "0");
  return `${pad(h)}:${pad(m)}:${pad(s)}:${pad(frames)}`;
}

/** Escolhe o passo (em segundos) entre marcas maiores da régua para que fiquem a pelo
 * menos ~70px de distância, dado o zoom atual. Função pura. */
function tlTickStep(pxPerSec) {
  const steps = [0.1, 0.2, 0.5, 1, 2, 5, 10, 15, 30, 60, 120, 300, 600, 900, 1800];
  for (const step of steps) {
    if (step * pxPerSec >= 70) return step;
  }
  return steps[steps.length - 1];
}

function tlIsDraggable(trackId, item) {
  if (trackId === "V1") return true;
  if (trackId.startsWith("V") && trackId !== "V1") return true;
  if (trackId === "TX") return true;
  if (trackId === "GR" && item.kind === "image") return true;
  return false;
}

function tlSpansWhole(trackId) {
  return trackId === "A1" || trackId === "MUS" || trackId === "CC" || /^A\d+$/.test(trackId);
}

/** Nome de arquivo, sem a pasta, para rótulos que vêm de um caminho (clipe, imagem, PiP...);
 * textos (cartão, sobreposição de texto) não têm barra e voltam como vieram. */
function tlDisplayLabel(label) {
  if (!label) return "";
  return /[\\/]/.test(label) ? label.split(/[\\/]/).pop() : label;
}

function tlTrackLabel(track) {
  const icon = track.kind === "audio" ? " ♪" : "";
  return `${track.label}${icon}`;
}

function createTimeline(container, callbacks) {
  const cb = Object.assign({ onSeek() {}, onSelect() {}, onClearSelection() {}, onOp() {} }, callbacks || {});
  let view = { total: 0, fps: 30, tracks: [] };
  let pxPerSec = 60;
  let snapEnabled = true;
  let playhead = 0;
  let selectedIds = new Set();
  let drag = null;

  container.classList.add("tl-root");
  container.innerHTML = '<div class="tl-scroll"></div>';
  const scrollEl = container.querySelector(".tl-scroll");

  function totalWidthPx() {
    return Math.max(200, view.total * pxPerSec + 40);
  }

  function xToTime(clientX) {
    const rect = scrollEl.getBoundingClientRect();
    const x = clientX - rect.left + scrollEl.scrollLeft - TL_HEADER_WIDTH;
    return Math.max(0, Math.min(view.total, x / pxPerSec));
  }

  function allItems() {
    const items = [];
    for (const track of view.tracks) {
      for (const item of track.items) items.push({ item, trackId: track.id });
    }
    return items;
  }

  function snapCandidates(excludeId) {
    const points = [0, view.total, playhead];
    for (const { item } of allItems()) {
      if (item.id === excludeId) continue;
      points.push(item.start, item.end);
    }
    return points;
  }

  function snapTime(t, excludeId) {
    if (!snapEnabled) return t;
    const tolerance = TL_SNAP_PX / pxPerSec;
    let best = t;
    let bestDist = tolerance;
    for (const p of snapCandidates(excludeId)) {
      const d = Math.abs(p - t);
      if (d < bestDist) {
        bestDist = d;
        best = p;
      }
    }
    return best;
  }

  function findItem(id) {
    for (const { item, trackId } of allItems()) {
      if (item.id === id) return { item, trackId };
    }
    return null;
  }

  function renderRuler() {
    const step = tlTickStep(pxPerSec);
    const ticks = [];
    for (let t = 0; t <= view.total + step; t += step) {
      ticks.push(`<div class="tl-tick" style="left:${t * pxPerSec}px"><span>${tlFormatTimecode(t, view.fps).slice(0, 8)}</span></div>`);
    }
    return `
      <div class="tl-row tl-ruler-row">
        <div class="tl-row-header tl-ruler-corner"></div>
        <div class="tl-row-lane tl-ruler" style="width:${totalWidthPx()}px">${ticks.join("")}</div>
      </div>`;
  }

  function renderTransitions(track) {
    if (track.id !== "V1") return "";
    const items = track.items;
    const hatches = [];
    for (let i = 1; i < items.length; i++) {
      const prev = items[i - 1];
      const cur = items[i];
      if (cur.transition && cur.start < prev.end) {
        const start = cur.start;
        const end = Math.min(prev.end, cur.end);
        hatches.push(`<div class="tl-transition" style="left:${start * pxPerSec}px;width:${Math.max(2, (end - start) * pxPerSec)}px" title="Transição: ${tlEsc(cur.transition.type || "")}"></div>`);
      }
    }
    return hatches.join("");
  }

  function itemHtml(track, item) {
    const left = item.start * pxPerSec;
    const width = Math.max(3, (item.end - item.start) * pxPerSec);
    const draggable = tlIsDraggable(track.id, item);
    const classes = [
      "tl-item",
      `tl-item-${tlKindClass(item.kind)}`,
      selectedIds.has(item.id) ? "selected" : "",
      item.muted ? "tl-item-muted" : "",
    ].filter(Boolean).join(" ");
    const handles = draggable
      ? '<div class="tl-item-handle tl-item-handle-in" data-handle="in"></div><div class="tl-item-handle tl-item-handle-out" data-handle="out"></div>'
      : "";
    return `<div class="${classes}" data-item-id="${tlEsc(item.id)}" data-track-id="${tlEsc(track.id)}"
        data-draggable="${draggable ? "1" : "0"}" style="left:${left}px;width:${width}px"
        title="${tlEsc(item.label || item.kind)}">
        ${handles}<span class="tl-item-label">${tlEsc(tlDisplayLabel(item.label) || item.kind)}</span>
      </div>`;
  }

  function renderTrack(track) {
    const items = track.items.map((item) => itemHtml(track, item)).join("");
    return `
      <div class="tl-row" data-track-id="${tlEsc(track.id)}">
        <div class="tl-row-header" title="${tlEsc(track.label)}">${tlEsc(tlTrackLabel(track))}</div>
        <div class="tl-row-lane" data-track-id="${tlEsc(track.id)}" style="width:${totalWidthPx()}px">
          ${renderTransitions(track)}${items}
        </div>
      </div>`;
  }

  function render() {
    const rows = view.tracks.map(renderTrack).join("");
    scrollEl.innerHTML = `${renderRuler()}${rows}<div class="tl-playhead" style="left:${TL_HEADER_WIDTH + playhead * pxPerSec}px"></div>`;
  }

  function updatePlayheadPosition() {
    const el = scrollEl.querySelector(".tl-playhead");
    if (el) el.style.left = `${TL_HEADER_WIDTH + playhead * pxPerSec}px`;
  }

  /* ---- interação: seleção, seek, arraste ---- */

  function selectSingle(id, additive) {
    if (!additive) selectedIds = new Set([id]);
    else if (selectedIds.has(id)) selectedIds.delete(id);
    else selectedIds.add(id);
    render();
  }

  function startSeekDrag(e) {
    const move = (ev) => cb.onSeek(snapTime(xToTime(ev.clientX), null));
    move(e);
    const up = () => {
      document.removeEventListener("mousemove", move);
      document.removeEventListener("mouseup", up);
    };
    document.addEventListener("mousemove", move);
    document.addEventListener("mouseup", up);
  }

  function startItemDrag(e, track, item, handle) {
    const startX = e.clientX;
    const original = { start: item.start, end: item.end };
    const mode = handle ? "trim" : track.id === "V1" ? "move-v1" : "shift";
    drag = { mode, track, item, handle, startX, original };
    const ghost = document.createElement("div");
    ghost.className = "tl-item tl-item-ghost";
    ghost.style.top = `${TL_RULER_HEIGHT + view.tracks.findIndex((t) => t.id === track.id) * TL_ROW_HEIGHT}px`;
    scrollEl.appendChild(ghost);
    drag.ghost = ghost;
    let moveIndicator = null;
    if (mode === "move-v1") {
      moveIndicator = document.createElement("div");
      moveIndicator.className = "tl-drop-indicator";
      scrollEl.appendChild(moveIndicator);
    }

    function applyGhostGeometry(deltaSeconds) {
      let left = original.start;
      let width = original.end - original.start;
      if (mode === "trim") {
        if (handle === "in") {
          left = Math.min(Math.max(original.start + deltaSeconds, 0), original.end - TL_MIN_ITEM_SECONDS);
          width = original.end - left;
        } else {
          const end = Math.max(original.end + deltaSeconds, original.start + TL_MIN_ITEM_SECONDS);
          width = end - left;
        }
      } else {
        left = Math.max(0, original.start + deltaSeconds);
        width = original.end - original.start;
      }
      ghost.style.left = `${TL_HEADER_WIDTH + left * pxPerSec}px`;
      ghost.style.width = `${Math.max(3, width * pxPerSec)}px`;
      return { left, width };
    }

    function onMove(ev) {
      const deltaSeconds = (ev.clientX - startX) / pxPerSec;
      if (mode === "move-v1") {
        const targetTime = snapTime(original.start + deltaSeconds, item.id);
        const v1Items = track.items;
        let targetIndex = v1Items.findIndex((it) => it.id !== item.id && it.start > targetTime);
        if (targetIndex === -1) targetIndex = v1Items.length;
        const xPx = TL_HEADER_WIDTH + (targetIndex < v1Items.length ? v1Items[targetIndex].start : view.total) * pxPerSec;
        if (moveIndicator) {
          moveIndicator.style.top = `${TL_RULER_HEIGHT + view.tracks.findIndex((t) => t.id === track.id) * TL_ROW_HEIGHT}px`;
          moveIndicator.style.left = `${xPx}px`;
        }
        ghost.style.top = `${TL_RULER_HEIGHT + view.tracks.findIndex((t) => t.id === track.id) * TL_ROW_HEIGHT}px`;
        ghost.style.left = `${TL_HEADER_WIDTH + targetTime * pxPerSec}px`;
        ghost.style.width = `${Math.max(3, (original.end - original.start) * pxPerSec)}px`;
        drag.result = { toIndex: targetIndex };
      } else {
        applyGhostGeometry(deltaSeconds);
        drag.result = { deltaSeconds };
      }
    }

    function onUp() {
      document.removeEventListener("mousemove", onMove);
      document.removeEventListener("mouseup", onUp);
      ghost.remove();
      if (moveIndicator) moveIndicator.remove();
      finishItemDrag();
      drag = null;
    }

    document.addEventListener("mousemove", onMove);
    document.addEventListener("mouseup", onUp);
  }

  function finishItemDrag() {
    if (!drag || !drag.result) return;
    const { mode, track, item, handle, original } = drag;
    if (mode === "move-v1") {
      const ownIndex = track.items.findIndex((it) => it.id === item.id);
      let to = drag.result.toIndex;
      if (to > ownIndex) to -= 1;
      if (to !== ownIndex && to >= 0) {
        cb.onOp({ type: "move", index: item.index, to });
      }
      return;
    }
    const deltaSeconds = drag.result.deltaSeconds || 0;
    if (Math.abs(deltaSeconds) < 0.001) return;
    if (mode === "trim") {
      cb.onOp({ type: "trim", index: item.index, side: handle, delta: deltaSeconds });
      return;
    }
    let start = original.start + deltaSeconds;
    let end = original.end + deltaSeconds;
    if (start < 0) {
      end -= start;
      start = 0;
    }
    if (end > view.total) {
      start -= end - view.total;
      end = view.total;
    }
    cb.onOp({ type: "overlay_span", index: item.index, start: snapTime(start, item.id), end: snapTime(end, item.id) });
  }

  scrollEl.addEventListener("mousedown", (e) => {
    const handleEl = e.target.closest("[data-handle]");
    const itemEl = e.target.closest(".tl-item:not(.tl-item-ghost)");
    const laneEl = e.target.closest(".tl-row-lane");
    if (handleEl && itemEl) {
      const trackId = itemEl.dataset.trackId;
      const track = view.tracks.find((t) => t.id === trackId);
      const item = track && track.items.find((it) => it.id === itemEl.dataset.itemId);
      if (track && item && tlIsDraggable(trackId, item)) {
        e.preventDefault();
        startItemDrag(e, track, item, handleEl.dataset.handle);
      }
      return;
    }
    if (itemEl) {
      const trackId = itemEl.dataset.trackId;
      const track = view.tracks.find((t) => t.id === trackId);
      const item = track && track.items.find((it) => it.id === itemEl.dataset.itemId);
      if (!track || !item) return;
      selectSingle(item.id, e.ctrlKey || e.metaKey);
      cb.onSelect(item, trackId, e.ctrlKey || e.metaKey);
      if (itemEl.dataset.draggable === "1") {
        e.preventDefault();
        startItemDrag(e, track, item, null);
      }
      return;
    }
    if (laneEl || e.target.closest(".tl-ruler")) {
      selectedIds = new Set();
      cb.onClearSelection();
      startSeekDrag(e);
    }
  });

  function zoomTo(next, focusSeconds) {
    pxPerSec = Math.max(TL_MIN_PX_PER_SEC, Math.min(TL_MAX_PX_PER_SEC, next));
    render();
    if (focusSeconds !== undefined) {
      scrollEl.scrollLeft = Math.max(0, TL_HEADER_WIDTH + focusSeconds * pxPerSec - scrollEl.clientWidth / 2);
    }
  }

  scrollEl.addEventListener(
    "wheel",
    (e) => {
      if (!e.ctrlKey) return;
      e.preventDefault();
      const factor = e.deltaY < 0 ? 1.15 : 1 / 1.15;
      zoomTo(pxPerSec * factor, xToTime(e.clientX));
    },
    { passive: false }
  );

  return {
    setView(newView) {
      view = newView || { total: 0, fps: 30, tracks: [] };
      const validIds = new Set(allItems().map(({ item }) => item.id));
      selectedIds = new Set([...selectedIds].filter((id) => validIds.has(id)));
      playhead = Math.max(0, Math.min(playhead, view.total));
      render();
    },
    getView() {
      return view;
    },
    setPlayhead(t) {
      playhead = Math.max(0, Math.min(view.total, t));
      updatePlayheadPosition();
    },
    getPlayhead() {
      return playhead;
    },
    getSelection() {
      return [...selectedIds].map((id) => findItem(id)).filter(Boolean).map((x) => x.item);
    },
    getSelectionWithTrack() {
      return [...selectedIds].map((id) => findItem(id)).filter(Boolean);
    },
    setSelection(ids) {
      selectedIds = new Set(ids || []);
      render();
    },
    clearSelection() {
      selectedIds = new Set();
      render();
    },
    itemAt(trackId, t) {
      const track = view.tracks.find((tr) => tr.id === trackId);
      if (!track) return null;
      return track.items.find((it) => t >= it.start && t < it.end) || null;
    },
    edgeTimes() {
      const v1 = view.tracks.find((t) => t.id === "V1");
      if (!v1) return [0, view.total];
      const times = new Set([0, view.total]);
      for (const it of v1.items) {
        times.add(it.start);
        times.add(it.end);
      }
      return [...times].sort((a, b) => a - b);
    },
    zoomIn() {
      zoomTo(pxPerSec * 1.3, playhead);
    },
    zoomOut() {
      zoomTo(pxPerSec / 1.3, playhead);
    },
    zoomFit(availablePx) {
      const px = Math.max(TL_MIN_PX_PER_SEC, Math.min(TL_MAX_PX_PER_SEC, (availablePx || 800) / Math.max(1, view.total)));
      zoomTo(px, 0);
      scrollEl.scrollLeft = 0;
    },
    isSnapEnabled() {
      return snapEnabled;
    },
    toggleSnap() {
      snapEnabled = !snapEnabled;
      return snapEnabled;
    },
    ensurePlayheadVisible() {
      const x = TL_HEADER_WIDTH + playhead * pxPerSec;
      const margin = 40;
      if (x < scrollEl.scrollLeft + TL_HEADER_WIDTH + margin) {
        scrollEl.scrollLeft = Math.max(0, x - TL_HEADER_WIDTH - margin);
      } else if (x > scrollEl.scrollLeft + scrollEl.clientWidth - margin) {
        scrollEl.scrollLeft = x - scrollEl.clientWidth + margin;
      }
    },
    getTracksElement() {
      return scrollEl;
    },
    /** Traduz um ponto da tela (ex.: de um evento de arrastar e soltar) para a trilha e o tempo
     * correspondentes, para quem solta mídia na linha do tempo (media.js) não precisar conhecer o
     * layout (largura do cabeçalho, pixels por segundo...) por conta própria. */
    hitTest(clientX, clientY) {
      const el = document.elementFromPoint(clientX, clientY);
      const laneEl = el && el.closest && el.closest("[data-track-id]");
      return { trackId: laneEl ? laneEl.dataset.trackId : null, time: snapTime(xToTime(clientX), null) };
    },
  };
}

window.DMakerTimeline = { create: createTimeline, formatTimecode: tlFormatTimecode, tickStep: tlTickStep };
