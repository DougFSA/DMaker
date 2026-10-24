"use strict";
/*
 * DMaker - dublagem na aba "Voz": traduz a fala de um vídeo ou áudio e a refaz no idioma alvo com a voz
 * clonada de quem fala, mantendo a música e o ruído de fundo.
 *
 * Dois passos, com a revisão no meio: "Preparar" (job: separa a voz, transcreve e traduz) devolve as falas
 * numa tabela editável; "Gerar dublagem" (job) sintetiza e monta. Cada fala sintetizada fica em cache no
 * servidor, então corrigir uma tradução e gerar de novo refaz só aquela.
 *
 * Tudo é lento na CPU, então cada ação é um job: o POST devolve job_id e o andamento chega por SSE, pelo
 * acompanhamento de jobs do voice.js (DMakerVoice.followJob). O arquivo vem de uma lista (mídia do projeto
 * aberto) ou de um envio (reaproveita /api/speech/upload). Usa em tempo de execução, vindos de app.js,
 * editor.js e speech.js: api, state, showAlert, handleError, formatApiError, saveProject, edState,
 * DMakerEditor.applyOp e DMakerSpeech.pure. O que é puro fica em window.DMakerDub.pure.
 *
 * window.DMakerDub:
 *   init()      chamado por app.js ao terminar de carregar o estado
 *   onShow()    chamado por app.js quando a aba Voz aparece (atualiza arquivos do projeto, vozes e projetos salvos)
 *   pure        parseGlossary, parseKeepDb, parseSpeakerCount, segmentEdits, describeResult, describeStretch, describeStems,
 *               statusLabel, segmentRowsHtml
 */
