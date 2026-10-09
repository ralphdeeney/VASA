"use strict";

const elements = Object.fromEntries([
  "account-email", "logout", "page-status", "page-error", "empty-state", "instance-list",
  "create-form", "instance-name", "create-submit", "selected-name", "connection-badge",
  "connection-message", "connection-controls", "connect", "disconnect", "refresh",
  "qr-panel", "qr-image", "connection-status", "connection-error",
].map((id) => [id, document.getElementById(id)]));

let csrfToken = "";
let instances = [];
let selectedId = null;
let pairingRequested = false;
let pollTimer = null;
let activeRequest = null;
let busy = false;
let connected = false;
let loaded = false;

class ApiError extends Error {
  constructor(httpStatus, code) {
    super("Request failed");
    this.httpStatus = httpStatus;
    this.code = code;
  }
}

async function api(path, options = {}) {
  const method = options.method || "GET";
  const headers = { ...options.headers };
  if (typeof options.body === "string") headers["Content-Type"] = "application/json";
  if (method !== "GET") headers["x-csrf-token"] = csrfToken;
  const response = await fetch(path, {
    ...options,
    method,
    headers,
    credentials: "same-origin",
    cache: "no-store",
    signal: options.signal || AbortSignal.timeout(15000),
  });
  let data = null;
  try { data = await response.json(); } catch { /* Use a safe generic error below. */ }
  if (!response.ok) {
    if (response.status === 401) window.location.assign("/login");
    const code = typeof data?.detail === "string" ? data.detail : data?.detail?.code;
    throw new ApiError(response.status, code);
  }
  return data;
}

function messageFor(error) {
  if (error instanceof ApiError) {
    if (error.httpStatus === 401) return "Your session has expired. Sign in again.";
    if (error.httpStatus === 403) return "This action could not be verified. Reload this page and try again.";
    if (error.httpStatus === 404) return "This account is no longer available. Reload your workspace.";
    if (error.httpStatus === 429) return "Too many requests. Wait a moment and try again.";
    if (error.code === "license_required") {
      return "WhatsApp activation is pending. Ask your administrator to activate the connection service, then retry.";
    }
    if (error.code === "not_configured") {
      return "WhatsApp setup is pending. Ask your administrator to complete setup, then retry.";
    }
    if (error.code === "unavailable" || error.httpStatus === 503) {
      return "WhatsApp connection is unavailable. Ask your administrator to check connection setup, then retry.";
    }
    if (error.httpStatus === 422) return "Check the account name and try again.";
    if (error.httpStatus === 409) return "An account with these details already exists. Choose another name.";
  }
  return "Could not reach VASA. Check your connection and try again.";
}

function showError(target, error, focus = false) {
  target.textContent = messageFor(error);
  target.hidden = false;
  if (focus) target.focus();
}

function hideQR() {
  elements["qr-panel"].hidden = true;
  elements["qr-image"].hidden = true;
  elements["qr-image"].removeAttribute("src");
}

function qrSource(value) {
  if (typeof value !== "string" || value.length > 1000000) return null;
  const prefix = "data:image/png;base64,";
  const raw = value.startsWith(prefix) ? value.slice(prefix.length) : value;
  if (!raw || raw.length % 4 !== 0 || !/^[A-Za-z0-9+/]+={0,2}$/.test(raw)) return null;
  try {
    const decoded = atob(raw);
    if (!decoded.startsWith("\x89PNG\r\n\x1a\n")) return null;
  } catch { return null; }
  return prefix + raw;
}

function renderList() {
  elements["instance-list"].replaceChildren();
  elements["empty-state"].hidden = instances.length !== 0;
  for (const instance of instances) {
    const item = document.createElement("li");
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = instance.name;
    if (instance.id === selectedId) button.setAttribute("aria-current", "true");
    button.addEventListener("click", () => selectInstance(instance));
    item.append(button);
    elements["instance-list"].append(item);
  }
}

function setBusy(value) {
  busy = value;
  elements.connect.disabled = !selectedId || value || connected;
  elements.disconnect.disabled = !selectedId || value;
  elements.refresh.disabled = !selectedId || value;
  elements["create-submit"].disabled = !loaded || value;
  elements["instance-name"].disabled = !loaded || value;
}

function cancelPolling() {
  if (pollTimer !== null) clearTimeout(pollTimer);
  pollTimer = null;
  if (activeRequest !== null) activeRequest.abort();
  activeRequest = null;
}

