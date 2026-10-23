"use strict";
/*
 * DMaker - estúdio de voz (aba "Voz"): biblioteca de vozes, clonagem (arquivo ou microfone), design de voz
 * por atributos, narração de um roteiro e inserção da narração no projeto aberto.
 *
 * Toda síntese na CPU é lenta (dezenas de segundos por segundo de áudio), então ouvir a prévia e gerar
 * a narração são jobs: o POST devolve job_id e o andamento chega por SSE (/api/jobs/{id}/events). Na narração
 * cada fala pronta chega como evento "utterance" e toca na hora (prévia ao vivo, Web Audio); "Parar" cancela
 * o job entre falas (POST /api/jobs/{id}/cancel) e o que já saiu fica no cache.
 *
 * O módulo roda dentro de uma função para não poluir o escopo global (os outros scripts declaram
 * constantes de nível superior). Usa em tempo de execução, vindos de app.js: api, state, showAlert,
 * handleError, formatApiError, saveProject, syncJsonFromSpec, pruneEmpty. O que é puro fica exposto em
 * window.DMakerVoice.pure.
 *
 * window.DMakerVoice:
 *   init({ brands })   chamado por app.js ao terminar de carregar o estado
 *   onShow()           chamado por app.js quando a aba Voz aparece (atualiza a lista de vozes)
 *   followJob(id, cb)  acompanha um job por SSE (usado por speech.js, que cuida de isolar voz e corrigir fala)
 *   pure               estimateSeconds, formatDuration, formatClock, recordingAdvice, buildNarrationItem,
 *                      planLiveChunk, playingIndexAt, liveStatusText, createLivePlayer...
 */
