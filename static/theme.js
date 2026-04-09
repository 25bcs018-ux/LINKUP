(() => {
  const THEME_KEY_BASE = 'linkup_bg_theme_v1';
  const DEFAULT_THEME = {
    base: '#7c3aed',
    intensity: 70,
  };
  let currentUserId = '';

  function safeUserId(raw) {
    return String(raw || '').trim().toLowerCase().slice(0, 64);
  }

  function themeKey() {
    if (currentUserId) {
      return `${THEME_KEY_BASE}:${currentUserId}`;
    }
    return THEME_KEY_BASE;
  }

  function isThemeLockedDefault() {
    const lock = document.documentElement?.dataset?.themeLock || '';
    return String(lock).trim().toLowerCase() === 'default';
  }

  function clamp(n, min, max) {
    return Math.min(max, Math.max(min, n));
  }

  function hexToRgb(hex) {
    const raw = String(hex || '').trim().replace('#', '');
    if (raw.length !== 6) return { r: 124, g: 58, b: 237 };
    const r = parseInt(raw.slice(0, 2), 16);
    const g = parseInt(raw.slice(2, 4), 16);
    const b = parseInt(raw.slice(4, 6), 16);
    if ([r, g, b].some((v) => Number.isNaN(v))) return { r: 124, g: 58, b: 237 };
    return { r, g, b };
  }

  function mix(a, b, t) {
    const k = clamp(t, 0, 1);
    return {
      r: Math.round(a.r + (b.r - a.r) * k),
      g: Math.round(a.g + (b.g - a.g) * k),
      b: Math.round(a.b + (b.b - a.b) * k),
    };
  }

  function toRgbString(rgb) {
    return `rgb(${rgb.r}, ${rgb.g}, ${rgb.b})`;
  }

  function toRgbaString(rgb, alpha) {
    const a = clamp(alpha, 0, 1).toFixed(3);
    return `rgba(${rgb.r}, ${rgb.g}, ${rgb.b}, ${a})`;
  }

  function computeTheme(baseHex, intensity) {
    const base = hexToRgb(baseHex);
    const deep = { r: 8, g: 10, b: 20 };
    const deep2 = { r: 11, g: 18, b: 37 };
    const accent1 = { r: 255, g: 45, b: 149 };
    const accent2 = { r: 34, g: 211, b: 238 };
    const accent3 = { r: 168, g: 85, b: 247 };

    const strength = clamp((Number(intensity) || 0) / 100, 0, 1);
    const bg0 = mix(base, deep, 0.82);
    const bg1 = mix(base, deep2, 0.78);
    const glowA = mix(base, accent1, 0.55);
    const glowB = mix(base, accent2, 0.5);
    const glowC = mix(base, accent3, 0.45);

    const glowAlpha1 = 0.08 + (0.2 * strength);
    const glowAlpha2 = 0.06 + (0.16 * strength);
    const glowAlpha3 = 0.05 + (0.14 * strength);
    const orbAlpha1 = 0.22 + (0.28 * strength);
    const orbAlpha2 = 0.18 + (0.24 * strength);

    const panel = mix(base, deep2, 0.58);
    const panel2 = mix(base, deep, 0.62);
    const glass = toRgbaString(panel, 0.78);
    const glassStrong = toRgbaString(panel, 0.9);
    const glassSoft = toRgbaString(panel2, 0.75);
    const panelGrad = `linear-gradient(160deg, ${toRgbaString(panel, 0.96)}, ${toRgbaString(panel2, 0.78)})`;
    const panelGradStrong = `linear-gradient(160deg, ${toRgbaString(panel, 0.98)}, ${toRgbaString(panel2, 0.82)})`;
    const panelGradSoft = `linear-gradient(160deg, ${toRgbaString(panel, 0.86)}, ${toRgbaString(panel2, 0.72)})`;

    return {
      bg0: toRgbString(bg0),
      bg1: toRgbString(bg1),
      glow1: toRgbaString(glowA, glowAlpha1),
      glow2: toRgbaString(glowB, glowAlpha2),
      glow3: toRgbaString(glowC, glowAlpha3),
      orb1: toRgbaString(glowA, orbAlpha1),
      orb2: toRgbaString(glowB, orbAlpha2),
      panel: toRgbString(panel),
      panel2: toRgbString(panel2),
      glass,
      glassStrong,
      glassSoft,
      panelGrad,
      panelGradStrong,
      panelGradSoft,
    };
  }

  function applyTheme(theme) {
    const data = theme && typeof theme === 'object' ? theme : DEFAULT_THEME;
    const base = data.base || DEFAULT_THEME.base;
    const intensity = clamp(Number(data.intensity) || DEFAULT_THEME.intensity, 0, 100);
    const resolved = computeTheme(base, intensity);
    const root = document.documentElement;
    root.style.setProperty('--theme-bg0', resolved.bg0);
    root.style.setProperty('--theme-bg1', resolved.bg1);
    root.style.setProperty('--theme-glow1', resolved.glow1);
    root.style.setProperty('--theme-glow2', resolved.glow2);
    root.style.setProperty('--theme-glow3', resolved.glow3);
    root.style.setProperty('--theme-orb1', resolved.orb1);
    root.style.setProperty('--theme-orb2', resolved.orb2);
    root.style.setProperty('--theme-panel', resolved.panel);
    root.style.setProperty('--theme-panel2', resolved.panel2);
    root.style.setProperty('--theme-glass', resolved.glass);
    root.style.setProperty('--theme-glass-strong', resolved.glassStrong);
    root.style.setProperty('--theme-glass-soft', resolved.glassSoft);
    root.style.setProperty('--theme-panel-grad', resolved.panelGrad);
    root.style.setProperty('--theme-panel-grad-strong', resolved.panelGradStrong);
    root.style.setProperty('--theme-panel-grad-soft', resolved.panelGradSoft);
  }

  function loadTheme() {
    try {
      if (isThemeLockedDefault()) return { ...DEFAULT_THEME };
      const raw = localStorage.getItem(themeKey());
      if (!raw) return { ...DEFAULT_THEME };
      const data = JSON.parse(raw);
      if (!data || typeof data !== 'object') return { ...DEFAULT_THEME };
      return {
        base: data.base || DEFAULT_THEME.base,
        intensity: clamp(Number(data.intensity) || DEFAULT_THEME.intensity, 0, 100),
      };
    } catch {
      return { ...DEFAULT_THEME };
    }
  }

  function saveTheme(theme) {
    try {
      if (isThemeLockedDefault()) return;
      localStorage.setItem(themeKey(), JSON.stringify(theme || DEFAULT_THEME));
    } catch {
      // ignore storage failures
    }
  }

  function resetTheme() {
    try {
      if (isThemeLockedDefault()) {
        applyTheme(DEFAULT_THEME);
        return { ...DEFAULT_THEME };
      }
      localStorage.removeItem(themeKey());
    } catch {
      // ignore
    }
    applyTheme(DEFAULT_THEME);
    return { ...DEFAULT_THEME };
  }

  function initTheme() {
    const locked = isThemeLockedDefault();
    const bootUser = locked ? '' : safeUserId(document.documentElement?.dataset?.themeUser || '');
    if (bootUser) {
      currentUserId = bootUser;
    }
    applyTheme(loadTheme());
  }

  function setUserId(userId) {
    if (isThemeLockedDefault()) return;
    const next = safeUserId(userId);
    if (next === currentUserId) return;
    currentUserId = next;
    initTheme();
  }

  window.LinkupTheme = {
    DEFAULT_THEME,
    computeTheme,
    applyTheme,
    loadTheme,
    saveTheme,
    resetTheme,
    setUserId,
  };

  initTheme();
})();
