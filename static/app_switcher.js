(() => {
  const prefersReducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  const coarsePointer = window.matchMedia('(pointer: coarse)').matches || window.matchMedia('(hover: none)').matches;
  const lowMemory = typeof navigator !== 'undefined' && navigator.deviceMemory && navigator.deviceMemory <= 4;
  if (prefersReducedMotion || coarsePointer || lowMemory) {
    document.body.classList.add('perf-mode');
  }

  const root = document.querySelector('[data-app-switcher]');
  if (!root) return;

  const button = root.querySelector('.app-switcher-btn');
  const panel = root.querySelector('.app-switcher-panel');
  const scrim = root.querySelector('.app-switcher-scrim');
  const STORAGE_KEY = 'app_switcher_pos_v1';
  let isDragging = false;
  let dragStart = null;
  let movedEnough = false;
  let tapHandled = false;

  function clamp(value, min, max) {
    return Math.min(Math.max(value, min), max);
  }

  function readStoredPosition() {
    try {
      const raw = localStorage.getItem(STORAGE_KEY);
      if (!raw) return null;
      const parsed = JSON.parse(raw);
      if (!parsed || typeof parsed.x !== 'number' || typeof parsed.y !== 'number') return null;
      return parsed;
    } catch {
      return null;
    }
  }

  function storePosition(x, y) {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify({ x, y }));
    } catch {
      // ignore storage failures
    }
  }

  function applyPosition(x, y) {
    if (!button) return;
    const rect = button.getBoundingClientRect();
    const maxX = window.innerWidth - rect.width - 8;
    const maxY = window.innerHeight - rect.height - 8;
    const nextX = clamp(x, 8, Math.max(8, maxX));
    const nextY = clamp(y, 8, Math.max(8, maxY));
    button.style.left = `${nextX}px`;
    button.style.top = `${nextY}px`;
    button.style.transform = 'translate(0, 0)';
  }

  function initPosition() {
    const saved = readStoredPosition();
    if (saved) {
      applyPosition(saved.x, saved.y);
      return;
    }
    const rect = button?.getBoundingClientRect();
    if (!rect) return;
    const x = 12;
    const y = Math.max(12, (window.innerHeight / 2) - (rect.height / 2));
    applyPosition(x, y);
  }

  function openPanel() {
    panel?.classList.add('is-open');
    panel?.setAttribute('aria-hidden', 'false');
    scrim?.classList.add('is-open');
    scrim?.setAttribute('aria-hidden', 'false');
  }

  function closePanel() {
    panel?.classList.remove('is-open');
    panel?.setAttribute('aria-hidden', 'true');
    scrim?.classList.remove('is-open');
    scrim?.setAttribute('aria-hidden', 'true');
  }

  button?.addEventListener('click', () => {
    if (tapHandled) {
      tapHandled = false;
      return;
    }
    if (panel?.classList.contains('is-open')) {
      closePanel();
    } else {
      openPanel();
    }
  });

  button?.addEventListener('pointerdown', (event) => {
    if (!button) return;
    if (event.button && event.button !== 0) return;
    isDragging = true;
    movedEnough = false;
    button.setPointerCapture(event.pointerId);
    const rect = button.getBoundingClientRect();
    dragStart = {
      offsetX: event.clientX - rect.left,
      offsetY: event.clientY - rect.top,
      startX: event.clientX,
      startY: event.clientY,
    };
  });

  button?.addEventListener('pointermove', (event) => {
    if (!isDragging || !dragStart) return;
    const nextX = event.clientX - dragStart.offsetX;
    const nextY = event.clientY - dragStart.offsetY;
    if (!movedEnough) {
      const dx = Math.abs(event.clientX - dragStart.startX);
      const dy = Math.abs(event.clientY - dragStart.startY);
      if (dx > 12 || dy > 12) movedEnough = true;
    }
    applyPosition(nextX, nextY);
  });

  button?.addEventListener('pointerup', (event) => {
    if (!isDragging) return;
    isDragging = false;
    const shouldToggle = !movedEnough;
    dragStart = null;
    button.releasePointerCapture(event.pointerId);
    if (shouldToggle) {
      tapHandled = true;
      movedEnough = false;
      if (panel?.classList.contains('is-open')) {
        closePanel();
      } else {
        openPanel();
      }
      return;
    }
    tapHandled = true;
    const x = parseFloat(button.style.left) || 12;
    const y = parseFloat(button.style.top) || 12;
    storePosition(x, y);
  });

  button?.addEventListener('pointercancel', (event) => {
    if (!isDragging) return;
    isDragging = false;
    dragStart = null;
    try { button.releasePointerCapture(event.pointerId); } catch {}
  });

  window.addEventListener('resize', () => {
    const x = parseFloat(button?.style.left || '12') || 12;
    const y = parseFloat(button?.style.top || '12') || 12;
    applyPosition(x, y);
  });

  scrim?.addEventListener('click', closePanel);

  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape') closePanel();
  });

  initPosition();
})();
