"use strict";
/*
 * DMaker - aba "Modelos": o que está baixado em cache/models, quanto ocupa, para que serve e de que licença,
 * com botões para baixar, apagar e limpar as sobras (arquivos que nenhum modelo usa).
 *
 * O servidor mede o disco e monta o aviso de cada exclusão; aqui só se desenha e se pede confirmação antes de
 * apagar. Baixar é um job (POST devolve job_id), acompanhado pelo SSE do voice.js (DMakerVoice.followJob).
 * Usa em tempo de execução, vindos de app.js: api, showAlert, handleError, openModal, closeModal.
 * O que é puro fica em window.DMakerModels.pure.
 *
 * window.DMakerModels:
 *   init()    chamado por app.js ao terminar de carregar o estado
 *   onShow()  chamado por app.js quando a aba Modelos aparece (mede o disco de novo)
 *   pure      formatBytes, stateLabel, modelRowHtml, leftoverItemsHtml, summaryText
 */
(function () {
  const STATE_LABELS = { installed: "baixado", partial: "incompleto", absent: "não baixado" };

  /* ==================== funções puras ==================== */

  function esc(value) {
    return String(value ?? "").replace(/[&<>"']/g, (c) => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
    }[c]));
  }

  /** Tamanho como o Explorador do Windows mostra (base 1024, vírgula decimal): "3,04 GB", "80,1 MB". */
  function formatBytes(bytes) {
    let value = Math.max(Number(bytes) || 0, 0);
    const units = [["B", 0], ["KB", 0], ["MB", 1], ["GB", 2]];
    for (let index = 0; index < units.length; index += 1) {
      const [unit, decimals] = units[index];
      if (value < 1024 || index === units.length - 1) return `${value.toFixed(decimals).replace(".", ",")} ${unit}`;
      value /= 1024;
    }
    return "";
  }

  function stateLabel(state) {
    return STATE_LABELS[state] || state;
  }

  function percentOf(done, total) {
    return total > 0 ? Math.min(100, Math.round((100 * done) / total)) : 0;
  }

  /** Linha da tabela de um modelo; `download` ({percent, label}) existe enquanto ele está sendo baixado. */
  function modelRowHtml(model, download) {
    const busy = !!download;
    let sizeCell = esc(model.size_label);
    if (model.state === "absent") {
      sizeCell = `<span class="voice-item-meta">ocupa ~${esc(model.expected_label)} ao baixar</span>`;
    } else if (model.state === "partial") {
      sizeCell = `${esc(model.size_label)}<span class="voice-item-meta">de ~${esc(model.expected_label)}</span>`;
    }
    const usedBy = (model.required_by || []).length
      ? `<div class="voice-item-meta">Usado por: ${model.required_by.map(esc).join("; ")}</div>`
      : "";
    const fetchLabel = model.state === "partial" ? "Continuar download" : `Baixar (${model.expected_label})`;
    const buttons = [];
    if (model.state !== "installed") {
      buttons.push(`<button type="button" class="btn btn-small btn-accent" data-models-action="download" data-model="${esc(model.id)}"${busy ? " disabled" : ""}>${esc(fetchLabel)}</button>`);
    }
    if (model.state !== "absent") {
      buttons.push(`<button type="button" class="btn btn-small btn-danger" data-models-action="remove" data-model="${esc(model.id)}"${busy ? " disabled" : ""}>Apagar</button>`);
    }
    const progress = busy
      ? `<div class="models-progress"><div class="progress-bar-track"><div class="progress-bar-fill" style="width:${download.percent}%"></div></div><div class="progress-bar-label">${esc(download.label)}</div></div>`
      : "";
    return `
      <tr data-model-row="${esc(model.id)}">
        <td><div class="models-name">${esc(model.name)}</div><div class="voice-item-meta">${esc(model.purpose)}</div>${usedBy}</td>
        <td><span class="models-state" data-state="${esc(model.state)}">${esc(stateLabel(model.state))}</span></td>
        <td class="models-size">${sizeCell}</td>
        <td>${esc(model.license)}</td>
        <td class="models-actions">${buttons.join("")}${progress}</td>
      </tr>`;
  }

  /** Lista das sobras, uma por linha, com o tamanho de cada. */
  function leftoverItemsHtml(leftovers) {
    return (leftovers || [])
      .map((item) => `<li class="voice-item-meta">${esc(item.path)}${item.is_dir ? "/" : ""}: ${esc(item.size_label)}</li>`)
      .join("");
  }

  function summaryText(inventory) {
    const parts = [`Ocupado em cache/models: ${inventory.total_label}`];
    if (inventory.disk_free_label) parts.push(`Livre no disco: ${inventory.disk_free_label}`);
    if (inventory.leftovers.length) parts.push(`Sobras: ${inventory.leftover_label}`);
    return parts.join(" · ");
  }

  /* ==================== estado e tela ==================== */

  const view = { inventory: null, downloads: {}, ready: false };
  const el = (id) => document.getElementById(id);

  function render() {
    const inventory = view.inventory;
    if (!inventory) return;
    el("models-summary").textContent = summaryText(inventory);
    el("models-dir").textContent = inventory.models_dir;
    el("models-rows").innerHTML = inventory.models.map((m) => modelRowHtml(m, view.downloads[m.id])).join("");
    const hasLeftovers = inventory.leftovers.length > 0;
    el("models-leftovers-block").hidden = !hasLeftovers;
    el("models-leftovers").innerHTML = leftoverItemsHtml(inventory.leftovers);
    el("models-leftovers-total").textContent = `${inventory.leftovers.length} item(ns), ${inventory.leftover_label}`;
  }

  async function load() {
    try {
      view.inventory = await api.get("/api/models");
      render();
    } catch (err) {
      handleError(err);
    }
  }

  /* ==================== baixar ==================== */

  async function download(modelId) {
    view.downloads[modelId] = { percent: 0, label: "Na fila..." };
    render();
    try {
      const { job_id } = await api.post(`/api/models/${encodeURIComponent(modelId)}/download`);
      await DMakerVoice.followJob(job_id, (evt) => {
        if (evt.label) view.downloads[modelId] = { percent: evt.percent || 0, label: evt.label };
        else if (evt.log) view.downloads[modelId] = { ...view.downloads[modelId], label: evt.log };
        render();
      });
      showAlert("Modelo baixado.", "success");
    } catch (err) {
      handleError(err);
    } finally {
      delete view.downloads[modelId];
      await load();
    }
  }

  /* ==================== apagar ==================== */

  function confirmModal({ title, warning, pathsHtml, confirmId, onConfirm }) {
    openModal(`
      <h3>${esc(title)}</h3>
      <p>${esc(warning)}</p>
      <ul class="models-paths">${pathsHtml}</ul>
      <div class="modal-actions">
        <button type="button" class="btn" id="models-cancel">Cancelar</button>
        <button type="button" class="btn btn-danger" id="${confirmId}">Apagar</button>
      </div>`);
    el("models-cancel").addEventListener("click", closeModal);
    el(confirmId).addEventListener("click", async () => {
      el(confirmId).disabled = true;
      try {
        await onConfirm();
      } catch (err) {
        handleError(err);
      } finally {
        closeModal();
        await load();
      }
    });
  }

  async function removeModel(modelId) {
    try {
      const plan = await api.get(`/api/models/${encodeURIComponent(modelId)}/removal`);
      confirmModal({
        title: "Apagar modelo",
        warning: plan.warning,
        pathsHtml: plan.paths.map((path) => `<li class="voice-item-meta">${esc(path)}</li>`).join(""),
        confirmId: "models-remove-confirm",
        onConfirm: async () => {
          await api.post(`/api/models/${encodeURIComponent(modelId)}/remove`, { confirm: true });
          showAlert("Modelo apagado.", "success");
        },
      });
    } catch (err) {
      handleError(err);
    }
  }

  function pruneLeftovers() {
    const leftovers = view.inventory ? view.inventory.leftovers : [];
    if (!leftovers.length) return;
    confirmModal({
      title: "Apagar sobras",
      warning: `Vai apagar ${leftovers.length} item(ns) que nenhum modelo do DMaker usa e liberar ${view.inventory.leftover_label}. Confira a lista: se algum é de um modelo seu, cancele.`,
      pathsHtml: leftoverItemsHtml(leftovers),
      confirmId: "models-prune-confirm",
      onConfirm: async () => {
        await api.post("/api/models/prune", { confirm: true, paths: leftovers.map((item) => item.path) });
        showAlert("Sobras apagadas.", "success");
      },
    });
  }

  /* ==================== ligação com a página ==================== */

  function init() {
    if (view.ready || !el("panel-models")) return;
    view.ready = true;
    el("models-rows").addEventListener("click", (event) => {
      const button = event.target.closest("[data-models-action]");
      if (!button || button.disabled) return;
      const modelId = button.dataset.model;
      if (button.dataset.modelsAction === "download") download(modelId);
      else if (button.dataset.modelsAction === "remove") removeModel(modelId);
    });
    el("models-refresh").addEventListener("click", load);
    el("models-prune").addEventListener("click", pruneLeftovers);
  }

  function onShow() {
    init();
    load();
  }

  window.DMakerModels = {
    init,
    onShow,
    pure: { formatBytes, stateLabel, percentOf, modelRowHtml, leftoverItemsHtml, summaryText },
  };
})();
