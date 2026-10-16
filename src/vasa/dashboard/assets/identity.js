"use strict";
(() => {
  const mode = window.location.pathname.slice(1);
  const form = document.getElementById("identity-form");
  const message = document.getElementById("identity-message");
  const submit = document.getElementById("identity-submit");
  const definitions = {
    signup: [
      "Create your workspace",
      "Verify your email before connecting WhatsApp.",
      ["name", "business", "email", "password"],
      "Create account",
    ],
    "resend-verification": [
      "Verify your email",
      "Request a fresh verification email before accepting an invitation.",
      ["email"],
      "Send verification email",
    ],
    "forgot-password": [
      "Forgot your password?",
      "We’ll send recovery instructions if your account is eligible.",
      ["email"],
      "Send reset instructions",
    ],
    "reset-password": [
      "Choose a new password",
      "Use the private link from your recovery email.",
      ["password"],
      "Reset password",
    ],
    "verify-email": [
      "Verify your email",
      "Confirm your email to continue onboarding.",
      [],
      "Verify email",
    ],
    "accept-invitation": [
      "Join your team",
      "Sign in with the verified email that received this invitation first.",
      [],
      "Accept invitation",
    ],
    logout: ["Sign out", "End your current VASA session.", [], "Sign out"],
  };
  const definition = definitions[mode];
  if (!definition) return;
  document.getElementById("identity-title").textContent = definition[0];
  document.getElementById("identity-description").textContent = definition[1];
  submit.textContent = definition[3];
  for (const name of definition[2]) {
    document.getElementById(`${name}-field`).hidden = false;
    document.getElementById(name).required = true;
  }
  // Keep private tokens out of query strings, referrers and subsequent navigation.
  const token =
    new URLSearchParams(window.location.hash.slice(1)).get("token") || "";
  if (window.location.hash)
    history.replaceState(null, "", window.location.pathname);
  let csrf = "";
  async function prepare() {
    try {
      const response = await fetch("/api/site/capabilities", {
        credentials: "same-origin",
        signal: AbortSignal.timeout(15000),
      });
      const capabilities = await response.json();
      if (mode !== "logout" && !capabilities.saas_enabled) {
        message.textContent =
          "Account onboarding is not enabled yet. Contact your workspace administrator.";
        return;
      }
      if (
        ["signup", "forgot-password", "resend-verification"].includes(mode) &&
        !capabilities.email_delivery_available
      ) {
        message.textContent =
          "Email delivery is not configured. Contact your administrator before continuing.";
        return;
      }
      if (mode === "signup" && !capabilities.signup_available) {
        message.textContent =
          "Public registration is not available at the moment.";
        return;
      }
      if (
        ["verify-email", "reset-password", "accept-invitation"].includes(
          mode,
        ) &&
        !token
      ) {
        message.textContent =
          "Open the complete private link from your email to continue.";
        return;
      }
      if (["logout", "accept-invitation"].includes(mode)) {
        const session = await fetch("/api/auth/me", {
          credentials: "same-origin",
        });
        if (!session.ok) {
          message.textContent = "Sign in first, then reopen this page.";
          return;
        }
        csrf = (await session.json()).csrf_token;
      }
      message.textContent = "";
      submit.disabled = false;
    } catch {
      message.textContent =
        "Could not reach VASA. Check your connection and reload this page.";
    }
  }
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (submit.disabled || !form.reportValidity()) return;
    submit.disabled = true;
    const payload = {};
    for (const field of definition[2])
      payload[field === "business" ? "business_name" : field] =
        document.getElementById(field).value;
    if (token) payload.token = token;
    try {
      const response = await fetch(
        mode === "logout" ? "/api/auth/logout" : `/api/saas/${mode}`,
        {
          method: "POST",
          credentials: "same-origin",
          headers: { "Content-Type": "application/json", "x-csrf-token": csrf },
          body: JSON.stringify(payload),
          signal: AbortSignal.timeout(15000),
        },
      );
      if (!response.ok) {
        message.textContent =
          response.status === 429
            ? "Too many attempts. Please wait and try again."
            : response.status === 403
              ? "This action is not permitted. Sign in with the appropriate account."
              : response.status === 503
                ? "This service is unavailable. Contact your administrator."
                : "The request could not be completed. Check your details or request a fresh email link.";
        return;
      }
      form.hidden = true;
      message.textContent =
        mode === "signup"
          ? "Check your email for your verification link. WhatsApp has not been connected."
          : ["forgot-password", "resend-verification"].includes(mode)
            ? "If an eligible account exists, recovery instructions will be sent."
            : mode === "logout"
              ? "You have signed out."
              : "Your request is complete. Sign in if your account is active; approval may still be required.";
      if (document.getElementById("password"))
        document.getElementById("password").value = "";
    } catch {
      message.textContent =
        "Could not reach VASA. Check your connection and try again.";
    } finally {
      submit.disabled = false;
    }
  });
  prepare();
})();
