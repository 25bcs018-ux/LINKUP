(() => {
  const buddyKey = 'linkup_nova_buddy';
  const context = (document.body?.dataset?.novaContext || '').trim() || 'general';
  const guestContexts = new Set(['front', 'auth', 'legal', 'support', 'verify', 'secure', 'general']);
  const buddyContexts = new Set([...guestContexts, 'chat', 'dashboard']);
  const isGuestContext = guestContexts.has(context);
  const reducedMotion = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  let buddyEl = null;
  let bubbleEl = null;
  let bubbleThreadEl = null;
  let bubbleFormEl = null;
  let bubbleInputEl = null;
  let bubbleSendEl = null;
  let moveTimer = null;
  let idleTimer = null;
  let lastActiveAt = Date.now();
  let typingTimer = null;
  let typingIndex = 0;
  let listenersBound = false;
  let driftFrame = null;
  let targetPoint = null;
  let currentPoint = { x: 0, y: 0 };
  let nextTargetAt = 0;
  let greetingDone = false;
  let lastNovaMessageId = 0;
  let buddyThread = [];

  const script = {
    chat: {
      greet: [
        'Hey, I am Nova. Need help with this chat?',
        'I can summarize or suggest a reply if you want.',
        'Ping me any time. I am right here.'
      ],
      idle: [
        'Want a quick recap of this chat?',
        'I can draft a reply if you are stuck.',
        'Need to open LinkUp Secure? Just ask.'
      ]
    },
    dashboard: {
      greet: [
        'Welcome back. Want to open chats or settings?',
        'I can help you get to what you need fast.'
      ],
      idle: [
        'Need help finding a feature?',
        'Want me to explain what is new here?'
      ]
    },
    front: {
      greet: [
        'Hi, I am Nova. Want a quick tour?',
        'I can guide you to sign in or create an account.'
      ],
      idle: [
        'Questions about LinkUp? Ask me.',
        'Want to see what LinkUp Secure is?'
      ]
    },
    auth: {
      greet: [
        'Need help signing in or creating an account?',
        'If something is confusing, ask me.'
      ],
      idle: [
        'I can explain login, usernames, and privacy.',
        'Need me to walk you through setup?'
      ]
    },
    legal: {
      greet: [
        'Want a quick summary of this page?',
        'I can highlight the key points.'
      ],
      idle: [
        'Ask me about privacy or data handling.',
        'Need the short version? I can summarize.'
      ]
    },
    support: {
      greet: [
        'Tell me the issue and I will suggest next steps.',
        'I am here if you need help.'
      ],
      idle: [
        'Want troubleshooting steps?',
        'I can help you draft a support ticket.'
      ]
    },
    verify: {
      greet: [
        'I can help with the OTP or verification steps.',
        'Need the code resent? I can guide you.'
      ],
      idle: [
        'If the OTP did not arrive, ask me what to do next.'
      ]
    },
    secure: {
      greet: [
        'Welcome to LinkUp Secure. Want a quick guide?',
        'I can explain create vs join.'
      ],
      idle: [
        'Need help setting up a secure chat?',
        'Ask me anything about Secure mode.'
      ]
    },
    general: {
      greet: [
        'Hi, I am Nova. Need help with anything?',
        'I can help you move around the app.'
      ],
      idle: [
        'Ask me anything. I am here.'
      ]
    }
  };

  const roasts = [
    'Ok, that was a choice. Want the smart version?',
    'Bold move. I respect the chaos.',
    'You are one click away from a better option.',
    'Let me guess, you clicked the hard way again.',
    'I can fix it before you break it again.'
  ];

  function isBuddyEnabled() {
    try {
      const stored = (localStorage.getItem(buddyKey) || '').trim();
      if (stored === '0' || stored === 'off' || stored === 'false') return false;
      if (stored === '1' || stored === 'on' || stored === 'true') return true;
    } catch (_) {}
    return true;
  }

  function persistBuddyEnabled(on) {
    try { localStorage.setItem(buddyKey, on ? '1' : '0'); } catch (_) {}
    document.body?.setAttribute('data-nova-buddy', on ? 'on' : 'off');
  }

  function cleanupBuddy() {
    if (moveTimer) window.clearInterval(moveTimer);
    if (idleTimer) window.clearInterval(idleTimer);
    if (typingTimer) window.clearInterval(typingTimer);
    if (driftFrame) window.cancelAnimationFrame(driftFrame);
    moveTimer = null;
    idleTimer = null;
    typingTimer = null;
    driftFrame = null;
    targetPoint = null;
    if (buddyEl) buddyEl.remove();
    buddyEl = null;
    bubbleEl = null;
    bubbleTextEl = null;
    bubbleFormEl = null;
    bubbleInputEl = null;
    bubbleSendEl = null;
  }

  function createBuddy() {
    if (buddyEl) return;
    buddyEl = document.createElement('div');
    buddyEl.className = 'nova-buddy';
    buddyEl.innerHTML = `
      <button class="nova-buddy-face" type="button" aria-label="Talk to Nova">
        <span class="nova-ai" aria-hidden="true"></span>
        <span class="nova-face" aria-hidden="true">
          <span class="eye eye-left"></span>
          <span class="eye eye-right"></span>
          <span class="mouth"></span>
        </span>
      </button>
      <div class="nova-buddy-bubble">
        <div class="nova-buddy-thread"></div>
        <form class="nova-buddy-form" autocomplete="off">
          <input class="nova-buddy-input" type="text" placeholder="Ask Nova..." />
          <button class="nova-buddy-send" type="submit">Send</button>
        </form>
      </div>
    `;
    document.body.appendChild(buddyEl);
    bubbleEl = buddyEl.querySelector('.nova-buddy-bubble');
    bubbleThreadEl = buddyEl.querySelector('.nova-buddy-thread');
    bubbleFormEl = buddyEl.querySelector('.nova-buddy-form');
    bubbleInputEl = buddyEl.querySelector('.nova-buddy-input');
    bubbleSendEl = buddyEl.querySelector('.nova-buddy-send');
    const faceBtn = buddyEl.querySelector('.nova-buddy-face');
    faceBtn?.addEventListener('click', () => {
      toggleBuddyTalk();
    });
    bubbleFormEl?.addEventListener('submit', async (ev) => {
      ev.preventDefault();
      await submitBuddyMessage();
    });
  }

  function markActivity() {
    lastActiveAt = Date.now();
  }

  function getScript() {
    return script[context] || script.general;
  }

  function pickMessage(kind) {
    const list = (getScript()[kind] || getScript().greet || []).filter(Boolean);
    if (!list.length) return '';
    const wantsRoast = Math.random() < 0.22 && roasts.length > 0;
    if (wantsRoast) return roasts[Math.floor(Math.random() * roasts.length)];
    return list[Math.floor(Math.random() * list.length)];
  }

  function showBubble(text, holdMs = 4200) {
    if (!bubbleEl || !bubbleThreadEl || !text) return;
    bubbleEl.classList.add('is-visible');
    addThreadMessage('nova', text);
    window.setTimeout(() => {
      if (buddyEl?.classList.contains('talk-open')) return;
      bubbleEl.classList.remove('is-visible');
    }, holdMs);
  }

  function escapeHtml(value) {
    return String(value || '')
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  function renderThread() {
    if (!bubbleThreadEl) return;
    const rows = buddyThread.map((item) => {
      const side = item.role === 'user' ? 'you' : 'them';
      const thinking = item.thinking ? 'thinking' : '';
      return `<div class="nova-bubble-msg ${side} ${thinking}">${escapeHtml(item.content || '')}</div>`;
    });
    bubbleThreadEl.innerHTML = rows.join('');
    bubbleThreadEl.scrollTop = bubbleThreadEl.scrollHeight;
  }

  function addThreadMessage(role, content, opts = {}) {
    const entry = {
      role,
      content: String(content || ''),
      thinking: Boolean(opts.thinking)
    };
    buddyThread.push(entry);
    while (buddyThread.length > 12) buddyThread.shift();
    renderThread();
    return buddyThread.length - 1;
  }

  function updateThreadMessage(index, content) {
    if (!buddyThread[index]) return;
    buddyThread[index].content = String(content || '');
    buddyThread[index].thinking = false;
    renderThread();
  }

  function toggleBuddyTalk(forceOpen) {
    if (!buddyEl || !bubbleEl) return;
    const open = typeof forceOpen === 'boolean' ? forceOpen : !buddyEl.classList.contains('talk-open');
    buddyEl.classList.toggle('talk-open', open);
    bubbleEl.classList.toggle('is-visible', open);
    if (open) {
      if (!buddyThread.length) {
        addThreadMessage('nova', pickMessage('greet') || 'Talk to me.');
      }
      bubbleInputEl?.focus();
    }
  }

  async function submitBuddyMessage() {
    const value = (bubbleInputEl?.value || '').trim();
    if (!value) return;
    if (bubbleSendEl) bubbleSendEl.disabled = true;
    const thinkingIndex = addThreadMessage('nova', 'Thinking...', { thinking: true });
    try {
      if (bubbleInputEl) bubbleInputEl.value = '';

      if (isGuestContext) {
        const reply = respondGuestBuddy(value);
        updateThreadMessage(thinkingIndex, reply);
        return;
      }

      const headers = { 'Content-Type': 'application/json' };
      const csrf = (document.querySelector('meta[name="csrf-token"]')?.getAttribute('content') || '').trim();
      if (csrf) headers['X-CSRF-Token'] = csrf;
      const res = await fetch(`/api/messages/${encodeURIComponent('NOVA')}`, {
        method: 'POST',
        headers,
        body: JSON.stringify({ content: value })
      });
      if (res.status === 401) {
        const reply = await submitGuestMessage(value);
        updateThreadMessage(thinkingIndex, reply);
        return;
      }
      if (!res.ok) {
        const d = await res.json().catch(() => ({}));
        throw new Error(d.error || 'Failed');
      }
      const reply = await waitForNovaReply();
      updateThreadMessage(thinkingIndex, reply || 'Sent. I will reply soon.');
    } catch (e) {
      updateThreadMessage(thinkingIndex, e.message || 'Something went wrong.');
    } finally {
      if (bubbleSendEl) bubbleSendEl.disabled = false;
    }
  }

  function respondGuestBuddy(text) {
    const t = String(text || '').toLowerCase().trim();
    const replies = [
      {
        test: (v) => v.includes('what is linkup') || v.includes('what is link up') || v.includes('linkup?'),
        reply: 'LinkUp is a fast, simple chat app for everyday conversations.'
      },
      {
        test: (v) => v.includes('create') && v.includes('account'),
        reply: 'Tap "Create account" and fill in a username, email, and password.'
      },
      {
        test: (v) => v.includes('sign in') || v.includes('login'),
        reply: 'Use your username or email and password to sign in.'
      },
      {
        test: (v) => v.includes('privacy'),
        reply: 'You can read the privacy summary on the Privacy page.'
      },
      {
        test: (v) => v.includes('terms') || v.includes('policy'),
        reply: 'The Terms page has the key rules and usage guidelines.'
      },
      {
        test: (v) => v.includes('secure'),
        reply: 'LinkUp Secure lets you create or join a protected chat space.'
      },
      {
        test: (v) => v.includes('creator'),
        reply: 'Creator is the studio for layouts and visual changes.'
      },
      {
        test: (v) => v.includes('support') || v.includes('help'),
        reply: 'Open Support to report an issue or get troubleshooting steps.'
      }
    ];
    const matched = replies.find((entry) => entry.test(t));
    if (matched) return matched.reply;
    return 'I am in guest mode. Ask about LinkUp, login, accounts, privacy, or secure mode.';
  }

  async function submitGuestMessage(content) {
    const res = await fetch('/api/nova/guest', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ content })
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      throw new Error(data.error || 'Guest mode failed');
    }
    return data.reply || 'Sent.';
  }

  async function waitForNovaReply(maxWaitMs = 6000, intervalMs = 500) {
    const start = Date.now();
    while ((Date.now() - start) < maxWaitMs) {
      const list = await fetchNovaMessagesSince();
      const reply = extractNovaReply(list);
      if (reply) return reply;
      await new Promise((resolve) => setTimeout(resolve, intervalMs));
    }
    return '';
  }

  async function fetchNovaMessagesSince() {
    try {
      const res = await fetch(`/api/messages/${encodeURIComponent('NOVA')}?since_id=${lastNovaMessageId || 0}`);
      if (!res.ok) return [];
      const data = await res.json().catch(() => ([]));
      if (!Array.isArray(data)) return [];
      data.forEach((m) => {
        const id = Number(m?.id || 0);
        if (id > lastNovaMessageId) lastNovaMessageId = id;
      });
      return data;
    } catch (_) {
      return [];
    }
  }

  function extractNovaReply(list) {
    if (!Array.isArray(list) || !list.length) return '';
    const last = [...list].reverse().find((m) => String(m?.sender_username || '').toLowerCase() === 'nova');
    return last?.content ? String(last.content) : '';
  }

  function rectIntersectsViewport(rect) {
    const vw = window.innerWidth;
    const vh = window.innerHeight;
    return !(rect.right < 0 || rect.left > vw || rect.bottom < 0 || rect.top > vh);
  }

  function expandRect(rect, pad) {
    const p = Number(pad || 0);
    return {
      left: rect.left - p,
      top: rect.top - p,
      right: rect.right + p,
      bottom: rect.bottom + p,
      width: rect.width + p * 2,
      height: rect.height + p * 2
    };
  }

  function getAvoidRects() {
    const selectors = [
      '[data-nova-avoid]',
      '.topbar',
      '.sidebar',
      '.composer',
      '#messages .bubble',
      '#messages .daysep',
      '#messages .hint',
      '#messages .empty',
      '.chat-loader',
      '.page-loader',
      '.ghost-shell'
    ];
    const nodes = Array.from(document.querySelectorAll(selectors.join(',')));
    return nodes
      .map((node) => node.getBoundingClientRect())
      .filter((rect) => rect.width > 0 && rect.height > 0 && rectIntersectsViewport(rect))
      .map((rect) => expandRect(rect, 8));
  }

  function rectsOverlap(a, b) {
    return !(a.right < b.left || a.left > b.right || a.bottom < b.top || a.top > b.bottom);
  }

  function getCandidatePoints() {
    const vw = window.innerWidth;
    const vh = window.innerHeight;
    const pad = 18;
    const size = 88;
    const topSafe = 90;
    const bottomSafe = Math.max(140, vh - 220);
    return [
      { x: Math.max(pad, vw * 0.15), y: Math.max(topSafe, vh * 0.2) },
      { x: Math.max(pad, vw * 0.2), y: Math.max(topSafe, vh * 0.45) },
      { x: Math.max(pad, vw * 0.25), y: Math.max(topSafe, vh * 0.7) },
      { x: vw - size - pad, y: topSafe },
      { x: vw - size - pad, y: Math.max(topSafe, vh * 0.35) },
      { x: vw - size - pad, y: bottomSafe },
      { x: Math.max(pad, vw * 0.45), y: Math.max(topSafe, vh * 0.3) },
      { x: Math.max(pad, vw * 0.55), y: Math.max(topSafe, vh * 0.55) },
      { x: pad, y: topSafe + 20 },
      { x: pad, y: bottomSafe }
    ];
  }

  function getBuddySize() {
    const rect = buddyEl?.getBoundingClientRect();
    const size = rect && rect.width ? rect.width : 88;
    return Math.max(68, Math.min(120, size));
  }

  function getViewportBounds(size) {
    const pad = 12;
    const vw = window.innerWidth;
    const vh = window.innerHeight;
    const maxX = Math.max(pad, vw - size - pad);
    const maxY = Math.max(pad, vh - size - pad);
    return { minX: pad, minY: pad, maxX, maxY };
  }

  function clampPoint(point, size) {
    const bounds = getViewportBounds(size);
    return {
      x: Math.max(bounds.minX, Math.min(bounds.maxX, point.x)),
      y: Math.max(bounds.minY, Math.min(bounds.maxY, point.y))
    };
  }

  function pickSafePoint() {
    const avoid = getAvoidRects();
    const size = getBuddySize();
    const bounds = getViewportBounds(size);
    for (let i = 0; i < 32; i += 1) {
      const x = bounds.minX + Math.random() * (bounds.maxX - bounds.minX || 1);
      const y = bounds.minY + Math.random() * (bounds.maxY - bounds.minY || 1);
      const rect = { left: x, top: y, right: x + size, bottom: y + size };
      const hit = avoid.some((box) => rectsOverlap(rect, box));
      if (!hit) return { x, y };
    }
    const points = getCandidatePoints();
    return clampPoint(points[Math.floor(Math.random() * points.length)], size);
  }

  function constrainBuddyPosition() {
    if (!buddyEl) return;
    const size = getBuddySize();
    if (currentPoint) currentPoint = clampPoint(currentPoint, size);
    if (targetPoint) targetPoint = clampPoint(targetPoint, size);
    buddyEl.style.transform = `translate3d(${Math.round(currentPoint.x)}px, ${Math.round(currentPoint.y)}px, 0)`;
  }

  function moveBuddy() {
    if (!buddyEl) return;
    const point = pickSafePoint();
    currentPoint = { x: point.x, y: point.y };
    buddyEl.style.transform = `translate3d(${Math.round(point.x)}px, ${Math.round(point.y)}px, 0)`;
    buddyEl.setAttribute('data-side', point.x > window.innerWidth * 0.5 ? 'right' : 'left');
  }

  function driftStep(now) {
    if (!buddyEl || reducedMotion) return;
    if (!targetPoint || now >= nextTargetAt) {
      targetPoint = pickSafePoint();
      nextTargetAt = now + 9000 + Math.random() * 4000;
    }
    const ease = 0.02;
    currentPoint.x += (targetPoint.x - currentPoint.x) * ease;
    currentPoint.y += (targetPoint.y - currentPoint.y) * ease;
    buddyEl.style.transform = `translate3d(${Math.round(currentPoint.x)}px, ${Math.round(currentPoint.y)}px, 0)`;
    buddyEl.setAttribute('data-side', currentPoint.x > window.innerWidth * 0.5 ? 'right' : 'left');
    driftFrame = window.requestAnimationFrame(driftStep);
  }

  function setupMovement() {
    moveBuddy();
    if (reducedMotion) return;
    if (moveTimer) window.clearInterval(moveTimer);
    if (driftFrame) window.cancelAnimationFrame(driftFrame);
    targetPoint = pickSafePoint();
    currentPoint = { x: targetPoint.x, y: targetPoint.y };
    nextTargetAt = performance.now() + 9000;
    driftFrame = window.requestAnimationFrame(driftStep);
    moveTimer = window.setInterval(() => moveBuddy(), 20000);
  }

  function setupIdleTalk() {
    if (idleTimer) window.clearInterval(idleTimer);
    idleTimer = window.setInterval(() => {
      const idleMs = Date.now() - lastActiveAt;
      if (idleMs > 20000) {
        showBubble(pickMessage('idle'));
        lastActiveAt = Date.now();
      }
    }, 8000);
  }

  function initBuddy() {
    if (!buddyContexts.has(context)) {
      persistBuddyEnabled(false);
      cleanupBuddy();
      return;
    }
    if (!isBuddyEnabled()) {
      persistBuddyEnabled(false);
      cleanupBuddy();
      return;
    }

    persistBuddyEnabled(true);
    createBuddy();
    setupMovement();
    setupIdleTalk();
    if (!listenersBound) {
      listenersBound = true;
      window.addEventListener('resize', constrainBuddyPosition);
      ['mousemove', 'keydown', 'touchstart', 'scroll'].forEach((evt) => {
        window.addEventListener(evt, markActivity, { passive: true });
      });
    }
    if (!greetingDone) {
      greetingDone = true;
      window.setTimeout(() => {
        showBubble(pickMessage('greet'));
      }, 900);
    }
  }

  window.NovaBuddy = {
    isEnabled: () => isBuddyEnabled(),
    setEnabled: (on) => {
      persistBuddyEnabled(!!on);
      if (on) {
        initBuddy();
      } else {
        cleanupBuddy();
      }
    }
  };

  initBuddy();
})();
