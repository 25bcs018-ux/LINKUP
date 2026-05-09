(() => {
  const novaFab = document.getElementById('novaFab');
  const novaPanel = document.getElementById('novaPanel');
  if (!novaFab || !novaPanel) return;

  const novaClose = document.getElementById('novaClose');
  const novaMessages = document.getElementById('novaMessages');
  const novaComposer = document.getElementById('novaComposer');
  const novaInput = document.getElementById('novaInput');
  const novaHero = document.getElementById('novaHero');
  const novaHeroTitle = document.getElementById('novaHeroTitle');
  const novaHeroSub = document.getElementById('novaHeroSub');
  const novaHeroHint = document.getElementById('novaHeroHint');
  const novaChips = document.getElementById('novaChips');

  const context = (document.body?.dataset?.novaContext || '').trim() || 'general';
  const stateKey = 'linkup_nova_open';
  const guestKey = 'linkup_nova_guest_history_v1';
  const guestMergeKey = 'linkup_nova_guest_merge_prompted_v1';
  let novaOpen = false;
  let novaPoll = null;
  let novaLastHash = '';
  let novaFirstLoad = true;
  let isGuestMode = false;

  const suggestions = {
    chat: {
      title: 'Ready to jump in?',
      sub: 'I can recap, suggest replies, or help you find features.',
      hint: 'Type /tour anytime',
      chips: ['Give me a quick tour', 'Summarize this chat', 'Suggest a reply', 'Open LinkUp Secure', 'Open Creator']
    },
    dashboard: {
      title: 'What should we do next?',
      sub: 'I can guide you to chats, settings, or secure mode.',
      hint: 'Say "help" or "tour"',
      chips: ['How do I start a chat?', 'Open LinkUp Secure', 'Open Creator', 'Show me tips']
    },
    front: {
      title: 'Welcome to LinkUp',
      sub: 'I can walk you through setup and answer questions.',
      hint: 'Ask me anything',
      chips: ['How does LinkUp work?', 'Show me onboarding', 'Open LinkUp Secure']
    },
    auth: {
      title: 'Need a hand?',
      sub: 'I can explain sign in, accounts, and privacy.',
      hint: 'Ask about login or registration',
      chips: ['Help me sign in', 'How do usernames work?', 'Privacy summary']
    },
    legal: {
      title: 'Quick policy helper',
      sub: 'I can summarize the key points in this page.',
      hint: 'Ask for a summary',
      chips: ['Summarize this page', 'What data is stored?', 'Open LinkUp Secure']
    },
    support: {
      title: 'Support buddy',
      sub: 'Tell me the issue and I will suggest next steps.',
      hint: 'Describe the problem',
      chips: ['Why can\'t I message someone?', 'How do I change my profile?', 'Open LinkUp Secure']
    },
    verify: {
      title: 'Email check-in',
      sub: 'I can help with verification or resend steps.',
      hint: 'Ask about OTP',
      chips: ['I did not get the OTP', 'How do I verify?', 'Open LinkUp Secure']
    },
    secure: {
      title: 'Secure mode guide',
      sub: 'I can explain LinkUp Secure workflows.',
      hint: 'Ask about secure chats',
      chips: ['What is LinkUp Secure?', 'Create a secure chat', 'Join a secure chat']
    },
    general: {
      title: 'Hi, I am NOVA',
      sub: 'I am your LinkUp buddy. Ask me anything.',
      hint: 'Type /tour anytime',
      chips: ['Give me a quick tour', 'Open LinkUp Secure', 'Open Creator']
    }
  };

  function escapeHtml(value) {
    return String(value || '')
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  function setHeroContent() {
    const preset = suggestions[context] || suggestions.general;
    if (novaHeroTitle) novaHeroTitle.textContent = preset.title;
    if (novaHeroSub) novaHeroSub.textContent = preset.sub;
    if (novaHeroHint) novaHeroHint.textContent = preset.hint;

    if (novaChips) {
      novaChips.innerHTML = '';
      preset.chips.forEach((text) => {
        const btn = document.createElement('button');
        btn.className = 'nova-chip';
        btn.type = 'button';
        btn.setAttribute('data-nova-chip', text);
        btn.textContent = text;
        novaChips.appendChild(btn);
      });
    }
  }

  function computeDock() {
    if (context === 'chat') {
      return window.innerWidth < 900 ? 'right' : 'left';
    }
    if (context === 'secure') {
      return 'right';
    }
    return window.innerWidth < 720 ? 'right' : 'right';
  }

  function applyDock() {
    document.body?.setAttribute('data-nova-dock', computeDock());
  }

  function setNovaOpen(open) {
    novaOpen = !!open;
    if (novaPanel) novaPanel.classList.toggle('open', novaOpen);
    if (novaPanel) novaPanel.setAttribute('aria-hidden', novaOpen ? 'false' : 'true');
    document.body?.classList.toggle('nova-panel-open', novaOpen);
    try { localStorage.setItem(stateKey, novaOpen ? '1' : '0'); } catch (_) {}
    if (novaOpen) {
      try { novaInput?.focus(); } catch (_) {}
      refreshNovaMessages();
      scheduleNovaPoll();
    }
  }

  window.NovaWidget = {
    open: () => setNovaOpen(true),
    close: () => setNovaOpen(false),
    submit: (text) => submitNova(text)
  };

  function loadGuestHistory() {
    try {
      const raw = localStorage.getItem(guestKey);
      const data = raw ? JSON.parse(raw) : [];
      return Array.isArray(data) ? data : [];
    } catch (_) {
      return [];
    }
  }

  function saveGuestHistory(list) {
    try { localStorage.setItem(guestKey, JSON.stringify(list || [])); } catch (_) {}
  }

  function addGuestMessage(role, content) {
    const list = loadGuestHistory();
    list.push({ role, content: String(content || '').slice(0, 1600), ts: Date.now() });
    while (list.length > 24) list.shift();
    saveGuestHistory(list);
  }

  function guestHistoryForRender() {
    const list = loadGuestHistory();
    return list.map((item) => ({
      sender_username: item.role === 'user' ? 'You' : 'NOVA',
      content: item.content || ''
    }));
  }

  function renderNovaMessages(data) {
    if (!novaMessages) return;
    const rows = [];
    const items = Array.isArray(data) ? data : [];
    for (const m of items) {
      const isMine = (String(m.sender_username || '').toLowerCase() !== 'nova');
      const side = isMine ? 'out' : 'in';
      const name = isMine ? 'You' : 'NOVA';
      const content = (m.deleted_for_all ? '[Deleted]' : (m.content || '')).trim();
      const safe = escapeHtml(content || '');
      rows.push(
        `<div class="nova-msg ${side}">
          <div class="nova-bubble">
            <div class="nova-line"><strong>${escapeHtml(name)}</strong></div>
            <div class="nova-text">${safe || '<span class="nova-muted">(empty)</span>'}</div>
          </div>
        </div>`
      );
    }
    if (novaHero) novaHero.classList.toggle('hidden', rows.length > 0);
    novaMessages.innerHTML = rows.length ? rows.join('') : '<div class="nova-hint">Say hi to NOVA.</div>';
    try {
      const body = document.getElementById('novaBody');
      if (body) body.scrollTop = body.scrollHeight;
    } catch (_) {}
  }

  function getCsrfToken() {
    return (document.querySelector('meta[name="csrf-token"]')?.getAttribute('content') || '').trim();
  }

  async function refreshNovaMessages() {
    if (!novaOpen || !novaMessages) return false;
    if (isGuestMode) {
      renderNovaMessages(guestHistoryForRender());
      return true;
    }
    let changed = false;
    if (novaFirstLoad) {
      novaFirstLoad = false;
      novaMessages.innerHTML = '<div class="nova-hint">Loading...</div>';
    }
    try {
      const res = await fetch(`/api/messages/${encodeURIComponent('NOVA')}`);
      if (!res.ok) {
        const d = await res.json().catch(() => ({}));
        const err = d.error || 'NOVA unavailable';
        if (String(err).toLowerCase() === 'not_authenticated') {
          const guest = loadGuestHistory();
          if (guest.length) {
            isGuestMode = true;
            renderNovaMessages(guestHistoryForRender());
            return true;
          }
        }
        const hint = err === 'not_authenticated'
          ? 'Sign in to chat with NOVA.'
          : escapeHtml(err);
        novaMessages.innerHTML = `<div class="nova-hint">${hint}</div>`;
        return false;
      }
      const data = await res.json();
      const h = JSON.stringify(data || []);
      if (h !== novaLastHash) {
        novaLastHash = h;
        renderNovaMessages(data);
        changed = true;
      }
      return changed;
    } catch (_) {
      novaMessages.innerHTML = '<div class="nova-hint">Network error</div>';
      return false;
    }
  }

  function scheduleNovaPoll() {
    if (!novaOpen) return;
    if (novaPoll) clearTimeout(novaPoll);
    novaPoll = setTimeout(async () => {
      const changed = await refreshNovaMessages();
      if (!changed) scheduleNovaPoll();
    }, 1100);
  }

  function appendLocalMessage(text, fromNova = true) {
    if (!novaMessages) return;
    const side = fromNova ? 'in' : 'out';
    const name = fromNova ? 'NOVA' : 'You';
    const safe = escapeHtml(text || '');
    const html = `
      <div class="nova-msg ${side}">
        <div class="nova-bubble">
          <div class="nova-line"><strong>${escapeHtml(name)}</strong></div>
          <div class="nova-text">${safe}</div>
        </div>
      </div>`;
    const wrapper = document.createElement('div');
    wrapper.innerHTML = html;
    novaMessages.appendChild(wrapper.firstElementChild);
  }

  function shouldHandleSecure(text) {
    const t = String(text || '').toLowerCase();
    if (!t.includes('secure')) return false;
    if (t.includes('linkup secure')) return true;
    return t.includes('open') || t.includes('launch') || t.includes('go to') || t.includes('enter');
  }

  function shouldHandleCreator(text) {
    const t = String(text || '').toLowerCase();
    if (!t.includes('creator') && !t.includes('studio')) return false;
    return t.includes('open') || t.includes('launch') || t.includes('go to') || t.includes('enter') || t.includes('creator');
  }

  function handleNovaCommand(text) {
    const raw = String(text || '').trim();
    if (!raw) return false;

    if (shouldHandleSecure(raw)) {
      const ok = window.confirm('Open LinkUp Secure? I will log you out here first.');
      if (!ok) {
        appendLocalMessage('No problem. Staying here.');
        return true;
      }
      appendLocalMessage('Opening LinkUp Secure now. Logging you out here for safety.');
      window.open('/linkup-secure', '_blank', 'noopener');
      window.location.href = '/logout';
      return true;
    }

    if (shouldHandleCreator(raw)) {
      appendLocalMessage('Opening Creator Studio.', true);
      window.open('/creator', '_blank', 'noopener');
      return true;
    }

    return false;
  }

  async function sendNovaMessage(text) {
    const content = (text || '').trim();
    if (!content) return;
    const headers = { 'Content-Type': 'application/json' };
    const csrf = getCsrfToken();
    if (csrf) headers['X-CSRF-Token'] = csrf;
    const res = await fetch(`/api/messages/${encodeURIComponent('NOVA')}`,
      {
        method: 'POST',
        headers,
        body: JSON.stringify({ content })
      }
    );
    if (res.status === 401) {
      return sendNovaGuestMessage(content);
    }
    if (!res.ok) {
      const d = await res.json().catch(() => ({}));
      const err = d.error || 'Failed';
      if (String(err).toLowerCase() === 'not_authenticated') {
        return sendNovaGuestMessage(content);
      }
      throw new Error(err);
    }
    isGuestMode = false;
  }

  async function sendNovaGuestMessage(content) {
    addGuestMessage('user', content);
    const history = loadGuestHistory().slice(-8).map((item) => ({
      role: item.role,
      content: item.content
    }));
    const res = await fetch('/api/nova/guest', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ content, history })
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      throw new Error(data.error || 'Guest mode failed');
    }
    addGuestMessage('assistant', data.reply || '');
    isGuestMode = true;
    renderNovaMessages(guestHistoryForRender());
    return true;
  }

  async function submitNova(text) {
    const submitted = (text || '').trim();
    if (!submitted) return;

    if (submitted === '/merge' || submitted.toLowerCase() === 'merge guest') {
      try {
        await mergeGuestHistory();
      } catch (e) {
        appendLocalMessage(e.message || 'Merge failed.', true);
      } finally {
        if (novaInput) novaInput.value = '';
      }
      return;
    }

    if (handleNovaCommand(submitted)) {
      if (novaInput) novaInput.value = '';
      return;
    }

    const sendBtn = novaComposer?.querySelector?.('.nova-send');
    try {
      if (sendBtn) sendBtn.disabled = true;
      if (novaInput) novaInput.value = '';
      await sendNovaMessage(submitted);
      await refreshNovaMessages();
    } catch (e) {
      const msg = e.message || 'NOVA failed. Try again.';
      appendLocalMessage(msg, true);
    } finally {
      if (sendBtn) sendBtn.disabled = false;
    }
  }

  function restoreOpenState() {
    try {
      const saved = localStorage.getItem(stateKey);
      if (saved === '1') {
        setNovaOpen(true);
      }
    } catch (_) {}
  }

  async function checkGuestMerge() {
    const guest = loadGuestHistory();
    if (!guest.length) return;
    try {
      const res = await fetch('/api/account/me');
      if (!res.ok) return;
    } catch (_) {
      return;
    }

    try {
      if (localStorage.getItem(guestMergeKey) === '1') return;
      localStorage.setItem(guestMergeKey, '1');
    } catch (_) {}

    setNovaOpen(true);
    appendLocalMessage('I found your guest NOVA chat. Type /merge to import it.', true);
  }

  async function mergeGuestHistory() {
    const guest = loadGuestHistory();
    if (!guest.length) {
      appendLocalMessage('No guest chat found to merge.', true);
      return;
    }
    const summary = guest
      .map((m) => `${m.role === 'user' ? 'You' : 'NOVA'}: ${m.content}`)
      .join('\n');
    const payload = `Merge my guest NOVA chat:\n${summary}`;
    await sendNovaMessage(payload);
    saveGuestHistory([]);
    isGuestMode = false;
    appendLocalMessage('Merged your guest notes into your account.', true);
  }

  novaFab.addEventListener('click', () => setNovaOpen(true));
  novaClose?.addEventListener('click', () => setNovaOpen(false));

  document.addEventListener('keydown', (ev) => {
    if (ev.key === 'Escape' && novaOpen) setNovaOpen(false);
  });

  novaComposer?.addEventListener('submit', async (ev) => {
    ev.preventDefault();
    await submitNova(novaInput?.value || '');
  });

  novaChips?.addEventListener('click', async (ev) => {
    const target = ev.target;
    if (!(target instanceof HTMLElement)) return;
    const v = target.getAttribute('data-nova-chip');
    if (!v) return;
    await submitNova(v);
  });

  setHeroContent();
  applyDock();
  window.addEventListener('resize', applyDock);
  restoreOpenState();
  checkGuestMerge();
})();
