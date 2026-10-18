"use strict";
(() => {
  let csrf = "";
  let page = 1;
  let busy = false;
  const message = document.getElementById("admin-message");
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
    if (!response.ok)
      throw new Error(
        response.status === 403
          ? "Platform permission is required."
          : response.status === 409
            ? "This operation was refused by account safety rules."
            : "The request could not be completed. Check the filters and retry.",
      );
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
        "Platform permission is required.",
        "This operation was refused by account safety rules.",
        "The request could not be completed. Check the filters and retry.",
        "Sign in with your platform account to continue.",
      ];
      message.textContent = approved.includes(error.message)
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
            }),
          );
          td.append(button);
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
