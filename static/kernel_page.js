(() => {
  const mount = document.getElementById('kernelMount');
  const statusEl = document.getElementById('kernelStatus');
  const pageSelect = document.getElementById('kernelPageSelect');
  const openTargetBtn = document.getElementById('kernelOpenTarget');
  if (!mount) return;

  const csrf = (document.querySelector('meta[name="csrf-token"]')?.getAttribute('content') || '').trim();
  let pageKey = String(pageSelect?.value || 'chats');
  let kernelLoggedIn = false;
  let visualMode = false;
  let selectedEl = null;

  const pageUrls = {
    chats: '/chats',
    dashboard: '/dashboard',
    front: '/',
    support: '/support',
    privacy: '/privacy',
    terms: '/terms',
    login: '/login',
    register: '/register'
  };

  const WORKSPACE_KEY = 'linkup_kernel_workspaces';

  function loadWorkspaces() {
    try {
      const raw = localStorage.getItem(WORKSPACE_KEY);
      const data = raw ? JSON.parse(raw) : [];
      return Array.isArray(data) ? data : [];
    } catch {
      return [];
    }
  }

  function saveWorkspaces(items) {
    try {
      localStorage.setItem(WORKSPACE_KEY, JSON.stringify(items || []));
    } catch {}
  }

  function kernelFetch(url, payload) {
    return fetch(url, {
      method: 'POST',
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json', ...(csrf ? { 'X-CSRF-Token': csrf } : {}) },
      body: JSON.stringify(payload || {})
    }).then(async (res) => {
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.error || 'Failed');
      return data;
    });
  }

  async function loadStatus() {
    try {
      const res = await fetch('/api/kernel/status', { credentials: 'same-origin' });
      const data = await res.json().catch(() => ({}));
      kernelLoggedIn = Boolean(data.kernel_logged_in);
      if (statusEl) {
        statusEl.textContent = kernelLoggedIn ? 'Kernel session active.' : 'Kernel session not active.';
      }
      return true;
    } catch {
      kernelLoggedIn = false;
      if (statusEl) statusEl.textContent = 'Kernel status unavailable.';
      return false;
    }
  }

  function renderLogin() {
    mount.innerHTML = `
      <div class="kernel-card">
        <strong>Kernel login</strong>
        <div class="kernel-row" style="margin-top:10px;">
          <input class="kernel-input" id="kernelUser" placeholder="Kernel username" />
          <input class="kernel-input" id="kernelPass" type="password" placeholder="Kernel password" />
        </div>
        <div class="kernel-hint">Password must be 6+ characters.</div>
        <div class="kernel-notice" id="kernelNotice" aria-live="polite"></div>
        <div class="kernel-actions">
          <button class="kernel-btn primary" id="kernelLogin" type="button">Login</button>
          <button class="kernel-btn" id="kernelRegister" type="button">Create kernel</button>
        </div>
      </div>
    `;

    function setNotice(message, kind) {
      const notice = document.getElementById('kernelNotice');
      if (!notice) return;
      notice.textContent = message || '';
      notice.classList.remove('error', 'ok');
      if (kind) notice.classList.add(kind);
    }

    document.getElementById('kernelLogin')?.addEventListener('click', async () => {
      const username = (document.getElementById('kernelUser')?.value || '').trim();
      const password = (document.getElementById('kernelPass')?.value || '').trim();
      try {
        setNotice('Logging in...', '');
        await kernelFetch('/api/kernel/login', { username, password });
        await loadStatus();
        renderMain();
      } catch (e) {
        setNotice(e.message || 'Login failed', 'error');
      }
    });

    document.getElementById('kernelRegister')?.addEventListener('click', async () => {
      const username = (document.getElementById('kernelUser')?.value || '').trim();
      const password = (document.getElementById('kernelPass')?.value || '').trim();
      if (username.length < 3 || username.length > 40) {
        setNotice('Username must be 3 to 40 characters.', 'error');
        return;
      }
      if (password.length < 6) {
        setNotice('Password must be at least 6 characters.', 'error');
        return;
      }
      try {
        setNotice('Creating kernel...', '');
        await kernelFetch('/api/kernel/register', { username, password });
        await loadStatus();
        renderMain();
      } catch (e) {
        setNotice(e.message || 'Register failed', 'error');
      }
    });
  }

  function renderMain() {
    mount.innerHTML = `
      <div class="kernel-card">
        <strong>Kernel session</strong>
        <div class="kernel-actions">
          <button class="kernel-btn" id="kernelLogout">Logout</button>
        </div>
      </div>
      <div class="kernel-card">
        <strong>Connect to LinkUp</strong>
        <div class="kernel-row" style="margin-top:10px;">
          <input class="kernel-input" id="linkupUser" placeholder="LinkUp username" />
          <input class="kernel-input" id="linkupPass" type="password" placeholder="LinkUp password" />
        </div>
        <div class="kernel-actions">
          <button class="kernel-btn" id="kernelConnect">Connect</button>
        </div>
        <div class="kernel-hint">Connect to enable permanent per-user CSS.</div>
      </div>
      <div class="kernel-card">
        <strong>Custom CSS (per user)</strong>
        <textarea class="kernel-textarea" id="kernelCss"></textarea>
        <div class="kernel-actions">
          <select class="kernel-select" id="kernelSaveMode">
            <option value="local">Save local</option>
            <option value="permanent">Save permanent</option>
          </select>
          <button class="kernel-btn primary" id="kernelSave">Save</button>
          <button class="kernel-btn" id="kernelApply">Apply local</button>
        </div>
        <div class="kernel-hint">Local uses browser cache; permanent requires connection.</div>
      </div>
      <div class="kernel-card">
        <strong>Visual mode</strong>
        <div class="kernel-actions">
          <button class="kernel-btn" id="kernelVisual">Toggle visual</button>
        </div>
        <div class="kernel-hint">Click any element outside the kernel UI to move it.</div>
      </div>
      <div class="kernel-card">
        <strong>Workspaces</strong>
        <div class="kernel-hint">Create focused setups for different pages.</div>
        <div class="kernel-actions" style="margin-top:8px;">
          <button class="kernel-btn" id="kernelWorkspaceToggle" type="button">Create workspace</button>
        </div>
        <div class="kernel-workspace-form" id="kernelWorkspaceForm" hidden>
          <input class="kernel-input" id="kernelWorkspaceName" placeholder="Workspace name" />
          <select class="kernel-select" id="kernelWorkspacePage">
            <option value="chats">Chats</option>
            <option value="dashboard">Dashboard</option>
            <option value="front">Front</option>
            <option value="support">Support</option>
            <option value="privacy">Privacy</option>
            <option value="terms">Terms</option>
            <option value="login">Login</option>
            <option value="register">Register</option>
          </select>
          <div class="kernel-actions">
            <button class="kernel-btn primary" id="kernelWorkspaceSave" type="button">Save</button>
            <button class="kernel-btn" id="kernelWorkspaceCancel" type="button">Cancel</button>
          </div>
        </div>
        <div class="kernel-workspace-list" id="kernelWorkspaceList"></div>
      </div>
    `;

    document.getElementById('kernelLogout')?.addEventListener('click', async () => {
      try {
        await kernelFetch('/api/kernel/logout', {});
      } catch {}
      kernelLoggedIn = false;
      renderLogin();
    });

    document.getElementById('kernelConnect')?.addEventListener('click', async () => {
      const username = (document.getElementById('linkupUser')?.value || '').trim();
      const password = (document.getElementById('linkupPass')?.value || '').trim();
      try {
        await kernelFetch('/api/kernel/connect', { username, password });
        alert('Connected. Permanent saves enabled.');
      } catch (e) {
        alert(e.message || 'Connect failed');
      }
    });

    document.getElementById('kernelApply')?.addEventListener('click', () => {
      const css = String(document.getElementById('kernelCss')?.value || '');
      applyLocalCss(css);
      saveLocalCss(css);
    });

    document.getElementById('kernelSave')?.addEventListener('click', async () => {
      const css = String(document.getElementById('kernelCss')?.value || '').trim();
      const mode = String(document.getElementById('kernelSaveMode')?.value || 'local');
      try {
        const data = await kernelFetch('/api/kernel/css/save', { page: pageKey, css, mode });
        if (data.saved === 'local') saveLocalCss(css);
        applyLocalCss(css);
        alert('Saved.');
      } catch (e) {
        alert(e.message || 'Save failed');
      }
    });

    document.getElementById('kernelVisual')?.addEventListener('click', () => {
      if (visualMode) {
        disableVisualMode();
      } else {
        enableVisualMode();
      }
    });

    const workspaceForm = document.getElementById('kernelWorkspaceForm');
    const workspaceList = document.getElementById('kernelWorkspaceList');
    const workspaceName = document.getElementById('kernelWorkspaceName');
    const workspacePage = document.getElementById('kernelWorkspacePage');

    function renderWorkspaces() {
      const items = loadWorkspaces();
      if (!workspaceList) return;
      if (!items.length) {
        workspaceList.innerHTML = '<div class="kernel-muted">No workspaces yet.</div>';
        return;
      }
      workspaceList.innerHTML = items.map((item) => {
        const label = String(item.name || 'Workspace');
        const page = String(item.page || 'chats');
        return `
          <div class="kernel-workspace">
            <div>
              <strong>${label}</strong>
              <div class="kernel-muted">Page: ${page}</div>
            </div>
            <div class="kernel-actions">
              <button class="kernel-btn" data-action="open" data-page="${page}">Open</button>
              <button class="kernel-btn" data-action="select" data-page="${page}">Select</button>
            </div>
          </div>
        `;
      }).join('');
    }

    document.getElementById('kernelWorkspaceToggle')?.addEventListener('click', () => {
      if (!workspaceForm) return;
      workspaceForm.hidden = !workspaceForm.hidden;
      if (!workspaceForm.hidden && workspaceName) workspaceName.focus();
    });

    document.getElementById('kernelWorkspaceCancel')?.addEventListener('click', () => {
      if (!workspaceForm) return;
      workspaceForm.hidden = true;
      if (workspaceName) workspaceName.value = '';
    });

    document.getElementById('kernelWorkspaceSave')?.addEventListener('click', () => {
      const name = String(workspaceName?.value || '').trim();
      const page = String(workspacePage?.value || 'chats');
      if (!name) {
        alert('Workspace name is required.');
        return;
      }
      const items = loadWorkspaces();
      items.unshift({
        id: `ws_${Date.now()}`,
        name,
        page,
        created_at: Date.now()
      });
      saveWorkspaces(items.slice(0, 20));
      if (workspaceName) workspaceName.value = '';
      if (workspaceForm) workspaceForm.hidden = true;
      renderWorkspaces();
    });

    workspaceList?.addEventListener('click', (event) => {
      const target = event.target;
      if (!(target instanceof HTMLElement)) return;
      const action = target.getAttribute('data-action');
      const page = target.getAttribute('data-page') || 'chats';
      if (action === 'open') {
        const url = pageUrls[page] || '/chats';
        window.open(url, '_blank', 'noopener');
      }
      if (action === 'select') {
        if (pageSelect) pageSelect.value = page;
        pageKey = page;
        hydrateCss();
      }
    });

    renderWorkspaces();

    hydrateCss();
  }

  function localKey() {
    return `linkup_kernel_css:${pageKey}`;
  }

  function saveLocalCss(css) {
    try { localStorage.setItem(localKey(), css); } catch {}
  }

  function loadLocalCss() {
    try { return localStorage.getItem(localKey()) || ''; } catch { return ''; }
  }

  function applyLocalCss(css) {
    let el = document.getElementById('kernelStyle');
    if (!el) {
      el = document.createElement('style');
      el.id = 'kernelStyle';
      document.head.appendChild(el);
    }
    el.textContent = css || '';
  }

  async function hydrateCss() {
    const local = loadLocalCss();
    if (local) {
      applyLocalCss(local);
      const input = document.getElementById('kernelCss');
      if (input) input.value = local;
    }
    try {
      const res = await fetch(`/api/kernel/css?page=${encodeURIComponent(pageKey)}`, { credentials: 'same-origin' });
      const data = await res.json().catch(() => ({}));
      if (res.ok && data.css) {
        applyLocalCss(data.css);
        const input = document.getElementById('kernelCss');
        if (input) input.value = data.css;
      }
    } catch {}
  }

  function enableVisualMode() {
    visualMode = true;
    document.body.classList.add('kernel-visual-active');
    document.addEventListener('click', onVisualClick, true);
  }

  function disableVisualMode() {
    visualMode = false;
    document.body.classList.remove('kernel-visual-active');
    document.removeEventListener('click', onVisualClick, true);
    if (selectedEl) selectedEl.classList.remove('kernel-highlight');
    selectedEl = null;
  }

  function onVisualClick(ev) {
    const target = ev.target;
    if (!(target instanceof HTMLElement)) return;
    ev.preventDefault();
    ev.stopPropagation();
    if (selectedEl) selectedEl.classList.remove('kernel-highlight');
    selectedEl = target;
    selectedEl.classList.add('kernel-highlight');
    const rect = selectedEl.getBoundingClientRect();
    const posCss = `#${ensureKernelId(selectedEl)} { position: fixed; left: ${Math.round(rect.left)}px; top: ${Math.round(rect.top)}px; }`;
    const input = document.getElementById('kernelCss');
    if (input) {
      input.value = (input.value || '') + `\n${posCss}`.trim();
    }
    applyLocalCss(input?.value || '');
  }

  function ensureKernelId(el) {
    if (el.id) return el.id;
    const id = `kernel_${Math.random().toString(36).slice(2, 8)}`;
    el.id = id;
    return id;
  }

  function openTargetPage() {
    const url = pageUrls[pageKey] || '/chats';
    window.open(url, '_blank', 'noopener');
  }

  pageSelect?.addEventListener('change', () => {
    pageKey = String(pageSelect.value || 'chats');
    hydrateCss();
  });

  openTargetBtn?.addEventListener('click', openTargetPage);

  loadStatus().then(() => {
    if (kernelLoggedIn) {
      renderMain();
    } else {
      renderLogin();
    }
  });
})();
