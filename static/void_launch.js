(() => {
  const storageKey = 'void_app_launch_v1';
  window.addEventListener('pageshow', () => {
    document.querySelectorAll('.app-launch-enter').forEach((el) => el.remove());
    try { localStorage.removeItem(storageKey); } catch {}
  });

  const data = (() => {
    try {
      const raw = localStorage.getItem(storageKey);
      if (!raw) return null;
      return JSON.parse(raw);
    } catch {
      return null;
    }
  })();

  if (!data) return;

  try { localStorage.removeItem(storageKey); } catch {}

  const body = document.body;
  const appKey = body?.dataset?.voidLaunchApp || '';
  const targetSelector = body?.dataset?.voidLaunchTarget || '';
  if (!appKey || !targetSelector || data.app !== appKey) return;

  const target = document.querySelector(targetSelector);
  if (!target) return;

  const rect = target.getBoundingClientRect();
  if (!rect.width || !rect.height) return;

  const overlay = document.createElement('div');
  overlay.className = 'app-launch-enter';
  const startW = Number(data.w) || 56;
  const startH = Number(data.h) || 56;
  overlay.style.width = `${startW}px`;
  overlay.style.height = `${startH}px`;
  overlay.style.borderRadius = data.radius || '16px';
  const startLeft = (window.innerWidth / 2) - (startW / 2);
  const startTop = (window.innerHeight / 2) - (startH / 2);
  overlay.style.left = `${startLeft}px`;
  overlay.style.top = `${startTop}px`;

  const logoWrap = document.createElement('div');
  logoWrap.className = 'app-launch-logo';
  if (data.html) logoWrap.innerHTML = data.html;
  overlay.appendChild(logoWrap);
  document.body.appendChild(overlay);

  const centerX = startLeft + (startW / 2);
  const centerY = startTop + (startH / 2);
  const targetCenterX = rect.left + (rect.width / 2);
  const targetCenterY = rect.top + (rect.height / 2);
  const deltaX = targetCenterX - centerX;
  const deltaY = targetCenterY - centerY;
  const scale = Math.min(rect.width / startW, rect.height / startH);

  overlay.style.setProperty(
    '--target-transform',
    `translate3d(${deltaX}px, ${deltaY}px, 0) scale(${scale || 1})`
  );

  requestAnimationFrame(() => {
    requestAnimationFrame(() => {
      overlay.classList.add('is-active');
    });
  });

  window.setTimeout(() => {
    overlay.remove();
  }, 900);
})();
