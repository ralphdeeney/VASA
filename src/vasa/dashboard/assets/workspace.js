"use strict";
(() => {
  let csrf = "";
  const message = document.getElementById("saas-message");
  const notice = (text) => {
    message.textContent = text;
  };
  async function request(path, method = "GET", body) {
    const response = await fetch(path, {
      method,
      credentials: "same-origin",
      headers: { "Content-Type": "application/json", "x-csrf-token": csrf },
      body: body === undefined ? undefined : JSON.stringify(body),
      signal: AbortSignal.timeout(15000),
    });
    if (!response.ok)
      throw new Error(
        response.status === 403
          ? "Your role does not permit this action."
          : response.status === 409
            ? "This change conflicts with workspace safety rules."
            : response.status === 503
              ? "This service is not available yet."
              : "The action could not be completed. Check your details and try again.",
      );
    return response.status === 204 ? null : response.json();
  }
  async function perform(action) {
    try {
      await action();
    } catch (error) {
      notice(error.message);
    }
  }
  function cell(row, value) {
    const td = document.createElement("td");
    td.textContent = String(value ?? "—");
    row.append(td);
    return td;
  }
  async function team() {
    const data = await request("/api/saas/team");
    const rows = document.getElementById("team-rows");
    rows.replaceChildren();
    for (const member of data.items) {
      const row = document.createElement("tr");
      for (const key of ["name", "email", "role", "status"])
        cell(row, member[key]);
      const controls = cell(row, "");
      const select = document.createElement("select");
      select.setAttribute("aria-label", `Role for ${member.email}`);
      for (const role of ["owner", "admin", "member"]) {
        const option = document.createElement("option");
        option.value = role;
        option.textContent = role;
        option.selected = member.role === role;
        select.append(option);
      }
      const save = document.createElement("button");
      save.type = "button";
      save.textContent = "Update";
      save.addEventListener("click", () =>
        perform(async () => {
          if (!window.confirm("Confirm this team role change?")) return;
          await request(
            `/api/saas/team/${encodeURIComponent(member.user_id)}`,
            "PATCH",
            { role: select.value, status: member.status, confirm: true },
          );
          await team();
          notice("Team membership updated.");
        }),
      );
      const revoke = document.createElement("button");
      revoke.type = "button";
      revoke.className = "secondary";
      revoke.textContent =
        member.status === "revoked" ? "Reactivate" : "Revoke";
      revoke.addEventListener("click", () =>
        perform(async () => {
          if (!window.confirm("Confirm this membership access change?")) return;
          await request(
            `/api/saas/team/${encodeURIComponent(member.user_id)}`,
            "PATCH",
            {
              role: member.role,
              status: member.status === "revoked" ? "active" : "revoked",
              confirm: true,
            },
          );
          await team();
          notice("Membership access updated.");
        }),
      );
      controls.append(select, save, revoke);
      rows.append(row);
    }
  }
  function bind(id, action) {
    document.getElementById(id).addEventListener("submit", (event) => {
      event.preventDefault();
      if (event.target.reportValidity()) perform(action);
    });
  }
  async function integrations() {
    const status = document.getElementById("integrations-status");
    const list = document.getElementById("integrations-list");
    status.textContent = "Loading permitted integration metadata…";
    try {
      const response = await fetch("/api/saas/integrations", {
        credentials: "same-origin",
        signal: AbortSignal.timeout(15000),
      });
      if (!response.ok) {
        status.textContent =
          response.status === 403
            ? "Only workspace owners and admins can view configured integrations."
            : "Integration metadata is unavailable. Please try again later.";
        return;
      }
      const data = await response.json();
      list.replaceChildren();
      for (const item of data.items) {
        const row = document.createElement("li");
        const name = document.createElement("span");
        name.textContent = item.name;
        const badge = document.createElement("span");
        badge.className = "badge";
        badge.textContent = "Tool Gateway · configured";
        row.append(name, badge);
        list.append(row);
      }
      status.textContent = data.items.length
        ? "Configured actions available to this workspace. Execution remains in the authorized runtime."
        : "No Tool Gateway actions are configured for this workspace.";
    } catch {
      status.textContent =
        "Could not load integration metadata. Check your connection and retry.";
    }
  }
  async function init() {
    try {
      const capabilities = await request("/api/site/capabilities");
      if (!capabilities.saas_enabled) return;
      await integrations();
      csrf = (await request("/api/auth/me")).csrf_token;
      document.getElementById("saas-workspace").hidden = false;
      const workspaces = await request("/api/saas/workspaces");
      for (const item of workspaces.items) {
        const option = document.createElement("option");
        option.value = item.id;
        option.textContent = item.name;
        option.selected = item.selected;
        document.getElementById("workspace-select").append(option);
      }
      const profile = await request("/api/saas/profile");
      document.getElementById("platform-admin-link").hidden = profile.platform_admin !== true;
      document.getElementById("profile-name").value = profile.name;
      document.getElementById("profile-email").textContent = profile.email;
      const organization = await request("/api/saas/organization");
      document.getElementById("organization-name").value = organization.name;
      await team();
    } catch {
      notice(
        "Some workspace administration features could not be loaded. Your voice workspace remains available.",
      );
    }
  }
  bind("workspace-select-form", async () => {
    await request("/api/saas/workspace", "POST", {
      tenant_id: document.getElementById("workspace-select").value,
    });
    window.location.reload();
  });
  bind("profile-form", async () => {
    await request("/api/saas/profile", "PATCH", {
      name: document.getElementById("profile-name").value,
    });
    notice("Profile saved.");
  });
  bind("organization-form", async () => {
    await request("/api/saas/organization", "PATCH", {
      name: document.getElementById("organization-name").value,
    });
    notice("Business profile saved.");
  });
  bind("invitation-form", async () => {
    await request("/api/saas/invitations", "POST", {
      email: document.getElementById("invite-email").value,
      role: document.getElementById("invite-role").value,
    });
    notice("Invitation sent.");
    document.getElementById("invite-email").value = "";
  });
  init();
})();
