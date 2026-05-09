(() => {
    // --- Pro Sidebar, FAB, Theme Toggle, Profile Menu ---
    window.addEventListener('DOMContentLoaded', () => {
      // Sidebar navigation
      const sidebarBtns = document.querySelectorAll('.sidebar-btn');
      sidebarBtns.forEach(btn => {
        btn.addEventListener('click', () => {
          sidebarBtns.forEach(b => b.classList.remove('active'));
          btn.classList.add('active');
          // Scroll to section or open modal as needed
          if (btn.id === 'navLibrarySidebar') document.getElementById('libraryModal')?.classList.add('show');
          if (btn.id === 'navDraftsSidebar') setStatus('Drafts coming soon.');
          if (btn.id === 'navCaptureSidebar') document.getElementById('dropzone')?.scrollIntoView({behavior:'smooth'});
          if (btn.id === 'navExportSidebar') setStatus('Export options below.');
          if (btn.id === 'navSettingsSidebar') setStatus('Settings coming soon.');
        });
      });

      // Floating Add Asset Button
      const fab = document.getElementById('fabAddAsset');
      if (fab) {
        fab.addEventListener('click', () => {
          document.getElementById('assetInput')?.click();
        });
      }

      // Theme toggle
      const themeBtn = document.getElementById('themeToggleBtn');
      if (themeBtn) {
        themeBtn.addEventListener('click', () => {
          document.body.classList.toggle('theme-light');
          localStorage.setItem('creatorTheme', document.body.classList.contains('theme-light') ? 'light' : 'dark');
        });
        // On load, set theme
        if (localStorage.getItem('creatorTheme') === 'light') {
          document.body.classList.add('theme-light');
        }
      }

      // Profile menu dropdown
      const profileBtn = document.getElementById('profileBtn');
      const profileDropdown = document.getElementById('profileDropdown');
      if (profileBtn && profileDropdown) {
        profileBtn.addEventListener('click', () => {
          profileDropdown.style.display = profileDropdown.style.display === 'block' ? 'none' : 'block';
        });
        document.addEventListener('click', (e) => {
          if (!profileBtn.contains(e.target) && !profileDropdown.contains(e.target)) {
            profileDropdown.style.display = 'none';
          }
        });
      }
      // Profile menu actions
      document.getElementById('profileSettingsBtn')?.addEventListener('click', () => setStatus('Settings coming soon.'));
      document.getElementById('profileFeedbackBtn')?.addEventListener('click', () => setStatus('Feedback coming soon.'));
      document.getElementById('profileLogoutBtn')?.addEventListener('click', () => setStatus('Logout coming soon.'));
    });

    // --- Pro Panels: History, Preview, Inspector ---
    // History stack for undo/redo
    const historyStack = [];
    let historyIndex = -1;
    function pushHistory(action, payload) {
      historyStack.splice(historyIndex + 1);
      historyStack.push({ action, payload });
      historyIndex = historyStack.length - 1;
      renderHistory();
    }
    function undo() {
      if (historyIndex > 0) {
        historyIndex--;
        // TODO: apply undo logic
        renderHistory();
      }
    }
    function redo() {
      if (historyIndex < historyStack.length - 1) {
        historyIndex++;
        // TODO: apply redo logic
        renderHistory();
      }
    }
    function renderHistory() {
      const list = document.getElementById('historyList');
      if (!list) return;
      if (historyStack.length === 0) {
        list.textContent = 'No actions yet.';
        return;
      }
      list.innerHTML = historyStack.map((h, i) => `<div${i===historyIndex?' style="color:var(--accent)"':''}>${h.action}</div>`).join('');
    }
    // Keyboard shortcuts
    window.addEventListener('keydown', (e) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'z') { e.preventDefault(); undo(); }
      if ((e.ctrlKey || e.metaKey) && (e.key.toLowerCase() === 'y' || (e.shiftKey && e.key.toLowerCase() === 'z'))) { e.preventDefault(); redo(); }
      if (e.key === 'Tab') { e.preventDefault(); document.getElementById('previewPanel')?.scrollIntoView({behavior:'smooth'}); }
    });
    // TODO: Call pushHistory('Action', {details}) in all major mutating actions
  const sampleAssets = [
    { name: 'Nebula', url: '/creator/assets/nebula.svg' },
    { name: 'Prism', url: '/creator/assets/prism.svg' },
    { name: 'Flux', url: '/creator/assets/flux.svg' },
    { name: 'Grid', url: '/creator/assets/grid.svg' }
  ];

  const state = {
    mode: 'gif',
    assets: [],
    frames: [],
    activeFrameId: null,
    isPlaying: false,
    playTimer: null,
    playLoops: 0,
    library: [],
    activeLibraryId: null,
    contacts: [],
    settings: {
      size: 320,
      delay: 120,
      zoom: 1,
      offsetX: 0,
      offsetY: 0,
      rotate: 0,
      fit: 'cover',
      caption: '',
      captionX: 0,
      captionY: 0,
      cropEnabled: false,
      cropX: 50,
      cropY: 50,
      cropSize: 100,
      outline: 6,
      shadow: 6,
      bgColor: '#081c22',
      stickerText: '',
      stickerTextX: 0,
      stickerTextY: 0,
      removeBg: false,
      removeBgColor: '#031016',
      removeBgTolerance: 26,
      cardTitle: '',
      cardLine: '',
      accent: '#62e6d9',
      filter: 'none',
      filterIntensity: 100,
      opacity: 1,
      flipX: false,
      flipY: false
    }
  };

  // --- Filter UI bindings ---
  window.addEventListener('DOMContentLoaded', () => {
    const filterSelect = document.getElementById('filterSelect');
    const filterIntensityRange = document.getElementById('filterIntensityRange');
    const filterIntensityGroup = document.getElementById('filterIntensityGroup');

    if (filterSelect) {
      filterSelect.addEventListener('change', (e) => {
        updateSetting('filter', e.target.value);
        if (e.target.value === 'brightness' || e.target.value === 'contrast') {
          filterIntensityGroup.style.display = '';
        } else {
          filterIntensityGroup.style.display = 'none';
        }
        drawPreview();
      });
    }
    if (filterIntensityRange) {

      filterIntensityRange.addEventListener('input', (e) => {
        updateSetting('filterIntensity', Number(e.target.value || 100));
        drawPreview();
      });
    }
  });

  const els = {
    assetInput: document.getElementById('assetInput'),
    assetGrid: document.getElementById('assetGrid'),
    dropzone: document.getElementById('dropzone'),
    frameList: document.getElementById('frameList'),
    timelineStrip: document.getElementById('timelineStrip'),
    clearFramesBtn: document.getElementById('clearFramesBtn'),
    reverseFramesBtn: document.getElementById('reverseFramesBtn'),
    playBtn: document.getElementById('playBtn'),
    pauseBtn: document.getElementById('pauseBtn'),
    exportBtn: document.getElementById('exportBtn'),
    downloadBtn: document.getElementById('downloadBtn'),
    saveBtn: document.getElementById('saveBtn'),
    previewCanvas: document.getElementById('previewCanvas'),
    canvasOverlay: document.getElementById('canvasOverlay'),
    stageSub: document.getElementById('stageSub'),
    modeList: document.getElementById('modeList'),
    renderStatus: document.getElementById('renderStatus'),
    renderNote: document.getElementById('renderNote'),
    sizeRange: document.getElementById('sizeRange'),
    delayRange: document.getElementById('delayRange'),
    frameDelayInput: document.getElementById('frameDelayInput'),
    applyDelayAllBtn: document.getElementById('applyDelayAllBtn'),
    resetEditsBtn: document.getElementById('resetEditsBtn'),
    centerEditsBtn: document.getElementById('centerEditsBtn'),
    fitCoverBtn: document.getElementById('fitCoverBtn'),
    fitContainBtn: document.getElementById('fitContainBtn'),
    zoomRange: document.getElementById('zoomRange'),
    offsetXRange: document.getElementById('offsetXRange'),
    offsetYRange: document.getElementById('offsetYRange'),
    rotateRange: document.getElementById('rotateRange'),
    opacityRange: document.getElementById('opacityRange'),
    flipXToggle: document.getElementById('flipXToggle'),
    flipYToggle: document.getElementById('flipYToggle'),
    fitSelect: document.getElementById('fitSelect'),
    captionInput: document.getElementById('captionInput'),
    captionXRange: document.getElementById('captionXRange'),
    captionYRange: document.getElementById('captionYRange'),
    cropToggle: document.getElementById('cropToggle'),
    cropResetBtn: document.getElementById('cropResetBtn'),
    cropXRange: document.getElementById('cropXRange'),
    cropYRange: document.getElementById('cropYRange'),
    cropSizeRange: document.getElementById('cropSizeRange'),
    outlineRange: document.getElementById('outlineRange'),
    shadowRange: document.getElementById('shadowRange'),
    bgColorInput: document.getElementById('bgColorInput'),
    stickerTextInput: document.getElementById('stickerTextInput'),
    stickerTextXRange: document.getElementById('stickerTextXRange'),
    stickerTextYRange: document.getElementById('stickerTextYRange'),
    removeBgToggle: document.getElementById('removeBgToggle'),
    removeBgColor: document.getElementById('removeBgColor'),
    removeBgTolerance: document.getElementById('removeBgTolerance'),
    cardTitleInput: document.getElementById('cardTitleInput'),
    cardLineInput: document.getElementById('cardLineInput'),
    accentColorInput: document.getElementById('accentColorInput'),
    libraryFilter: document.getElementById('libraryFilter'),
    libraryList: document.getElementById('libraryList'),
    libraryRefreshBtn: document.getElementById('libraryRefreshBtn'),
    libraryModal: document.getElementById('libraryModal'),
    libraryScrim: document.getElementById('libraryScrim'),
    libraryCloseBtn: document.getElementById('libraryCloseBtn'),
    settingsModal: document.getElementById('settingsModal'),
    settingsScrim: document.getElementById('settingsScrim'),
    settingsForm: document.getElementById('settingsForm'),
    settingsSize: document.getElementById('settingsSize'),
    settingsDelay: document.getElementById('settingsDelay'),
    settingsFit: document.getElementById('settingsFit'),
    settingsBg: document.getElementById('settingsBg'),
    settingsAutoplay: document.getElementById('settingsAutoplay'),
    settingsSaveBtn: document.getElementById('settingsSaveBtn'),
    settingsCloseBtn: document.getElementById('settingsCloseBtn'),
    sendContactSelect: document.getElementById('sendContactSelect'),
    sendBtn: document.getElementById('sendBtn'),
    sendSelection: document.getElementById('sendSelection'),
    statusNote: document.getElementById('statusNote'),
    navLibraryBtn: document.getElementById('navLibraryBtn'),
    navDraftsBtn: document.getElementById('navDraftsBtn'),
    navCaptureBtn: document.getElementById('navCaptureBtn'),
    newSessionBtn: document.getElementById('newSessionBtn'),
    quickTourBtn: document.getElementById('quickTourBtn'),
    tourScrim: document.getElementById('tourScrim'),
    tourCard: document.getElementById('tourCard'),
    tourStep: document.getElementById('tourStep'),
    tourTitle: document.getElementById('tourTitle'),
    tourText: document.getElementById('tourText'),
    tourPrevBtn: document.getElementById('tourPrevBtn'),
    tourNextBtn: document.getElementById('tourNextBtn'),
    tourSkipBtn: document.getElementById('tourSkipBtn')
  };

  const csrfToken = (document.querySelector('meta[name="csrf-token"]') || {}).content || '';
  let gifLibPromise = null;

  function loadGifLib() {
    if (window.GIF) return Promise.resolve(true);
    if (gifLibPromise) return gifLibPromise;
    gifLibPromise = new Promise((resolve, reject) => {
      const script = document.createElement('script');
      script.src = 'https://cdnjs.cloudflare.com/ajax/libs/gif.js/0.2.0/gif.min.js';
      script.async = true;
      script.onload = () => resolve(true);
      script.onerror = () => reject(new Error('gif_lib_failed'));
      document.head.appendChild(script);
    });
    return gifLibPromise;
  }

  function setStatus(text) {
    if (els.statusNote) {
      els.statusNote.textContent = text;
    }
  }

  function scrollToId(id) {
    const el = document.getElementById(id);
    if (!el) return;
    el.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }

  function setRenderStatus(text, note) {
    if (els.renderStatus) els.renderStatus.textContent = text;
    if (els.renderNote) els.renderNote.textContent = note;
  }

  function uid() {
    return Math.random().toString(36).slice(2);
  }

  function addAsset(asset) {
    state.assets.push(asset);
    renderAssets();
    return asset;
  }

  function loadImage(url) {
    return new Promise((resolve, reject) => {
      const img = new Image();
      img.crossOrigin = 'anonymous';
      img.decoding = 'async';
      img.onload = () => resolve(img);
      img.onerror = reject;
      img.src = url;
    });
  }

  function addAssetFromUrl(url, name) {
    return loadImage(url).then((img) => {
      return addAsset({ id: uid(), name: name || 'Asset', img, url });
    });
  }

  function addAssetFromFile(file) {
    const url = URL.createObjectURL(file);
    return loadImage(url).then((img) => {
      return addAsset({ id: uid(), name: file.name || 'Upload', img, url });
    });
  }

  function ensureSampleAsset(sample) {
    const existing = state.assets.find((asset) => asset.url === sample.url);
    if (existing) return Promise.resolve(existing);
    return addAssetFromUrl(sample.url, sample.name);
  }

  function applyPreset(presetKey) {
    const presets = {
      starter: {
        label: 'Starter loop ready.',
        mode: 'gif',
        order: [0, 1, 2],
        delay: 140
      },
      pulse: {
        label: 'Pulse loop ready.',
        mode: 'gif',
        order: [0, 1, 2, 3, 2, 1],
        delay: 110
      },
      sticker: {
        label: 'Sticker pop ready.',
        mode: 'sticker',
        order: [1],
        delay: 120
      }
    };

    const preset = presets[presetKey];
    if (!preset) return;

    handleModeChange(preset.mode);
    const targets = preset.order.map((index) => sampleAssets[index]).filter(Boolean);
    Promise.all(targets.map(ensureSampleAsset)).then((assets) => {
      state.frames = [];
      state.activeFrameId = null;
      assets.forEach((asset) => {
        const frame = { id: uid(), assetId: asset.id, settings: makeFrameSettings() };
        frame.settings.delay = preset.delay;
        state.frames.push(frame);
        state.activeFrameId = frame.id;
      });
      renderFrames();
      drawPreview();
      setStatus(preset.label);
    }).catch(() => {
      setStatus('Preset failed to load.');
    });
  }

  function addFrame(assetId) {
    const frame = { id: uid(), assetId, settings: makeFrameSettings() };
    state.frames.push(frame);
    state.activeFrameId = frame.id;
    syncControlsFromFrame(frame);
    renderFrames();
    drawPreview();
  }

  function getActiveFrame() {
    return state.frames.find((f) => f.id === state.activeFrameId) || state.frames[0] || null;
  }

  function makeFrameSettings() {
    return {
      delay: state.settings.delay,
      zoom: state.settings.zoom,
      offsetX: state.settings.offsetX,
      offsetY: state.settings.offsetY,
      rotate: state.settings.rotate,
      fit: state.settings.fit,
      captionX: state.settings.captionX,
      captionY: state.settings.captionY,
      cropEnabled: state.settings.cropEnabled,
      cropX: state.settings.cropX,
      cropY: state.settings.cropY,
      cropSize: state.settings.cropSize,
      outline: state.settings.outline,
      shadow: state.settings.shadow,
      bgColor: state.settings.bgColor,
      stickerTextX: state.settings.stickerTextX,
      stickerTextY: state.settings.stickerTextY,
      removeBg: state.settings.removeBg,
      removeBgColor: state.settings.removeBgColor,
      removeBgTolerance: state.settings.removeBgTolerance,
      opacity: state.settings.opacity,
      flipX: state.settings.flipX,
      flipY: state.settings.flipY
    };
  }

  function ensureFrameSettings(frame) {
    if (!frame) return;
    if (!frame.settings) {
      frame.settings = makeFrameSettings();
    }
  }

  function removeFrame(frameId) {
    state.frames = state.frames.filter((frame) => frame.id !== frameId);
    if (state.activeFrameId === frameId) {
      state.activeFrameId = state.frames[0]?.id || null;
    }
    renderFrames();
    drawPreview();
  }

  function moveFrame(frameId, direction) {
    const index = state.frames.findIndex((frame) => frame.id === frameId);
    if (index < 0) return;
    const newIndex = index + direction;
    if (newIndex < 0 || newIndex >= state.frames.length) return;
    const [frame] = state.frames.splice(index, 1);
    state.frames.splice(newIndex, 0, frame);
    renderFrames();
  }

  function duplicateActiveFrame() {
    const frame = state.frames.find((f) => f.id === state.activeFrameId);
    if (!frame) return;
    const cloned = { id: uid(), assetId: frame.assetId };
    const index = state.frames.findIndex((f) => f.id === frame.id);
    state.frames.splice(index + 1, 0, cloned);
    state.activeFrameId = cloned.id;
    renderFrames();
  }

  function renderAssets() {
    if (!els.assetGrid) return;
    els.assetGrid.innerHTML = '';
    state.assets.forEach((asset) => {
      const card = document.createElement('button');
      card.type = 'button';
      card.className = 'asset-card';
      card.innerHTML = `
        <div class="asset-thumb"><img class="thumb-img" src="${asset.url}" alt="${escapeHtml(asset.name)}" /></div>
        <div class="asset-name">${escapeHtml(asset.name)}</div>
      `;
      card.addEventListener('click', () => addFrame(asset.id));
      els.assetGrid.appendChild(card);
    });
  }

  function renderFrames() {
    if (els.frameList) {
      els.frameList.innerHTML = '';
      state.frames.forEach((frame, index) => {
        ensureFrameSettings(frame);
        const asset = state.assets.find((a) => a.id === frame.assetId);
        const item = document.createElement('div');
        item.className = 'frame-item';
        if (frame.id === state.activeFrameId) {
          item.classList.add('active');
        }
        item.innerHTML = `
          <div class="frame-thumb"><img class="thumb-img" src="${asset?.url || ''}" alt="" /></div>
          <div>
            <div class="asset-name">${escapeHtml(asset?.name || 'Frame')}</div>
            <div class="asset-name">Frame ${index + 1} • ${frame.settings.delay}ms</div>
          </div>
          <div>
            <button class="frame-action" data-action="up">Up</button>
            <button class="frame-action" data-action="down">Down</button>
          </div>
        `;
        item.addEventListener('click', () => {
          state.activeFrameId = frame.id;
          syncControlsFromFrame(frame);
          drawPreview();
        });
        item.querySelectorAll('.frame-action').forEach((btn) => {
          btn.addEventListener('click', (event) => {
            event.stopPropagation();
            const action = btn.getAttribute('data-action');
            if (action === 'up') moveFrame(frame.id, -1);
            if (action === 'down') moveFrame(frame.id, 1);
          });
        });
        els.frameList.appendChild(item);
      });
    }
    renderTimeline();
  }

  function renderTimeline() {
    if (!els.timelineStrip) return;
    els.timelineStrip.innerHTML = '';
    state.frames.forEach((frame, index) => {
      ensureFrameSettings(frame);
      const asset = state.assets.find((a) => a.id === frame.assetId);
      const tile = document.createElement('div');
      tile.className = 'timeline-frame';
      tile.draggable = true;
      tile.innerHTML = `
        <div class="timeline-thumb"><img class="thumb-img" src="${asset?.url || ''}" alt="" /></div>
        <div class="asset-name">${index + 1}</div>
        <input class="frame-delay" type="number" min="60" max="1000" value="${frame.settings.delay}" />
      `;
      tile.addEventListener('click', () => {
        state.activeFrameId = frame.id;
        syncControlsFromFrame(frame);
        drawPreview();
      });
      tile.addEventListener('dragstart', (event) => {
        event.dataTransfer?.setData('text/plain', frame.id);
        event.dataTransfer.effectAllowed = 'move';
      });
      tile.addEventListener('dragover', (event) => {
        event.preventDefault();
      });
      tile.addEventListener('drop', (event) => {
        event.preventDefault();
        const draggedId = event.dataTransfer?.getData('text/plain');
        if (!draggedId || draggedId === frame.id) return;
        const fromIndex = state.frames.findIndex((f) => f.id === draggedId);
        const toIndex = state.frames.findIndex((f) => f.id === frame.id);
        if (fromIndex < 0 || toIndex < 0) return;
        const [moved] = state.frames.splice(fromIndex, 1);
        state.frames.splice(toIndex, 0, moved);
        renderFrames();
      });
      const delayInput = tile.querySelector('.frame-delay');
      delayInput?.addEventListener('input', (event) => {
        const value = Number(event.target.value || 120);
        frame.settings.delay = Math.max(60, Math.min(1000, value));
        if (frame.id === state.activeFrameId) {
          if (els.frameDelayInput) els.frameDelayInput.value = String(frame.settings.delay);
        }
      });
      els.timelineStrip.appendChild(tile);
    });
  }

  function escapeHtml(text) {
    return String(text || '')
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  function updateOverlay() {
    const hasFrames = state.frames.length > 0;
    const needsAsset = state.mode === 'gif' || state.mode === 'sticker';
    if (els.canvasOverlay) {
      els.canvasOverlay.style.display = !hasFrames && needsAsset ? 'grid' : 'none';
    }
  }

  function getFrameSettings(frame) {
    if (!frame) return { ...state.settings };
    ensureFrameSettings(frame);
    return { ...state.settings, ...frame.settings };
  }

  function hexToRgb(hex) {
    const value = (hex || '#000000').replace('#', '');
    if (value.length !== 6) return { r: 0, g: 0, b: 0 };
    return {
      r: parseInt(value.slice(0, 2), 16),
      g: parseInt(value.slice(2, 4), 16),
      b: parseInt(value.slice(4, 6), 16)
    };
  }

  function applyRemoveBackground(img, settings) {
    if (!settings.removeBg) return img;
    const canvas = document.createElement('canvas');
    canvas.width = img.width;
    canvas.height = img.height;
    const ctx = canvas.getContext('2d');
    ctx.drawImage(img, 0, 0);
    const imageData = ctx.getImageData(0, 0, canvas.width, canvas.height);
    const data = imageData.data;
    const target = hexToRgb(settings.removeBgColor);
    const tolerance = settings.removeBgTolerance || 0;
    for (let i = 0; i < data.length; i += 4) {
      const dr = data[i] - target.r;
      const dg = data[i + 1] - target.g;
      const db = data[i + 2] - target.b;
      const distance = Math.sqrt((dr * dr) + (dg * dg) + (db * db));
      if (distance <= tolerance) {
        data[i + 3] = 0;
      }
    }
    ctx.putImageData(imageData, 0, 0);
    return canvas;
  }

  function updateSetting(key, value, applyAll = false) {
    state.settings[key] = value;
    if (applyAll) {
      state.frames.forEach((frame) => {
        ensureFrameSettings(frame);
        frame.settings[key] = value;
      });
    } else {
      const frame = getActiveFrame();
      if (frame) {
        ensureFrameSettings(frame);
        frame.settings[key] = value;
      }
    }
  }

  function applyQuickEdit(action) {
    if (action === 'center') {
      updateSetting('offsetX', 0);
      updateSetting('offsetY', 0);
      updateSetting('captionX', 0);
      updateSetting('captionY', 0);
      if (els.offsetXRange) els.offsetXRange.value = '0';
      if (els.offsetYRange) els.offsetYRange.value = '0';
      if (els.captionXRange) els.captionXRange.value = '0';
      if (els.captionYRange) els.captionYRange.value = '0';
      drawPreview();
      return;
    }

    if (action === 'fit-cover' || action === 'fit-contain') {
      const fit = action === 'fit-cover' ? 'cover' : 'contain';
      updateSetting('fit', fit);
      if (els.fitSelect) els.fitSelect.value = fit;
      drawPreview();
      return;
    }

    if (action === 'reset') {
      updateSetting('zoom', 1);
      updateSetting('offsetX', 0);
      updateSetting('offsetY', 0);
      updateSetting('rotate', 0);
      updateSetting('opacity', 1);
      updateSetting('flipX', false);
      updateSetting('flipY', false);
      updateSetting('captionX', 0);
      updateSetting('captionY', 0);
      updateSetting('fit', 'cover');
      updateSetting('cropEnabled', false);
      updateSetting('cropX', 50);
      updateSetting('cropY', 50);
      updateSetting('cropSize', 100);

      if (els.zoomRange) els.zoomRange.value = '100';
      if (els.offsetXRange) els.offsetXRange.value = '0';
      if (els.offsetYRange) els.offsetYRange.value = '0';
      if (els.rotateRange) els.rotateRange.value = '0';
      if (els.opacityRange) els.opacityRange.value = '100';
      if (els.flipXToggle) els.flipXToggle.checked = false;
      if (els.flipYToggle) els.flipYToggle.checked = false;
      if (els.captionXRange) els.captionXRange.value = '0';
      if (els.captionYRange) els.captionYRange.value = '0';
      if (els.fitSelect) els.fitSelect.value = 'cover';
      if (els.cropToggle) els.cropToggle.checked = false;
      if (els.cropXRange) els.cropXRange.value = '50';
      if (els.cropYRange) els.cropYRange.value = '50';
      if (els.cropSizeRange) els.cropSizeRange.value = '100';
      drawPreview();
    }
  }

  function syncControlsFromFrame(frame) {
    const settings = getFrameSettings(frame);
    if (els.sizeRange) els.sizeRange.value = String(state.settings.size || 320);
    if (els.frameDelayInput) els.frameDelayInput.value = String(settings.delay || state.settings.delay);
    if (els.delayRange) els.delayRange.value = String(settings.delay || state.settings.delay);
    if (els.zoomRange) els.zoomRange.value = String((settings.zoom || 1) * 100);
    if (els.offsetXRange) els.offsetXRange.value = String(settings.offsetX || 0);
    if (els.offsetYRange) els.offsetYRange.value = String(settings.offsetY || 0);
    if (els.rotateRange) els.rotateRange.value = String(settings.rotate || 0);
    if (els.opacityRange) els.opacityRange.value = String(Math.round((settings.opacity ?? 1) * 100));
    if (els.flipXToggle) els.flipXToggle.checked = !!settings.flipX;
    if (els.flipYToggle) els.flipYToggle.checked = !!settings.flipY;
    if (els.fitSelect) els.fitSelect.value = settings.fit || 'cover';
    if (els.captionXRange) els.captionXRange.value = String(settings.captionX || 0);
    if (els.captionYRange) els.captionYRange.value = String(settings.captionY || 0);
    if (els.captionInput) els.captionInput.value = state.settings.caption || '';
    if (els.cropToggle) els.cropToggle.checked = !!settings.cropEnabled;
    if (els.cropXRange) els.cropXRange.value = String(settings.cropX || 50);
    if (els.cropYRange) els.cropYRange.value = String(settings.cropY || 50);
    if (els.cropSizeRange) els.cropSizeRange.value = String(settings.cropSize || 100);
    if (els.outlineRange) els.outlineRange.value = String(settings.outline || 0);
    if (els.shadowRange) els.shadowRange.value = String(settings.shadow || 0);
    if (els.bgColorInput) els.bgColorInput.value = settings.bgColor || '#081c22';
    if (els.stickerTextInput) els.stickerTextInput.value = state.settings.stickerText || '';
    if (els.stickerTextXRange) els.stickerTextXRange.value = String(settings.stickerTextX || 0);
    if (els.stickerTextYRange) els.stickerTextYRange.value = String(settings.stickerTextY || 0);
    if (els.removeBgToggle) els.removeBgToggle.checked = !!settings.removeBg;
    if (els.removeBgColor) els.removeBgColor.value = settings.removeBgColor || '#031016';
    if (els.removeBgTolerance) els.removeBgTolerance.value = String(settings.removeBgTolerance || 0);
    if (els.cardTitleInput) els.cardTitleInput.value = state.settings.cardTitle || '';
    if (els.cardLineInput) els.cardLineInput.value = state.settings.cardLine || '';
    if (els.accentColorInput) els.accentColorInput.value = state.settings.accent || '#62e6d9';
    if (els.filterSelect) els.filterSelect.value = state.settings.filter || 'none';
    if (els.filterIntensityRange) {
      els.filterIntensityRange.value = String(state.settings.filterIntensity || 100);
    }
    const intensityGroup = document.getElementById('filterIntensityGroup');
    if (intensityGroup) {
      intensityGroup.style.display = (state.settings.filter === 'brightness' || state.settings.filter === 'contrast') ? '' : 'none';
    }
  }

  function drawImageWithSettings(ctx, img, size, settings) {
    const zoom = settings.zoom;
    const rotate = (settings.rotate || 0) * (Math.PI / 180);
    const offsetX = settings.offsetX || 0;
    const offsetY = settings.offsetY || 0;
    const fit = settings.fit || 'cover';
    let source = img;
    let crop = null;

    // --- Apply filter if needed ---
    if (settings.filter && settings.filter !== 'none') {
      const tempCanvas = document.createElement('canvas');
      tempCanvas.width = img.width;
      tempCanvas.height = img.height;
      const tctx = tempCanvas.getContext('2d');
      tctx.drawImage(img, 0, 0);
      let imageData = tctx.getImageData(0, 0, tempCanvas.width, tempCanvas.height);
      let data = imageData.data;
      const intensity = (settings.filterIntensity || 100) / 100;
      switch (settings.filter) {
        case 'grayscale':
          for (let i = 0; i < data.length; i += 4) {
            const avg = (data[i] + data[i+1] + data[i+2]) / 3;
            data[i] = data[i+1] = data[i+2] = avg * intensity + data[i]*(1-intensity);
          }
          break;
        case 'sepia':
          for (let i = 0; i < data.length; i += 4) {
            let r = data[i], g = data[i+1], b = data[i+2];
            data[i] = Math.min(255, (r * (1 - intensity)) + (0.393 * r + 0.769 * g + 0.189 * b) * intensity);
            data[i+1] = Math.min(255, (g * (1 - intensity)) + (0.349 * r + 0.686 * g + 0.168 * b) * intensity);
            data[i+2] = Math.min(255, (b * (1 - intensity)) + (0.272 * r + 0.534 * g + 0.131 * b) * intensity);
          }
          break;
        case 'invert':
          for (let i = 0; i < data.length; i += 4) {
            data[i] = 255 - data[i];
            data[i+1] = 255 - data[i+1];
            data[i+2] = 255 - data[i+2];
          }
          break;
        case 'brightness':
          for (let i = 0; i < data.length; i += 4) {
            data[i] = Math.min(255, data[i] * intensity);
            data[i+1] = Math.min(255, data[i+1] * intensity);
            data[i+2] = Math.min(255, data[i+2] * intensity);
          }
          break;
        case 'contrast':
          const factor = (259 * (intensity * 255 + 255)) / (255 * (259 - intensity * 255));
          for (let i = 0; i < data.length; i += 4) {
            data[i] = Math.min(255, factor * (data[i] - 128) + 128);
            data[i+1] = Math.min(255, factor * (data[i+1] - 128) + 128);
            data[i+2] = Math.min(255, factor * (data[i+2] - 128) + 128);
          }
          break;
      }
      tctx.putImageData(imageData, 0, 0);
      source = tempCanvas;
    }
    if (settings.cropEnabled) {
      const cropSize = Math.max(20, Math.min(100, settings.cropSize || 100)) / 100;
      const side = Math.min(img.width, img.height) * cropSize;
      const sx = (img.width - side) * ((settings.cropX || 50) / 100);
      const sy = (img.height - side) * ((settings.cropY || 50) / 100);
      crop = { sx, sy, sw: side, sh: side };
    }
    const baseWidth = crop ? crop.sw : img.width;
    const baseHeight = crop ? crop.sh : img.height;
    const scaleBase = fit === 'contain'
      ? Math.min(size / baseWidth, size / baseHeight)
      : Math.max(size / baseWidth, size / baseHeight);
    const scale = scaleBase * zoom;
    const drawWidth = baseWidth * scale;
    const drawHeight = baseHeight * scale;

    ctx.save();
    ctx.translate(size / 2 + offsetX, size / 2 + offsetY);
    ctx.rotate(rotate);
    if (crop) {
      ctx.drawImage(source, crop.sx, crop.sy, crop.sw, crop.sh, -drawWidth / 2, -drawHeight / 2, drawWidth, drawHeight);
    } else {
      ctx.drawImage(source, -drawWidth / 2, -drawHeight / 2, drawWidth, drawHeight);
    }
    ctx.restore();
  }

  function drawCaption(ctx, size, settings) {
    const caption = state.settings.caption.trim();
    if (!caption) return;
    const offsetX = settings.captionX || 0;
    const offsetY = settings.captionY || 0;
    ctx.save();
    ctx.fillStyle = 'rgba(0, 0, 0, 0.55)';
    ctx.fillRect(0, size - 44 + offsetY, size, 44);
    ctx.fillStyle = '#e7ffff';
    ctx.font = '600 16px "Space Grotesk", sans-serif';
    ctx.textAlign = 'center';
    ctx.fillText(caption, size / 2 + offsetX, size - 16 + offsetY);
    ctx.restore();
  }

  function drawSticker(ctx, img, size, settings) {
    ctx.save();
    ctx.fillStyle = settings.bgColor;
    ctx.fillRect(0, 0, size, size);
    ctx.translate(size / 2, size / 2);
    ctx.shadowColor = 'rgba(0, 0, 0, 0.35)';
    ctx.shadowBlur = settings.shadow;
    ctx.shadowOffsetX = 0;
    ctx.shadowOffsetY = 4;
    ctx.translate(-size / 2, -size / 2);
    drawImageWithSettings(ctx, img, size, settings);
    ctx.shadowBlur = 0;
    ctx.restore();

    if (settings.outline > 0) {
      ctx.save();
      ctx.shadowColor = state.settings.accent;
      ctx.shadowBlur = settings.outline;
      ctx.shadowOffsetX = 0;
      ctx.shadowOffsetY = 0;
      drawImageWithSettings(ctx, img, size, settings);
      ctx.restore();
    }

    const text = state.settings.stickerText.trim();
    if (text) {
      const offsetX = settings.stickerTextX || 0;
      const offsetY = settings.stickerTextY || 0;
      ctx.save();
      ctx.fillStyle = 'rgba(0, 0, 0, 0.55)';
      ctx.fillRect(0, size - 40 + offsetY, size, 40);
      ctx.fillStyle = '#e7ffff';
      ctx.font = '600 15px "Space Grotesk", sans-serif';
      ctx.textAlign = 'center';
      ctx.fillText(text, size / 2 + offsetX, size - 14 + offsetY);
      ctx.restore();
    }
  }

  function drawCard(ctx, size) {
    const accent = state.settings.accent;
    ctx.save();
    const grad = ctx.createLinearGradient(0, 0, size, size);
    grad.addColorStop(0, '#06171f');
    grad.addColorStop(1, accent);
    ctx.fillStyle = grad;
    ctx.fillRect(0, 0, size, size);
    ctx.strokeStyle = 'rgba(255, 255, 255, 0.15)';
    ctx.lineWidth = 2;
    ctx.strokeRect(12, 12, size - 24, size - 24);
    ctx.fillStyle = '#e7ffff';
    ctx.font = '700 20px "Space Grotesk", sans-serif';
    ctx.fillText(state.settings.cardTitle || 'Pulse Card', 28, 60);
    ctx.font = '400 14px "Space Grotesk", sans-serif';
    ctx.fillStyle = 'rgba(231, 255, 255, 0.75)';
    ctx.fillText(state.settings.cardLine || 'Creator note', 28, 88);
    ctx.restore();
  }

  function drawPoster(ctx, size) {
    ctx.save();
    ctx.fillStyle = '#041016';
    ctx.fillRect(0, 0, size, size);
    ctx.fillStyle = state.settings.accent;
    ctx.fillRect(0, size - 60, size, 60);
    ctx.fillStyle = '#041016';
    ctx.font = '700 18px "Oxanium", sans-serif';
    ctx.fillText('LINKUP POSTER', 18, size - 24);
    ctx.restore();
  }

  function drawPreview() {
    const canvas = els.previewCanvas;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    const size = state.settings.size;
    canvas.width = size;
    canvas.height = size;
    ctx.clearRect(0, 0, size, size);

    if (state.mode === 'card') {
      drawCard(ctx, size);
      updateOverlay();
      return;
    }

    if (state.mode === 'poster') {
      drawPoster(ctx, size);
      updateOverlay();
      return;
    }

    const frame = state.frames.find((f) => f.id === state.activeFrameId) || state.frames[0];
    const asset = state.assets.find((a) => a.id === frame?.assetId);
    if (!asset) {
      updateOverlay();
      return;
    }
    const settings = getFrameSettings(frame);
    ctx.fillStyle = settings.bgColor;
    ctx.fillRect(0, 0, size, size);
    const source = applyRemoveBackground(asset.img, settings);
    if (state.mode === 'sticker') {
      drawSticker(ctx, source, size, settings);
    } else {
      drawImageWithSettings(ctx, source, size, settings);
      drawCaption(ctx, size, settings);
    }
    updateOverlay();
  }

  function playPreview() {
    if (state.isPlaying || state.mode !== 'gif' || state.frames.length === 0) return;
    state.isPlaying = true;
    state.playLoops = 0;
    let index = 0;
    const step = () => {
      if (!state.isPlaying) return;
      const frame = state.frames[index % state.frames.length];
      ensureFrameSettings(frame);
      state.activeFrameId = frame.id;
      drawPreview();
      index += 1;
      const delay = frame.settings.delay || state.settings.delay;
      if (index % state.frames.length === 0) {
        state.playLoops += 1;
        if (state.playLoops >= 3) {
          pausePreview();
          return;
        }
      }
      state.playTimer = setTimeout(step, delay);
    };
    step();
  }

  function pausePreview() {
    state.isPlaying = false;
    if (state.playTimer) clearTimeout(state.playTimer);
    state.playTimer = null;
  }

  function buildGif() {
    if (state.frames.length === 0) {
      setStatus('Add frames to build a GIF.');
      return Promise.reject(new Error('no frames'));
    }
    if (!window.GIF) {
      return loadGifLib()
        .then(() => buildGif())
        .catch(() => buildGifServer());
    }
    setRenderStatus('Rendering', 'Building GIF frames...');
    return new Promise((resolve, reject) => {
      const gif = new window.GIF({
        workers: 2,
        quality: 10,
        workerScript: 'https://cdnjs.cloudflare.com/ajax/libs/gif.js/0.2.0/gif.worker.js'
      });
      const size = state.settings.size;
      const offscreen = document.createElement('canvas');
      offscreen.width = size;
      offscreen.height = size;
      const ctx = offscreen.getContext('2d');

      state.frames.forEach((frame) => {
        ensureFrameSettings(frame);
        const asset = state.assets.find((a) => a.id === frame.assetId);
        if (!asset) return;
        const settings = getFrameSettings(frame);
        ctx.clearRect(0, 0, size, size);
        ctx.fillStyle = settings.bgColor;
        ctx.fillRect(0, 0, size, size);
        const source = applyRemoveBackground(asset.img, settings);
        drawImageWithSettings(ctx, source, size, settings);
        drawCaption(ctx, size, settings);
        gif.addFrame(ctx, { copy: true, delay: settings.delay });
      });

      gif.on('finished', (blob) => {
        setRenderStatus('Ready', 'GIF ready.');
        resolve(blob);
      });
      gif.on('abort', () => {
        setRenderStatus('Idle', 'Render stopped.');
        reject(new Error('abort'));
      });
      gif.render();
    });
  }

  function renderFrameToBlob(frame, size) {
    return new Promise((resolve) => {
      const canvas = document.createElement('canvas');
      canvas.width = size;
      canvas.height = size;
      const ctx = canvas.getContext('2d');
      const asset = state.assets.find((a) => a.id === frame.assetId);
      if (!asset) return resolve(null);
      const settings = getFrameSettings(frame);
      ctx.clearRect(0, 0, size, size);
      ctx.fillStyle = settings.bgColor;
      ctx.fillRect(0, 0, size, size);
      const source = applyRemoveBackground(asset.img, settings);
      drawImageWithSettings(ctx, source, size, settings);
      drawCaption(ctx, size, settings);
      canvas.toBlob((blob) => resolve(blob), 'image/png');
    });
  }

  function buildGifServer() {
    if (!csrfToken) {
      setStatus('Missing CSRF token. Reload the page.');
      return Promise.reject(new Error('csrf')); 
    }
    setRenderStatus('Rendering', 'Using server renderer...');
    const size = state.settings.size;
    const form = new FormData();
    form.append('caption', state.settings.caption || '');
    form.append('delay', String(state.settings.delay));
    form.append('size', String(size));
    const frames = state.frames.slice();
    return Promise.all(frames.map((frame) => renderFrameToBlob(frame, size)))
      .then((blobs) => {
        blobs.forEach((blob, index) => {
          if (blob) form.append('frames', blob, `frame-${index}.png`);
        });
        return fetch('/api/media/gif', {
          method: 'POST',
          headers: { 'X-CSRF-Token': csrfToken },
          body: form
        });
      })
      .then((res) => {
        if (!res.ok) throw new Error('server gif failed');
        return res.json();
      })
      .then((data) => {
        if (!data?.item) throw new Error('invalid gif response');
        upsertLibraryItem(data.item);
        selectLibraryItem(data.item.id);
        setRenderStatus('Ready', 'GIF ready.');
        return fetch(data.item.url).then((resp) => resp.blob());
      });
  }

  function exportCurrent() {
    if (state.mode === 'gif') {
      return buildGif().then((blob) => {
        downloadBlob(blob, 'linkup-creator.gif');
        setStatus('GIF downloaded.');
      }).catch(() => {
        setStatus('Unable to render GIF.');
      });
    }
    const canvas = els.previewCanvas;
    if (!canvas) return Promise.resolve();
    return new Promise((resolve) => {
      canvas.toBlob((blob) => {
        if (!blob) return;
        downloadBlob(blob, `linkup-${state.mode}.png`);
        setStatus('File downloaded.');
        resolve();
      }, 'image/png');
    });
  }

  function upsertLibraryItem(item) {
    const index = state.library.findIndex((i) => i.id === item.id);
    if (index >= 0) {
      state.library[index] = item;
    } else {
      state.library.unshift(item);
    }
    renderLibrary();
  }

  function selectLibraryItem(id) {
    state.activeLibraryId = id;
    renderLibrary();
    const item = state.library.find((i) => i.id === id);
    if (els.sendSelection) {
      els.sendSelection.textContent = item ? `${item.title || item.kind} (#${item.id})` : 'None';
    }
  }

  function renderLibrary() {
    if (!els.libraryList) return;
    const filter = els.libraryFilter?.value || 'all';
    const items = state.library.filter((item) => filter === 'all' || item.kind === filter);
    els.libraryList.innerHTML = '';
    if (!items.length) {
      els.libraryList.innerHTML = '<div class="status-note">No saved items yet.</div>';
      return;
    }
    items.forEach((item) => {
      const row = document.createElement('div');
      row.className = 'library-item';
      if (item.id === state.activeLibraryId) row.classList.add('active');
      row.innerHTML = `
        <div class="library-thumb"><img class="thumb-img" src="${item.url}" alt="" /></div>
        <div>
          <div class="asset-name">${escapeHtml(item.title || item.kind)}</div>
          <div class="asset-name">${item.kind.toUpperCase()} • ${new Date(item.created_at || Date.now()).toLocaleDateString()}</div>
        </div>
      `;
      row.addEventListener('click', () => {
        selectLibraryItem(item.id);
        addAssetFromUrl(item.url, item.title || item.kind).then(() => {
          setStatus('Loaded from library.');
        });
      });
      els.libraryList.appendChild(row);
    });
  }

  function loadLibrary() {
    fetch('/api/media/list')
      .then((res) => res.json())
      .then((data) => {
        if (Array.isArray(data?.items)) {
          state.library = data.items;
          renderLibrary();
        }
      })
      .catch(() => {
        setStatus('Could not load library.');
      });
  }

  function loadContacts() {
    fetch('/api/contacts/list')
      .then((res) => res.json())
      .then((data) => {
        state.contacts = Array.isArray(data?.contacts) ? data.contacts : [];
        if (els.sendContactSelect) {
          els.sendContactSelect.innerHTML = '';
          state.contacts.forEach((contact) => {
            const opt = document.createElement('option');
            opt.value = contact.username;
            opt.textContent = contact.display_name || contact.username;
            els.sendContactSelect.appendChild(opt);
          });
        }
      })
      .catch(() => {
        setStatus('Could not load contacts.');
      });
  }

  function sendSelectedToChat() {
    if (!csrfToken) {
      setStatus('Missing CSRF token. Reload the page.');
      return;
    }
    const target = els.sendContactSelect?.value || '';
    const item = state.library.find((i) => i.id === state.activeLibraryId);
    if (!target || !item) {
      setStatus('Pick a contact and a saved item.');
      return;
    }
    fetch(`/api/messages/${encodeURIComponent(target)}/media/${item.id}`, {
      method: 'POST',
      headers: { 'X-CSRF-Token': csrfToken }
    }).then((res) => {
      if (!res.ok) throw new Error('send failed');
      setStatus(`Sent to ${target}.`);
    }).catch(() => {
      setStatus('Send failed.');
    });
  }

  function saveToLinkup() {
    if (!csrfToken) {
      setStatus('Missing CSRF token. Reload the page.');
      return;
    }
    if (state.mode === 'gif') {
      buildGif().then((blob) => {
        const form = new FormData();
        form.append('file', blob, 'creator.gif');
        return fetch('/api/media/upload', {
          method: 'POST',
          headers: { 'X-CSRF-Token': csrfToken },
          body: form
        });
      }).then((res) => {
        if (!res.ok) throw new Error('upload failed');
        return res.json();
      }).then((data) => {
        if (data?.item) {
          upsertLibraryItem(data.item);
          selectLibraryItem(data.item.id);
        }
        setStatus('Saved to LinkUp library.');
      }).catch(() => {
        setStatus('Save failed. Log in and try again.');
      });
      return;
    }

    const canvas = els.previewCanvas;
    if (!canvas) return;
    canvas.toBlob((blob) => {
      if (!blob) return;
      const form = new FormData();
      form.append('file', blob, 'creator.png');
      form.append('caption', state.settings.caption || state.settings.cardTitle || 'creator');
      form.append('size', String(state.settings.size));
      fetch('/api/media/sticker', {
        method: 'POST',
        headers: { 'X-CSRF-Token': csrfToken },
        body: form
      }).then((res) => {
        if (!res.ok) throw new Error('upload failed');
        return res.json();
      }).then((data) => {
        if (data?.item) {
          upsertLibraryItem(data.item);
          selectLibraryItem(data.item.id);
        }
        setStatus('Saved to LinkUp library.');
      }).catch(() => {
        setStatus('Save failed. Log in and try again.');
      });
    }, 'image/png');
  }

  function handleModeChange(mode) {
    state.mode = mode;
    pausePreview();
    if (mode === 'gif') {
      loadGifLib().catch(() => {
        setStatus('GIF.js unavailable. Using server renderer for GIF export.');
      });
    }
    drawPreview();
    updateOverlay();
    if (els.stageSub) {
      const msg = mode === 'gif'
        ? 'Build a GIF from your frame stack.'
        : mode === 'sticker'
          ? 'Craft a sticker from a single frame.'
          : mode === 'card'
            ? 'Create a pulse card with text.'
            : 'Generate a poster grid card.';
      els.stageSub.textContent = msg;
    }
  }

  function bindInputs() {
    els.sizeRange?.addEventListener('input', (e) => {
      state.settings.size = Number(e.target.value || 320);
      drawPreview();
    });
    els.delayRange?.addEventListener('input', (e) => {
      const value = Number(e.target.value || 120);
      updateSetting('delay', value);
    });
    els.frameDelayInput?.addEventListener('input', (e) => {
      const value = Math.max(60, Math.min(1000, Number(e.target.value || 120)));
      updateSetting('delay', value);
      renderFrames();
    });
    els.applyDelayAllBtn?.addEventListener('click', () => {
      const value = Math.max(60, Math.min(1000, Number(els.frameDelayInput?.value || 120)));
      updateSetting('delay', value, true);
      renderFrames();
    });
    els.zoomRange?.addEventListener('input', (e) => {
      updateSetting('zoom', Number(e.target.value || 100) / 100);
      drawPreview();
    });
    els.offsetXRange?.addEventListener('input', (e) => {
      updateSetting('offsetX', Number(e.target.value || 0));
      drawPreview();
    });
    els.offsetYRange?.addEventListener('input', (e) => {
      updateSetting('offsetY', Number(e.target.value || 0));
      drawPreview();
    });
    els.rotateRange?.addEventListener('input', (e) => {
      updateSetting('rotate', Number(e.target.value || 0));
      drawPreview();
    });
    els.fitSelect?.addEventListener('change', (e) => {
      updateSetting('fit', e.target.value || 'cover');
      drawPreview();
    });
    els.captionInput?.addEventListener('input', (e) => {
      state.settings.caption = e.target.value || '';
      drawPreview();
    });
    els.captionXRange?.addEventListener('input', (e) => {
      updateSetting('captionX', Number(e.target.value || 0));
      drawPreview();
    });
    els.captionYRange?.addEventListener('input', (e) => {
      updateSetting('captionY', Number(e.target.value || 0));
      drawPreview();
    });
    els.cropToggle?.addEventListener('change', (e) => {
      updateSetting('cropEnabled', !!e.target.checked);
      drawPreview();
    });
    els.cropResetBtn?.addEventListener('click', () => {
      updateSetting('cropX', 50);
      updateSetting('cropY', 50);
      updateSetting('cropSize', 100);
      if (els.cropXRange) els.cropXRange.value = '50';
      if (els.cropYRange) els.cropYRange.value = '50';
      if (els.cropSizeRange) els.cropSizeRange.value = '100';
      drawPreview();
    });
    els.cropXRange?.addEventListener('input', (e) => {
      updateSetting('cropX', Number(e.target.value || 50));
      drawPreview();
    });
    els.cropYRange?.addEventListener('input', (e) => {
      updateSetting('cropY', Number(e.target.value || 50));
      drawPreview();
    });
    els.cropSizeRange?.addEventListener('input', (e) => {
      updateSetting('cropSize', Number(e.target.value || 100));
      drawPreview();
    });
    els.outlineRange?.addEventListener('input', (e) => {
      updateSetting('outline', Number(e.target.value || 0));
      drawPreview();
    });
    els.shadowRange?.addEventListener('input', (e) => {
      updateSetting('shadow', Number(e.target.value || 0));
      drawPreview();
    });
    els.bgColorInput?.addEventListener('input', (e) => {
      updateSetting('bgColor', e.target.value || '#081c22');
      drawPreview();
    });
    els.stickerTextInput?.addEventListener('input', (e) => {
      state.settings.stickerText = e.target.value || '';
      drawPreview();
    });
    els.stickerTextXRange?.addEventListener('input', (e) => {
      updateSetting('stickerTextX', Number(e.target.value || 0));
      drawPreview();
    });
    els.stickerTextYRange?.addEventListener('input', (e) => {
      updateSetting('stickerTextY', Number(e.target.value || 0));
      drawPreview();
    });
    els.removeBgToggle?.addEventListener('change', (e) => {
      updateSetting('removeBg', !!e.target.checked);
      drawPreview();
    });
    els.removeBgColor?.addEventListener('input', (e) => {
      updateSetting('removeBgColor', e.target.value || '#031016');
      drawPreview();
    });
    els.removeBgTolerance?.addEventListener('input', (e) => {
      updateSetting('removeBgTolerance', Number(e.target.value || 0));
      drawPreview();
    });
    els.cardTitleInput?.addEventListener('input', (e) => {
      state.settings.cardTitle = e.target.value || '';
      drawPreview();
    });
    els.cardLineInput?.addEventListener('input', (e) => {
      state.settings.cardLine = e.target.value || '';
      drawPreview();
    });
    els.accentColorInput?.addEventListener('input', (e) => {
      state.settings.accent = e.target.value || '#62e6d9';
      drawPreview();
    });
  }

  function bindEvents() {
    els.assetInput?.addEventListener('change', (e) => {
      const files = Array.from(e.target.files || []);
      Promise.all(files.map(addAssetFromFile)).then(() => {
        setStatus('Assets added.');
      });
    });

    els.dropzone?.addEventListener('dragover', (e) => {
      e.preventDefault();
      els.dropzone.classList.add('active');
    });
    els.dropzone?.addEventListener('dragleave', () => {
      els.dropzone.classList.remove('active');
    });
    els.dropzone?.addEventListener('drop', (e) => {
      e.preventDefault();
      els.dropzone.classList.remove('active');
      const files = Array.from(e.dataTransfer?.files || []);
      Promise.all(files.map(addAssetFromFile)).then(() => {
        setStatus('Assets added.');
      });
    });

    document.querySelectorAll('[data-preset]').forEach((btn) => {
      btn.addEventListener('click', () => applyPreset(btn.getAttribute('data-preset') || ''));
    });

    els.resetEditsBtn?.addEventListener('click', () => applyQuickEdit('reset'));
    els.centerEditsBtn?.addEventListener('click', () => applyQuickEdit('center'));
    els.fitCoverBtn?.addEventListener('click', () => applyQuickEdit('fit-cover'));
    els.fitContainBtn?.addEventListener('click', () => applyQuickEdit('fit-contain'));

    els.clearFramesBtn?.addEventListener('click', () => {
      state.frames = [];
      state.activeFrameId = null;
      renderFrames();
      drawPreview();
    });

    els.reverseFramesBtn?.addEventListener('click', () => {
      state.frames.reverse();
      renderFrames();
    });

    document.getElementById('duplicateFrameBtn')?.addEventListener('click', duplicateActiveFrame);
    document.getElementById('removeFrameBtn')?.addEventListener('click', () => {
      if (state.activeFrameId) removeFrame(state.activeFrameId);
    });

    els.playBtn?.addEventListener('click', playPreview);
    els.pauseBtn?.addEventListener('click', pausePreview);
    els.exportBtn?.addEventListener('click', exportCurrent);
    els.downloadBtn?.addEventListener('click', exportCurrent);
    els.saveBtn?.addEventListener('click', saveToLinkup);

    els.libraryRefreshBtn?.addEventListener('click', loadLibrary);
    els.libraryFilter?.addEventListener('change', renderLibrary);
    els.sendBtn?.addEventListener('click', sendSelectedToChat);

    const openLibrary = () => {
      els.libraryModal?.classList.add('show');
      els.libraryScrim?.classList.add('show');
      els.libraryModal?.setAttribute('aria-hidden', 'false');
      els.libraryScrim?.setAttribute('aria-hidden', 'false');
      if (location.hash !== '#libraryModal') {
        history.replaceState(null, '', '#libraryModal');
      }
      loadLibrary();
    };
    const closeLibrary = () => {
      els.libraryModal?.classList.remove('show');
      els.libraryScrim?.classList.remove('show');
      els.libraryModal?.setAttribute('aria-hidden', 'true');
      els.libraryScrim?.setAttribute('aria-hidden', 'true');
      if (location.hash === '#libraryModal') {
        history.replaceState(null, '', '#');
      }
    };

    els.navLibraryBtn?.addEventListener('click', openLibrary);
    els.libraryCloseBtn?.addEventListener('click', closeLibrary);
    els.libraryScrim?.addEventListener('click', closeLibrary);

    els.navDraftsBtn?.addEventListener('click', () => {
      setStatus('Drafts are coming soon.');
      openLibrary();
    });
    els.navCaptureBtn?.addEventListener('click', () => {
      scrollToId('dropzone');
      els.assetInput?.click();
    });
    els.newSessionBtn?.addEventListener('click', () => {
      state.assets = [];
      state.frames = [];
      state.activeFrameId = null;
      renderAssets();
      renderFrames();
      drawPreview();
      setStatus('Session cleared.');
      initSamples();
    });
    els.quickTourBtn?.addEventListener('click', () => {
      openTour();
    });

    els.tourNextBtn?.addEventListener('click', nextTour);
    els.tourPrevBtn?.addEventListener('click', prevTour);
    els.tourSkipBtn?.addEventListener('click', closeTour);
    els.tourScrim?.addEventListener('click', closeTour);

    els.modeList?.querySelectorAll('.mode-btn').forEach((btn) => {
      btn.addEventListener('click', () => {
        els.modeList.querySelectorAll('.mode-btn').forEach((b) => b.classList.remove('active'));
        btn.classList.add('active');
        handleModeChange(btn.dataset.mode || 'gif');
      });
    });

    els.previewCanvas?.addEventListener('click', () => {
      if (state.mode === 'gif') {
        pausePreview();
        playPreview();
      }
    });
  }

  function initSamples() {
    Promise.all(sampleAssets.map((asset) => addAssetFromUrl(asset.url, asset.name)))
      .catch(() => {
        // ignore sample load failures
      });
  }

  const tourSteps = [
    { selector: '.dropzone', title: 'Asset Bay', text: 'Drop images here or click to upload.' },
    { selector: '#frameList', title: 'Frame Stack', text: 'Pick assets to build a frame sequence.' },
    { selector: '.stage', title: 'Creator Canvas', text: 'Preview and tweak crop, zoom, and caption.' },
    { selector: '.timeline', title: 'Timeline', text: 'Drag frames to reorder and edit per-frame delay.' },
    { selector: '#sendPanel', title: 'Send to Chat', text: 'Save to library and send to a contact.' }
  ];

  let tourIndex = 0;
  let activeHighlight = null;

  function clearHighlight() {
    if (activeHighlight) {
      activeHighlight.classList.remove('tour-highlight');
      activeHighlight = null;
    }
  }

  function showTourStep(index) {
    const step = tourSteps[index];
    if (!step) return;
    const target = document.querySelector(step.selector);
    if (!target) return;
    clearHighlight();
    activeHighlight = target;
    activeHighlight.classList.add('tour-highlight');
    const rect = target.getBoundingClientRect();
    const card = els.tourCard;
    if (card) {
      const top = Math.min(window.innerHeight - 180, rect.bottom + 12);
      const left = Math.min(window.innerWidth - 360, rect.left);
      card.style.top = `${Math.max(16, top)}px`;
      card.style.left = `${Math.max(16, left)}px`;
    }
    if (els.tourStep) els.tourStep.textContent = String(index + 1).padStart(2, '0');
    if (els.tourTitle) els.tourTitle.textContent = step.title;
    if (els.tourText) els.tourText.textContent = step.text;
  }

  function openTour() {
    tourIndex = 0;
    els.tourScrim?.classList.add('show');
    els.tourCard?.classList.add('show');
    els.tourScrim?.setAttribute('aria-hidden', 'false');
    els.tourCard?.setAttribute('aria-hidden', 'false');
    showTourStep(tourIndex);
  }

  function closeTour() {
    clearHighlight();
    els.tourScrim?.classList.remove('show');
    els.tourCard?.classList.remove('show');
    els.tourScrim?.setAttribute('aria-hidden', 'true');
    els.tourCard?.setAttribute('aria-hidden', 'true');
  }

  function nextTour() {
    if (tourIndex < tourSteps.length - 1) {
      tourIndex += 1;
      showTourStep(tourIndex);
    } else {
      closeTour();
    }
  }

  function prevTour() {
    if (tourIndex > 0) {
      tourIndex -= 1;
      showTourStep(tourIndex);
    }
  }

  function init() {
    bindEvents();
    bindInputs();
    requestAnimationFrame(() => initSamples());
    drawPreview();
    if (typeof requestIdleCallback === 'function') {
      requestIdleCallback(() => loadContacts());
    } else {
      setTimeout(() => loadContacts(), 300);
    }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
