(() => {
  window.addEventListener('DOMContentLoaded', () => {
    requestAnimationFrame(() => document.body.classList.add('void-enter'));
  });

  window.addEventListener('pageshow', () => {
    document.body.classList.remove('void-app-launching');
    document.querySelectorAll('.app-launch-overlay').forEach((el) => el.remove());
    isLaunching = false;
  });

  const tabs = Array.from(document.querySelectorAll('.app-tab'));
  const titleEl = document.getElementById('appTitle');
  const descEl = document.getElementById('appDesc');
  const panel = document.querySelector('.app-panel');
  const accountBtn = document.getElementById('voidAccountBtn');
  const accountDrawer = document.getElementById('voidAccountDrawer');
  const accountClose = document.getElementById('voidAccountClose');
  const accountScrim = document.getElementById('voidAccountScrim');
  const tourReplay = document.getElementById('voidTourReplay');
  const manualOpen = document.getElementById('voidManualOpen');
  const manual = document.getElementById('voidManual');
  const manualClose = document.getElementById('voidManualClose');
  const manualTabs = Array.from(document.querySelectorAll('.manual-tab'));
  const manualChapters = Array.from(document.querySelectorAll('.manual-chapter'));
  const tour = document.getElementById('voidTour');
  const tourStep = document.getElementById('voidTourStep');
  const tourVoice = document.getElementById('voidTourVoice');
  const tourTitle = document.getElementById('voidTourTitle');
  const tourCopy = document.getElementById('voidTourCopy');
  const tourHint = document.getElementById('voidTourHint');
  const tourBack = document.getElementById('voidTourBack');
  const tourNext = document.getElementById('voidTourNext');
  const tourSkip = document.getElementById('voidTourSkip');
  let isLaunching = false;

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

  function isTourOpen() {
    return tour?.classList.contains('is-open');
  }

  function isManualOpen() {
    return manual?.classList.contains('is-open');
  }

  function updateModalState() {
    if (isTourOpen() || isManualOpen()) {
      document.body.classList.add('void-modal-open');
    } else {
      document.body.classList.remove('void-modal-open');
    }
  }

  function openManual() {
    if (!manual) return;
    if (isTourOpen()) closeTour();
    manual.classList.add('is-open');
    manual.setAttribute('aria-hidden', 'false');
    closeAccountDrawer();
    updateModalState();
  }

  function closeManual() {
    if (!manual) return;
    manual.classList.remove('is-open');
    manual.setAttribute('aria-hidden', 'true');
    updateModalState();
  }

  function setManualChapter(chapter) {
    manualTabs.forEach((tab) => {
      const isActive = tab.dataset.chapter === chapter;
      tab.classList.toggle('is-active', isActive);
      tab.setAttribute('aria-selected', isActive ? 'true' : 'false');
    });
    manualChapters.forEach((section) => {
      section.classList.toggle('is-active', section.dataset.chapter === chapter);
    });
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

  function launchApp(tab, href) {
    if (!tab || !href) return;
    if (isLaunching) return;
    const prefersReducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    if (prefersReducedMotion) {
      window.location.href = href;
      return;
    }

    isLaunching = true;

    const logo = tab.querySelector('.app-logo');
    const rect = (logo || tab).getBoundingClientRect();
    const overlay = document.createElement('div');
    overlay.className = 'app-launch-overlay';
    overlay.style.left = `${rect.left}px`;
    overlay.style.top = `${rect.top}px`;
    overlay.style.width = `${rect.width}px`;
    overlay.style.height = `${rect.height}px`;
    overlay.style.borderRadius = getComputedStyle(logo || tab).borderRadius || '16px';

    const logoWrap = document.createElement('div');
    logoWrap.className = 'app-launch-logo';
    if (logo) logoWrap.innerHTML = logo.innerHTML;
    overlay.appendChild(logoWrap);

    const viewportWidth = window.innerWidth;
    const viewportHeight = window.innerHeight;
    const centerX = rect.left + rect.width / 2;
    const centerY = rect.top + rect.height / 2;
    const deltaX = (viewportWidth / 2) - centerX;
    const deltaY = (viewportHeight / 2) - centerY;
    const scale = 1.6;

    overlay.style.setProperty(
      '--target-transform',
      `translate3d(${deltaX}px, ${deltaY}px, 0) scale(${scale})`
    );

    try {
      localStorage.setItem('void_app_launch_v1', JSON.stringify({
        app: tab.dataset.app || '',
        html: logo ? logo.innerHTML : '',
        w: rect.width,
        h: rect.height,
        radius: overlay.style.borderRadius,
        t: Date.now()
      }));
    } catch {
      // ignore storage failures
    }

    document.body.classList.add('void-app-launching');
    document.body.appendChild(overlay);

    requestAnimationFrame(() => {
      requestAnimationFrame(() => {
        overlay.classList.add('is-active');
      });
    });

    window.setTimeout(() => {
      window.location.href = href;
    }, 2000);
  }

  tabs.forEach((tab) => {
    tab.addEventListener('mouseenter', () => setActive(tab));
    tab.addEventListener('focus', () => setActive(tab));
    tab.addEventListener('click', () => {
      const href = tab.dataset.href || '';
      recordAppUse(tab.dataset.app || '');
      if (href) launchApp(tab, href);
    });
    tab.addEventListener('keydown', (event) => {
      if (event.key === 'Enter' || event.key === ' ') {
        event.preventDefault();
        const href = tab.dataset.href || '';
        recordAppUse(tab.dataset.app || '');
        if (href) launchApp(tab, href);
      }
    });
  });

  accountBtn?.addEventListener('click', openAccountDrawer);
  accountClose?.addEventListener('click', closeAccountDrawer);
  accountScrim?.addEventListener('click', closeAccountDrawer);
  manualOpen?.addEventListener('click', openManual);
  manualClose?.addEventListener('click', closeManual);
  manualTabs.forEach((tab) => {
    tab.addEventListener('click', () => setManualChapter(tab.dataset.chapter));
  });
  if (manualTabs.length > 0) {
    setManualChapter(manualTabs[0].dataset.chapter);
  }
  document.addEventListener('keydown', (event) => {
    if (event.key !== 'Escape') return;
    if (isManualOpen()) {
      closeManual();
      return;
    }
    if (isTourOpen()) {
      closeTour();
      return;
    }
    closeAccountDrawer();
  });

  const tourSlides = [
    {
      voice: 'Hey, I am your guide. I will keep this quick and human.',
      title: 'Welcome to VOID',
      copy: 'This is the hub. Every app starts here, and your Void ID carries you across them.',
      hint: 'Hover the app cards to preview the experience.',
      target: '.void-head'
    },
    {
      voice: 'Each card is a doorway. Pick the one that matches your moment.',
      title: 'Choose an app',
      copy: 'Tap a card to launch LinkUp, Secure, Kernel, or Creator.',
      hint: 'Click a card to enter right away.',
      target: '.app-tabs'
    },
    {
      voice: 'This one is your identity control room.',
      title: 'Open your account drawer',
      copy: 'Profile details, usage, support, and the Void Book live here.',
      hint: 'Hit Account to open the drawer.',
      target: '#voidAccountBtn',
      ensureDrawer: true
    },
    {
      voice: 'If you forget anything, the book is your map.',
      title: 'The Void Book',
      copy: 'This manual explains the mission, the apps, and how to move around.',
      hint: 'Open the Void Book for the full guide.',
      target: '#voidAccountDrawer',
      ensureDrawer: true
    },
    {
      voice: 'You are ready. I will stay quiet unless you call me.',
      title: 'Launch and explore',
      copy: 'Jump into an app and build your flow. You can replay this tour anytime.',
      hint: 'Use the app switcher to jump between apps fast.',
      target: '.app-panel'
    }
  ];

  function shouldShowTour() {
    const flag = document.body?.dataset?.showVoidTour === '1';
    if (!flag) return false;
    try {
      return localStorage.getItem('void_tour_done') !== '1';
    } catch {
      return true;
    }
  }

  function markTourDone() {
    try {
      localStorage.setItem('void_tour_done', '1');
    } catch {
      // ignore storage failures
    }
  }

  function renderTour(index) {
    const slide = tourSlides[index] || tourSlides[0];
    if (tourStep) tourStep.textContent = `Step ${index + 1} of ${tourSlides.length}`;
    if (tourVoice) tourVoice.textContent = slide.voice || '';
    if (tourTitle) tourTitle.textContent = slide.title;
    if (tourCopy) tourCopy.textContent = slide.copy;
    if (tourHint) tourHint.textContent = slide.hint || '';
    if (tourNext) tourNext.textContent = index === tourSlides.length - 1 ? 'Finish' : 'Next';
    if (tourBack) tourBack.disabled = index === 0;
    setTourTarget(slide.target);
    if (slide.ensureDrawer) {
      openAccountDrawer();
    }
  }

  let activeTourTarget = null;
  function setTourTarget(selector) {
    if (activeTourTarget) activeTourTarget.classList.remove('tour-target');
    if (!selector) {
      activeTourTarget = null;
      return;
    }
    const nextTarget = document.querySelector(selector);
    if (nextTarget) {
      nextTarget.classList.add('tour-target');
      activeTourTarget = nextTarget;
    }
  }

  function openTour() {
    if (!tour) return;
    closeManual();
    tourIndex = 0;
    renderTour(0);
    tour.classList.add('is-open');
    tour.setAttribute('aria-hidden', 'false');
    updateModalState();
  }

  function closeTour() {
    if (!tour) return;
    tour.classList.remove('is-open');
    tour.setAttribute('aria-hidden', 'true');
    markTourDone();
    setTourTarget(null);
    updateModalState();
  }

  let tourIndex = 0;
  tourBack?.addEventListener('click', () => {
    tourIndex = Math.max(0, tourIndex - 1);
    renderTour(tourIndex);
  });
  tourNext?.addEventListener('click', () => {
    tourIndex += 1;
    if (tourIndex >= tourSlides.length) {
      closeTour();
      return;
    }
    renderTour(tourIndex);
  });

  tourSkip?.addEventListener('click', closeTour);
  tourReplay?.addEventListener('click', () => {
    openTour();
    closeAccountDrawer();
  });

  if (shouldShowTour()) {
    openTour();
  }


  setActive(tabs[0]);
})();
