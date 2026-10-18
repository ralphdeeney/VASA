"use strict";
(() => {
  const form = document.getElementById("admin-login-form");
  const button = document.getElementById("admin-login-submit");
  const message = document.getElementById("admin-login-message");
  let pending = false;
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (pending) return;
    pending = true;
    button.disabled = true;
    message.textContent = "Signing in…";
    const password = document.getElementById("admin-login-password");
    try {
      const response = await fetch("/api/auth/admin/login", {
        method: "POST", credentials: "same-origin",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({username: document.getElementById("admin-username").value.trim(), password: password.value}),
        signal: AbortSignal.timeout(15000),
      });
      if (response.ok) {
        password.value = "";
        window.location.assign("/admin");
        return;
      }
      message.textContent = response.status === 429
        ? "Too many sign-in attempts. Please wait before trying again."
        : response.status === 401 || response.status === 403
          ? "The username or password is incorrect, or platform access is unavailable."
          : "Platform sign-in is temporarily unavailable. Please try again.";
    } catch {
      message.textContent = "Unable to connect. Please check your connection and retry.";
    } finally {
      pending = false;
      button.disabled = false;
    }
  });
})();
