(() => {
  window.addEventListener('DOMContentLoaded', () => {
    requestAnimationFrame(() => document.body.classList.add('void-enter'));
  });

  const tabs = Array.from(document.querySelectorAll('.app-tab'));
  const titleEl = document.getElementById('appTitle');
  const descEl = document.getElementById('appDesc');
  const panel = document.querySelector('.app-panel');
  const accountBtn = document.getElementById('voidAccountBtn');
  const accountDrawer = document.getElementById('voidAccountDrawer');
  const accountClose = document.getElementById('voidAccountClose');
  const accountScrim = document.getElementById('voidAccountScrim');

  const usageKeys = ['linkup', 'secure', 'kernel', 'creator'];

  function getUsage() {
    try {
      return JSON.parse(localStorage.getItem('void_app_usage') || '{}');
    } catch (error) {
      return {};
    }
  }

  function setUsage(usage) {
    localStorage.setItem('void_app_usage', JSON.stringify(usage));
  }

  function recordAppUse(appKey) {
    if (!appKey) return;
    const usage = getUsage();
    usage[appKey] = (usage[appKey] || 0) + 1;
    setUsage(usage);
  }

  function updateUsageUI() {
    const usage = getUsage();
    const uniqueCount = usageKeys.filter((key) => usage[key]).length;
    const totalEl = document.getElementById('voidAppsCount');
    if (totalEl) totalEl.textContent = String(uniqueCount);
    const map = {
      linkup: 'voidUsageLinkup',
      secure: 'voidUsageSecure',
      kernel: 'voidUsageKernel',
      creator: 'voidUsageCreator'
    };
    Object.keys(map).forEach((key) => {
      const el = document.getElementById(map[key]);
      if (el) el.textContent = String(usage[key] || 0);
    });
  }

  function formatDate(value) {
    if (!value) return '--';
    const parsed = new Date(value);
    if (Number.isNaN(parsed.valueOf())) return value;
    return parsed.toLocaleDateString();
  }

  function hydrateAccount() {
    const data = document.body?.dataset || {};
    const nameEl = document.getElementById('voidAccountName');
    const emailEl = document.getElementById('voidAccountEmail');
    const idEl = document.getElementById('voidAccountId');
    const createdEl = document.getElementById('voidAccountCreated');
    if (nameEl) nameEl.textContent = data.voidUsername || '--';
    if (emailEl) emailEl.textContent = data.voidEmail || '--';
    if (idEl) idEl.textContent = data.voidId || '--';
    if (createdEl) createdEl.textContent = formatDate(data.voidCreated);
    updateUsageUI();
  }

  function openAccountDrawer() {
    accountDrawer?.classList.add('is-open');
    accountDrawer?.setAttribute('aria-hidden', 'false');
    accountScrim?.classList.add('is-open');
    accountScrim?.setAttribute('aria-hidden', 'false');
    hydrateAccount();
  }

  function closeAccountDrawer() {
    accountDrawer?.classList.remove('is-open');
    accountDrawer?.setAttribute('aria-hidden', 'true');
    accountScrim?.classList.remove('is-open');
    accountScrim?.setAttribute('aria-hidden', 'true');
  }

  function setActive(tab) {
    if (!tab) return;
    tabs.forEach((t) => {
      const isActive = t === tab;
      t.classList.toggle('is-active', isActive);
      t.setAttribute('aria-selected', isActive ? 'true' : 'false');
    });
    if (titleEl) titleEl.textContent = tab.dataset.title || 'App';
    if (descEl) descEl.textContent = tab.dataset.desc || '';
    if (panel) {
      panel.classList.remove('app-panel-pulse');
      void panel.offsetWidth;
      panel.classList.add('app-panel-pulse');
    }
  }

  tabs.forEach((tab) => {
    tab.addEventListener('mouseenter', () => setActive(tab));
    tab.addEventListener('focus', () => setActive(tab));
    tab.addEventListener('click', () => {
      const href = tab.dataset.href || '';
      recordAppUse(tab.dataset.app || '');
      if (href) window.location.href = href;
    });
    tab.addEventListener('keydown', (event) => {
      if (event.key === 'Enter' || event.key === ' ') {
        event.preventDefault();
        const href = tab.dataset.href || '';
        recordAppUse(tab.dataset.app || '');
        if (href) window.location.href = href;
      }
    });
  });

  accountBtn?.addEventListener('click', openAccountDrawer);
  accountClose?.addEventListener('click', closeAccountDrawer);
  accountScrim?.addEventListener('click', closeAccountDrawer);
  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape') closeAccountDrawer();
  });


  setActive(tabs[0]);
})();
