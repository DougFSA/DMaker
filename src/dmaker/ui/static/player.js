"use strict";
/*
 * DMaker - prévia ao vivo (sem render), estilo palco do Shotcut.
 *
 * Não sabe nada sobre a linha do tempo (timeline.js) nem sobre a orquestração (editor.js):
 * recebe uma "vista" (build_timeline_view), a spec completa (para detalhes de estilo que a
 * vista não carrega, como velocidade do clipe ou aparência de uma sobreposição), o tema da
 * marca e um mapa de proxies, e desenha um palco com as camadas na ordem V1 -> GR -> V2+ -> TX.
 * Não mostra transições, Ken Burns, legendas nem correção de cor: é uma prévia aproximada.
 * O som do V1 sai do próprio <video>; em cada trilha de áudio (A2 em diante e MUS) toca só o item do
 * instante, que a vista já fatiou como o render (arquivo, ponto no arquivo e volume), com um <audio>
 * por trilha.
 *
 * window.DMakerPlayer.create(container, callbacks) -> controlador:
 *   setData({ view, spec, theme, proxyUrls })
 *   setTime(t) / getTime()
 *   play() / pause() / isPlaying()
 *   setRate(multiplier)   (positivo = avança, negativo = "J" reproduz de trás para frente)
 *   stepFrame(deltaFrames)
 *   setVolume(v)
 *
 * callbacks: { onTick(t, rate), onMediaError(path) }
 */

function plEsc(value) {
  return String(value).replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
}

const PL_SYNC_TOLERANCE = 0.15;
const PL_DEFAULT_SIZES = { hook: 90, title: 90, subtitle: 56, cta: 60, "lower-third": 56, custom: 60 };

function plFileUrl(path) {
  return `/api/file?path=${encodeURIComponent(path)}`;
}

function plResolveMediaUrl(path, proxyUrls) {
  if (!path) return null;
  return (proxyUrls && proxyUrls[path]) || plFileUrl(path);
}

/** Fração de posição (left/top em %) para os quatro cantos e as bordas usadas nas
 * sobreposições de imagem/PiP. Função pura. */
function plCornerStyle(position, marginPctX, marginPctY) {
  const styles = {
    "top-left": `top:${marginPctY}%;left:${marginPctX}%;`,
    "top-right": `top:${marginPctY}%;right:${marginPctX}%;`,
    "bottom-left": `bottom:${marginPctY}%;left:${marginPctX}%;`,
    "bottom-right": `bottom:${marginPctY}%;right:${marginPctX}%;`,
    top: `top:${marginPctY}%;left:50%;transform:translateX(-50%);`,
    bottom: `bottom:${marginPctY}%;left:50%;transform:translateX(-50%);`,
    center: "top:50%;left:50%;transform:translate(-50%,-50%);",
  };
  return styles[position] || styles["top-right"];
}

function plTextPosition(role, position) {
  if (position === "top" || position === "center" || position === "bottom") return position;
  if (role === "hook" || role === "title") return "top";
  if (role === "subtitle") return "bottom";
  return "bottom";
}

/* ---------- o que tocar em cada instante (funções puras, expostas em DMakerPlayer.pure) ---------- */

const PL_SEEK_GRACE_MS = 800; // depois de uma busca, o tempo que o elemento tem para carregar antes de ser buscado de novo
const PL_RESEEK_WINDOW = 0.5; // dentro da carência, só busca de novo se o alvo andou além do que a busca anterior prevê

/** Item da trilha que cobre o instante t (start <= t < end), ou null: onde nenhum item soa, a trilha
 * fica muda (a vista só manda um item por trecho que a faixa realmente cobre). */
function plItemAt(items, t) {
  return (items || []).find((it) => t >= it.start && t < it.end) || null;
}

/** Deslocamento, no relógio da sessão, que `in_point` ainda precisa descontar para virar tempo no
 * arquivo: o `extra.offset` explícito do item (zero nos itens fatiados, cujo `in_point` já é tempo no
 * arquivo) ou o da fonte nomeada. */
