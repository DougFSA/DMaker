"use strict";
/*
 * DMaker - áudio na aba "Voz": isolar a voz de um arquivo (voz de um lado, música e ruído do outro) e
 * corrigir uma fala (trocar uma palavra dita errado pela certa, na voz do próprio falante).
 *
 * Tudo aqui é lento na CPU (separar voz, transcrever, sintetizar), então cada ação é um job: o POST devolve
 * job_id e o andamento chega por SSE, pelo acompanhamento de jobs do voice.js (DMakerVoice.followJob).
 *
 * O arquivo vem de uma lista (mídia do projeto aberto) ou de um envio. Usa em tempo de execução, vindos de
 * app.js e editor.js: api, state, showAlert, handleError, formatApiError, saveProject, edState e
 * DMakerEditor.applyOp. O que é puro fica em window.DMakerSpeech.pure.
 *
 * window.DMakerSpeech:
 *   init()      chamado por app.js ao terminar de carregar o estado
 *   onShow()    chamado por app.js quando a aba Voz aparece (atualiza arquivos do projeto e vozes)
 *   pure        groupWordsByBreath, selectionFor, projectSourceOptions, replaceSourceOps, abWindow...
 */
(function () {
  const BREATH_PAUSE_S = 0.25; // pausa que o falante usa para tomar fôlego; o servidor devolve o mesmo valor
  const AB_PADDING_S = 1.5; // quanto antes e depois do trecho o A/B toca
  const UPLOAD_VALUE = "upload";
  const MEDIA_KINDS = ["clip", "audio"];

  /* ==================== funções puras ==================== */

  /** Palavras em grupos de fôlego: uma pausa de `pause` segundos ou mais começa um grupo novo. */
  function groupWordsByBreath(words, pause) {
    const limit = pause === undefined ? BREATH_PAUSE_S : pause;
    const groups = [];
    words.forEach((word, index) => {
      const last = groups[groups.length - 1];
      if (last && word.start - words[last[last.length - 1]].end < limit) last.push(index);
      else groups.push([index]);
    });
    return groups;
  }

  /** Trecho entre duas palavras clicadas (em qualquer ordem): índices, tempo e texto. */
  function selectionFor(words, a, b) {
    const first = Math.min(a, b);
    const last = Math.max(a, b);
    const span = words.slice(first, last + 1);
    return {
      first,
      last,
      start: words[first].start,
      end: words[last].end,
      text: span.map((w) => w.text).join(" "),
    };
  }

  /** Arquivos do projeto que têm áudio (trechos e áudios), com o caminho já resolvido. */
  function projectSourceOptions(entries) {
    return (entries || [])
      .filter((entry) => MEDIA_KINDS.includes(entry.kind) && entry.path)
      .map((entry, index) => ({ value: `project:${index}`, label: entry.label, path: entry.path, entry }));
  }

  /** Operações set_field que trocam o arquivo original pelo corrigido em tudo que o usa no projeto:
   * as fontes nomeadas (multicâmera), os trechos e os vídeos sobrepostos. `entry` vem da lista de mídia
   * (src cru como está na spec, ou nome da fonte). */
  function replaceSourceOps(spec, entry, newPath) {
    const ops = [];
    if (!entry || !spec) return ops;
    if (entry.source) {
      ops.push({ type: "set_field", path: `sources.${entry.source}.src`, value: newPath });
      return ops;
    }
    (spec.timeline || []).forEach((segment, index) => {
      if (segment.type === "clip" && segment.src === entry.src) {
        ops.push({ type: "set_field", path: `timeline.${index}.src`, value: newPath });
      }
    });
    (spec.overlays || []).forEach((overlay, index) => {
      if (overlay.type === "video" && overlay.src === entry.src) {
        ops.push({ type: "set_field", path: `overlays.${index}.src`, value: newPath });
      }
    });
    return ops;
  }

  /** Janela do A/B: a região trocada com uma folga de cada lado, para ouvir a emenda no contexto. */
  function abWindow(region, padding) {
    const pad = padding === undefined ? AB_PADDING_S : padding;
    return { start: Math.max(0, region[0] - pad), end: region[1] + pad };
  }

  /** Número do campo, ou null se vazio ou inválido. */
  function numberOrNull(value) {
    const text = String(value ?? "").trim().replace(",", ".");
    if (text === "") return null;
    const number = Number(text);
    return Number.isFinite(number) && number >= 0 ? number : null;
  }

  /** Frase de resumo do que a correção fez. */
  function describeFix(result) {
    const region = `${result.region[0].toFixed(1)} a ${result.region[1].toFixed(1)} s`;
    const warning = result.squeezed ? " Atenção: a fala ficou apertada, tente um texto mais curto." : "";
    return `Trocado "${result.old_text}" por "${result.new_text}" (região ${region}). Duração: ${result.rule}.${warning}`;
  }

  /* ==================== estado ==================== */

  const speech = {
    ready: false,
    uploads: { iso: null, fix: null }, // { path, name } do último arquivo enviado em cada seção
    options: { iso: [], fix: [] },
    words: [],
    selection: null,
    anchor: null,
    result: null,
    busy: { iso: false, words: false, fix: false },
  };

  const el = (id) => document.getElementById(id);
  const esc = (value) => DMakerVoice.pure.esc(value);

  /* ==================== escolha do arquivo ==================== */

  function projectEntries() {
    if (!state.currentProject || !state.spec || !window.DMakerMedia) return [];
    const view = typeof edState !== "undefined" ? edState.view : null;
    return projectSourceOptions(DMakerMedia.collectMediaEntries(state.spec, view));
  }

  function renderSources(prefix) {
    const select = el(`speech-${prefix}-source`);
    const previous = select.value;
    const options = projectEntries();
    const items = options.map((o) => ({ value: o.value, label: o.label }));
    const uploaded = speech.uploads[prefix];
    if (uploaded) items.push({ value: "uploaded", label: `Enviado: ${uploaded.name}` });
    items.push({ value: UPLOAD_VALUE, label: "Enviar um arquivo..." });
    select.innerHTML = items.map((o) => `<option value="${esc(o.value)}">${esc(o.label)}</option>`).join("");
    speech.options[prefix] = options;
    const wanted = items.some((o) => o.value === previous) ? previous : items[0].value;
    select.value = wanted === UPLOAD_VALUE && uploaded ? "uploaded" : wanted;
    updateSourceFields(prefix);
  }

  function updateSourceFields(prefix) {
    el(`speech-${prefix}-upload-field`).hidden = el(`speech-${prefix}-source`).value !== UPLOAD_VALUE;
    updateButtons();
  }

  /** O arquivo escolhido na seção: { path, entry } (entry só para mídia do projeto) ou null. */
  function chosenSource(prefix) {
    const value = el(`speech-${prefix}-source`).value;
    if (value === "uploaded") return speech.uploads[prefix] ? { path: speech.uploads[prefix].path, entry: null } : null;
    const option = speech.options[prefix].find((o) => o.value === value);
    return option ? { path: option.path, entry: option.entry } : null;
  }

  async function uploadChosenFile(prefix) {
    const file = el(`speech-${prefix}-file`).files[0];
    if (!file) return;
    const form = new FormData();
    form.append("file", file, file.name);
    try {
      const response = await fetch("/api/speech/upload", { method: "POST", body: form });
      const text = await response.text();
      let data = null;
      try { data = JSON.parse(text); } catch { data = text; }
      if (!response.ok) throw new Error(formatApiError(data));
      speech.uploads[prefix] = { path: data.path, name: file.name };
      renderSources(prefix);
      el(`speech-${prefix}-source`).value = "uploaded";
      updateSourceFields(prefix);
    } catch (err) {
      handleError(err);
    }
  }

  /* ==================== andamento de um job ==================== */

  function showProgress(boxId, fillId, labelId, visible) {
    el(boxId).hidden = !visible;
    if (fillId && !visible) el(fillId).style.width = "0%";
    if (!visible && labelId) el(labelId).textContent = "";
  }

  /** Roda um job e desenha o andamento (etapa, porcentagem e cronômetro); resolve com o resultado. */
  async function runJob(start, boxId, fillId, labelId) {
    const startedAt = Date.now();
    let label = "Na fila...";
    let percent = 0;
    const draw = () => {
      const elapsed = DMakerVoice.pure.formatClock(Date.now() - startedAt);
      el(labelId).textContent = `${label} · ${elapsed} decorridos`;
      if (fillId) el(fillId).style.width = `${percent}%`;
    };
    showProgress(boxId, fillId, labelId, true);
    draw();
    const ticker = setInterval(draw, 1000);
    try {
      const { job_id } = await start();
      return await DMakerVoice.followJob(job_id, (evt) => {
        if (evt.label) { label = evt.label; percent = evt.percent || 0; }
        else if (evt.log) label = evt.log;
        draw();
      });
    } finally {
      clearInterval(ticker);
      showProgress(boxId, fillId, labelId, false);
    }
  }

  function updateButtons() {
    const iso = chosenSource("iso");
    el("speech-iso-run").disabled = speech.busy.iso || !iso;
    const fix = chosenSource("fix");
    el("speech-fix-transcribe").disabled = speech.busy.words || speech.busy.fix || !fix;
    const ready = !!fix && !!speech.selection && !!el("speech-fix-text").value.trim();
    el("speech-fix-run").disabled = speech.busy.fix || !ready;
    el("speech-fix-use").disabled = !(speech.result && speech.result.entry);
  }

  /* ==================== isolar voz ==================== */

  async function isolate() {
    const source = chosenSource("iso");
    if (!source) return;
    const body = {
      path: source.path,
      start: numberOrNull(el("speech-iso-start").value),
      end: numberOrNull(el("speech-iso-end").value),
      format: el("speech-iso-format").value,
    };
    speech.busy.iso = true;
    el("speech-iso-result").hidden = true;
    updateButtons();
    try {
      const result = await runJob(() => api.post("/api/speech/isolate", body), "speech-iso-progress", "speech-iso-fill", "speech-iso-label");
      el("speech-iso-voice").src = `${result.voice_url}&t=${Date.now()}`;
      el("speech-iso-background").src = `${result.background_url}&t=${Date.now()}`;
      el("speech-iso-voice-download").href = `${result.voice_url}&download=true`;
      el("speech-iso-background-download").href = `${result.background_url}&download=true`;
      el("speech-iso-result").hidden = false;
      showAlert("Voz e fundo prontos.", "success");
    } catch (err) {
      handleError(err);
    } finally {
      speech.busy.iso = false;
      updateButtons();
    }
  }

  /* ==================== corrigir fala: palavras ==================== */

  function renderWords() {
    const box = el("speech-words");
    const groups = groupWordsByBreath(speech.words);
    const picked = speech.selection;
    box.innerHTML = groups.map((group) => {
      const spans = group.map((index) => {
        const word = speech.words[index];
        const inside = picked && index >= picked.first && index <= picked.last;
        const anchor = speech.anchor === index && !picked;
        return `<span class="speech-word${inside ? " selected" : ""}${anchor ? " anchor" : ""}" data-word="${index}" title="${word.start.toFixed(2)} a ${word.end.toFixed(2)} s">${esc(word.text)}</span>`;
      }).join(" ");
      const first = speech.words[group[0]];
      return `<div class="speech-line"><span class="speech-time">${first.start.toFixed(1)} s</span>${spans}</div>`;
    }).join("");
    el("speech-selection").textContent = picked
      ? `Trecho escolhido: "${picked.text}" (${picked.start.toFixed(2)} a ${picked.end.toFixed(2)} s)`
      : speech.anchor !== null ? "Agora clique na última palavra do trecho." : "Nenhum trecho escolhido.";
  }

  function pickWord(index) {
    if (speech.anchor === null || speech.selection) {
      speech.anchor = index;
      speech.selection = null;
    } else {
      speech.selection = selectionFor(speech.words, speech.anchor, index);
      speech.anchor = null;
    }
    renderWords();
    updateButtons();
  }

  async function transcribe() {
    const source = chosenSource("fix");
    if (!source) return;
    const body = {
      path: source.path,
      start: numberOrNull(el("speech-fix-from").value),
      end: numberOrNull(el("speech-fix-to").value),
    };
    speech.busy.words = true;
    updateButtons();
    try {
      const result = await runJob(() => api.post("/api/speech/words", body), "speech-words-progress", null, "speech-words-label");
      speech.words = result.words;
      speech.selection = null;
      speech.anchor = null;
      el("speech-words-block").hidden = false;
      renderWords();
      if (!speech.words.length) showAlert("Nenhuma fala encontrada nesse trecho.", "error");
    } catch (err) {
      handleError(err);
    } finally {
      speech.busy.words = false;
      updateButtons();
    }
  }

  /* ==================== corrigir fala: gerar e conferir ==================== */

  async function fix() {
    const source = chosenSource("fix");
    const picked = speech.selection;
    const text = el("speech-fix-text").value.trim();
    if (!source || !picked || !text) return;
    const body = {
      path: source.path,
      text,
      start: picked.start,
      end: picked.end,
      voice: el("speech-fix-voice").value || null,
      save_voice: el("speech-fix-save").value.trim() || null,
      expand: el("speech-fix-expand").checked,
    };
    speech.busy.fix = true;
    el("speech-fix-result").hidden = true;
    updateButtons();
    try {
      const result = await runJob(() => api.post("/api/speech/fix", body), "speech-fix-progress", "speech-fix-fill", "speech-fix-label");
      speech.result = { ...result, entry: source.entry };
      showFixResult(speech.result);
      showAlert("Fala corrigida. Ouça o antes e o depois.", "success");
    } catch (err) {
      handleError(err);
    } finally {
      speech.busy.fix = false;
      updateButtons();
    }
  }

  function showFixResult(result) {
    el("speech-fix-summary").textContent = describeFix(result);
    el("speech-fix-original").src = result.original_url;
    el("speech-fix-fixed").src = `${result.audio_url}&t=${Date.now()}`;
    el("speech-fix-download").href = `${result.audio_url}&download=true`;
    el("speech-fix-result").hidden = false;
    updateButtons();
  }

  /** Toca o trecho trocado (com folga) no original ou no corrigido, parando no fim da janela. */
  function playRegion(which) {
    const result = speech.result;
    if (!result) return;
    const target = el(which === "original" ? "speech-fix-original" : "speech-fix-fixed");
    const other = el(which === "original" ? "speech-fix-fixed" : "speech-fix-original");
    other.pause();
    const window_ = abWindow(result.region);
    const stop = () => {
      if (target.currentTime >= window_.end) {
        target.pause();
        target.removeEventListener("timeupdate", stop);
      }
    };
    target.currentTime = window_.start;
    target.addEventListener("timeupdate", stop);
    target.play().catch(() => showAlert("Use o player para ouvir.", "success"));
  }

  /** Troca o original pelo corrigido nos trechos do projeto aberto e salva pelo fluxo normal. */
  async function useInProject() {
    const result = speech.result;
    if (!result || !result.entry || !state.currentProject || !state.spec) {
      showAlert("Escolha um arquivo do projeto aberto para usar a correção nele.", "error");
      return;
    }
    const ops = replaceSourceOps(state.spec, result.entry, result.output);
    if (!ops.length) {
      showAlert("Nenhum trecho do projeto usa este arquivo.", "error");
      return;
    }
    for (const op of ops) {
      if (!(await DMakerEditor.applyOp(op))) return;
    }
    if (await saveProject()) {
      showAlert(`Arquivo corrigido usado em ${ops.length} ponto(s) do projeto ${state.currentProject}.`, "success");
    }
  }

  /* ==================== ligação com a página ==================== */

  async function loadVoices() {
    const select = el("speech-fix-voice");
    try {
      const voices = await api.get("/api/voices");
      const items = voices.map((v) => ({ value: v.id, label: `${v.name} (${v.kind})` }));
      select.innerHTML = '<option value="">Voz do próprio falante (automática)</option>'
        + items.map((o) => `<option value="${esc(o.value)}">${esc(o.label)}</option>`).join("");
    } catch (err) {
      handleError(err);
    }
  }

  function bindEvents() {
    ["iso", "fix"].forEach((prefix) => {
      el(`speech-${prefix}-source`).addEventListener("change", () => {
        updateSourceFields(prefix);
        if (prefix === "fix") { speech.words = []; speech.selection = null; speech.anchor = null; el("speech-words-block").hidden = true; }
      });
      el(`speech-${prefix}-file`).addEventListener("change", () => uploadChosenFile(prefix));
    });
    el("speech-iso-run").addEventListener("click", isolate);
    el("speech-fix-transcribe").addEventListener("click", transcribe);
    el("speech-fix-run").addEventListener("click", fix);
    el("speech-fix-text").addEventListener("input", updateButtons);
    el("speech-words").addEventListener("click", (e) => {
      const word = e.target.closest("[data-word]");
      if (word) pickWord(Number(word.dataset.word));
    });
    el("speech-ab-original").addEventListener("click", () => playRegion("original"));
    el("speech-ab-fixed").addEventListener("click", () => playRegion("fixed"));
    el("speech-fix-use").addEventListener("click", useInProject);
  }

  function init() {
    if (speech.ready || !el("speech-fix-block")) return;
    speech.ready = true;
    bindEvents();
    renderSources("iso");
    renderSources("fix");
    updateButtons();
    loadVoices();
  }

  function onShow() {
    if (!speech.ready) return;
    renderSources("iso");
    renderSources("fix");
    loadVoices();
  }

  window.DMakerSpeech = {
    init,
    onShow,
    pure: { groupWordsByBreath, selectionFor, projectSourceOptions, replaceSourceOps, abWindow, numberOrNull, describeFix },
  };
})();
