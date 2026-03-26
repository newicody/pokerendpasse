/**
 * settings_manager.js — Gestionnaire centralisé des paramètres client
 * Toutes les pages du projet importent ce fichier.
 */

const SettingsManager = (() => {
    const STORAGE_KEY = 'poker_settings';

    const DEFAULTS = {
        // Audio
        sound:        'on',           // 'on' | 'off'
        soundVolume:  0.5,            // 0–1

        // Apparence
        theme:        'dark',         // voir ThemeManager.list()
        customCss:    '',
        customCssUrl: '',

        // Jeu
        animationSpeed: 'normal',     // 'fast' | 'normal' | 'slow'
        cardDisplay:    'standard',   // 'standard' | 'large' | '4color'
        autoAction:     'never',      // 'never' | 'check_fold' | 'call_any'
        showHistory:    'all',        // 'all' | 'mine' | 'none'
        tableBackground:'felt',       // 'felt' | 'wood' | 'marble'
        chatNotifications: 'on',      // 'on' | 'off'
        actionTimer:    30,           // secondes
    };

    function _load() {
        try {
            return { ...DEFAULTS, ...JSON.parse(localStorage.getItem(STORAGE_KEY) || '{}') };
        } catch (e) {
            return { ...DEFAULTS };
        }
    }

    function _save(settings) {
        try {
            localStorage.setItem(STORAGE_KEY, JSON.stringify(settings));
        } catch (e) { /* quota dépassé ou navigation privée */ }
    }

    return {
        defaults: DEFAULTS,

        load()  { return _load(); },
        save(s) { _save({ ..._load(), ...s }); },

        get(key)        { return _load()[key]; },
        set(key, value) { const s = _load(); s[key] = value; _save(s); },

        reset() { _save({ ...DEFAULTS }); },

        /** Remplit un formulaire HTML depuis les settings */
        populateForm(formEl) {
            if (!formEl) return;
            const s = _load();
            Object.entries(s).forEach(([key, val]) => {
                const el = formEl.querySelector(`[id="${key}"], [name="${key}"]`);
                if (!el) return;
                if (el.type === 'checkbox') el.checked = (val === true || val === 'on');
                else el.value = val;
            });
        },

        /** Lit un formulaire HTML et sauvegarde */
        saveFromForm(formEl) {
            if (!formEl) return;
            const s   = _load();
            const els = formEl.querySelectorAll('[id], [name]');
            els.forEach(el => {
                const key = el.id || el.name;
                if (!(key in DEFAULTS)) return;
                s[key] = (el.type === 'checkbox') ? (el.checked ? 'on' : 'off') : el.value;
            });
            _save(s);
            return s;
        },
    };
})();

window.SettingsManager = SettingsManager;
