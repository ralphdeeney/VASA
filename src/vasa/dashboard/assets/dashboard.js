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
  if (options.body !== undefined) headers["Content-Type"] = "application/json";
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
