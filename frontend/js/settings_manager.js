/**
 * settings_manager.js — Gestionnaire centralisé des paramètres client
 * Version unifiée (remplace settings.js ET settings_manager.js)
 */

const SettingsManager = (() => {
    const STORAGE_KEY = 'poker_settings';

    const DEFAULTS = {
        sound:            'on',
        soundVolume:      0.5,
        theme:            'dark',
        animationSpeed:   'normal',
        cardDisplay:      'standard',
        autoAction:       'never',
        showHistory:      'all',
        tableBackground:  'felt',
        chatNotifications:'on',
        actionTimer:      30,
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
        } catch (e) { /* quota ou navigation privée */ }
    }

    return {
        defaults: DEFAULTS,
        load()            { return _load(); },
        save(s)           { _save({ ..._load(), ...s }); },
        get(key)          { return _load()[key]; },
        set(key, value)   { const s = _load(); s[key] = value; _save(s); },
        reset()           { _save({ ...DEFAULTS }); },
    };
})();

window.SettingsManager = SettingsManager;
// Compat ancienne API
window.settings = SettingsManager;
