"use strict";
(() => {
  let csrf = "";
  let page = 1;
  let busy = false;
  const message = document.getElementById("admin-message");
  const refusalMessages = {
    self_organization_deletion_denied: "You cannot delete the workspace used by your current session.",
    suspend_organization_first: "Suspend this organization before deleting it.",
    organization_name_mismatch: "The organization name does not match. Nothing was deleted.",
    active_calls_block_deletion: "Deletion is blocked by active or unresolved call state. Wait for calls to finish.",
    disconnect_whatsapp_first: "WhatsApp disconnection could not be verified. No registration was removed. Check connection state before retrying.",
    deletion_capacity_exceeded: "This organization requires operator-assisted deletion.",
    self_suspension_denied: "You cannot suspend your own platform login.",
    platform_admin_protected: "Platform administrators are protected from suspension.",
    last_role_required: "This user is the last active owner or admin of a workspace. Assign a replacement first, or suspend the organization instead.",
    self_organization_suspension_denied: "You cannot suspend the workspace used by your current session.",
  };
  async function api(path, method = "GET", body) {
    const response = await fetch(path, {
      method,
      credentials: "same-origin",
      headers: { "Content-Type": "application/json", "x-csrf-token": csrf },
      body: body === undefined ? undefined : JSON.stringify(body),
      signal: AbortSignal.timeout(15000),
    });
    if (response.status === 401) {
      window.location.assign("/admin/login");
      throw new Error("Sign in with your platform account to continue.");
    }
    if (!response.ok) {
      if (path.endsWith("/delete") && [403, 503].includes(response.status)) {
        const data = await response.json().catch(() => ({}));
        throw new Error(data.detail === "invalid_current_password" ? "Your current password is incorrect."
          : "Deletion could not finish. The organization remains suspended. Retry to reconcile its connections; do not recreate it.");
      }
      if (response.status === 409) {
        const data = await response.json().catch(() => ({}));
        throw new Error(refusalMessages[data.detail] || "This operation was refused by account safety rules.");
      }
      throw new Error(
        response.status === 403
          ? "Platform permission is required."
          : response.status === 409
            ? "This operation was refused by account safety rules."
            : "The request could not be completed. Check the filters and retry.",
      );
    }
    return response.json();
  }
  async function safe(action) {
    if (busy) return;
    busy = true;
    const buttons = [...document.querySelectorAll("button")];
    const disabled = buttons.map((button) => button.disabled);
    buttons.forEach((button) => { button.disabled = true; });
    try {
      await action();
    } catch (error) {
      const approved = [
        "Your current password is incorrect.",
        "Deletion could not finish. The organization remains suspended. Retry to reconcile its connections; do not recreate it.",
        "Platform permission is required.",
        "This operation was refused by account safety rules.",
        "The request could not be completed. Check the filters and retry.",
        "Sign in with your platform account to continue.",
      ];
      message.className = "notice admin-notice admin-feedback-error";
      message.textContent = [...approved, ...Object.values(refusalMessages)].includes(error.message)
        ? error.message : "The request could not be completed. Please retry.";
    } finally {
      buttons.forEach((button, index) => { button.disabled = disabled[index]; });
      document.getElementById("admin-previous").disabled = page <= 1;
      document.getElementById("admin-next").disabled = !hasNext;
      busy = false;
    }
  }
  let hasNext = false;
  const columns = {
    users: ["email", "name", "status", "email_verified", "platform_admin"],
    organizations: ["id", "name", "slug", "status"],
    registrations: ["email", "tenant_id", "status", "created_at"],
    audit: ["action", "target", "actor_id", "tenant_id", "created_at"],
  };
  let deletionTarget = null;
  document.getElementById("admin-delete-cancel").addEventListener("click", () => {
    document.getElementById("admin-delete-dialog").close();
    document.getElementById("admin-delete-password").value = "";
    deletionTarget = null;
  });
  document.getElementById("admin-delete-dialog").addEventListener("close", () => {
    document.getElementById("admin-delete-password").value = "";
  });
  document.getElementById("admin-delete-form").addEventListener("submit", (event) => {
    event.preventDefault();
    if (!deletionTarget) return;
    if (document.getElementById("admin-delete-name").value !== deletionTarget.name) {
      document.getElementById("admin-delete-message").textContent = "Enter the exact organization name.";
      return;
    }
    safe(async () => {
      const target = deletionTarget;
      const password = document.getElementById("admin-delete-password").value;
      document.getElementById("admin-delete-password").value = "";
      document.getElementById("admin-delete-dialog").close();
      await api(`/api/saas/admin/organizations/${encodeURIComponent(target.id)}/delete`, "POST", {
        confirm: true, confirm_name: target.name, current_password: password,
      });
      deletionTarget = null;
      await load();
      message.className = "notice admin-notice admin-feedback-success";
      message.textContent = "Organization and its WhatsApp registrations deleted. Other workspaces were preserved.";
    });
  });
  async function load() {
    const directory = document.getElementById("admin-directory").value;
    const params = new URLSearchParams({ page: String(page), page_size: "20" });
    const query = document.getElementById("admin-query").value.trim();
    if (query) params.set("search", query);
    const status = document.getElementById("admin-status").value;
    if (status && directory !== "audit") params.set("status", status);
    if (["users", "organizations"].includes(directory))
      params.set("sort", document.getElementById("admin-sort").value);
    const data = await api(`/api/saas/admin/${directory}?${params}`);
    const head = document.getElementById("admin-columns");
    const rows = document.getElementById("admin-rows");
    head.replaceChildren();
    rows.replaceChildren();
    const heading = document.createElement("tr");
    for (const key of columns[directory]) {
      const th = document.createElement("th");
      th.scope = "col";
      th.textContent = key.replaceAll("_", " ");
      heading.append(th);
    }
    if (directory !== "audit") {
      const th = document.createElement("th");
      th.scope = "col";
      th.textContent = "Actions";
      heading.append(th);
    }
    head.append(heading);
    for (const item of data.items) {
      const row = document.createElement("tr");
      for (const key of columns[directory]) {
        const td = document.createElement("td");
        td.textContent = String(item[key] ?? "—");
        if (key === "status" && ["active", "suspended", "pending"].includes(item[key])) {
          const badge = document.createElement("span");
          badge.className = `admin-status-badge admin-status-${item[key]}`;
          badge.textContent = item[key][0].toUpperCase() + item[key].slice(1);
          td.replaceChildren(badge);
        }
        row.append(td);
      }
      if (directory !== "audit") {
        const td = document.createElement("td");
        const states =
          directory === "registrations"
            ? ["approved", "rejected"]
            : [item.status === "suspended" ? "active" : "suspended"];
        for (const status of states) {
          const button = document.createElement("button");
          button.type = "button";
          button.className = "secondary compact";
          button.textContent =
            status === "active"
              ? "Reactivate"
              : status === "suspended"
                ? "Suspend"
                : status;
          button.addEventListener("click", () =>
            safe(async () => {
              if (
                !window.confirm(
                  `Confirm ${status} for this ${directory === "users" ? "user" : directory === "organizations" ? "organization" : "registration"}?`,
                )
              )
                return;
              await api(
                `/api/saas/admin/${directory}/${encodeURIComponent(item.id)}/${directory === "registrations" ? "review" : "status"}`,
                "POST",
                { status, confirm: true },
              );
              await load();
              message.className = "notice admin-notice admin-feedback-success";
              message.textContent = status === "suspended"
                ? "Suspended successfully. You can reactivate this account here."
                : status === "active" ? "Reactivated successfully." : "Registration updated.";
            }),
          );
          td.append(button);
        }
        if (directory === "organizations") {
          const remove = document.createElement("button");
          remove.type = "button";
          remove.className = "secondary compact";
          remove.textContent = "Delete…";
          remove.addEventListener("click", () => {
            deletionTarget = item;
            document.getElementById("admin-delete-form").reset();
            document.getElementById("admin-delete-message").textContent = "";
            document.getElementById("admin-delete-scope").textContent = `Selected organization: ${item.name} (${item.id})`;
            document.getElementById("admin-delete-dialog").showModal();
          });
          td.append(remove);
        }
        if (directory === "users") {
          const details = document.createElement("details");
          const summary = document.createElement("summary");
          summary.textContent = "Memberships";
          details.append(summary);
          for (const membership of item.memberships || []) {
            const text = document.createElement("p");
            text.textContent = `${membership.tenant_id} · ${membership.role} · ${membership.status}`;
            details.append(text);
          }
          td.append(details);
        }
        row.append(td);
      }
      rows.append(row);
    }
    document.getElementById("admin-caption").textContent =
      `${directory} directory`;
    document.getElementById("admin-page").textContent =
      `Page ${page} · ${data.total} records`;
    document.getElementById("admin-previous").disabled = page <= 1;
    hasNext = page * 20 < data.total;
    document.getElementById("admin-next").disabled = !hasNext;
    message.className = "notice admin-notice";
    message.textContent = data.items.length
      ? "Authorized records loaded."
      : "No matching records.";
  }
  document
    .getElementById("admin-search")
    .addEventListener("submit", (event) => {
      event.preventDefault();
      if (busy) return;
      page = 1;
      safe(load);
    });
  document.getElementById("admin-previous").addEventListener("click", () => {
    if (busy) return;
    page = Math.max(1, page - 1);
    safe(load);
  });
  document.getElementById("admin-next").addEventListener("click", () => {
    if (busy) return;
    page += 1;
    safe(load);
  });
  document
    .getElementById("admin-connections")
    .addEventListener("submit", (event) => {
      event.preventDefault();
      safe(async () => {
        const data = await api(
          `/api/saas/admin/connections?tenant_id=${encodeURIComponent(document.getElementById("admin-tenant").value)}`,
        );
        const list = document.getElementById("admin-connection-list");
        list.replaceChildren();
        for (const item of data.items) {
          const li = document.createElement("li");
          li.textContent = `${item.name} · ${item.id}`;
          list.append(li);
        }
        message.textContent = "Scoped connections loaded.";
      });
    });
  async function refreshHealth() {
    const health = await api("/api/saas/admin/health");
    document.getElementById("admin-health").textContent = health.status === "ready"
      ? "Platform checks passed." : "Platform is not ready. Review operational monitoring.";
  }
  document.getElementById("admin-health-refresh").addEventListener("click", () => safe(refreshHealth));
  document.querySelectorAll("[data-directory]").forEach((link) => {
    link.addEventListener("click", () => {
      if (busy) return;
      document.getElementById("admin-directory").value = link.dataset.directory;
      document.getElementById("admin-status").value = "";
      document.getElementById("admin-sort").value = "created_at";
      page = 1;
      document.querySelectorAll(".admin-navigation a").forEach((item) => item.removeAttribute("aria-current"));
      link.setAttribute("aria-current", "page");
      safe(load);
    });
  });
  document.getElementById("admin-directory").addEventListener("change", () => {
    document.getElementById("admin-status").value = "";
    document.getElementById("admin-sort").value = "created_at";
  });
  document.getElementById("admin-password-form").addEventListener("submit", (event) => {
    event.preventDefault();
    const current = document.getElementById("admin-current-password");
    const password = document.getElementById("admin-new-password");
    const confirm = document.getElementById("admin-confirm-password");
    const status = document.getElementById("admin-password-message");
    if (password.value !== confirm.value) {
      status.textContent = "The new passwords do not match.";
      return;
    }
    if (!window.confirm("Change your password and sign out all sessions?")) return;
    safe(async () => {
      await api("/api/saas/admin/password", "POST", {
        current_password: current.value, new_password: password.value,
      });
      current.value = ""; password.value = ""; confirm.value = "";
      status.textContent = "Password changed. Sign in again with your new password.";
      window.location.assign("/admin/login");
    });
  });
  safe(async () => {
    csrf = (await api("/api/auth/me")).csrf_token;
    const overview = await api("/api/saas/admin/overview");
    for (const key of [
      "users",
      "organizations",
      "connections",
      "registrations",
    ]) {
      const card = document.createElement("p");
      card.className = "admin-metric";
      card.textContent = {users: "Registered users", organizations: "Organizations", connections: "WhatsApp connections", registrations: "Registrations"}[key];
      const count = document.createElement("strong");
      count.textContent = String(overview[key]);
      card.append(count);
      document.getElementById("admin-metrics").append(card);
    }
    const account = await api("/api/saas/admin/account");
    document.getElementById("admin-account").textContent = `${account.username} · ${account.email} · Platform super admin`;
    await refreshHealth();
    await load();
  });
})();
