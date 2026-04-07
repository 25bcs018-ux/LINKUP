(() => {
  const usernameInput = document.getElementById('username');
  const helper = document.getElementById('usernameHelper');
  const sugBox = document.getElementById('usernameSuggestions');
  const sugList = document.getElementById('usernameSuggestionsList');
  const form = usernameInput?.closest('form');
  const csrfToken = (document.querySelector('meta[name="csrf-token"]')?.getAttribute('content') || '').trim();

  if (!usernameInput || !helper) return;

  function setHelper(text, kind = '') {
    helper.textContent = text || '';
    helper.classList.remove('good', 'bad');
    if (kind) helper.classList.add(kind);
  }

  function clearSuggestions() {
    if (sugBox) sugBox.style.display = 'none';
    if (sugList) sugList.innerHTML = '';
  }

  function renderSuggestions(suggestions) {
    if (!sugBox || !sugList) return;
    sugList.innerHTML = '';

    if (!Array.isArray(suggestions) || suggestions.length === 0) {
      sugBox.style.display = 'none';
      return;
    }

    for (const s of suggestions) {
      const btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'sug';
      btn.textContent = s;
      btn.addEventListener('click', () => {
        usernameInput.value = s;
        usernameInput.focus();
        clearSuggestions();
        debouncedCheck();
      });
      sugList.appendChild(btn);
    }

    sugBox.style.display = '';
  }

  async function checkUsername(raw) {
    const value = String(raw || '').trim();

    if (!value) {
      setHelper('');
      clearSuggestions();
      return { available: false, seed: '', suggestions: [] };
    }

    if (value.length < 3) {
      setHelper('Username must be at least 3 characters.', 'bad');
      clearSuggestions();
      return { available: false, seed: '', suggestions: [] };
    }

    if (value.length > 15) {
      setHelper('Username must be 15 characters or less.', 'bad');
      clearSuggestions();
      return { available: false, seed: '', suggestions: [] };
    }

    try {
      const res = await fetch('/api/username/suggestions', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...(csrfToken ? { 'X-CSRF-Token': csrfToken } : {}) },
        body: JSON.stringify({ username: value })
      });

      if (!res.ok) {
        setHelper('Unable to check username right now.', 'bad');
        clearSuggestions();
        return { available: false, seed: '', suggestions: [] };
      }

      const data = await res.json();
      const seed = (data.seed || '').trim();

      if (!seed) {
        setHelper('Try letters/numbers only.', 'bad');
        clearSuggestions();
        return { available: false, seed: '', suggestions: [] };
      }

      if (data.available) {
        setHelper(`Available: ${seed}`, 'good');
        clearSuggestions();
        return { available: true, seed, suggestions: [] };
      }

      setHelper('That username is taken. Try one of these:', 'bad');
      renderSuggestions(data.suggestions || []);
      return { available: false, seed, suggestions: data.suggestions || [] };
    } catch {
      setHelper('Unable to check username right now.', 'bad');
      clearSuggestions();
      return { available: false, seed: '', suggestions: [] };
    }
  }

  let lastResult = { available: false, seed: '', suggestions: [] };
  let timer = null;
  function debouncedCheck() {
    if (timer) window.clearTimeout(timer);
    timer = window.setTimeout(async () => {
      lastResult = await checkUsername(usernameInput.value);
    }, 250);
  }

  usernameInput.addEventListener('input', debouncedCheck);
  usernameInput.addEventListener('blur', () => {
    // quick check on blur, no debounce delay
    checkUsername(usernameInput.value).then((r) => (lastResult = r));
  });

  // If server rendered suggestions, make them clickable as well.
  document.querySelectorAll('[data-suggest]').forEach((btn) => {
    btn.addEventListener('click', () => {
      const v = btn.getAttribute('data-suggest') || '';
      if (!v) return;
      usernameInput.value = v;
      usernameInput.focus();
      debouncedCheck();
    });
  });

  if (form) {
    form.addEventListener('submit', async (e) => {
      // If we already know it's taken, block submit and keep the user on the page.
      // Otherwise, do a last-second check.
      const current = String(usernameInput.value || '').trim();
      if (!current) return;

      if (lastResult.seed && !lastResult.available) {
        e.preventDefault();
        usernameInput.focus();
        return;
      }

      const r = await checkUsername(current);
      lastResult = r;
      if (!r.available) {
        e.preventDefault();
        usernameInput.focus();
      }
    });
  }
})();