function schedulePoll(id) {
  if (id !== selectedId || document.hidden) return;
  if (pollTimer !== null) clearTimeout(pollTimer);
  pollTimer = setTimeout(() => syncConnection(id), 5000);
}

async function syncConnection(id) {
  if (id !== selectedId) return;
  if (activeRequest !== null) activeRequest.abort();
  const controller = new AbortController();
  activeRequest = controller;
  const timeout = setTimeout(() => controller.abort(), 12000);
  let retry = true;
  try {
    const connection = await api(`/api/whatsapp/instances/${encodeURIComponent(id)}/status`, {
      signal: controller.signal,
    });
    if (id !== selectedId) return;
    connected = connection.connected === true && connection.logged_in === true;
    elements["connection-error"].hidden = true;
    elements["connection-badge"].classList.toggle("connected", connected);
    elements["connection-badge"].textContent = connected ? "Connected" : "Disconnected";
    elements["connection-message"].textContent = connected
      ? "Your WhatsApp account is connected."
      : connection.logged_in === true
        ? "Your account is linked. Connect WhatsApp to restore its connection."
        : "Connect WhatsApp to generate a QR code, then scan it with your phone.";
    if (connected) {
      pairingRequested = false;
      hideQR();
      elements["connection-status"].textContent = "Connection confirmed. Status updates automatically.";
    } else if (pairingRequested && connection.logged_in !== true) {
      elements["connection-badge"].textContent = "Pairing pending";
      const qr = await api(`/api/whatsapp/instances/${encodeURIComponent(id)}/qr`, {
        signal: controller.signal,
      });
      if (id !== selectedId) return;
      const source = qrSource(qr.qrcode);
      if (source !== null) {
        elements["qr-image"].src = source;
        elements["qr-image"].hidden = false;
        elements["qr-panel"].hidden = false;
        elements["connection-status"].textContent = "Pairing required. Scan the QR code to continue.";
      } else {
        hideQR();
        elements["connection-status"].textContent = "Pairing pending. Waiting for a QR code. You can refresh the status.";
      }
    } else {
      hideQR();
      elements["connection-status"].textContent = pairingRequested
        ? "Waiting for the account to connect…" : "Status updates automatically.";
    }
  } catch (error) {
    if (id !== selectedId || (controller.signal.aborted && activeRequest !== controller)) return;
    hideQR();
    elements["connection-badge"].classList.remove("connected");
    elements["connection-badge"].textContent = "Status unavailable";
    elements["connection-status"].textContent = "Use Refresh status to try again.";
    showError(elements["connection-error"], error);
    // Stop unattended retries on failure; a user action or tab return can retry.
    retry = false;
  } finally {
    clearTimeout(timeout);
    const ownsRequest = activeRequest === controller;
    if (ownsRequest) activeRequest = null;
    if (id === selectedId && ownsRequest) {
      setBusy(busy);
      if (retry && !controller.signal.aborted) schedulePoll(id);
    }
  }
}

function selectInstance(instance) {
  cancelPolling();
  selectedId = instance.id;
  pairingRequested = false;
  connected = false;
  hideQR();
  elements["selected-name"].textContent = instance.name;
  elements["connection-badge"].textContent = "Checking status";
  elements["connection-badge"].classList.remove("connected");
  elements["connection-message"].textContent = "Checking your WhatsApp connection…";
  elements["connection-error"].hidden = true;
  elements["connection-controls"].hidden = false;
  setBusy(busy);
  renderList();
  syncConnection(instance.id);
}

elements["create-form"].addEventListener("submit", async (event) => {
  event.preventDefault();
  if (busy || !elements["create-form"].reportValidity()) return;
  const name = elements["instance-name"].value.trim();
  if (!name) {
    elements["instance-name"].setCustomValidity("Enter an account name.");
    elements["instance-name"].reportValidity();
    return;
  }
  setBusy(true);
  elements["page-error"].hidden = true;
  elements["page-status"].textContent = "Adding your account…";
  try {
    const instance = await api("/api/whatsapp/instances", { method: "POST", body: JSON.stringify({ name }) });
    if (typeof instance?.id !== "string" || typeof instance?.name !== "string") throw new Error("Invalid account response");
    instances.push(instance);
    elements["instance-name"].value = "";
    elements["page-status"].textContent = "Account added. You can now connect WhatsApp.";
    selectInstance(instance);
  } catch (error) {
    showError(elements["page-error"], error, true);
    elements["page-status"].textContent = "";
  } finally { setBusy(false); }
});

