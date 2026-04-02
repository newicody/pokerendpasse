/**
 * theme_manager.js — Gestionnaire de thèmes visuels
 */
const ThemeManager = (() => {
    const THEMES = {
        dark: {
            '--bg-primary': '#0d1f0d',
            '--bg-secondary': 'rgba(0,0,0,0.6)',
            '--bg-tertiary': 'rgba(0,0,0,0.4)',
            '--accent': '#ffd700',
            '--accent-light': '#ffb347',
            '--accent-rgb': '255,215,0',
            '--text-primary': '#ffffff',
            '--text-secondary': 'rgba(255,255,255,0.7)',
            '--text-muted': 'rgba(255,255,255,0.5)',
            '--border-color': 'rgba(255,215,0,0.3)',
            '--border-subtle': 'rgba(255,255,255,0.1)',
            '--success': '#27ae60',
            '--danger': '#e74c3c',
            '--warning': '#ff9800',
            '--info': '#3498db',
            '--table-felt': '#1a5c2e',
            '--table-border': '#8b6914',
        },
        light: {
            '--bg-primary': '#f0f0f0',
            '--bg-secondary': 'rgba(255,255,255,0.9)',
            '--bg-tertiary': 'rgba(255,255,255,0.7)',
            '--accent': '#2c7a2c',
            '--accent-light': '#3a9a3a',
            '--accent-rgb': '44,122,44',
            '--text-primary': '#1a1a1a',
            '--text-secondary': 'rgba(0,0,0,0.7)',
            '--text-muted': 'rgba(0,0,0,0.5)',
            '--border-color': 'rgba(44,122,44,0.3)',
            '--border-subtle': 'rgba(0,0,0,0.1)',
            '--success': '#27ae60',
            '--danger': '#e74c3c',
            '--warning': '#e67e22',
            '--info': '#2980b9',
            '--table-felt': '#2e8b57',
            '--table-border': '#8b7355',
        },
        neon: {
            '--bg-primary': '#0a0a1a',
            '--bg-secondary': 'rgba(0,0,20,0.8)',
            '--bg-tertiary': 'rgba(0,0,30,0.6)',
            '--accent': '#00ff88',
            '--accent-light': '#00ffcc',
            '--accent-rgb': '0,255,136',
            '--text-primary': '#e0e0ff',
            '--text-secondary': 'rgba(224,224,255,0.7)',
            '--text-muted': 'rgba(224,224,255,0.5)',
            '--border-color': 'rgba(0,255,136,0.4)',
            '--border-subtle': 'rgba(0,255,136,0.1)',
            '--success': '#00ff88',
            '--danger': '#ff3366',
            '--warning': '#ffaa00',
            '--info': '#00aaff',
            '--table-felt': '#0d1a2a',
            '--table-border': '#00ff88',
        },
        blue: {
            '--bg-primary': '#0a1628',
            '--bg-secondary': 'rgba(10,22,40,0.8)',
            '--bg-tertiary': 'rgba(10,22,40,0.5)',
            '--accent': '#4da6ff',
            '--accent-light': '#80bfff',
            '--accent-rgb': '77,166,255',
            '--text-primary': '#e0e8f0',
            '--text-secondary': 'rgba(224,232,240,0.7)',
            '--text-muted': 'rgba(224,232,240,0.5)',
            '--border-color': 'rgba(77,166,255,0.3)',
            '--border-subtle': 'rgba(77,166,255,0.1)',
            '--success': '#27ae60',
            '--danger': '#e74c3c',
            '--warning': '#f39c12',
            '--info': '#4da6ff',
            '--table-felt': '#1a3050',
            '--table-border': '#4da6ff',
        },
        red: {
            '--bg-primary': '#1a0a0a',
            '--bg-secondary': 'rgba(30,10,10,0.8)',
            '--bg-tertiary': 'rgba(30,10,10,0.5)',
            '--accent': '#ff4444',
            '--accent-light': '#ff7777',
            '--accent-rgb': '255,68,68',
            '--text-primary': '#f0e0e0',
            '--text-secondary': 'rgba(240,224,224,0.7)',
            '--text-muted': 'rgba(240,224,224,0.5)',
            '--border-color': 'rgba(255,68,68,0.3)',
            '--border-subtle': 'rgba(255,68,68,0.1)',
            '--success': '#27ae60',
            '--danger': '#ff4444',
            '--warning': '#ff9800',
            '--info': '#3498db',
            '--table-felt': '#2a1010',
            '--table-border': '#8b2020',
        },
    };

    let _current = 'dark';

    function setTheme(name) {
        const vars = THEMES[name];
        if (!vars) return;
        _current = name;
        const root = document.documentElement;
        for (const [prop, val] of Object.entries(vars)) {
            root.style.setProperty(prop, val);
        }
        document.body.setAttribute('data-theme', name);
        try { localStorage.setItem('poker_theme', name); } catch(e) {}
        // Synchroniser avec SettingsManager
        if (typeof SettingsManager !== 'undefined') {
            SettingsManager.set('theme', name);
        }
    }
  function getTheme() { return _current; }
    function getAvailable() { return Object.keys(THEMES); }

    // Charger depuis localStorage ou SettingsManager
    try {
        let saved = null;
        if (typeof SettingsManager !== 'undefined') {
            saved = SettingsManager.get('theme');
        }
        if (!saved) saved = localStorage.getItem('poker_theme');
        if (saved && THEMES[saved]) setTheme(saved);
    } catch(e) {}

    return { setTheme, getTheme, getAvailable };
})();

window.ThemeManager = ThemeManager;
