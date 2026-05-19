(() => {
  if (window.location.pathname === '/kernel') return;

  const path = window.location.pathname || '/';
  let pageKey = '';
  if (path.startsWith('/chats')) pageKey = 'chats';
  else if (path.startsWith('/dashboard')) pageKey = 'dashboard';
  else if (path.startsWith('/support') || path.startsWith('/linkup/support')) pageKey = 'support';
  else if (path.startsWith('/linkup/feedback')) pageKey = 'linkup_feedback';
  if (!pageKey) return;

  const styleId = 'kernelStyle';
  const scriptId = 'kernelScript';
  const localKey = `linkup_kernel_css:${pageKey}`;
  const localJsKey = `linkup_kernel_js:${pageKey}`;
  const kernelKeyMapKey = 'linkup_kernel_keys_v1';
  const visualFlagKey = 'linkup_kernel_visual';
  const kernelCsrfKey = 'linkup_kernel_csrf';
  const urlParams = new URLSearchParams(window.location.search || '');
  const forceDefault = urlParams.get('kernel_default') === '1';

  function applyCss(css) {
    let el = document.getElementById(styleId);
    if (!el) {
      el = document.createElement('style');
      el.id = styleId;
      document.head.appendChild(el);
    }
    el.textContent = css || '';
  }

  function applyJs(js) {
    let el = document.getElementById(scriptId);
    if (!el) {
      el = document.createElement('script');
      el.id = scriptId;
      document.body.appendChild(el);
    }
    el.textContent = js || '';
  }

  function applyLocalJs(js) {
    const existing = document.getElementById('kernelLocalScript');
    if (existing) existing.remove();
    if (!js) return;
    const el = document.createElement('script');
    el.id = 'kernelLocalScript';
    el.textContent = js;
    document.body.appendChild(el);
  }

  function readLocalCss() {
    try { return localStorage.getItem(localKey) || ''; } catch { return ''; }
  }

  function writeLocalCss(css) {
    try { localStorage.setItem(localKey, css || ''); } catch {}
  }

  function readLocalJs() {
    try { return localStorage.getItem(localJsKey) || ''; } catch { return ''; }
  }

  function writeLocalJs(js) {
    try { localStorage.setItem(localJsKey, js || ''); } catch {}
  }

    function pushHistory(needsReload) {
      undoStack.push({
        css: readLocalCss(),
        js: readLocalJs(),
        needsReload: !!needsReload
      });
      if (undoStack.length > undoLimit) undoStack.shift();
    }

    function restoreSnapshot(snapshot) {
      if (!snapshot) return;
      writeLocalCss(snapshot.css || '');
      applyCss(snapshot.css || '');
      writeLocalJs(snapshot.js || '');
      applyLocalJs(snapshot.js || '');
    }

    function undoLast() {
      const snapshot = undoStack.pop();
      if (!snapshot) {
        alert('Nothing to undo.');
        return;
      }
      restoreSnapshot(snapshot);
      if (snapshot.needsReload) window.location.reload();
    }

  function isVisualMode() {
    try { return localStorage.getItem(visualFlagKey) === '1'; } catch { return false; }
  }

  function readKernelKeyMap() {
    try {
      const raw = localStorage.getItem(kernelKeyMapKey);
      const data = raw ? JSON.parse(raw) : {};
      return data && typeof data === 'object' ? data : {};
    } catch {
      return {};
    }
  }

  if (!forceDefault) {
    try {
      const local = localStorage.getItem(localKey) || '';
      if (local) applyCss(local);
    } catch {}

    try {
      const localJs = localStorage.getItem(localJsKey) || '';
      if (localJs) applyLocalJs(localJs);
    } catch {}

    const keyMap = readKernelKeyMap();
    const kernelKey = String(keyMap[pageKey] || '').trim();
    if (kernelKey) {
      fetch(`/api/kernel/key/apply?key=${encodeURIComponent(kernelKey)}&page=${encodeURIComponent(pageKey)}`)
        .then((res) => res.json().catch(() => ({})))
        .then((data) => {
          if (!data || !data.ok) return;
          if (data.css) applyCss(data.css);
          if (data.js) applyJs(data.js);
        })
        .catch(() => {});
    }
  }

  if (isVisualMode()) {
    initVisualEditor();
  }

  function initVisualEditor() {
    const csrf = (() => {
      try { return localStorage.getItem(kernelCsrfKey) || ''; } catch { return ''; }
    })();

    function kernelPost(url, payload) {
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

    const panel = document.createElement('div');
    panel.id = 'kernelEditorPanel';
    panel.innerHTML = `
      <div class="kernel-editor-header" id="kernelEditorDragHandle">
        <div>
          <div class="kernel-editor-eyebrow">Visual Studio</div>
          <strong>Kernel Editor</strong>
          <div class="kernel-editor-sub">Click to select, drag to move.</div>
        </div>
        <button type="button" id="kernelEditorExit" class="ghost">Exit</button>
      </div>
      <div class="kernel-editor-section">
        <div class="kernel-editor-row">
          <span>Selected</span>
          <span id="kernelEditorSelected">None</span>
        </div>
        <div class="kernel-editor-actions">
          <button type="button" id="kernelEditorMode" class="ghost">Mode: Select</button>
          <button type="button" id="kernelEditorUndo" class="ghost">Undo</button>
          <button type="button" id="kernelEditorClear" class="ghost">Clear selection</button>
          <button type="button" id="kernelEditorDelete" class="danger">Delete selected</button>
        </div>
        <div class="kernel-editor-sub" id="kernelEditorModeHint">Select mode: click to select. Interact mode: normal clicks, hold Alt to select.</div>
      </div>
      <div class="kernel-editor-section">
        <div class="kernel-editor-title">Text + style</div>
        <input id="kernelEditorText" placeholder="Rename text" />
        <div class="kernel-editor-grid">
          <input id="kernelEditorColor" placeholder="Text color" />
          <input id="kernelEditorBg" placeholder="Background" />
          <input id="kernelEditorFont" placeholder="Font size (px)" />
          <input id="kernelEditorRadius" placeholder="Radius (px)" />
          <input id="kernelEditorLeft" placeholder="Left (px)" />
          <input id="kernelEditorTop" placeholder="Top (px)" />
        </div>
        <div class="kernel-editor-actions">
          <button type="button" id="kernelEditorApplyText" class="ghost">Apply text</button>
          <button type="button" id="kernelEditorApplyStyle" class="primary">Apply style</button>
        </div>
      </div>
      <div class="kernel-editor-section">
        <div class="kernel-editor-title">Action</div>
        <select id="kernelEditorActionType">
          <option value="link">Link to URL/page</option>
          <option value="show_message">Show message</option>
          <option value="open_modal">Open modal by id</option>
          <option value="toggle_class">Toggle class on id</option>
        </select>
        <input id="kernelEditorActionValue" placeholder="URL or target id" />
        <input id="kernelEditorActionMessage" placeholder="Message text" />
        <input id="kernelEditorActionClass" placeholder="Class to toggle" />
        <button type="button" id="kernelEditorApplyAction" class="primary">Apply action</button>
      </div>
      <div class="kernel-editor-section">
        <div class="kernel-editor-title">Add button</div>
        <input id="kernelEditorNewText" placeholder="Button label" />
        <select id="kernelEditorNewActionType">
          <option value="link">Link to URL/page</option>
          <option value="show_message">Show message</option>
          <option value="open_modal">Open modal by id</option>
          <option value="toggle_class">Toggle class on id</option>
        </select>
        <input id="kernelEditorNewActionValue" placeholder="URL or target id" />
        <input id="kernelEditorNewActionMessage" placeholder="Message text" />
        <input id="kernelEditorNewActionClass" placeholder="Class to toggle" />
        <button type="button" id="kernelEditorAddButton" class="primary">Add button</button>
      </div>
      <div class="kernel-editor-section">
        <div class="kernel-editor-title">Publish key</div>
        <button type="button" id="kernelEditorPublish" class="primary">Save + generate key</button>
        <input id="kernelEditorKey" placeholder="Key will appear here" readonly />
        <button type="button" id="kernelEditorCopyKey" class="ghost" disabled>Copy key</button>
      </div>
      <div class="kernel-editor-footer">Edits save to local preview. Use Publish to generate a key.</div>
    `;

    const style = document.createElement('style');
    style.id = 'kernelEditorStyle';
    style.textContent = `
      :root {
        --kernel-panel-bg: #ffffff;
        --kernel-panel-ink: #0b1220;
        --kernel-panel-muted: rgba(15, 23, 42, 0.65);
        --kernel-panel-border: rgba(15, 23, 42, 0.2);
        --kernel-panel-accent: #0ea5a8;
        --kernel-panel-accent-2: #f97316;
        --kernel-panel-danger: #dc2626;
        --kernel-panel-ghost: #eef2f6;
      }
      #kernelEditorPanel {
        position: fixed;
        right: 16px;
        top: 16px;
        z-index: 99999;
        width: 360px;
        font-family: "Space Grotesk", "Satoshi", "Avenir Next", "Helvetica Neue", sans-serif;
        font-size: 12px;
        color: var(--kernel-panel-ink);
        background: var(--kernel-panel-bg);
        border: 1px solid var(--kernel-panel-border);
        box-shadow: 0 20px 60px rgba(15, 23, 42, 0.25);
        border-radius: 18px;
        padding: 14px;
        max-height: 78vh;
        overflow: auto;
        cursor: default;
        backdrop-filter: blur(10px);
      }
      #kernelEditorPanel input,
      #kernelEditorPanel select {
        width: 100%;
        border-radius: 12px;
        border: 1px solid rgba(15, 23, 42, 0.28);
        padding: 9px 12px;
        font-size: 12px;
        background: #ffffff;
        color: var(--kernel-panel-ink);
      }
      #kernelEditorPanel button {
        border-radius: 999px;
        border: 1px solid rgba(15, 23, 42, 0.3);
        background: #ffffff;
        color: var(--kernel-panel-ink);
        padding: 8px 14px;
        cursor: pointer;
        font-weight: 600;
        transition: transform 0.15s ease, box-shadow 0.15s ease;
      }
      #kernelEditorPanel button:hover {
        transform: translateY(-1px);
        box-shadow: 0 8px 20px rgba(15, 23, 42, 0.15);
      }
      #kernelEditorPanel button.primary {
        background: linear-gradient(140deg, var(--kernel-panel-accent), #22c55e);
        border: none;
        color: #ffffff;
      }
      #kernelEditorPanel button.ghost {
        background: var(--kernel-panel-ghost);
        border-color: rgba(15, 23, 42, 0.22);
      }
      #kernelEditorPanel button.danger {
        background: #fee2e2;
        border-color: rgba(220, 38, 38, 0.55);
        color: #991b1b;
      }
      #kernelEditorPanel .kernel-editor-header {
        display: flex;
        justify-content: space-between;
        align-items: center;
        margin-bottom: 10px;
        gap: 12px;
        padding-bottom: 8px;
        border-bottom: 1px solid rgba(15, 23, 42, 0.08);
        cursor: grab;
      }
      #kernelEditorPanel .kernel-editor-header:active {
        cursor: grabbing;
      }
      #kernelEditorPanel .kernel-editor-eyebrow {
        text-transform: uppercase;
        letter-spacing: 0.16em;
        font-size: 10px;
        color: var(--kernel-panel-muted);
      }
      #kernelEditorPanel .kernel-editor-sub {
        font-size: 11px;
        color: var(--kernel-panel-muted);
      }
      #kernelEditorPanel .kernel-editor-title {
        text-transform: uppercase;
        letter-spacing: 0.12em;
        font-size: 10px;
        color: var(--kernel-panel-muted);
      }
      #kernelEditorPanel .kernel-editor-section {
        display: grid;
        gap: 8px;
        margin-bottom: 12px;
        padding: 10px;
        border-radius: 14px;
        border: 1px solid rgba(15, 23, 42, 0.12);
        background: #f7f9fc;
      }
      #kernelEditorPanel .kernel-editor-row {
        display: flex;
        justify-content: space-between;
        font-weight: 600;
      }
      #kernelEditorPanel .kernel-editor-grid {
        display: grid;
        grid-template-columns: repeat(2, minmax(0, 1fr));
        gap: 8px;
      }
      #kernelEditorPanel .kernel-editor-actions {
        display: flex;
        gap: 8px;
        flex-wrap: wrap;
      }
      #kernelEditorPanel .kernel-editor-footer {
        font-size: 11px;
        color: var(--kernel-panel-muted);
      }
      .kernel-added-button {
        padding: 8px 16px;
        border-radius: 999px;
        border: 1px solid rgba(15, 23, 42, 0.2);
        background: #ffffff;
        cursor: pointer;
      }
      .kernel-editor-highlight {
        outline: 2px dashed var(--kernel-panel-accent-2);
        outline-offset: 2px;
      }
      @media (max-width: 680px) {
        #kernelEditorPanel {
          width: calc(100% - 24px);
          right: 12px;
          left: 12px;
          top: auto;
          bottom: 12px;
          max-height: 70vh;
          overflow: auto;
        }
      }
    `;
    document.head.appendChild(style);
    document.body.appendChild(panel);

    let selectedEl = null;
    let dragging = false;
    let dragOffsetX = 0;
    let dragOffsetY = 0;
    let panelDragging = false;
    let panelOffsetX = 0;
    let panelOffsetY = 0;
    let editorMode = 'select';
    let dragHistoryPushed = false;
    const undoStack = [];
    const undoLimit = 40;

    function ensureKernelId(el) {
      if (el.id) return el.id;
      const id = `kernel_el_${Math.random().toString(36).slice(2, 8)}`;
      el.id = id;
      return id;
    }

    function isNovaTarget(el) {
      if (!el) return false;
      const id = (el.id || '').toLowerCase();
      if (id.startsWith('nova')) return true;
      if (el.closest('#novaPanel, #novaFab, #novaFabHome')) return true;
      if (el.closest('[id^="nova"], [id^="Nova"], [class*="nova"], [class*="Nova"]')) return true;
      return false;
    }

    function upsertCssRule(css, id, updates) {
      const selector = `#${id}`;
      const ruleRegex = new RegExp(`#${id}\\s*\\{[^}]*\\}`, 'm');
      let props = {};
      if (ruleRegex.test(css)) {
        const match = css.match(ruleRegex);
        const body = match ? match[0].slice(match[0].indexOf('{') + 1, match[0].lastIndexOf('}')) : '';
        body.split(';').forEach((part) => {
          const [key, value] = part.split(':');
          if (key && value) props[key.trim()] = value.trim();
        });
      }
      Object.keys(updates).forEach((key) => {
        if (updates[key]) props[key] = updates[key];
      });
      const ruleBody = Object.entries(props).map(([k, v]) => `${k}: ${v};`).join(' ');
      const nextRule = `${selector} { ${ruleBody} }`;
      if (ruleRegex.test(css)) {
        return css.replace(ruleRegex, nextRule);
      }
      return (css || '').trim() ? `${css.trim()}\n${nextRule}` : nextRule;
    }

    function upsertJsBlock(js, id, tag, code) {
      const start = `// kernel-${tag}:${id}`;
      const end = `// kernel-${tag}-end:${id}`;
      const block = `${start}\n${code}\n${end}`;
      const blockRegex = new RegExp(`${start}[\\s\\S]*?${end}`, 'm');
      if (blockRegex.test(js)) {
        return js.replace(blockRegex, block);
      }
      return (js || '').trim() ? `${js.trim()}\n${block}` : block;
    }

    function applyStyleToSelected() {
      if (!selectedEl) return;
      pushHistory(false);
      const id = ensureKernelId(selectedEl);
      const color = document.getElementById('kernelEditorColor')?.value.trim();
      const bg = document.getElementById('kernelEditorBg')?.value.trim();
      const font = document.getElementById('kernelEditorFont')?.value.trim();
      const radius = document.getElementById('kernelEditorRadius')?.value.trim();
      const left = document.getElementById('kernelEditorLeft')?.value.trim();
      const top = document.getElementById('kernelEditorTop')?.value.trim();
      const updates = {
        ...(color ? { color } : {}),
        ...(bg ? { 'background-color': bg } : {}),
        ...(font ? { 'font-size': `${parseInt(font, 10)}px` } : {}),
        ...(radius ? { 'border-radius': `${parseInt(radius, 10)}px` } : {}),
      };
      if (left || top) {
        updates.position = 'fixed';
        if (left) updates.left = `${parseInt(left, 10)}px`;
        if (top) updates.top = `${parseInt(top, 10)}px`;
      }
      const nextCss = upsertCssRule(readLocalCss(), id, updates);
      writeLocalCss(nextCss);
      applyCss(nextCss);
    }

    function applyTextToSelected() {
      if (!selectedEl) return;
      pushHistory(true);
      const id = ensureKernelId(selectedEl);
      const text = document.getElementById('kernelEditorText')?.value || '';
      selectedEl.textContent = text;
      const snippet = `(() => { const el = document.getElementById(${JSON.stringify(id)}); if (el) el.textContent = ${JSON.stringify(text)}; })();`;
      const nextJs = upsertJsBlock(readLocalJs(), id, 'text', snippet);
      writeLocalJs(nextJs);
      applyLocalJs(nextJs);
    }

    function applyActionToSelected() {
      if (!selectedEl) return;
      pushHistory(true);
      const id = ensureKernelId(selectedEl);
      const type = document.getElementById('kernelEditorActionType')?.value || 'link';
      const value = document.getElementById('kernelEditorActionValue')?.value || '';
      const message = document.getElementById('kernelEditorActionMessage')?.value || '';
      const className = document.getElementById('kernelEditorActionClass')?.value || '';
      let snippet = '';
      if (type === 'link') {
        if (!value) return;
        snippet = `(() => { const el = document.getElementById(${JSON.stringify(id)}); if (!el) return; el.addEventListener('click', () => { window.location.href = ${JSON.stringify(value)}; }); })();`;
      } else if (type === 'show_message') {
        if (!message) return;
        snippet = `(() => { const el = document.getElementById(${JSON.stringify(id)}); if (!el) return; el.addEventListener('click', () => { alert(${JSON.stringify(message)}); }); })();`;
      } else if (type === 'open_modal') {
        if (!value) return;
        snippet = `(() => { const el = document.getElementById(${JSON.stringify(id)}); if (!el) return; el.addEventListener('click', () => { const modal = document.getElementById(${JSON.stringify(value)}); if (modal) modal.style.display = 'block'; }); })();`;
      } else if (type === 'toggle_class') {
        if (!value || !className) return;
        snippet = `(() => { const el = document.getElementById(${JSON.stringify(id)}); const target = document.getElementById(${JSON.stringify(value)}); if (!el || !target) return; el.addEventListener('click', () => { target.classList.toggle(${JSON.stringify(className)}); }); })();`;
      }
      if (!snippet) return;
      const nextJs = upsertJsBlock(readLocalJs(), id, 'action', snippet);
      writeLocalJs(nextJs);
      applyLocalJs(nextJs);
    }

    function addButton() {
      pushHistory(true);
      const label = document.getElementById('kernelEditorNewText')?.value || 'New Button';
      const type = document.getElementById('kernelEditorNewActionType')?.value || 'link';
      const value = document.getElementById('kernelEditorNewActionValue')?.value || '';
      const message = document.getElementById('kernelEditorNewActionMessage')?.value || '';
      const className = document.getElementById('kernelEditorNewActionClass')?.value || '';
      const button = document.createElement('button');
      button.textContent = label;
      button.type = 'button';
      button.className = 'kernel-added-button';
      const id = ensureKernelId(button);
      const blockedTags = ['BUTTON', 'A', 'INPUT', 'IMG', 'SVG'];
      const container = selectedEl && !blockedTags.includes(selectedEl.tagName)
        ? selectedEl
        : (selectedEl?.parentElement || document.body);
      if (isNovaTarget(container)) return;
      container.appendChild(button);
      selectedEl = button;
      button.classList.add('kernel-editor-highlight');
      document.getElementById('kernelEditorSelected').textContent = `#${id}`;

      const actionValue = document.getElementById('kernelEditorActionValue');
      if (actionValue) actionValue.value = value;
      const actionClass = document.getElementById('kernelEditorActionClass');
      if (actionClass) actionClass.value = className;
      const actionType = document.getElementById('kernelEditorActionType');
      if (actionType) actionType.value = type;
      const actionMessage = document.getElementById('kernelEditorActionMessage');
      if (actionMessage) actionMessage.value = message;
      applyActionToSelected();
    }

    function clearSelection() {
      if (selectedEl) selectedEl.classList.remove('kernel-editor-highlight');
      selectedEl = null;
      const label = document.getElementById('kernelEditorSelected');
      if (label) label.textContent = 'None';
    }

    function deleteSelected() {
      if (!selectedEl) return;
      pushHistory(true);
      const id = ensureKernelId(selectedEl);
      selectedEl.remove();
      clearSelection();
      const snippet = `(() => { const el = document.getElementById(${JSON.stringify(id)}); if (el) el.remove(); })();`;
      const nextJs = upsertJsBlock(readLocalJs(), id, 'delete', snippet);
      writeLocalJs(nextJs);
      applyLocalJs(nextJs);
    }

    function syncActionFields() {
      const type = document.getElementById('kernelEditorActionType')?.value || 'link';
      const valueInput = document.getElementById('kernelEditorActionValue');
      const msgInput = document.getElementById('kernelEditorActionMessage');
      const classInput = document.getElementById('kernelEditorActionClass');
      if (valueInput) valueInput.style.display = (type === 'link' || type === 'open_modal' || type === 'toggle_class') ? '' : 'none';
      if (msgInput) msgInput.style.display = (type === 'show_message') ? '' : 'none';
      if (classInput) classInput.style.display = (type === 'toggle_class') ? '' : 'none';
    }

    function syncNewActionFields() {
      const type = document.getElementById('kernelEditorNewActionType')?.value || 'link';
      const valueInput = document.getElementById('kernelEditorNewActionValue');
      const msgInput = document.getElementById('kernelEditorNewActionMessage');
      const classInput = document.getElementById('kernelEditorNewActionClass');
      if (valueInput) valueInput.style.display = (type === 'link' || type === 'open_modal' || type === 'toggle_class') ? '' : 'none';
      if (msgInput) msgInput.style.display = (type === 'show_message') ? '' : 'none';
      if (classInput) classInput.style.display = (type === 'toggle_class') ? '' : 'none';
    }

    function syncEditorMode() {
      const modeBtn = document.getElementById('kernelEditorMode');
      const hint = document.getElementById('kernelEditorModeHint');
      if (modeBtn) modeBtn.textContent = `Mode: ${editorMode === 'select' ? 'Select' : 'Interact'}`;
      if (hint) {
        hint.textContent = editorMode === 'select'
          ? 'Select mode: click to select. Interact mode: normal clicks, hold Alt to select.'
          : 'Interact mode: clicks work normally. Hold Alt and click to select.';
      }
    }

    async function publishKey() {
      try {
        const data = await kernelPost('/api/kernel/key/create', {
          page: pageKey,
          css: readLocalCss(),
          js: readLocalJs(),
        });
        const keyInput = document.getElementById('kernelEditorKey');
        const copyBtn = document.getElementById('kernelEditorCopyKey');
        if (keyInput) keyInput.value = data.key || '';
        if (copyBtn) copyBtn.disabled = !data.key;
        alert('Key generated. Paste it into LinkUp settings.');
      } catch (e) {
        alert(e.message || 'Key generation failed');
      }
    }

    async function copyKey() {
      const key = String(document.getElementById('kernelEditorKey')?.value || '').trim();
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
    }

    document.getElementById('kernelEditorExit')?.addEventListener('click', () => {
      try { localStorage.removeItem(visualFlagKey); } catch {}
      panel.remove();
      style.remove();
      document.removeEventListener('click', onSelect, true);
      document.removeEventListener('pointerdown', onDragStart, true);
      document.removeEventListener('pointermove', onDragMove, true);
      document.removeEventListener('pointerup', onDragEnd, true);
      document.removeEventListener('pointerdown', onPanelDragStart, true);
      document.removeEventListener('pointermove', onPanelDragMove, true);
      document.removeEventListener('pointerup', onPanelDragEnd, true);
    });

    document.getElementById('kernelEditorApplyStyle')?.addEventListener('click', applyStyleToSelected);
    document.getElementById('kernelEditorApplyText')?.addEventListener('click', applyTextToSelected);
    document.getElementById('kernelEditorApplyAction')?.addEventListener('click', applyActionToSelected);
    document.getElementById('kernelEditorAddButton')?.addEventListener('click', addButton);
    document.getElementById('kernelEditorPublish')?.addEventListener('click', publishKey);
    document.getElementById('kernelEditorCopyKey')?.addEventListener('click', copyKey);
    document.getElementById('kernelEditorUndo')?.addEventListener('click', undoLast);
    document.getElementById('kernelEditorClear')?.addEventListener('click', clearSelection);
    document.getElementById('kernelEditorDelete')?.addEventListener('click', deleteSelected);
    document.getElementById('kernelEditorActionType')?.addEventListener('change', syncActionFields);
    document.getElementById('kernelEditorNewActionType')?.addEventListener('change', syncNewActionFields);
    document.getElementById('kernelEditorMode')?.addEventListener('click', () => {
      editorMode = editorMode === 'select' ? 'interact' : 'select';
      syncEditorMode();
    });
    syncActionFields();
    syncNewActionFields();
    syncEditorMode();

    function onSelect(ev) {
      const target = ev.target;
      if (!(target instanceof HTMLElement)) return;
      if (target.closest('#kernelEditorPanel')) return;
      if (isNovaTarget(target)) return;
      if (editorMode === 'interact' && !ev.altKey) return;
      ev.preventDefault();
      ev.stopPropagation();
      if (selectedEl) selectedEl.classList.remove('kernel-editor-highlight');
      selectedEl = target;
      selectedEl.classList.add('kernel-editor-highlight');
      document.getElementById('kernelEditorSelected').textContent = `#${ensureKernelId(target)}`;
      const textInput = document.getElementById('kernelEditorText');
      if (textInput) textInput.value = target.textContent || '';
      syncActionFields();
    }

    function onDragStart(ev) {
      const target = ev.target;
      if (!(target instanceof HTMLElement)) return;
      if (!selectedEl || target !== selectedEl) return;
      if (target.closest('#kernelEditorPanel')) return;
      if (isNovaTarget(target)) return;
      if (!dragHistoryPushed) {
        pushHistory(false);
        dragHistoryPushed = true;
      }
      ev.preventDefault();
      dragging = true;
      const rect = selectedEl.getBoundingClientRect();
      dragOffsetX = ev.clientX - rect.left;
      dragOffsetY = ev.clientY - rect.top;
    }

    function onDragMove(ev) {
      if (!dragging || !selectedEl) return;
      ev.preventDefault();
      const id = ensureKernelId(selectedEl);
      const left = Math.round(ev.clientX - dragOffsetX);
      const top = Math.round(ev.clientY - dragOffsetY);
      const nextCss = upsertCssRule(readLocalCss(), id, {
        position: 'fixed',
        left: `${left}px`,
        top: `${top}px`,
      });
      writeLocalCss(nextCss);
      applyCss(nextCss);
    }

    function onDragEnd() {
      dragging = false;
      dragHistoryPushed = false;
    }

    function onPanelDragStart(ev) {
      const handle = ev.target;
      if (!(handle instanceof HTMLElement)) return;
      if (!handle.closest('#kernelEditorDragHandle')) return;
      ev.preventDefault();
      panelDragging = true;
      const rect = panel.getBoundingClientRect();
      panelOffsetX = ev.clientX - rect.left;
      panelOffsetY = ev.clientY - rect.top;
    }

    function onPanelDragMove(ev) {
      if (!panelDragging) return;
      ev.preventDefault();
      const left = Math.max(8, Math.min(window.innerWidth - panel.offsetWidth - 8, ev.clientX - panelOffsetX));
      const top = Math.max(8, Math.min(window.innerHeight - panel.offsetHeight - 8, ev.clientY - panelOffsetY));
      panel.style.left = `${left}px`;
      panel.style.top = `${top}px`;
      panel.style.right = 'auto';
      panel.style.bottom = 'auto';
    }

    function onPanelDragEnd() {
      panelDragging = false;
    }

    document.addEventListener('click', onSelect, true);
    document.addEventListener('pointerdown', onDragStart, true);
    document.addEventListener('pointermove', onDragMove, true);
    document.addEventListener('pointerup', onDragEnd, true);
    document.addEventListener('pointerdown', onPanelDragStart, true);
    document.addEventListener('pointermove', onPanelDragMove, true);
    document.addEventListener('pointerup', onPanelDragEnd, true);
  }
})();
