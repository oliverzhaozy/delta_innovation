// The only client-side behavior in the app: copy-to-clipboard for generated text.
document.addEventListener("click", (event) => {
  const button = event.target.closest("[data-copy]");
  if (!button) return;
  const source = document.querySelector(button.dataset.copy);
  if (!source) return;
  navigator.clipboard.writeText(source.innerText).then(() => {
    const original = button.textContent;
    button.textContent = "Copied ✓";
    setTimeout(() => (button.textContent = original), 1500);
  });
});
