"use strict";
/*
 * DMaker - painel de andamento: deriva a etapa atual do pipeline a partir dos eventos do job (log e
 * progress) recebidos por SSE, sem depender de nenhum campo novo do backend.
 *
 * As chaves vêm dos textos que pipeline/renderer.py manda por `ctx.log` e das labels dos comandos
 * ffmpeg de cada etapa (pipeline/segments.py "trecho i/N", pipeline/captions.py "áudio para
 * transcrição", pipeline/assembly.py "montagem final"). Módulo à parte, sem estado global próprio:
 * quem chama guarda o `state` e passa de volta a cada evento (fácil de testar, fácil de reiniciar).
 */

const STEPS = [
  { key: "fontes", label: "Fontes e sincronização" },
  { key: "mezaninos", label: "Trechos" },
  { key: "legendas", label: "Legendas" },
  { key: "texto", label: "Camada de texto" },
  { key: "loudness", label: "Loudness" },
  { key: "montagem", label: "Montagem final" },
  { key: "thumbnail", label: "Miniatura" },
];

/** Etapa indicada por uma linha de log do renderer (ou null se a linha não marca etapa nenhuma). */
function stepKeyFromLog(message) {
  const text = message || "";
  if (/^render /.test(text)) return "fontes";
  if (/^sincronizando /.test(text) || /come[cç]a em [+-]?\d/.test(text)) return "fontes";
  if (/^trechos: \d+/.test(text)) return "mezaninos";
  if (/^legendas: /.test(text)) return "legendas";
  if (text === "montagem final") return "montagem";
  if (/^pronto: /.test(text)) return "thumbnail";
  return null;
}

/** Etapa indicada pela label de um comando ffmpeg (evento "progress"). */
function stepKeyFromProgressLabel(label) {
  const text = label || "";
  if (/^(recorte do )?trecho \d+\/\d+/.test(text)) return "mezaninos";
  if (text === "áudio para transcrição") return "legendas";
  if (text === "montagem final") return "montagem";
  if (text === "thumbnail") return "thumbnail";
  return null;
}

/** Detalhe curto da etapa atual (ex.: "trecho 2/5", "42%"), quando dá para extrair do evento. */
function detailFromEvent(evt) {
  if (evt.kind !== "progress") return "";
  const match = /trecho \d+\/\d+/.exec(evt.label || "");
  if (match) return match[0];
  return evt.percent !== undefined && evt.percent !== null ? `${evt.percent}%` : "";
}

function initialState() {
  return { stepIndex: -1, detail: "", startedAt: null };
}

/** Estado novo a partir de um evento do job (start/log/progress/end). Função pura. */
function nextState(state, evt) {
  const startedAt = state.startedAt || (evt.kind === "start" ? Date.now() : null);
  let key = null;
  if (evt.kind === "log") key = stepKeyFromLog(evt.message);
  else if (evt.kind === "progress") key = stepKeyFromProgressLabel(evt.label);
  const idx = key ? STEPS.findIndex((s) => s.key === key) : -1;
  const stepIndex = idx > state.stepIndex ? idx : state.stepIndex;
  const detail = idx >= 0 ? detailFromEvent(evt) : state.detail;
  return { stepIndex, detail, startedAt };
}

/** Lista <li> das etapas conhecidas, com a atual destacada e as anteriores marcadas como concluídas. */
function stepsHtml(state) {
  return STEPS.map((step, i) => {
    const status = i < state.stepIndex ? "done" : i === state.stepIndex ? "current" : "pending";
    const detail =
      status === "current" && state.detail ? ` <span class="progress-step-detail">${state.detail}</span>` : "";
    return `<li class="progress-step progress-step-${status}">${step.label}${detail}</li>`;
  }).join("");
}

/** Tempo decorrido desde o início do job, formatado "mm:ss" (vazio se ainda não começou). */
function elapsedLabel(state, now) {
  if (!state.startedAt) return "";
  const totalSeconds = Math.max(0, Math.round((now - state.startedAt) / 1000));
  const m = Math.floor(totalSeconds / 60);
  const s = totalSeconds % 60;
  return `${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
}

window.DMakerProgress = {
  STEPS,
  stepKeyFromLog,
  stepKeyFromProgressLabel,
  initialState,
  nextState,
  stepsHtml,
  elapsedLabel,
};
