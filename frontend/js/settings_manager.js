// frontend/js/settings_manager.js
/**
 * settings_manager.js — Gestionnaire centralisé des paramètres client
 */

const SettingsManager = (() => {
    const STORAGE_KEY = 'poker_settings';
    const DEFAULTS = {
        // Apparence
        theme: 'dark',               // 'dark', 'light', 'neon', 'blue', 'red'
        cardDeck: 'standard',       // 'standard', 'fourcolor', 'classic', 'minimal'
        tableStyle: 'felt',         // 'felt', 'blue-felt', 'wood', 'dark'
        // Son
        sound: 'on',                // 'on', 'off'
        soundVolume: 0.5,           // 0.0 - 1.0
        // Comportement
        animationSpeed: 'normal',   // 'fast', 'normal', 'slow'
        autoAction: 'never',        // 'never', 'check_fold'
        showHistory: 'all',         // 'all', 'mine', 'none'
        chatTimestamps: true,       // boolean
        // Table spécifique
        showStacksInBB: false,      // boolean
        actionTimer: 30,            // secondes
        // Réseau
        networkQuality: 'auto',     // 'auto', 'low', 'high'
        reconnectOnDrop: true,      // boolean
    chatFontSize: 'medium',
    chatNotifications: true,
    soundOnWin: true,
    reconnectDelay: 5,
    historyMaxEntries: 50,
    email: '',

    };

    let _settings = { ...DEFAULTS };

    // Charge les paramètres depuis localStorage
    function load() {
        try {
            const stored = localStorage.getItem(STORAGE_KEY);
            if (stored) {
                const parsed = JSON.parse(stored);
                _settings = { ...DEFAULTS, ...parsed };
            } else {
                _settings = { ...DEFAULTS };
            }
        } catch (e) {
            console.warn('Failed to load settings:', e);
            _settings = { ...DEFAULTS };
        }
        return _settings;
    }

    // Sauvegarde les paramètres actuels dans localStorage
    function save(settings = null) {
        if (settings) {
            _settings = { ..._settings, ...settings };
        }
        try {
            localStorage.setItem(STORAGE_KEY, JSON.stringify(_settings));
        } catch (e) {
            console.warn('Failed to save settings:', e);
        }
        return _settings;
    }

    // Retourne la valeur d'un paramètre
    function get(key) {
        if (key === undefined) return _settings;
        return _settings[key];
    }

    // Met à jour un paramètre et sauvegarde
    function set(key, value) {
        _settings[key] = value;
        save();
        return _settings;
    }

    // Réinitialise aux valeurs par défaut
    function reset() {
        _settings = { ...DEFAULTS };
        save();
        return _settings;
    }

    // Applique les paramètres visuels (thème, cartes, style table) au DOM
    function applyVisual() {
        const { theme, cardDeck, tableStyle, animationSpeed } = _settings;

        // Thème
        if (typeof ThemeManager !== 'undefined') {
            ThemeManager.setTheme(theme);
        } else {
            document.documentElement.setAttribute('data-theme', theme);
        }

        // Jeu de cartes
        if (typeof CardsModule !== 'undefined') {
            CardsModule.setDeck(cardDeck);
        }

        // Style de table
        document.body.setAttribute('data-table-style', tableStyle);

        // Vitesse d'animation
        document.body.setAttribute('data-animation-speed', animationSpeed);
    }

    // Applique les paramètres sonores
    function applySound() {
        if (typeof SoundManager !== 'undefined') {
            if (_settings.sound === 'off') {
                SoundManager.disable();
            } else {
                SoundManager.enable();
            }
            SoundManager.setVolume(_settings.soundVolume);
        }
    }

    // Applique tous les paramètres (visuels, son, comportement)
    function applyAll() {
        applyVisual();
        applySound();
        // Autres paramètres comportementaux stockés localement pour d'autres scripts
        localStorage.setItem('poker_auto_action', _settings.autoAction);
        localStorage.setItem('poker_chat_timestamps', _settings.chatTimestamps ? 'true' : 'false');
        localStorage.setItem('poker_show_history', _settings.showHistory);
        localStorage.setItem('poker_action_timer', _settings.actionTimer);
        if (_settings.showStacksInBB !== undefined) {
            localStorage.setItem('poker_table_prefs', JSON.stringify({ showStacksInBB: _settings.showStacksInBB }));
        }
    }

    // Synchronise les éléments de formulaire (selects, checkbox) avec les paramètres
    function bindUI() {
        // Sélecteurs d'apparence
        const themeSelect = document.getElementById('themeSelect');
        if (themeSelect) {
            themeSelect.value = _settings.theme;
            themeSelect.addEventListener('change', (e) => {
                set('theme', e.target.value);
                applyVisual();
            });
        }
        const cardDeckSelect = document.getElementById('cardDeckSelect');
        if (cardDeckSelect) {
            cardDeckSelect.value = _settings.cardDeck;
            cardDeckSelect.addEventListener('change', (e) => {
                set('cardDeck', e.target.value);
                applyVisual();
            });
        }
        const tableStyleSelect = document.getElementById('tableStyleSelect');
        if (tableStyleSelect) {
            tableStyleSelect.value = _settings.tableStyle;
            tableStyleSelect.addEventListener('change', (e) => {
                set('tableStyle', e.target.value);
                applyVisual();
            });
        }

        // Son
        const soundSetting = document.getElementById('soundSetting');
        if (soundSetting) {
            soundSetting.value = _settings.sound;
            soundSetting.addEventListener('change', (e) => {
                set('sound', e.target.value);
                applySound();
            });
        }
        const soundVolume = document.getElementById('soundVolume');
        if (soundVolume) {
            soundVolume.value = _settings.soundVolume;
            soundVolume.addEventListener('input', (e) => {
                set('soundVolume', parseFloat(e.target.value));
                applySound();
            });
        }

        // Comportement
        const animationSpeed = document.getElementById('animationSpeed');
        if (animationSpeed) {
            animationSpeed.value = _settings.animationSpeed;
            animationSpeed.addEventListener('change', (e) => {
                set('animationSpeed', e.target.value);
                document.body.setAttribute('data-animation-speed', e.target.value);
            });
        }
        const autoAction = document.getElementById('autoAction');
        if (autoAction) {
            autoAction.value = _settings.autoAction;
            autoAction.addEventListener('change', (e) => {
                set('autoAction', e.target.value);
                localStorage.setItem('poker_auto_action', e.target.value);
            });
        }
        const showHistory = document.getElementById('showHistory');
        if (showHistory) {
            showHistory.value = _settings.showHistory;
            showHistory.addEventListener('change', (e) => {
                set('showHistory', e.target.value);
                localStorage.setItem('poker_show_history', e.target.value);
            });
        }
        const chatTimestamps = document.getElementById('chatTimestamps');
        if (chatTimestamps) {
            chatTimestamps.checked = _settings.chatTimestamps;
            chatTimestamps.addEventListener('change', (e) => {
                set('chatTimestamps', e.target.checked);
                localStorage.setItem('poker_chat_timestamps', e.target.checked ? 'true' : 'false');
            });
        }
        const actionTimer = document.getElementById('actionTimer');
        if (actionTimer) {
            actionTimer.value = _settings.actionTimer;
            actionTimer.addEventListener('change', (e) => {
                set('actionTimer', parseInt(e.target.value));
                localStorage.setItem('poker_action_timer', e.target.value);
            });
        }

        // Table spécifique
        const stackDisplayToggle = document.getElementById('stackDisplayToggle');
        if (stackDisplayToggle) {
            stackDisplayToggle.checked = _settings.showStacksInBB;
            stackDisplayToggle.addEventListener('change', (e) => {
                set('showStacksInBB', e.target.checked);
                localStorage.setItem('poker_table_prefs', JSON.stringify({ showStacksInBB: e.target.checked }));
            });
        }

        // Réseau
        const networkQuality = document.getElementById('networkQuality');
        if (networkQuality) {
            networkQuality.value = _settings.networkQuality;
            networkQuality.addEventListener('change', (e) => {
                set('networkQuality', e.target.value);
            });
        }
        const reconnectOnDrop = document.getElementById('reconnectOnDrop');
        if (reconnectOnDrop) {
            reconnectOnDrop.checked = _settings.reconnectOnDrop;
            reconnectOnDrop.addEventListener('change', (e) => {
                set('reconnectOnDrop', e.target.checked);
            });
        }
    }

    // Initialisation : charge, applique et lie les éléments UI si présents
    function init() {
        load();
        applyAll();
        bindUI();
        return _settings;
    }

    return {
        load,
        save,
        get,
        set,
        reset,
        applyVisual,
        applySound,
        applyAll,
        bindUI,
        init,
        defaults: DEFAULTS,
    };
})();

window.SettingsManager = SettingsManager;

// Initialisation automatique après chargement du DOM
document.addEventListener('DOMContentLoaded', () => {
    SettingsManager.load();
});
