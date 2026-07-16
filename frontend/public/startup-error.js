const parameters = new URLSearchParams(window.location.search);
const detail = document.querySelector("#startup-error-detail");

if (detail instanceof HTMLParagraphElement) {
  detail.textContent =
    parameters.get("message") ?? "Glacial encountered an unknown startup error.";
}