elements["instance-name"].addEventListener("input", () => elements["instance-name"].setCustomValidity(""));

async function changeConnection(action) {
  if (!selectedId || busy) return;
  const id = selectedId;
  cancelPolling();
  setBusy(true);
  elements["connection-error"].hidden = true;
  elements["connection-status"].textContent = action === "connect" ? "Requesting connection…" : "Disconnecting…";
  hideQR();
  try {
    await api(`/api/whatsapp/instances/${encodeURIComponent(id)}/${action}`, { method: "POST" });
    if (id !== selectedId) return;
    pairingRequested = action === "connect";
    await syncConnection(id);
  } catch (error) {
    if (id === selectedId) {
      showError(elements["connection-error"], error, true);
      elements["connection-status"].textContent = "The request did not complete. Try again when the connection is available.";
    }
  } finally { setBusy(false); }
}

elements.connect.addEventListener("click", () => changeConnection("connect"));
elements.disconnect.addEventListener("click", () => changeConnection("disconnect"));
elements.refresh.addEventListener("click", () => {
  if (!selectedId || busy) return;
  cancelPolling();
  syncConnection(selectedId);
});

elements.logout.addEventListener("click", async () => {
  if (elements.logout.disabled) return;
  elements.logout.disabled = true;
  cancelPolling();
  try {
    await api("/api/auth/logout", { method: "POST" });
    csrfToken = "";
    window.location.assign("/login");
  } catch (error) {
    showError(elements["page-error"], error, true);
    elements.logout.disabled = false;
  }
});

document.addEventListener("visibilitychange", () => {
  cancelPolling();
  if (!document.hidden && selectedId && !busy) syncConnection(selectedId);
});
window.addEventListener("pagehide", cancelPolling);

async function initialize() {
  try {
    const account = await api("/api/auth/me");
    if (typeof account?.email !== "string" || typeof account?.csrf_token !== "string") throw new Error("Invalid session response");
    csrfToken = account.csrf_token;
    elements["account-email"].textContent = account.email;
    elements.logout.disabled = false;
    initializeProduct();
    const result = await api("/api/whatsapp/instances");
    if (!Array.isArray(result) || !result.every((entry) => typeof entry?.id === "string" && typeof entry?.name === "string")) {
      throw new Error("Invalid accounts response");
    }
    instances = result;
    loaded = true;
    setBusy(false);
    renderList();
    elements["page-status"].textContent = "";
    if (instances.length) selectInstance(instances[0]);
  } catch (error) {
    elements["page-status"].textContent = "Workspace could not be loaded. Reload this page to try again.";
    showError(elements["page-error"], error);
  }
}

initialize();

// Product panels share the authenticated session, but load independently of WhatsApp.
const panel = (id) => document.getElementById(id);
const agentFields = {
  name: "agent-name", business_name: "business-name", greeting: "greeting",
  business_description: "business-description", instructions: "instructions",
};
function panelError(section, error) {
  let message = "The request could not be completed. Try again.";
  if (error instanceof ApiError) {
    if (error.httpStatus === 401) message = "Your session has expired. Sign in again.";
    else if (error.httpStatus === 403) message = "Reload the page and try again.";
    else if (error.httpStatus === 404) message = "This item is no longer available. Refresh the list.";
    else if ([400, 413, 415, 422].includes(error.httpStatus)) {
      message = section === "knowledge"
        ? "Check the title and text, or upload a readable TXT, PDF, or DOCX file within the size limit."
        : "Check the form fields and try again.";
    } else if (error.httpStatus === 429) message = "Wait a moment before trying again.";
    else if (error.httpStatus >= 500) message = "This service is temporarily unavailable. Try again shortly.";
  }
  panel(`${section}-error`).textContent = message;
  panel(`${section}-error`).hidden = false;
  panel(`${section}-status`).textContent = "";
}
function startPanel(section, message) {
  panel(`${section}-error`).hidden = true;
  panel(`${section}-status`).textContent = message;
}
function enableForm(id, enabled) {
  for (const control of panel(id).querySelectorAll("input, textarea, button")) control.disabled = !enabled;
}
let agentBusy = false;
async function loadAgent() {
  if (agentBusy) return;
  agentBusy = true;
  enableForm("agent-form", false);
  startPanel("agent", "Loading assistant…");
  try {
    const agent = await api("/api/agent");
    for (const [key, id] of Object.entries(agentFields)) panel(id).value = agent?.[key] || "";
    panel("agent-status").textContent = "";
    enableForm("agent-form", true);
  } catch (error) { panelError("agent", error); }
  finally { agentBusy = false; panel("agent-retry").disabled = false; }
}
panel("agent-retry").addEventListener("click", loadAgent);
panel("agent-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  if (agentBusy || !panel("agent-form").reportValidity()) return;
  const data = { language: "en", voice: "kokoro_af_maple" };
  for (const [key, id] of Object.entries(agentFields)) data[key] = panel(id).value.trim();
  if (!data.name || [data.name, data.business_name, data.business_description, data.instructions].reduce((total, value) => total + value.length, 0) > 3600) {
    panel("agent-error").textContent = "Enter an assistant name and keep the names, business description, and instructions within 3,600 characters combined.";
    panel("agent-error").hidden = false;
    return;
  }
  agentBusy = true;
  enableForm("agent-form", false);
  startPanel("agent", "Saving assistant…");
  try {
    await api("/api/agent", { method: "PUT", body: JSON.stringify(data) });
    panel("agent-status").textContent = "Assistant saved.";
  } catch (error) { panelError("agent", error); }
  finally { agentBusy = false; enableForm("agent-form", true); }
});

