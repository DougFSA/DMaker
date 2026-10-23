"use strict";
/*
 * DMaker - fila de narrações na aba "Voz": roteiros longos (audiobook, manual narrado) e vários de uma vez.
 *
 * A fila roda no servidor, um item por vez e sozinha, e retoma de onde parou. Esta tela só mostra o estado
 * (chega por SSE em /api/voices/queue/events, uma foto da fila inteira a cada mudança) e manda os comandos:
 * pausar, retomar, cancelar, subir, descer, tentar de novo e remover. Os itens entram pelo botão "Mandar para a
 * fila" da caixa de roteiro (usa a voz, o idioma e a velocidade escolhidos em Narração) ou por upload de .txt,
 * .md ou .docx, que o servidor divide em capítulos.
 *
 * Usa em tempo de execução, vindos de app.js: api, showAlert, handleError, formatApiError. O que é puro fica
 * em window.DMakerQueue.pure.
 *
 * window.DMakerQueue:
 *   init()     chamado por app.js ao terminar de carregar o estado
 *   onShow()   chamado por app.js quando a aba Voz aparece (abre o acompanhamento)
 *   onHide()   chamado por app.js ao sair da aba (fecha o acompanhamento)
 *   pure       actionsFor, describeProgress, fileLinks, queueSummary, textBody
 */
