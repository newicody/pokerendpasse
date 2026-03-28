/**
 * theme_manager.js — Gestionnaire de thèmes poker
 * Gère : sélection du thème, CSS custom, variables CSS dynamiques.
 * Version corrigée avec application correcte des variables
 */
'use strict';

const ThemeManager = (() => {
    const THEMES = {
        dark: {
            label: '🌑 Dark (défaut)',
            className: 'theme-dark'
        },
        green: {
            label: '♠ Classic Green',
            className: 'theme-green'
        },
        neon: {
            label: '💜 Neon Night',
            className: 'theme-neon'
        },
        royal: {
            label: '👑 Royal Blue',
            className: 'theme-royal'
        },
        crimson: {
            label: '🔴 Crimson',
            className: 'theme-crimson'
        },
        light: {
            label: '☀️ Light',
            className: 'theme-light'
        }
    };

    let _current = 'dark';

    /**
     * Applique le CSS personnalisé
     */
    function _applyCustomCss(css) {
        let tag = document.getElementById('poker-custom-css');
        if (!tag) {
            tag = document.createElement('style');
            tag.id = 'poker-custom-css';
            document.head.appendChild(tag);
        }
        tag.textContent = css || '';
    }

    /**
     * Applique une URL CSS externe
     */
    function _applyCustomUrl(url) {
        let tag = document.getElementById('poker-custom-css-link');
        if (url) {
            if (!tag) {
                tag = document.createElement('link');
                tag.id = 'poker-custom-css-link';
                tag.rel = 'stylesheet';
                document.head.appendChild(tag);
            }
            tag.href = url;
        } else if (tag) {
            tag.remove();
        }
    }

    return {
        /** Tous les thèmes disponibles */
        list() {
            return Object.entries(THEMES).map(([id, t]) => ({
                id,
                label: t.label
            }));
        },

        /** Applique un thème par son ID */
        apply(themeId) {
            const theme = THEMES[themeId];
            if (!theme) {
                console.warn(`Thème inconnu : ${themeId}, utilisation du thème dark`);
                themeId = 'dark';
            }
            
            _current = themeId;

            // Supprimer toutes les anciennes classes de thème
            document.body.className = document.body.className
                .replace(/\btheme-\S+/g, '')
                .trim();
            
            // Appliquer la nouvelle classe
            document.body.classList.add(THEMES[themeId].className);
            
            // Forcer le recalcul des styles
            document.body.offsetHeight;
            
            console.log(`Theme applied: ${themeId}`);
        },

        /** Thème courant */
        current() {
            return _current;
        },

        /** Charge et applique les préférences depuis localStorage */
        load() {
            try {
                const stored = JSON.parse(localStorage.getItem('poker_settings') || '{}');
                const themeId = stored.theme || 'dark';
                this.apply(themeId);
                _applyCustomCss(stored.customCss || '');
                _applyCustomUrl(stored.customCssUrl || '');
            } catch (e) {
                console.error('Error loading theme:', e);
                this.apply('dark');
            }
        },

        /** Sauvegarde les préférences */
        save(themeId, customCss = '', customCssUrl = '') {
            try {
                const stored = JSON.parse(localStorage.getItem('poker_settings') || '{}');
                stored.theme = themeId;
                stored.customCss = customCss;
                stored.customCssUrl = customCssUrl;
                localStorage.setItem('poker_settings', JSON.stringify(stored));
            } catch (e) {
                console.error('Error saving theme:', e);
            }
            
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

        /** Toggle entre les thèmes */
        toggle() {
            const themes = Object.keys(THEMES);
            const currentIndex = themes.indexOf(_current);
            const nextIndex = (currentIndex + 1) % themes.length;
            this.apply(themes[nextIndex]);
            this.save(themes[nextIndex]);
            return themes[nextIndex];
        }
    };
})();

// Export global
window.ThemeManager = ThemeManager;

// Auto-load au chargement de la page
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => ThemeManager.load());
} else {
    ThemeManager.load();
}