function plFileOffset(item, sourceOffsetOf) {
  if (item.extra && typeof item.extra.offset === "number") return item.extra.offset;
  return item.source ? sourceOffsetOf(item.source) : 0;
}

/** Tempo no arquivo de origem para um item com in_point/start, dado o tempo t da linha do tempo
 * (mesma conta usada por clipes, PiP, faixas externas e música: ver timeline_view.py). */
function plFileTime(item, t, itemRate, sourceOffsetOf) {
  return item.in_point + (t - item.start) * itemRate - plFileOffset(item, sourceOffsetOf);
}

/** Onde buscar dentro do arquivo para tocar `fileTime`, ou null para pausar: nunca um tempo negativo
 * nem além do fim (que dispararia busca a cada quadro e estalos). Com `loop`, passar do fim dá a volta,
 * como a música em loop do render. Sem a duração (metadados ainda não chegaram), vale o tempo pedido. */
function plPlayableTime(fileTime, duration, loop) {
  if (!(fileTime >= 0)) return null;
  if (!Number.isFinite(duration) || duration <= 0) return fileTime;
  if (fileTime < duration) return fileTime;
  return loop ? fileTime % duration : null;
}

/** Arquivo e tempo nele que um clipe do V1 toca em t. Clipe de fonte em várias partes traz
 * `extra.pieces`, um pedaço por arquivo (já com o ponto de cada um), e toca o que grava o instante. */
function plClipPlayback(item, t, itemRate, sourceOffsetOf, fallbackPath) {
  const pieces = item.extra && item.extra.pieces;
  if (pieces && pieces.length) {
    const piece = pieces.find((p) => t >= p.start && t < p.end) || (t < pieces[0].start ? pieces[0] : pieces[pieces.length - 1]);
    return { path: piece.path, fileTime: piece.in_point + (t - piece.start) * itemRate };
  }
  return { path: fallbackPath, fileTime: plFileTime(item, t, itemRate, sourceOffsetOf) };
}

/** Mudo e volume (0 a 1) de um item de áudio: o volume do item (faixa ou música) vezes o geral. O mudo
 * vem do item, da trilha ou de qualquer um dos dois volumes zerado. */
function plAudioGain(item, trackMuted, master) {
  const itemVolume = item.extra && typeof item.extra.volume === "number" ? item.extra.volume : 1;
  const muted = !!(item.muted || trackMuted || itemVolume <= 0 || master <= 0);
  return { muted, volume: muted ? 0 : Math.min(1, itemVolume * master) };
}

function plIsPlayableAudioTrack(track) {
  return track.id === "MUS" || /^A[2-9]\d*$/.test(track.id);
}

