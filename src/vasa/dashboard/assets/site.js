"use strict";
const section = {
  "/features": "features",
  "/how-it-works": "how-it-works",
  "/pricing": "pricing",
  "/contact": "contact",
}[window.location.pathname];
if (section) document.getElementById(section)?.scrollIntoView();

(() => {
  const form = document.getElementById("contact-form");
  if (!form) return;
  const status = document.getElementById("contact-status");
  const submit = document.getElementById("contact-submit");
  const fields = ["name", "email", "message"].map((name) =>
    document.getElementById(`contact-${name}`),
  );
  async function prepareContact() {
    try {
      const response = await fetch("/api/site/capabilities", {
        credentials: "same-origin",
        signal: AbortSignal.timeout(15000),
      });
      if (!response.ok || (await response.json()).contact_available !== true) {
        status.textContent =
          "The enquiry form is not available yet. You can still sign in to your workspace below.";
        return;
      }
      form.hidden = false;
      for (const field of fields) field.disabled = false;
      submit.disabled = false;
      status.textContent =
        "Your request will be sent to the VASA team. Do not include passwords or private API keys.";
    } catch {
      status.textContent =
        "Contact availability could not be checked. Please try again later.";
    }
  }
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (submit.disabled || !form.reportValidity()) return;
    submit.disabled = true;
    try {
      const response = await fetch("/api/site/contact", {
        method: "POST",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name: fields[0].value,
          email: fields[1].value,
          message: fields[2].value,
        }),
        signal: AbortSignal.timeout(15000),
      });
      if (!response.ok) {
        status.className = "notice error";
        status.textContent =
          response.status === 429
            ? "Too many requests. Please wait before trying again."
            : response.status === 503
              ? "Contact delivery is unavailable. Please try again later."
              : "Your request could not be sent. Check your details and try again.";
        return;
      }
      status.className = "small muted";
      form.reset();
      form.hidden = true;
      status.textContent = "Your request has been sent to the VASA team.";
    } catch {
      status.className = "notice error";
      status.textContent =
        "Could not reach VASA. Check your connection and retry.";
    } finally {
      submit.disabled = false;
    }
  });
  prepareContact();
})();