(function () {
  const ACTIONS_BY_STATE = {
    pending: ["pause", "cancel", "up", "down"],
    running: ["pause", "cancel"],
    paused: ["resume", "cancel", "up", "down"],
    failed: ["retry", "remove"],
    cancelled: ["retry", "remove"],
    done: ["remove"],
  };
  const ACTION_LABELS = {
    pause: "Pausar",
    resume: "Retomar",
    cancel: "Cancelar",
    up: "Subir",
    down: "Descer",
    retry: "Tentar de novo",
    remove: "Remover",
  };
  const ACTION_TITLES = {
    pause: "Para na próxima fala e guarda o que já foi narrado",
    resume: "Volta para a fila, na mesma posição",
    cancel: "Desiste do item; o que já foi narrado fica guardado",
    up: "Roda antes do item de cima",
    down: "Roda depois do item de baixo",
    retry: "Refaz o item; as falas que já saíram vêm do cache",
    remove: "Tira o item da lista (os áudios continuam na pasta)",
  };
  const SOURCE_LABELS = { text: "texto", file: "arquivo" };

  /* ==================== funções puras ==================== */

  function esc(value) {
    return String(value ?? "").replace(/[&<>"']/g, (c) => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
    }[c]));
  }

  /** Botões que fazem sentido em cada estado, na ordem em que aparecem. */
  function actionsFor(state) {
    return ACTIONS_BY_STATE[state] || [];
  }

  /** "2 h 05 min", "12 min" ou "40 s" (o mesmo formato do servidor, para os números baterem). */
  function formatSeconds(seconds) {
    const total = Math.round(seconds);
    const hours = Math.floor(total / 3600);
    const minutes = Math.floor((total % 3600) / 60);
    if (hours) return `${hours} h ${String(minutes).padStart(2, "0")} min`;
    if (minutes) return `${minutes} min`;
    return `${total % 60} s`;
  }

  /** Primeira linha de um erro de job, sem o nome da exceção. */
  function firstLine(text) {
    return String(text || "").split("\n")[0].replace(/^\w+(Error|Exception):\s*/, "");
  }

  /** O que o item está fazendo, numa linha: capítulo e fala em andamento, quanto falta ou o desfecho. */
  function describeProgress(item) {
    const chapters = `${item.chapters_total} ${item.chapters_total === 1 ? "capítulo" : "capítulos"}`;
    const left = item.eta_label ? ` · faltam cerca de ${item.eta_label}` : "";
    if (item.state === "running") {
      if (!item.chapter) return `Preparando o roteiro${left}`;
      const where = item.chapters_total > 1 ? `capítulo ${item.chapter} de ${item.chapters_total}, ` : "";
      return `${where}fala ${item.utterance} de ${item.utterances}${left}`;
    }
    if (item.state === "pending") return `Aguardando a vez · ${chapters}${left}`;
    if (item.state === "paused") return `Pausado em ${item.percent}% · ${chapters}`;
    if (item.state === "done") return `Pronto · ${chapters}${item.duration_s ? ` · ${formatSeconds(item.duration_s)} de áudio` : ""}`;
    if (item.state === "cancelled") return `Cancelado em ${item.percent}%`;
    if (item.state === "failed") return firstLine(item.error) || "Falhou";
    return chapters;
  }

  /** Arquivos prontos num bloco que abre e fecha (um audiobook tem dezenas): ouvir (áudio) e baixar; a legenda só baixa. */
  function fileLinks(files) {
    if (!files || !files.length) return "";
    const rows = files.map((file) => {
      const listen = file.audio ? `<a class="btn btn-small" href="${esc(file.url)}" target="_blank" rel="noopener">Ouvir</a>` : "";
      const download = `<a class="btn btn-small" href="${esc(file.url)}${file.url.includes("?") ? "&" : "?"}download=true">Baixar</a>`;
      return `<div class="queue-file"><span class="queue-file-name">${esc(file.name)}</span>${listen}${download}</div>`;
    }).join("");
    return `<details class="queue-files"><summary>Arquivos prontos (${files.length})</summary>${rows}</details>`;
  }

  /** Linha de resumo no topo da lista. */
  function queueSummary(view) {
    const items = view.items || [];
    if (!items.length) return "A fila está vazia.";
    const waiting = items.filter((i) => i.state === "pending" || i.state === "running").length;
    const parts = [`${items.length} ${items.length === 1 ? "item" : "itens"}`];
    if (waiting && view.eta_label) parts.push(`tempo estimado para esvaziar: ${view.eta_label}`);
    if (waiting && !view.running && !view.worker) parts.push("nenhum executor ativo: abra pelo dmaker ui ou rode dmaker voice queue run");
    return parts.join(" · ");
  }

  /** Corpo do POST que manda o texto da caixa de roteiro para a fila. */
  function textBody(fields) {
    const body = {
      text: fields.text,
      voice: fields.voice || null,
      language: fields.language || null,
      speed: fields.speed,
      brand: fields.brand || null,
      draft: !!fields.draft,
      format: fields.format || "wav",
    };
    if (fields.title && fields.title.trim()) body.title = fields.title.trim();
    return body;
  }

  /* ==================== estado ==================== */

  const queue = { ready: false, source: null, rendered: new Map(), view: { items: [] } };

  const el = (id) => document.getElementById(id);

  /* ==================== desenho da lista ==================== */

  function itemHtml(item) {
    const meta = [SOURCE_LABELS[item.source.kind] || item.source.kind, item.source.name, item.options.draft ? "rascunho" : null, item.options.format]
      .filter(Boolean).map(esc).join(" · ");
    const buttons = actionsFor(item.state).map((action) => {
      const danger = action === "cancel" || action === "remove" ? " btn-danger" : "";
      return `<button type="button" class="btn btn-small${danger}" data-queue-action="${action}" title="${esc(ACTION_TITLES[action])}">${ACTION_LABELS[action]}</button>`;
    }).join("");
    const bar = item.state === "running" || item.state === "paused" || item.state === "pending"
      ? `<div class="progress-bar-track"><div class="progress-bar-fill" style="width:${item.percent}%"></div></div>`
      : "";
    const chapter = item.state === "running" && item.chapter_title
      ? `<div class="voice-item-meta">${esc(item.chapter_title)}</div>` : "";
    const note = item.note ? `<div class="voice-item-meta">${esc(item.note)}</div>` : "";
    const folder = item.state === "done" ? `<div class="voice-item-meta">Pasta: ${esc(item.output_dir)}</div>` : "";
    return `
      <li class="voice-item queue-item" data-queue-id="${esc(item.id)}" data-state="${esc(item.state)}">
        <div class="voice-item-main">
          <div class="voice-item-name">${esc(item.title)} <span class="voice-badge queue-state-${esc(item.state)}">${esc(item.state_label)}</span></div>
          <div class="voice-item-meta">${meta}</div>
          ${bar}
          <div class="voice-item-meta queue-progress">${esc(describeProgress(item))}</div>
          ${chapter}${note}
        </div>
        ${folder}
        <div class="voice-item-actions">${buttons}</div>
        ${fileLinks(item.files)}
      </li>`;
  }

  /** Põe o item na lista só se mudou: quem está com os arquivos abertos ou ouvindo não perde o lugar
   * quando outro item avança. */
  function placeItem(list, item, index) {
    const html = itemHtml(item).trim();
    let node = list.querySelector(`[data-queue-id="${CSS.escape(item.id)}"]`);
    if (!node || queue.rendered.get(item.id) !== html) {
      const fresh = document.createElement("template");
      fresh.innerHTML = html;
      const replacement = fresh.content.firstElementChild;
      const opened = node && node.querySelector("details.queue-files[open]");
      if (opened) replacement.querySelector("details.queue-files")?.setAttribute("open", "");
      if (node) node.replaceWith(replacement);
      node = replacement;
      queue.rendered.set(item.id, html);
    }
    if (list.children[index] !== node) list.insertBefore(node, list.children[index] || null);
  }

  function render(view) {
    queue.view = view;
    const list = el("voice-queue-list");
    if (!view.items.length) {
      list.innerHTML = '<li class="empty-hint">Nada na fila. Mande um roteiro pelo botão "Mandar para a fila".</li>';
      queue.rendered.clear();
    } else {
      list.querySelectorAll(".empty-hint").forEach((node) => node.remove());
      const ids = new Set(view.items.map((item) => item.id));
      list.querySelectorAll("[data-queue-id]").forEach((node) => {
        if (!ids.has(node.dataset.queueId)) { queue.rendered.delete(node.dataset.queueId); node.remove(); }
      });
      view.items.forEach((item, index) => placeItem(list, item, index));
    }
    el("voice-queue-summary").textContent = queueSummary(view);
    el("voice-queue-clear").disabled = !view.items.some((i) => i.state === "done" || i.state === "cancelled");
  }

  /* ==================== acompanhamento ==================== */

  function open() {
    if (queue.source) return;
    const source = new EventSource("/api/voices/queue/events");
    source.onmessage = (message) => {
      try { render(JSON.parse(message.data)); } catch (err) { console.error(err); }
    };
    queue.source = source; // o EventSource reconecta sozinho se a conexão cair
  }

  function close() {
    if (queue.source) queue.source.close();
    queue.source = null;
  }

  async function refresh() {
    render(await api.get("/api/voices/queue"));
  }

  /* ==================== comandos ==================== */

  async function runAction(itemId, action) {
    try {
      if (action === "remove") render(await api.del(`/api/voices/queue/${encodeURIComponent(itemId)}`));
      else if (action === "up" || action === "down") {
        render(await api.post(`/api/voices/queue/${encodeURIComponent(itemId)}/move`, { direction: action === "up" ? -1 : 1 }));
      } else render(await api.post(`/api/voices/queue/${encodeURIComponent(itemId)}/${action}`));
    } catch (err) {
      handleError(err);
    }
  }

  /** Voz, idioma, velocidade e marca da seção Narração, que a fila reaproveita. */
  function narrationChoices() {
    return {
      voice: el("voice-script-voice").value,
      language: el("voice-language").value,
      speed: Number(el("voice-speed").value) || 1,
      brand: el("voice-pron-brand").value,
      draft: el("voice-queue-draft").checked,
      format: el("voice-queue-format").value,
      title: el("voice-queue-title").value,
    };
  }

  async function enqueueText() {
    const text = el("voice-script").value.trim();
    if (!text) return;
    try {
      render(await api.post("/api/voices/queue", textBody({ ...narrationChoices(), text })));
      showAlert("Roteiro na fila.", "success");
    } catch (err) {
      handleError(err);
    }
  }

  async function enqueueFile() {
    const file = el("voice-queue-file").files[0];
    if (!file) return;
    const choices = narrationChoices();
    const form = new FormData();
    form.append("file", file, file.name);
    if (choices.title.trim()) form.append("title", choices.title.trim());
    if (choices.voice) form.append("voice", choices.voice);
    if (choices.language) form.append("language", choices.language);
    if (choices.brand) form.append("brand", choices.brand);
    form.append("speed", String(choices.speed));
    form.append("draft", choices.draft ? "true" : "false");
    form.append("format", choices.format);
    el("voice-queue-upload").disabled = true;
    try {
      const response = await fetch("/api/voices/queue/upload", { method: "POST", body: form });
      const text = await response.text();
      let data = null;
      try { data = JSON.parse(text); } catch { data = text; }
      if (!response.ok) throw new Error(formatApiError(data));
      render(data);
      el("voice-queue-file").value = "";
      showAlert("Roteiro na fila.", "success");
    } catch (err) {
      handleError(err);
    } finally {
      updateButtons();
    }
  }

  async function clearFinished() {
    try {
      render(await api.post("/api/voices/queue/clear-finished"));
    } catch (err) {
      handleError(err);
    }
  }

  function updateButtons() {
    el("voice-queue-upload").disabled = !el("voice-queue-file").files.length;
    el("voice-enqueue").disabled = !el("voice-script").value.trim();
  }

  /* ==================== ligação com a página ==================== */

  function bindEvents() {
    el("voice-queue-list").addEventListener("click", (e) => {
      const button = e.target.closest("[data-queue-action]");
      if (!button) return;
      runAction(button.closest("[data-queue-id]").dataset.queueId, button.dataset.queueAction);
    });
    el("voice-enqueue").addEventListener("click", enqueueText);
    el("voice-queue-upload").addEventListener("click", enqueueFile);
    el("voice-queue-clear").addEventListener("click", clearFinished);
    el("voice-queue-file").addEventListener("change", updateButtons);
    el("voice-script").addEventListener("input", updateButtons);
  }

  function init() {
    if (queue.ready || !el("voice-queue-block")) return;
    queue.ready = true;
    bindEvents();
    updateButtons();
    refresh().catch(handleError);
  }

  function onShow() {
    if (!queue.ready) return;
    refresh().catch(handleError);
    open();
  }

  function onHide() {
    close();
  }

  window.DMakerQueue = {
    init,
    onShow,
    onHide,
    pure: { actionsFor, describeProgress, fileLinks, queueSummary, textBody, formatSeconds },
  };
})();
