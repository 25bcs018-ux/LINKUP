(() => {
  const drawer = document.getElementById('appDrawer');
  const scrim = document.getElementById('appDrawerScrim');
  const openBtn = document.getElementById('appDrawerBtn');
  const closeBtn = document.getElementById('appDrawerClose');
  const appKeyInput = document.getElementById('appKeyInput');
  const backLink = document.getElementById('supportBackLink');
  const appLabels = Array.from(document.querySelectorAll('[data-app-label]'));
  const body = document.body;

  function openDrawer() {
    drawer?.classList.add('is-open');
    drawer?.setAttribute('aria-hidden', 'false');
    scrim?.classList.add('is-open');
    scrim?.setAttribute('aria-hidden', 'false');
  }

  function closeDrawer() {
    drawer?.classList.remove('is-open');
    drawer?.setAttribute('aria-hidden', 'true');
    scrim?.classList.remove('is-open');
    scrim?.setAttribute('aria-hidden', 'true');
  }

  function setApp(appKey, label, backUrl) {
    if (appKeyInput) appKeyInput.value = appKey || 'void';
    appLabels.forEach((el) => {
      el.textContent = label || 'Void';
    });
    if (backLink && backUrl) backLink.href = backUrl;
    if (body) body.dataset.app = appKey || 'void';
  }

  openBtn?.addEventListener('click', openDrawer);
  closeBtn?.addEventListener('click', closeDrawer);
  scrim?.addEventListener('click', closeDrawer);
  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape') closeDrawer();
  });

  document.querySelectorAll('[data-app-select]').forEach((btn) => {
    btn.addEventListener('click', () => {
      const appKey = btn.getAttribute('data-app-key') || 'void';
      const label = btn.getAttribute('data-app-label') || 'Void';
      const backUrl = btn.getAttribute('data-app-back') || '';
      setApp(appKey, label, backUrl);
      closeDrawer();
    });
  });
})();
