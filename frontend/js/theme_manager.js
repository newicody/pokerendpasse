/**
 * theme_manager.js — Gestionnaire de thèmes poker
 * Gère : sélection du thème, CSS custom, variables CSS dynamiques.
 */

const ThemeManager = (() => {
    const THEMES = {
        dark: {
            label: '🌑 Dark (défaut)',
            vars: {
                '--bg-primary':      '#0d1f0d',
                '--bg-secondary':    'rgba(0,0,0,0.6)',
                '--accent':          '#ffd700',
                '--accent-light':    '#ffb347',
                '--text-primary':    '#ffffff',
                '--text-secondary':  'rgba(255,255,255,0.7)',
                '--border-color':    'rgba(255,215,0,0.3)',
                '--card-bg':         'rgba(0,0,0,0.6)',
                '--felt-color':      '#1a472a',
                '--shadow-color':    'rgba(0,0,0,0.5)',
            },
        },
        green: {
            label: '♠ Classic Green',
            vars: {
                '--bg-primary':      '#0a2a0a',
                '--bg-secondary':    'rgba(0,40,0,0.7)',
                '--accent':          '#00e676',
                '--accent-light':    '#69f0ae',
                '--text-primary':    '#e8f5e9',
                '--text-secondary':  'rgba(200,255,200,0.7)',
                '--border-color':    'rgba(0,230,118,0.3)',
                '--card-bg':         'rgba(0,30,0,0.7)',
                '--felt-color':      '#1b5e20',
                '--shadow-color':    'rgba(0,0,0,0.6)',
            },
        },
        neon: {
            label: '💜 Neon Night',
            vars: {
                '--bg-primary':      '#0a0015',
                '--bg-secondary':    'rgba(20,0,50,0.8)',
                '--accent':          '#e040fb',
                '--accent-light':    '#ff80ab',
                '--text-primary':    '#f3e5f5',
                '--text-secondary':  'rgba(220,190,255,0.7)',
                '--border-color':    'rgba(224,64,251,0.4)',
                '--card-bg':         'rgba(15,0,40,0.8)',
                '--felt-color':      '#1a0033',
                '--shadow-color':    'rgba(100,0,150,0.4)',
            },
        },
        royal: {
            label: '👑 Royal Blue',
            vars: {
                '--bg-primary':      '#0a0f2e',
                '--bg-secondary':    'rgba(0,10,50,0.7)',
                '--accent':          '#42a5f5',
                '--accent-light':    '#80d8ff',
                '--text-primary':    '#e3f2fd',
                '--text-secondary':  'rgba(180,210,255,0.7)',
                '--border-color':    'rgba(66,165,245,0.3)',
                '--card-bg':         'rgba(0,10,40,0.7)',
                '--felt-color':      '#0d2060',
                '--shadow-color':    'rgba(0,30,100,0.5)',
            },
        },
        crimson: {
            label: '🔴 Crimson',
            vars: {
                '--bg-primary':      '#1a0000',
                '--bg-secondary':    'rgba(40,0,0,0.7)',
                '--accent':          '#ef5350',
                '--accent-light':    '#ff8a80',
                '--text-primary':    '#ffebee',
                '--text-secondary':  'rgba(255,200,200,0.7)',
                '--border-color':    'rgba(239,83,80,0.3)',
                '--card-bg':         'rgba(30,0,0,0.7)',
                '--felt-color':      '#5d0000',
                '--shadow-color':    'rgba(80,0,0,0.5)',
            },
        },
        light: {
            label: '☀️ Light',
            vars: {
                '--bg-primary':      '#f5f5f5',
                '--bg-secondary':    'rgba(255,255,255,0.8)',
                '--accent':          '#1565c0',
                '--accent-light':    '#42a5f5',
                '--text-primary':    '#212121',
                '--text-secondary':  'rgba(0,0,0,0.6)',
                '--border-color':    'rgba(21,101,192,0.3)',
                '--card-bg':         'rgba(255,255,255,0.85)',
                '--felt-color':      '#2e7d32',
                '--shadow-color':    'rgba(0,0,0,0.2)',
            },
        },
    };

    let _current = 'dark';

    function _applyVars(vars) {
        const root = document.documentElement;
        Object.entries(vars).forEach(([k, v]) => root.style.setProperty(k, v));
    }

    function _applyCustomCss(css) {
        let tag = document.getElementById('poker-custom-css');
        if (!tag) {
            tag = document.createElement('style');
            tag.id = 'poker-custom-css';
            document.head.appendChild(tag);
        }
        tag.textContent = css || '';
    }

    function _applyCustomUrl(url) {
        let tag = document.getElementById('poker-custom-css-link');
        if (url) {
            if (!tag) {
                tag = document.createElement('link');
                tag.id   = 'poker-custom-css-link';
                tag.rel  = 'stylesheet';
                document.head.appendChild(tag);
            }
            tag.href = url;
        } else if (tag) {
            tag.remove();
        }
    }

    return {
        /** Tous les thèmes disponibles */
        list() { return Object.entries(THEMES).map(([id, t]) => ({ id, label: t.label })); },

        /** Applique un thème par son ID */
        apply(themeId) {
            const theme = THEMES[themeId];
            if (!theme) {
                console.warn(`Thème inconnu : ${themeId}`);
                return;
            }
            _current = themeId;

            // Supprimer les anciennes classes de thème
            document.body.className = document.body.className
                .replace(/\btheme-\S+/g, '')
                .trim();
            document.body.classList.add(`theme-${themeId}`);

            _applyVars(theme.vars);
        },

        /** Thème courant */
        current() { return _current; },

        /** Charge et applique les préférences depuis localStorage */
        load() {
            try {
                const s = JSON.parse(localStorage.getItem('poker_settings') || '{}');
                this.apply(s.theme || 'dark');
                _applyCustomCss(s.customCss || '');
                _applyCustomUrl(s.customCssUrl || '');
            } catch (e) {
                this.apply('dark');
            }
        },

        /** Sauvegarde les préférences (appelé depuis le modal options) */
        save(themeId, customCss = '', customCssUrl = '') {
            try {
                const s = JSON.parse(localStorage.getItem('poker_settings') || '{}');
                s.theme       = themeId;
                s.customCss   = customCss;
                s.customCssUrl = customCssUrl;
                localStorage.setItem('poker_settings', JSON.stringify(s));
            } catch (e) { /* ignore */ }
            this.apply(themeId);
            _applyCustomCss(customCss);
            _applyCustomUrl(customCssUrl);
        },

        /** Applique du CSS admin (depuis la page admin) */
        applyAdmin(theme, css, url) {
            this.save(theme, css, url);
        },

        /** Populate un <select> avec les thèmes */
        populateSelect(selectEl) {
            if (!selectEl) return;
            selectEl.innerHTML = this.list()
                .map(t => `<option value="${t.id}" ${t.id === _current ? 'selected' : ''}>${t.label}</option>`)
                .join('');
        },
    };
})();

window.ThemeManager = ThemeManager;
