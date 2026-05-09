(() => {
  window.addEventListener('DOMContentLoaded', () => {
    requestAnimationFrame(() => document.body.classList.add('void-enter'));
  });

  const tabSignIn = document.getElementById('tabSignIn');
  const tabCreate = document.getElementById('tabCreate');
  const panelSignIn = document.getElementById('panelSignIn');
  const panelCreate = document.getElementById('panelCreate');

  function setTab(which) {
    const isCreate = which === 'create';
    tabSignIn?.classList.toggle('active', !isCreate);
    tabCreate?.classList.toggle('active', isCreate);
    tabSignIn?.setAttribute('aria-selected', isCreate ? 'false' : 'true');
    tabCreate?.setAttribute('aria-selected', isCreate ? 'true' : 'false');
    panelSignIn?.classList.toggle('hidden', isCreate);
    panelCreate?.classList.toggle('hidden', !isCreate);
  }

  tabSignIn?.addEventListener('click', () => setTab('signin'));
  tabCreate?.addEventListener('click', () => setTab('create'));

  const initial = document.body?.dataset?.voidTab || 'signin';
  setTab(initial === 'create' ? 'create' : 'signin');
})();
