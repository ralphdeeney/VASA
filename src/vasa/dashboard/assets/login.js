"use strict";

const form = document.getElementById("login-form");
const email = document.getElementById("email");
const password = document.getElementById("password");
const submit = document.getElementById("login-submit");
const error = document.getElementById("login-error");
const status = document.getElementById("login-status");

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (!form.reportValidity() || submit.disabled) return;
  error.hidden = true;
  submit.disabled = true;
  status.textContent = "Signing in…";
  try {
    const response = await fetch("/api/auth/login", {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email: email.value.trim(), password: password.value }),
      signal: AbortSignal.timeout(15000),
    });
    if (!response.ok) {
      error.textContent = response.status === 429
        ? "Too many sign-in attempts. Wait a few minutes and try again."
        : response.status === 401
          ? "The email or password is incorrect. Please try again."
          : "Sign-in is unavailable. Please try again or contact your administrator.";
      error.hidden = false;
      error.focus();
      return;
    }
    password.value = "";
    window.location.assign("/dashboard");
  } catch {
    error.textContent = "Could not reach VASA. Check your connection and try again.";
    error.hidden = false;
    error.focus();
  } finally {
    submit.disabled = false;
    status.textContent = "";
  }
});