let knowledgeBusy = false;
function knowledgeControls(enabled) {
  enableForm("knowledge-form", enabled);
  enableForm("upload-form", enabled);
  for (const button of panel("source-list").querySelectorAll("button")) button.disabled = !enabled;
}
function readableDate(value) {
  if (!value) return "Date unavailable";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "Date unavailable" : date.toLocaleString();
}
async function loadSources() {
  const result = await api("/api/knowledge");
  const sources = Array.isArray(result) ? result : result?.sources;
  if (!Array.isArray(sources)) throw new Error("Invalid sources response");
  panel("source-list").replaceChildren();
  for (const source of sources) {
    const row = document.createElement("li");
    const description = document.createElement("span");
    description.textContent = `${source.name} · ${String(source.kind || "text").toUpperCase()} · ${readableDate(source.created_at)}`;
    const remove = document.createElement("button");
    remove.type = "button"; remove.className = "secondary compact";
    remove.textContent = "Delete"; remove.setAttribute("aria-label", `Delete ${source.name}`);
    remove.addEventListener("click", () => knowledgeAction(async () => {
      await api(`/api/knowledge/${encodeURIComponent(source.id)}`, { method: "DELETE" });
    }, "Source deleted."));
    row.append(description, remove); panel("source-list").append(row);
  }
  return sources.length;
}
async function knowledgeAction(action, success) {
  if (knowledgeBusy) return;
  knowledgeBusy = true; knowledgeControls(false);
  startPanel("knowledge", "Updating knowledge…");
  try {
    await action();
    const count = await loadSources();
    panel("knowledge-status").textContent = success || (count ? "Sources refreshed." : "No sources yet. Add your first source above.");
  } catch (error) { panelError("knowledge", error); }
  finally { knowledgeBusy = false; knowledgeControls(true); }
}
panel("knowledge-retry").addEventListener("click", () => knowledgeAction(async () => {}, ""));
panel("knowledge-form").addEventListener("submit", (event) => {
  event.preventDefault();
  if (!panel("knowledge-form").reportValidity()) return;
  const name = panel("knowledge-name").value.trim();
  const text = panel("knowledge-text").value.trim();
  if (!name || !text) {
    panelError("knowledge", new ApiError(422)); return;
  }
  knowledgeAction(async () => {
    await api("/api/knowledge", { method: "POST", body: JSON.stringify({ name, text }), signal: AbortSignal.timeout(35000) });
    panel("knowledge-form").reset();
  }, "Knowledge added.");
});
panel("upload-form").addEventListener("submit", (event) => {
  event.preventDefault();
  const file = panel("knowledge-file").files[0];
  if (!file) return;
  if (!/\.(txt|pdf|docx)$/i.test(file.name) || file.size === 0 || file.size > 2 * 1024 * 1024) {
    panelError("knowledge", new ApiError(413)); return;
  }
  knowledgeAction(async () => {
    await api("/api/knowledge/upload", {
      method: "POST", body: file, signal: AbortSignal.timeout(35000),
      headers: { "Content-Type": "application/octet-stream", "x-file-name": encodeURIComponent(file.name) },
    });
    panel("upload-form").reset();
  }, "Document added.");
});

