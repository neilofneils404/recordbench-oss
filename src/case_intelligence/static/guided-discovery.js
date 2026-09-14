/* One explicit batch per submission; no polling or automatic continuation. */
(() => {
  let submitting = false;
  document.querySelectorAll('[data-discovery-batch]').forEach(form => {
    form.addEventListener('submit', event => {
      if (submitting) { event.preventDefault(); return; }
      submitting = true;
      document.querySelectorAll('[data-discovery-batch] button').forEach(button => { button.disabled = true; });
      document.querySelector('[data-discovery-progress]').hidden = false;
    });
  });
  window.addEventListener('pageshow', () => {
    submitting = false;
    document.querySelectorAll('[data-discovery-batch] button').forEach(button => { button.disabled = false; });
    document.querySelector('[data-discovery-progress]').hidden = true;
  });
})();