function createPlayer(container, callbacks) {
  const cb = Object.assign({ onTick() {}, onMediaError() {} }, callbacks || {});
  let view = { total: 0, fps: 30, tracks: [], sources: {} };
  let spec = { timeline: [], overlays: [] };
  let theme = { colors: {}, font: "", logos: {}, no_dash: false };
  let proxyUrls = {};

  let currentTime = 0;
  let rate = 0;
  let rafId = null;
  let lastTs = null;
  let volume = 1;
  const mediaCache = new Map(); // url -> { el }
  const activeChannel = new Map(); // canal -> url atual
  // trilha de áudio (A2..., MUS) -> { el, url, path, errored, lastSeek }: um <audio> por TRILHA, que troca de
  // src quando o item muda de arquivo, para não abrir uma conexão por arquivo (limite de 6 por servidor
  // do Chrome em HTTP/1.1)
  const audioChannels = new Map();

  container.classList.add("player-root");
  container.innerHTML = `
    <div class="player-stage-wrap">
      <div class="player-stage" id="player-stage">
        <div class="player-layer player-layer-v1" id="player-layer-v1"></div>
        <div class="player-layer player-layer-gr" id="player-layer-gr"></div>
        <div class="player-layer player-layer-pip" id="player-layer-pip"></div>
        <div class="player-layer player-layer-tx" id="player-layer-tx"></div>
        <div class="player-approx-notice">Prévia aproximada: transições, legendas e efeitos só no render.</div>
      </div>
    </div>
    <div class="player-media-pool" id="player-media-pool" hidden></div>
    <div class="player-controls">
      <button type="button" class="icon-btn" id="pl-go-start" title="Ir ao início (Home)">|&laquo;</button>
      <button type="button" class="icon-btn" id="pl-step-back" title="Quadro anterior (seta esquerda)">&lsaquo;</button>
      <button type="button" class="btn btn-small btn-accent" id="pl-play-pause" title="Reproduzir/Pausar (Espaço)">Play</button>
      <button type="button" class="icon-btn" id="pl-step-forward" title="Próximo quadro (seta direita)">&rsaquo;</button>
      <button type="button" class="icon-btn" id="pl-go-end" title="Ir ao fim (End)">&raquo;|</button>
      <span class="player-speed" id="player-speed">1x</span>
      <span class="player-timecode" id="player-timecode">00:00:00:00</span>
      <label class="player-volume">Vol
        <input type="range" id="pl-volume" min="0" max="1" step="0.05" value="1">
      </label>
      <span class="player-notice" id="player-notice"></span>
    </div>`;

  const stage = container.querySelector("#player-stage");
  const layerV1 = container.querySelector("#player-layer-v1");
  const layerGr = container.querySelector("#player-layer-gr");
  const layerPip = container.querySelector("#player-layer-pip");
  const layerTx = container.querySelector("#player-layer-tx");
  const mediaPool = container.querySelector("#player-media-pool");
  const notice = container.querySelector("#player-notice");
  const timecodeEl = container.querySelector("#player-timecode");
  const speedEl = container.querySelector("#player-speed");
  const playPauseBtn = container.querySelector("#pl-play-pause");

  function updateStageAspect() {
    if (view.width && view.height) stage.style.aspectRatio = `${view.width} / ${view.height}`;
  }

  function sourceOffset(sourceName) {
    const src = view.sources && view.sources[sourceName];
    return src ? src.offset || 0 : 0;
  }

  /** Caminho absoluto do arquivo por trás de um item: `item.path`, já resolvido pela spec
   * (`pipeline.timeline_view._resolve_item_path`), com `src`/a fonte nomeada como reforço. É por
   * causa deste caminho (em vez do `src` cru, que podia ser relativo à pasta do projeto) que a
   * prévia mostra qualquer projeto, não só os que têm tudo em caminho absoluto. */
  function sourcePath(item) {
    if (item.path) return item.path;
    if (item.src) return item.src;
    if (item.source) {
      const src = view.sources && view.sources[item.source];
      return src ? src.path || src.src : null;
    }
    return null;
  }

  function clipSpeed(item) {
    const seg = spec.timeline && spec.timeline[item.index];
    return seg && typeof seg.speed === "number" && seg.speed > 0 ? seg.speed : 1;
  }

  /** Monta a URL de /api/card-preview a partir dos campos do cartão na spec em memória (não
   * depende de nada salvo em disco, então funciona mesmo com cortes/edições ainda não salvos). */
  function cardPreviewUrl(item) {
    const seg = spec.timeline && spec.timeline[item.index];
    if (!seg) return null;
    const width = Math.min(1080, view.width || 1080);
    const params = new URLSearchParams();
    params.set("title", seg.title || "");
    if (seg.subtitle) params.set("subtitle", seg.subtitle);
    if (seg.variant) params.set("variant", seg.variant);
    params.set("logo", seg.logo === false ? "false" : "true");
    if (seg.background) params.set("background", seg.background);
    if (spec.brand) params.set("brand", spec.brand);
    params.set("preset", (spec.output && spec.output.preset) || "instagram/reels");
    params.set("width", String(width));
    return `/api/card-preview?${params.toString()}`;
  }

  function fileTimeFor(item, t, itemRate) {
    return plFileTime(item, t, itemRate, sourceOffset);
  }

  /** Arquivo e tempo nele que o clipe do V1 toca em t (ver `plClipPlayback`). */
  function clipPlayback(item, t) {
    return plClipPlayback(item, t, clipSpeed(item), sourceOffset, sourcePath(item));
  }

  /** O som do clipe sai do próprio <video> do V1; ele fica mudo se o clipe, a A1 ou o mute_clips pedem. */
  function clipAudioMuted(item) {
    if (item.muted) return true;
    if (spec.audio && spec.audio.mute_clips) return true;
    const a1 = view.tracks.find((t) => t.id === "A1");
    if (!a1) return false;
    if (a1.muted) return true;
    const a1Item = a1.items.find((it) => it.index === item.index);
    return !!(a1Item && a1Item.muted);
  }

  function clipVolume(item) {
    const seg = spec.timeline && spec.timeline[item.index];
    return seg && typeof seg.volume === "number" ? seg.volume : 1;
  }

  /** Um `<video>` por URL única (proxy ou arquivo original) dos clipes e PiPs, criado uma vez e
   * reaproveitado enquanto o item mostrar essa mesma URL. Bug real encontrado aqui: o elemento nunca
   * tinha `src` atribuído (só ficava no DOM, mudo e sem quadro nenhum) - por isso nenhum clipe tocava
   * na prévia, mesmo com o caminho já certo. O som das faixas externas e da música não passa por aqui:
   * cada trilha tem o seu <audio> (`audioChannels`), para um arquivo de câmera tocado como faixa não
   * dividir o elemento com o <video> do V1. */
  function getMediaEntry(url, kind) {
    let entry = mediaCache.get(url);
    if (!entry) {
      const el = document.createElement(kind);
      el.preload = "auto";
      el.playsInline = true;
      el.src = url;
      el.addEventListener("error", () => {
        entry.errored = true;
        showNotice("sem proxy: gerando...");
        cb.onMediaError(entry.path || url);
      });
      entry = { el, errored: false, path: null };
      mediaPool.appendChild(el);
      mediaCache.set(url, entry);
    }
    return entry;
  }

  function showNotice(text) {
    notice.textContent = text;
    if (text) setTimeout(() => { if (notice.textContent === text) notice.textContent = ""; }, 4000);
  }

  /* ---------- camada V1 (clipe / imagem / cartão) ---------- */

  function activeV1Item() {
    const track = view.tracks.find((t) => t.id === "V1");
    if (!track || !track.items.length) return null;
    return track.items.find((it) => currentTime >= it.start && currentTime < it.end) || track.items[track.items.length - 1];
  }

  let lastV1Key = null;

  function renderV1(item) {
    const key = item ? `${item.id}:${item.kind}` : null;
    if (key === lastV1Key && item && item.kind !== "clip") return;
    lastV1Key = key;
    if (!item) {
      layerV1.innerHTML = "";
      return;
    }
    if (item.kind === "image") {
      layerV1.innerHTML = `<img class="player-media" src="${plEsc(plResolveMediaUrl(sourcePath(item), proxyUrls))}" alt="">`;
    } else if (item.kind === "card") {
      const url = cardPreviewUrl(item);
      layerV1.innerHTML = url ? `<img class="player-media" src="${plEsc(url)}" alt="">` : "";
    } else if (item.kind === "clip") {
      const { path } = clipPlayback(item, currentTime);
      const url = plResolveMediaUrl(path, proxyUrls);
      if (!url) { layerV1.innerHTML = ""; return; }
      const entry = getMediaEntry(url, "video");
      entry.path = path;
      entry.el.className = "player-media";
      // tirar o <video> do DOM o pausa: só troca quando o arquivo do instante muda (corte ou fronteira de parte)
      if (layerV1.firstChild !== entry.el || layerV1.childNodes.length !== 1) {
        layerV1.innerHTML = "";
        layerV1.appendChild(entry.el);
      }
    } else {
      layerV1.innerHTML = "";
    }
  }

  function syncV1(item) {
    if (!item || item.kind !== "clip") return;
    const { path, fileTime } = clipPlayback(item, currentTime);
    const url = plResolveMediaUrl(path, proxyUrls);
    if (!url) return;
    const entry = mediaCache.get(url);
    if (!entry) return;
    const el = entry.el;
    const itemRate = clipSpeed(item);
    activeChannel.set("v1", url);
    if (Math.abs(el.currentTime - fileTime) > PL_SYNC_TOLERANCE) el.currentTime = Math.max(0, fileTime);
    const muted = clipAudioMuted(item);
    el.muted = muted;
    el.volume = muted ? 0 : Math.min(1, clipVolume(item) * volume);
    if (rate > 0 && !entry.errored) {
      el.playbackRate = Math.min(16, Math.max(0.0625, itemRate * rate));
      if (el.paused) el.play().catch(() => {});
    } else {
      el.pause();
    }
  }

  /* ---------- camada GR (imagens e barra de progresso) ---------- */

  function renderGr() {
    const track = view.tracks.find((t) => t.id === "GR");
    if (!track || track.hidden) { layerGr.innerHTML = ""; return; }
    const active = track.items.filter((it) => currentTime >= it.start && currentTime < it.end);
    layerGr.innerHTML = active.map((item) => grItemHtml(item)).join("");
  }

  function grItemHtml(item) {
    if (item.kind === "progress-bar") {
      const ov = spec.overlays && spec.overlays[item.index];
      const height = (ov && ov.height) || 10;
      const position = (item.extra && item.extra.position) || "bottom";
      const fraction = view.total > 0 ? Math.min(1, currentTime / view.total) : 0;
      const anchor = position === "top" ? "top:0;" : "bottom:0;";
      return `<div class="player-progress-track" style="${anchor}height:${height}px">
        <div class="player-progress-fill" style="width:${(fraction * 100).toFixed(2)}%"></div>
      </div>`;
    }
    const ov = spec.overlays && spec.overlays[item.index];
    const width = (ov && ov.width) || 0.22;
    const opacity = ov && typeof ov.opacity === "number" ? ov.opacity : 1;
    const margin = ov && typeof ov.margin === "number" ? ov.margin : 24;
    const position = (item.extra && item.extra.position) || "top-right";
    const marginPctX = view.width ? (margin / view.width) * 100 : 3;
    const marginPctY = view.height ? (margin / view.height) * 100 : 3;
    const url = resolveImageSrc(item);
    if (!url) return "";
    return `<img class="player-overlay-image" style="width:${(width * 100).toFixed(2)}%;opacity:${opacity};${plCornerStyle(position, marginPctX, marginPctY)}" src="${plEsc(url)}" alt="">`;
  }

  /** "logo"/"logo:variante" resolve pelo tema (não é arquivo); qualquer outra imagem usa `item.path`
   * (caminho absoluto já resolvido pela spec) e só cai para `plFileUrl(item.src)` se a vista, por
   * algum motivo, não tiver mandado o path. */
  function resolveImageSrc(item) {
    const src = item.src;
    if (!src) return null;
    if (src === "logo" || src.startsWith("logo:")) {
      const kind = src.includes(":") ? src.split(":")[1] : "horizontal";
      return theme.logos && theme.logos[kind];
    }
    return item.path ? plFileUrl(item.path) : plFileUrl(src);
  }

  /* ---------- camada PiP (V2, V3...) ---------- */

  function renderPip() {
    const pipTracks = view.tracks.filter((t) => t.kind === "video" && t.id !== "V1" && !t.hidden);
    const activeItems = [];
    for (const track of pipTracks) {
      const item = track.items.find((it) => currentTime >= it.start && currentTime < it.end);
      if (item) activeItems.push(item);
    }
    const wanted = new Set();
    const html = [];
    for (const item of activeItems) {
      const path = sourcePath(item);
      const url = plResolveMediaUrl(path, proxyUrls);
      if (!url) continue;
      wanted.add(`pip:${item.id}`);
      const entry = getMediaEntry(url, "video");
      entry.path = path;
      const ov = spec.overlays && spec.overlays[item.index];
      html.push(pipWrapperHtml(item, ov, entry.el));
    }
    layerPip.innerHTML = "";
    for (const node of html) layerPip.appendChild(node);
    for (const key of [...activeChannel.keys()]) {
      if (key.startsWith("pip:") && !wanted.has(key)) {
        const url = activeChannel.get(key);
        const entry = mediaCache.get(url);
        if (entry) entry.el.pause();
        activeChannel.delete(key);
      }
    }
  }

  function pipWrapperHtml(item, ov, videoEl) {
    const width = (ov && ov.width) || 0.28;
    const shape = (ov && ov.shape) || "rounded";
    const radius = shape === "circle" ? "50%" : shape === "rounded" ? `${((ov && ov.radius) || 0.08) * 100}%` : "0";
    const border = ov && typeof ov.border === "number" ? ov.border : 0;
    const borderColor = (ov && ov.border_color) || "white";
    const opacity = ov && typeof ov.opacity === "number" ? ov.opacity : 1;
    const margin = ov && typeof ov.margin === "number" ? ov.margin : 20;
    const marginPctX = view.width ? (margin / view.width) * 100 : 3;
    const marginPctY = view.height ? (margin / view.height) * 100 : 3;
    let posStyle;
    if (ov && typeof ov.x === "number" && typeof ov.y === "number") {
      posStyle = `left:${ov.x * 100}%;top:${ov.y * 100}%;`;
    } else {
      posStyle = plCornerStyle((item.extra && item.extra.position) || "bottom-right", marginPctX, marginPctY);
    }
    const wrap = document.createElement("div");
    wrap.className = "player-pip";
    wrap.style.cssText = `width:${width * 100}%;opacity:${opacity};border-radius:${radius};border:${border}px solid ${borderColor};${posStyle}`;
    videoEl.className = "player-pip-video";
    wrap.appendChild(videoEl);
    return wrap;
  }

  function syncPip() {
    const pipTracks = view.tracks.filter((t) => t.kind === "video" && t.id !== "V1" && !t.hidden);
    for (const track of pipTracks) {
      const item = track.items.find((it) => currentTime >= it.start && currentTime < it.end);
      if (!item) continue;
      const path = sourcePath(item);
      const url = plResolveMediaUrl(path, proxyUrls);
      if (!url) continue;
      const entry = mediaCache.get(url);
      if (!entry) continue;
      const el = entry.el;
      const target = fileTimeFor(item, currentTime, 1);
      activeChannel.set(`pip:${item.id}`, url);
      if (Math.abs(el.currentTime - target) > PL_SYNC_TOLERANCE) el.currentTime = Math.max(0, target);
      const ov = spec.overlays && spec.overlays[item.index];
      const itemVolume = ov && typeof ov.volume === "number" ? ov.volume : 1;
      el.muted = item.muted || itemVolume <= 0;
      el.volume = el.muted ? 0 : Math.min(1, itemVolume) * volume;
      if (rate > 0 && !entry.errored) {
        el.playbackRate = Math.min(16, Math.max(0.0625, rate));
        el.play().catch(() => {});
      } else {
        el.pause();
      }
    }
  }

  /* ---------- camada TX (texto) ---------- */

  function renderTx() {
    const track = view.tracks.find((t) => t.id === "TX");
    if (!track || track.hidden) { layerTx.innerHTML = ""; return; }
    const active = track.items.filter((it) => currentTime >= it.start && currentTime < it.end);
    layerTx.innerHTML = active.map((item) => txItemHtml(item)).join("");
  }

  function txItemHtml(item) {
    const ov = spec.overlays && spec.overlays[item.index];
    const role = (item.extra && item.extra.role) || "custom";
    const position = plTextPosition(role, ov && ov.position);
    const style = (ov && ov.style) || {};
    const uppercase = style.uppercase;
    const size = style.size || PL_DEFAULT_SIZES[role] || 60;
    const color = style.color || theme.colors?.text || "#FFFFFF";
    const rowStyle = position === "top" ? "top:8%;" : position === "center" ? "top:50%;transform:translateY(-50%);" : "bottom:10%;";
    const text = item.label || "";
    return `<div class="player-text player-text-${plEsc(role)}" style="${rowStyle}font-size:calc(var(--stage-h,600px) * ${size / 1080});color:${plEsc(color)};font-family:${plEsc(theme.font || "inherit")};${uppercase ? "text-transform:uppercase;" : ""}">${plEsc(text)}</div>`;
  }

  /* ---------- relógio (rAF) ---------- */

  function setTimeInternal(t) {
    const clamped = Math.max(0, Math.min(view.total || 0, t));
    if (clamped !== t) rate = 0;
    currentTime = clamped;
  }

  function renderFrame() {
    const item = activeV1Item();
    renderV1(item);
    renderGr();
    renderPip();
    renderTx();
    syncV1(item);
    syncPip();
    syncAudioTracks();
    timecodeEl.textContent = window.DMakerTimeline ? window.DMakerTimeline.formatTimecode(currentTime, view.fps) : currentTime.toFixed(2);
    speedEl.textContent = rate === 0 ? "Pausado" : `${rate > 0 ? "" : "-"}${Math.abs(rate)}x`;
    playPauseBtn.textContent = rate > 0 ? "Pause" : "Play";
  }

  /* ---------- trilhas de áudio (A2 em diante e MUS): um <audio> por trilha ---------- */

  function audioChannelFor(trackId) {
    let channel = audioChannels.get(trackId);
    if (!channel) {
      const el = document.createElement("audio");
      el.preload = "auto";
      el.dataset.track = trackId; // só para inspecionar no navegador qual elemento é de qual trilha
      channel = { el, url: null, path: null, errored: false, lastSeek: null };
      el.addEventListener("error", () => {
        if (!channel.url) return; // limpar o src ao desmontar o canal também dispara "error"
        channel.errored = true;
        showNotice("sem proxy: gerando...");
        cb.onMediaError(channel.path || channel.url);
      });
      mediaPool.appendChild(el);
      audioChannels.set(trackId, channel);
    }
    return channel;
  }

  function dropAudioChannel(trackId) {
    const channel = audioChannels.get(trackId);
    if (!channel) return;
    channel.url = null;
    channel.el.pause();
    channel.el.removeAttribute("src");
    channel.el.load();
    channel.el.remove();
    audioChannels.delete(trackId);
  }

  /** Busca o <audio> para `target` quando ele se afastou além da tolerância. Logo depois de uma busca o
   * elemento fica parado carregando dados, enquanto `target` segue andando: sem a carência, esse atraso
   * estoura a tolerância e dispara outra busca, e outra (visto em faixa de câmera a 2x). `mediaRate` é
   * quantos segundos de arquivo passam por segundo de relógio. */
  function seekChannel(channel, target, mediaRate) {
    const el = channel.el;
    if (Math.abs(el.currentTime - target) <= PL_SYNC_TOLERANCE) return;
    const now = performance.now();
    const last = channel.lastSeek;
    if (last && now - last.at < PL_SEEK_GRACE_MS) {
      const continued = last.target + ((now - last.at) / 1000) * mediaRate;
      if (Math.abs(continued - target) < PL_RESEEK_WINDOW) return; // a busca anterior ainda está carregando
    }
    el.currentTime = target;
    channel.lastSeek = { target, at: now };
  }

  /** Toca na trilha só o item do instante (o que a faixa realmente grava ali, como no render); sem item,
   * ou com o ponto fora do arquivo, o elemento da trilha pausa. */
  function syncAudioTrack(track) {
    const item = plItemAt(track.items, currentTime);
    const channel = item ? audioChannelFor(track.id) : audioChannels.get(track.id);
    if (!channel) return;
    const path = item ? sourcePath(item) : null;
    const url = plResolveMediaUrl(path, proxyUrls);
    if (!item || !url) { channel.el.pause(); return; }
    if (channel.url !== url) {
      channel.url = url;
      channel.path = path;
      channel.errored = false;
      channel.lastSeek = null;
      channel.el.src = url;
    }
    const speed = item.extra && item.extra.speed > 0 ? item.extra.speed : 1;
    const loop = !!(item.extra && item.extra.loop);
    const target = plPlayableTime(fileTimeFor(item, currentTime, speed), channel.el.duration, loop);
    if (target == null) { channel.el.pause(); return; }
    seekChannel(channel, target, rate > 0 ? speed * rate : 0);
    const gain = plAudioGain(item, track.muted, volume);
    channel.el.muted = gain.muted;
    channel.el.volume = gain.volume;
    if (rate > 0 && !channel.errored) {
      channel.el.playbackRate = Math.min(16, Math.max(0.0625, speed * rate));
      if (channel.el.paused) channel.el.play().catch(() => {});
    } else {
      channel.el.pause();
    }
  }

  function syncAudioTracks() {
    const live = new Set();
    for (const track of view.tracks) {
      if (!plIsPlayableAudioTrack(track)) continue;
      live.add(track.id);
      syncAudioTrack(track);
    }
    for (const trackId of [...audioChannels.keys()]) {
      if (!live.has(trackId)) dropAudioChannel(trackId);
    }
  }

  function tick(ts) {
    if (lastTs != null && rate !== 0) {
      const dt = (ts - lastTs) / 1000;
      const next = currentTime + dt * rate;
      if (next <= 0) { setTimeInternal(0); rate = 0; } else if (next >= view.total) { setTimeInternal(view.total); rate = 0; } else { setTimeInternal(next); }
    }
    lastTs = ts;
    renderFrame();
    cb.onTick(currentTime, rate);
    if (rate !== 0) rafId = requestAnimationFrame(tick);
    else rafId = null;
  }

  function ensureLoop() {
    if (rafId == null) {
      lastTs = null;
      rafId = requestAnimationFrame(tick);
    }
  }

  const stageObserver = new ResizeObserver((entries) => {
    for (const entry of entries) {
      stage.style.setProperty("--stage-h", `${entry.contentRect.height}px`);
      stage.style.setProperty("--stage-w", `${entry.contentRect.width}px`);
    }
  });
  stageObserver.observe(stage);

  container.querySelector("#pl-go-start").addEventListener("click", () => controller.setTime(0));
  container.querySelector("#pl-go-end").addEventListener("click", () => controller.setTime(view.total));
  container.querySelector("#pl-step-back").addEventListener("click", () => controller.stepFrame(-1));
  container.querySelector("#pl-step-forward").addEventListener("click", () => controller.stepFrame(1));
  container.querySelector("#pl-play-pause").addEventListener("click", () => {
    if (controller.isPlaying()) controller.pause(); else controller.play();
  });
  container.querySelector("#pl-volume").addEventListener("input", (e) => controller.setVolume(Number(e.target.value)));

  const controller = {
    setData(data) {
      view = data.view || view;
      spec = data.spec || spec;
      theme = data.theme || theme;
      proxyUrls = data.proxyUrls || proxyUrls;
      updateStageAspect();
      currentTime = Math.max(0, Math.min(view.total || 0, currentTime));
      renderFrame();
    },
    setProxyUrls(map) {
      proxyUrls = map || {};
      renderFrame();
    },
    setTime(t) {
      setTimeInternal(t);
      renderFrame();
      cb.onTick(currentTime, rate);
    },
    getTime() {
      return currentTime;
    },
    stepFrame(delta) {
      rate = 0;
      const fps = view.fps || 30;
      setTimeInternal(currentTime + delta / fps);
      renderFrame();
      cb.onTick(currentTime, rate);
    },
    play() {
      rate = 1;
      renderFrame();
      ensureLoop();
    },
    pause() {
      rate = 0;
      renderFrame();
    },
    isPlaying() {
      return rate !== 0;
    },
    getRate() {
      return rate;
    },
    setRate(multiplier) {
      rate = multiplier;
      renderFrame();
      if (rate !== 0) ensureLoop();
    },
    setVolume(v) {
      volume = Math.max(0, Math.min(1, v));
      renderFrame();
    },
    destroy() {
      stageObserver.disconnect();
      if (rafId) cancelAnimationFrame(rafId);
      for (const trackId of [...audioChannels.keys()]) dropAudioChannel(trackId);
    },
  };
  return controller;
}

window.DMakerPlayer = {
  create: createPlayer,
  pure: {
    itemAt: plItemAt,
    fileTime: plFileTime,
    playableTime: plPlayableTime,
    clipPlayback: plClipPlayback,
    audioGain: plAudioGain,
  },
};
