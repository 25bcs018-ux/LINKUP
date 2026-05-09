(() => {
  if (window.location.pathname === '/kernel') return;

  const path = window.location.pathname || '/';
  let pageKey = '';
  if (path === '/' || path === '/index') pageKey = 'front';
  else if (path.startsWith('/chats')) pageKey = 'chats';
  else if (path.startsWith('/dashboard')) pageKey = 'dashboard';
  else if (path.startsWith('/support')) pageKey = 'support';
  else if (path.startsWith('/privacy')) pageKey = 'privacy';
  else if (path.startsWith('/terms')) pageKey = 'terms';
  else if (path.startsWith('/login')) pageKey = 'login';
  else if (path.startsWith('/register')) pageKey = 'register';
  if (!pageKey) return;

  const styleId = 'kernelStyle';
  const localKey = `linkup_kernel_css:${pageKey}`;

  function applyCss(css) {
    let el = document.getElementById(styleId);
    if (!el) {
      el = document.createElement('style');
      el.id = styleId;
      document.head.appendChild(el);
    }
    el.textContent = css || '';
  }

  try {
    const local = localStorage.getItem(localKey) || '';
    if (local) applyCss(local);
  } catch {}

  fetch(`/api/kernel/css?page=${encodeURIComponent(pageKey)}`, { credentials: 'same-origin' })
    .then((res) => res.json().catch(() => ({})))
    .then((data) => {
      if (data && data.css) applyCss(data.css);
    })
    .catch(() => {});
})();
