'use strict';
// Apply a saved palette before the page body paints, then wire every theme control.
(() => {
  const key = 'foodbridge.theme';
  const stylesheet = document.getElementById('marketplace-theme');
  const metaColor = document.querySelector('meta[name="theme-color"]');
  let theme = 'dark';
  try { theme = localStorage.getItem(key) === 'light' ? 'light' : 'dark'; }
  catch (_) { /* Private browsing may block storage. */ }

  function updateButtons() {
    const dark = theme === 'dark';
    document.querySelectorAll('[data-theme-toggle]').forEach(button => {
      const label = `Switch to ${dark ? 'light' : 'dark'} theme`;
      button.setAttribute('aria-label', label);
      button.title = label;
      button.querySelector('.theme-toggle-label').textContent = dark ? 'Light theme' : 'Dark theme';
    });
  }

  function apply(next, save) {
    theme = next === 'light' ? 'light' : 'dark';
    document.documentElement.dataset.theme = theme;
    if (stylesheet) stylesheet.disabled = theme === 'light';
    if (metaColor) metaColor.content = theme === 'dark' ? '#0b1422' : '#f4f7f8';
    if (save) {
      try { localStorage.setItem(key, theme); } catch (_) { /* Keep this tab's choice. */ }
    }
    updateButtons();
  }

  apply(theme, false);
  document.addEventListener('DOMContentLoaded', () => {
    updateButtons();
    document.querySelectorAll('[data-theme-toggle]').forEach(button => {
      button.addEventListener('click', () => apply(theme === 'dark' ? 'light' : 'dark', true));
    });
  });
  window.addEventListener('storage', event => {
    if (event.key === key) apply(event.newValue, false);
  });
})();
