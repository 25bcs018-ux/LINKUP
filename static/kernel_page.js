(() => {
  const mount = document.getElementById('kernelMount');
  const statusEl = document.getElementById('kernelStatus');
  if (!mount) return;

  const csrf = (document.querySelector('meta[name="csrf-token"]')?.getAttribute('content') || '').trim();
  const editPageKey = 'linkup_kernel_edit_page';
  let pageKey = 'chats';
  let kernelLoggedIn = false;
  let kernelUsername = '';

  try {
    const storedPage = localStorage.getItem(editPageKey);
    if (storedPage) pageKey = storedPage;
  } catch {}

  try {
    if (csrf) localStorage.setItem('linkup_kernel_csrf', csrf);
  } catch {}

  const pageUrls = {
    chats: '/chats',
    dashboard: '/dashboard',
    support: '/support',
    linkup_feedback: '/linkup/feedback'
  };

  function escapeHtml(s) {
    return String(s)
      .replaceAll('&', '&amp;')
      .replaceAll('<', '&lt;')
      .replaceAll('>', '&gt;')
      .replaceAll('"', '&quot;')
      .replaceAll("'", '&#39;');
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
      kernelUsername = String(data.kernel_username || '').trim();
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
    document.body.classList.add('kernel-auth');
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
        renderWelcome();
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
        renderWelcome();
      } catch (e) {
        setNotice(e.message || 'Register failed', 'error');
      }
    });
  }

  function renderWelcome() {
    document.body.classList.remove('kernel-auth');
    const name = kernelUsername ? escapeHtml(kernelUsername) : 'Creator';
    mount.innerHTML = `
      <div class="kernel-card">
        <strong>Welcome, ${name}</strong>
        <div class="kernel-hint">Choose how you want to build your UI changes.</div>
        <div class="kernel-actions">
          <button class="kernel-btn primary" id="kernelContinue">Continue</button>
          <button class="kernel-btn" id="kernelLogout">Logout</button>
        </div>
      </div>
    `;

    document.getElementById('kernelContinue')?.addEventListener('click', renderMethodChooser);
    document.getElementById('kernelLogout')?.addEventListener('click', async () => {
      try {
        await kernelFetch('/api/kernel/logout', {});
      } catch {}
      kernelLoggedIn = false;
      renderLogin();
    });
  }

  function renderMethodChooser() {
    document.body.classList.remove('kernel-auth');
    mount.innerHTML = `
      <div class="kernel-card">
        <strong>Choose a method</strong>
        <div class="kernel-hint">Visual edits are saved with keys. Developer mode is coming next.</div>
        <div class="kernel-methods">
          <div class="kernel-method-card">
            <div>
              <strong>Developer method</strong>
              <div class="kernel-hint">Code-first editing (coming soon).</div>
            </div>
            <button class="kernel-btn" type="button" disabled>Developer</button>
          </div>
          <div class="kernel-method-card">
            <div>
              <strong>Visual method</strong>
              <div class="kernel-hint">Click and edit UI without code.</div>
            </div>
            <button class="kernel-btn primary" type="button" id="kernelOpenVisual">Visual</button>
          </div>
        </div>
        <div class="kernel-actions">
          <button class="kernel-btn" id="kernelLogout">Logout</button>
        </div>
      </div>
    `;

    document.getElementById('kernelOpenVisual')?.addEventListener('click', renderVisualSetup);
    document.getElementById('kernelLogout')?.addEventListener('click', async () => {
      try {
        await kernelFetch('/api/kernel/logout', {});
      } catch {}
      kernelLoggedIn = false;
      renderLogin();
    });
  }

  function renderVisualSetup() {
    document.body.classList.remove('kernel-auth');
    mount.innerHTML = `
      <div class="kernel-card">
        <strong>Visual method</strong>
        <div class="kernel-hint">Pick a LinkUp page to edit, preview it, then open the visual editor.</div>
        <div class="kernel-actions">
          <select class="kernel-select" id="kernelEditPage">
            <option value="chats">Chats</option>
            <option value="dashboard">Dashboard</option>
            <option value="support">Support</option>
            <option value="linkup_feedback">Feedback</option>
          </select>
          <button class="kernel-btn" id="kernelPreviewPage" type="button">Preview</button>
          <button class="kernel-btn primary" id="kernelVisualOpen" type="button">Open editor</button>
        </div>
        <div class="kernel-actions">
          <button class="kernel-btn" id="kernelBackMethods" type="button">Back</button>
          <button class="kernel-btn" id="kernelLogout" type="button">Logout</button>
        </div>
      </div>
      <div class="kernel-card">
        <strong>Publish key</strong>
        <div class="kernel-hint">Use the visual editor to save and generate a key for LinkUp settings.</div>
      </div>
      <div class="kernel-card">
        <strong>History</strong>
        <div class="kernel-history" id="kernelHistoryList">Loading history...</div>
      </div>
    `;

    const editPageSelect = document.getElementById('kernelEditPage');
    if (editPageSelect) {
      editPageSelect.value = pageKey;
      if (!editPageSelect.value) editPageSelect.value = 'chats';
    }

    editPageSelect?.addEventListener('change', () => {
      pageKey = String(editPageSelect.value || pageKey || 'chats');
    });

    document.getElementById('kernelPreviewPage')?.addEventListener('click', () => {
      const target = String(editPageSelect?.value || pageKey);
      pageKey = target;
      openTargetPage(false);
    });

    document.getElementById('kernelVisualOpen')?.addEventListener('click', () => {
      const target = String(editPageSelect?.value || pageKey);
      pageKey = target;
      openTargetPage(true);
    });

    document.getElementById('kernelBackMethods')?.addEventListener('click', renderMethodChooser);

    document.getElementById('kernelLogout')?.addEventListener('click', async () => {
      try {
        await kernelFetch('/api/kernel/logout', {});
      } catch {}
      kernelLoggedIn = false;
      renderLogin();
    });

    loadHistory();
  }

  function openTargetPage(visual) {
    const baseUrl = pageUrls[pageKey] || '/chats';
    const url = new URL(baseUrl, window.location.origin);
    try { localStorage.setItem(editPageKey, pageKey); } catch {}
    if (visual) {
      try { localStorage.setItem('linkup_kernel_visual', '1'); } catch {}
      url.searchParams.set('kernel_default', '1');
    }
    window.open(url.toString(), '_blank', 'noopener');
  }

  async function loadHistory() {
    const host = document.getElementById('kernelHistoryList');
    if (!host) return;
    host.textContent = 'Loading history...';
    try {
      const res = await fetch('/api/kernel/key/history', { credentials: 'same-origin' });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.error || 'Unable to load');
      const items = Array.isArray(data.items) ? data.items : [];
      if (!items.length) {
        host.textContent = 'No keys yet.';
        return;
      }
      host.innerHTML = items.map((item) => `
        <div class="kernel-history-row" data-id="${escapeHtml(item.id)}">
          <div>
            <strong>${escapeHtml(item.page || 'page')}</strong>
            <div class="kernel-hint">${escapeHtml(item.created_at || '')}</div>
          </div>
          <button class="kernel-btn" type="button" data-action="reveal">Reveal</button>
          <button class="kernel-btn" type="button" data-action="copy" disabled>Copy</button>
        </div>
      `).join('');

      host.querySelectorAll('[data-action="reveal"]').forEach((btn) => {
        btn.addEventListener('click', async () => {
          const row = btn.closest('.kernel-history-row');
          const keyId = row?.getAttribute('data-id');
          if (!keyId) return;
          const password = window.prompt('Kernel password');
          if (!password) return;
          try {
            const data = await kernelFetch('/api/kernel/key/reveal', { id: keyId, password });
            const keyEl = row?.querySelector('.kernel-history-key');
            if (keyEl) {
              keyEl.textContent = data.key || '';
            } else {
              const span = document.createElement('div');
              span.className = 'kernel-history-key';
              span.textContent = data.key || '';
              row?.appendChild(span);
            }
            const copyBtn = row?.querySelector('[data-action="copy"]');
            if (copyBtn) copyBtn.disabled = !data.key;
          } catch (e) {
            alert(e.message || 'Reveal failed');
          }
        });
      });

      host.querySelectorAll('[data-action="copy"]').forEach((btn) => {
        btn.addEventListener('click', async () => {
          const row = btn.closest('.kernel-history-row');
          const key = row?.querySelector('.kernel-history-key')?.textContent || '';
          if (!key) return;
          try {
            if (navigator.clipboard && navigator.clipboard.writeText) {
              await navigator.clipboard.writeText(key);
            } else {
              const tmp = document.createElement('input');
              tmp.value = key;
              document.body.appendChild(tmp);
              tmp.select();
              document.execCommand('copy');
              tmp.remove();
            }
            alert('Key copied.');
          } catch {
            alert('Copy failed.');
          }
        });
      });
    } catch (e) {
      host.textContent = e.message || 'Unable to load history.';
    }
  }

  loadStatus().then(() => {
    if (kernelLoggedIn) {
      renderWelcome();
    } else {
      renderLogin();
    }
  });
})();