(function () {
  const UPLOAD_VALUE = "upload";
  const STATUS_LABELS = {
    fits: "cabe",
    advances: "avança na pausa",
    squeezed: "comprimida",
    stretched: "vídeo esticado",
    overflow: "não coube",
    empty: "sem tradução",
  };

  /* ==================== funções puras ==================== */

  /** Termos separados por vírgula ou quebra de linha, sem vazios nem repetidos (sem diferenciar caixa). */
  function parseGlossary(text) {
    const seen = new Set();
    return String(text || "")
      .split(/[,\n]/)
      .map((term) => term.trim())
      .filter((term) => {
        const key = term.toLowerCase();
        if (!term || seen.has(key)) return false;
        seen.add(key);
        return true;
      });
  }

  /** Volume da voz original por baixo, em dB: vazio é "sem voz original"; 18 e -18 valem -18 (nunca acima de 0). */
  function parseKeepDb(value) {
    const text = String(value ?? "").trim().replace(",", ".");
    if (text === "") return null;
    const number = Number(text);
    return Number.isFinite(number) ? -Math.abs(number) : null;
  }

  /** Quantidade de pessoas falando: vazio é "deixar o áudio decidir" (null); só inteiros de 1 a 12 valem. */
  function parseSpeakerCount(value) {
    const text = String(value ?? "").trim();
    if (!/^\d+$/.test(text)) return null;
    const number = Number(text);
    return number >= 1 && number <= 12 ? number : null;
  }

  /** Lista {id, text, locked, speaker?} a partir das linhas da tabela; sem falante escolhido, a chave some. */
  function segmentEdits(rows) {
    return rows.map((row) => ({
      id: row.id,
      text: String(row.text || "").trim(),
      locked: !!row.locked,
      speaker: row.speaker || undefined,
    }));
  }

  /** Frase de resumo das trilhas exportadas, com o quanto a voz original ficava baixa no vídeo dublado. */
  function describeStems(result) {
    const kept = result.original_voice_db === null || result.original_voice_db === undefined
      ? ""
      : ` O vídeo dublado usa a voz original a ${result.original_voice_db} dB; a trilha dela vem sem atenuar.`;
    return `Trilhas prontas (${result.files.join(", ")}), cada uma com ${result.duration.toFixed(2)} s.${kept}`;
  }

  function statusLabel(status) {
    return STATUS_LABELS[status] || status;
  }

  /** Frase de resumo do que a geração fez. */
  function describeResult(result) {
    const total = result.report.length;
    const made = result.regenerated;
    const seconds = Object.values(result.timings || {}).reduce((sum, value) => sum + value, 0);
    const reused = total - made;
    const base = `${made} fala(s) sintetizada(s) agora e ${reused} reaproveitada(s) do cache, em ${seconds.toFixed(0)} s.`;
    return base + describeStretch(result.stretched, result.output_seconds);
  }

  /** Frase sobre o vídeo esticado (vazia quando nada foi esticado): quantos trechos, quantos segundos a mais e a duração final. */
  function describeStretch(stretched, outputSeconds) {
    if (!stretched || !stretched.length) return "";
    const added = stretched.reduce((sum, item) => sum + item.added_seconds, 0);
    const total = outputSeconds ? ` O vídeo final tem ${outputSeconds.toFixed(1)} s.` : "";
    return ` Vídeo esticado em ${stretched.length} trecho(s), ${added.toFixed(1)} s a mais.${total}`;
  }

  function escapeHtml(value) {
    return String(value ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  }

  /** O select de falante de uma fala: um item por falante do projeto, o da fala marcado. */
  function speakerSelectHtml(segment, speakers) {
    const options = speakers.map((name) => `<option value="${escapeHtml(name)}"${name === segment.speaker ? " selected" : ""}>${escapeHtml(name)}</option>`);
    const empty = segment.speaker ? "" : '<option value="" selected>Sem falante</option>';
    return `<select class="dub-speaker-pick" aria-label="Falante da fala ${escapeHtml(segment.id)}" title="Quem fala: a fala dubla com a voz dele">${empty}${options.join("")}</select>`;
  }

  /** HTML da tabela de falas: tempo, falante (com 2 ou mais no projeto), original, tradução editável e a trava. */
  function segmentRowsHtml(segments, speakers = []) {
    const withSpeakers = speakers.length > 1;
    return segments.map((s) => `<div class="dub-row" data-id="${escapeHtml(s.id)}">`
      + `<div class="dub-who"><div class="dub-time">${s.start.toFixed(1)} a ${s.end.toFixed(1)} s</div>`
      + `${withSpeakers ? speakerSelectHtml(s, speakers) : ""}</div>`
      + `<div class="dub-original">${escapeHtml(s.original)}</div>`
      + `<textarea class="dub-text" rows="2" aria-label="Tradução da fala ${escapeHtml(s.id)}">${escapeHtml(s.text)}</textarea>`
      + '<div class="dub-status"></div>'
      + `<label class="dub-lock" title="Travada: traduzir de novo não mexe nesta fala"><input type="checkbox" class="dub-locked"${s.locked ? " checked" : ""}> travar</label>`
      + "</div>").join("");
  }

  /* ==================== estado ==================== */

  const dub = {
    ready: false,
    upload: null, // { path, name } do último arquivo enviado
    options: [],
    project: null, // resposta do servidor: { project, segments, ... }
    entry: null, // mídia do projeto aberto que foi dublada (para "Usar no projeto")
    result: null,
    busy: false,
  };

  const el = (id) => document.getElementById(id);
  const esc = (value) => DMakerVoice.pure.esc(value);

  /* ==================== escolha do arquivo ==================== */

  function projectEntries() {
    if (!state.currentProject || !state.spec || !window.DMakerMedia) return [];
    const view = typeof edState !== "undefined" ? edState.view : null;
    return DMakerSpeech.pure.projectSourceOptions(DMakerMedia.collectMediaEntries(state.spec, view));
  }

  function renderSources() {
    const select = el("dub-source");
    const previous = select.value;
    const options = projectEntries();
    const items = options.map((o) => ({ value: o.value, label: o.label }));
    if (dub.upload) items.push({ value: "uploaded", label: `Enviado: ${dub.upload.name}` });
    items.push({ value: UPLOAD_VALUE, label: "Enviar um arquivo..." });
    select.innerHTML = items.map((o) => `<option value="${esc(o.value)}">${esc(o.label)}</option>`).join("");
    dub.options = options;
    const wanted = items.some((o) => o.value === previous) ? previous : items[0].value;
    select.value = wanted === UPLOAD_VALUE && dub.upload ? "uploaded" : wanted;
    updateSourceFields();
  }

  /** A quantidade de pessoas só faz sentido no modo "uma voz por pessoa". */
  function updateSpeakerFields() {
    el("dub-speaker-count-field").hidden = el("dub-speaker").value !== "per_speaker";
  }

  function updateSourceFields() {
    el("dub-upload-field").hidden = el("dub-source").value !== UPLOAD_VALUE;
    updateButtons();
  }

  /** O arquivo escolhido: { path, entry } (entry só para mídia do projeto) ou null. */
  function chosenSource() {
    const value = el("dub-source").value;
    if (value === "uploaded") return dub.upload ? { path: dub.upload.path, entry: null } : null;
    const option = dub.options.find((o) => o.value === value);
    return option ? { path: option.path, entry: option.entry } : null;
  }

  async function uploadChosenFile() {
    const file = el("dub-file").files[0];
    if (!file) return;
    const form = new FormData();
    form.append("file", file, file.name);
    try {
      const response = await fetch("/api/speech/upload", { method: "POST", body: form });
      const text = await response.text();
      let data = null;
      try { data = JSON.parse(text); } catch { data = text; }
      if (!response.ok) throw new Error(formatApiError(data));
      dub.upload = { path: data.path, name: file.name };
      renderSources();
      el("dub-source").value = "uploaded";
      updateSourceFields();
    } catch (err) {
      handleError(err);
    }
  }

  /* ==================== andamento de um job ==================== */

  /** Roda um job e desenha o andamento (etapa, porcentagem e cronômetro); resolve com o resultado. */
  async function runJob(start, boxId, fillId, labelId) {
    const startedAt = Date.now();
    let label = "Na fila...";
    let percent = 0;
    const draw = () => {
      const elapsed = DMakerVoice.pure.formatClock(Date.now() - startedAt);
      el(labelId).textContent = `${label} · ${elapsed} decorridos`;
      el(fillId).style.width = `${percent}%`;
    };
    el(boxId).hidden = false;
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
      el(boxId).hidden = true;
      el(fillId).style.width = "0%";
    }
  }

  function updateButtons() {
    el("dub-prepare").disabled = dub.busy || !chosenSource() || el("dub-from").value === el("dub-to").value;
    el("dub-open-run").disabled = dub.busy || !el("dub-open").value;
    ["dub-save", "dub-retranslate", "dub-render", "dub-stems"].forEach((id) => { el(id).disabled = dub.busy || !dub.project; });
    el("dub-use").disabled = !(dub.result && dub.result.entry);
  }

  /* ==================== projeto de dublagem ==================== */

  function showProject(project) {
    dub.project = project;
    const speakers = project.speakers || [];
    el("dub-segments").innerHTML = segmentRowsHtml(project.segments, speakers);
    el("dub-segments").classList.toggle("dub-with-speakers", speakers.length > 1);
    const model = project.translator_model ? ` Tradução: ${project.translator_model}.` : "";
    const people = speakers.length > 1 ? ` ${speakers.length} falantes: troque o falante de uma fala se o programa errou; só essa fala é refeita.` : "";
    el("dub-project-summary").textContent = `${project.segments.length} fala(s), ${project.source_language} para ${project.target_language}.${model}${people} Corrija o que precisar; as traduções travadas não mudam ao traduzir de novo.`;
    el("dub-keep").value = project.keep_original_db === null || project.keep_original_db === undefined ? "" : project.keep_original_db;
    el("dub-speaker").value = project.speaker_mode;
    el("dub-fit").value = project.fit_mode || "voz";
    updateSpeakerFields();
    el("dub-voice").value = project.voice || "";
    el("dub-project-block").hidden = false;
    updateButtons();
  }

  function collectRows() {
    return Array.from(el("dub-segments").querySelectorAll(".dub-row")).map((row) => ({
      id: row.dataset.id,
      text: row.querySelector(".dub-text").value,
      locked: row.querySelector(".dub-locked").checked,
      speaker: row.querySelector(".dub-speaker-pick")?.value || null,
    }));
  }

  async function saveProjectEdits() {
    const body = {
      project: dub.project.project,
      segments: segmentEdits(collectRows()),
      keep_original_db: parseKeepDb(el("dub-keep").value),
      speaker_mode: el("dub-speaker").value,
      fit_mode: el("dub-fit").value,
      voice: el("dub-voice").value || null,
    };
    const saved = await api.put("/api/dub/project", body);
    showProject(saved);
    return saved;
  }

  async function prepare() {
    const source = chosenSource();
    if (!source) return;
    const body = {
      path: source.path,
      source_language: el("dub-from").value,
      target_language: el("dub-to").value,
      speaker_mode: el("dub-speaker").value,
      fit_mode: el("dub-fit").value,
      num_speakers: el("dub-speaker").value === "per_speaker" ? parseSpeakerCount(el("dub-speaker-count").value) : null,
      voice: el("dub-voice").value || null,
      keep_original_db: parseKeepDb(el("dub-keep").value),
      glossary: parseGlossary(el("dub-glossary").value),
    };
    dub.busy = true;
    dub.result = null;
    el("dub-result").hidden = true;
    updateButtons();
    try {
      const project = await runJob(() => api.post("/api/dub/prepare", body), "dub-prepare-progress", "dub-prepare-fill", "dub-prepare-label");
      dub.entry = source.entry;
      showProject(project);
      loadSavedProjects();
      showAlert("Tradução pronta. Revise as falas e gere a dublagem.", "success");
    } catch (err) {
      handleError(err);
    } finally {
      dub.busy = false;
      updateButtons();
    }
  }

  async function retranslate() {
    dub.busy = true;
    updateButtons();
    try {
      await saveProjectEdits();
      const project = await runJob(() => api.post("/api/dub/retranslate", { project: dub.project.project }), "dub-prepare-progress", "dub-prepare-fill", "dub-prepare-label");
      showProject(project);
      showAlert("Falas destravadas traduzidas de novo.", "success");
    } catch (err) {
      handleError(err);
    } finally {
      dub.busy = false;
      updateButtons();
    }
  }

  async function render() {
    dub.busy = true;
    el("dub-result").hidden = true;
    updateButtons();
    try {
      await saveProjectEdits();
      const result = await runJob(
        () => api.post("/api/dub/render", { project: dub.project.project, draft: el("dub-draft").checked }),
        "dub-render-progress", "dub-render-fill", "dub-render-label",
      );
      dub.result = { ...result, entry: dub.entry || null };
      showResult(dub.result);
      showAlert(result.warnings.length ? "Dublagem pronta, com avisos." : "Dublagem pronta. Ouça o original e o dublado.", result.warnings.length ? "error" : "success");
    } catch (err) {
      handleError(err);
    } finally {
      dub.busy = false;
      updateButtons();
    }
  }

  /** Gera as trilhas separadas (as falas já sintetizadas vêm do cache) e baixa o .zip. */
  async function downloadStems() {
    dub.busy = true;
    updateButtons();
    try {
      await saveProjectEdits();
      const result = await runJob(
        () => api.post("/api/dub/stems", { project: dub.project.project, draft: el("dub-draft").checked }),
        "dub-render-progress", "dub-render-fill", "dub-render-label",
      );
      const link = document.createElement("a");
      link.href = result.zip_url;
      link.download = "";
      document.body.appendChild(link);
      link.click();
      link.remove();
      showAlert(describeStems(result), "success");
    } catch (err) {
      handleError(err);
    } finally {
      dub.busy = false;
      updateButtons();
    }
  }

  /** Escreve em cada linha da tabela como a fala coube no tempo (cabe, avança, comprimida, não coube). */
  function markStatuses(report) {
    report.forEach((item) => {
      const row = el("dub-segments").querySelector(`.dub-row[data-id="${item.id}"]`);
      if (!row) return;
      const status = row.querySelector(".dub-status");
      const stretch = item.video_stretch > 1 ? ` ${item.video_stretch.toFixed(2)}x` : "";
      status.textContent = `${statusLabel(item.status)}${stretch}${item.cached ? "" : " · nova"}`;
      status.title = item.message;
      status.classList.toggle("dub-status-warn", item.status === "overflow");
    });
  }

  function showResult(result) {
    markStatuses(result.report);
    el("dub-summary").textContent = describeResult(result);
    el("dub-warnings").innerHTML = result.warnings.map((w) => `<li>${esc(w)}</li>`).join("");
    el("dub-original").src = result.original_url;
    el("dub-dubbed").src = `${result.output_url}&t=${Date.now()}`;
    el("dub-download").href = result.download_url;
    el("dub-download-srt").href = result.srt_url;
    el("dub-result").hidden = false;
    updateButtons();
  }

  /** Toca o original ou o dublado do começo, parando o outro: para comparar de ouvido. */
  function play(which) {
    const target = el(which === "original" ? "dub-original" : "dub-dubbed");
    const other = el(which === "original" ? "dub-dubbed" : "dub-original");
    other.pause();
    target.currentTime = 0;
    target.play().catch(() => showAlert("Use o player para ouvir.", "success"));
  }

  /** Troca o original pelo dublado nos trechos do projeto aberto e salva pelo fluxo normal. */
  async function useInProject() {
    const result = dub.result;
    if (!result || !result.entry || !state.currentProject || !state.spec) {
      showAlert("Escolha um arquivo do projeto aberto para usar a dublagem nele.", "error");
      return;
    }
    const ops = DMakerSpeech.pure.replaceSourceOps(state.spec, result.entry, result.output);
    if (!ops.length) {
      showAlert("Nenhum trecho do projeto usa este arquivo.", "error");
      return;
    }
    for (const op of ops) {
      if (!(await DMakerEditor.applyOp(op))) return;
    }
    if (await saveProject()) {
      showAlert(`Dublagem usada em ${ops.length} ponto(s) do projeto ${state.currentProject}.`, "success");
    }
  }

  /* ==================== projetos salvos e listas ==================== */

  async function loadSavedProjects() {
    const select = el("dub-open");
    try {
      const projects = await api.get("/api/dub/projects");
      select.innerHTML = '<option value="">Projetos de dublagem salvos...</option>'
        + projects.map((p) => `<option value="${esc(p.path)}">${esc(p.name)}</option>`).join("");
    } catch (err) {
      handleError(err);
    }
    updateButtons();
  }

  async function openSavedProject() {
    const path = el("dub-open").value;
    if (!path) return;
    try {
      const project = await api.get(`/api/dub/project?path=${encodeURIComponent(path)}`);
      dub.entry = null;
      dub.result = null;
      el("dub-result").hidden = true;
      showProject(project);
    } catch (err) {
      handleError(err);
    }
  }

  async function loadVoicesAndLanguages() {
    try {
      const [voices, options] = await Promise.all([api.get("/api/voices"), api.get("/api/voices/design-options")]);
      el("dub-voice").innerHTML = '<option value="">Clonar a voz de quem fala (automático)</option>'
        + voices.map((v) => `<option value="${esc(v.id)}">${esc(v.name)} (${esc(v.kind)})</option>`).join("");
      const languages = options.languages.map((l) => `<option value="${esc(l.value)}">${esc(l.label)}</option>`).join("");
      const from = el("dub-from").value || "pt";
      const to = el("dub-to").value || "en";
      el("dub-from").innerHTML = languages;
      el("dub-to").innerHTML = languages;
      el("dub-from").value = from;
      el("dub-to").value = to;
    } catch (err) {
      handleError(err);
    }
    updateButtons();
  }

  /* ==================== ligação com a página ==================== */

  function bindEvents() {
    el("dub-source").addEventListener("change", updateSourceFields);
    el("dub-file").addEventListener("change", uploadChosenFile);
    el("dub-speaker").addEventListener("change", updateSpeakerFields);
    el("dub-from").addEventListener("change", updateButtons);
    el("dub-to").addEventListener("change", updateButtons);
    el("dub-open").addEventListener("change", updateButtons);
    el("dub-prepare").addEventListener("click", prepare);
    el("dub-open-run").addEventListener("click", openSavedProject);
    el("dub-save").addEventListener("click", async () => {
      try { await saveProjectEdits(); showAlert("Traduções salvas.", "success"); } catch (err) { handleError(err); }
    });
    el("dub-retranslate").addEventListener("click", retranslate);
    el("dub-render").addEventListener("click", render);
    el("dub-stems").addEventListener("click", downloadStems);
    el("dub-play-original").addEventListener("click", () => play("original"));
    el("dub-play-dubbed").addEventListener("click", () => play("dubbed"));
    el("dub-use").addEventListener("click", useInProject);
  }

  function init() {
    if (dub.ready || !el("dub-block")) return;
    dub.ready = true;
    bindEvents();
    updateSpeakerFields();
    renderSources();
    loadVoicesAndLanguages();
    loadSavedProjects();
  }

  function onShow() {
    if (!dub.ready) return;
    renderSources();
    loadVoicesAndLanguages();
    loadSavedProjects();
  }

  window.DMakerDub = {
    init,
    onShow,
    pure: {
      parseGlossary,
      parseKeepDb,
      parseSpeakerCount,
      segmentEdits,
      describeResult,
      describeStretch,
      describeStems,
      statusLabel,
      segmentRowsHtml,
    },
  };
})();
