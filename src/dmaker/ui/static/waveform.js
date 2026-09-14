"use strict";
/*
 * DMaker - forma de onda das trilhas de áudio da linha do tempo.
 *
 * Não sabe nada sobre a linha do tempo (timeline.js decide quais itens têm áudio e a janela de
 * tempo do arquivo que cada canvas mostra); só busca os picos calculados pelo backend
 * (GET /api/waveform) e desenha um trecho deles num canvas.
 *
 * window.DMakerWaveform:
 *   fetchPeaks(path, stream) -> Promise<{duration, peaks_per_second, peaks} | null>
 *     cacheia em memória por "path::stream"; enquanto a promessa não resolve, chamadas repetidas
 *     para a mesma chave reaproveitam a mesma promessa (uma única requisição por arquivo).
 *   draw(canvas, waveform, fileStart, fileEnd, options)
 *     desenha, ao longo da largura do canvas, o trecho do arquivo entre os tempos `fileStart` e
 *     `fileEnd` (um por pixel); `options.loop` repete os picos além da duração (música em loop);
 *     tempo fora do trecho gravado (antes do início, ou depois do fim sem repetir) fica em branco.
 */

const WV_CACHE = new Map(); // "path::stream" -> Promise<Waveform | null>

function wvKey(path, stream) {
  return `${path}::${stream || 0}`;
}

function fetchPeaks(path, stream) {
  if (!path) return Promise.resolve(null);
  const key = wvKey(path, stream);
  const cached = WV_CACHE.get(key);
  if (cached) return cached;
  const params = new URLSearchParams({ path, stream: String(stream || 0) });
  const promise = fetch(`/api/waveform?${params.toString()}`)
    .then((res) => (res.ok ? res.json() : null))
    .catch(() => null);
  WV_CACHE.set(key, promise);
  return promise;
}

/** Índice do pico mais próximo de um tempo do arquivo, ou -1 se estiver fora do trecho gravado.
 * Função pura. */
function peakIndexAt(peaksLength, peaksPerSecond, duration, fileTime, loop) {
  let t = fileTime;
  if (loop && duration > 0) {
    t = ((t % duration) + duration) % duration;
  } else if (t < 0 || t >= duration) {
    return -1;
  }
  const i = Math.floor(t * peaksPerSecond);
  return i >= 0 && i < peaksLength ? i : -1;
}

function draw(canvas, waveform, fileStart, fileEnd, options) {
  const opts = Object.assign({ loop: false, color: "rgba(255,255,255,0.5)", muted: false }, options || {});
  const ctx = canvas.getContext("2d");
  const width = canvas.width;
  const height = canvas.height;
  ctx.clearRect(0, 0, width, height);
  if (!waveform || !waveform.peaks || !waveform.peaks.length || width <= 0 || height <= 0) return;
  const peaks = waveform.peaks;
  const pps = waveform.peaks_per_second;
  const duration = waveform.duration;
  const mid = height / 2;
  const span = fileEnd - fileStart;
  ctx.fillStyle = opts.muted ? "rgba(255,255,255,0.2)" : opts.color;
  for (let x = 0; x < width; x++) {
    const fileTime = span === 0 ? fileStart : fileStart + (x / width) * span;
    const idx = peakIndexAt(peaks.length, pps, duration, fileTime, opts.loop);
    if (idx < 0) continue;
    const amplitude = Math.max(0, Math.min(1, peaks[idx]));
    const barHeight = Math.max(1, amplitude * height);
    ctx.fillRect(x, mid - barHeight / 2, 1, barHeight);
  }
}

window.DMakerWaveform = { fetchPeaks, draw, peakIndexAt };