(function () {
  const CHARS_PER_SECOND = 14; // ritmo médio da fala em português, para estimar a duração do roteiro
  const PAUSE_MARKER = /\[pausa\s+(\d+(?:[.,]\d+)?)\]/gi;
  const INLINE_OVERRIDE = /\[\[([^\]]{0,256})\]\]/g; // [[termo|pronúncia]] ou [[pronúncia]]
  const RECOMMENDED_MIN_S = 5;
  const RECOMMENDED_MAX_S = 8;
  const MAX_USED_S = 15; // o servidor só usa os primeiros 15 s da referência
  const MAX_RECORDING_S = 30;
  const HISTORY_LIMIT = 30;
  const LAST_VOICE_KEY = "dmaker.voice.lastVoice";
  const KIND_LABELS = { clone: "clonada", design: "desenhada" };
  const LIVE_FADE_S = 0.005; // fade nas pontas de cada fala da prévia ao vivo (ver planLiveChunk)
  const LIVE_LEAD_S = 0.06; // folga para agendar a primeira fala (ou uma atrasada) no futuro do relógio de áudio
  const LIVE_STOP_FADE_S = 0.02; // rampa de silêncio ao parar

  /* ==================== funções puras ==================== */

  /** Segundos estimados de fala: caracteres / 14 por segundo, ajustado pela velocidade, mais as
   * pausas fixas dos marcadores [pausa 1.2]. */
  function estimateSeconds(text, speed) {
    let pauses = 0;
    const spoken = spokenForm(text).replace(PAUSE_MARKER, (_, value) => {
      pauses += parseFloat(value.replace(",", "."));
      return " ";
    });
    const characters = spoken.replace(/\s+/g, " ").trim().length;
    const rate = speed > 0 ? speed : 1;
    return characters / CHARS_PER_SECOND / rate + pauses;
  }

  /** O texto como a voz o lê: [[termo|pronúncia]] vira a pronúncia (o servidor faz o mesmo). */
  function spokenForm(text) {
    return String(text || "").replace(INLINE_OVERRIDE, (_, inner) => inner.split("|").slice(-1)[0]);
  }

  /** Frase curta para ouvir um termo do dicionário, no idioma dele (o termo duas vezes: a primeira pode soar solta). */
  function pronunciationPreviewText(term, language) {
    const word = String(term || "").trim();
    const code = String(language || "pt").toLowerCase().split(/[-_]/)[0];
    if (code === "en") return `I say ${word}. Again: ${word}.`;
    return `Eu falo ${word}. Repito: ${word}.`;
  }

  /** "42 s" abaixo de um minuto, "1 min 05 s" acima. */
  function formatDuration(seconds) {
    const total = Math.max(0, Math.round(seconds || 0));
    if (total < 60) return `${total} s`;
    return `${Math.floor(total / 60)} min ${String(total % 60).padStart(2, "0")} s`;
  }

  /** Cronômetro "m:ss" a partir de milissegundos. */
  function formatClock(milliseconds) {
    const total = Math.max(0, Math.floor((milliseconds || 0) / 1000));
    return `${Math.floor(total / 60)}:${String(total % 60).padStart(2, "0")}`;
  }

  /** Conselho sobre o tamanho da gravação de referência: { level: "bad"|"ok"|"good", text }. */
  function recordingAdvice(seconds) {
    if (seconds < 3) return { level: "bad", text: "Muito curto: grave pelo menos 5 segundos de fala." };
    if (seconds < RECOMMENDED_MIN_S) return { level: "ok", text: "Quase lá: o ideal são de 5 a 8 segundos." };
    if (seconds <= RECOMMENDED_MAX_S) return { level: "good", text: "Ótimo: de 5 a 8 segundos de fala limpa." };
    if (seconds <= MAX_USED_S) return { level: "ok", text: "Dá para usar, mas de 5 a 8 segundos já bastam." };
    return { level: "bad", text: `Só os primeiros ${MAX_USED_S} segundos serão usados.` };
  }

  /** Extensão do arquivo gravado pelo MediaRecorder, a partir do tipo MIME. */
  function extensionForMime(mime) {
    const type = String(mime || "").toLowerCase();
    if (type.includes("ogg")) return "ogg";
    if (type.includes("mp4")) return "m4a";
    if (type.includes("wav")) return "wav";
    return "webm";
  }

  /** Item de project.audio.narration: só leva idioma e seed quando a pessoa escolheu. */
  function buildNarrationItem(entry, start) {
    const item = {
      text: entry.text,
      start: Math.round(Math.max(0, start || 0) * 100) / 100,
      speed: entry.speed,
    };
    if (entry.voiceId) item.voice = entry.voiceId;
    if (entry.language) item.language = entry.language;
    if (entry.seed !== null && entry.seed !== undefined) item.seed = entry.seed;
    return item;
  }

  /* ---------- prévia ao vivo (Web Audio) ---------- */

  /**
   * Onde e quando tocar a próxima fala da prévia ao vivo. Funde as falas na linha do tempo do AudioContext:
   * cada uma começa exatamente onde a anterior terminou mais a pausa do roteiro (`cursor`), então a emenda
   * não depende de timers (que oscilam dezenas de ms) e sim do relógio de áudio. Se a fala chegou depois do
   * ponto previsto (`cursor` já passou), toca assim que der: `late` avisa que a CPU não acompanhou.
   * O fade de 5 ms nas duas pontas tira o degrau que o corte seco de uma amostra não nula faz (o estalo);
   * é curto demais para ser ouvido como queda de volume (menos que qualquer fonema) e nunca passa de metade
   * da fala, para não apagar uma fala curtíssima.
   */
  function planLiveChunk(cursor, now, duration, pauseAfter) {
    const earliest = now + LIVE_LEAD_S;
    const late = cursor !== null && cursor < now;
    const startAt = cursor !== null && !late ? cursor : earliest;
    const endAt = startAt + duration;
    return {
      startAt,
      endAt,
      fade: Math.min(LIVE_FADE_S, duration / 2),
      nextCursor: endAt + Math.max(0, pauseAfter || 0),
      late,
    };
  }

  /** Índice (a partir de 1) da fala que toca no instante `time`, contando a pausa depois dela; null se nada
   * foi agendado ou se tudo o que chegou já terminou. `plans` vem na ordem, cada um com `index` e `nextCursor`. */
  function playingIndexAt(plans, time) {
    const current = plans.find((plan) => time < plan.nextCursor);
    return current ? current.index : null;
  }

  /** Frase de andamento da prévia ao vivo. `view`: { total, ready, playing, stoppedAfter }. */
  function liveStatusText(view) {
    const { total, ready, playing } = view;
    if (view.stoppedAfter !== null && view.stoppedAfter !== undefined) {
      return `Parado depois da fala ${view.stoppedAfter} de ${total}. O que já saiu ficou guardado.`;
    }
    if (!ready) return "Esperando a primeira fala ficar pronta...";
    if (playing) return `Tocando fala ${playing} de ${total}${ready < total ? ` · ${ready} prontas` : ""}`;
    if (ready < total) return `Esperando a fala ${ready + 1} de ${total} ficar pronta...`;
    return "Prévia ao vivo terminada.";
  }

  /**
   * Toca os pedaços (falas) na ordem em que chegam, sem esperar o roteiro inteiro. `context` é um
   * AudioContext (ou OfflineAudioContext, nos testes); `loadChunk(url)` devolve os bytes do WAV. Cada
   * fala é decodificada e agendada pelo relógio do contexto, uma depois da outra, mesmo que a decodificação
   * de uma demore mais que a da seguinte (a cadeia de promessas preserva a ordem).
   */
  function createLivePlayer(context, loadChunk, onError) {
    const master = context.createGain();
    master.connect(context.destination);
    const plans = [];
    const sources = [];
    let cursor = null;
    let chain = Promise.resolve();
    let stopped = false;

    function place(chunk, buffer) {
      const plan = planLiveChunk(cursor, context.currentTime, buffer.duration, chunk.pauseAfter);
      const source = context.createBufferSource();
      source.buffer = buffer;
      const gain = context.createGain();
      gain.gain.setValueAtTime(0, plan.startAt);
      gain.gain.linearRampToValueAtTime(1, plan.startAt + plan.fade);
      gain.gain.setValueAtTime(1, plan.endAt - plan.fade);
      gain.gain.linearRampToValueAtTime(0, plan.endAt);
      source.connect(gain);
      gain.connect(master);
      source.onended = () => gain.disconnect();
      source.start(plan.startAt);
      sources.push(source);
      cursor = plan.nextCursor;
      plans.push({ index: chunk.index, ...plan });
    }

    return {
      enqueue(chunk) {
        chain = chain
          .then(async () => {
            if (stopped) return;
            const buffer = await context.decodeAudioData(await loadChunk(chunk.url));
            if (!stopped) place(chunk, buffer);
          })
          .catch((err) => { if (onError) onError(err); });
        return chain;
      },
      /** Silencia em 20 ms (rampa, não corte seco, pelo mesmo motivo do fade) e descarta o que faltava tocar. */
      stop() {
        stopped = true;
        const now = context.currentTime;
        master.gain.cancelScheduledValues(now);
        master.gain.setValueAtTime(master.gain.value, now);
        master.gain.linearRampToValueAtTime(0, now + LIVE_STOP_FADE_S);
        sources.forEach((source) => { try { source.stop(now + LIVE_STOP_FADE_S + 0.005); } catch { /* já terminou */ } });
      },
      plans,
      ready: () => plans.length,
      playingIndex: () => playingIndexAt(plans, context.currentTime),
    };
  }

  /** Última linha útil de um erro de job ("ValueError: mensagem\nTraceback...") sem o nome da exceção. */
  function jobErrorMessage(error) {
    const first = String(error || "Erro desconhecido").split("\n")[0];
    return first.replace(/^\w+(Error|Exception):\s*/, "") || "Erro desconhecido";
  }

  function esc(value) {
    return String(value ?? "").replace(/[&<>"']/g, (c) => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
    }[c]));
  }

  /* ==================== estado ==================== */

  const studio = {
    ready: false,
    voices: [],
    options: null,
    brands: [],
    brandFilter: "",
    history: [],
    current: null,
    busy: false,
    previewing: new Set(),
    pronunciation: [],
    listening: new Set(),
    recorder: null,
    recordedBlob: null,
    recordingStartedAt: 0,
    recordingTicker: null,
    recordingStream: null,
    elapsedTicker: null,
    stopping: false,
    jobId: null, // job de narração em andamento (para o botão Parar)
    audioContext: null,
    live: null, // prévia ao vivo da narração em andamento
    liveTicker: null,
  };

  const el = (id) => document.getElementById(id);

  function optionsHtml(items, blankLabel) {
    const blank = blankLabel === undefined ? "" : `<option value="">${esc(blankLabel)}</option>`;
    return blank + items.map((o) => `<option value="${esc(o.value)}">${esc(o.label)}</option>`).join("");
  }

  function languageLabel(code) {
    const found = ((studio.options && studio.options.languages) || []).find((l) => l.value === code);
    return found ? found.label : code;
  }

  function rememberVoice(voiceId) {
    try { localStorage.setItem(LAST_VOICE_KEY, voiceId || ""); } catch { /* sem armazenamento local: só não lembra */ }
  }

  function rememberedVoice() {
    try { return localStorage.getItem(LAST_VOICE_KEY) || ""; } catch { return ""; }
  }

  /* ==================== job com andamento por SSE ==================== */

  /** Acompanha um job até o fim; resolve com o resultado ou rejeita com a mensagem do erro. Um job parado
   * a pedido rejeita com `cancelled = true` e o que já ficou pronto em `result`. `onEvent` recebe todo
   * evento cru (é por ele que a prévia ao vivo recebe cada fala pronta). */
  function followJob(jobId, onProgress, onEvent) {
    return new Promise((resolve, reject) => {
      const source = new EventSource(`/api/jobs/${jobId}/events`);
      let finished = false;
      source.onmessage = (message) => {
        let evt;
        try { evt = JSON.parse(message.data); } catch { return; }
        if (onEvent) onEvent(evt);
        if (evt.kind === "progress" && onProgress) onProgress(evt);
        if (evt.kind === "log" && onProgress) onProgress({ log: evt.message });
        if (evt.kind === "end") {
          finished = true;
          source.close();
          if (evt.status === "done") resolve(evt.result);
          else if (evt.status === "cancelled") {
            reject(Object.assign(new Error("Cancelado."), { cancelled: true, result: evt.result }));
          } else reject(new Error(jobErrorMessage(evt.error)));
        }
      };
      source.onerror = () => {
        if (!finished && source.readyState === 2) reject(new Error("A conexão com o servidor foi perdida."));
      };
    });
  }

  function startElapsedTicker(render) {
    const startedAt = Date.now();
    stopElapsedTicker();
    render(0);
    studio.elapsedTicker = setInterval(() => render(Date.now() - startedAt), 1000);
  }

  function stopElapsedTicker() {
    clearInterval(studio.elapsedTicker);
    studio.elapsedTicker = null;
  }

  /* ==================== lista de vozes ==================== */

  async function loadVoices() {
    const query = studio.brandFilter ? `?brand=${encodeURIComponent(studio.brandFilter)}` : "";
    studio.voices = await api.get(`/api/voices${query}`);
    renderVoices();
    renderScriptVoiceSelect();
  }

  function renderVoices() {
    const list = el("voice-list");
    if (!studio.voices.length) {
      list.innerHTML = '<li class="empty-hint">Nenhuma voz ainda. Clone ou desenhe uma abaixo.</li>';
      return;
    }
    list.innerHTML = studio.voices.map((v) => {
      const meta = [languageLabel(v.language), v.brand, v.engine, v.instruct].filter(Boolean).map(esc).join(" · ");
      const removable = v.removable !== false;
      return `
      <li class="voice-item" data-voice="${esc(v.id)}">
        <div class="voice-item-main">
          <div class="voice-item-name">${esc(v.name)} <span class="voice-badge">${esc(KIND_LABELS[v.kind] || v.kind)}</span></div>
          <div class="voice-item-meta">${meta}</div>
          <div class="voice-item-status" data-voice-status="${esc(v.id)}"></div>
        </div>
        <div class="voice-item-actions">
          <button type="button" class="btn btn-small" data-voice-action="preview" ${studio.previewing.has(v.id) ? "disabled" : ""} title="Ouvir uma amostra desta voz">Ouvir</button>
          <button type="button" class="btn btn-small" data-voice-action="use" title="Usar esta voz no roteiro">Usar</button>
          ${removable ? '<button type="button" class="btn btn-small btn-danger" data-voice-action="remove" title="Remover do catálogo">Remover</button>' : ""}
        </div>
      </li>`;
    }).join("");
  }

  function renderScriptVoiceSelect() {
    const select = el("voice-script-voice");
    const wanted = select.value || rememberedVoice();
    const items = studio.voices.map((v) => ({ value: v.id, label: `${v.name} (${KIND_LABELS[v.kind] || v.kind})` }));
    select.innerHTML = optionsHtml(items, "Voz automática");
    select.value = items.some((o) => o.value === wanted) ? wanted : "";
  }

  function setVoiceStatus(voiceId, text) {
    const target = document.querySelector(`[data-voice-status="${CSS.escape(voiceId)}"]`);
    if (target) target.textContent = text || "";
  }

  async function previewVoice(voiceId) {
    studio.previewing.add(voiceId);
    renderVoices();
    const startedAt = Date.now();
    const status = (extra) => setVoiceStatus(voiceId, `Gerando amostra... ${formatClock(Date.now() - startedAt)}${extra ? " · " + extra : ""}`);
    let label = "";
    const ticker = setInterval(() => status(label), 1000);
    status("");
    try {
      const { job_id } = await api.post(`/api/voices/${encodeURIComponent(voiceId)}/preview`);
      const result = await followJob(job_id, (evt) => { if (evt.label) label = evt.label; });
      const audio = el("voice-preview-audio");
      audio.src = `${result.audio_url}&t=${Date.now()}`;
      await audio.play().catch(() => showAlert("Amostra pronta: use o player para ouvir.", "success"));
    } catch (err) {
      handleError(err);
    } finally {
      clearInterval(ticker);
      studio.previewing.delete(voiceId);
      renderVoices();
    }
  }

  async function removeVoice(voiceId) {
    const voice = studio.voices.find((v) => v.id === voiceId);
    if (!window.confirm(`Remover a voz "${voice ? voice.name : voiceId}"? Isso apaga a gravação de referência dela.`)) return;
    try {
      await api.del(`/api/voices/${encodeURIComponent(voiceId)}`);
      showAlert("Voz removida.", "success");
      await loadVoices();
    } catch (err) {
      handleError(err);
    }
  }

  function useVoice(voiceId) {
    el("voice-script-voice").value = voiceId;
    rememberVoice(voiceId);
    el("voice-script").focus();
  }

  /* ==================== pronúncia ==================== */

  function pronunciationQuery() {
    const brand = el("voice-pron-brand").value;
    return brand ? `?brand=${encodeURIComponent(brand)}` : "";
  }

  async function loadPronunciation() {
    const data = await api.get(`/api/voices/pronunciation${pronunciationQuery()}`);
    studio.pronunciation = data.entries;
    renderPronunciation();
  }

  function renderPronunciation() {
    const list = el("voice-pron-rows");
    if (!studio.pronunciation.length) {
      list.innerHTML = '<li class="empty-hint">Nenhum termo ainda. Adicione abaixo.</li>';
      return;
    }
    const brandName = (key) => {
      const found = studio.brands.find((b) => b.key === key);
      return found ? found.name || found.key : key;
    };
    list.innerHTML = studio.pronunciation.map((entry) => {
      const listening = studio.listening.has(pronunciationKey(entry.term, entry.language));
      const scope = entry.scope === "global" ? "Todas as marcas" : brandName(entry.scope);
      return `
      <li class="voice-item" data-pron-term="${esc(entry.term)}" data-pron-scope="${esc(entry.scope)}" data-pron-language="${esc(entry.language)}">
        <div class="voice-item-main">
          <div class="voice-item-name">${esc(entry.term)} &rarr; ${esc(entry.spoken)}</div>
          <div class="voice-item-meta">Idioma: ${esc(languageLabel(entry.language))} · Vale em: ${esc(scope)}</div>
        </div>
        <div class="voice-item-actions">
          <button type="button" class="btn btn-small" data-pron-action="listen" ${listening ? "disabled" : ""} title="Gera uma frase curta com a voz escolhida em Narração">${listening ? "Gerando..." : "Ouvir"}</button>
          <button type="button" class="btn btn-small btn-danger" data-pron-action="remove">Remover</button>
        </div>
      </li>`;
    }).join("");
  }

  function pronunciationKey(term, language) {
    return `${language}:${term}`;
  }

  function updatePronunciationForm() {
    el("voice-pron-add").disabled = !(el("voice-pron-term").value.trim() && el("voice-pron-spoken").value.trim());
  }

  async function addPronunciation() {
    const body = {
      term: el("voice-pron-term").value.trim(),
      spoken: el("voice-pron-spoken").value.trim(),
      brand: el("voice-pron-brand").value || null,
      language: el("voice-pron-language").value || "pt",
    };
    if (!body.term || !body.spoken) return;
    try {
      const data = await api.post("/api/voices/pronunciation", body);
      studio.pronunciation = data.entries;
      renderPronunciation();
      el("voice-pron-term").value = "";
      el("voice-pron-spoken").value = "";
      updatePronunciationForm();
      showAlert(`Pronúncia de "${body.term}" salva.`, "success");
    } catch (err) {
      handleError(err);
    }
  }

  async function removePronunciation(term, scope, language) {
    if (!window.confirm(`Tirar "${term}" (${languageLabel(language)}) do dicionário?`)) return;
    const params = new URLSearchParams({ term, language });
    if (scope !== "global") params.set("brand", scope);
    try {
      const data = await api.del(`/api/voices/pronunciation?${params}`);
      studio.pronunciation = data.entries;
      renderPronunciation();
    } catch (err) {
      handleError(err);
    }
  }

  /** Gera uma frase curta com o termo, pela mesma rota de síntese da narração, e toca. */
  async function listenPronunciation(term, language) {
    const key = pronunciationKey(term, language);
    studio.listening.add(key);
    renderPronunciation();
    try {
      const { job_id } = await api.post("/api/voices/speak", {
        text: pronunciationPreviewText(term, language),
        voice: el("voice-script-voice").value || null,
        language,
        brand: el("voice-pron-brand").value || null,
        seed: 1,
      });
      const result = await followJob(job_id);
      const audio = el("voice-preview-audio");
      audio.src = `${result.audio_url}&t=${Date.now()}`;
      await audio.play().catch(() => showAlert("Prévia pronta: use o player da lista de vozes para ouvir.", "success"));
    } catch (err) {
      handleError(err);
    } finally {
      studio.listening.delete(key);
      renderPronunciation();
    }
  }

  /* ==================== nova voz: clonar ==================== */

  function selectedReference() {
    if (el("voice-source-mic").checked) {
      return studio.recordedBlob
        ? { blob: studio.recordedBlob, filename: `gravacao.${extensionForMime(studio.recordedBlob.type)}` }
        : null;
    }
    const file = el("voice-clone-file").files[0];
    return file ? { blob: file, filename: file.name } : null;
  }

  function updateCloneState() {
    const micMode = el("voice-source-mic").checked;
    el("voice-clone-file-field").hidden = micMode;
    el("voice-clone-mic").hidden = !micMode;
    const ready = !!selectedReference() && el("voice-clone-name").value.trim() && el("voice-clone-consent").checked;
    el("voice-clone-submit").disabled = !ready || studio.busy;
  }

  function renderRecording(elapsedMs) {
    el("voice-rec-clock").textContent = formatClock(elapsedMs);
    const advice = recordingAdvice(elapsedMs / 1000);
    const hint = el("voice-rec-advice");
    hint.textContent = advice.text;
    hint.dataset.level = advice.level;
  }

  async function startRecording() {
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia || typeof MediaRecorder === "undefined") {
      showAlert("Este navegador não grava pelo microfone. Envie um arquivo de áudio.", "error");
      return;
    }
    try {
      studio.recordingStream = await navigator.mediaDevices.getUserMedia({ audio: true });
    } catch {
      showAlert("Sem acesso ao microfone. Libere a permissão no navegador ou envie um arquivo.", "error");
      return;
    }
    const chunks = [];
    const recorder = new MediaRecorder(studio.recordingStream);
    recorder.ondataavailable = (e) => { if (e.data && e.data.size) chunks.push(e.data); };
    recorder.onstop = () => {
      studio.recordedBlob = new Blob(chunks, { type: recorder.mimeType || "audio/webm" });
      studio.recordingStream.getTracks().forEach((t) => t.stop());
      clearInterval(studio.recordingTicker);
      const playback = el("voice-rec-playback");
      playback.src = URL.createObjectURL(studio.recordedBlob);
      playback.hidden = false;
      el("voice-rec-toggle").textContent = "Gravar de novo";
      updateCloneState();
    };
    studio.recorder = recorder;
    studio.recordedBlob = null;
    el("voice-rec-playback").hidden = true;
    studio.recordingStartedAt = Date.now();
    recorder.start();
    el("voice-rec-toggle").textContent = "Parar gravação";
    el("voice-rec-clock").classList.add("recording");
    renderRecording(0);
    studio.recordingTicker = setInterval(() => {
      const elapsed = Date.now() - studio.recordingStartedAt;
      renderRecording(elapsed);
      if (elapsed >= MAX_RECORDING_S * 1000) stopRecording();
    }, 200);
    updateCloneState();
  }

  function stopRecording() {
    if (studio.recorder && studio.recorder.state === "recording") studio.recorder.stop();
    el("voice-rec-clock").classList.remove("recording");
  }

  function toggleRecording() {
    if (studio.recorder && studio.recorder.state === "recording") stopRecording();
    else startRecording();
  }

  async function submitClone() {
    const reference = selectedReference();
    if (!reference) return;
    const form = new FormData();
    form.append("name", el("voice-clone-name").value.trim());
    form.append("audio", reference.blob, reference.filename);
    form.append("language", el("voice-clone-language").value);
    const referenceText = el("voice-clone-text").value.trim();
    if (referenceText) form.append("reference_text", referenceText);
    if (el("voice-clone-brand").value) form.append("brand", el("voice-clone-brand").value);
    const button = el("voice-clone-submit");
    studio.busy = true;
    updateCloneState();
    button.textContent = referenceText ? "Clonando..." : "Clonando e transcrevendo...";
    try {
      const resp = await fetch("/api/voices/clone", { method: "POST", body: form });
      const text = await resp.text();
      let data = null;
      try { data = JSON.parse(text); } catch { data = text; }
      if (!resp.ok) throw new Error(formatApiError(data));
      showAlert(`Voz "${data.name}" clonada.`, "success");
      el("voice-clone-name").value = "";
      el("voice-clone-text").value = "";
      el("voice-clone-file").value = "";
      el("voice-clone-consent").checked = false;
      studio.recordedBlob = null;
      el("voice-rec-playback").hidden = true;
      await loadVoices();
      useVoice(data.id);
    } catch (err) {
      handleError(err);
    } finally {
      studio.busy = false;
      button.textContent = "Clonar voz";
      updateCloneState();
    }
  }

  /* ==================== nova voz: desenhar ==================== */

  async function submitDesign() {
    const body = {
      name: el("voice-design-name").value.trim(),
      gender: el("voice-design-gender").value || null,
      age: el("voice-design-age").value || null,
      pitch: el("voice-design-pitch").value || null,
      accent: el("voice-design-accent").value || null,
      whisper: el("voice-design-whisper").checked,
      instruct: el("voice-design-instruct").value.trim() || null,
      brand: el("voice-design-brand").value || null,
      language: el("voice-design-language").value,
    };
    if (!body.name) {
      showAlert("Dê um nome para a voz.", "error");
      return;
    }
    const button = el("voice-design-submit");
    button.disabled = true;
    try {
      const voice = await api.post("/api/voices/design", body);
      showAlert(`Voz "${voice.name}" criada.`, "success");
      el("voice-design-name").value = "";
      await loadVoices();
      useVoice(voice.id);
    } catch (err) {
      handleError(err);
    } finally {
      button.disabled = false;
    }
  }

  function showNewVoiceTab(which) {
    document.querySelectorAll("[data-voice-newtab]").forEach((b) => b.classList.toggle("active", b.dataset.voiceNewtab === which));
    el("voice-new-clone").hidden = which !== "clone";
    el("voice-new-design").hidden = which !== "design";
  }

  /* ==================== roteiro e geração ==================== */

  function updateScriptStats() {
    const text = el("voice-script").value;
    const speed = Number(el("voice-speed").value) || 1;
    el("voice-speed-value").textContent = `${speed.toFixed(2)}x`;
    const seconds = estimateSeconds(text, speed);
    el("voice-script-stats").textContent = text.trim()
      ? `${text.length} caracteres · duração estimada ${formatDuration(seconds)} (cerca de ${CHARS_PER_SECOND} caracteres por segundo)`
      : "Escreva ou cole o roteiro da narração.";
    el("voice-generate").disabled = studio.busy || !text.trim();
  }

  function showGenerating(visible) {
    el("voice-progress").hidden = !visible;
    if (!visible) el("voice-progress-fill").style.width = "0%";
    el("voice-stop").disabled = false;
    el("voice-stop").textContent = "Parar";
  }

  /* ---------- prévia ao vivo na tela ---------- */

  function liveAudioContext() {
    const Context = window.AudioContext || window.webkitAudioContext;
    if (!Context) return null;
    if (!studio.audioContext) studio.audioContext = new Context();
    return studio.audioContext;
  }

  async function fetchChunkBytes(url) {
    const response = await fetch(url);
    if (!response.ok) throw new Error("Não consegui carregar uma fala da prévia ao vivo.");
    return response.arrayBuffer();
  }

  /** Começa uma prévia ao vivo nova (chamada dentro do clique, que é o que libera o áudio do navegador).
   * Sem Web Audio no navegador devolve null e a narração segue só com o arquivo final. */
  function startLivePreview() {
    stopLivePreview();
    const context = liveAudioContext();
    if (!context) return null;
    context.resume().catch(() => {});
    const live = {
      player: createLivePlayer(context, fetchChunkBytes, () => showAlert("Uma fala da prévia ao vivo não tocou; o arquivo final não é afetado.", "error")),
      total: 0,
      jobEnded: false,
      stoppedAfter: null,
    };
    studio.live = live;
    el("voice-live").hidden = false;
    drawLivePreview();
    studio.liveTicker = setInterval(drawLivePreview, 150);
    return live;
  }

  function drawLivePreview() {
    const live = studio.live;
    if (!live) return;
    const playing = live.player.playingIndex();
    el("voice-live-status").textContent = liveStatusText({
      total: live.total, ready: live.player.ready(), playing, stoppedAfter: live.stoppedAfter,
    });
    if ((live.jobEnded && playing === null) || live.stoppedAfter !== null) clearInterval(studio.liveTicker);
  }

  function stopLivePreview() {
    clearInterval(studio.liveTicker);
    if (studio.live) studio.live.player.stop();
    studio.live = null;
  }

  /** Silencia só a prévia ao vivo; a geração continua e o arquivo final sai do mesmo jeito. */
  function muteLivePreview() {
    if (!studio.live) return;
    stopLivePreview();
    el("voice-live-status").textContent = "Prévia ao vivo silenciada. A geração continua.";
  }

  function onJobEvent(evt) {
    const live = studio.live;
    if (!live || evt.kind !== "utterance") return;
    live.total = evt.total;
    live.player.enqueue({ index: evt.index, url: evt.audio_url, pauseAfter: evt.pause_after_s });
  }

  async function stopGeneration() {
    if (!studio.jobId || el("voice-stop").disabled) return;
    el("voice-stop").disabled = true;
    el("voice-stop").textContent = "Parando...";
    studio.stopping = true;
    if (studio.live) {
      studio.live.player.stop();
      studio.live.stoppedAfter = studio.live.player.ready();
      drawLivePreview();
    }
    try {
      await api.post(`/api/jobs/${studio.jobId}/cancel`);
    } catch (err) {
      handleError(err);
    }
  }

  async function generate() {
    const text = el("voice-script").value.trim();
    if (!text) return;
    const speed = Number(el("voice-speed").value) || 1;
    const seedRaw = el("voice-seed").value.trim();
    const entry = {
      text,
      voiceId: el("voice-script-voice").value || null,
      speed,
      language: el("voice-language").value || null,
      seed: seedRaw === "" ? null : Number(seedRaw),
    };
    const brand = el("voice-pron-brand").value || null;
    rememberVoice(entry.voiceId);
    studio.busy = true;
    updateScriptStats();
    showGenerating(true);
    let label = "Na fila...";
    let percent = 0;
    const draw = (elapsedMs) => {
      const shown = studio.stopping ? "Parando assim que a fala atual terminar" : label;
      el("voice-progress-label").textContent = `${shown} · ${formatClock(elapsedMs)} decorridos`;
      el("voice-progress-fill").style.width = `${percent}%`;
    };
    studio.stopping = false;
    startElapsedTicker(draw);
    const live = startLivePreview();
    try {
      const { job_id } = await api.post("/api/voices/speak", {
        text: entry.text, voice: entry.voiceId, speed: entry.speed, language: entry.language, seed: entry.seed, brand,
      });
      studio.jobId = job_id;
      const result = await followJob(job_id, (evt) => {
        if (evt.label) { label = evt.label; percent = evt.percent || 0; }
        else if (evt.log) label = evt.log;
      }, onJobEvent);
      if (live) live.jobEnded = true;
      const voice = studio.voices.find((v) => v.id === entry.voiceId);
      addToHistory({
        ...entry,
        voiceName: voice ? voice.name : "Voz automática",
        duration: result.duration_s,
        audioUrl: result.audio_url,
        output: result.output,
        at: new Date(),
      });
      showAlert("Narração pronta.", "success");
    } catch (err) {
      if (live) live.jobEnded = true;
      if (err.cancelled) {
        if (live) live.stoppedAfter = err.result && err.result.ready !== undefined ? err.result.ready : live.player.ready();
        drawLivePreview();
        showAlert("Narração parada. As falas prontas ficaram guardadas: gerar o mesmo texto de novo não as sintetiza outra vez.", "success");
      } else {
        stopLivePreview();
        el("voice-live").hidden = true;
        handleError(err);
      }
    } finally {
      studio.jobId = null;
      stopElapsedTicker();
      studio.busy = false;
      showGenerating(false);
      updateScriptStats();
    }
  }

  /* ==================== resultado e histórico ==================== */

  function addToHistory(item) {
    item.id = `${Date.now()}-${studio.history.length}`;
    studio.history.unshift(item);
    studio.history.length = Math.min(studio.history.length, HISTORY_LIMIT);
    showResult(item);
    renderHistory();
  }

  function showResult(item) {
    studio.current = item;
    const player = el("voice-result-audio");
    player.src = `${item.audioUrl}&t=${item.id}`;
    el("voice-result").hidden = false;
    el("voice-result-meta").textContent = `${item.voiceName} · ${formatDuration(item.duration)} · velocidade ${item.speed.toFixed(2)}x`;
    el("voice-result-download").href = `${item.audioUrl}&download=true`;
  }

  function renderHistory() {
    const list = el("voice-history");
    if (!studio.history.length) {
      list.innerHTML = '<li class="empty-hint">As narrações geradas nesta sessão aparecem aqui.</li>';
      return;
    }
    list.innerHTML = studio.history.map((h) => {
      const excerpt = h.text.length > 70 ? `${h.text.slice(0, 70)}...` : h.text;
      return `
      <li class="voice-history-item" data-history="${esc(h.id)}">
        <div class="voice-history-text">${esc(excerpt)}</div>
        <div class="voice-item-meta">${esc(h.voiceName)} · ${esc(formatDuration(h.duration))} · ${esc(h.at.toLocaleTimeString("pt-BR"))}</div>
        <div class="voice-item-actions">
          <button type="button" class="btn btn-small" data-history-action="play">Ouvir</button>
          <a class="btn btn-small" href="${esc(h.audioUrl)}&download=true">Baixar</a>
          <button type="button" class="btn btn-small" data-history-action="reuse">Reusar texto</button>
          <button type="button" class="btn btn-small" data-history-action="insert">Inserir no projeto</button>
        </div>
      </li>`;
    }).join("");
  }

  /* ==================== inserir no projeto aberto ==================== */

  /** Acrescenta a narração em project.audio.narration e salva pelo fluxo normal de salvar. Se o servidor
   * recusar (por exemplo, o campo ainda não existe na spec), desfaz a inserção e mostra a mensagem dele. */
  async function insertIntoProject(item) {
    if (!state.currentProject || !state.spec) {
      showAlert("Abra um projeto para inserir a narração nele.", "error");
      return;
    }
    const start = window.DMakerEditor && DMakerEditor.getPlayheadTime ? DMakerEditor.getPlayheadTime() : 0;
    const narration = buildNarrationItem(item, start);
    state.spec.audio = state.spec.audio || {};
    const previous = state.spec.audio.narration;
    state.spec.audio.narration = [...(previous || []), narration];
    const saved = await saveProject();
    if (!saved) {
      if (previous) state.spec.audio.narration = previous;
      else delete state.spec.audio.narration;
      return;
    }
    syncJsonFromSpec();
    if (state.activeTab === "editor" && typeof renderEditorForm === "function") renderEditorForm();
    if (window.DMakerEditor) DMakerEditor.refreshView();
    showAlert(`Narração inserida em ${narration.start.toFixed(2)} s do projeto ${state.currentProject}.`, "success");
  }

  /* ==================== ligação com a página ==================== */

  function bindEvents() {
    const root = el("panel-voice");

    root.addEventListener("click", (e) => {
      const voiceAction = e.target.closest("[data-voice-action]");
      if (voiceAction) {
        const voiceId = voiceAction.closest("[data-voice]").dataset.voice;
        const action = voiceAction.dataset.voiceAction;
        if (action === "preview") previewVoice(voiceId);
        else if (action === "use") useVoice(voiceId);
        else if (action === "remove") removeVoice(voiceId);
        return;
      }
      const historyAction = e.target.closest("[data-history-action]");
      if (historyAction) {
        const item = studio.history.find((h) => h.id === historyAction.closest("[data-history]").dataset.history);
        if (!item) return;
        const action = historyAction.dataset.historyAction;
        if (action === "play") { showResult(item); el("voice-result-audio").play().catch(() => {}); }
        else if (action === "reuse") { el("voice-script").value = item.text; updateScriptStats(); el("voice-script").focus(); }
        else if (action === "insert") insertIntoProject(item);
        return;
      }
      const pronAction = e.target.closest("[data-pron-action]");
      if (pronAction) {
        const row = pronAction.closest("[data-pron-term]");
        const { pronTerm, pronScope, pronLanguage } = row.dataset;
        if (pronAction.dataset.pronAction === "listen") listenPronunciation(pronTerm, pronLanguage);
        else removePronunciation(pronTerm, pronScope, pronLanguage);
        return;
      }
      const newTab = e.target.closest("[data-voice-newtab]");
      if (newTab) showNewVoiceTab(newTab.dataset.voiceNewtab);
    });

    el("voice-pron-brand").addEventListener("change", () => loadPronunciation().catch(handleError));
    el("voice-pron-add").addEventListener("click", addPronunciation);
    ["voice-pron-term", "voice-pron-spoken"].forEach((id) => {
      el(id).addEventListener("input", updatePronunciationForm);
      el(id).addEventListener("keydown", (e) => { if (e.key === "Enter") addPronunciation(); });
    });

    el("voice-brand-filter").addEventListener("change", (e) => {
      studio.brandFilter = e.target.value;
      loadVoices().catch(handleError);
    });
    el("voice-script").addEventListener("input", updateScriptStats);
    el("voice-speed").addEventListener("input", updateScriptStats);
    el("voice-script-voice").addEventListener("change", (e) => rememberVoice(e.target.value));
    el("voice-generate").addEventListener("click", generate);
    el("voice-stop").addEventListener("click", stopGeneration);
    el("voice-live-mute").addEventListener("click", muteLivePreview);
    el("voice-result-insert").addEventListener("click", () => { if (studio.current) insertIntoProject(studio.current); });
    el("voice-rec-toggle").addEventListener("click", toggleRecording);
    el("voice-clone-submit").addEventListener("click", submitClone);
    el("voice-design-submit").addEventListener("click", submitDesign);
    ["voice-source-file", "voice-source-mic"].forEach((id) => el(id).addEventListener("change", updateCloneState));
    ["voice-clone-file", "voice-clone-consent"].forEach((id) => el(id).addEventListener("change", updateCloneState));
    el("voice-clone-name").addEventListener("input", updateCloneState);
  }

  function fillStaticSelects() {
    const languages = studio.options.languages;
    const brands = studio.brands.map((b) => ({ value: b.key, label: b.name || b.key }));
    el("voice-clone-language").innerHTML = optionsHtml(languages);
    el("voice-design-language").innerHTML = optionsHtml(languages);
    el("voice-language").innerHTML = optionsHtml(languages, "Idioma da voz (padrão)");
    el("voice-clone-brand").innerHTML = optionsHtml(brands, "Sem marca (serve para qualquer uma)");
    el("voice-design-brand").innerHTML = optionsHtml(brands, "Sem marca (serve para qualquer uma)");
    el("voice-brand-filter").innerHTML = optionsHtml(brands, "Todas as vozes");
    el("voice-pron-brand").innerHTML = optionsHtml(brands, "Global (todas as marcas)");
    el("voice-pron-language").innerHTML = optionsHtml(languages);
    el("voice-design-gender").innerHTML = optionsHtml(studio.options.gender, "Não definir");
    el("voice-design-age").innerHTML = optionsHtml(studio.options.age, "Não definir");
    el("voice-design-pitch").innerHTML = optionsHtml(studio.options.pitch, "Não definir");
    el("voice-design-accent").innerHTML = optionsHtml(studio.options.accent, "Não definir");
  }

  async function init(config) {
    if (studio.ready || !el("panel-voice")) return;
    studio.brands = (config && config.brands) || [];
    try {
      studio.options = await api.get("/api/voices/design-options");
    } catch (err) {
      handleError(err);
      return;
    }
    studio.ready = true;
    fillStaticSelects();
    bindEvents();
    showNewVoiceTab("clone");
    renderHistory();
    updateScriptStats();
    updateCloneState();
    loadVoices().catch(handleError);
    loadPronunciation().catch(handleError);
  }

  function onShow() {
    if (!studio.ready) return;
    loadVoices().catch(handleError);
    loadPronunciation().catch(handleError);
  }

  window.DMakerVoice = {
    init,
    onShow,
    followJob, // speech.js acompanha seus próprios jobs com o mesmo SSE
    pure: {
      esc,
      estimateSeconds,
      spokenForm,
      pronunciationPreviewText,
      formatDuration,
      formatClock,
      recordingAdvice,
      extensionForMime,
      buildNarrationItem,
      jobErrorMessage,
      planLiveChunk,
      playingIndexAt,
      liveStatusText,
      createLivePlayer,
    },
  };
})();