let callsBusy = false;
let detailRequest = 0;
let detailController = null;
async function loadCalls() {
  if (callsBusy) return;
  callsBusy = true; panel("calls-refresh").disabled = true;
  startPanel("calls", "Loading recent calls…");
  try {
    const result = await api("/api/calls?limit=50&offset=0");
    if (!Array.isArray(result?.calls)) throw new Error("Invalid calls response");
    panel("call-list").replaceChildren();
    for (const call of result.calls) {
      const row = document.createElement("li");
      const button = document.createElement("button");
      button.type = "button";
      button.textContent = `${call.caller || "Unknown caller"} · ${readableDate(call.started_at)} · ${call.state}`;
      button.addEventListener("click", () => loadCall(call.id));
      row.append(button); panel("call-list").append(row);
    }
    panel("calls-status").textContent = result.calls.length ? "Showing up to 50 recent calls. Select a call to see its conversation." : "No calls yet.";
  } catch (error) { panelError("calls", error); }
  finally { callsBusy = false; panel("calls-refresh").disabled = false; }
}
async function loadCall(id) {
  const request = ++detailRequest;
  if (detailController) detailController.abort();
  const controller = new AbortController();
  detailController = controller;
  const signal = AbortSignal.any([controller.signal, AbortSignal.timeout(30000)]);
  panel("call-detail").hidden = true;
  startPanel("calls", "Loading conversation…");
  try {
    const path = `/api/calls/${encodeURIComponent(id)}`;
    const result = await api(path, { signal });
    if (request !== detailRequest) return;
    // The server pages durable transcripts; bounded loops load the whole call.
    let cursor = result.next_sequence;
    for (let page = 1; cursor != null && page < 10; page++) {
      const next = await api(`${path}?after_sequence=${encodeURIComponent(cursor)}`, { signal });
      if (request !== detailRequest) return;
      result.messages.push(...next.messages);
      if (next.next_sequence === cursor) throw new Error("Transcript cursor did not advance");
      cursor = next.next_sequence;
    }
    if (cursor != null || result.messages.length > 1000) throw new Error("Transcript limit exceeded");
    const toolOffset = result.next_tool_offset;
    if (toolOffset != null) {
      const next = await api(`${path}?tool_offset=${encodeURIComponent(toolOffset)}`, { signal });
      if (request !== detailRequest) return;
      result.tool_calls.push(...next.tool_calls);
      if (next.next_tool_offset != null || result.tool_calls.length > 200) throw new Error("Action limit exceeded");
    }
    const call = result.call;
    panel("call-heading").textContent = `Call with ${call.caller || "unknown caller"}`;
    panel("call-meta").textContent = `${readableDate(call.started_at)} · ${call.state} · ${call.ended_at ? `Ended ${readableDate(call.ended_at)}` : "In progress"}`;
    panel("call-summary").textContent = call.summary || "Summary is not available yet.";
    panel("call-outcome").textContent = call.outcome || "Outcome is not available yet.";
    panel("transcript").replaceChildren();
    for (const message of result.messages) {
      const item = document.createElement("li");
      const speaker = document.createElement("strong");
      speaker.textContent = `${({ customer: "Caller", user: "Caller", agent: "Assistant", assistant: "Assistant", tool: "Action", system: "System" })[message.role] || "Message"}: `;
      const content = document.createElement("span"); content.textContent = message.content;
      item.append(speaker, content); panel("transcript").append(item);
    }
    if (!result.messages.length) { const item = document.createElement("li"); item.textContent = "No transcript available."; panel("transcript").append(item); }
    panel("call-actions").replaceChildren();
    for (const action of result.tool_calls) {
      const item = document.createElement("li");
      const name = ({ custom_webhook: "Business action", end_call: "End call", knowledge_search: "Knowledge search" })[action.name] || "Action";
      item.textContent = `${name}: ${action.status}${action.error_code ? " (could not complete)" : ""}`;
      panel("call-actions").append(item);
    }
    if (!result.tool_calls.length) { const item = document.createElement("li"); item.textContent = "No actions recorded."; panel("call-actions").append(item); }
    panel("call-detail").hidden = false; panel("call-heading").focus();
    panel("calls-status").textContent = "Conversation loaded.";
  } catch (error) { if (request === detailRequest) panelError("calls", error); }
  finally { if (detailController === controller) detailController = null; }
}
window.addEventListener("pagehide", () => { if (detailController) detailController.abort(); });
panel("calls-refresh").addEventListener("click", loadCalls);
function initializeProduct() {
  loadAgent(); knowledgeAction(async () => {}, ""); loadCalls();
}
